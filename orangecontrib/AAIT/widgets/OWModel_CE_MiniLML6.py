import os
import sys

from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Output
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from orangecontrib.AAIT.utils import SimpleDialogQt
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import GetFromRemote, get_local_store_path
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils import SimpleDialogQt, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.MetManagement import GetFromRemote, get_local_store_path
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWModel_CE_MiniLML6(widget.OWWidget):
    name = "Cross Encoder - MiniLM L6 v2"
    description = "Load the cross encoder MiniLM L6 v2 from the AAIT Store"
    category = "AAIT - MODELS"
    icon = "icons/owmodel_ce_minilml6.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owmodel_ce_minilml6.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmodel_ce_minilml6.ui")
    priority=1091
    want_control_area = False

    class Outputs:
        out_model_path = Output("Model", str, auto_summary=False)

    def __init__(self):
        super().__init__()
        # Path management
        self.current_ows = ""
        local_store_path = get_local_store_path()
        model_name = "cross-encoder_MiniLM-L6"
        self.model_path = os.path.join(local_store_path, "Models", "NLP", model_name)

        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        if not os.path.exists(self.model_path):
            if not SimpleDialogQt.BoxYesNo("Model isn't in your computer. Do you want to download it from AAIT store?"):
                return
            try:
                GetFromRemote("Cross encoder MiniLM L6")
            except Exception as e:
                SimpleDialogQt.BoxError(f"Unable to get the Model : {e}")
                return

        if os.path.exists(self.model_path):
            self.Outputs.out_model_path.send(self.model_path)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWModel_CE_MiniLML6()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()