import os
import json
import ast
from Orange.widgets import  widget
from Orange.widgets.settings import Setting
from Orange.widgets.utils.widgetpreview import WidgetPreview
from Orange.widgets.widget import Input, Output
from Orange.data import Table
from AnyQt.QtWidgets import QCheckBox
import copy
from AnyQt.QtCore import QTimer

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


    class Inputs:
        data = Input("Data", Table)
        save_path = Input("Path", str, auto_summary=False)
        path_table = Input("Path Table", Table)

    class Outputs:
        data = Output("Data", Table)

    @Inputs.data
    def dataset(self, data): 
        """Handle new data input."""
        if data is None:
            self.data=None
            self.Outputs.data.send(None)
            return
        self.data = data
        self.run()


    @Inputs.save_path
    def set_save_path(self, in_save_path):
        if in_save_path is None:
            self.save_path=None
            self.Outputs.data.send(None)
            return
        self.save_path = in_save_path.replace('"', '')
        self.json = False
        if self.save_path.endswith(".json"):
            self.json = True
        self.run()

    @Inputs.path_table
    def set_path_table(self, in_path_table):
        if in_path_table is None:
            self.save_path=None
            return
        self.json = False
        if "path" in in_path_table.domain:
            if in_path_table[0]["path"].value.endswith(".json"):
                self.json = True
            self.save_path = in_path_table[0]["path"].value.replace('"', '')
            self.run()


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.checkbox_annotations = self.findChild(QCheckBox, 'checkBox')
        self.checkBox_2 = self.findChild(QCheckBox,'checkBox_2')

        self.checkbox_annotations.setChecked(self.annotations)
        self.checkBox_2.setChecked(self.purge_widget)
        self.checkbox_annotations.stateChanged.connect(self.update_parameters)
        self.checkBox_2.stateChanged.connect(self.update_parameters)
        # Data Management
        self.save_path = None
        self.data = None
        self.json = False
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def update_parameters(self):
        self.annotations = self.checkbox_annotations.isChecked()
        self.purge_widget=self.checkBox_2.isChecked()
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
        saver.filter = selected_filter
        saver.do_save()
        self.Outputs.data.send(self.data)


    def save_json(self):
        if "content" not in self.data.domain:
            self.error("No answer column found.")
            return
        if "content" not in self.data.domain:
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

            with open(folder_path, "w", encoding="utf-8") as f:
                json.dump(data_raw, f, ensure_ascii=False, indent=4)
        self.information("JSON saved successfully")
        self.Outputs.data.send(self.data)

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
        if self.json:
            self.save_json()
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
