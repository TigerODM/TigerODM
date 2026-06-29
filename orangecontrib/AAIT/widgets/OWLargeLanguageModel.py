import os
import sys

from AnyQt.QtWidgets import QApplication, QComboBox
from AnyQt.QtCore import QTimer, Qt
from AnyQt.QtGui import QIcon
from Orange.widgets import widget
from Orange.widgets.utils.signals import Output, Input
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QCheckBox
import Orange

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
    from Orange.widgets.orangecontrib.AAIT.llm.okNokGpu import auto_choose_model,get_model_names
    from Orange.widgets.orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import help_management
    from orangecontrib.AAIT.llm.okNokGpu import auto_choose_model,get_model_names
    from orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file




@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWLargeLanguageModel(widget.OWWidget):
    name = "Large Language Model"
    description = "Load a large language model (Qwen, Gemma, Phi...) for Engine LLM."
    category = "AAIT - MODELS"
    icon = "icons/owlargelanguagemodel.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owlargelanguagemodel.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owlargelanguagemodel.ui")
    priority=1093
    want_control_area = False
    autochoose_llm: str = Setting("False")
    # Settings
    model_name = Setting("Qwen3.5 9B Q6")

    class Inputs:
        data = Input("path", Orange.data.Table, auto_summary=False)

    class Outputs:
        out_model_path = Output("Model", str, auto_summary=False)


    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        self.run()


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        ## Combobox for model choice
        self.combobox_model = self.findChild(QComboBox, "comboBox")
        ## checboc for model autochoose_llm
        self.checkBox=self.findChild(QCheckBox, "checkBox")
        if str(self.autochoose_llm)=="False":
            self.checkBox.setChecked(False)
        else:
            self.checkBox.setChecked(True)


        self.data = None

        self.combobox_model.addItems(get_model_names().keys())
        self.display_local_models()
        self.combobox_model.setEnabled(True)
        if self.autochoose_llm=="True":
            self.model_name=auto_choose_model()
            self.combobox_model.setEnabled(False)
        self.combobox_model.setCurrentIndex(self.combobox_model.findText(self.model_name))
        self.combobox_model.currentTextChanged.connect(self.on_model_changed)
        self.checkBox.clicked.connect(self.update_checkbox)
        # Run
        self.run()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))



    def update_checkbox(self):
        if self.checkBox.isChecked():
            self.autochoose_llm="True"
            self.combobox_model.setEnabled(False)
        else:
            self.autochoose_llm = "False"
            self.combobox_model.setEnabled(True)
        self.run()

    def on_model_changed(self, text):
        self.model_name = text
        self.run()

    def display_local_models(self):

        # Prepare your icons
        icon_check = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons/green_check.svg"))  # green check
        icon_down_body = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons/blue_down_arrow.svg"))  # blue arrow
        model_names=get_model_names()
        for i in range(self.combobox_model.count()):
            item = self.combobox_model.model().item(i)
            filename = model_names[item.text()]
            if filename!="":
                item.setForeground(Qt.black)
                item.setIcon(icon_check)
            else:
                item.setForeground(Qt.gray)
                item.setIcon(icon_down_body)


    def run(self):
        self.error("")
        self.warning("")

        if self.autochoose_llm=="True":
            self.model_name=auto_choose_model()
            self.warning("autochoose llm activated : "+str(self.model_name))

        if self.data is not None:
            if not "path" in self.data.domain:
                self.error("Requires a 'path' variable")
                return
            else:
                self.warning("")
                self.model_name = self.data[0]["path"].value.replace('"', "").replace("'", "")
                self.Outputs.out_model_path.send(self.model_name)
                return

        # Get the model path based on the selected name
        model_names=get_model_names()

        try:
            filename = model_names[self.model_name]
        except Exception as e:
            print(e)
            filename=""

        if filename=="":
            try:
                filename = get_path_or_retrieve(self.model_name)
            except Exception as e:
                self.error(str(e))
                return
        self.Outputs.out_model_path.send(filename)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWLargeLanguageModel()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
