import os
import sys
import Orange.data
from AnyQt.QtWidgets import QPushButton, QApplication, QRadioButton, QComboBox, QCheckBox, QSpinBox, QLabel, QFileDialog, QLineEdit
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
    from Orange.widgets.orangecontrib.IO4IT.utils.pst_extractor.export_pst import export_pst_folder
else:
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.IO4IT.utils import mail
    from orangecontrib.IO4IT.utils import keys_manager
    from orangecontrib.AAIT.utils import MetManagement
    from orangecontrib.IO4IT.utils.pst_extractor.export_pst import export_pst_folder

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

    # --- Persisted settings ---
    type_co: str = Setting("")
    your_email_conf: str = Setting("")
    send_mail: str = Setting("False")
    sort_order: str = Setting("Ascending")
    read_all: bool = Setting(True)
    email_count: int = Setting(10)
    pst_folder: str = Setting("")

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    # ------------------------------------------------------------------
    # Qt → Settings synchronisation helpers
    # ------------------------------------------------------------------

    def on_text_changed(self, new_text):
        if new_text == self.type_co:
            return
        self.update_setting_from_qt_view()
        visible = (self.type_co == "ARCHIVE PST")
        self.lineEdit_pst_folder.setVisible(visible)
        self.pushButton_browse_pst.setVisible(visible)

    def on_text_changed2(self):
        self.your_email_conf = str(self.comboBox2.currentText())

    def on_sort_order_changed(self):
        self.sort_order = str(self.comboBox_sort_order.currentText())

    def on_read_all_toggled(self, checked: bool):
        self.read_all = checked
        self._update_email_count_visibility()

    def on_email_count_changed(self, value: int):
        self.email_count = value

    def select_pst_folder(self):
        if self.type_co != "ARCHIVE PST":
            return

        folder = QFileDialog.getExistingDirectory(self, "Select PST folder")

        if folder:
            self.pst_folder = folder
            self.lineEdit_pst_folder.setText(folder)


    # ------------------------------------------------------------------
    # Show / hide the "number of emails" widgets depending on read_all
    # ------------------------------------------------------------------

    def _update_email_count_visibility(self):
        visible = not self.read_all
        self.label_email_count.setVisible(visible)
        self.spinBox_email_count.setVisible(visible)

    # ------------------------------------------------------------------
    # Full Qt-view ↔ settings sync
    # ------------------------------------------------------------------

    def update_qt_view_from_settings(self):
        # Read / Send radio buttons
        if str(self.send_mail) == "True":
            self.radioButton.setChecked(False)
            self.radioButton2.setChecked(True)
        else:
            self.radioButton.setChecked(True)
            self.radioButton2.setChecked(False)

        # Connection type combobox
        index = self.comboBox.findText(str(self.type_co))
        self.comboBox.setCurrentIndex(index if index != -1 else 0)

        # Configuration file combobox
        if self.type_co not in ("", "ARCHIVE PST"):
            self.comboBox2.show()
            self.comboBox2.clear()

            try:
                offusc_conf_agents = mail.list_conf_files(self.type_co)
            except FileNotFoundError:
                offusc_conf_agents = []

            self.comboBox2.addItems(offusc_conf_agents)

            index1 = self.comboBox2.findText(str(self.your_email_conf))
            self.comboBox2.setCurrentIndex(index1 if index1 != -1 else 0)
        else:
            self.comboBox2.clear()
            self.comboBox2.hide()

        # Sort order combobox
        idx_sort = self.comboBox_sort_order.findText(str(self.sort_order))
        self.comboBox_sort_order.setCurrentIndex(idx_sort if idx_sort != -1 else 0)

        # Read all checkbox + email count spinbox
        self.checkBox_read_all.setChecked(self.read_all)
        self.spinBox_email_count.setValue(self.email_count)
        self._update_email_count_visibility()
        self.lineEdit_pst_folder.setText(self.pst_folder)

    def update_setting_from_qt_view(self):
        self.type_co = str(self.comboBox.currentText())

        if self.type_co in ("", "ARCHIVE PST"):
            self.comboBox2.hide()
        else:
            self.comboBox2.show()
            self.comboBox2.clear()
            offusc_conf_agents = mail.list_conf_files(self.type_co)
            self.comboBox2.addItems(offusc_conf_agents)

        self.send_mail = False if self.radioButton.isChecked() else True
        self.sort_order = str(self.comboBox_sort_order.currentText())
        self.read_all = self.checkBox_read_all.isChecked()
        self.email_count = self.spinBox_email_count.value()
        self.pst_folder = self.lineEdit_pst_folder.text()

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def __init__(self):
        super().__init__()

        self.setFixedWidth(700)
        self.setFixedHeight(480)
        uic.loadUi(self.gui, self)

        # Existing widgets
        self.comboBox = self.findChild(QComboBox, 'comboBox')
        self.comboBox2 = self.findChild(QComboBox, 'comboBox_2')
        self.radioButton = self.findChild(QRadioButton, 'radioButton')
        self.radioButton2 = self.findChild(QRadioButton, 'radioButton_2')
        self.pushButton = self.findChild(QPushButton, 'pushButton')

        # New widgets
        self.comboBox_sort_order = self.findChild(QComboBox, 'comboBox_sort_order')
        self.checkBox_read_all = self.findChild(QCheckBox, 'checkBox_read_all')
        self.spinBox_email_count = self.findChild(QSpinBox, 'spinBox_email_count')
        self.label_email_count = self.findChild(QLabel, 'label_email_count')
        self.pushButton_browse_pst = self.findChild(QPushButton, "pushButton_browse_pst")
        self.lineEdit_pst_folder = self.findChild(QLineEdit, "lineEdit_pst_folder")
        self.pushButton_browse_pst.clicked.connect(self.select_pst_folder)

        # Populate connection type combobox
        types_co = [
            "",
            "IMAP4_SSL",
            "MICROSOFT_EXCHANGE_OWA",
            "MICROSOFT_EXCHANGE_OAUTH2",
            "MICROSOFT_EXCHANGE_OAUTH2_MICROSOFT_GRAPH",
            "ARCHIVE PST",
        ]
        self.comboBox.addItems(types_co)

        # Populate sort order combobox
        self.comboBox_sort_order.addItems(["Ascending", "Descending"])

        # Connect signals
        self.comboBox.currentTextChanged.connect(self.on_text_changed)
        self.comboBox2.hide()
        self.comboBox2.currentTextChanged.connect(self.on_text_changed2)
        self.radioButton.clicked.connect(self.update_setting_from_qt_view)
        self.radioButton2.clicked.connect(self.update_setting_from_qt_view)
        self.comboBox_sort_order.currentTextChanged.connect(self.on_sort_order_changed)
        self.checkBox_read_all.toggled.connect(self.on_read_all_toggled)
        self.spinBox_email_count.valueChanged.connect(self.on_email_count_changed)
        self.pushButton.clicked.connect(self.run)

        self.thread = None
        self.data = None
        self.data_to_send = None
        self.input_dir = None
        self.output_dir = None

        self.post_initialized()

        
        self.update_qt_view_from_settings()

    # ------------------------------------------------------------------
    # Data input
    # ------------------------------------------------------------------

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        self.run()

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _run_mail_daemonizer(self):
        self.data_to_send = self.data
        
        if self.type_co == "ARCHIVE PST":
            output_dir = export_pst_folder(self.pst_folder)
            output_dir_domain = StringVariable("output_dir")

            domain = Domain([], metas=[output_dir_domain])
            self.data_to_send = Table.from_list(domain, [[str(output_dir)]])
            return

        if self.send_mail == True:
            mail.check_send_new_emails(self.your_email_conf, self.type_co)
        else:
            try:
                agent = ""
                if self.type_co == "IMAP4_SSL":
                    agent, _, _, _, alias, _, _, _, _ = keys_manager.lire_config_imap4_ssl(self.your_email_conf)
                    if alias != "":
                        agent = alias
                if self.type_co == "MICROSOFT_EXCHANGE_OWA":
                    _, agent, _, _, _, _ = keys_manager.lire_config_owa(self.your_email_conf)
                if self.type_co in ("MICROSOFT_EXCHANGE_OAUTH2", "MICROSOFT_EXCHANGE_OAUTH2_MICROSOFT_GRAPH"):
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
                        domain = Domain([], metas=[input_dir_domain, output_dir_domain])
                        self.data_to_send = Table.from_list(domain, [[self.input_dir, self.output_dir]])

            except Exception as e:
                self.error("An error occurred : ", e)
                return

            sort_ascending = (self.sort_order == "Ascending")
            max_emails = None if self.read_all else self.email_count

            mail.check_new_emails(
                self.your_email_conf,
                self.type_co,
                ascending=sort_ascending,
                max_emails=max_emails,
            )

        return

    # ------------------------------------------------------------------
    # Thread management
    # ------------------------------------------------------------------

    def run(self):
        if self.thread is not None:
            self.thread.safe_quit()

        if self.type_co == "ARCHIVE PST":
            self.pst_folder = self.lineEdit_pst_folder.text()
            if self.pst_folder == "":
                print(f"PST folder : {self.pst_folder}")
                self.error("You need to select a PST folder")
                return
        else:
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
