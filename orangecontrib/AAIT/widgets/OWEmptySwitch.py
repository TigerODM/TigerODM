import os
import sys

import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import create_trigger_table
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils.MetManagement import create_trigger_table
    from orangecontrib.AAIT.utils import help_management

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWEmptySwitch(widget.OWWidget):
    name = "Empty Switch"
    description = "This widget lets the input data pass if it receives any, otherwise it emits a table on its Trigger output."
    category = "AAIT - TOOLBOX"
    icon = "icons/owemptyswitch.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owemptyswitch.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owemptyswitch.ui")
    want_control_area = False
    priority = 1060

    class Inputs:
        data = Input("Data", object, auto_summary=False)

    class Outputs:
        data = Output("Data", Orange.data.Table)
        trigger = Output("Trigger", object, auto_summary=False)


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
        if self.data is None:
            self.Outputs.data.send(None)
            self.Outputs.trigger.send(create_trigger_table())
        else:
            self.Outputs.data.send(self.data)
            self.Outputs.trigger.send(None)

    def post_initialized(self):
        pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWEmptySwitch()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
