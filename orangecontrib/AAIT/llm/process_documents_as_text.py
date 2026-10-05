import os
import re
from pathlib import Path

from Orange.data import StringVariable


# Number of bytes inspected to decide whether a file is binary
BINARY_SNIFF_SIZE = 8192


def is_binary(raw: bytes) -> bool:
    """A file is considered binary if its first bytes contain a NUL byte (except UTF-16/32 with BOM)."""
    head = raw[:BINARY_SNIFF_SIZE]
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):  # UTF-16 / UTF-32 BOM
        return False
    return b"\x00" in head


def decode_text(raw: bytes) -> str:
    """Decode bytes into text, trying the most likely encodings first."""
    # 1) BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return raw.decode("utf-32", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")

    # 2) Encoding declared in an XML prolog (xml, cihx, xsd, svg...)
    candidates = []
    match = re.match(rb'\s*<\?xml[^>]*encoding=["\']([A-Za-z0-9_\-\.]+)["\']', raw[:200])
    if match:
        candidates.append(match.group(1).decode("ascii"))

    # 3) Usual encodings (latin-1 never fails, so it is the last resort)
    candidates += ["utf-8", "cp1252", "latin-1"]
    for encoding in candidates:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


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
