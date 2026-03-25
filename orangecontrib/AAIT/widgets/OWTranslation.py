import os
import sys

import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from transformers import MarianMTModel
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.llm import translations
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.AAIT.utils import thread_management, help_management
    from orangecontrib.AAIT.llm import translations
    from orangecontrib.AAIT.utils.import_uic import uic


class OWTranslation(widget.OWWidget):
    name = "Translation"
    description = "Generate a translation on the column 'content' of a Table"
    icon = "icons/owtranslation.svg"
    category = "AAIT - LLM INTEGRATION"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owtranslation.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owtranslation.ui")
    want_control_area = False
    priority= 1100
    class Inputs:
        data = Input("Data", Orange.data.Table)
        model = Input("Model", (MarianMTModel, object), auto_summary=False)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        self.run()

    @Inputs.model
    def set_model(self, in_model):
        if in_model is not None:
            self.model = in_model[0]
            self.tokenizer = in_model[1]
        else:
            self.model = None
            self.tokenizer = None
        self.run()

    def __init__(self):
        super().__init__()
        # Path management
        self.current_ows = ""

        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        # Data Management
        self.data = None
        self.model = None
        self.tokenizer = None
        self.thread = None
        self.result = None
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def run(self):
        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            return

        if self.model is None:
            self.Outputs.data.send(None)
            return

        if self.tokenizer is None:
            self.Outputs.data.send(None)
            return

        # Verification of in_data
        self.error("")
        try:
            self.data.domain["content"]
        except KeyError:
            self.error('You need a "content" column in input data')
            return

        if type(self.data.domain["content"]).__name__ != 'StringVariable':
            self.error('"content" column needs to be a Text')
            return

        # Start progress bar
        self.progressBarInit()

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        self.thread = thread_management.Thread(translations.generate_translation,
                                               self.data, self.model, self.tokenizer)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.result = result
            self.Outputs.data.send(self.result)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        print("Generation finished")
        self.progressBarFinished()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWTranslation()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
