import os
import sys

import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtCore import QTimer
from Orange.widgets.settings import Setting


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import process_documents
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.llm import process_documents
    from orangecontrib.AAIT.utils import thread_management, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWLoadDocuments(widget.OWWidget):
    name = "Load Documents"
    description = "Loads the data from the textual (pdf, docx, md, txt, py, html, json, ows) documents contained in the 'path' column."
    category = "AAIT - TOOLBOX"
    icon = "icons/owloaddocuments.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owloaddocuments.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owloaddocuments.ui")
    want_control_area = False
    priority = 1060

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)
        details = Output("Details", Orange.data.Table)

    detailed_docx_loading = Setting(False)
    per_page_loading = Setting(False)
    autorun = Setting(True)

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
        self.thread = None
        self.result = None

        self.pushButton_send.setEnabled(True) 
        self.checkBox_send.setEnabled(True) 
        self.checkBox_detailed.setEnabled(True) 

        # Initialise the checkBoxes from the settings
        self.checkBox_send.setChecked(bool(self.autorun))
        self.checkBox_detailed.setChecked(bool(self.detailed_docx_loading))
        self.checkBox_pages.setChecked(bool(self.per_page_loading))
        


        self.post_initialized()

        # Auto-send checkbox (checkBox_send in the .ui)
        self.checkBox_send.stateChanged.connect(self.on_autosend_checkbox_toggled)

        # Detailed docx loading checkbox
        self.checkBox_detailed.stateChanged.connect(self.on_detailed_checkbox_toggled)

        # Per page loading
        self.checkBox_pages.stateChanged.connect(self.on_pages_checkbox_toggled)

        # Run button
        self.pushButton_send.clicked.connect(self.run)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))


    def on_autosend_checkbox_toggled(self, state):
        self.autorun = bool(state)
        if self.autorun:
            self.run()

    def on_pages_checkbox_toggled(self, state):
        self.per_page_loading = bool(state)
        if state and self.detailed_docx_loading:
            # Décoche l'autre case sans déclencher son handler (pas de double run)
            self.checkBox_detailed.blockSignals(True)
            self.checkBox_detailed.setChecked(False)
            self.checkBox_detailed.blockSignals(False)
            self.detailed_docx_loading = False
        if not state:
            self.Outputs.details.send(None)
        if self.autorun:
            self.run()

    def on_detailed_checkbox_toggled(self, state):
        self.detailed_docx_loading = bool(state)
        if state and self.per_page_loading:
            # Décoche l'autre case sans déclencher son handler (pas de double run)
            self.checkBox_pages.blockSignals(True)
            self.checkBox_pages.setChecked(False)
            self.checkBox_pages.blockSignals(False)
            self.per_page_loading = False
        if not state:
            self.Outputs.details.send(None)
        if self.autorun:
            self.run()

    def run(self):
        self.warning("")
        self.error("")

        # If Thread is already running, interrupt it
        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            self.Outputs.details.send(None)
            return

        if "path" not in self.data.domain:
            self.error("You need a 'path' column in your input data.")
            self.Outputs.data.send(None)
            self.Outputs.details.send(None)
            return

        if "content" in self.data.domain:
            self.error("You must not have a 'content' column in your input data, because one will be added.")
            self.Outputs.data.send(None)
            self.Outputs.details.send(None)
            return

        if "name" in self.data.domain:
            self.error("You must not have a 'name' column in your input data, because one will be added.")
            self.Outputs.data.send(None)
            self.Outputs.details.send(None)
            return

        if self.detailed_docx_loading and "type" in self.data.domain:
            self.error("You must not have a 'type' column in your input data when using detailed loading.")
            self.Outputs.data.send(None)
            self.Outputs.details.send(None)
            return
        
        if self.per_page_loading and "page" in self.data.domain:
            self.error("You must not have a 'page' column in your input data when using per-page loading.")
            self.Outputs.data.send(None)
            self.Outputs.details.send(None)
            return
        
        # Start progress bar
        self.progressBarInit()

        # Choose the loading function based on the checkbox
        if self.per_page_loading:
            loading_fn = process_documents.load_documents_per_page
        elif self.detailed_docx_loading:
            loading_fn = process_documents.load_documents_in_table_detailed
        else:
            loading_fn = process_documents.load_documents_in_table

        # Thread management
        self.thread = thread_management.Thread(loading_fn, self.data)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.result = result
            if isinstance(result, tuple):
                main_table, details_table = result
                self.Outputs.data.send(main_table)
                self.Outputs.details.send(details_table)
            else:
                self.Outputs.data.send(result)
                self.Outputs.details.send(None)

        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            self.Outputs.details.send(None)
            return

    def handle_finish(self):
        print("Text documents loading is finished.")
        self.progressBarFinished()

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWLoadDocuments()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()