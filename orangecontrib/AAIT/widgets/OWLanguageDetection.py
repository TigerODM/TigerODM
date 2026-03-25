import os
import sys

from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Table, Domain, StringVariable
from langdetect import detect, LangDetectException
from AnyQt.QtWidgets import QApplication
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
class OWLanguageDetection(widget.OWWidget):
    name = "Language Detection"
    description = "Detects language of text content."
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/languages.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/languages.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owlangdetect.ui")
    want_control_area = False
    priority = 1060

    class Inputs:
        data = Input("Content", Table)

    class Outputs:
        data = Output("Content with language", Table)

    def __init__(self):
        super().__init__()
        self.data = None
        self.autorun = True
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.autorun = True

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    @Inputs.data
    def set_data(self, in_data):
        if in_data is None:
            self.Outputs.data.send(None)
            return


        self.data = in_data
        if self.autorun and self.data:
            self.process()

    def detect_language(self, text):
        try:
            return detect(text)
        except LangDetectException:
            return "unknown"

    def process(self):
        if self.data is None:
            print("[INFO] No input data provided.")
            self.Outputs.data.send(None)
            return

        if "Content" not in self.data.domain:
            self.error("Missing 'Content' column in input data")
            self.Outputs.data.send(None)
            print("[ERROR] 'Content' column not found in input data.")
            return

        self.error("")

        language_var = StringVariable("Language")
        new_domain = Domain(self.data.domain.attributes,
                            self.data.domain.class_vars,
                            self.data.domain.metas + (language_var,))

        new_metas = []
        for i, row in enumerate(self.data):
            text = str(row["Content"])
            lang = self.detect_language(text)
            print(f"[DEBUG] Row {i}: Detected language -> {lang}")
            new_metas.append(list(row.metas) + [lang])

        out_data = Table(new_domain, self.data.X, self.data.Y, new_metas)
        print("[INFO] Language detection complete. Sending output data.")
        self.Outputs.data.send(out_data)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ow = OWLanguageDetection()
    ow.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
