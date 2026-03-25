import os
import sys
import time
import json
import Orange
from Orange.widgets.widget import OWWidget, Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QLineEdit,QApplication
from AnyQt.QtWidgets import QCheckBox, QPushButton

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement,SimpleDialogQt
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert, server_uvicorn
    from Orange.widgets.orangecontrib.HLIT_dev.utils import hlit_python_api
else:
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import MetManagement,SimpleDialogQt
    from orangecontrib.HLIT_dev.remote_server_smb import convert, server_uvicorn
    from orangecontrib.HLIT_dev.utils import hlit_python_api

class InputInterface(OWWidget):
    name = "Input Interface"
    description = "Send data to a local interface"
    icon = "icons/input_interface.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/input_interface.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/input_interface.ui")
    priority = 3000
    input_id = Setting("")
    workflow_id = Setting("")
    help_description = Setting("")
    widget_input_uuid=Setting("")
    expected_input = Setting("")
    want_control_area = False
    category = "AAIT - API"
    Automatically_start_API=Setting("True")
    Automatically_open_interface = Setting("False")


    class Inputs:
        data = Input("Data in example", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.error("")
        if in_data is None:
            return
        self.expected_input = ""
        if in_data is not None:
            result=convert.convert_data_table_to_json_explicite(in_data, self.input_id) # a caster en explcite json
            if result==None:
                self.error("error cant cast datatable to json")
                return
            self.expected_input={"workflow_id":self.workflow_id,"data":[result]}
            self.send_data_example()

    class Outputs:
        data = Output("Data", Orange.data.Table)
        signal_ready_do_work = Output("is ready do work", str, auto_summary=False)
        data_out_exemple = Output("Data out example", Orange.data.Table)

    def __init__(self):
        super().__init__()
        self.data = None
        if str(self.widget_input_uuid)=="":
            self.widget_input_uuid=MetManagement.generate_unique_id_from_mac_timestamp()
        # Qt Management
        self.setFixedWidth(700)
        self.setFixedHeight(400)
        uic.loadUi(self.gui, self)

        self.check_box_automatically_start_api= self.findChild(QCheckBox, 'checkBox')
        self.check_box_automatically_open_interface = self.findChild(QCheckBox, 'checkBox_2')

        if self.Automatically_start_API == "True":
            self.check_box_automatically_start_api.setChecked(True)
            self.start_api()

        if self.Automatically_open_interface == "True":
            self.check_box_automatically_open_interface.setChecked(True)

        self.check_box_automatically_start_api.stateChanged.connect(self.on_checkbox_start_api_toggled)
        self.check_box_automatically_open_interface.stateChanged.connect(self.on_checkbox_start_interface_toggled)

        self.pushButton_start_api=self.findChild(QPushButton, 'pushButton')
        self.pushButton_start_api.clicked.connect(self.start_api)
        self.pushButton_quit_api = self.findChild(QPushButton, 'pushButton_3')
        self.pushButton_quit_api.clicked.connect(self.quit_api)
        self.pushButton_send_data_as_data_exemple=self.findChild(QPushButton, 'pushButton_4')
        self.pushButton_send_data_as_data_exemple.clicked.connect(self.send_data_as_data_exemple)


        #self.input_id_input = QLineEdit(self)
        self.input_id_input = self.findChild(QLineEdit, 'InputId')
        self.input_id_input.setPlaceholderText("Input Id")
        self.input_id_input.setText(self.input_id)
        self.input_id_input.editingFinished.connect(self.update_settings)
        #gui.widgetBox(self.controlArea, orientation='vertical').layout().addWidget(self.input_id_input)

        #self.workflow_id_input = QLineEdit(self)
        self.workflow_id_input = self.findChild(QLineEdit, 'WorkflowId')
        self.workflow_id_input.setPlaceholderText("Workflow ID")
        self.workflow_id_input.setText(self.workflow_id)
        self.workflow_id_input.editingFinished.connect(self.update_settings)
        #gui.widgetBox(self.controlArea, orientation='vertical').layout().addWidget(self.workflow_id_input)

        self.description_input = self.findChild(QLineEdit, 'Description')
        self.description_input.setText(self.help_description)
        self.description_input.editingFinished.connect(self.update_settings)
        self.send_data_example()
        self.signal_ready_do_work()
        self.thread = None
        self.run()

    def on_checkbox_start_api_toggled(self,state):
        if state==0:
            self.Automatically_start_API = "False"
            return
        self.Automatically_start_API = "True"
    def on_checkbox_start_interface_toggled(self,state):
        if state==0:
            self.Automatically_open_interface = "False"
            return
        self.Automatically_open_interface = "True"
    def start_api(self):
        if not server_uvicorn.is_port_in_use("127.0.0.1", 8000, timeout=10):
            hlit_python_api.start_api_in_new_terminal()

    def quit_api(self):
        res=hlit_python_api.exit_server("127.0.0.1:8000")
        to_print="Server exiting without error (terminal still open)"
        if res!=0:
            to_print="Cannot disconnect the server (it may not have been running - please check the logs for details)"
        SimpleDialogQt.BoxInfo(to_print)

    def signal_ready_do_work(self):
        self.Outputs.signal_ready_do_work.send(str(self.widget_input_uuid))
    def update_settings(self):
        self.input_id = self.input_id_input.text()
        self.workflow_id = self.workflow_id_input.text()
        self.help_description = self.description_input.text()
        self.signal_ready_do_work()
        if self.workflow_id != "" and self.input_id != "":
            if self.expected_input !="":
                self.expected_input = {"workflow_id": self.workflow_id, "data": [{"num_input": self.input_id, "values":self.expected_input["data"][0]["values"]}]}
            if self.thread is None:
                self.run()


    def check_file_exists(self, path):
        while not os.path.exists(path +".ok") or not os.path.exists(path + "input_data_" + self.input_id + ".tab"):
            time.sleep(1)

    def execute(self):
        path_file = MetManagement.get_api_local_folder(workflow_id=self.workflow_id)
        self.check_file_exists(path_file)
        # Execution of the workflow
        if not os.path.exists(path_file + "config.json"):
            self.error("Le fichier 'config.json' n'existe pas.")
            return

        with open(path_file + "config.json", "r", encoding="utf-8") as file:
            data = json.load(file)

        data_table_path = ""
        if self.workflow_id == data["workflow_id"]:
            for input in data["data_config"]:
                if self.input_id == str(input["num_input"]):
                    data_table_path = input["path"]

        if data_table_path == "" or not os.path.exists(path_file + data_table_path):
            #self.information("Le fichier input n'existe pas.")
            return

        out_data = Orange.data.Table(path_file + data_table_path)
        #suppression du fichier d'entrée après utilisation
        MetManagement.reset_files([path_file + data_table_path])
        return out_data

    def send_data_example(self):
        if self.expected_input=="":
             return
        if 'data' in self.expected_input:
            table = convert.convert_json_to_orange_data_table(self.expected_input["data"][0])
            self.Outputs.data_out_exemple.send(table)

    def send_data_as_data_exemple(self):
        if self.expected_input=="":
             return
        if 'data' in self.expected_input:
            table = convert.convert_json_to_orange_data_table(self.expected_input["data"][0])
            self.Outputs.data.send(table)

    def run(self):
        self.error("")
        self.warning("")

        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()

        if self.workflow_id == "" or self.input_id == "":
            self.warning("Workflow ID et/ou Input ID manquant(s).")
            return

        self.thread = thread_management.Thread(self.execute)
        self.thread.result.connect(self.handle_result)
        self.thread.finished.connect(self.run)
        self.thread.start()

    def handle_result(self, result):
        if result is None:
            self.error("error out data is None")
            return
        self.error("")
        try:
            out_data = Orange.data.Table(result)
            self.Outputs.data.send(out_data)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = InputInterface()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
