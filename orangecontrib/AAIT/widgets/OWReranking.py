import os
import sys

import Orange.data
from Orange.data import Table, Domain, ContinuousVariable
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output

from sentence_transformers import CrossEncoder
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import thread_management, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file



@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWReranking(widget.OWWidget):
    name = "Reranking"
    description = "Apply a reranker to the column 'content' of your input data, in regards to a column 'request' in your request data."
    category = "AAIT - TOOLBOX"
    icon = "icons/owreranking.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owreranking.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owreranking.ui")
    want_control_area = False
    priority = 1212

    class Inputs:
        data = Input("Data", Orange.data.Table)
        request = Input("Request", Orange.data.Table)
        model_path = Input("Model", str, auto_summary=False)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        # if self.autorun:
        #     self.run()

    @Inputs.request
    def set_request(self, in_request):
        self.data_request = in_request
        # if self.autorun:
        #     self.run()

    @Inputs.model_path
    def set_model_path(self, in_model_path):
        self.model_path = in_model_path
        # if self.autorun:
        #     self.run()

    def handleNewSignals(self):
        self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        # Data Management
        self.data = None
        self.data_request = None
        self.model_path = None
        self.model = None
        self.thread = None
        self.autorun = True
        self.result = None
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))


    def run(self):
        self.error("")
        self.warning("")

        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            return

        if self.data_request is None:
            self.Outputs.data.send(None)
            return

        if self.model_path is None:
            self.Outputs.data.send(None)
            return

        self.load_model()
        if self.model is None:
            self.Outputs.data.send(None)
            return

        # Verification of in_data
        if not "content" in self.data.domain or type(self.data.domain["content"]).__name__ != "StringVariable":
            self.error('You need a "content" column as a text variable in your input data')
            return

        if not "request" in self.data_request.domain or type(self.data_request.domain["request"]).__name__ != "StringVariable":
            self.error('You need a "request" column as a text variable in your input request')
            return


        request = self.data_request[0]["request"].value

        # Start progress bar
        self.progressBarInit()

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        self.thread = thread_management.Thread(self.rerank_table, self.data, request, self.model)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.result = result
            self.Outputs.data.send(result)
            # self.data = None
            # self.data_request = None
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        print("Reranking finished")
        self.progressBarFinished()

    def post_initialized(self):
        pass


    def load_model(self):
        self.error("")
        try:
            self.model = CrossEncoder(self.model_path)
        except Exception as e:
            self.error(f"An error occured when trying to load the model: {e}")
            self.model = None


    def rerank_table(self, table, request, model, progress_callback=None, argself=None):
        # Copy of input data
        data = table.copy()
        attr_dom = list(data.domain.attributes)
        metas_dom = list(data.domain.metas)
        class_dom = list(data.domain.class_vars)

        # Get the "content" but keep the entire row
        documents = [(row["content"].value, row) for row in data]
        # Create request - content pairs for scoring
        pairs = [(request, content) for content, _ in documents]
        scores = model.predict(pairs)

        # Combine scores with original rows
        scored_rows = list(zip(scores, documents))
        sorted_rows = sorted(scored_rows, key=lambda x: x[0], reverse=True)

        # Iterate on the data Table
        rows = []
        for i, (score, (_, row)) in enumerate(sorted_rows):
            # Get the rest of the data
            features = [row[x] for x in attr_dom]
            targets = [row[y] for y in class_dom]
            metas = list(row.metas)
            new_row = features + targets + metas + [score]
            rows.append(new_row)
            if progress_callback is not None:
                progress_value = float(100 * (i + 1) / len(sorted_rows))
                progress_callback(progress_value)
            if argself is not None:
                if argself.stop:
                    break

        # Create new Domain for new columns
        score_var = [ContinuousVariable("Score (reranking)")]
        domain = Domain(attributes=attr_dom, metas=metas_dom + score_var, class_vars=class_dom)

        # Create and return table
        out_data = Table.from_list(domain=domain, rows=rows)
        return out_data


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWReranking()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
