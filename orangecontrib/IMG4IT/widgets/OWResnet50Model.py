import os
import sys

from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Output


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from orangecontrib.AAIT.utils import SimpleDialogQt
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import GetFromRemote, get_local_store_path
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import SimpleDialogQt
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.MetManagement import GetFromRemote, get_local_store_path
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWModelResnet50(widget.OWWidget):
    name = "ResNet50 Model Embeddings"
    description = "Load the model ResNet50 Model from the AAIT Store"
    icon = "icons/resnet50.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/resnet50.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmodel_resnet50.ui")
    priority=1093
    want_control_area = False

    class Outputs:
        out_model_path = Output("Image Model", str, auto_summary=False)

    def __init__(self):
        super().__init__()
        # Path management
        self.current_ows = ""
        local_store_path = get_local_store_path()
        model_name = "resnet50-0676ba61.pth"
        self.model_path = os.path.join(local_store_path, "Models", "ComputerVision","resnet50", model_name)
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        # Verify if model exists
        if not os.path.exists(self.model_path):
            if not SimpleDialogQt.BoxYesNo("Model isn't in your computer. Do you want to download it from AAIT store?"):
                return
            try:
                if 0 != GetFromRemote("ResNet50"):
                    return
            except:
                SimpleDialogQt.BoxError("Unable to get the Model.")
                return
        self.Outputs.out_model_path.send(self.model_path.replace("\\","/"))



if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWModelResnet50()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
