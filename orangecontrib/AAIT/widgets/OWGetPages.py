import os
import sys
import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import OWWidget
import fitz  # PyMuPDF
from Orange.data import ContinuousVariable
from AnyQt.QtCore import QTimer
from Orange.widgets.settings import Setting


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import help_management

class OWGetPages(OWWidget):
    name = "Get Pages"
    description = ("Extract the PDF page number(s) corresponding to a text chunk contained  in the document. The data table must contain two columns: the PDF path (path) and the text chunks (Chunks)")
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/book.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/book.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owgetpages.ui")
    want_control_area = False
    priority = 1060
    one_row_per_chunk = Setting(False)
    autorun = Setting(True)

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)


    @Inputs.data
    def set_path_table(self, in_data):
        self.data = in_data
        if in_data is None:
            self.Outputs.data.send(None)
            return
        if self.autorun:
            self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(600)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.data = None

        # UI connections
        self.checkBox.setChecked(bool(self.autorun))
        self.pushButton.setEnabled(not self.autorun)
        self.checkBox.toggled.connect(self.on_autorun_checkbox_toggled)
        self.oneRowPerChunkCheckBox.setChecked(bool(self.one_row_per_chunk))
        self.oneRowPerChunkCheckBox.toggled.connect(self.on_orpc_checkbox_toggled)
        self.pushButton.clicked.connect(self.run)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def on_orpc_checkbox_toggled(self, state):
        self.one_row_per_chunk = bool(state)
        if self.data is not None:
            self.run()
    
    def on_autorun_checkbox_toggled(self, state):
        self.autorun = bool(state)
        self.pushButton.setEnabled(not self.autorun)
        if self.autorun and self.data is not None:
            self.run()

    def load_pdf_with_sparse_mapping(self, pdf_path):
        """
        Load PDF thanks to fitz and create a mapping to identify pages limits.
        The pages containing the chunks will then be identified efficiently.

        :param pdf_path: The path to a pdf.
        :return: A dictionary containing the limit indexes for each page of the document.
        """
        # Load the pdf
        doc = fitz.open(pdf_path)
        full_text = ""
        page_mapping = {}  # Sparse mapping: {page_num: (start_index, end_index)}

        # Iterate over each page
        for page_num in range(len(doc)):
            # Get the text from the page
            page_text = doc[page_num].get_text()
            # Get the start index
            start_index = len(full_text)
            full_text += page_text
            # Get the end index
            end_index = len(full_text) - 1
            # Store the indexes for current page
            page_mapping[page_num + 1] = (start_index, end_index)

        doc.close()
        return full_text, page_mapping

    def find_pages_for_extract(self, full_text, page_mapping, extract):
        """
        Identify the pages that a given extract belongs to.

        :param full_text: The complete text of the PDF.
        :param page_mapping: A dictionary with page numbers as keys and (start_index, end_index) as values.
        :param extract: The text snippet to locate.
        :return: A list of page numbers the extract spans.
        """
        if not extract:
            return []

        occurrence_pages = []

        idx = full_text.find(extract)

        occurrence_count = 0

        while idx != -1:

            occurrence_count += 1

            start_index = idx
            end_index = start_index + len(extract) - 1

            # Find which page contains this occurrence
            for page, (start, end) in page_mapping.items():

                if start <= end_index and end >= start_index:
                    occurrence_pages.append(page)

                    break

            idx = full_text.find(extract, idx + 1)

        return occurrence_pages

    def run(self):
        self.error(None)
        if self.data is None:
            return
        if not "path" in self.data.domain:
            self.error('You don\'t have "path" column in your input data.')
            self.Outputs.data.send(None)
            return

        if not "Chunks" in self.data.domain:
            self.error('You don\'t have "Chunks" column in your input data.')
            self.Outputs.data.send(None)
            return

        new_rows = []
        pages_column_data = []

        # Checkbox state
        one_row_per_chunk = self.one_row_per_chunk

        for row in self.data:
            path_value = row["path"].value

            if os.path.isfile(path_value):
                filepath = path_value
            elif "name" in self.data.domain:
                filepath = os.path.join(path_value, row["name"].value)
            else:
                filepath = path_value

            search_text = row["Chunks"].value
            try:
                full_text, page_mapping = self.load_pdf_with_sparse_mapping(filepath)
                pages = self.find_pages_for_extract(full_text, page_mapping, search_text)

            except Exception:
                pages = []

            # Default page if nothing found
            if not pages:
                pages = [1]

            # -----------------------------------
            # MODE 1:
            # one row per occurrence
            # -----------------------------------
            if one_row_per_chunk:
                for page in pages:
                    new_rows.append(row)
                    pages_column_data.append(page)

            # -----------------------------------
            # MODE 2, default mode:
            # first occurrence only
            # -----------------------------------
            else:
                new_rows.append(row)
                pages_column_data.append(pages[0])

        try:
            domain = self.data.domain

            # Build table directly from original rows
            output_data = Orange.data.Table(domain, new_rows)

            output_data = output_data.add_column(ContinuousVariable("page"), pages_column_data)
            self.Outputs.data.send(output_data)

        except Exception as e:
            self.error(f"Error building output table: {str(e)}")
            self.Outputs.data.send(None)

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWGetPages()
    my_widget.show()

    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()