import os
import sys

from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Table, Domain, ContinuousVariable
from thefuzz import fuzz
from AnyQt.QtWidgets import QApplication
from AnyQt.QtCore import QTimer, QObject, QThread, pyqtSignal

# Import intelligent selon contexte
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management

# Worker pour exécution asynchrone
class KeywordWorker(QObject):
    finished = pyqtSignal(Table)
    error = pyqtSignal(str)

    def __init__(self, data, keywords, threshold=80):
        super().__init__()
        self.data = data
        self.keywords = keywords
        self.threshold = threshold

    def extract_matched_keywords(self, text, keywords):
        words = text.split(" ")
        matched_keywords = []
        for keyword in keywords:
            best_score = max(fuzz.ratio(word.lower(), keyword.lower()) for word in words)
            if best_score >= self.threshold:
                matched_keywords.append(keyword)
        return matched_keywords

    def run(self):
        try:
            if "Content" not in self.data.domain or "Keywords" not in self.keywords.domain:
                self.error.emit("Missing 'Content' or 'Keywords' column")
                return

            keyword_list = [
                str(row["Keywords"])
                for row in self.keywords
                if str(row["Keywords"]).strip() != ""
            ]

            new_metas_vars = list(self.data.domain.metas)
            if not any(var.name == "Keywords" for var in new_metas_vars):
                new_metas_vars.append(ContinuousVariable("Keywords"))

            new_domain = Domain(
                self.data.domain.attributes,
                self.data.domain.class_vars,
                new_metas_vars
            )

            new_metas = []
            for row in self.data:
                text = str(row["Content"])
                matched_keywords = self.extract_matched_keywords(text, keyword_list)
                score = (
                    sum(fuzz.ratio(word.lower(), kw.lower()) for kw in matched_keywords for word in text.split())
                    / len(keyword_list)
                    if matched_keywords else 0.0
                )
                new_metas.append(list(row.metas) + [score])

            out_data = Table(new_domain, self.data.X, self.data.Y, new_metas)
            self.finished.emit(out_data)

        except Exception as e:
            self.error.emit(str(e))

# Définition du widget principal
@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWKeywords(widget.OWWidget):
    name = "Keywords Detection"
    description = "Give the amount of keywords from in_object in in_data"
    icon = "icons/owkeywords.png"
    category = "AAIT - LLM INTEGRATION"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owkeywords.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owkeyword.ui")
    want_control_area = False
    priority = 1050

    class Inputs:
        data = Input("Content", Table)
        keywords = Input("Keywords", Table)

    class Outputs:
        data = Output("Keywords per Content", Table)

    def __init__(self):
        super().__init__()
        self.data = None
        self.keywords = None
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.autorun = True
        self.thread = None
        self.worker = None

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.autorun and self.keywords:
            self.process()

    @Inputs.keywords
    def set_keywords(self, in_keywords):
        self.keywords = in_keywords
        if self.autorun and self.data:
            self.process()

    def process(self):
        if self.data is None or self.keywords is None:
            self.Outputs.data.send(None)
            return

        self.error("")  # Clear errors
        self.thread = QThread()
        self.worker = KeywordWorker(self.data, self.keywords)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

    def on_worker_finished(self, out_data):
        print("[INFO] Thread finished. Output ready.")
        self.Outputs.data.send(out_data)

    def on_worker_error(self, message):
        print(f"[ERROR] Worker error: {message}")
        self.error(message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ow = OWKeywords()
    ow.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()

