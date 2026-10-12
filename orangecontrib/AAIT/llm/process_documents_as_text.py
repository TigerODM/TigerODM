import os
import re
from pathlib import Path

from Orange.data import StringVariable


# Number of bytes inspected to decide whether a file is binary
BINARY_SNIFF_SIZE = 8192
# Above this proportion of control bytes, the file is considered binary
# (real text has ~0 %, random binary data ~10 %)
BINARY_CONTROL_RATIO = 0.05

# Signatures of common binary formats (always rejected, even if they look like text)
BINARY_SIGNATURES = (
    b"%PDF", b"PK\x03\x04", b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"BM",
    b"\x7fELF", b"MZ", b"\xd0\xcf\x11\xe0", b"Rar!", b"7z\xbc\xaf", b"\x1f\x8b",
    b"SQLite format 3",
)

# Control bytes that are normal in a text file: \t \n \r \f \b ESC
_TEXT_CONTROLS = {0x08, 0x09, 0x0A, 0x0C, 0x0D, 0x1B}


def _detect_bomless_utf16(head: bytes):
    """Detect UTF-16 without BOM: one byte out of two is NUL for ASCII content."""
    if len(head) < 4:
        return None
    # Typical XML start in UTF-16
    if head.startswith(b"<\x00"):
        return "utf-16-le"
    if head.startswith(b"\x00<"):
        return "utf-16-be"
    if len(head) < 32:  # too short for a reliable statistic
        return None
    even = head[0::2]
    odd = head[1::2]
    even_nul = even.count(0) / len(even)
    odd_nul = odd.count(0) / len(odd)
    if odd_nul > 0.4 and even_nul < 0.05:
        return "utf-16-le"
    if even_nul > 0.4 and odd_nul < 0.05:
        return "utf-16-be"
    return None


def is_binary(raw: bytes) -> bool:
    """
    Tolerant binary detection (closer to what a text editor accepts):
    - known binary signatures (pdf, zip/docx, images, exe...) -> binary
    - otherwise binary only if a large share of the first bytes are control bytes.
    A few stray NUL bytes (padding, corrupted export...) no longer reject a text file.
    """
    # Trailing NUL padding (frequent in some exports) is ignored for the analysis
    head = raw.rstrip(b"\x00")[:BINARY_SNIFF_SIZE]
    if not head:
        return False
    if head.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):  # BOM -> text
        return False
    if _detect_bomless_utf16(head):
        return False
    if head.startswith(BINARY_SIGNATURES):
        return True
    control = sum(1 for b in head if b < 0x20 and b not in _TEXT_CONTROLS)
    return control / len(head) > BINARY_CONTROL_RATIO


def decode_text(raw: bytes) -> str:
    """Decode bytes into text, trying the most likely encodings first."""
    # 1) BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return raw.decode("utf-32", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")

    # 2) UTF-16 without BOM
    utf16 = _detect_bomless_utf16(raw[:BINARY_SNIFF_SIZE])
    if utf16:
        return raw.decode(utf16, errors="replace").replace("\x00", "")

    # 3) Encoding declared in an XML prolog (xml, cihx, xsd, svg...)
    candidates = []
    match = re.match(rb'\s*<\?xml[^>]*encoding=["\']([A-Za-z0-9_\-\.]+)["\']', raw[:200])
    if match:
        candidates.append(match.group(1).decode("ascii"))

    # 4) Usual encodings (latin-1 never fails, so it is the last resort)
    candidates += ["utf-8", "cp1252", "latin-1"]
    for encoding in candidates:
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    # Stray NUL bytes are useless in text and break some downstream tools
    return text.replace("\x00", "")


def extract_raw_text(filepath: str) -> str:
    """Read any file as plain text. Returns an ERROR message if the file is binary or unreadable."""
    try:
        with open(filepath, "rb") as f:
            raw = f.read()
    except Exception as e:
        return f"ERROR: Extraction Error ({e})"
    if is_binary(raw):
        return "ERROR: Binary file, it cannot be loaded as plain text."
    return decode_text(raw)


def load_documents_as_text(table, extractors=None, progress_callback=None, argself=None):
    """
    Load every file listed in the "path" column as raw text and add the meta columns
    "name" and "content" (same output as process_documents.load_documents_in_table).

    :param table: Orange.data.Table containing file paths in a column named "path".
    :param extractors: optional dict {extension: function(filepath) -> str}. Files whose
                       extension is in this dict are read with the given function instead
                       of raw text (e.g. {".pdf": extract_text}). Extensions are lowercase,
                       with the dot.
    :return: Orange.data.Table with added meta columns "name" and "content".
    """
    extractors = extractors or {}
    data = table.copy()
    names, texts = [], []
    total = len(data)
    for i, row in enumerate(data):
        filepath = row["path"].value
        names.append(Path(filepath).name)
        extension = os.path.splitext(filepath)[1].lower()
        extractor = extractors.get(extension, extract_raw_text)
        texts.append(extractor(filepath))
        if progress_callback is not None:
            progress_callback(float(100 * (i + 1) / total))
        if argself is not None and getattr(argself, "stop", False):
            break
    # If stopped early, pad so that the columns keep the table length
    names += [""] * (total - len(names))
    texts += [""] * (total - len(texts))

    data = data.add_column(variable=StringVariable("name"), data=names, to_metas=True)
    data = data.add_column(variable=StringVariable("content"), data=texts, to_metas=True)
    return data
