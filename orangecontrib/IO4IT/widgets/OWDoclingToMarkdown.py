import os, time, sys
from pathlib import Path
from concurrent.futures import as_completed

from AnyQt.QtWidgets import QLabel, QApplication
from AnyQt.QtCore import pyqtSignal
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Domain, StringVariable, Table, DiscreteVariable

# --- Ajouts pour l'écriture Excel ---
from openpyxl import Workbook

# --- Docling (unique lib utilisée pour la conversion) ---
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
    WordFormatOption,
)
from docling.pipeline.simple_pipeline import SimplePipeline
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

# --- Orange contrib Imports ---
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.thread_management import Thread
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.AAIT.utils.thread_management import Thread
    from orangecontrib.AAIT.utils.import_uic import uic


# --------- worker stateless : convertit 1 fichier avec Docling ----------
def _convert_one_file(file_path_str: str):
    """Convertit un fichier (PDF/DOCX/PPTX) en Markdown via Docling.
    Écrit <parent>/a_md/<stem>.md et renvoie [input_path, output_md, status, duration_sec, message].
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
        # Docling minimal config (inspiré du snippet)
        doc_converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.PPTX],
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=StandardPdfPipeline,
                    backend=PyPdfiumDocumentBackend
                ),
                InputFormat.DOCX: WordFormatOption(
                    pipeline_cls=SimplePipeline
                ),
                # PPTX: pas d'option spécifique; géré par défaut
            },
        )
        doc = doc_converter.convert(str(src)).document
        md = doc.export_to_markdown()
        out_md.write_text(md, encoding="utf-8")
        status, message = "ok", ""
    except Exception as e:
        status = "nok"
        message = f"{type(e).__name__}: {e}"
        # Lignes d'écriture du fichier de trace .md supprimées ici
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
    want_main_area = False
    want_control_area = True
    priority = 1004

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
        self.exec_info = QLabel("Exécution: séquentielle (aucun executor connecté).", self)
        self.processed_statuses = {}  # Dictionary to accumulate statuses for each file

        uic.loadUi(self.gui, self)

        self.error("")
        self.warning("")

    @Inputs.data
    def set_data(self, in_data: Table | None):
        self.data = in_data
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
            self.exec_info.setText("Exécution: via ProcessPoolExecutor externe (parallèle).")
        else:
            self.exec_info.setText("Exécution: séquentielle (aucun executor connecté).")

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

        # Initialize status dictionary for incremental updates
        self.processed_statuses = {str(p): ["pending", ""] for p in files}
        self.update_status_output()

        # Connect internal signal
        self.status_update_signal.connect(self.handle_status_update)

        # Connect and start thread for the main function
        self.thread = Thread(self._run_conversion, files)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

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
            # Orange's Table.from_list expects a flat list of values matching the domain's order.
            # The row should contain the values for input_path, status, and message.
            # The status_info is a list [status, message]. We need to prepend the path_str.
            status_rows.append([path_str, status, message])

        status_table = Table.from_list(status_domain, status_rows)
        self.Outputs.status_data.send(status_table)

    def _run_conversion(self, files, progress_callback):
        results = []

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

        if self.external_executor is None:
            # --- Mode simple séquentiel ---
            for i, p in enumerate(files):
                path_str = str(p)
                # on met à jour le statut en "in_progress" et on envoie
                self.status_update_signal.emit([path_str, "in_progress", ""])

                row = _convert_one_file(path_str)
                results.append(row)
                ws.append(row)
                wb.save(excel_path)
                self.status_update_signal.emit([row[0], row[2], row[4]])

                progress_callback((i + 1) / len(files) * 100)
        else:
            # --- Mode parallèle via executor externe ---
            fut_map = {self.external_executor.submit(_convert_one_file, str(p)): str(p) for p in files}

            for i, fut in enumerate(as_completed(fut_map), 1):
                file_path_str = fut_map[fut]
                # on met à jour le statut en "in_progress" et on envoie
                self.status_update_signal.emit([file_path_str, "in_progress", ""])

                try:
                    row = fut.result()
                    results.append(row)
                    ws.append(row)
                    wb.save(excel_path)
                    self.status_update_signal.emit([row[0], row[2], row[4]])
                except Exception as e:
                    # Gestion des erreurs de la future et envoi
                    # Note : Dans ce cas, output_md est vide, car _convert_one_file renvoie ""
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