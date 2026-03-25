import os
import sys
import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import OWWidget
import fitz  # PyMuPDF
from Orange.data import ContinuousVariable
import copy
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import help_management

class OWGetPages(OWWidget):
    name = "Get Pages"
    description = ("Extract the PDF page number corresponding to a text chunk contained in the document. The data table must contain two columns: the PDF path (path) and the text chunks (Chunks)")
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/book.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/book.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owgetpages.ui")
    want_control_area = False
    priority = 1060

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
        self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(600)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.data = None
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

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
        # Find the start index of the extract in the full text
        start_index = full_text.find(extract)
        if start_index == -1:
            return []  # Extract not found

        # Determine the end index of the extract
        end_index = start_index + len(extract) - 1

        # Find all pages the extract spans
        pages = []
        for page, (start, end) in page_mapping.items():
            if start <= end_index and end >= start_index:
                pages.append(page)

        return pages


    def run(self):
        self.error(None)
        if not "path" in self.data.domain:
            self.error('You don\'t have "path" column in your input data.')
            self.Outputs.data.send(None)
            return

        if not "Chunks" in self.data.domain:
            self.error('You don\'t have "Chunks" column in your input data.')
            self.Outputs.data.send(None)
            return
        pages = []
        for row in self.data:
            filepath = row["path"].value if os.path.isfile(row["path"].value) else os.path.join(row["path"].value,
                                                                                                row["name"].value)
            search_text = row["Chunks"].value
            try:
                full_text, page_mapping = self.load_pdf_with_sparse_mapping(filepath)
                page = self.find_pages_for_extract(full_text, page_mapping, search_text)[0]
            except:
                page = 1
            pages.append(page)
        if pages:
            print(f"The text was found on page(s): {pages}")
        else:
            print("The text was not found in the PDF.")

        data = copy.deepcopy(self.data)
        data = data.add_column(ContinuousVariable("page"), pages)
        self.Outputs.data.send(data)

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
