import os
import sys
import Orange.data
from AnyQt.QtWidgets import QPushButton, QApplication, QRadioButton, QComboBox
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting
from Orange.data import StringVariable
from Orange.data import Domain
from Orange.data import Table


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.IO4IT.utils import mail
    from Orange.widgets.orangecontrib.IO4IT.utils import keys_manager
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
else:
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.IO4IT.utils import mail
    from orangecontrib.IO4IT.utils import keys_manager
    from orangecontrib.AAIT.utils import MetManagement

class OWInboxMailMonitoring(widget.OWWidget):
    name = "InboxMailMonitoring"
    description = "Runs daemonizer_no_input_output in a thread; passes data through."
    icon = "icons/monitor-email.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/monitor-email.svg"
    priority = 1091
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owinboxmailmonitoring.ui")
    want_control_area = False
    category = "AAIT - API"
    type_co:str=Setting("")
    your_email_conf: str = Setting("")
    send_mail = Setting("False")

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    def on_text_changed(self,new_text):
        if new_text == self.type_co:
            return  # Rien à faire, pas de vrai changement
        self.update_setting_from_qt_view()

    def on_text_changed2(self):
        self.your_email_conf = str(self.comboBox2.currentText())

    def update_qt_view_from_settings(self):
        if str(self.send_mail) == "True":
            self.radioButton.setChecked(False)
            self.radioButton2.setChecked(True)
        else:
            self.radioButton.setChecked(True)
            self.radioButton2.setChecked(False)

        index = self.comboBox.findText(str(self.type_co))
        if index != -1:
            self.comboBox.setCurrentIndex(index)
        else:
            self.comboBox.setCurrentIndex(0)
        if self.type_co != "":
            self.comboBox2.show()
            offusc_conf_agents = mail.list_conf_files(self.type_co)
            self.comboBox2.addItems(offusc_conf_agents)
            index1 = self.comboBox2.findText(str(self.your_email_conf))
            if index1 != -1:
                self.comboBox2.setCurrentIndex(index1)
            else:
                self.comboBox2.setCurrentIndex(0)

    def update_setting_from_qt_view(self):
        self.type_co=str(self.comboBox.currentText())
        if self.type_co == "":
            self.comboBox2.hide()
        if self.type_co !="":
            self.comboBox2.show()
            self.comboBox2.clear()
            offusc_conf_agents = mail.list_conf_files(self.type_co)
            self.comboBox2.addItems(offusc_conf_agents)
        if self.radioButton.isChecked():
            self.send_mail = False
        else:
            self.send_mail = True

    def __init__(self):
        super().__init__()

        self.setFixedWidth(700)
        self.setFixedHeight(400)
        uic.loadUi(self.gui, self)

        self.comboBox = self.findChild(QComboBox, 'comboBox')
        self.comboBox2 = self.findChild(QComboBox, 'comboBox_2')
        self.radioButton = self.findChild(QRadioButton, 'radioButton')
        self.radioButton2 = self.findChild(QRadioButton, 'radioButton_2')
        self.pushButton = self.findChild(QPushButton, 'pushButton')

        types_co = [
            "",
            "IMAP4_SSL",
            "MICROSOFT_EXCHANGE_OWA",
            "MICROSOFT_EXCHANGE_OAUTH2",
            "MICROSOFT_EXCHANGE_OAUTH2_MICROSOFT_GRAPH"
        ]

        self.comboBox.addItems(types_co)
        self.comboBox.currentTextChanged.connect(self.on_text_changed)
        self.comboBox2.hide()
        self.comboBox2.currentTextChanged.connect(self.on_text_changed2)
        self.radioButton.clicked.connect(self.update_setting_from_qt_view)
        self.radioButton2.clicked.connect(self.update_setting_from_qt_view)
        self.pushButton.clicked.connect(self.run)
        self.thread = None
        self.data = None
        self.data_to_send = None
        self.input_dir  = None
        self.output_dir = None
        self.post_initialized()
        self.update_qt_view_from_settings()


    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        self.run()

    def _run_mail_daemonizer(self):
        self.data_to_send = self.data
        if self.send_mail == True:
            mail.check_send_new_emails(self.your_email_conf, self.type_co)
        #lecture des mails on va lire la config en rapport pour renvoyer le dossier d'envoi et de reception
        else:
            try:
                agent = ""
                if self.type_co == "IMAP4_SSL":
                    agent, _, _, _, alias = keys_manager.lire_config_imap4_ssl(self.your_email_conf)
                    if alias != "":
                        agent = alias
                if self.type_co == "MICROSOFT_EXCHANGE_OWA":
                    _, agent, _, _, _, _ = keys_manager.lire_config_owa(self.your_email_conf)
                if self.type_co == "MICROSOFT_EXCHANGE_OAUTH2" or self.type_co == "MICROSOFT_EXCHANGE_OAUTH2_MICROSOFT_GRAPH":
                    _, _, _, agent = keys_manager.lire_config_oauth2(self.your_email_conf, type=self.type_co)
                if agent != "":
                    chemin_dossier = MetManagement.get_path_mailFolder()
                    self.input_dir = chemin_dossier + str(agent) + "/in"
                    self.output_dir = chemin_dossier + str(agent) + "/out"
                    input_dir_domain = StringVariable("input_dir")
                    output_dir_domain = StringVariable("output_dir")
                    if not os.path.isdir(self.input_dir):
                        os.makedirs(self.input_dir)
                    if not os.path.isdir(self.output_dir):
                        os.makedirs(self.output_dir)
                    if self.data_to_send is not None:
                        self.data_to_send = self.data_to_send.add_column(input_dir_domain, [self.input_dir])
                        self.data_to_send = self.data_to_send.add_column(output_dir_domain, [self.output_dir])
                    else:
                        domain=Domain([],metas=[input_dir_domain,output_dir_domain])
                        self.data_to_send =Table.from_list(domain,[[self.input_dir,self.output_dir]])
            except Exception as e:
                self.error("An error occurred : ", e)
                return
            mail.check_new_emails(self.your_email_conf, self.type_co)
        return

    def run(self):
        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()


        if self.your_email_conf == "":
            self.error("You need to select a configuration file")
            return

        if self.type_co == "":
            self.error("You need to select a type of connection")
            return

        self.error("")
        self.progressBarInit()
        self.thread = thread_management.Thread(self._run_mail_daemonizer)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self):
        try:
            self.Outputs.data.send(self.data_to_send)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        self.progressBarFinished()

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = OWInboxMailMonitoring()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()




