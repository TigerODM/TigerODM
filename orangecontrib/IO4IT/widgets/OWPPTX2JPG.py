import os
import sys
from AnyQt.QtWidgets import QApplication
from AnyQt.QtCore import pyqtSignal
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Domain, StringVariable, Table, DiscreteVariable
from Orange.widgets.settings import Setting

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IO4IT.utils import file2images
    from Orange.widgets.orangecontrib.AAIT.utils.thread_management import Thread
    from Orange.widgets.orangecontrib.AAIT.utils import  base_widget
else:
    from orangecontrib.IO4IT.utils import file2images
    from orangecontrib.AAIT.utils.thread_management import Thread
    from orangecontrib.AAIT.utils import  base_widget
def _find_var(domain, name):
    """Retourne la variable de nom `name` si elle existe dans le domaine, sinon None."""
    if not name:
        return None
    try:
        return domain[name]
    except (KeyError, ValueError):
        return None
class OWPPTX2JPG(base_widget.BaseListWidget):
    name = "PPTX/PDF to Images"
    description = "Convertit les fichiers PowerPoint et PDF en images JPG."
    icon = "icons/file2images.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/file2images.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owfile2images.ui")
    want_control_area = False
    category = "AAIT - TOOLBOX"
    priority = 10000

    selected_column_name = Setting("path")

    output_column_name = Setting("output_folder")
    pages_column_name = Setting("pages")
    output_ext = Setting("jpg")
    output_dpi = Setting(150)

    auto_send = Setting(False)
    create_unique_folder = Setting(False)
    status_update_signal = pyqtSignal(list)
    SUPPORTED_EXT = (".pptx", ".pdf")
    class Inputs:
        data = Input("Files Table", Table)

    class Outputs:
        data = Output("Images Table", Table)
        status_data = Output("Status Table", Table)

    @Inputs.data
    def set_data(self, in_data: Table | None):
        self.data = in_data
        if self.data:
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        if self.auto_send:
            self.run()

    def __init__(self):
        super().__init__()
        self.setSizeGripEnabled(False)
        self.data = None
        self.thread = None
        self.processed_statuses = {}

        if hasattr(self, "checkBox_send"):
            self.checkBox_send.setChecked(self.auto_send)
            self.checkBox_send.toggled.connect(self._update_auto_send_setting)

        if hasattr(self, "checkBox_multiple_folders"):
            self.checkBox_multiple_folders.setChecked(self.create_unique_folder)
            self.checkBox_multiple_folders.toggled.connect(self._update_create_unique_folder_setting)

        # Sélecteur de format de sortie (jpg / png / tif). Optionnel : si le combo
        # n'existe pas dans le .ui, on garde la valeur par défaut du Setting ("jpg").
        if hasattr(self, "comboBox_ext"):
            idx = self.comboBox_ext.findText(self.output_ext)
            if idx >= 0:
                self.comboBox_ext.setCurrentIndex(idx)
            self.comboBox_ext.currentTextChanged.connect(self._update_output_ext_setting)

        # Sélecteur de résolution (DPI). Optionnel : si le spinbox n'existe
        # pas dans le .ui, on garde la valeur par défaut du Setting (150).
        if hasattr(self, "spinBox_dpi"):
            self.spinBox_dpi.setValue(self.output_dpi)
            self.spinBox_dpi.valueChanged.connect(self._update_output_dpi_setting)

        if hasattr(self, "pushButton_send"):
            self.pushButton_send.clicked.connect(self.run)

        self.status_update_signal.connect(self.handle_status_update)

    def _update_auto_send_setting(self, checked):
        self.auto_send = checked

    def _update_create_unique_folder_setting(self, checked):
        self.create_unique_folder = checked

    def _update_output_ext_setting(self, text):
        self.output_ext = text.strip().lower()

    def _update_output_dpi_setting(self, value):
        self.output_dpi = int(value)

    def run(self):
        self.error("")
        self.warning("")

        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)
            return

        domain = self.data.domain

        # --- Colonne fichier (obligatoire) ---
        file_attr = _find_var(domain, self.selected_column_name)
        if file_attr is None:
            self.error(f"Column '{self.selected_column_name}' not found in input data.")
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)
            return

        # --- Colonnes optionnelles ---
        out_attr = _find_var(domain, self.output_column_name)     # dossier de sortie
        pages_attr = _find_var(domain, self.pages_column_name)    # pages/slides

        if out_attr is None:
            self.warning(f"Colonne dossier '{self.output_column_name}' absente : "
                         f"dossier de sortie calculé automatiquement.")

        # --- Construction des tâches : (fichier, dossier_sortie, pages) ---
        jobs = []
        for row in self.data:
            f = str(row[file_attr]).strip()
            if not f.lower().endswith(self.SUPPORTED_EXT):
                continue
            out_dir = str(row[out_attr]).strip() if out_attr is not None else ""
            pages = str(row[pages_attr]).strip() if pages_attr is not None else "all"
            jobs.append((f, out_dir or None, pages or "all"))

        # Dédoublonnage : on ne convertit pas deux fois une tâche identique
        jobs = list(dict.fromkeys(jobs))

        if not jobs:
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)
            return

        self.processed_statuses = {}
        self.progressBarInit()

        unique_folder = self.create_unique_folder
        out_ext = self.output_ext
        dpi = self.output_dpi
        self.thread = Thread(self._convert_and_build_table, jobs, unique_folder, out_ext, dpi)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_status_update(self, info):
        path_str, status, message = info
        # Accumule en mémoire uniquement, sans envoyer les mises à jour intermédiaires
        self.processed_statuses[path_str] = {"status": status, "message": message}

    def handle_progress(self, value: float) -> None:
        """Met à jour la barre de progression (reçu via progress_callback)"""
        self.progressBarSet(int(value))

    def handle_result(self, result_table):
        try:
            self.Outputs.data.send(result_table)

            final_statuses = {
                path: d for path, d in self.processed_statuses.items()
                if d["status"] != "in_progress"
            }

            status_domain = Domain([], metas=[
                StringVariable("input_file"),
                DiscreteVariable("status", values=["ok", "nok"]),
                StringVariable("message"),
            ])

            rows = [[path, d["status"], d["message"]] for path, d in final_statuses.items()]
            status_table = Table.from_list(status_domain, rows) if rows else None
            self.Outputs.status_data.send(status_table)   # ← always sent

        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)            # ← always sent on error too

    def handle_finish(self):
        """Nettoyage final une fois le thread terminé"""
        print("File Conversion finished")
        self.progressBarFinished()

    def _convert_and_build_table(self, jobs, unique_folder, out_ext, dpi, progress_callback):
        results = []
        total = len(jobs)
        for i, (f, out_dir, pages) in enumerate(jobs):
            self.status_update_signal.emit([f, "in_progress", "Processing..."])
            try:
                res = file2images.process_one_file(
                    f,
                    out_dir_str=out_dir,
                    pages=pages,
                    out_ext=out_ext,
                    dpi=dpi,
                    unique_folder=unique_folder,
                )
                results.append(res)
                self.status_update_signal.emit([res[0], res[2], res[4]])
            except Exception as e:
                results.append([f, "", "nok", "0.0", str(e)])
                self.status_update_signal.emit([f, "nok", str(e)])

            progress_callback((i + 1) / total * 100)

        # Build fresh img_rows — no accumulation from previous runs
        seen = set()  # Deduplicate in case of reruns
        img_rows = []
        for res in results:
            if res[2] == "ok":
                for img in str(res[1]).split("|"):
                    img = img.strip()
                    if img and img not in seen:
                        seen.add(img)
                        img_rows.append([res[0], img])

        out_domain = Domain([], metas=[
            StringVariable("original_file_path"),
            StringVariable("image_slide_path"),
        ])
        return Table.from_list(out_domain, img_rows)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = OWPPTX2JPG()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
