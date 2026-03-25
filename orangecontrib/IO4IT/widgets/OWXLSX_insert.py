import os
import sys
import pandas as pd
import win32com.client as win32
import pythoncom

from AnyQt.QtWidgets import QApplication, QPushButton, QCheckBox
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Domain, StringVariable, Table, DiscreteVariable

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.thread_management import Thread
    from Orange.widgets.orangecontrib.AAIT.utils import  base_widget
else:
    from orangecontrib.AAIT.utils.thread_management import Thread
    from orangecontrib.AAIT.utils import  base_widget


class OWInsertDataToExcel(base_widget.BaseListWidget):
    name = "Insert Data to Excel"
    description = "Insère une data table dans un fichier Excel à partir d'une cellule définie."
    category = "AAIT - TOOLBOX"
    icon = "icons/xlsx_insert.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/xlsx_insert.png"
    gui = os.path.join(os.path.dirname(__file__), "designer", "owinsertdatatoexcel.ui")
    want_control_area = False
    priority = 1010

    auto_send = Setting(True)
    selected_column_name = Setting("path")

    class Inputs:
        parameters = Input("Parameters", Table)
        data       = Input("Data Table", Table)

    class Outputs:
        status_data = Output("Status Table", Table)

    # ------------------------------------------------------------------ inputs
    @Inputs.parameters
    def set_parameters(self, in_data: Table | None):
        #A modif pour changer file_path en selection
        self.parameters = in_data
        if self.parameters:
            self.var_selector.add_variables(self.parameters.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        if self.auto_send and self.parameters and self.data:
            self.run()

    @Inputs.data
    def set_data(self, in_data: Table | None):
        self.data = in_data
        if self.auto_send and self.parameters and self.data:
            self.run()

    # ------------------------------------------------------------------ init
    def __init__(self):
        super().__init__()
        self.setSizeGripEnabled(False)
        self.setFixedSize(474, 400)
        self.parameters = None
        self.data       = None
        self.thread     = None
        self.result = None

        self.pushButton_run = self.findChild(QPushButton,  "pushButton_run")
        self.checkBox_send  = self.findChild(QCheckBox,    "checkBox_send")

        if self.checkBox_send:
            self.checkBox_send.setChecked(self.auto_send)
            self.checkBox_send.toggled.connect(self._on_autorun_toggled)

        if self.pushButton_run:
            self.pushButton_run.clicked.connect(self.run)


    # ------------------------------------------------------------------ slots UI
    def _on_autorun_toggled(self, checked: bool):
        self.auto_send = checked

    # ------------------------------------------------------------------ run
    def run(self):
        self.error("")
        self.warning("")
        self.information("")
       # If thread is running, quit previous
        if self.thread is not None:
            # Note: win32com threads are tricky to kill, but we follow the pattern
            if hasattr(self.thread, 'safe_quit'):
                self.thread.safe_quit()

        if self.parameters is None or self.data is None:
            return

        col_name = self.selected_column_name
        try:
            attr = self.parameters.domain[col_name]
            col_idx = self.parameters.domain.index(attr)
        except (KeyError, ValueError):
            self.error(f"Colonne '{col_name}' introuvable.")
            return

        # 2. Préparation des paramètres
        try:
            # On prend la première ligne de la table parameters
            row0 = self.parameters[0]
            
            # On convertit en DataFrame pour faciliter le mapping des autres colonnes (sheet, row, col)
            params_df = self._orange_table_to_dataframe(self.parameters)
            params_df.columns = params_df.columns.str.strip().str.lower()
            
            # On récupère le chemin dynamiquement depuis la colonne choisie, 
            # et les autres infos depuis les colonnes nommées classiquement
            file_params = {
                "file_path": str(row0[col_idx]).strip(), 
                "sheet_name": str(params_df.iloc[0].get("sheet_name", "Sheet1")).strip(),
                "start_col": int(float(str(params_df.iloc[0].get("col", 1)).strip())),
                "start_row": int(float(str(params_df.iloc[0].get("row", 1)).strip()))
            }
            
            data_df = self._orange_table_to_dataframe(self.data)
        except Exception as e:
            self.error(f"Erreur initialisation : {e}")
            return

        if self.pushButton_run:
            self.pushButton_run.setEnabled(False)
        # Start progress bar
        self.progressBarInit()

        # Connect and start thread (Architecture mimic)
        self.thread = Thread(self._run_logic, file_params, data_df)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.result = result
            if result.get("status") == "ok":
                self.information(result["details"])
            else:
                self.error(result.get("details", "Erreur inconnue"))
            
            self._send_status(result.get("status", "ko"), result.get("details", ""))
        except Exception as e:
            print("An error occurred when handling result:", e)
    
    def handle_finish(self):
        if self.pushButton_run:
            self.pushButton_run.setEnabled(True)
        self.progressBarFinished()
        print("Excel insertion process finished")

    # --- Thread Logic ---
    def _run_logic(self, file_params, df, progress_callback):
        """ Logique exécutée en thread. """
        result = {"status": "ko", "details": "Erreur inconnue."}
        excel = None
        wb = None
        try:
            pythoncom.CoInitialize()
            if not os.path.isfile(file_params['file_path']):
                return {"status": "ko", "details": "Fichier introuvable."}

            excel = win32.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            
            wb = excel.Workbooks.Open(os.path.abspath(file_params['file_path']))
            ws = wb.Worksheets(file_params['sheet_name'])

            total_rows = len(df)
            #total_ops = max(1, 1 + total_rows)

            # Header
            #for ci, col_name in enumerate(df.columns):
            #    ws.Cells(file_params['start_row'], file_params['start_col'] + ci).Value = str(col_name)
            #progress_callback(10)

            # Data
            for ri, row in enumerate(df.itertuples(index=False), start=0):
                for ci, val in enumerate(row):
                    ws.Cells(file_params['start_row'] + ri, file_params['start_col'] + ci).Value = val
                progress_callback(10 + int(((ri+1) / total_rows) * 80))

            wb.Save()
            result = {"status": "ok", "details": "Données insérées avec succès."}
        except Exception as e:
            result = {"status": "ko", "details": str(e)}
        finally:
            if wb: wb.Close(False)
            if excel: excel.Quit()
            pythoncom.CoUninitialize()
        return result

    # --- Helpers ---

    def _send_status(self, status, details):
        domain = Domain([], metas=[DiscreteVariable("status", values=["ok", "ko"]), StringVariable("details")])
        self.Outputs.status_data.send(Table.from_list(domain, [[status, details]]))

    def _orange_table_to_dataframe(self, table: Table) -> pd.DataFrame:
        col_names = [var.name for var in table.domain.attributes + table.domain.metas]
        if table.domain.class_var:
            col_names.append(table.domain.class_var.name)
        
        data = {name: list(table.get_column(name)) for name in col_names}
        df = pd.DataFrame(data).astype(str).replace("nan", "")
        return df

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = OWInsertDataToExcel()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()