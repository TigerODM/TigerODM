import os
import sys

from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Output
from sentence_transformers import SentenceTransformer
from AnyQt.QtCore import QTimer


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from orangecontrib.AAIT.utils import SimpleDialogQt
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils import SimpleDialogQt, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWModelMPNET(widget.OWWidget):
    name = "Model - Embeddings - MPNET"
    description = "Load the embeddings model all-mpnet-base-v2 from the AAIT Store"
    category = "AAIT - MODELS"
    icon = "icons/owmodel_mpnet.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owmodel_mpnet.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmodel_mpnet.ui")
    priority = 1061
    want_control_area = False

    class Outputs:
        out_model = Output("Model", SentenceTransformer, auto_summary=False)

    def __init__(self):
        super().__init__()
        # Path management
        self.current_ows = ""
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.error("")
        try:
            self.model_path = get_path_or_retrieve("MPNET BASE V2")
        except Exception as e:
            self.error(str(e))
            return
        self.model = None
        self.load_sentence_transformer(self.model_path)
        if self.model is not None:
            self.Outputs.out_model.send(self.model)
        else:
            SimpleDialogQt.BoxError("An Error Occurred when loading model.")
            self.Outputs.out_model.send(None)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def load_sentence_transformer(self, model_path):
        self.model = SentenceTransformer(model_path, device="cpu")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWModelMPNET()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
