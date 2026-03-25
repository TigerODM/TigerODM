import os
import sys

from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Output
from transformers import AutoTokenizer, MarianMTModel, AutoModelForSeq2SeqLM
from AnyQt.QtCore import QTimer


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import SimpleDialogQt, thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import GetFromRemote, get_local_store_path
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import SimpleDialogQt, thread_management, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.MetManagement import GetFromRemote, get_local_store_path
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWModel_HelsinkiEnFr(widget.OWWidget):
    name = "Model - Translation - Helsinki EN-FR"
    description = "Load the translation model Helsinki EN-FR from the AAIT Store"
    category = "AAIT - MODELS"
    icon = "icons/owmodel_helsinki_en_fr.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owmodel_helsinki_en_fr.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmodel_helsinki_en_fr.ui")
    priority = 1101
    want_control_area = False

    class Outputs:
        out_models = Output("Models", (MarianMTModel, object), auto_summary=False)

    def __init__(self):
        super().__init__()
        # Path management
        self.current_ows = ""
        local_store_path = get_local_store_path()
        model_name = "helsinki_en_fr"
        self.model_path = os.path.join(local_store_path, "Models", "NLP", model_name)
        self.model = None
        self.tokenizer = None
        self.models = None
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        if not os.path.exists(self.model_path):
            if not SimpleDialogQt.BoxYesNo("Model isn't in your computer. Do you want to download it from AAIT store?"):
                return
            try:
                GetFromRemote("Translation")
            except Exception as e:  # TODO ciblage de l'erreur
                SimpleDialogQt.BoxError(f"Unable to get the model: {e}")
                return
        # Data Management
        self.progressBarInit()
        self.thread = thread_management.Thread(self.load_model, self.model_path)
        self.thread.finish.connect(self.handle_loading_finish)
        self.thread.start()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def load_model(self, model_path):
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_path,
            device_map=None,
            low_cpu_mem_usage=False
        )

        self.model = self.model.to("cpu")
        self.model.eval()

        #print("MODEL DEVICE =", next(self.model.parameters()).device)

    def handle_loading_finish(self):
        self.models = (self.model, self.tokenizer)
        if self.model is not None and self.tokenizer is not None:
            self.Outputs.out_models.send(self.models)
        else:
            SimpleDialogQt.BoxError("An Error Occurred when loading model.")
            self.Outputs.out_models.send(None)
        self.progressBarFinished()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWModel_HelsinkiEnFr()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
