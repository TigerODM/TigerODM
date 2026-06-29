import os
import sys

from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Output
from transformers import AutoTokenizer, MarianMTModel
from AnyQt.QtCore import QTimer


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from orangecontrib.AAIT.utils import SimpleDialogQt, thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils import SimpleDialogQt, thread_management, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWModel_HelsinkiFrEn(widget.OWWidget):
    name = "Model - Translation - Helsinki FR-EN"
    description = "Load the translation model Helsinki FR-EN from the AAIT Store"
    category = "AAIT - MODELS"
    icon = "icons/owmodel_helsinki_fr_en.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owmodel_helsinki_fr_en.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmodel_helsinki_fr_en.ui")
    priority = 1102
    want_control_area = False

    class Outputs:
        out_models = Output("Models", (MarianMTModel, object), auto_summary=False)

    def __init__(self):
        super().__init__()
        # Path management
        self.current_ows = ""
        self.model = None
        self.tokenizer = None
        self.models= None
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        try:
            self.model_path = get_path_or_retrieve("Helsinki FR EN")
        except Exception as e:
            self.error(str(e))
            return
        # Data Management
        self.progressBarInit()
        self.thread = thread_management.Thread(self.load_model, self.model_path)
        self.thread.finish.connect(self.handle_loading_finish)
        self.thread.start()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def load_model(self, model_path):
        self.model = MarianMTModel.from_pretrained(model_path)
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

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
    my_widget = OWModel_HelsinkiFrEn()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
