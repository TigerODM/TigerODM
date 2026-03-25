import os
import sys

from AnyQt.QtWidgets import QApplication
from Orange.data import Table, Domain, StringVariable
from Orange.widgets.utils.signals import Output, Input
from Orange.widgets import widget
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import process_documents
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.llm import process_documents
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import help_management

class OWProcessDocumentsFromPath(widget.OWWidget): # type: ignore
    name = "Process Documents From Path"
    description = ("Read the documents from a folder and search for a 'embeddings.pkl' file. Then the content of "
                   "'embeddings.pkl' is returned as Processed Data, while the content of the documents (not contained "
                   "in 'embeddings.pkl') is returned as Data")
    icon = "icons/processdocuments.svg"
    category = "AAIT - TOOLBOX"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/processdocuments.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owprocessdocuments.ui")
    priority = 1211
    category = "Advanced Artificial Intelligence Tools"
    want_control_area = False

    class Inputs:
        dirpath = Input("Path", str, auto_summary=False)
        path_table = Input("Path Table", Table)

    class Outputs:
        data = Output("Data", Table)
        processed_data = Output("Processed Data", Table)


    @Inputs.dirpath
    def set_dirpath(self, in_dirpath):
        if in_dirpath is not None:
            self.dirpath = in_dirpath
            self.run()

    @Inputs.path_table
    def set_path_table(self, in_path_table):
        if in_path_table is not None:
            if "path" in in_path_table.domain:
                self.dirpath = in_path_table[0]["path"].value
                self.run()
            else:
                self.warning("You need a 'path' variable from which the data will be loaded.")


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        # Data Management
        self.dirpath = None
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def run(self):
        self.error("")

        if self.dirpath is None:
            return

        if os.path.exists(self.dirpath):
            out_data, out_processed_data = process_documents.process_documents(self.dirpath)
            self.Outputs.data.send(out_data)
            self.Outputs.processed_data.send(out_processed_data)
        else:
            var_path = StringVariable("path")
            var_name = StringVariable("name")
            var_content = StringVariable("content")
            dom = Domain([], metas=[var_path, var_name, var_content])
            out_data = Table.from_list(dom, rows=[["", "", ""]])
            self.Outputs.data.send(out_data)
            self.Outputs.processed_data.send(out_data)
            self.error(f"Selected path '{self.dirpath}' does not exist.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWProcessDocumentsFromPath()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()