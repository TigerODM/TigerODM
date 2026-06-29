import os
import json
import ast
from Orange.widgets import  widget
from Orange.widgets.settings import Setting
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import Input, Output
from Orange.data import Table, StringVariable, Domain
from AnyQt.QtWidgets import QCheckBox
import copy
from AnyQt.QtCore import QTimer
import numpy as np
from pathlib import Path
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import help_management

class OWSaveFilepathEntry(widget.OWWidget):
    name = "Save with Filepath Entry"
    description = "Save data to a .pkl file, based on the provided path"
    category = "AAIT - TOOLBOX"
    icon = "icons/owsavefilepathentry.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owsavefilepathentry.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owsavewithpath.ui")
    priority = 1220
    want_control_area = False

    # Persistent settings for fileId and CSV delimiter
    filename: str = Setting("embeddings.pkl")
    annotations: bool = Setting(True)
    purge_widget: bool = Setting(False)
    allow_path_in_input: bool = Setting(False)

    class Inputs:
        data = Input("Data", Table)
        save_path = Input("Path", str, auto_summary=False)
        path_table = Input("Path Table", Table)

    class Outputs:
        data = Output("Data", Table)
        save_path_output = Output("Path", Table)

    @Inputs.data
    def dataset(self, data): 
        """Handle new data input."""
        if data is None:
            self.data=None
            self.Outputs.data.send(None)
            return
        if not self.allow_path_in_input:
            self.data = data
            self.run()
            return
        # est ce que j'a definit ma table de sortie dans mon in_data
        path_var = next((m for m in data.domain.metas if m.name == "path"), None)
        if path_var is None:
            self.data = data
            self.run()
            return

        # Table avec uniquement la méta "path"
        domain_path = Domain([], metas=[path_var])
        path_data = data.transform(domain_path)
        if path_data[0]["path"].value.endswith(".json"):
            self.data=data # cas json on laisse path dans la datatable
        else:
            # Table avec tout le reste
            domain_rest = Domain(
                data.domain.attributes,
                data.domain.class_vars,
                [m for m in data.domain.metas if m.name != "path"]
            )
            rest_data = data.transform(domain_rest)
            self.data =rest_data
        self.set_path_table(path_data)



    @Inputs.save_path
    def set_save_path(self, in_save_path):
        if in_save_path is None:
            self.save_path=None
            self.Outputs.data.send(None)
            self.Outputs.save_path_output.send(None)
            return
        self.save_path = in_save_path.replace('"', '')
        self.json = False
        if self.save_path.endswith(".json"):
            self.json = True
        var = StringVariable("path")
        domain = Domain([], metas=[var])
        X = np.empty((1, 0))
        metas = np.array([[in_save_path]], dtype=object)
        table = Table.from_numpy(domain, X, metas=metas)
        self.Outputs.save_path_output.send(table)
        self.run()

    @Inputs.path_table
    def set_path_table(self, in_path_table):
        if in_path_table is None:
            self.save_path=None
            self.Outputs.data.send(None)
            self.Outputs.save_path_output.send(None)
            return
        self.json = False
        if "path" in in_path_table.domain:
            if in_path_table[0]["path"].value.endswith(".json"):
                self.json = True
            self.save_path = in_path_table[0]["path"].value.replace('"', '')
            var = StringVariable("path")
            domain = Domain([], metas=[var])
            X = np.empty((1, 0))
            metas = np.array([[in_path_table[0]["path"]]], dtype=object)
            table = Table.from_numpy(domain, X, metas=metas)
            self.Outputs.save_path_output.send(table)
            self.run()


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.checkbox_annotations = self.findChild(QCheckBox, 'checkBox')
        self.checkBox_2 = self.findChild(QCheckBox,'checkBox_2')
        self.checkBox_3 = self.findChild(QCheckBox,'checkBox_3')
        self.checkbox_annotations.setChecked(self.annotations)
        self.checkBox_2.setChecked(self.purge_widget)
        self.checkBox_3.setChecked(self.allow_path_in_input)
        self.checkbox_annotations.stateChanged.connect(self.update_parameters)
        self.checkBox_2.stateChanged.connect(self.update_parameters)
        self.checkBox_3.stateChanged.connect(self.update_parameters)
        # Data Management
        self.save_path = None
        self.data = None
        self.json = False
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def update_parameters(self):
        self.annotations = self.checkbox_annotations.isChecked()
        self.purge_widget=self.checkBox_2.isChecked()
        self.allow_path_in_input=self.checkBox_3.isChecked()
        self.run()

    def save_file(self):
        self.error("")
        self.warning("")
        if os.path.isdir(self.save_path):
            self.save_path = os.path.join(self.save_path, self.filename)

        import Orange.widgets.data.owsave as save_py
        saver = save_py.OWSave()
        saver.add_type_annotations = self.annotations
        filters = saver.valid_filters()
        extension = os.path.splitext(self.save_path)[1]
        selected_filter = ""
        for key in filters:
            if f"(*{extension})" in key:
                selected_filter = key
        if selected_filter == "":
            self.error(f"Invalid extension for savepath : {self.save_path}")
            self.Outputs.data.send(None)
            return

        saver.data = self.data
        saver.filename = self.save_path
        Path(str(self.save_path)).parent.mkdir(parents=True,exist_ok=True)
        saver.filter = selected_filter
        saver.do_save()
        self.Outputs.data.send(self.data)


    def save_json(self):
        if "content" not in self.data.domain:
            self.error("No answer column found.")
            return
        if "path" not in self.data.domain:
            self.error("No path column found.")
            return
        for i in range(len(self.data.get_column("path"))):
            text_response = self.data.get_column("content")[i]
            folder_path = self.data.get_column("path")[i]
            try:
                data_raw = json.loads(text_response)
            except json.JSONDecodeError as e:
                print("JSON mal formé :", e)
                try:
                    data_raw = ast.literal_eval(text_response)
                except Exception as e2:
                    print("Invalid JSON :", e2)
                    self.error("Invalid JSON :", e2)
                    return
            Path(str(folder_path)).parent.mkdir(parents=True,exist_ok=True)
            with open(folder_path, "w", encoding="utf-8") as f:
                json.dump(data_raw, f, ensure_ascii=False, indent=4)
        self.information("JSON saved successfully")
        self.Outputs.data.send(self.data)

    def save_html(self):
        self.error("")
        self.information("")

        if "content" not in self.data.domain:
            self.error("No content column found.")
            return
        if "path" not in self.data.domain:
            self.error("No path column found.")
            return

        try:
            for i in range(len(self.data.get_column("path"))):
                # Extraction fidèle à la méthode JSON
                html_content = str(self.data.get_column("content")[i])
                target_path = str(self.data.get_column("path")[i]).replace('"', '')

                # Création des dossiers parents avec Path (comme dans save_json)
                Path(target_path).parent.mkdir(parents=True, exist_ok=True)

                # Écriture du fichier
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(html_content)

            self.information(f"{len(self.data)} HTML file(s) saved successfully.")
            self.Outputs.data.send(self.data)

        except Exception as e:
            print("Error saving HTML :", e)
            self.error(f"Error saving HTML : {str(e)}")

    def run(self):
        self.error("")
        self.information("")
        """Save data to a file."""
        if self.data is None:
            self.error("need data")
            return
        if self.save_path is None:
            self.error("need path")
            return
        if self.save_path.endswith(".json"):
            self.save_json()
        elif self.save_path.endswith(".html"):
            self.save_html()
        else:
            self.save_file()

        if self.purge_widget:
            self.save_path = None
        to_send=copy.deepcopy(self.data)
        if self.purge_widget:
            self.data = None

        self.Outputs.data.send(to_send)




if __name__ == "__main__": 
    WidgetPreview(OWSaveFilepathEntry).run()
