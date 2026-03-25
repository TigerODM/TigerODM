import os
import sys
import math
from rank_bm25 import BM25Okapi

import Orange
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.data import  ContinuousVariable
from thefuzz import fuzz
from AnyQt.QtWidgets import QApplication, QComboBox
from Orange.widgets.settings import Setting
from AnyQt.QtCore import QTimer

# Import intelligent selon contexte
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import thread_management, help_management
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWKeywordsDetection(widget.OWWidget):
    name = "Keywords Detection"
    description = 'The input Data must contain a column "content". The input Keywords must contain a column "keywords". This widget will count the number of keywords that occur in the content with a fuzzy matching (percentage based on small variations).'
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/owkeywordsdetection.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owkeywordsdetection.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owkeywordsdetection.ui")
    want_control_area = False
    priority = 1071

    # Settings
    mode = Setting("Fuzzy")

    class Inputs:
        data = Input("Data", Orange.data.Table)
        keywords = Input("Keywords", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)


    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.autorun:
            self.run()

    @Inputs.keywords
    def set_keywords(self, in_keywords):
        self.keywords = in_keywords
        if self.autorun:
            self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        self.combobox_mode = self.findChild(QComboBox, "comboBox")
        self.combobox_mode.setCurrentIndex(self.combobox_mode.findText(self.mode))
        self.combobox_mode.currentTextChanged.connect(self.on_mode_changed)

        # Data Management
        self.data = None
        self.keywords = None
        self.thread = None
        self.autorun = True
        self.result = None

        # Custom updates
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def on_mode_changed(self, text):
        self.mode = text
        self.run()


    def run(self):
        self.error("")
        self.warning("")

        # If Thread is already running, interrupt it
        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            return

        if self.keywords is None:
            self.Outputs.data.send(None)
            return

        if "content" not in self.data.domain:
            self.error('You need a "content" column in your input Data.')
            self.Outputs.data.send(None)
            return

        if "keywords" not in self.keywords.domain:
            self.error('You need a "keywords" column in your input Keywords.')
            self.Outputs.data.send(None)
            return


        self.progressBarInit()

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        self.thread = thread_management.Thread(compute_keywords_on_table, self.data, self.keywords, self.mode)
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
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        print("Keywords computation finished !")
        self.progressBarFinished()

    def post_initialized(self):
        pass



def compute_keywords_on_table(table, keywords, mode="Fuzzy", progress_callback=None, argself=None):
    """
    Compute fuzzy match scores between table rows and a list of keywords,
    and add them as a new meta column.

    Args:
        table (Orange.data.Table): Input table with a "content" column.
        keywords (Orange.data.Table): Table with a "keywords" column.
        mode (str): Type of keyword search, "Fuzzy" or "Strict".
        progress_callback (callable, optional): Function called with progress (0–100).
        argself (object, optional): If has attribute `stop=True`, stops processing early.

    Returns:
        Orange.data.Table: Copy of input with a new meta column "Score - Keywords".
    """
    # Make a copy of the table to avoid modifying the original
    data = table.copy()

    # Extract the list of keywords from the 'keywords' table
    keywords_list = [row["keywords"].value for row in keywords]

    if mode == "Elastic":
        corpus = [row["content"].value for row in data]
        scores = get_bm25_scores(corpus, keywords_list)

    else:
        scores = []
        # Iterate over each row in the copied table
        for i, row in enumerate(data):
            content = row["content"].value  # Text from the 'content' column
            score = 0
            if mode == "Fuzzy":
                score = fuzzy_match_score(content, keywords_list)  # Compute similarity score
            elif mode == "Strict":
                score = strict_match_score(content, keywords_list)

            scores.append(score)

            # Update progress if a progress callback is provided
            if progress_callback is not None:
                progress_value = float(100 * (i + 1) / len(data))
                progress_callback(progress_value)

            # Stop loop if 'argself' exists and stop flag is set
            if argself is not None:
                if argself.stop:
                    break

    # Create a new continuous variable (column) for keyword scores
    score_var = ContinuousVariable("Score - Keywords")
    # Add the scores as a meta attribute to the table
    data = data.add_column(score_var, scores, to_metas=True)

    return data



def fuzzy_match_score(text, keywords_list):
    """
    Checks if keywords are present in text using fuzzy matching
    and returns a global score.

    Args:
        text (str): The full text to search in.
        keywords_list (list): List of keywords to find.

    Returns:
        float: Global match score (0-100).
    """
    keywords_list = list(filter(None, keywords_list))
    if len(keywords_list)==0:
        return 0

    words = text.split(" ")  # Split text into words
    total_score = 0

    for keyword in keywords_list:
        best_score = max(fuzz.ratio(word.lower(), keyword.lower()) for word in words)
        total_score += best_score

    return total_score / len(keywords_list)  # Normalize score


def strict_match_score(text, keywords_list):
    """
    Checks if keywords are present in text using exact matching
    and returns a global score (0 or 100).

    Args:
        text (str): The full text to search in.
        keywords_list (list): List of keywords to find.

    Returns:
        float: Global match score (0-100).
    """
    keywords_list = list(filter(None, keywords_list))
    if len(keywords_list) == 0:
        return 0.0

    # Normalize text and split into words
    words = set(text.lower().split())

    matches = sum(1 for keyword in keywords_list if keyword.lower() in words)
    score = (matches / len(keywords_list)) * 100
    return score


### Gemini freestyle
def bm25_match_score(text, keywords_list, idf_map=None, k1=1.5, b=0.75, avg_dl=10.0):
    """
    Calculates the BM25 score for a text given a list of keywords.

    Args:
        text (str): The document text.
        keywords_list (list): The query terms.
        idf_map (dict): Precomputed IDF scores for terms.
                        If None, defaults to 1.0 for all terms.
        k1 (float): Term frequency saturation parameter (usually 1.2 to 2.0).
        b (float): Length normalization parameter (usually 0.75).
        avg_dl (float): Average length of documents in the collection.

    Returns:
        float: The BM25 relevance score.
    """
    if not keywords_list or not text:
        return 0.0

    # Tokenize and normalize
    doc_words = text.lower().split()
    doc_len = len(doc_words)

    # Calculate term frequencies in this specific document
    tf_counts = {}
    for word in doc_words:
        tf_counts[word] = tf_counts.get(word, 0) + 1

    score = 0.0
    for keyword in keywords_list:
        keyword = keyword.lower()
        if keyword not in tf_counts:
            continue

        # Get IDF (default to 1.0 if not provided)
        idf = idf_map.get(keyword, 1.0) if idf_map else 1.0

        # Calculate TF component with saturation and length normalization
        tf = tf_counts[keyword]
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * (doc_len / avg_dl))

        score += idf * (numerator / denominator)

    return score

### Gemini freestyle
def calculate_idf(corpus):
    """
    Args:
        corpus (list of str): All documents in your dataset.
    """
    N = len(corpus)
    idf_map = {}
    words_in_docs = [set(doc.lower().split()) for doc in corpus]

    # Find all unique words across all docs
    all_unique_words = set().union(*words_in_docs)

    for word in all_unique_words:
        # Number of documents containing the word
        n_q = sum(1 for doc_set in words_in_docs if word in doc_set)
        # Standard BM25 IDF formula
        idf_map[word] = math.log((N - n_q + 0.5) / (n_q + 0.5) + 1.0)

    return idf_map



def get_bm25_scores(corpus, keywords_list):
    """
    Calcule les scores BM25 pour un corpus entier par rapport à des mots-clés.

    Args:
        corpus (list of str): Liste de textes (documents).
        keywords_list (list of str): Liste des mots-clés de recherche.

    Returns:
        list of float: Les scores pour chaque document du corpus.
    """
    # 1. Préparation des données (Tokenization simple)
    # La bibliothèque attend une liste de listes de mots
    tokenized_corpus = [doc.lower().split() for doc in corpus]
    tokenized_query = [keyword.lower() for keyword in keywords_list]

    # 2. Initialisation du modèle BM25
    # C'est ici que k1, b et avg_dl sont calculés/appliqués
    bm25 = BM25Okapi(tokenized_corpus)

    # 3. Calcul des scores
    scores = bm25.get_scores(tokenized_query)

    return scores



if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWKeywordsDetection()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()

