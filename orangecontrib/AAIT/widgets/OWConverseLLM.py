import os
import sys

import Orange.data
from AnyQt.QtWidgets import QApplication, QLabel, QWidget, QScrollArea, QLineEdit, QHBoxLayout, QVBoxLayout, QDoubleSpinBox, QSpinBox
from AnyQt.QtCore import QTimer, Qt
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import answers_llama
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.llm import answers_llama
    from orangecontrib.AAIT.utils import thread_management, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWConverseLLM(widget.OWWidget):
    name = "Converse LLM"
    description = "Generate a response to a column 'prompt' with a LLM, while keeping the previous interactions in memory"
    icon = "icons/owconversellm.svg"
    category = "AAIT - ALGORITHM"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owconversellm.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owconversellm.ui")
    want_control_area = False
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
    k_cache = Setting(0)
    v_cache = Setting(0)

    @Inputs.data
    def set_data(self, in_data):
        if in_data is None:
            self.Outputs.data.send(None)
            return
        self.data = in_data
        if self.autorun:
            self.run()

    @Inputs.model_path
    def set_model_path(self, in_model_path):
        self.model_path = in_model_path
        # Reset everything when changing model
        self.conversation = []
        self.clear_chat_area() # TODO render Qt UI

        # If there is already a model
        if self.model is not None:
            # Interrupt an eventual threaded generation
            if self.thread is not None:
                if self.thread.isRunning():
                    self.thread.safe_quit()
            self.model = None

        # If the link has been cut, do nothing
        if in_model_path is None:
            return
        # Check for the GPU / CPU, load model and start a chat session # TODO ?
        # answers.check_gpu(in_model_path, self)
        self.model = answers_llama.load_model(self.model_path, use_gpu=True, n_ctx=int(self.n_ctx))

        if self.autorun:
            self.run()


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(750)
        self.setFixedHeight(650)
        uic.loadUi(self.gui, self)
        # Context
        self.lineEdit_n_ctx = self.findChild(QLineEdit, "lineEdit")
        self.lineEdit_n_ctx.setText(str(self.n_ctx))
        self.lineEdit_n_ctx.editingFinished.connect(self.update_n_ctx)
        # Context cache
        self.comboKCache.setCurrentIndex(self.k_cache)
        self.comboVCache.setCurrentIndex(self.v_cache)
        self.comboKCache.currentIndexChanged.connect(self.update_cache)
        self.comboVCache.currentIndexChanged.connect(self.update_cache)
        # Workflow ID for streaming
        self.edit_ID = self.findChild(QLineEdit, 'lineEdit_2')
        self.edit_ID.setText(self.workflow_id)
        self.edit_ID.editingFinished.connect(self.update_workflow_id)
        # SpinBoxes
        self.edit_max_tokens = self.bind_spinbox("boxMaxTokens", self.max_tokens)
        self.edit_temperature = self.bind_spinbox("boxTemperature", self.temperature, is_double=True)
        self.edit_top_p = self.bind_spinbox("boxTopP", self.top_p, is_double=True)
        self.edit_top_k = self.bind_spinbox("boxTopK", self.top_k)
        self.edit_repeat_penalty = self.bind_spinbox("boxRepeatPenalty", self.repeat_penalty, is_double=True)
        # Chat display
        self.scrollArea_display = self.findChild(QScrollArea, "scrollArea")
        self.scrollArea_display.setWidgetResizable(True)
        self.widget_display = self.scrollArea_display.widget()
        self.vLayout_display = QVBoxLayout(self.widget_display)
        self.vLayout_display.addStretch()

        # Data Management
        self.data = None
        self.model = None
        self.model_path = None
        self.conversation = None
        self.current_assistant_card = None

        self.thread = None
        self.autorun = True
        self.use_gpu = False
        self.can_run = True
        self.result = None

        # Custom updates
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def update_n_ctx(self):
        value = self.lineEdit_n_ctx.text()
        self.n_ctx = value if value.isdigit() else "32768"
        # answers.check_gpu(self.model_path, self) # TODO reload model

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
        self.error("")
        self.warning("")

        # If Thread is already running, interrupt it
        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            return

        if self.model is None:
            self.Outputs.data.send(None)
            return

        if not "prompt" in self.data.domain:
            self.error('You need a "prompt" column in your input data.')
            self.Outputs.data.send(None)
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

        # Start progress bar
        self.progressBarInit()

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        self.thread = thread_management.Thread(answers_llama.generate_conversation, self.data, self.model, self.conversation, int(self.n_ctx), query_parameters, self.workflow_id)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, progress) -> None:
        action = progress[0]
        value = progress[1]
        if action == "progressBar":
            self.progressBarSet(value)
        elif action == "user":
            user_card = UserMessageCard(value)
            self.add_message_card(user_card)
        elif action == "assistant":
            if self.current_assistant_card is None:
                assistant_card = AssistantMessageCard(value)
                self.add_message_card(assistant_card)
                self.current_assistant_card = assistant_card
            else:
                current_text = self.current_assistant_card.label.text()
                current_text += value
                self.current_assistant_card.setText(current_text)
        elif action == "warning":
            self.warning(value)
        # QApplication.processEvents()
        # self.scroll_to_bottom()


    def handle_result(self, result):
        try:
            self.result = result[0]
            self.conversation = result[1]
            self.Outputs.data.send(self.result)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        print("Generation finished")
        self.progressBarFinished()
        self.current_assistant_card = None

    def onDeleteWidget(self):
        if self.model is not None:
            self.model = None
        super().onDeleteWidget()

    def post_initialized(self):
        pass


    # UI
    def add_message_card(self, message_card):
        self.vLayout_display.insertWidget(self.vLayout_display.count() - 1, message_card)

    # UI
    def scroll_to_bottom(self):
        self.scrollArea_display.verticalScrollBar().setValue(self.scrollArea_display.verticalScrollBar().maximum())

    # UI # TODO à tester
    def clear_chat_area(self):
        """
        Supprime uniquement les cartes de message sans casser le layout.
        """
        for i in reversed(range(self.vLayout_display.count())):
            item = self.vLayout_display.itemAt(i)
            widget = item.widget()

            # On ne supprime que les widgets qui sont des cartes
            if isinstance(widget, (UserMessageCard, AssistantMessageCard)):
                widget.setParent(None)  # Détache du layout
                widget.deleteLater()  # Supprime de la mémoire
            elif widget is None and item.spacerItem():
                # Optionnel : si tu veux garder ton "ressort" du bas,
                # ne fais rien ici.
                pass



# UI - User message card
class UserMessageCard(QWidget):
    def __init__(self, text=""):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setStyleSheet("""
            background-color: #5050a0;
            color: white;
            border-radius: 8px;
            padding: 6px;
        """)
        self.layout.addWidget(self.label)
        self.layout.addStretch()  # push message to left
        self.setLayout(self.layout)

    def setText(self, text):
        """Update the card's text dynamically."""
        self.label.setText(text)

# UI - Assistant message card
class AssistantMessageCard(QWidget):
    def __init__(self, text=""):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.layout.addStretch()  # push message to right
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setStyleSheet("""
            background-color: #3c3c3c;
            color: white;
            border-radius: 8px;
            padding: 6px;
        """)
        self.layout.addWidget(self.label)
        self.setLayout(self.layout)
        QTimer.singleShot(0, lambda: help_management.override_help_action(self, "converse_llm.html"))

    def setText(self, text):
        """Update the card's text dynamically."""
        self.label.setText(text)






if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWConverseLLM()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
