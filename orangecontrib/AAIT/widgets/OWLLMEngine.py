
import os
import sys

import Orange.data
from AnyQt.QtWidgets import QApplication, QLabel
from AnyQt import QtGui
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QLineEdit, QTextBrowser, QSpinBox, QDoubleSpinBox
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import answers_llama
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management,MetManagement, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.llm import answers_llama
    from orangecontrib.AAIT.utils import thread_management,MetManagement, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWQEdgeLLM(widget.OWWidget):
    name = "Engine LLM"
    description = "Generate a response to a column 'prompt' with a LLM"
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/edge_llm.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/edge_llm.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owedgellm.ui")
    want_control_area = True
    priority = 1089

    class Inputs:
        data = Input("Data", Orange.data.Table)
        model_path = Input("Model", str, auto_summary=False)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    n_ctx: str = Setting("32768")
    workflow_id = Setting("")

    max_tokens = Setting(0)
    temperature = Setting(0.4)
    top_p = Setting(0.4)
    top_k = Setting(40)
    repeat_penalty = Setting(1.15)
    k_cache = Setting(1)
    v_cache = Setting(1)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.autorun:
            self.run()

    @Inputs.model_path
    def set_model_path(self, in_model_path):
        self.model_path = in_model_path
        if self.autorun:
            self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(700)
        self.setFixedHeight(700)
        uic.loadUi(self.gui, self)
        self.label_description = self.findChild(QLabel, 'Description')
        # Context size
        self.edit_nCtx = self.findChild(QLineEdit, 'lineEdit')
        self.edit_nCtx.setText(str(self.n_ctx))
        self.edit_nCtx.editingFinished.connect(self.update_n_ctx)
        # Context cache
        self.comboKCache.setCurrentIndex(self.k_cache)
        self.comboVCache.setCurrentIndex(self.v_cache)
        self.comboKCache.currentIndexChanged.connect(self.update_cache)
        self.comboVCache.currentIndexChanged.connect(self.update_cache)
        # Workflow ID for streaming
        self.edit_ID = self.findChild(QLineEdit, 'lineEdit_2')
        self.edit_ID.setText(self.workflow_id)
        self.edit_ID.editingFinished.connect(self.update_workflow_id)
        # Bind all spinboxes
        self.edit_max_tokens = self.bind_spinbox("boxMaxTokens", self.max_tokens)
        self.edit_temperature = self.bind_spinbox("boxTemperature", self.temperature, is_double=True)
        self.edit_top_p = self.bind_spinbox("boxTopP", self.top_p, is_double=True)
        self.edit_top_k = self.bind_spinbox("boxTopK", self.top_k)
        self.edit_repeat_penalty = self.bind_spinbox("boxRepeatPenalty", self.repeat_penalty, is_double=True)

        # Text browser
        self.textBrowser = self.findChild(QTextBrowser, 'textBrowser')

        # # Data Management
        self.data = None
        self.model_path = None
        self.thread = None
        self.autorun = True
        self.use_gpu = True
        self.can_run = True
        self.result = None
        self.n_ctx = self.edit_nCtx.text() if self.edit_nCtx.text().isdigit() else "32768"
        self.workflow_id = self.edit_ID.text()

        # Custom updates
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def update_n_ctx(self):
        value = self.edit_nCtx.text()  # Read the current value
        self.n_ctx = value if value.isdigit() else "32768"  # Default or parsed value
        self.edit_nCtx.setText(self.n_ctx)
       #answers.check_gpu(self.model_path, self) remettre!!!!
        #self.run()

    def update_cache(self):
        self.k_cache = self.comboKCache.currentIndex()
        self.v_cache = self.comboVCache.currentIndex()

    def update_workflow_id(self):
        self.workflow_id = self.edit_ID.text()

    def bind_spinbox(self, name, value, is_double=False):
        widget_type = QDoubleSpinBox if is_double else QSpinBox
        box = self.findChild(widget_type, name)
        box.setValue(value)
        box.editingFinished.connect(self.update_parameters)
        return box

    def update_parameters(self):
        self.max_tokens = self.edit_max_tokens.value()
        self.temperature = self.edit_temperature.value()
        self.top_p = self.edit_top_p.value()
        self.top_k = self.edit_top_k.value()
        self.repeat_penalty = self.edit_repeat_penalty.value()
        print("Updated parameters:")
        print(f"  Max tokens     : {self.max_tokens}")
        print(f"  Temperature    : {self.temperature}")
        print(f"  Top P          : {self.top_p}")
        print(f"  Top K          : {self.top_k}")
        print(f"  Repeat penalty : {self.repeat_penalty}")


    def run(self):
        # Clear error & warning
        self.warning("")
        self.error("")

        # If Thread is already running, interrupt it
        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            return

        if self.model_path is None or not os.path.exists(self.model_path):
            self.Outputs.data.send(None)
            return

        if not "prompt" in self.data.domain:
            self.Outputs.data.send(None)
            return

        if "Answer" in self.data.domain:
            self.error('You cannot have "Answer" in your input data. Please rename or remove the column.')
            self.Outputs.data.send(None)
            return

        #answers_llama.check_gpu(self.model_path, self)
        if not self.can_run:
            return

        query_parameters = {
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
            "k_cache": self.k_cache,
            "v_cache": self.v_cache
        }
        chemin_dossier = MetManagement.get_api_local_folder(workflow_id=self.workflow_id)
        if os.path.exists(chemin_dossier):
            MetManagement.write_file_time(chemin_dossier + "time.txt")

        # Start progress bar
        self.progressBarInit()
        self.textBrowser.setText("")

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        self.thread = thread_management.Thread(answers_llama.generate_answers, self.data, self.model_path,
                                               self.use_gpu, int(self.n_ctx), query_parameters, self.workflow_id)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, progress) -> None:
        action = progress[0]
        value = progress[1]

        if action == "progressBar":
            self.progressBarSet(value)
            # Using the anchor method here too
            self.append_text_at_end("\n\n\n\n")

        elif action == "assistant":
            if value is not None:
                self.append_text_at_end(value)

        elif action == "warning":
            self.warning(value)
        elif action == "error":
            self.error(value)

    def append_text_at_end(self, text):
        # 1. Create a cursor anchored to the document (not the UI focus)
        cursor = QtGui.QTextCursor(self.textBrowser.document())
        # 2. Move this "invisible" cursor to the end
        cursor.movePosition(QtGui.QTextCursor.End)
        # 3. Insert the text : this modifies the underlying data without affecting the scrollbar or the user's cursor
        cursor.insertText(text)

    def handle_result(self, result):
        if result is None:
            self.error("unable to load model")
            self.Outputs.data.send(None)
            return
        try:
            self.result = result
            self.Outputs.data.send(result)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        print("Generation finished")
        self.progressBarFinished()

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWQEdgeLLM()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
