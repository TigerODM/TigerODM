import os
import sys

from AnyQt.QtWidgets import QApplication, QComboBox
from AnyQt.QtCore import QTimer, Qt
from AnyQt.QtGui import QIcon
from Orange.widgets import widget
from Orange.widgets.utils.signals import Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QCheckBox

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
    from Orange.widgets.orangecontrib.AAIT.utils import SimpleDialogQt
    from Orange.widgets.orangecontrib.AAIT.llm.okNokGpu import has_gpu_with_min_vram
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import GetFromRemote, get_local_store_path,ensure_file_exists_recursive
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import help_management
    from orangecontrib.AAIT.utils import SimpleDialogQt
    from orangecontrib.AAIT.llm.okNokGpu import has_gpu_with_min_vram
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.MetManagement import GetFromRemote, get_local_store_path,ensure_file_exists_recursive
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


model_names = {
    "Qwen3 1.7B (Q2)": "Qwen3-1.7B-Q2_K_L.gguf",
    "Qwen3 1.7B": "Qwen3-1.7B-Q6_K.gguf",
    "Qwen3 4B": "Qwen3-4B-Q4_K_M.gguf",
    "Qwen3 8B": "Qwen3-8B-Q4_K_M.gguf",
    "Qwen3 14B": "Qwen3-14B-Q4_K_M.gguf",
    "Granite4 7B": "granite-4.0-h-tiny-Q4_K_M.gguf",
    "Phi4 4B": "Phi-4-mini-reasoning-Q4_K_M.gguf",
    "Gemma3 270m": "gemma-3-270m-Q8_0.gguf",
    "Gemma3 12B": "gemma-3-12b-it-Q4_K_M.gguf",
    "Deepseek 8B": "DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf"
}

best_big_llm_ordered = ["Qwen3 14B","Qwen3 8B","Qwen3 4B"]
best_small_llm_ordered = ["Qwen3 1.7B"]

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
    model_name = Setting("Qwen3 8B")

    class Outputs:
        out_model_path = Output("Model", str, auto_summary=False)

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


        self.display_local_models()
        self.combobox_model.setEnabled(True)
        if self.autochoose_llm=="True":
            self.auto_choose_model()
            self.combobox_model.setEnabled(False)


        self.combobox_model.setCurrentIndex(self.combobox_model.findText(self.model_name))
        self.combobox_model.currentTextChanged.connect(self.on_model_changed)
        self.checkBox.clicked.connect(self.update_checkbox)
        # Run
        self.run()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def auto_choose_model(self):
        if has_gpu_with_min_vram():
           for element in best_big_llm_ordered:
                filename = model_names[element]
                path = os.path.join(get_local_store_path(), "Models", "NLP", filename)
                model_path = str(path)
                if os.path.exists(model_path):
                    self.model_name=element
                    return
        for element in best_small_llm_ordered:
            filename = model_names[element]
            path = os.path.join(get_local_store_path(), "Models", "NLP", filename)
            model_path = str(path)
            if os.path.exists(model_path):
                self.model_name = element
                return

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
        local_store_path = get_local_store_path()

        # Prepare your icons
        icon_check = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons/green_check.svg"))  # green check
        icon_down_body = QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons/blue_down_arrow.svg"))  # blue arrow

        for i in range(self.combobox_model.count()):
            item = self.combobox_model.model().item(i)
            filename = model_names[item.text()]
            path = os.path.join(local_store_path, "Models", "NLP", filename)
            model_path = str(path)
            list_tr = [model_path]
            if ensure_file_exists_recursive(list_tr):
                item.setForeground(Qt.black)
                item.setIcon(icon_check)
            else:
                item.setForeground(Qt.gray)
                item.setIcon(icon_down_body)


    def run(self):
        self.error("")
        self.warning("")
        if self.autochoose_llm=="True":
            self.auto_choose_model()
            self.warning("autochoose llm activated : "+str(self.model_name))
        # Get the model path based on the selected name
        filename = model_names[self.model_name]
        model_path = os.path.join(get_local_store_path(), "Models", "NLP", filename)
        model_path=str(model_path)
        list_tr=[model_path]
        # Verify if model exists
        if not ensure_file_exists_recursive(list_tr):
            if not SimpleDialogQt.BoxYesNo("Model isn't in your computer. Do you want to download it from AAIT store ?"):
                self.error("Model is not on your computer.")
                return
            try:
                if 0 != GetFromRemote(self.model_name):
                    self.error("Model is not on your computer.")
                    return
                ensure_file_exists_recursive(list_tr)
            except Exception as e:
                SimpleDialogQt.BoxError(f"Unable to get the Model ({e})")
                self.error("Model is not on your computer.")
                return
        model_path=list_tr[0]
        self.Outputs.out_model_path.send(model_path)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWLargeLanguageModel()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
