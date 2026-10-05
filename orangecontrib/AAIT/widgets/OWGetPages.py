import os
import sys
import unicodedata

import numpy as np
import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import OWWidget
import fitz  # PyMuPDF
from Orange.data import ContinuousVariable, StringVariable
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
    tolerant_search = Setting(False)
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

        self.tolerantCheckBox.setChecked(bool(self.tolerant_search))
        self.tolerantCheckBox.toggled.connect(self.on_tolerant_checkbox_toggled)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def on_orpc_checkbox_toggled(self, state):
        self.one_row_per_chunk = bool(state)
        if self.data is not None:
            self.run()

    def on_tolerant_checkbox_toggled(self, state):
        self.tolerant_search = bool(state)
        if self.data is not None:
            self.run()

    def on_autorun_checkbox_toggled(self, state):
        self.autorun = bool(state)
        self.pushButton.setEnabled(not self.autorun)
        if self.autorun and self.data is not None:
            self.run()

    def load_pdf_with_sparse_mapping(self, pdf_path, normalize=False):
        """
        Load PDF thanks to fitz and create a mapping to identify pages limits.
        The pages containing the chunks will then be identified efficiently.

        :param pdf_path: The path to a pdf.
        :param normalize: If True, each page is NFC-normalised (tolerant search),
                          so that accents made of two code points count as one.
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
            if normalize:
                page_text = unicodedata.normalize("NFC", page_text)
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

    def match_key_map(self, text):
        """
        Build the "match key" of a text: the text reduced to what survives any
        extractor (Word, PDF). Whitespace, hyphens/dashes and invisible characters
        are dropped, ligatures are expanded and case is ignored, so two texts that
        look the same on screen get the same key, whatever the source format.

        :param text: The text to reduce.
        :return: (key, index_map) where index_map[i] is the index, in text, of the
                 character that produced key[i]. It allows going back from a position
                 in the key to the original text.
        """
        key, imap = [], []
        for i, ch in enumerate(text):
            if ch < "\x80":
                # ASCII fast path (most of the text): no Unicode normalisation needed
                if ch == "-" or ch.isspace():
                    continue
                key.append(ch.lower())
                imap.append(i)
                continue
            for c in unicodedata.normalize("NFKC", ch).casefold():
                # Skip whitespace, dashes (Pd), invisible chars (Cf) and minus sign
                if c.isspace() or unicodedata.category(c) in ("Pd", "Cf") or c == "\u2212":
                    continue
                key.append(c)
                imap.append(i)
        return "".join(key), imap

    def match_key(self, text):
        """
        Match key of a text snippet (see match_key_map), without the index map.

        :param text: The text snippet.
        :return: The match key.
        """
        return self.match_key_map(unicodedata.normalize("NFC", str(text)))[0]

    def find_pages_for_extract_tolerant(self, full_text, key, imap, page_mapping, extract):
        """
        Same as find_pages_for_extract, but the comparison is done on match keys
        (see match_key_map), so hyphens, spaces, line breaks, ligatures and case
        are ignored.

        :param full_text: The complete (NFC-normalised) text of the PDF.
        :param key: The match key of full_text.
        :param imap: The index map of the key (key position -> full_text position).
        :param page_mapping: A dictionary with page numbers as keys and (start_index, end_index) as values.
        :param extract: The text snippet to locate.
        :return: A list of (page number, text as written in the PDF), one per occurrence.
        """
        extract_key = self.match_key(extract) if extract else ""
        if not extract_key:
            return []

        occurrences = []
        pos = key.find(extract_key)

        while pos != -1:
            # Back to positions in the original text
            start_index = imap[pos]
            end_index = imap[pos + len(extract_key) - 1]

            # Find which page contains this occurrence
            for page, (start, end) in page_mapping.items():
                if start <= end_index and end >= start_index:
                    occurrences.append((page, full_text[start_index:end_index + 1]))
                    break

            pos = key.find(extract_key, pos + 1)

        return occurrences

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
        matched_column_data = []  # only used in tolerant mode

        # Checkbox states
        one_row_per_chunk = self.one_row_per_chunk
        tolerant = self.tolerant_search

        # Each PDF is read (and its key computed) only once per run
        pdf_cache = {}

        for row in self.data:
            path_value = row["path"].value

            if os.path.isfile(path_value):
                filepath = path_value
            elif "name" in self.data.domain:
                filepath = os.path.join(path_value, row["name"].value)
            else:
                filepath = path_value

            search_text = row["Chunks"].value

            if filepath not in pdf_cache:
                try:
                    full_text, page_mapping = self.load_pdf_with_sparse_mapping(filepath, normalize=tolerant)
                    key, imap = self.match_key_map(full_text) if tolerant else (None, None)
                    pdf_cache[filepath] = (full_text, page_mapping, key, imap)
                except Exception:
                    pdf_cache[filepath] = None

            # occurrences: list of (page, text as written in the PDF)
            occurrences = []
            loaded = pdf_cache[filepath]
            if loaded is not None:
                full_text, page_mapping, key, imap = loaded
                try:
                    if tolerant:
                        occurrences = self.find_pages_for_extract_tolerant(
                            full_text, key, imap, page_mapping, search_text)
                    else:
                        pages = self.find_pages_for_extract(full_text, page_mapping, search_text)
                        occurrences = [(page, "") for page in pages]
                except Exception:
                    occurrences = []

            # Default page if nothing found (matched_text stays empty = not found)
            if not occurrences:
                occurrences = [(1, "")]

            # -----------------------------------
            # MODE 1:
            # one row per occurrence
            # -----------------------------------
            if one_row_per_chunk:
                for page, matched in occurrences:
                    new_rows.append(row)
                    pages_column_data.append(page)
                    matched_column_data.append(matched)

            # -----------------------------------
            # MODE 2, default mode:
            # first occurrence only
            # -----------------------------------
            else:
                new_rows.append(row)
                pages_column_data.append(occurrences[0][0])
                matched_column_data.append(occurrences[0][1])

        try:
            domain = self.data.domain

            # Build table directly from original rows
            output_data = Orange.data.Table(domain, new_rows)

            output_data = output_data.add_column(ContinuousVariable("page"), pages_column_data)

            # Tolerant mode only: text as written in the PDF (empty = not found).
            # Not added in exact mode, so existing workflows get the same output.
            if tolerant:
                output_data = output_data.add_column(
                    StringVariable("matched_text"),
                    np.array(matched_column_data, dtype=object),
                    to_metas=True)

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
