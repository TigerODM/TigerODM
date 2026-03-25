import os
import sys
# import time
import requests
# import orangecanvas.application.canvasmain as canvasmain
import Orange.data
from AnyQt.QtWidgets import QApplication, QLabel
from Orange.widgets import widget # , gui
from Orange.widgets.utils.signals import Input, Output
# from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QLineEdit, QTextBrowser #, QTextEdit

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    # from Orange.widgets.orangecontrib.AAIT.llm import answers
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.IO4IT.utils.keys_manager import lire_config_api
else:
    # from orangecontrib.AAIT.llm import answers
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.IO4IT.utils.keys_manager import lire_config_api

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWDeep_Search(widget.OWWidget):
    name = "Deep Search"
    description = "Generate a response to a column 'prompt' with a LLM"
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/deepsearch.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/deepsearch.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owdeepsearch.ui")
    want_control_area = True
    priority = 1089

    class Inputs:
        prompt = Input("Prompt", Orange.data.Table)

    class Outputs:
        response = Output("Response", Orange.data.Table)

    SERVICE_NAME = "PERPLEXITY"

    @Inputs.prompt
    def set_prompt(self, in_prompt: Orange.data.Table):
        if in_prompt is None:
            self.Outputs.response.send(None)
            return
        if in_prompt is not None:
            if "prompt" not in in_prompt.domain:
                self.error("You need a column prompt");
                return
            self.prompt = str(in_prompt[0]["prompt"])  # ← cast en str
            self.error(None)
            if self.autorun:
                self.run()

    def __init__(self):
        super().__init__()
        # Qt Managementt
        self.setFixedWidth(700)
        self.setFixedHeight(500)
        uic.loadUi(self.gui, self)
        self.label_description = self.findChild(QLabel, 'Description')
        # print(self.label_description.text())
        self.line_api_key: QLineEdit = self.findChild(QLineEdit, "line_api_key")
        # Connexion du champ à la fonction de mise à jour
        self.line_api_key.editingFinished.connect(self.update_api_key)
        # Text browser
        self.textBrowser = self.findChild(QTextBrowser, 'textBrowser')
        # Data Management
        self.api_key = None
        self.prompt = None
        self.load_api_key()
        self.thread = None
        self.autorun = True
        self.can_run = True
        self.result = None  # sera ma table de sortie
        self.post_initialized()


    def load_api_key(self):
        try:
            cfg = lire_config_api(self.SERVICE_NAME)
            if cfg is None:
                self.error(f"⚠️ No API key stored for service '{self.SERVICE_NAME}'.\n"
                           "Use keys_manager.enregistrer_config_cli_api() to add one.")
                self.api_key = None
            else:
                self.api_key = cfg["api_key"]
                self.error(None)
        except Exception as e:
            self.api_key = None
            self.error(f"Error loading API key: {e}")

    def update_api_key(self):
        self.api_key = self.line_api_key.text().strip()

    def deepsearch(self, api_key: str, prompt: str):
        """
        Appelle Perplexity Sonar Deep-Research et renvoie la réponse complète
        dans une Orange Table (métadonnée 'response').
        """

        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        payload = {
            "model": "sonar-pro",
            "messages": [
                {"role": "system",
                 "content": ("You are a deep research assistant. "
                             "Answer only in Markdown without exposing any chain-of-thought.")},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 20_000,
            "format": "markdown"
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=600)
            resp.raise_for_status()
            answer_md = resp.json()["choices"][0]["message"]["content"]

        except requests.HTTPError: #as e:
            print("STATUS :", resp.status_code)  # affiche 400, 401, etc.
            print("DETAIL :", resp.text)  # message JSON complet de Perplexity

            answer_md = f"**Erreur Perplexity :** {resp.text}"

        except Exception as e:
            answer_md = f"**Erreur Perplexity :** {e}"

        # Affiche la réponse complète dans la console
        # print("Réponse Perplexity :\n", answer_md)

        response_var = Orange.data.StringVariable("response")

        domain = Orange.data.Domain([], metas=[response_var])
        out_data = Orange.data.Table.from_list(domain, [[answer_md]])
        return out_data

    def run(self):
        #print("I'm running...")
        #print(self.prompt)
        #print(self.api_key)
        if not self.can_run:
            return

        if self.prompt == None:
            return

        if self.api_key == None:
            #print("Je sors")
            return

        # If Thread is already running, interrupt it
        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        # Start progress bar
        self.progressBarInit()
        #◙self.textBrowser.setText("")

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        self.thread = thread_management.Thread(self.deepsearch, self.api_key, self.prompt)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, progress) -> None:
        value = progress[0]
        text = progress[1]
        if value is not None:
            self.progressBarSet(value)
        if text is None:
            self.textBrowser.setText("")
        else:
            self.textBrowser.insertPlainText(text)

    def handle_result(self, result):
        try:
            self.result = result
            self.Outputs.response.send(result)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.response.send(None)
            return

    def handle_finish(self):
        #print("Generation finished")
        self.progressBarFinished()


    def post_initialized(self):
        pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWDeep_Search()
    my_widget.show()
    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())

