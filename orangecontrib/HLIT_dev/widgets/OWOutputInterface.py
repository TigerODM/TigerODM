import os
import sys
import json
import Orange
from Orange.widgets.widget import OWWidget, Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QLineEdit, QApplication
from Orange.data import Table


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.HLIT_dev.remote_server_smb import convert
    from orangecontrib.AAIT.utils import MetManagement

class OutputInterface(OWWidget):
    name = "Output Interface"
    description = "Convert pdf from a directory to docx using word"
    icon = "icons/output_interface.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
         icon = "icons_dev/output_interface.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/output_interface.ui")
    priority = 3000
    workflow_id = Setting("")
    help_description = Setting("")
    expected_output = Setting("")
    want_control_area = False
    category = "AAIT - API"

    class Inputs:
        data_output = Input("Data", Table)
        data_in_example = Input("Data in example", Table)

    class Outputs:
        data_out_exemple = Output("Data out example", Orange.data.Table)

    @Inputs.data_output
    def set_data(self, dataset):
        self.data = dataset
        if self.data is not None:
            self.run()

    @Inputs.data_in_example
    def set_data_in_example(self, dataset):
        self.error("")
        if dataset is not None:
            result=convert.convert_data_table_to_json(dataset)
            if result==None:
                self.error("error cant cast datatable to json")
                return
            self.expected_output=result
            self.send_data_example()


    def __init__(self):
        super().__init__()
        self.data = None
        # Qt Management
        self.setFixedWidth(700)
        self.setFixedHeight(200)
        uic.loadUi(self.gui, self)

        self.workflow_id_input = self.findChild(QLineEdit, 'WorkflowId')
        self.workflow_id_input.setPlaceholderText("Workflow ID")
        self.workflow_id_input.setText(self.workflow_id)
        self.workflow_id_input.editingFinished.connect(self.update_settings)


        self.description_input = self.findChild(QLineEdit, 'Description')
        self.description_input.setText(self.help_description)
        self.description_input.editingFinished.connect(self.update_settings)
        self.send_data_example()

    def update_settings(self):
        self.workflow_id = self.workflow_id_input.text()
        self.help_description = self.description_input.text()
        if self.data is not None:
            self.run()

    def run(self):
        self.error("")
        self.warning("")
        if self.workflow_id == "":
            self.warning("Workflow ID manquant(s).")
            return

        path_file = MetManagement.get_api_local_folder(workflow_id=self.workflow_id)
        # Execution of the workflow
        if not os.path.exists(path_file + "config.json"):
            self.information("Le fichier 'config.json' n'existe pas encore en attente de données du serveur.")
            return
        with open(path_file + "config.json", "r", encoding="utf-8") as file:
            data = json.load(file)

        if self.workflow_id != data["workflow_id"]:
            self.error("Le workflow id ne correspond pas avec votre configuration.")
            return
        json_output = convert.convert_data_table_to_json(self.data)
        if json_output == None:
            return

        with open(path_file + "output.json", "w", encoding="utf-8") as file_out:
            json.dump(json_output, file_out, indent=4, ensure_ascii=False)

        with open(path_file + ".out_ok", "w") as fichier:
            pass
        fichier.close()

    def send_data_example(self):
        if self.expected_output == "":
            return
        if len(self.expected_output) > 0:
            data = convert.convert_json_implicite_to_data_table(self.expected_output)
            self.Outputs.data_out_exemple.send(data)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OutputInterface()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
