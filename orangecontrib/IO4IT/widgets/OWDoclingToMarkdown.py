import os, time, sys, re
from pathlib import Path
from concurrent.futures import as_completed

from AnyQt.QtWidgets import QApplication
from AnyQt.QtCore import pyqtSignal
from Orange.widgets import widget
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Domain, StringVariable, Table, DiscreteVariable

# --- Ajouts pour l'écriture Excel ---
from openpyxl import Workbook

# --- Docling (unique lib utilisée pour la conversion) ---
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
    WordFormatOption,
)
from docling.pipeline.simple_pipeline import SimplePipeline
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
try:
    from docling.datamodel.accelerator_options import AcceleratorOptions
except ImportError:
    from docling.datamodel.pipeline_options import AcceleratorOptions

# --- Orange contrib Imports ---
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.thread_management import Thread
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import GetFromRemote
    from Orange.widgets.orangecontrib.AAIT.utils import SimpleDialogQt
else:
    from orangecontrib.AAIT.utils.thread_management import Thread
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from orangecontrib.AAIT.utils.MetManagement import GetFromRemote
    from orangecontrib.AAIT.utils import SimpleDialogQt

# Clé AAIT store des modèles Docling (layout, tableformer, RapidOcr)
DOCLING_MODELS_KEY = "Docling Models"
# Sous-dossiers attendus dans le dossier des modèles (cf. docling-tools models download)
DOCLING_MODELS_SUBDIRS = ("docling-project--docling-layout-heron", "docling-project--docling-models", "RapidOcr")
# Sous-dossier RapidOCR (nom imposé par Docling : RapidOcrModel._model_repo_folder)
RAPIDOCR_SUBDIR = "RapidOcr"


def _torch_arch_names() -> set | None:
    """Architectures torch connues du rapidocr installé (clés de arch_config.yaml).
    rapidocr choisit l'architecture d'après le NOM du fichier .pth (son stem) :
    un poids absent de cette liste ne peut pas être chargé.
    Renvoie None si le fichier est introuvable (aucun filtrage)."""
    try:
        import rapidocr
        root = Path(rapidocr.__file__).resolve().parent
        cfgs = list(root.rglob("arch_config.yaml"))
        if not cfgs:
            return None
        names = set()
        for line in cfgs[0].read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([^\s#][^:]*):", line)
            if m:
                names.add(m.group(1).strip())
        return names or None
    except Exception as e:
        print(f"[Docling] arch_config RapidOCR illisible : {e}")
        return None


def _rapidocr_version() -> str:
    try:
        from importlib.metadata import version
        return version("rapidocr")
    except Exception:
        return "?"


# Ordre de préférence des poids (chinois/multilingue, du plus récent au plus ancien)
_DET_PREFERENCE = ("PP-OCRv6_det_small", "ch_PP-OCRv5_det_mobile", "ch_PP-OCRv4_det_mobile",
                   "ch_PP-OCRv4_det_infer")
_REC_PREFERENCE = ("PP-OCRv6_rec_small", "ch_PP-OCRv5_rec_mobile", "ch_PP-OCRv4_rec_mobile",
                   "ch_PP-OCRv4_rec_infer")
# rapidocr >= 3.10 : "ch_ppocr_...", 3.8/3.9 : "ch_ptocr_..._mobile", <= 3.5 : "..._infer"
_CLS_PREFERENCE = ("ch_ppocr_mobile_v2.0_cls_mobile", "ch_ptocr_mobile_v2.0_cls_mobile",
                   "ch_ptocr_mobile_v2.0_cls_infer")


def _pick(candidates: list, preference: tuple) -> Path | None:
    by_stem = {p.stem: p for p in candidates}
    for stem in preference:
        if stem in by_stem:
            return by_stem[stem]
    # Sinon : un poids "ch_" ou sans préfixe de langue, puis n'importe lequel
    for p in candidates:
        if p.stem.startswith(("ch_", "PP-OCR")):
            return p
    return candidates[0] if candidates else None


def _pick_keys(base: Path, rec: Path) -> str | None:
    """Fichier de caractères pour la reconnaissance (torch n'en embarque pas)."""
    txts = sorted(p for p in base.rglob("*.txt") if p.is_file())
    if not txts:
        return None
    same_dir = [p for p in txts if p.parent == rec.parent]
    if len(same_dir) == 1:
        return str(same_dir[0])
    m = re.search(r"PP-OCRv(\d)", rec.stem)
    ver = m.group(1) if m else ""
    if ver == "6":
        hits = [p for p in txts if "v6" in p.name.lower()]
    else:
        hits = [p for p in txts if "keys_v1" in p.name.lower() or f"v{ver}" in p.name.lower()]
    if hits:
        return str(hits[0])
    return str(txts[0]) if len(txts) == 1 else None


def _rapidocr_model_paths(artifacts_path: str | None) -> dict:
    """Poids RapidOCR torch présents dans le store ET chargeables par le rapidocr installé.

    rapidocr (torch) déduit l'architecture du nom du fichier .pth, et les noms attendus
    par Docling varient selon les versions (ch_PP-OCRv4_det_infer / _mobile, PP-OCRv6_det_small...).
    On passe donc explicitement des fichiers réellement présents et compatibles.
    Renvoie les clés trouvées parmi det_model_path, cls_model_path, rec_model_path, rec_keys_path.
    """
    if not artifacts_path:
        return {}
    base = Path(artifacts_path) / RAPIDOCR_SUBDIR
    if not base.is_dir():
        return {}
    arch = _torch_arch_names()
    pths = sorted(p for p in base.rglob("*.pth") if p.is_file())
    if arch is not None:
        pths = [p for p in pths if p.stem in arch]
    det = _pick([p for p in pths if "_det_" in p.stem], _DET_PREFERENCE)
    cls = _pick([p for p in pths if "_cls_" in p.stem], _CLS_PREFERENCE)
    rec = _pick([p for p in pths if "_rec_" in p.stem], _REC_PREFERENCE)
    paths = {}
    if det:
        paths["det_model_path"] = str(det)
    if cls:
        paths["cls_model_path"] = str(cls)
    if rec:
        paths["rec_model_path"] = str(rec)
        keys = _pick_keys(base, rec)
        if keys:
            paths["rec_keys_path"] = keys
    return paths


def _rapidocr_incompatibility(artifacts_path: str | None) -> str:
    """Message si le store contient des poids RapidOCR que le rapidocr installé ne sait pas charger."""
    if not artifacts_path:
        return ""
    base = Path(artifacts_path) / RAPIDOCR_SUBDIR
    arch = _torch_arch_names()
    if arch is None or not base.is_dir():
        return ""
    unknown = sorted({p.stem for p in base.rglob("*.pth") if p.is_file() and p.stem not in arch})
    if unknown and not all(k in _rapidocr_model_paths(artifacts_path)
                           for k in ("det_model_path", "cls_model_path", "rec_model_path")):
        return (f"Poids RapidOCR non supportés par rapidocr {_rapidocr_version()} : "
                f"{', '.join(unknown)}. Mettez à jour docling/rapidocr ou retéléchargez les modèles.")
    return ""


def _docling_models_complete(artifacts_path: str) -> bool:
    """True si chaque sous-dossier de modèles existe et n'est pas vide,
    et si des poids RapidOCR torch (det, cls, rec) chargeables sont présents."""
    if not artifacts_path:
        return False
    for sub in DOCLING_MODELS_SUBDIRS:
        d = Path(artifacts_path) / sub
        if not d.is_dir() or not any(d.iterdir()):
            return False
    ocr = _rapidocr_model_paths(artifacts_path)
    return all(k in ocr for k in ("det_model_path", "cls_model_path", "rec_model_path"))


def _params_from_stem(stem: str, task: str, version_enum, type_enum) -> dict:
    """Paramètres RapidOCR cohérents avec le fichier choisi (version, taille).
    Utilisés notamment pour retrouver le dictionnaire de caractères de la reconnaissance."""
    m = re.search(r"PP-OCRv(\d)", stem)
    size = stem.rsplit("_", 1)[-1]
    params = {f"{task}.lang_type": "ch"}
    try:
        if m:
            params[f"{task}.ocr_version"] = version_enum(f"PP-OCRv{m.group(1)}")
        params[f"{task}.model_type"] = type_enum(size)
    except Exception:
        pass
    return params


def _build_ocr_options(force_ocr: bool, artifacts_path: str | None) -> RapidOcrOptions:
    """Options RapidOCR torch, avec chemins de poids explicites si le store en contient."""
    base_kwargs = dict(backend="torch", force_full_page_ocr=force_ocr)
    pinned = _rapidocr_model_paths(artifacts_path)
    if not pinned:
        return RapidOcrOptions(**base_kwargs)

    rapidocr_params = {}
    try:
        from rapidocr import ModelType, OCRVersion
        if "det_model_path" in pinned:
            rapidocr_params.update(_params_from_stem(Path(pinned["det_model_path"]).stem, "Det", OCRVersion, ModelType))
        if "rec_model_path" in pinned:
            rapidocr_params.update(_params_from_stem(Path(pinned["rec_model_path"]).stem, "Rec", OCRVersion, ModelType))
        rapidocr_params.update({
            "Cls.ocr_version": OCRVersion("PP-OCRv4"),
            "Cls.model_type": ModelType("mobile"),
            "Cls.lang_type": "ch",
        })
    except Exception as e:
        print(f"[Docling] paramètres RapidOCR non fixés : {e}")

    # Versions de Docling sans 'rapidocr_params' ou sans 'rec_keys_path' : repli progressif
    no_keys = {k: v for k, v in pinned.items() if k != "rec_keys_path"}
    attempts = []
    if rapidocr_params:
        attempts += [{**pinned, "rapidocr_params": rapidocr_params},
                     {**no_keys, "rapidocr_params": rapidocr_params}]
    attempts += [pinned, no_keys]
    last_err = None
    for extra in attempts:
        try:
            return RapidOcrOptions(**base_kwargs, **extra)
        except Exception as e:
            last_err = e
    print(f"[Docling] chemins RapidOCR explicites ignorés : {last_err}")
    return RapidOcrOptions(**base_kwargs)


# --------- helpers Docling ----------
def _build_converter(force_ocr: bool = False, artifacts_path: str | None = None, num_threads: int | None = None):
    """Construit le DocumentConverter.
    force_ocr=False : configuration d'origine (options PDF par défaut).
    force_ocr=True  : OCR RapidOCR forcé sur toute la page (PDF image).
    artifacts_path  : dossier local des modèles (AAIT store) -> aucun accès réseau.
    num_threads     : threads Docling (None = défaut Docling).
    """
    pdf_options = PdfPipelineOptions()
    if artifacts_path:
        pdf_options.artifacts_path = artifacts_path
    if num_threads:
        pdf_options.accelerator_options = AcceleratorOptions(num_threads=num_threads)
    # RapidOCR backend torch : onnxruntime n'est pas installé dans TigerODM
    # (et ce sont les poids "RapidOcr" fournis dans le dossier de modèles).
    # Chemins des poids passés explicitement : indépendant des noms attendus
    # par la version de docling/rapidocr installée.
    pdf_options.ocr_options = _build_ocr_options(force_ocr, artifacts_path)
    if force_ocr:
        pdf_options.do_ocr = True
    pdf_format = PdfFormatOption(
        pipeline_cls=StandardPdfPipeline,
        backend=PyPdfiumDocumentBackend,
        pipeline_options=pdf_options,
    )

    # Docling minimal config (inspiré du snippet)
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.PPTX],
        format_options={
            InputFormat.PDF: pdf_format,
            InputFormat.DOCX: WordFormatOption(
                pipeline_cls=SimplePipeline
            ),
            # PPTX: pas d'option spécifique; géré par défaut
        },
    )


def _has_text(md: str, min_chars: int = 20) -> bool:
    """True si le Markdown contient du vrai texte (hors commentaires <!-- image -->)."""
    cleaned = re.sub(r"<!--.*?-->", "", md, flags=re.DOTALL)
    return sum(c.isalnum() for c in cleaned) >= min_chars


# --------- worker stateless : convertit 1 fichier avec Docling ----------
def _convert_one_file(file_path_str: str, artifacts_path: str | None = None):
    """Convertit un fichier (PDF/DOCX/PPTX) en Markdown via Docling.
    Écrit <parent>/conversion_markdown/<stem>.md et renvoie
    [input_path, output_md, status, duration_sec, message].
    Pensé pour être appelé soit directement, soit via ProcessPoolExecutor.
    """
    t0 = time.time()
    src = Path(file_path_str)
    out_dir = src.parent / "conversion_markdown"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / f"{src.stem}.md"
    out_md_str = str(out_md) # Valeur par défaut, sera modifiée si "nok" pour clarité

    # Si déjà converti : on ne refait pas
    if out_md.exists():
        status = "ok"
        message = "existant: deja converti"
        duration = time.time() - t0
        return [str(src), out_md_str, status, f"{duration:.2f}", message]

    try:
        # 1er passage : comportement d'origine
        doc = _build_converter(artifacts_path=artifacts_path).convert(str(src)).document
        md = doc.export_to_markdown()
        message = ""

        # Repli : pages PDF sans texte exploitable (pages image) -> OCR pleine page.
        # Décidé page par page : un PDF peut mêler pages natives et pages scannées.
        if src.suffix.lower() == ".pdf":
            pages = sorted(doc.pages)
            page_md = {n: doc.export_to_markdown(page_no=n) for n in pages}
            empty = [n for n in pages if not _has_text(page_md[n])]
            if not pages or len(empty) == len(pages):
                # Aucune page avec texte : comportement d'origine (OCR pleine page sur tout le PDF)
                if not _has_text(md):
                    doc = _build_converter(force_ocr=True, artifacts_path=artifacts_path).convert(str(src)).document
                    md = doc.export_to_markdown()
                    message = "ocr pleine page (pdf sans texte natif)"
            elif empty:
                # Seules certaines pages sont vides : OCR pleine page sur ces pages uniquement
                # (un seul converter réutilisé : modèles chargés une fois)
                conv_ocr = _build_converter(force_ocr=True, artifacts_path=artifacts_path)
                recovered = []
                for n in empty:
                    ocr_md = conv_ocr.convert(str(src), page_range=(n, n)).document.export_to_markdown()
                    if _has_text(ocr_md):
                        page_md[n] = ocr_md
                        recovered.append(n)
                if recovered:
                    md = "\n\n".join(page_md[n] for n in pages)
                    message = f"ocr pleine page sur pages : {', '.join(map(str, recovered))}"

        out_md.write_text(md, encoding="utf-8")
        status = "ok"
    except Exception as e:
        status = "nok"
        message = f"{type(e).__name__}: {e}"
        out_md_str = "" # Indique qu'aucun fichier de sortie n'a été créé.

    duration = time.time() - t0
    return [str(src), out_md_str, status, f"{duration:.2f}", message]


class OWDoclingToMarkdown(widget.OWWidget):
    name = "Docling To Markdown"
    description = "Convert DOCX/PPTX/PDF to Markdown via Docling"
    icon = "icons/md.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/md.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owdoclingtomarkdown.ui")
    want_control_area = False
    priority = 1004

    auto_send = Setting(True)

    status_update_signal = pyqtSignal(list)

    class Inputs:
        data = Input("Files Table", Table)
        executor = Input("ProcessPoolExecutor", object)

    class Outputs:
        data = Output("Markdown Table", Table)
        status_data = Output("Status Table", Table)

    def __init__(self):
        super().__init__()
        self.data = None
        self.external_executor = None
        self.thread = None
        self.result = None
        self.processed_statuses = {}  # Dictionary to accumulate statuses for each file
        # Chemin des modèles Docling dans l'AAIT store ("" = indisponibles : PDF non convertis)
        self.artifacts_path = ""

        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        self.checkBox_send.setChecked(self.auto_send)
        self.checkBox_send.toggled.connect(self._update_auto_send)
        self.pushButton_send.clicked.connect(self.run)
        # Connecté une seule fois (sinon un handler de plus à chaque exécution)
        self.status_update_signal.connect(self.handle_status_update)

        self.error("")
        self.warning("")

    def _update_auto_send(self, checked):
        self.auto_send = checked

    @Inputs.data
    def set_data(self, in_data: Table | None):
        self.data = in_data
        if self.auto_send:
            self.run()

    def run(self):
        in_data = self.data
        self.error("")
        self.warning("")

        if not in_data:
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)
            return

        try:
            _ = in_data.domain["file_path"]
        except Exception:
            self.error('Colonne "file_path" (Text) requise.')
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)
            return

        self._convert_now()

    @Inputs.executor
    def set_executor(self, executor_obj):
        self.external_executor = executor_obj
        if executor_obj is not None:
            self.label_exec.setText("Exécution: via ProcessPoolExecutor externe (parallèle).")
        else:
            self.label_exec.setText("Exécution: séquentielle (aucun executor connecté).")

    def _convert_now(self):
        if self.thread is not None and self.thread.isRunning():
            self.thread.safe_quit()

        if not self.data:
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)
            return

        # Start progress bar
        self.progressBarInit()

        # Récupère les chemins et filtre par extensions supportées
        try:
            paths = [Path(str(x)) for x in self.data.get_column("file_path")]
        except Exception as e:
            self.error(f"Lecture de 'file_path' impossible: {e}")
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)
            return

        files = [p for p in paths if p.exists() and p.suffix.lower() in (".pdf", ".docx", ".pptx")]
        if not files:
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)
            self.progressBarFinished()
            return

        # Les modèles ne servent qu'aux PDF (DOCX/PPTX : SimplePipeline sans modèle)
        if any(p.suffix.lower() == ".pdf" for p in files):
            self._resolve_docling_models()

        # Initialize status dictionary for incremental updates
        self.processed_statuses = {str(p): ["pending", ""] for p in files}
        self.update_status_output()

        # Connect and start thread for the main function
        self.thread = Thread(self._run_conversion, files)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def _resolve_docling_models(self):
        """Cherche les modèles Docling dans l'AAIT store, propose le téléchargement
        depuis le remote AAIT store sinon. Aucune autre source : à défaut, les PDF
        ne sont pas convertis.
        Appelé dans le thread GUI (boîtes de dialogue). Revérifié à chaque exécution :
        les modèles ont pu être supprimés depuis la dernière résolution.
        """
        if _docling_models_complete(self.artifacts_path):
            return
        self.artifacts_path = ""
        try:
            path = get_path_or_retrieve(DOCLING_MODELS_KEY)
            # Dossier présent mais incomplet : get_path_or_retrieve ne teste que son existence
            if not _docling_models_complete(path):
                if not SimpleDialogQt.BoxYesNo("Docling models are incomplete in your computer. "
                                               "Do you want to download them from AAIT store?"):
                    raise ValueError("User don't want to download Docling models")
                if GetFromRemote(DOCLING_MODELS_KEY) != 0 or not _docling_models_complete(path):
                    # Cas fréquent : poids RapidOCR du store d'une version non supportée
                    # par le rapidocr installé (ex. PP-OCRv6 avec un rapidocr ancien)
                    incompat = _rapidocr_incompatibility(path)
                    SimpleDialogQt.BoxError("Unable to get the Model." + (f"\n{incompat}" if incompat else ""))
                    raise ValueError(f"Docling models still incomplete in: {path} {incompat}")
            self.artifacts_path = path
        except Exception as e:
            print(f"[Docling] modèles AAIT store indisponibles : {e}")
            self.warning("Modèles Docling indisponibles (AAIT store) : les PDF ne seront pas convertis.")

    def update_status_output(self):
        """Helper function to create and send the status table."""
        status_domain = Domain(
            [],  # This list must be empty because the table has no attributes.
            metas=[
                StringVariable("input_path"),
                DiscreteVariable("status", values=["pending", "in_progress", "ok", "nok"]),
                StringVariable("message"),
            ],
        )

        status_rows = []
        for path_str, status_info in self.processed_statuses.items():
            status, message = status_info
            status_rows.append([path_str, status, message])

        status_table = Table.from_list(status_domain, status_rows)
        self.Outputs.status_data.send(status_table)

    def _run_conversion(self, files, progress_callback):
        results = []
        pdfs = [str(p) for p in files if p.suffix.lower() == ".pdf"]
        artifacts_path = self.artifacts_path
        models_error = "modèles Docling indisponibles (AAIT store)"

        # Gère le chemin du fichier Excel
        base_name = "conversion_results"  # Nom de base pour le fichier Excel
        # Définir le chemin du dossier de sortie de Docling
        if files:
            first_file_path = Path(files[0])
            out_dir = first_file_path.parent / "conversion_markdown"
        else:
            out_dir = Path.cwd() / "conversion_markdown"

        excel_path = out_dir / f"{base_name}.xlsx"
        counter = 1
        while excel_path.exists():
            excel_path = out_dir / f"{base_name}_{counter}.xlsx"
            counter += 1

        # Initialise le classeur et la feuille Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "Conversion Results"
        headers = ["input_path", "output_md", "status", "duration_sec", "message"]
        ws.append(headers)

        # Sans modèles, les PDF ne sont pas convertis (DOCX/PPTX n'en ont pas besoin)
        if pdfs and not artifacts_path:
            for path_str in pdfs:
                row = [path_str, "", "nok", "0.00", models_error]
                results.append(row)
                ws.append(row)
                self.status_update_signal.emit([path_str, "nok", models_error])
            out_dir.mkdir(parents=True, exist_ok=True)
            wb.save(excel_path)
            files = [p for p in files if p.suffix.lower() != ".pdf"]

        if self.external_executor is None:
            # --- Mode simple séquentiel ---
            for i, p in enumerate(files):
                path_str = str(p)
                self.status_update_signal.emit([path_str, "in_progress", ""])

                row = _convert_one_file(path_str, artifacts_path)
                results.append(row)
                ws.append(row)
                wb.save(excel_path)
                self.status_update_signal.emit([row[0], row[2], row[4]])

                progress_callback((i + 1) / len(files) * 100)
        else:
            # --- Mode parallèle via executor externe ---
            fut_map = {self.external_executor.submit(_convert_one_file, str(p), artifacts_path): str(p)
                       for p in files}

            for i, fut in enumerate(as_completed(fut_map), 1):
                file_path_str = fut_map[fut]
                self.status_update_signal.emit([file_path_str, "in_progress", ""])

                try:
                    row = fut.result()
                    results.append(row)
                    ws.append(row)
                    wb.save(excel_path)
                    self.status_update_signal.emit([row[0], row[2], row[4]])
                except Exception as e:
                    row = [file_path_str, "",
                           "nok", "0.00", f"FutureError: {e}"]
                    results.append(row)
                    ws.append(row)
                    wb.save(excel_path)
                    self.status_update_signal.emit([row[0], "nok", f"FutureError: {e}"])

                progress_callback(i / len(files) * 100)

        # The final result is the table built from all results
        domain = Domain([], metas=[
            StringVariable("input_path"),
            StringVariable("output_md"),
            StringVariable("status"),
            StringVariable("duration_sec"),
            StringVariable("message"),
        ])
        final_table = Table.from_list(domain, results)
        return final_table

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_status_update(self, status_info: list):
        """Receives a single status update and updates the internal dictionary and the output."""
        path_str, status, message = status_info
        self.processed_statuses[path_str] = [status, message]
        self.update_status_output()

    def handle_result(self, result: Table):
        try:
            self.result = result
            self.Outputs.data.send(result)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)

    def handle_finish(self):
        self.progressBarFinished()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWDoclingToMarkdown()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
