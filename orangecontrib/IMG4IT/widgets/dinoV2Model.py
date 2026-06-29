import os
import sys

from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Output


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWModelQwenInstruct7BQ6(widget.OWWidget):
    name = "DinoV2 Model Embeddings"
    description = "Load the model DinoV2 Model from the AAIT Store"
    icon = "icons/dinoV2.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/dinoV2.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmodel_dinoV2.ui")
    priority=1093
    want_control_area = False

    class Outputs:
        out_model_path = Output("Image Model", str, auto_summary=False)

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
            self.model_path = get_path_or_retrieve("DinoV2")
        except Exception as e:
            self.error(str(e))
            return
        self.Outputs.out_model_path.send(self.model_path)



if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWModelQwenInstruct7BQ6()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
