import os
import sys

from Orange.data import Table, Domain, StringVariable, ContinuousVariable
from AnyQt.QtWidgets import QApplication, QSpinBox, QRadioButton
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtCore import QTimer
from Orange.widgets import widget

from sentence_transformers import CrossEncoder

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm.retrieval import chunk_table_to_dict, retrieve_chunks_cosine, rerank_chunks
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management, thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic

else:
    from orangecontrib.AAIT.llm.retrieval import chunk_table_to_dict, retrieve_chunks_cosine, rerank_chunks
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management, thread_management
    from orangecontrib.AAIT.utils.import_uic import uic


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OW_M_RetrieveChunks(widget.OWWidget):
    name = "RAG - Retrieve Chunks"
    description = "Identify the skills used by a language model (service, code, data extraction...)."
    category = "AAIT - META WIDGETS"
    icon = "icons/ow_m_retrievechunks.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/ow_m_retrievechunks.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_m_retrievechunks.ui")
    want_control_area = False
    priority = 1060


    class Inputs:
        questions = Input("Questions", Table)
        chunks = Input("Chunks", Table)
        reranker_path = Input("Reranker", str, auto_summary=False)

    class Outputs:
        retrieved = Output("Retrieved chunks", Table)


    @Inputs.questions
    def set_data(self, in_questions):
        self.questions = in_questions

    @Inputs.chunks
    def set_chunks(self, in_chunks):
        self.chunks = in_chunks

    @Inputs.reranker_path
    def set_reranker(self, in_reranker_path):
        self.reranker_path = in_reranker_path

    def handleNewSignals(self):
        self.run()

    # Settings
    top_k = Setting(100)
    n_chunks = Setting(10)
    n_batches = Setting(2)
    restrict_to_path = Setting(False)


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(470)
        uic.loadUi(self.gui, self)

        # UI Parameters management
        self.edit_top_k = self.findChild(QSpinBox, 'box_top_k')
        self.edit_top_k.setValue(self.top_k)
        self.edit_top_k.editingFinished.connect(self.update_top_k)

        self.edit_n_chunks = self.findChild(QSpinBox, 'box_n_chunks')
        self.edit_n_chunks.setValue(self.n_chunks)
        self.edit_n_chunks.editingFinished.connect(self.update_n_chunks)

        self.edit_n_batches = self.findChild(QSpinBox, 'box_n_batches')
        self.edit_n_batches.setValue(self.n_batches)
        self.edit_n_batches.editingFinished.connect(self.update_n_batches)

        self.radio_restrict_path = self.findChild(QRadioButton, 'radioB_restrict_path')
        self.radio_restrict_path.setChecked(self.restrict_to_path)
        self.radio_restrict_path.toggled.connect(self.update_restrict_to_path)

        # Data Management
        self.questions = None
        self.chunks = None
        self.reranker_path = None
        self.reranker = None
        self.thread = None
        self.result = None

        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))


    def update_top_k(self):
        self.top_k = self.edit_top_k.value()

    def update_n_chunks(self):
        self.n_chunks = self.edit_n_chunks.value()

    def update_n_batches(self):
        self.n_batches = self.edit_n_batches.value()

    def update_restrict_to_path(self, checked):
        self.restrict_to_path = checked


    def run(self):
        self.warning("")
        self.error("")

        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        if self.questions is None:
            self.Outputs.retrieved.send(None)
            return

        if self.chunks is None:
            self.Outputs.retrieved.send(None)
            return

        expected_columns_in_questions = ["path", "questions", "embedding_0"]
        for name in expected_columns_in_questions:
            if name not in self.questions.domain:
                self.error(f'You need the following column in your "Questions" table: {name}')
                self.Outputs.retrieved.send(None)
                return

        expected_columns_in_chunks = ["path", "Unique ID", "Chunks", "Chunks index", "embedding_0"]
        for name in expected_columns_in_chunks:
            if name not in self.chunks.domain:
                self.error(f'You need the following column in your "Chunks" table: {name}')
                self.Outputs.retrieved.send(None)
                return

        self.load_model()
        if self.reranker is None:
            self.Outputs.retrieved.send(None)
            return

        self.progressBarInit()
        self.thread = thread_management.Thread(retrieve_chunks, self.questions, self.chunks, self.reranker,
                                               self.top_k, self.n_chunks, self.n_batches, self.restrict_to_path)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()


    def handle_progress(self, value):
        self.progressBarSet(value)

    def handle_result(self, result):
        if result is None:
            self.error("An error occurred.")
            self.Outputs.retrieved.send(None)
            return

        try:
            self.result = result
            self.Outputs.retrieved.send(result)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.retrieved.send(None)
            return

    def handle_finish(self):
        self.progressBarFinished()


    def load_model(self):
        self.error("")
        try:
            self.reranker = CrossEncoder(self.reranker_path)
        except Exception as e:
            self.error(f"An error occured when trying to load the model: {e}")
            self.reranker = None

    def post_initialized(self):
        pass


def retrieve_chunks(questions, chunks, reranker, top_k=100, n_chunks=10, n_batches=2, restrict_to_path=False, progress_callback=None, argself=None):
    # Convert table to dictionary for faster computation
    chunks_as_dict = chunk_table_to_dict(chunks)
    group = 0
    new_rows = []
    for i, row in enumerate(questions):
        path = row["path"].value
        question = row["questions"].value
        q_embeddings = [row[var].value for var in questions.domain if "embedding_" in var.name]

        # These are dictionaries instead of Table !
        chunks_cosine = retrieve_chunks_cosine(q_embeddings, chunks_as_dict, top_k=top_k, restrict_to_path=restrict_to_path, path=path)
        chunks_reranker = rerank_chunks(question, chunks_cosine, reranker)

        # Number of chunks actually available
        n_available = len(chunks_reranker)

        # Adapt the number of batches to the available chunks
        actual_n_batches = min(
            n_batches,
            (n_available + n_chunks - 1) // n_chunks,
        )

        for batch in range(actual_n_batches):
            start = batch * n_chunks
            end = start + n_chunks
            for chunk in chunks_reranker[start:end]:
                ID = chunk["id"]
                text = chunk["text"]
                score = chunk["score"]

                chunk_path = chunk["path"]
                chunk_index = chunk["index"]

                new_row = [path, question, group, chunk_path, ID, text, chunk_index, score]
                new_rows.append(new_row)

            group += 1

        if progress_callback is not None:
            progress_value = float(100 * (i + 1) / len(questions))
            progress_callback(progress_value)

        if argself is not None:
            if argself.stop:
                break

    var_path = StringVariable("path")
    var_question = StringVariable("questions")
    var_group = ContinuousVariable("group")
    var_uniqueID = StringVariable("Unique ID")
    var_chunk_path = StringVariable("Chunks path")
    var_chunk = StringVariable("Chunks")
    var_chunk_index = ContinuousVariable("Chunks index")
    var_score = ContinuousVariable("Score (reranking)")

    domain = Domain([], metas=[var_path, var_question, var_group, var_chunk_path, var_uniqueID, var_chunk, var_chunk_index, var_score])
    out_data = Table.from_list(domain=domain, rows=new_rows)
    return out_data





if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OW_M_RetrieveChunks()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
