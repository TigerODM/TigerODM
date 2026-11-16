import os
import sys
import math
import numpy as np
from rank_bm25 import BM25Okapi

import Orange
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.data import ContinuousVariable, StringVariable, Domain, Table
from thefuzz import fuzz
from AnyQt.QtWidgets import QApplication, QComboBox, QCheckBox, QSpinBox
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
    top_keywords_mode = Setting(False)
    top_x = Setting(10)

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

        # Mode Combobox
        self.combobox_mode = self.findChild(QComboBox, "comboBox")
        self.combobox_mode.setCurrentIndex(self.combobox_mode.findText(self.mode))
        self.combobox_mode.currentTextChanged.connect(self.on_mode_changed)

        # Top Keywords Checkbox
        self.checkbox_top = self.findChild(QCheckBox, "checkBox_top_keywords")
        if self.checkbox_top:
            self.checkbox_top.setChecked(self.top_keywords_mode)
            self.checkbox_top.stateChanged.connect(self.on_top_keywords_changed)

        # Top X Spinbox
        self.spinbox_x = self.findChild(QSpinBox, "spinBox_top_x")
        if self.spinbox_x:
            self.spinbox_x.setValue(self.top_x)
            self.spinbox_x.valueChanged.connect(self.on_top_x_changed)

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

    def on_top_keywords_changed(self, state):
        self.top_keywords_mode = bool(state)
        self.run()
        
    def on_top_x_changed(self, value):
        self.top_x = value
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

        self.thread = thread_management.Thread(
            compute_keywords_on_table, 
            self.data, 
            self.keywords, 
            self.mode, 
            self.top_keywords_mode, 
            self.top_x
        )
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



def compute_keywords_on_table(table, keywords, mode="Fuzzy", top_keywords_mode=False, top_x=10, progress_callback=None, argself=None):
    """
    Compute fuzzy match scores between table rows and a list of keywords.
    If top_keywords_mode is False: Adds a new meta column to the input table.
    If top_keywords_mode is True: Returns a new table associating each 'content' with its Top X keywords and scores.
    """
    data = table.copy()
    keywords_list = [row["keywords"].value for row in keywords if row["keywords"].value]
    
    if len(keywords_list) == 0:
        return data

    if top_keywords_mode:
        # Mode : Extraction du TOP X Mots-clés POUR CHAQUE LIGNE (content)
        corpus = [row["content"].value for row in data]
        total_steps = len(data)
        
        out_X = []
        out_metas = []
        
        if mode == "Elastic":
            tokenized_corpus = [doc.lower().split() for doc in corpus]
            bm25 = BM25Okapi(tokenized_corpus)
            
            # Précalcul des scores BM25 de chaque mot-clé contre tous les documents
            keyword_to_scores = {}
            for kw in keywords_list:
                keyword_to_scores[kw] = bm25.get_scores([kw.lower()])
                
            for i, row in enumerate(data):
                content = row["content"].value
                
                # Scores de tous les mots-clés pour ce document précis
                doc_scores = {kw: keyword_to_scores[kw][i] for kw in keywords_list}
                
                # Tri et récupération du Top X pour ce contenu
                sorted_kws = sorted(doc_scores.items(), key=lambda item: item[1], reverse=True)[:top_x]
                
                for kw, score in sorted_kws:
                    out_X.append([score])
                    out_metas.append([content, kw])
                    
                if progress_callback:
                    progress_callback(float(100 * (i + 1) / total_steps))
                if argself and argself.stop:
                    break
                    
        else:
            # Fuzzy ou Strict
            for i, row in enumerate(data):
                content = row["content"].value
                doc_scores = {}
                
                for kw in keywords_list:
                    if mode == "Fuzzy":
                        doc_scores[kw] = fuzzy_match_single(content, kw)
                    elif mode == "Strict":
                        doc_scores[kw] = strict_match_single(content, kw)
                        
                # Tri et récupération du Top X pour ce contenu
                sorted_kws = sorted(doc_scores.items(), key=lambda item: item[1], reverse=True)[:top_x]
                
                for kw, score in sorted_kws:
                    out_X.append([score])
                    out_metas.append([content, kw])
                    
                if progress_callback:
                    progress_callback(float(100 * (i + 1) / total_steps))
                if argself and argself.stop:
                    break

        # Création de la table de sortie : 3 colonnes (score, content, keyword)
        domain = Domain([ContinuousVariable("score")], metas=[StringVariable("content"), StringVariable("keyword")])
        
        if len(out_X) == 0:
            X_arr = np.empty((0, 1), dtype=float)
            metas_arr = np.empty((0, 2), dtype=object)
        else:
            X_arr = np.array(out_X, dtype=float)
            metas_arr = np.array(out_metas, dtype=object)
            
        out_table = Table.from_numpy(domain, X=X_arr, metas=metas_arr)
        return out_table

    else:
        # Comportement original : Score global pour chaque ligne
        scores = []
        if mode == "Elastic":
            corpus = [row["content"].value for row in data]
            scores = get_bm25_scores(corpus, keywords_list)
            if progress_callback:
                progress_callback(100.0)
        else:
            for i, row in enumerate(data):
                content = row["content"].value
                if mode == "Fuzzy":
                    score = fuzzy_match_score(content, keywords_list)
                elif mode == "Strict":
                    score = strict_match_score(content, keywords_list)

                scores.append(score)

                if progress_callback is not None:
                    progress_callback(float(100 * (i + 1) / len(data)))
                if argself is not None and argself.stop:
                    break

        score_var = ContinuousVariable("Score - Keywords")
        data = data.add_column(score_var, scores, to_metas=True)
        return data


def fuzzy_match_single(text, keyword):
    """Calcule le score fuzzy pour un SEUL mot clé dans le texte"""
    words = text.split(" ")
    if not words:
        return 0
    return max((fuzz.ratio(word.lower(), keyword.lower()) for word in words), default=0)

def strict_match_single(text, keyword):
    """Calcule le score strict pour un SEUL mot clé dans le texte"""
    words = set(text.lower().split())
    return 100.0 if keyword.lower() in words else 0.0

def fuzzy_match_score(text, keywords_list):
    keywords_list = list(filter(None, keywords_list))
    if len(keywords_list) == 0:
        return 0
    words = text.split(" ")
    total_score = sum(fuzzy_match_single(text, kw) for kw in keywords_list)
    return total_score / len(keywords_list)

def strict_match_score(text, keywords_list):
    keywords_list = list(filter(None, keywords_list))
    if len(keywords_list) == 0:
        return 0.0
    words = set(text.lower().split())
    matches = sum(1 for keyword in keywords_list if keyword.lower() in words)
    return (matches / len(keywords_list)) * 100

def get_bm25_scores(corpus, keywords_list):
    tokenized_corpus = [doc.lower().split() for doc in corpus]
    tokenized_query = [keyword.lower() for keyword in keywords_list]
    bm25 = BM25Okapi(tokenized_corpus)
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