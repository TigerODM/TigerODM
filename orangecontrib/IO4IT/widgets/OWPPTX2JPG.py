import os
import sys
from AnyQt.QtWidgets import QApplication
from AnyQt.QtCore import pyqtSignal, QTimer
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Domain, StringVariable, Table, DiscreteVariable
from Orange.widgets.settings import Setting

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IO4IT.utils import pptx2jpg
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.thread_management import Thread
    from Orange.widgets.orangecontrib.AAIT.utils import  base_widget
else:
    from orangecontrib.IO4IT.utils import pptx2jpg
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.thread_management import Thread
    from orangecontrib.AAIT.utils import  base_widget

class OWPPTX2JPG(base_widget.BaseListWidget):
    name = "PPTX to Images"
    description = "Convertit les présentations PowerPoint en images JPG."
    icon = "icons/pptx2jpg.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/pptx2jpg.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owpptx2jpg.ui")
    want_control_area = False
    category = "AAIT - TOOLBOX"
    priority = 10000

    selected_column_name = Setting("path")

    auto_send = Setting(False)
    create_unique_folder = Setting(False)
    status_update_signal = pyqtSignal(list)

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
        if self.autorun:
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

        if hasattr(self, "pushButton_send"):
            self.pushButton_send.clicked.connect(self.run)

        self.status_update_signal.connect(self.handle_status_update)

    def _update_auto_send_setting(self, checked):
        self.auto_send = checked

    def _update_create_unique_folder_setting(self, checked):
        self.create_unique_folder = checked

    def run(self):
        self.error("")
        self.warning("")

        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None) 
            return
        
        col_name = self.selected_column_name  # ← colonne choisie par l'utilisateur
        try:
            attr = self.data.domain[col_name]
            col_idx = self.data.domain.index(attr)
        except (KeyError, ValueError):
            self.error(f"Column '{col_name}' not found in input data.")
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None) 
            return

        pptx_files = [str(row[col_idx]) for row in self.data if str(row[col_idx]).lower().endswith(".pptx")]
        
        if not pptx_files:
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None) 
            return

        self.processed_statuses = {}        

        self.progressBarInit()

        unique_folder = self.create_unique_folder

        self.thread = Thread(self._convert_and_build_table, pptx_files, unique_folder)

        self.thread.result.connect(self.handle_progress) # Fonction lignes 106-108 create embeddings
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()
    
    def handleNewSignals(self):
        if self.data:
            has_path = any(v.name == self.selected_column_name for v in self.data.domain.variables + self.data.domain.metas)            
            if hasattr(self, "pushButton_send"):
                self.pushButton_send.setEnabled(has_path)

            if has_path and self.auto_send:
                QTimer.singleShot(100, self.run)
        else:
            if hasattr(self, "pushButton_send"):
                self.pushButton_send.setEnabled(False)

    def handle_status_update(self, info):
        path_str, status, message = info
        # Accumule en mémoire uniquement, sans envoyer les mises à jour intermédiaires
        self.processed_statuses[path_str] = {"status": status, "message": message}

    def handle_progress(self, value: float) -> None:
        """Met à jour la barre de progression (reçu via progress_callback)"""
        self.progressBarSet(value)

    def handle_result(self, result_table):
        """Gère la table de données finale reçue du thread"""
        try:
            self.Outputs.data.send(result_table)

            # Envoie la status table
            final_statuses = {
                path: d for path, d in self.processed_statuses.items()
                if d["status"] != "in_progress"
            }

            status_domain = Domain([], metas=[
                StringVariable("input_pptx"),
                DiscreteVariable("status", values=["ok", "nok"]),
                StringVariable("message"),
            ])

            rows = [[path, d["status"], d["message"]] for path, d in final_statuses.items()]
            if rows:
                self.Outputs.status_data.send(Table.from_list(status_domain, rows))
                
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)

    def handle_finish(self):
        """Nettoyage final une fois le thread terminé"""
        print("PPTX Conversion finished")
        self.progressBarFinished()

    def _convert_and_build_table(self, files, unique_folder, progress_callback):
        results = []
        for i, f in enumerate(files):
            self.status_update_signal.emit([f, "in_progress", "Processing..."])
            try:
                # ✅ unique_folder transmis à la fonction de conversion
                res = pptx2jpg.process_one_pptx(f, unique_folder=unique_folder)
                results.append(res)
                self.status_update_signal.emit([res[0], res[2], res[4]])
            except Exception as e:
                self.status_update_signal.emit([f, "nok", str(e)])
            
            progress_callback((i + 1) / len(files) * 100)
        
        # Build fresh img_rows — no accumulation from previous runs
        seen = set()  # ✅ Deduplicate in case of reruns
        img_rows = []
        for res in results:
            if res[2] == "ok":
                for img in str(res[1]).split("|"):
                    img = img.strip()
                    if img and img not in seen:  # ✅ Skip duplicates
                        seen.add(img)
                        img_rows.append([res[0], img])

        out_domain = Domain([], metas=[StringVariable("original_pptx_path"), StringVariable("image_slide_path")])
        return Table.from_list(out_domain, img_rows)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = OWPPTX2JPG()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()