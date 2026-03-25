import os
from AnyQt.QtWidgets import QPushButton, QApplication, QRadioButton, QCheckBox,QSpinBox, QLineEdit

from Orange.widgets.settings import Setting
from Orange.widgets.widget import OWWidget, Output, Input
from Orange.data import Table
from AnyQt.QtCore import QTimer
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import OperationSystem, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.unlink_table_domain import unlink_domain
else:
    from orangecontrib.AAIT.utils import OperationSystem, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.AAIT.utils.unlink_table_domain import unlink_domain



class OwOperationSystem(OWWidget):
    name = "Operation System"
    description = "Basic operation on file and folder: delete copy/paste etc"
    icon = "icons/operationSystem.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/operationSystem.png"
    category = "AAIT - TOOLBOX"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_OperationSystem.ui")
    priority = 10
    want_control_area = False

    class Inputs:
        input_table = Input("in data", Table)

    class Outputs:
        data = Output("out data", Table)

    str_spinBox: str = Setting("1")
    str_autosend: str = Setting("True")
    str_radio_box_checked=Setting("0")
    str_proxy: str = Setting("")

    @Inputs.input_table
    def input_table(self, data):
        self.error("")
        self.in_data = data
        if data is not None:
            if self.str_autosend=="True":
                self.run()


    def update_setting_from_qt_view(self):
        self.str_spinBox=str(self.spinBox.value())
        if self.checkBox_autosend.isChecked():
            self.str_autosend="True"
        else:
            self.str_autosend="False"
        if self.radioButton_deleteFoldersFiles.isChecked():
            self.str_radio_box_checked="0"
        if self.radioButton_createFolders.isChecked():
            self.str_radio_box_checked="1"
        if self.radioButton_moveRenamme.isChecked():
            self.str_radio_box_checked="2"
        if self.radioButton_copy.isChecked():
            self.str_radio_box_checked="3"
        if self.radioButton_sleep.isChecked():
            self.str_radio_box_checked="4"
        if self.radioButton_setProxy.isChecked():
            self.str_radio_box_checked="5"
        if self.radioButton_unlink_all_variable.isChecked():
            self.str_radio_box_checked="6"


    def __init__(self):
        super().__init__()
        self.selected_path = ""
        self.in_data = None
        self.thread = None

        self.setFixedWidth(700)
        self.setFixedHeight(400)
        uic.loadUi(self.gui, self)
        self.pushButton=self.findChild(QPushButton, 'pushButton')
        self.radioButton_deleteFoldersFiles=self.findChild(QRadioButton, 'radioButton_deleteFoldersFiles')
        self.radioButton_createFolders = self.findChild(QRadioButton, 'radioButton_createFolders')
        self.radioButton_moveRenamme = self.findChild(QRadioButton, 'radioButton_moveRenamme')
        self.radioButton_copy = self.findChild(QRadioButton, 'radioButton_copy')
        self.radioButton_sleep = self.findChild(QRadioButton, 'radioButton_sleep')
        self.radioButton_setProxy = self.findChild(QRadioButton, 'radioButton_setProxy')
        self.spinBox = self.findChild(QSpinBox, 'spinBox')
        self.checkBox_autosend= self.findChild(QCheckBox, 'checkBox_autosend')
        self.radioButton_unlink_all_variable=self.findChild(QRadioButton, 'radioButton_unlink_all_variable')
        self.spinBox.setValue(int(self.str_spinBox))

        self.edit_proxy = self.findChild(QLineEdit, 'lineEdit')
        self.edit_proxy.setPlaceholderText("")
        self.edit_proxy.setText(self.str_proxy)
        self.edit_proxy.editingFinished.connect(self.update_parameters)

        if self.str_autosend=="True":
            self.checkBox_autosend.setChecked(True)
        else:
            self.checkBox_autosend.setChecked(False)
        if self.str_radio_box_checked=="0":
            self.radioButton_deleteFoldersFiles.setChecked(True)
            self.radioButton_createFolders.setChecked(False)
            self.radioButton_moveRenamme.setChecked(False)
            self.radioButton_copy.setChecked(False)
            self.radioButton_sleep.setChecked(False)
            self.radioButton_setProxy.setChecked(False)
            self.radioButton_unlink_all_variable.setChecked(False)

        if self.str_radio_box_checked=="1":
            self.radioButton_deleteFoldersFiles.setChecked(False)
            self.radioButton_createFolders.setChecked(True)
            self.radioButton_moveRenamme.setChecked(False)
            self.radioButton_copy.setChecked(False)
            self.radioButton_sleep.setChecked(False)
            self.radioButton_setProxy.setChecked(False)
            self.radioButton_unlink_all_variable.setChecked(False)

        if self.str_radio_box_checked=="2":
            self.radioButton_deleteFoldersFiles.setChecked(False)
            self.radioButton_createFolders.setChecked(False)
            self.radioButton_moveRenamme.setChecked(True)
            self.radioButton_copy.setChecked(False)
            self.radioButton_sleep.setChecked(False)
            self.radioButton_setProxy.setChecked(False)
            self.radioButton_unlink_all_variable.setChecked(False)

        if self.str_radio_box_checked=="3":
            self.radioButton_deleteFoldersFiles.setChecked(False)
            self.radioButton_createFolders.setChecked(False)
            self.radioButton_moveRenamme.setChecked(False)
            self.radioButton_copy.setChecked(True)
            self.radioButton_sleep.setChecked(False)
            self.radioButton_setProxy.setChecked(False)
            self.radioButton_unlink_all_variable.setChecked(False)

        if self.str_radio_box_checked == "4":
            self.radioButton_deleteFoldersFiles.setChecked(False)
            self.radioButton_createFolders.setChecked(False)
            self.radioButton_moveRenamme.setChecked(False)
            self.radioButton_copy.setChecked(False)
            self.radioButton_sleep.setChecked(True)
            self.radioButton_setProxy.setChecked(False)
            self.radioButton_unlink_all_variable.setChecked(False)

        if self.str_radio_box_checked == "5":
            self.radioButton_deleteFoldersFiles.setChecked(False)
            self.radioButton_createFolders.setChecked(False)
            self.radioButton_moveRenamme.setChecked(False)
            self.radioButton_copy.setChecked(False)
            self.radioButton_sleep.setChecked(False)
            self.radioButton_setProxy.setChecked(True)
            self.radioButton_unlink_all_variable.setChecked(False)

        if self.str_radio_box_checked == "6":
            self.radioButton_deleteFoldersFiles.setChecked(False)
            self.radioButton_createFolders.setChecked(False)
            self.radioButton_moveRenamme.setChecked(False)
            self.radioButton_copy.setChecked(False)
            self.radioButton_sleep.setChecked(False)
            self.radioButton_setProxy.setChecked(False)
            self.radioButton_unlink_all_variable.setChecked(True)

        self.radioButton_deleteFoldersFiles.clicked.connect(self.update_setting_from_qt_view)
        self.radioButton_createFolders.clicked.connect(self.update_setting_from_qt_view)
        self.radioButton_moveRenamme.clicked.connect(self.update_setting_from_qt_view)
        self.radioButton_copy.clicked.connect(self.update_setting_from_qt_view)
        self.radioButton_sleep.clicked.connect(self.update_setting_from_qt_view)
        self.radioButton_setProxy.clicked.connect(self.update_setting_from_qt_view)
        self.radioButton_unlink_all_variable.clicked.connect(self.update_setting_from_qt_view)
        self.spinBox.valueChanged.connect(self.update_setting_from_qt_view)
        self.checkBox_autosend.clicked.connect(self.update_setting_from_qt_view)


        self.pushButton.clicked.connect(self.run)
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def update_parameters(self):
        self.str_proxy = (self.edit_proxy.text() or "").strip()

    def run(self):
        if self.thread is not None:
            self.thread.safe_quit()
        if self.in_data is None:
            self.Outputs.data.send(None)
            return

        self.error("")
        if self.str_radio_box_checked == "6":
            self.Outputs.data.send(unlink_domain(self.in_data))
            return

        # time peut importe l entree
        if self.str_radio_box_checked == "4":
            self.progressBarInit()
            self.thread = thread_management.Thread(OperationSystem.sleep_seconds, int(self.str_spinBox))
            self.thread.progress.connect(self.handle_progress)
            self.thread.result.connect(self.handle_result)
            self.thread.finish.connect(self.handle_finish)
            self.thread.start()
            return
        self.error("")
        if self.str_radio_box_checked == "5":
            self.progressBarInit()
            self.thread = thread_management.Thread(OperationSystem.set_proxy,self.str_proxy)
            self.thread.progress.connect(self.handle_progress)
            self.thread.result.connect(self.handle_result)
            self.thread.finish.connect(self.handle_finish)
            self.thread.start()
            return
        self.error("")
        try:
            self.in_data.domain["input"]
        except KeyError:
            self.error('You need a "input" column in input data')
            self.Outputs.data.send(None)
            return

        if type(self.in_data.domain["input"]).__name__ != 'StringVariable':
            self.error('"input" column needs to be a Text')
            return
        # liste en ignorant les valeurs manquante
        input_paths = [str(x) for x in self.in_data.get_column("input") if x is not None and str(x).strip() != ""]
        if len(input_paths)==0:
            self.error('"input" needs paths')
            return
        if self.str_radio_box_checked == "0":
            self.progressBarInit()
            self.thread = thread_management.Thread(OperationSystem.DeleteFolderlistOrFilelist, input_paths)
            self.thread.progress.connect(self.handle_progress)
            self.thread.result.connect(self.handle_result)
            self.thread.finish.connect(self.handle_finish)
            self.thread.start()
            return
        if self.str_radio_box_checked == "1":
            self.progressBarInit()
            self.thread = thread_management.Thread(OperationSystem.ensure_dirs, input_paths)
            self.thread.progress.connect(self.handle_progress)
            self.thread.result.connect(self.handle_result)
            self.thread.finish.connect(self.handle_finish)
            self.thread.start()
            return

        try:
            self.in_data.domain["output"]
        except KeyError:
            self.error('You need a "output" column in input data')
            return

        if type(self.in_data.domain["output"]).__name__ != 'StringVariable':
            self.error('"output" column needs to be a Text')
            return
        outputs_paths = [str(x) for x in self.in_data.get_column("output") if x is not None and str(x).strip() != ""]
        if len(input_paths)!=len(outputs_paths):
            self.error('"input" and "outputs" needs same dimensions')
            return
        if self.str_radio_box_checked == "2":
            self.progressBarInit()
            self.thread = thread_management.Thread(OperationSystem.move_or_rename, input_paths,outputs_paths)
            self.thread.progress.connect(self.handle_progress)
            self.thread.result.connect(self.handle_result)
            self.thread.finish.connect(self.handle_finish)
            self.thread.start()
            return
        if self.str_radio_box_checked == "3":
            self.progressBarInit()
            self.thread = thread_management.Thread(OperationSystem.copy_and_overwrite, input_paths,outputs_paths)
            self.thread.progress.connect(self.handle_progress)
            self.thread.result.connect(self.handle_result)
            self.thread.finish.connect(self.handle_finish)
            self.thread.start()
            return





    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.Outputs.data.send(self.in_data)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return
    def handle_finish(self):
        print("process finished")
        self.progressBarFinished()

# Test standalone
if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = OwOperationSystem()
    window.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()