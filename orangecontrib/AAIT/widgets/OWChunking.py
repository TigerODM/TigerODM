import os

import Orange.data
from Orange.data import StringVariable
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QLineEdit
from AnyQt.QtWidgets import QComboBox
from AnyQt.QtCore import QTimer

from transformers import AutoTokenizer
#from sentence_transformers import SentenceTransformer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import chunking
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, base_widget, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import get_local_store_path
else:
    from orangecontrib.AAIT.llm import chunking
    from orangecontrib.AAIT.utils import thread_management, base_widget, help_management
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils.MetManagement import get_local_store_path


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWChunker(base_widget.BaseListWidget):
    name = "Text Chunker"
    description = "Create chunks on the column 'content' of a Table"
    icon = "icons/owchunking.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owchunking.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owchunking.ui")
    want_control_area = False
    priority = 1050
    category = "AAIT - LLM INTEGRATION"

    # Settings
    chunk_size: str = Setting("300")
    overlap: str = Setting("100")
    mode: str = Setting("tokens")
    selected_column_name = Setting("content")

    class Inputs:
        data = Input("Data", Orange.data.Table)
        model = Input("Tokenizer", str, auto_summary=False)

    class Outputs:
        data = Output("Chunked Data", Orange.data.Table)
        infos = Output("Information", Orange.data.Table)


    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.data:
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        if self.autorun:
            self.run()

    @Inputs.model
    def set_model(self, in_model_path):
        self.tokenizer_path = in_model_path
        if self.autorun:
            self.run()


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(490)
        #uic.loadUi(self.gui, self)

        # Chunking method
        self.edit_mode = self.findChild(QComboBox, "comboBox")
        self.edit_mode.setCurrentText(self.mode)
        self.edit_mode.currentTextChanged.connect(self.update_edit_mode)
        # Chunk size
        self.edit_chunkSize = self.findChild(QLineEdit, 'chunkSize')
        self.edit_chunkSize.setText(str(self.chunk_size))
        self.edit_chunkSize.textChanged.connect(self.update_chunk_size)
        # Chunk overlap
        self.edit_overlap = self.findChild(QLineEdit, 'QLoverlap')
        self.edit_overlap.setText(str(self.overlap))
        self.edit_overlap.textChanged.connect(self.update_overlap)


        # Data Management
        self.data = None
        self.tokenizer = None
        self.tokenizer_path = None
        self.thread = None
        self.autorun = True
        self.result=None
        self.meta_infos = None
        self.mode = self.edit_mode.currentText()
        self.chunk_size = self.edit_chunkSize.text() if self.edit_chunkSize.text().isdigit() else "300"
        self.overlap = self.edit_overlap.text() if self.edit_overlap.text().isdigit() else "100"

        self.post_initialized()

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def update_chunk_size(self, text):
        self.chunk_size = text

    def update_overlap(self, text):
        self.overlap = text

    def update_edit_mode(self, text):
        self.mode = text

    def run(self):
        self.error("")
        self.warning("")

        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            return

        # Tokenizer management
        if self.tokenizer_path:
            if self.tokenizer_path.endswith(".gguf"):
                self.error("Invalid model for chunking. Try with Tokenizer - Qwen3 8B.")
                self.tokenizer = None
                self.Outputs.data.send(None)
                return
            else:
                try:
                    self.tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_path)
                except Exception as e:
                    self.tokenizer = None
                    self.error(f"Invalid model for chunking. Try with Tokenizer - Qwen3 8B. ({e})")
                    self.Outputs.data.send(None)
                    return
        else:
            self.warning('Using default chunking method "character". You should try using a tokenizer like "Tokenizer - Qwen3 8B".')
            self.tokenizer = "character"

        # Verification of in_data
        if not self.selected_column_name in self.data.domain:
            self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
            return

        if not isinstance(self.data.domain[self.selected_column_name], StringVariable):
            self.error('You must select a text variable.')
            return

        if self.mode == "words":
            self.warning('"words" chunking method is deprecated and will soon be removed. Please use "tokens" instead.')
            path_ugly = os.path.join(get_local_store_path(), "Models", "NLP", "all-mpnet-base-v2")
            if not os.path.exists(path_ugly):
                self.error("You need all-mpnet-base-v2 in your AAIT Store (Models/NLP/...) for this mode.")
                return


        # Start progress bar
        self.progressBarInit()

        # Connect and start thread
        self.thread = thread_management.Thread(chunking.create_chunks, self.data, self.selected_column_name, self.tokenizer, int(self.chunk_size), int(self.overlap), str(self.mode))
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()


    def handle_progress(self, value: float) -> None:
        """
        Handles the progress signal from the main function.

        Updates the progress bar with the given value.

        :param value: (float): The value to set for the progress bar.

        :return: None
        """

        self.progressBarSet(value)

    def handle_result(self, result):
        """
        Handles the result signal from the main function.

        Attempts to send the result to the data output port. In case of an error,
        sends None to the data output port and displays the error message.

        :param result:
             Any: The result from the main function.

        :return:
            None
        """

        try:
            self.result = result[0]
            self.meta_infos = result[1]
            self.Outputs.data.send(self.result)
            self.Outputs.infos.send(self.meta_infos)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        """
        Handles the end signal from the main function.

        Displays a message indicating that the segmentation is complete and updates
        the progress bar to reflect the completion.

        :return:
            None
        """
        print("Chunking finished")
        self.progressBarFinished()

    def post_initialized(self):
        """
        This method is intended for post-initialization tasks after the widget has
        been fully initialized.

        Override this method in subclasses to perform additional configurations
        or settings that require the widget to be fully constructed. This can
        include tasks such as connecting signals, initializing data, or setting
        properties of the widget dependent on its final state.

        :return:
            None
        """
        pass




if __name__ == "__main__":

    #print(chunks1)

    # Advanced initialization with custom parameters
    from orangewidget.utils.widgetpreview import WidgetPreview
    from orangecontrib.text.corpus import Corpus
    corpus_ = Corpus.from_file("book-excerpts")
    WidgetPreview(OWChunker).run(corpus_)