import os
import sys
import json
from Orange.widgets.widget import OWWidget, Input, Output
from AnyQt.QtWidgets import QApplication, QCheckBox,QLineEdit
from Orange.data import Table
from Orange.widgets.settings import Setting

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
    from Orange.widgets.orangecontrib.AAIT.utils import windows_utils,mac_utils
    from Orange.widgets.orangecontrib.AAIT.utils import SimpleDialogQt
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import MetManagement
    from orangecontrib.AAIT.utils import windows_utils,mac_utils
    from orangecontrib.AAIT.utils import SimpleDialogQt

class OWControl(OWWidget):
    name = "CheckTable"
    description = "Check whether the columns match the expected columns."
    icon = "icons/check_table.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
         icon = "icons_dev/check_table.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/CheckTable.ui")
    priority = 3000
    statut = Setting("")
    workflow_id = Setting("")
    help_description = Setting("")
    want_control_area = False
    category = "AAIT - API"
    str_nb_line_data_in_reference = Setting("0")
    str_col_description=Setting("")
    str_check_number_of_line=Setting("False")
    str_allow_extra_column = Setting("False")
    str_pop_message_box= Setting("False")
    workflow_id = Setting("")

    class Inputs:
        data = Input("Data", Table)
        data_in_reference = Input("Data in Reference", Table)
    class Outputs:
        data = Output("Data", Table)
        data_out_error = Output("Data out error", Table)





    @Inputs.data
    def set_data(self, in_data):
        if in_data is None:
            self.Outputs.data.send(None)
            return
        self.data = in_data
        self.run()

    @Inputs.data_in_reference
    def set_data_in_reference(self, dataset):
        self.error("")
        if dataset is None:
            self.Outputs.data.send(None)
            return
        result=MetManagement.describe_orange_table(dataset)
        if result is None:
            self.str_nb_line_data_in_reference="0"
            self.str_col_description=""
            self.error("error during reading data_in_reference")
            return
        self.str_nb_line_data_in_reference=str(result[0])
        self.str_col_description=str(json.dumps(result[1], ensure_ascii=False))

    def update_checkBox_1(self):
        if self.checkBox_1.isChecked():
            self.str_check_number_of_line="True"
        else:
            self.str_check_number_of_line = "False"

    def update_checkBox_2(self):
        if self.checkBox_2.isChecked():
            self.str_allow_extra_column="True"
        else:
            self.str_allow_extra_column = "False"

    def update_checkBox_3(self):
        if self.checkBox_3.isChecked():
            self.str_pop_message_box = "True"
        else:
            self.str_pop_message_box = "False"

    def update_settings(self):
        self.workflow_id = self.workflow_id_input.text()
        if self.workflow_id != "":
            self.run()

    def __init__(self):
        super().__init__()
        self.data = None

        self.setFixedWidth(700)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.checkBox_1 = self.findChild(QCheckBox, 'checkBox')
        self.checkBox_2 = self.findChild(QCheckBox, 'checkBox_2')
        self.checkBox_3 = self.findChild(QCheckBox, 'checkBox_3')
        if self.str_check_number_of_line=="True":
            self.checkBox_1.setChecked(True)
        else:
            self.checkBox_1.setChecked(False)
        if self.str_allow_extra_column=="True":
            self.checkBox_2.setChecked(True)
        else:
            self.checkBox_2.setChecked(False)
        if self.str_pop_message_box=="True":
            self.checkBox_3.setChecked(True)
        else:
            self.checkBox_3.setChecked(False)


        self.workflow_id_input = self.findChild(QLineEdit, 'WorkflowId')
        self.workflow_id_input.setPlaceholderText("Workflow ID")
        self.workflow_id_input.setText(self.workflow_id)
        self.workflow_id_input.editingFinished.connect(self.update_settings)



        self.checkBox_1.stateChanged.connect(self.update_checkBox_1)
        self.checkBox_2.stateChanged.connect(self.update_checkBox_2)
        self.checkBox_3.stateChanged.connect(self.update_checkBox_3)



    def run(self):
        self.error("")
        self.warning("")
        if self.data is None:
            self.error("you need a data_in")
            return
        if self.str_col_description=="":
            self.error("you need to set a data_in_reference")
            return
        result=MetManagement.describe_orange_table(self.data)
        if result is None:
            self.error("error during reading data_in")
            return
        # verification du nombre de ligne si on l a specifié
        if self.str_check_number_of_line=="True":
            if result[0]!=int(self.str_nb_line_data_in_reference):
                return self.this_widget_in_error("number of line invalid "+str(result[0])+"!="+self.str_nb_line_data_in_reference)

        col_description_reference=json.loads(self.str_col_description)
        col_description_in_data = result[1]

        def compare_cols(cols1, cols2):
            """
            Compare deux listes de colonnes (dicts {name, kind, var_type}).
            Retourne un tuple:
              - commons : éléments présents dans les deux listes
              - only1   : éléments présents seulement dans cols1
              - only2   : éléments présents seulement dans cols2
            """
            # On convertit chaque dict en tuple trié pour qu'il soit hashable
            set1 = {tuple(sorted(d.items())) for d in cols1}
            set2 = {tuple(sorted(d.items())) for d in cols2}

            commons = set1 & set2
            only1 = set1 - set2
            only2 = set2 - set1

            # On retransforme en dicts pour rester lisible
            def back_to_dicts(s):
                return [dict(t) for t in s]

            return back_to_dicts(commons), back_to_dicts(only1), back_to_dicts(only2)

        _, only1, only2 = compare_cols(col_description_reference, col_description_in_data)
        if len(only1) > 0:
            if len(only2) > 0:
                return self.this_widget_in_error(
                    "missing column" + str(only1) + " ++++ column not in reference -> " + str(only2))
            return self.this_widget_in_error(
                "missing column" + str(only1))
        if len(only2) > 0:
            if self.str_allow_extra_column != "True":
                return self.this_widget_in_error("column not in reference -> " + str(only2))
        if self.workflow_id != "":
            path_file = MetManagement.get_api_local_folder(workflow_id=self.workflow_id)
            # Execution of the workflow
            if os.path.exists(path_file + "config.json"):
                # remove time out
                MetManagement.write_file_time(path_file + "time.txt")
        self.Outputs.data.send(self.data)
        self.Outputs.data_out_error.send(None)

        return
    def this_widget_in_error(self,error_message):
        self.error(error_message)
        if self.str_pop_message_box =="True":
            if os.name=='nt':
                windows_utils.BoxMessage(error_message, 0, "Error")
            elif  sys.platform.startswith("Darwin") or sys.platform.startswith("darwin") :
                return mac_utils.BoxMessage_macos(error_message, 0, "Error")
            else:
                SimpleDialogQt.BoxError(error_message)
        if self.workflow_id!="":
            path_file = MetManagement.get_api_local_folder(workflow_id=self.workflow_id)
            # Execution of the workflow
            if os.path.exists(path_file + "config.json"):
                # time out
                MetManagement.write_file_arbitrary_time(path_file + "time.txt", "1")
        self.Outputs.data.send(None)
        self.Outputs.data_out_error.send(MetManagement.create_trigger_table())
        return


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWControl()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
