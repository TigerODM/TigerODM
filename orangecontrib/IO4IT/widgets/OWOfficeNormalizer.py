import os
import sys
from pathlib import Path
import shutil
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Domain, StringVariable, Table, DiscreteVariable
from openpyxl import Workbook
import docx
import filetype
import multiprocessing
import queue

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IO4IT.utils import utils_md
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.IO4IT.utils import utils_md
    from orangecontrib.AAIT.utils.import_uic import uic


def _convert_file_process(src_path: Path, dst_dir: Path, file_type: str, result_queue: multiprocessing.Queue):
    """
    Fonction de conversion exécutée dans un processus séparé.
    Place le résultat (statut, chemin, détails) dans une file d'attente.
    """
    try:
        if file_type == "doc":
            dst = utils_md.convert_doc_to_docx(src_path, dst_dir)
            result_queue.put(("ok", str(dst), "doc->docx"))
        elif file_type == "ppt":
            dst = utils_md.convert_ppt_to_pptx(src_path, dst_dir)
            result_queue.put(("ok", str(dst), "ppt->pptx"))
    except Exception as e:
        result_queue.put(("ko", "", f"conversion failed: {e}"))


class OWOfficeNormalizer(widget.OWWidget):
    name = "Office Normalizer"
    description = "Convertit .doc→.docx et .ppt→.pptx via COM (Windows + Office)"
    category = "AAIT - TOOLBOX"
    icon = "icons/office_normalizer.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/office_normalizer.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owofficenormalizer.ui")
    want_control_area = False
    priority = 1003

    class Inputs:
        data = Input("Files Table", Table)

    class Outputs:
        data = Output("Normalized Files", Table)
        status_data = Output("Status Table", Table)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        self.data = None
        self.autorun = True
        self.result = None
        self.processed_statuses = []

        # Connecter la case à cocher pour activer/désactiver le spinbox
        self.checkBox_timeout.toggled.connect(self.spinBox_timeout.setEnabled)
        self.spinBox_timeout.setEnabled(self.checkBox_timeout.isChecked())

        self.post_initialized()

    @Inputs.data
    def set_data(self, in_data: Table | None):
        self.data = in_data
        if self.autorun:
            self.run()

    def run(self):
        if self.data is None:
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)
            return

        self.error("")
        try:
            self.data.domain["file_path"]
        except KeyError:
            self.error("You need a 'file_path' column in input data.")
            return

        self.progressBarInit()
        self.processed_statuses = []
        self.Outputs.status_data.send(None)

        # Déterminer la valeur du timeout
        self.timeout_value = None
        if self.checkBox_timeout.isChecked():
            self.timeout_value = self.spinBox_timeout.value()

        result_table = self._normalize_files(self.data)

        self.Outputs.data.send(result_table)
        self.progressBarFinished()

    def _check_file_status(self, file_path: Path):
        """
        Vérifie si un fichier est accessible, non corrompu et non protégé par un mot de passe.
        Retourne un tuple : (statut_court, détails)
        """
        if not file_path.exists():
            return "ko", "not found"
        try:
            with open(file_path, 'rb'):
                pass
        except IOError as e:
            return "ko", f"locked or permission denied: {e}"
        try:
            filetype.guess(file_path)
        except Exception as e:
            # Si filetype échoue, c'est probablement un problème de lecture ou de corruption.
            return "ko", f"file format detection failed: {e}"

        if file_path.suffix.lower() == ".docx":
            try:
                docx.Document(file_path)
            except Exception:
                return "ko", "corrupted"
        return "ok", "ready"

    def _normalize_files(self, in_data: Table) -> Table:
        rows = []
        file_paths = [str(x) for x in in_data.get_column("file_path")]
        total_files = len(file_paths)

        if not file_paths:
            return Table.from_list(
                Domain([], metas=[StringVariable("src_path"), StringVariable("dst_path"), StringVariable("status")]),
                [])

        common_path = Path(os.path.commonpath(file_paths))
        output_base_dir = common_path / "office_normalisation"
        output_base_dir.mkdir(parents=True, exist_ok=True)

        base_name = "normalization_results"
        excel_path = output_base_dir / f"{base_name}.xlsx"
        counter = 1
        while excel_path.exists():
            excel_path = output_base_dir / f"{base_name}_{counter}.xlsx"
            counter += 1

        wb = Workbook()
        ws = wb.active
        ws.title = "Normalization Results"
        headers = ["src_path", "dst_path", "status", "details"]
        ws.append(headers)

        for i, path_str in enumerate(file_paths):
            self.progressBarSet(i / total_files * 100)
            src = Path(path_str)
            dst_path = ""
            status_short, details = self._check_file_status(src)

            if status_short == "ok":
                try:
                    if src.suffix.lower() == ".docx":
                        dst_dir = output_base_dir / src.parent.relative_to(common_path)
                        dst_dir.mkdir(parents=True, exist_ok=True)
                        dst = dst_dir / src.name
                        shutil.copy(src, dst)
                        dst_path = str(dst)
                        details = "docx - unchanged"

                    elif src.suffix.lower() in [".doc", ".ppt"]:
                        dst_dir = output_base_dir / src.parent.relative_to(common_path)
                        dst_dir.mkdir(parents=True, exist_ok=True)

                        result_queue = multiprocessing.Queue()
                        p = multiprocessing.Process(
                            target=_convert_file_process,
                            args=(src, dst_dir, src.suffix.lower().lstrip("."), result_queue)
                        )
                        p.start()

                        try:
                            # Utilisation de la valeur de timeout sélectionnée
                            p.join(timeout=self.timeout_value)

                            if p.is_alive():
                                p.terminate()
                                status_short = "ko"
                                details = "conversion timed out"
                            else:
                                status_short, dst_path, details = result_queue.get(timeout=1)
                        except queue.Empty:
                            status_short = "ko"
                            details = "conversion process failed silently"
                        except Exception as e:
                            status_short = "ko"
                            details = f"conversion failed: {e}"

                    else:
                        dst_dir = output_base_dir / src.parent.relative_to(common_path)
                        dst_dir.mkdir(parents=True, exist_ok=True)
                        dst = dst_dir / src.name
                        if not dst.exists():
                            shutil.copy(src, dst)
                        dst_path = str(dst)
                        details = "unchanged"

                except Exception as e:
                    status_short = "ko"
                    details = f"error: {e}"

            result_row = [path_str, dst_path, status_short, details]
            ws.append(result_row)
            wb.save(excel_path)
            rows.append([path_str, dst_path, status_short])

            self.processed_statuses.append([path_str, status_short, details])
            self._send_status_table()

            QApplication.processEvents()

        self.progressBarSet(100)
        domain = Domain([], metas=[
            StringVariable("src_path"),
            StringVariable("dst_path"),
            StringVariable("status")
        ])
        return Table.from_list(domain, rows)

    def _send_status_table(self):
        domain = Domain([], metas=[
            StringVariable("src_path"),
            DiscreteVariable("status", values=["ok", "ko"]),
            StringVariable("details")
        ])
        status_table = Table.from_list(domain, self.processed_statuses)
        self.Outputs.status_data.send(status_table)

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def post_initialized(self):
        pass


if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    my_widget = OWOfficeNormalizer()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()