import sys
from AnyQt import QtWidgets
import os


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.IO4IT.utils import keys_manager
    from Orange.widgets.orangecontrib.AAIT.utils.SimpleDialogQt import BoxError,BoxInfo
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.IO4IT.utils import keys_manager
    from orangecontrib.AAIT.utils.SimpleDialogQt import BoxError,BoxInfo
FUNCTION_NAMES = [
    "Create / overwrite api key",
    "Create / overwrite imap4_ssl configuration",
    "Create / overwrite nxp configuration",
    "Create / overwrite owa configuration",
    "Create / overwrite oauth2 configuration",
    "Read api key",
    "Read imap4_ssl configuration",
    "Read nxp configuration",
    "Read owa configuration",
    "Read oauth2 configuration",
]


class KeyManagerUI(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        the_gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/key_manager_ui.ui")
        the_gui=the_gui.replace("\\","/")
        uic.loadUi(the_gui, self)

        # Remplir la combo
        self.comboActions.addItems(FUNCTION_NAMES)

        # signaux OK / Cancel

        self.comboActions.currentTextChanged.connect(self.on_current_text_changed)
        self.pushButton_read.clicked.connect(self.populate_textDetails)
        self.pushButton_delete.clicked.connect(self.handle_delete_clicked)
        self.pushButton_write.clicked.connect(self.handle_write_clicked)
        self.pushButton_sync.clicked.connect(self.handle_pushButton_sync_clicked)
        self.adjustSize()
        self.setFixedSize(self.size())
        self.comboMode.setVisible(False)
        self.labelMode.setVisible(False)
        self.pushButton_read.setVisible(False)
        self.pushButton_delete.setVisible(False)
        self.set_stdtextDetails("Create / overwrite api key")


    def handle_write_clicked(self):
        current_str=str(self.textDetails.toPlainText())

        if current_str=="":
            return

        func_name = str(self.comboActions.currentText())
        if func_name in ["Create / overwrite api key", "Read api key" ]:
            try:
                keys_manager.parse_json_and_save_api(current_str)
            except Exception as e:
                print(e)
                BoxError(str(e))
                return
        elif func_name in ["Create / overwrite imap4_ssl configuration", "Read imap4_ssl configuration"]:
            try:
                keys_manager.parse_json_and_save_ssl(current_str)
            except Exception as e:
                print(e)
                BoxError(str(e))
                return
        elif func_name in ["Create / overwrite nxp configuration", "Read nxp configuration"]:
            try:
                keys_manager.parse_json_and_save_nxp(current_str)
            except Exception as e:
                print(e)
                BoxError(str(e))
                return
        elif func_name in ["Create / overwrite owa configuration", "Read owa configuration"]:
            try:
                keys_manager.parse_json_and_save_owa(current_str)
            except Exception as e:
                print(e)
                BoxError(str(e))
                return
        elif func_name in ["Create / overwrite oauth2 configuration", "Read oauth2 configuration"]:
            try:
                keys_manager.parse_json_and_save_oauth2(current_str)
            except Exception as e:
                print(e)
                BoxError(str(e))
                return
        BoxInfo("Done")



    def handle_delete_clicked(self):
        if str(self.comboMode.currentText())=="":
            return
        func_name = str(self.comboActions.currentText())
        if func_name in ["Create / overwrite api key", "Read api key"]:
            try:
                keys_manager.delete_secret("API",str(self.comboMode.currentText()))
            except Exception as e:
                print(e)
                BoxError(str(e))
                return
        elif func_name in ["Create / overwrite imap4_ssl configuration", "Read imap4_ssl configuration"]:
            try:
                keys_manager.delete_secret("IMAP4_SSL",str(self.comboMode.currentText()))
            except Exception as e:
                print(e)
                BoxError(str(e))
                return
        elif func_name in ["Create / overwrite nxp configuration", "Read nxp configuration"]:
            try:
                keys_manager.delete_secret("NXP",str(self.comboMode.currentText()))
            except Exception as e:
                print(e)
                BoxError(str(e))
                return
        elif func_name in ["Create / overwrite owa configuration", "Read owa configuration"]:
            try:
                keys_manager.delete_secret("MICROSOFT_EXCHANGE_OWA",str(self.comboMode.currentText()))
            except Exception as e:
                print(e)
                BoxError(str(e))
                return
        elif func_name in ["Create / overwrite oauth2 configuration", "Read oauth2 configuration"]:
            try:
                keys_manager.delete_secret("MICROSOFT_EXCHANGE_OAUTH2",str(self.comboMode.currentText()) )
            except Exception as e:
                print(e)
                BoxError(str(e))
                return
        else:
            BoxError("Invalid function")
            return
        if func_name == "Read api key":
            self.populate_combo_mode_from_folder(keys_manager.get_keys_dir("API"))
        elif func_name == "Read imap4_ssl configuration":
            self.populate_combo_mode_from_folder(keys_manager.get_keys_dir("IMAP4_SSL"))
        elif func_name == "Read owa configuration":
            self.populate_combo_mode_from_folder(keys_manager.get_keys_dir("MICROSOFT_EXCHANGE_OWA"))
        elif func_name == "Read nxp configuration":
            self.populate_combo_mode_from_folder(keys_manager.get_keys_dir("NXP"))
        elif func_name == "Read oauth2 configuration":
            self.populate_combo_mode_from_folder(keys_manager.get_keys_dir("MICROSOFT_EXCHANGE_OAUTH2"))
        BoxInfo("Done")

    def set_stdtextDetails(self,func_name):
        if func_name=="Create / overwrite api key":
            self.textDetails.setText("{\n'service': 'service_name',\n'api_key': 'api_key',\n'description': 'this_is_a_description'\n}")
        elif func_name=="Create / overwrite imap4_ssl configuration":
            self.textDetails.setText("{\n'agent': 'service_name',\n'alias': 'alias_name',\n'domain': '@domain.com',\n'interval_second': 1,\n'password': 'password'\n}")
        elif func_name=="Create / overwrite nxp configuration":
            self.textDetails.setText("{\n'dossier_node_id': 'bode_key',\n'serveur': 'servor_adress',\n'username': 'my_username',\n'password': 'password',\n'description': 'this is a description'\n}")
        elif func_name=="Create / overwrite owa configuration":
            self.textDetails.setText("{\n'alias': 'nom2@domain2.com',\n'interval_second': 1,\n'mail': 'nom@domain.com',\n'password_encrypted': 'password',\n'server': 'toto.titi.tata',\n'username': 'domaine\\username'\n}")
        elif func_name=="Create / overwrite oauth2 configuration":
            self.textDetails.setText("{\n'client_id': 'my_client_id',\n'client_secret':\n'my_client_secret',\n'tenant_id': 'my_guid_azure',\n'user_email': 'mail@domain.com'\n}")
        else:
            self.textDetails.setText("")
    def populate_combo_mode_from_folder(self, folder_path):
        # Nettoyer avant tout
        self.comboMode.clear()
        # Vérification du dossier
        if not folder_path or not os.path.isdir(folder_path):
            return  # dossier invalide → combo purgé, masqué
        # Recherche des fichiers .sec
        sec_files = [
            f for f in os.listdir(folder_path)
            if f.lower().endswith(".sec") and os.path.isfile(os.path.join(folder_path, f))
        ]
        # Si aucun fichier trouvé → juste retour (combo reste masqué)
        if not sec_files:
            return

        # Peupler le combo
        for filename in sec_files:
            basename = filename[:-4]  # retire ".sec"
            # stocker le vrai nom en data interne Qt
            self.comboMode.addItem(basename, filename)
        self.comboMode.setCurrentIndex(0)

    def populate_textDetails(self):
        self.textDetails.setText("")
        func_name = str(self.comboActions.currentText())
        if func_name=="":
            return
        key_name =str(self.comboMode.currentText())
        if key_name=="":
            return
        if func_name == "Read api key":
            self.textDetails.setText(str(keys_manager.lire_config_api(key_name)).replace('\\\\','\\'))
        if func_name == "Read imap4_ssl configuration":
            self.textDetails.setText(str(keys_manager.lire_config_imap4_ssl_dict_sec(key_name)).replace('\\\\','\\'))
        if func_name == "Read owa configuration":
            self.textDetails.setText(str(keys_manager.lire_config_owa_dict_sec(key_name)).replace('\\\\','\\'))
        if func_name == "Read nxp configuration":
            self.textDetails.setText(str(keys_manager.lire_config_nxp(key_name)).replace('\\\\','\\'))
        if func_name == "Read oauth2 configuration":
            self.textDetails.setText(str(keys_manager.lire_config_oauth2_dict_sec(key_name)).replace('\\\\','\\'))



    def on_current_text_changed(self):
        self.textDetails.setText("")
        func_name = str(self.comboActions.currentText())
        self.comboMode.clear()
        self.pushButton_read.setVisible(False)
        self.pushButton_delete.setVisible(False)
        if func_name  in (
            "Read api key",
            "Read imap4_ssl configuration",
            "Read owa configuration",
            "Read nxp configuration",
            "Read oauth2 configuration"
        ):
            self.textDetails.setVisible(True)
            self.pushButton_read.setVisible(True)
            self.pushButton_delete.setVisible(True)
            self.comboMode.setVisible(True)
            self.labelMode.setVisible(True)
            if func_name=="Read api key":
                self.populate_combo_mode_from_folder(keys_manager.get_keys_dir("API"))
            elif func_name=="Read imap4_ssl configuration":
                self.populate_combo_mode_from_folder(keys_manager.get_keys_dir("IMAP4_SSL"))
            elif func_name=="Read owa configuration":
                self.populate_combo_mode_from_folder(keys_manager.get_keys_dir("MICROSOFT_EXCHANGE_OWA"))
            elif func_name=="Read nxp configuration":
                self.populate_combo_mode_from_folder(keys_manager.get_keys_dir("NXP"))
            elif func_name=="Read oauth2 configuration":
                self.populate_combo_mode_from_folder(keys_manager.get_keys_dir("MICROSOFT_EXCHANGE_OAUTH2"))



            self.textDetails.setVisible(True)
        else:
            self.set_stdtextDetails(func_name)
            self.comboMode.setVisible(False)
            self.labelMode.setVisible(False)


    def handle_pushButton_sync_clicked(self):
        keys_manager.recreate_all_sec_file()
        BoxInfo("Done")



def main():
    app = QtWidgets.QApplication(sys.argv)
    dlg = KeyManagerUI()
    dlg.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()




if __name__ == "__main__":
    main()
