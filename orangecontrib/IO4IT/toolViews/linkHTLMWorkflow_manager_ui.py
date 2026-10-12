import os
import json
from AnyQt import QtWidgets
import sys
import ast

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert, hlit_workflow_management
else:
    from orangecontrib.AAIT.utils import MetManagement
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.HLIT_dev.remote_server_smb import convert, hlit_workflow_management

FUNCTION_NAMES = [
    "Create",
    "Update",
    "Delete"
]

class LinkWorkflowManagerUI(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        the_gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/link_workflow_manager_ui.ui")
        the_gui=the_gui.replace("\\","/")
        uic.loadUi(the_gui, self)

        self.folder_path = None
        self.list_key_name = None
        self.list_config_html_ows = None

        # Remplir la combo
        self.comboActions.addItems(FUNCTION_NAMES)

        # signaux OK / Cancel
        self.comboActions.currentTextChanged.connect(self.on_current_text_changed)
        self.comboMode.currentTextChanged.connect(self.on_current_comboMode_changed)
        #self.pushButton_read.clicked.connect(self.populate_textDetails)
        self.pushButton_delete.clicked.connect(self.handle_delete_clicked)
        self.pushButton_write.clicked.connect(self.handle_write_clicked)
        # self.pushButton_sync.clicked.connect(self.handle_pushButton_sync_clicked)
        self.adjustSize()
        self.setFixedSize(self.size())
        self.comboMode.setVisible(False)
        self.labelMode.setVisible(False)
        self.pushButton_read.setVisible(False)
        self.pushButton_delete.setVisible(False)
        self.pushButton_write.setVisible(True)
        self.set_stdtextDetails("Create")
        self.run()

    def set_stdtextDetails(self, func_name):
        if func_name == "Create":
            self.textDetails.setText(
                '{\n"name": "",\n"description": "",\n"ows_file": "",\n"html_file": "",\n"with_gui": "True",\n"with_terminal": "True",\n"daemonizable": "True",\n"timeout_daemon": 60\n}')
        else:
            self.textDetails.setText("")

    def get_list_of_key_name(self, list_config_html_ows):
        key_name = []
        for item in list_config_html_ows:
            if "name" in item:
                key_name.append(item["name"])
        return key_name

    def create_new_config_linkHTMLWorkflow(self, new_config):
        if isinstance(new_config, str):
            new_config = json.loads(new_config)

        if not new_config.get("name") or not new_config.get("ows_file"):
            print("You need to define the name and the path to the ows file")
            return

        if ".ows" not in new_config.get("ows_file"):
            print("You need to provide a ows file")
            return

        if 0 != convert.is_valid_json_string(new_config):
            print("No valid json")
            return

        json_str = json.dumps(new_config)
        data = json.loads(json_str)
        if "name" not in list(data.keys()):
            print("You need a name in your json")
            return
        key_name = data["name"]

        if self.list_key_name != []:
            if key_name in  self.list_key_name:
                print("key name already exist")
                return

        path = self.folder_path + key_name + ".json"
        with open(path, "w") as fichier:
            json.dump([new_config], fichier, indent=4)
        self.run()

    def update_config_linkHTMLWorkflow(self, new_json):
        if str(self.comboMode.currentText()) == "":
            return

        if isinstance(new_json, str):
            try:
                new_json = ast.literal_eval(new_json)
            except Exception as e:
                print(f"Erreur de conversion : {e}")
                return
        key_name = str(self.comboMode.currentText())
        old_json = {}
        for item in self.list_config_html_ows:
            if key_name == item["name"]:
                old_json=item
        if old_json == {}:
            return
        try:
            new_list_json = []
            for item in self.list_config_html_ows:
                if old_json["fichier_json"] == item["fichier_json"]:
                    if item["name"] == old_json["name"]:
                        new_list_json.append(new_json)
                    else:
                        del item["fichier_json"]
                        new_list_json.append(item)
            path = self.folder_path + old_json["fichier_json"]
            with open(path, "w", encoding="utf-8") as fichier:
                json.dump(new_list_json, fichier, indent=4, ensure_ascii=False)
            self.run()
            self.populate_combo_mode_from_folder()
        except Exception as e:
            print(f"Erreur de conversion : {e}")
            return



    def delete_config_linkHTMLWorkflow(self):
        if str(self.comboMode.currentText()) == "":
            return
        key_name = str(self.comboMode.currentText())
        old_json = {}
        for item in self.list_config_html_ows:
            if key_name == item["name"]:
                old_json = item

        if old_json == {}:
            return

        new_list_json = []
        for item in self.list_config_html_ows:
            if old_json["fichier_json"] == item["fichier_json"]:
                if key_name != item["name"]:
                    del item["fichier_json"]
                    new_list_json.append(item)

        #Si 0 on supprime car seul dans json / Sinon on garde le json mais on retire la key_name correspondante
        if len(new_list_json) == 0:
            MetManagement.reset_files([self.folder_path+old_json["fichier_json"]])
        else:
            try:
                path = self.folder_path + old_json["fichier_json"]
                with open(path, "w", encoding="utf-8") as fichier:
                    json.dump(new_list_json, fichier, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"Erreur de conversion : {e}")
                return
        self.run()
        self.populate_combo_mode_from_folder()


    def get_config_linkHTMLWorkflow(self, key_name=""):
        config = {}
        key_name = str(self.comboMode.currentText())
        for item in self.list_config_html_ows:
            if key_name == item["name"]:
                config = item
        if config == {}:
            print("Config not found")
            return
        return config


    def run(self):
        self.folder_path = MetManagement.get_path_linkHTMLWorkflow()
        list_config_html_ows = []
        if 0 != hlit_workflow_management.read_config_ows_html_file_as_dict(list_config_html_ows):
            print("No config file found")
            self.list_config_html_ows = []
            self.set_stdtextDetails("Create")
            return
        self.list_key_name = self.get_list_of_key_name(list_config_html_ows)
        aait_store = MetManagement.get_local_store_path()

        for item in list_config_html_ows:
            item["ows_file"] = item["ows_file"].replace(aait_store, "")
            item["html_file"] = item["html_file"].replace(aait_store, "")
        self.list_config_html_ows = list_config_html_ows
        #create_new_config_linkHTMLWorkflow(new_json, folder_path, list_key_name, list_config_html_ows)
        #update_config_linkHTMLWorkflow("export_md", new_json, list_config_html_ows, folder_path)
        #delete_config_linkHTMLWorkflow("export_md", list_config_html_ows, folder_path)
        #config = get_config_linkHTMLWorkflow("test11", list_config_html_ows)

    def handle_write_clicked(self):
        current_str=str(self.textDetails.toPlainText())
        if current_str=="":
            return
        func_name = str(self.comboActions.currentText())
        if func_name == "Create":
            self.create_new_config_linkHTMLWorkflow(current_str)
        elif func_name == "Update":
            self.update_config_linkHTMLWorkflow(current_str)
        return

    def handle_delete_clicked(self):
        current_str = str(self.textDetails.toPlainText())
        if current_str == "":
            return
        func_name = str(self.comboActions.currentText())
        if func_name == "Delete":
            self.delete_config_linkHTMLWorkflow()
        return

    def on_current_text_changed(self):
        func_name = str(self.comboActions.currentText())
        self.pushButton_read.setVisible(False)
        self.pushButton_delete.setVisible(False)
        if len(self.list_config_html_ows) == 0:
            self.set_stdtextDetails("Create")
            self.comboActions.setCurrentIndex(0)
            return
        if func_name == "Create":
            self.comboMode.setVisible(False)
            self.pushButton_write.setVisible(True)
            self.set_stdtextDetails("Create")
        else:
            if func_name == "Update":
                self.pushButton_write.setVisible(True)
                self.pushButton_delete.setVisible(False)
            if func_name == "Delete":
                self.pushButton_write.setVisible(False)
                self.pushButton_delete.setVisible(True)
            self.comboMode.setVisible(True)
            self.populate_combo_mode_from_folder()

    def on_current_comboMode_changed(self):
        key_name = str(self.comboMode.currentText())
        if not key_name or key_name == "" or key_name == "Create":
            return
        json = self.get_config_linkHTMLWorkflow(key_name).copy()
        del json["fichier_json"]
        self.textDetails.setText(str(json))

    def populate_combo_mode_from_folder(self):
        # Nettoyer avant tout
        self.comboMode.clear()
        self.textDetails.setText("")
        # Peupler le combo
        for item in self.list_key_name:
            self.comboMode.addItem(item)
        self.comboMode.setCurrentIndex(0)
        self.textDetails.setText(str(self.list_config_html_ows[0]))

def main():
    app = QtWidgets.QApplication(sys.argv)
    dlg = LinkWorkflowManagerUI()
    dlg.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()

if __name__ == "__main__":
    main()
