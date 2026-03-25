import re, hashlib, secrets, urllib.parse, logging
from pathlib import Path
import fitz  # PyMuPDF
import win32com.client

MAX_STEM_LEN = 40
IMAGE_RESOLUTION_SCALE = 2.0

_log = logging.getLogger(__name__)
logging.getLogger("fitz").setLevel(logging.ERROR)
logging.getLogger("PIL").setLevel(logging.WARNING)

def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-") or "file"

def short_stem(original_stem: str) -> str:
    base = slugify(original_stem)[:MAX_STEM_LEN]
    h = secrets.token_hex(6)
    return f"{base}-{h}"

def truncate_path(path, max_length=240):
    p = Path(path)
    s = str(p)
    if len(s) <= max_length:
        return p
    h = hashlib.md5(s.encode()).hexdigest()
    new_name = (p.stem[:50] + "_" + h + p.suffix)
    return p.parent / new_name

def try_read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return urllib.parse.unquote(path.read_text(encoding=enc, errors="ignore"))
        except Exception:
            continue
    return ""

def is_pdf_text_based(fpath: Path) -> bool:
    try:
        with fitz.open(fpath) as doc:
            for page in doc:
                if page.get_text().strip():
                    return True
            return False
    except Exception:
        return False

def strip_image_markdown(md_text: str) -> str:
    md_text = re.sub(r'!\[[^\]]*\]\([^\)]+\)', '', md_text)
    md_text = re.sub(r'<img\b[^>]*>', '', md_text, flags=re.IGNORECASE)
    md_text = re.sub(r'\n{3,}', '\n\n', md_text)
    return md_text.strip()

# --- COM helpers (Windows + Office)
def _make_word_invisible(word):
    try:
        word.Visible = False
        word.DisplayAlerts = 0
        word.ScreenUpdating = False
    except Exception:
        pass

def _make_powerpoint_invisible(ppt):
    try:
        ppt.Visible = 0  # 0=Hidden
    except Exception:
        pass

def convert_doc_to_docx(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() != ".doc":
        return src if src.suffix.lower() == ".docx" else src
    dst = out_dir / (src.stem + ".docx")
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    word = win32com.client.Dispatch("Word.Application")
    _make_word_invisible(word)
    try:
        doc = word.Documents.Open(str(src), ReadOnly=True)
        doc.SaveAs(str(dst), FileFormat=16)  # DOCX
        doc.Close(False)
        if not dst.exists() or dst.stat().st_size == 0:
            raise RuntimeError("DOCX non généré")
        return dst
    finally:
        word.Quit()

def convert_ppt_to_pptx(src: Path, out_dir: Path) -> Path:

    out_dir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() != ".ppt":
        return src if src.suffix.lower() == ".pptx" else src
    dst = out_dir / (src.stem + ".pptx")
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    ppt = win32com.client.Dispatch("PowerPoint.Application")
    _make_powerpoint_invisible(ppt)
    try:
        pres = ppt.Presentations.Open(str(src), WithWindow=False)
        pres.SaveAs(str(dst), 24)  # ppSaveAsOpenXMLPresentation
        pres.Close()
        if not dst.exists() or dst.stat().st_size == 0:
            raise RuntimeError("PPTX non généré")
        return dst
    finally:
        ppt.Quit()

def docx_to_pdf(src_docx: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / (src_docx.stem + ".pdf")
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        return pdf_path
    word = win32com.client.Dispatch("Word.Application")
    _make_word_invisible(word)
    try:
        doc = word.Documents.Open(str(src_docx), ReadOnly=True)
        try:
            doc.ExportAsFixedFormat(OutputFileName=str(pdf_path), ExportFormat=17)
        except Exception:
            doc.SaveAs(str(pdf_path), FileFormat=17)
        doc.Close(False)
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            raise RuntimeError("PDF non généré depuis DOCX")
        return pdf_path
    finally:
        word.Quit()

def pptx_to_pdf(src_pptx: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / (src_pptx.stem + ".pdf")
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        return pdf_path
    ppt = win32com.client.Dispatch("PowerPoint.Application")
    _make_powerpoint_invisible(ppt)
    try:
        pres = ppt.Presentations.Open(str(src_pptx), WithWindow=False)
        pres.SaveAs(str(pdf_path), 32)  # PDF
        pres.Close()
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            raise RuntimeError("PDF non généré depuis PPTX")
        return pdf_path
    finally:
        ppt.Quit()

def is_word_installed():
    try:
        win32com.client.Dispatch("Word.Application")
        return True
    except Exception:
        return False