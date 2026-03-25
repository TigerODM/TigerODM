import os
import sys
import zipfile
from Orange.data import StringVariable, Table, Domain
import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtCore import QTimer


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWUnzipFolder(widget.OWWidget):
    name = "Unzip Folder"
    description = "Unzip Folder(s) from path"
    category = "AAIT - TOOLBOX"
    icon = "icons/zip.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/zip.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owunzipfolder.ui")
    want_control_area = False
    priority = 1060

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_path(self, data):
        if data is None:
            return
        if "path" not in data.domain:
            self.warning("You need a 'path' variable in your data.")
        self.path = data.get_column("path")
        self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(300)
        self.setFixedHeight(200)
        uic.loadUi(self.gui, self)

        # Data Management
        self.path = None
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def run(self):
        self.error("")
        self.warning("")

        if self.path is None:
            return
        try:
            new_path = []
            for i in range(len(self.path)):
                zip_file = self.path[i]
                extract_path = self.path[i].replace(".zip", "")
                os.makedirs(extract_path, exist_ok=True)
                with zipfile.ZipFile(zip_file, "r") as zip_ref:
                    zip_ref.extractall(extract_path)
                    new_path.append([extract_path])
            X = [[] for _ in new_path]
            domain = Domain([], metas=[StringVariable("path")])
            out_data = Table.from_numpy(domain, X, metas=new_path)
            self.Outputs.data.send(out_data)

        except Exception as e:
            self.error(f"An error occurred: {e}")
            return

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWUnzipFolder()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
