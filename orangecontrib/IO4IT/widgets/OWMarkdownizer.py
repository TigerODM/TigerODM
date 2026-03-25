import os
import sys
import logging
import urllib.parse
import datetime
import time
import re
import hashlib
import secrets
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed


import fitz  # PyMuPDF

from AnyQt.QtCore import QThread, pyqtSignal
from AnyQt.QtWidgets import QApplication, QLabel, QSpinBox, QTextEdit, QPushButton

from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Domain, StringVariable, Table

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode

# ---- fix torch (Orange contrib)
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.AAIT.utils.import_uic import uic


# ---- Logging
logging.getLogger("fitz").setLevel(logging.ERROR)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)

IMAGE_RESOLUTION_SCALE = 2.0

# ======================
#       UTILS
# ======================
MAX_STEM_LEN = 40  # pour chemins courts côté .md
PROCESSED_DIR_NAME = "fichiers_traites"   # conversions intermédiaires

def _make_word_invisible(word):
    try:
        word.Visible = False
        word.DisplayAlerts = 0  # wdAlertsNone
        word.ScreenUpdating = False
    except Exception:
        pass

def _make_powerpoint_invisible(ppt):
    try:
        ppt.Visible = 0  # 0=Hidden, 1=Normal
    except Exception:
        pass

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

def build_out_md(file_path: Path, out_dir: Path) -> Path:
    """Nom .md court pour éviter des chemins trop longs côté Windows."""
    stem = short_stem(file_path.stem)
    out_md = out_dir / f"{stem}.md"
    return truncate_path(out_md)

def try_read_md(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return urllib.parse.unquote(path.read_text(encoding=enc))
        except Exception:
            continue
    return ""

def is_pdf_text_based(fpath: Path) -> bool:
    try:
        with fitz.open(fpath) as doc:
            return any(page.get_text().strip() for page in doc)
    except Exception:
        return False

def strip_image_markdown(md_text: str) -> str:
    """Supprime les images markdown/HTML du contenu (au cas où un fallback Office direct est utilisé)."""
    md_text = re.sub(r'!\[[^\]]*\]\([^\)]+\)', '', md_text)
    md_text = re.sub(r'<img\b[^>]*>', '', md_text, flags=re.IGNORECASE)
    md_text = re.sub(r'\n{3,}', '\n\n', md_text)
    return md_text.strip()

# ======================
#  CONVERSIONS Office (COM Word/PowerPoint uniquement)
# ======================

def convert_doc_to_docx(src, out_dir: Path):
    """Convertit exclusivement via COM Word (invisible)."""
    import win32com.client
    fpath = Path(src)
    out_dir.mkdir(parents=True, exist_ok=True)
    if fpath.suffix.lower() != ".doc":
        return fpath if fpath.suffix.lower() == ".docx" else fpath
    dst = out_dir / (fpath.stem + ".docx")
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    try:
        word = win32com.client.Dispatch("Word.Application")
        _make_word_invisible(word)
        try:
            doc = word.Documents.Open(str(fpath), ReadOnly=True)
            doc.SaveAs(str(dst), FileFormat=16)  # 16 = wdFormatDocumentDefault (DOCX)
            doc.Close(False)
        finally:
            word.Quit()
        if dst.exists() and dst.stat().st_size > 0:
            return dst
        raise RuntimeError("COM Word: .docx non généré")
    except Exception as e2:
        raise RuntimeError(f"Échec .doc→.docx via COM Word: {e2}")

def convert_ppt_to_pdf(fpath, out_dir: Path):
    import win32com.client
    fpath = Path(fpath)
    out_dir.mkdir(parents=True, exist_ok=True)
    if fpath.suffix.lower() != ".ppt":
        return fpath
    pdf_path = out_dir / (fpath.stem + ".pdf")
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        return pdf_path
    try:
        powerpoint = win32com.client.Dispatch("PowerPoint.Application")
        _make_powerpoint_invisible(powerpoint)
        presentation = powerpoint.Presentations.Open(str(fpath), WithWindow=False)
        presentation.SaveAs(str(pdf_path), 32)  # ppSaveAsPDF
        presentation.Close()
        powerpoint.Quit()
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            raise RuntimeError("PDF non généré")
        return pdf_path
    except Exception as e:
        raise RuntimeError(f"Erreur conversion .ppt → .pdf : {e}")

def pptx_to_pdf(src_pptx: Path, out_dir: Path) -> Path:
    import win32com.client
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
            raise RuntimeError("COM PowerPoint: PDF non généré")
        return pdf_path
    finally:
        ppt.Quit()

def docx_to_pdf(src_docx: Path, out_dir: Path) -> Path:
    """DOCX → PDF via COM Word (invisible)."""
    import win32com.client
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / (src_docx.stem + ".pdf")
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        return pdf_path
    word = win32com.client.Dispatch("Word.Application")
    _make_word_invisible(word)
    try:
        doc = word.Documents.Open(str(src_docx), ReadOnly=True)
        try:
            doc.ExportAsFixedFormat(OutputFileName=str(pdf_path), ExportFormat=17)  # 17 = wdExportFormatPDF
        except Exception:
            doc.SaveAs(str(pdf_path), FileFormat=17)  # 17 = wdFormatPDF
        doc.Close(False)
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            raise RuntimeError("COM Word: PDF non généré depuis DOCX.")
        return pdf_path
    finally:
        word.Quit()

# ======================
#  NORMALISATION
# ======================

def normalize_input_file(src: Path, logs: list, processed_dir: Path) -> Path:
    """
    Retourne un chemin vers un fichier 'normalisé' (dans processed_dir si conversion).
    Cibles autorisées: .pdf | .docx | .pptx
    - .doc  → converti en processed_dir/<nom>.docx (COM Word)
    - .ppt  → converti en processed_dir/<nom>.pdf
    - .pdf/.docx/.pptx : on garde l'original
    """
    ext = src.suffix.lower()
    if ext == ".doc":
        try:
            dst = convert_doc_to_docx(src, processed_dir)
            logs.append(f"[CONVERT] ✅ .doc→.docx (COM Word) : {src.name} -> {dst.name}")
            return dst
        except Exception as e:
            logs.append(f"[ERROR] ❌ Échec .doc→.docx (COM Word) : {e}")
            raise
    if ext == ".ppt":
        try:
            dst = convert_ppt_to_pdf(src, processed_dir)
            logs.append(f"[CONVERT] ✅ .ppt→.pdf : {src.name} -> {dst.name}")
            return dst
        except Exception as e:
            logs.append(f"[ERROR] ❌ Échec .ppt→.pdf : {e}")
            raise
    if ext in {".pdf", ".docx", ".pptx"}:
        return src
    logs.append(f"[SKIP] ⏭️ Format non supporté: {src.name}")
    raise RuntimeError("Format non supporté")


# ======================
#  PDF → MD (TEXTE SEUL, sans images)
# ======================

def save_md_from_pdf_textonly(pdf_path: Path, out_md: Path, logs: list):
    opts = PdfPipelineOptions()
    opts.generate_page_images = False
    opts.generate_picture_images = False
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    conv_res = conv.convert(pdf_path)
    conv_res.document.save_as_markdown(out_md, image_mode=ImageRefMode.REFERENCED)

# ======================
#  WORKER (produit .md, .mds ; le .mde est géré dans le thread)
# ======================

def process_file_worker(file_path_str, base_input_dir_str, base_output_dir_str, processed_dir_str):
    logs = []
    start_time = time.time()
    start_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    src = Path(file_path_str)
    base_input_dir = Path(base_input_dir_str)        # dossier d'entrée
    base_output_dir = Path(base_output_dir_str)      # .../parent/a_md/<nom_dossier_entree>
    processed_dir = Path(processed_dir_str)          # .../parent/a_md/<nom_dossier_entree>/fichiers_traites

    # Recréation de l'arborescence sous a_md/<nom_dossier_entree>
    try:
        rel_parent = src.parent.relative_to(base_input_dir)
    except ValueError:
        rel_parent = Path("")
    out_dir = base_output_dir / rel_parent
    out_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    # 0) Normalisation
    try:
        file_path = normalize_input_file(src, logs, processed_dir)
    except Exception as e:
        logs.append(f"[ERROR] ❌ Échec conversion : {e}")
        return [
            str(src.parent), str(out_dir), src.name, "",
            [f"[{start_str}] {msg}" for msg in logs],
            {
                "name": src.name,
                "content": "",
                "input_dir": str(src.parent),
                "status": "non converti",
                "duration_sec": round(time.time() - start_time, 2),
                "timestamp": start_str,
                "type conversion": "échec conversion"
            }
        ]

    # 1) Prépare sorties
    out_md = build_out_md(file_path, out_dir)
    out_mds = out_dir / (out_md.stem + ".mds")

    if out_md.exists():
        duration = time.time() - start_time
        content = try_read_md(out_md)
        logs.append(f"[SKIP] ✅ Déjà converti : {file_path.name} ({duration:.2f} sec)")
        return [
            str(file_path.parent), str(out_dir), file_path.name, content,
            [f"[{start_str}] {msg}" for msg in logs],
            {
                "name": file_path.name,
                "content": content,
                "input_dir": str(file_path.parent),
                "status": "ok",
                "duration_sec": round(duration, 2),
                "timestamp": start_str,
                "type conversion": "deja converti"
            }
        ]

    out_mds.touch(exist_ok=True)

    # 2) Conversion TEXTE SEUL
    type_conv = "text"
    statut = "ok"
    content = ""

    try:
        logs.append(f"[DOC] 📄 Traitement : {file_path.name}")
        ext = file_path.suffix.lower()

        if ext == ".pdf":
            save_md_from_pdf_textonly(file_path, out_md, logs)
            content = try_read_md(out_md)

        elif ext == ".docx":
            try:
                logs.append("[INFO] DOCX → conversion directe en Markdown (texte seul)")
                conv_res = DocumentConverter().convert(file_path)
                conv_res.document.save_as_markdown(out_md, image_mode=ImageRefMode.REFERENCED)
                content = try_read_md(out_md)
                content = strip_image_markdown(content)
                weak = len(content.strip()) < 50 or len(re.findall(r"[A-Za-zÀ-ÿ0-9]", content)) < 20
                if weak:
                    logs.append("[INFO] DOCX→MD vide/faible ; fallback COM Word → PDF puis extraction")
                    pdf = docx_to_pdf(file_path, processed_dir)
                    save_md_from_pdf_textonly(pdf, out_md, logs)
                    content = try_read_md(out_md)
                else:
                    out_md.write_text(content, encoding="utf-8")
            except Exception as e_docx:
                logs.append(f"[WARN] DOCX→MD KO: {e_docx} ; fallback COM Word → PDF")
                pdf = docx_to_pdf(file_path, processed_dir)
                save_md_from_pdf_textonly(pdf, out_md, logs)
                content = try_read_md(out_md)

        elif ext == ".pptx":
            try:
                pdf = pptx_to_pdf(file_path, processed_dir)
                save_md_from_pdf_textonly(pdf, out_md, logs)
                content = try_read_md(out_md)
            except Exception as e_pp:
                raise RuntimeError(f"PPTX→PDF KO: {e_pp}")

        else:
            raise RuntimeError(f"Format inattendu après normalisation: {ext}")

        logs.append(f"[DOC] ✅ Conversion OK : {file_path.name}")

    except Exception as e:
        content = f"[Erreur conversion] {e}"
        logs.append(f"[ERROR] ❌ Conversion: {file_path.name} — {e}")
        type_conv = "error"
        statut = "nok"

    finally:
        try:
            if out_mds.exists():
                out_mds.unlink()
        except Exception:
            pass

    if content and not out_md.exists():
        out_md.write_text(content, encoding='utf-8')

    duration = time.time() - start_time
    logs.append(f"[END] ✅ Fin traitement {file_path.name} en {duration:.2f} secondes")

    return [
        str(file_path.parent), str(out_dir), file_path.name, content,
        [f"[{start_str}] {msg}" for msg in logs],
        {
            "name": file_path.name,
            "content": content,
            "input_dir": str(file_path.parent),
            "status": statut,
            "duration_sec": round(duration, 2),
            "timestamp": start_str,
            "type conversion": type_conv
        }
    ]

# ======================
#  THREAD (écrit .mde)
# ======================
class MarkdownConversionThread(QThread):
    result = pyqtSignal(list)
    progress = pyqtSignal(float)
    finish = pyqtSignal()
    log = pyqtSignal(str)

    def __init__(self, input_dir, max_workers, parent=None):
        super().__init__(parent)
        self.input_dir = Path(input_dir)
        # >>> a_md au MÊME NIVEAU que le dossier d'entrée (au sein du dossier parent)
        self.output_root = self.input_dir / "a_md"
        # Sous-dossier racine = nom du dossier d'entrée
        self.base_output_dir = self.output_root
        # Conversions intermédiaires dans a_md/<nom_dossier_entree>/fichiers_traites
        self.processed_dir = self.base_output_dir / PROCESSED_DIR_NAME
        self.max_workers = max_workers

    def run(self):
        os.makedirs(self.base_output_dir, exist_ok=True)
        os.makedirs(self.processed_dir, exist_ok=True)
        global_start = time.time()
        self.log.emit(f"[THREAD] 📁 Dossier d'entrée : {self.input_dir}")
        self.log.emit(f"[THREAD] 📦 Dossier de sortie : {self.base_output_dir}")
        results = []

        # Parcours récursif
        patterns = ["*.pdf", "*.docx", "*.doc", "*.pptx", "*.ppt"]
        files = []
        for patt in patterns:
            files.extend(self.input_dir.rglob(patt))
        files = sorted(files)

        if not files:
            self.log.emit("⚠️ Aucun fichier détecté (récursif).")
            self.result.emit([[str(self.input_dir), str(self.base_output_dir), "", "Aucun fichier détecté"]])
            self.finish.emit()
            return

        log_file_path = self.base_output_dir / "log.txt"

        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    process_file_worker,
                    str(f), str(self.input_dir), str(self.base_output_dir), str(self.processed_dir)
                ): f for f in files
            }
            total = len(futures)
            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                if result is not None:
                    # logs UI + fichier
                    logs = result[4]
                    for line in logs:
                        self.log.emit(line)
                    results.append(result)

                    try:
                        with open(log_file_path, "a", encoding="utf-8") as f:
                            for line in logs:
                                f.write(line + "\n")
                    except Exception as e:
                        self.log.emit(f"[ERROR] ❌ Erreur écriture log : {e}")

                    # .mde à côté du .md, dans le SOUS-DOSSIER correspondant
                    try:
                        src_name = Path(result[2])
                        out_subdir = Path(result[1])  # sous-dossier précis
                        out_subdir.mkdir(parents=True, exist_ok=True)
                        output_path_ok_mde = out_subdir / (src_name.stem + ".mde")
                        data = result[5]
                        with open(output_path_ok_mde, 'w', encoding='utf-8') as file:
                            file.write(str(data))
                    except Exception as e:
                        self.log.emit(f"[ERROR] ❌ Échec écriture MDE : {e}")

                self.progress.emit(i / total * 100)

        total_duration = time.time() - global_start
        self.log.emit(f"⏱️ Temps total de traitement : {total_duration:.2f} secondes")
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(f"\n[GLOBAL] ⏱️ Temps total de traitement : {total_duration:.2f} secondes\n")
        self.result.emit(results)
        self.finish.emit()

class FileProcessorApp(widget.OWWidget):
    name = "Markdownizer"
    description = "[deprecated]Convert PDFs, DOCX, PPTX to Markdown (ignore image)"
    icon = "icons/dep_md_old.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
       icon = "icons_dev/dep_md_old.png"
    want_control_area = False
    priority = 1001
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmarkdownizer.ui")

    class Inputs:
        data = Input("Data", Table)

    class Outputs:
        data = Output("Markdown Data Table", Table)
        data2 = Output("Markdow Directory Treated", Table)

    def __init__(self):
        super().__init__()
        self.data = None
        self.thread = None
        self.input_dir = None

        uic.loadUi(self.gui, self)

        self.cpu_label = self.findChild(QLabel, "labelCpuInfo")
        self.spin_box = self.findChild(QSpinBox, "spinBoxThreads")
        self.ok_button = self.findChild(QPushButton, "pushButtonOk")
        self.log_box = self.findChild(QTextEdit, "textEditLog")

        self.cpu_label.setText(f"🖥️ CPU disponibles : {os.cpu_count() or 'inconnu'}")
        self.ok_button.clicked.connect(self.restart_processing)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        self.error("")
        if not in_data:
            return
        try:
            input_dir_var = in_data.domain["input_dir"]
            if not isinstance(input_dir_var, StringVariable):
                raise ValueError
            self.input_dir = in_data.get_column("input_dir")[0]
        except (KeyError, ValueError):
            self.error('"input_dir" column is required and must be Text')
            return
        self.start_thread()

    def start_thread(self):
        self.progressBarInit()
        if self.thread:
            self.thread.quit()

        self.log_box.clear()
        self.thread = MarkdownConversionThread(self.input_dir, self.spin_box.value())
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.log.connect(self.append_log)
        self.thread.start()

    def restart_processing(self):
        if not self.data or not self.input_dir:
            self.append_log("[UI] ❌ Données manquantes.")
            return
        self.append_log("[UI] 🔁 Reprise du traitement avec nouveau nombre de threads...")
        self.start_thread()

    def append_log(self, message):
        self.log_box.append(message)

    def handle_progress(self, value):
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            domain = Domain([], metas=[
                StringVariable('input_dir'),
                StringVariable('output_dir'),
                StringVariable('name'),
                StringVariable('content'),
                StringVariable('status'),
                StringVariable('duration_sec'),
                StringVariable('timestamp'),
                StringVariable('type conversion')
            ])
            table = Table(domain, [[] for _ in result])
            for i, meta in enumerate(result):
                if meta is None:
                    continue
                info = meta[5] if isinstance(meta[5], dict) else {}
                table.metas[i] = [
                    meta[0], meta[1], meta[2], meta[3],
                    info.get("status", ""),
                    str(info.get("duration_sec", "")),
                    info.get("timestamp", ""),
                    info.get("type conversion", "")
                ]
            self.Outputs.data.send(table)

            # Parcours récursif de tous les .md sous .../parent/a_md/<nom_dossier_entree>
            base_output_dir = Path(self.input_dir).parent / "a_md" / Path(self.input_dir).name
            markdown_list = []
            for file in base_output_dir.rglob("*.md"):
                markdown_text = file.read_text(encoding="utf-8", errors="ignore")
                markdown_list.append([str(file), markdown_text])

            domain2 = Domain([], metas=[
                StringVariable('file_name'),
                StringVariable('content_markdown')
            ])
            table2 = Table(domain2, [[] for _ in markdown_list])
            for i, meta in enumerate(markdown_list):
                table2.metas[i] = [meta[0], meta[1]]

            self.Outputs.data2.send(table2)
        except Exception as e:
            _log.error("[ERROR] Erreur lors de la génération de la table de sortie :", exc_info=True)
            self.append_log(f"[ERROR] ❌ Sortie non générée : {e}")
            self.Outputs.data.send(None)

    def handle_finish(self):
        self.append_log("✅ Conversion terminée")
        self.progressBarFinished()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget_instance = FileProcessorApp()
    widget_instance.show()
    sys.exit(app.exec() if hasattr(app, "exec") else app.exec_())
