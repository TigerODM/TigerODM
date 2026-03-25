import os
import sys

import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from orangecontrib.text.corpus import Corpus
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
class OWTable2Corpus(widget.OWWidget):
    name = "Table to Corpus"
    description = "Convert a Table to a Corpus and set the column 'content' as the used text feature."
    category = "AAIT - TOOLBOX"
    icon = "icons/owtable2corpus.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owtable2corpus.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owtable2corpus.ui")
    want_control_area = False
    priority = 1060

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Corpus", Corpus)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.autorun:
            self.run()


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        # Data Management
        self.data = None
        self.autorun = True
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def run(self):
        self.warning("")
        if self.data is None:
            self.Outputs.data.send(None)
            return

        if not "content" in self.data.domain:
            self.warning("You haven't defined a 'content' variable.")

        domain = self.data.domain
        out_data = Corpus.from_table(domain, self.data)
        out_data.text_features = [Orange.data.StringVariable(name="content")]
        self.Outputs.data.send(out_data)

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWTable2Corpus()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
