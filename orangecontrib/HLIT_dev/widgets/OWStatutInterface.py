import os
import sys
import json
from Orange.widgets.widget import OWWidget, Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QLineEdit, QApplication
from Orange.data import Table

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import MetManagement

class StatutInterface(OWWidget):
    name = "Statut Interface"
    description = "Get the statut of the workflow in the local interface"
    icon = "icons/statut.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
         icon = "icons_dev/statut.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/statut_interface.ui")
    priority = 3000
    statut = Setting("")
    workflow_id = Setting("")
    help_description = Setting("")
    want_control_area = False
    category = "AAIT - API"

    class Inputs:
        data = Input("Data", Table)

    class Outputs:
        data = Output("Data", Table)

    @Inputs.data
    def set_data(self, in_data):
        if in_data is not None:
            self.data = in_data
            self.run()

    def __init__(self):
        super().__init__()
        self.data = None

        self.setFixedWidth(700)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        self.statut_input = self.findChild(QLineEdit, 'StatutValue')
        self.statut_input.setPlaceholderText("Value statut")
        self.statut_input.setText(self.statut)
        self.statut_input.editingFinished.connect(self.update_settings)

        # Qt Management
        self.workflow_id_input = self.findChild(QLineEdit, 'WorkflowId')
        self.workflow_id_input.setPlaceholderText("Workflow ID")
        self.workflow_id_input.setText(self.workflow_id)
        self.workflow_id_input.editingFinished.connect(self.update_settings)

        self.description_input = self.findChild(QLineEdit, 'Description')
        self.description_input.setText(self.help_description)
        self.description_input.editingFinished.connect(self.update_settings)

    def update_settings(self):
        self.statut = self.statut_input.text()
        self.workflow_id = self.workflow_id_input.text()
        if self.workflow_id != "" and self.statut != "":
            self.run()

    def run(self):
        self.error("")
        self.warning("")
        if self.data is None:
            return
        if self.workflow_id == "":
            self.warning("Workflow ID manquant -> je m'arrete.")
            return

        if self.statut == "":
            self.warning("Statut manquant -> je m'arrete..")
            return

        path_file = MetManagement.get_api_local_folder(workflow_id=self.workflow_id)

        # On remet à jour les fichiers statuts
        file_to_delete = [path_file + ".statut_ok", path_file + "statut.json"]

        if os.path.exists(file_to_delete[0]) and os.path.exists(file_to_delete[1]):
            if MetManagement.reset_files(file_to_delete) != 0:
                self.error("Les fichiers statuts sont supprimés .")
                return

        # Execution of the workflow
        if not os.path.exists(path_file + "config.json"):
            #self.error("Le fichier 'config.json' n'existe pas.")
            self.warning("Le serveur ne semble pas lancé -> je laisse passé le signal sans rien faire..")

            self.Outputs.data.send(self.data)
            return

        with open(path_file + "config.json", "r", encoding="utf-8") as file:
            data = json.load(file)

        if self.workflow_id != data["workflow_id"]:
            self.error("Le workflow id ne correspond pas avec votre configuration.")
            return

        with open(path_file + "statut.json", "w") as fichier:
            json.dump({"value" : self.statut}, fichier, indent=4)
        with open(path_file + ".statut_ok", "w") as fichier:
            pass
        MetManagement.write_file_time(path_file + "time.txt")
        self.Outputs.data.send(self.data)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = StatutInterface()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
