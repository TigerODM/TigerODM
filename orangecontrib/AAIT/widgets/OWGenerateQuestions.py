import os
import sys
import re
import copy
import numpy as np
import ntpath

import Orange.data
from Orange.data import StringVariable, Domain, Table
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from sentence_transformers import SentenceTransformer
from AnyQt.QtCore import QTimer


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import lmstudio
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.llm import lmstudio
    from orangecontrib.AAIT.utils import thread_management, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWGenerateQuestions(widget.OWWidget):
    name = "Generate Questions"
    description = "Generate questions on the column 'content' of an input table"
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/owgeneratequestions.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owgeneratequestions.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owgeneratequestions.ui")
    want_control_area = False
    priority = 1060

    class Inputs:
        #data = Input("Data for GPT4All", Orange.data.Table)
        data_lmstudio = Input("Data for LMStudio", Orange.data.Table)
        model = Input("Model", str, auto_summary=False)
        embedder = Input("Embedder", SentenceTransformer, auto_summary=False)

    class Outputs:
        data = Output("Data", Orange.data.Table)


    @Inputs.data_lmstudio
    def set_data_lmstudio(self, in_data):
        if in_data is None:
            self.Outputs.data.send(None)
            return
        self.data_lmstudio = in_data
        self.data = None
        if self.autorun:
            self.run()

    @Inputs.model
    def set_model(self, in_model):
        self.model = in_model
        if self.autorun:
            self.run()

    @Inputs.embedder
    def set_embedder(self, in_embedder):
        self.embedder = in_embedder
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
        self.data_lmstudio = None
        self.model = None
        self.embedder = None
        self.thread = None
        self.autorun = True
        self.result = None
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def run(self):
        self.error("")
        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()
            return

        # Verify inputs
        if self.data is None and self.data_lmstudio is None:
            return

        if self.data and self.data_lmstudio:
            self.error('You cannot have both inputs GPT4All and LMStudio.')
            return

        if self.model is None:
            return

        if self.embedder is None:
            return

        # If LMStudio is used : verify settings
        if self.data_lmstudio is not None:
            llm = 'lmstudio'
            data = self.data_lmstudio
            model_list = lmstudio.get_model_lmstudio()
            if isinstance(model_list, str) and model_list == "Error":
                self.error("Please launch the LMStudio app and start the server.")
                return
            # Verify that the models directory is set in LMStudio (aait_store)
            if model_list is None:
                self.error("Your models directory in LMStudio is not set properly.")
                return

            # Verify that the plugged model exists in your LMStudio model list
            if not any(ntpath.basename(d["id"]).lower() == ntpath.basename(self.model.lower()) for d in model_list["data"]):
                self.error(f"Model not found in LMStudio. You are trying to use {ntpath.basename(self.model.lower())}, please verify that this model's API identifier exists in LMStudio.")
                return
            for d in model_list["data"]:
                if ntpath.basename(d["id"]).lower() == ntpath.basename(self.model.lower()):
                    self.model = d["id"]

        # IF GPT4All is used
        if self.data is not None:
            llm = 'gpt4all'
            data = self.data
            self.model = ntpath.basename(self.model)

        # Verification of in_data
        try:
            data.domain["content"]
        except KeyError:
            self.error('You need a "content" column in input data')
            return

        if type(data.domain["content"]).__name__ != 'StringVariable':
            self.error('"content" column needs to be a Text')
            return

        # Start progress bar
        self.progressBarInit()

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        self.thread = thread_management.Thread(self.generate_questions_on_table, data, self.model, self.embedder, llm)
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
        print("Question generation finished")
        self.progressBarFinished()
        self.thread = None

    def post_initialized(self):
        pass


    def generate_questions_on_table(self, table, model, embedder, llm="gpt4all", progress_callback=None, argself=None):
        data = copy.deepcopy(table)
        new_metas = list(data.domain.metas) + [StringVariable("Questions")]
        new_domain = Domain(data.domain.attributes, data.domain.class_vars, new_metas)

        new_rows = []
        for i, row in enumerate(data):
            print(f"\n\n -- Working on row {i}")
            content = row["content"].value
            questions = self.generate_dataset_on_chunk(content, model, embedder, llm)
            for question in questions:
                new_metas_values = list(row.metas) + [question]
                new_instance = Orange.data.Instance(new_domain, [row[x] for x in data.domain.attributes] + [row[y] for y in data.domain.class_vars] + new_metas_values)
                new_rows.append(new_instance)
                if progress_callback is not None:
                    progress_value = float(100 * (i + 1) / len(data))
                    progress_callback(progress_value)
            if argself:
                if argself.stop:
                    break

        out_data = Table.from_list(domain=new_domain, rows=new_rows)
        return out_data



    def generate_dataset_on_chunk(self, chunk, model, embedder, llm="gpt4all", threshold=0.7, max_repeat=5, safety_limit=15,
                                  previous_results=None):
        """
        Generates a dataset of unique questions and answers for a given text chunk.

        Parameters:
            model: The language model used to generate questions and answers.
            embedder: A sentence embedding model used to encode questions for similarity checks.
            chunk (str): The text chunk to process.
            threshold (float): The cosine similarity threshold for considering two questions as duplicates (default: 0.95).
            max_repeat (int): The maximum number of iterations to attempt generating unique questions (default: 20).
            safety_limit (int): A hard limit on the total number of iterations to avoid infinite loops (default: 200).
            previous_results(dict): A dictionnary containing the lists of embeddings, questions and answers for the given chunk

        Returns:
            tuple: A tuple containing two lists:
                - saved_questions (list of str): The list of unique questions.
                - saved_answers (list of str): The list of answers corresponding to the questions.
        """
        # Initialize lists to store unique embeddings, questions, and answers
        saved = []  # Stores embeddings of unique questions
        saved_questions = []  # Stores unique questions
        saved_answers = []  # Stores answers corresponding to the unique questions

        # Initialize counters for loop control
        repeat = 0  # Tracks the number of successful iterations adding unique questions
        safety = 0  # Tracks the total number of iterations to prevent infinite loops

        # Continue generating questions until max_repeat or safety_limit is reached
        while repeat < max_repeat and safety < safety_limit:
            print(f"\nRepeated: {repeat}/{max_repeat} | Safety: {safety}/{safety_limit}")
            # Generate questions and answers using the model
            try:
                model_output = self.generate_questions_and_answers(model, chunk, llm)
                questions = self.parse_questions_and_answers(model_output)
            except TypeError:
                self.error("The model could not generate an answer. Please make sure your model is loaded in LMStudio.")
                return []
            print("### Questions generated:", len(questions))
            answers = questions

            if questions != [] and answers != []:
                # Iterate over the generated questions and answers
                added = []
                # print(f"{len(questions)} questions generated")
                # print(f"{len(saved)} questions to compare")
                for i in range(len(questions)):
                    question = questions[i]
                    answer = answers[i]
                    to_add = True  # Flag to indicate if the current question is unique

                    # Encode the current question into embeddings
                    embeddings = embedder.encode(question, show_progress_bar=False)

                    # Check the similarity of the current question with previously saved questions
                    for saved_embeddings in saved:
                        cos_sim = cosine_similarity(embeddings, saved_embeddings)
                        if cos_sim > threshold:  # If too similar, mark for exclusion
                            to_add = False
                            # print("---> Duplicate !", cos_sim)
                            break  # No need to check further if similarity is already too high

                    # Add the question and its answer if it is unique
                    if to_add:
                        saved.append(embeddings)  # Save the embeddings of the unique question
                        saved_questions.append(question)  # Save the question
                        saved_answers.append(answer)  # Save the corresponding answer

                    added.append(to_add)
                print("### Questions stored:", sum(added))
                # print(f"Added {sum(added)} questions to the question list ! --> {len(saved)} questions saved\n")
                if not any(added):
                    repeat += 1

            # Increment the safety counter for every loop iteration
            safety += 1

        # Return the collected unique questions and their corresponding answers
        return saved_questions


    def generate_questions_and_answers(self, model, text, llm="gpt4all", max_tokens=4096, temperature=1, top_p=1, top_k=50, stop_tokens=None):
        """
        Generates question-answer pairs based on a provided text using a language model (LLM).

        Parameters:
            model (Llama): The language model instance with a callable API for generating text.
            text (str): The input document or excerpt to generate questions and answers from.
            llm (str): The type of backend to use, "gpt4all" or "lmstudio".
            max_tokens (int): Maximum tokens for the model's output (default is 4096).
            temperature (float): Sampling temperature to control randomness (default is 1).
            top_p (float): Top-p sampling to limit the token pool by probability (default is 1).
            top_k (int): Top-k sampling to limit the token pool by rank (default is 50).
            stop_tokens (list): List of stop sequences to terminate generation (default is None).

        Returns:
            str: The generated question-answer pairs.
        """
        # Define the prompt
        prompt = f"""### Contexte : Tu es un examinateur. Ton objectif est de préparer des questions pour un examen. Les candidats vont être interrogés sur un document, dont ils ont dû apprendre le contenu. Ils n'ont aucun accès au document durant l'examen.


### Instructions :
- Génère des questions simples et précises qui reflètent les informations principales du document. 
- Les candidats n'auront pas accès au document pour répondre aux questions.
- Tu ne dois JAMAIS faire d'allusion au document
- Tu ne dois JAMAIS utiliser la formule "D'après ce document".
- Tu ne dois JAMAIS utiliser la formule "Comme mentionne ce document".
- Tu ne dois JAMAIS utiliser la formule "Selon ce document".
- Respecte la stucture suivante :
1)
2)
3)
etc...


### Document :



"{text}"




### Assistant :"""
        # if llm == "gpt4all":
        #     try:
        #         # Generate output using the LLM
        #         localhost = "localhost:4891"
        #         response = GPT4ALL.call_completion_api(localhost=localhost, message_content=prompt, model_name=model,
        #                                                temperature=1, top_p=1)
        #         answer = GPT4ALL.clean_response(response)
        #
        #
        #         # Extract and return the text portion of the response
        #         return answer.strip()
        #     except Exception as e:
        #         return f"Error generating questions and answers: {e}"

        if llm == "lmstudio":
            try:
                # Generate output using the LLM
                response = lmstudio.appel_lmstudio(prompt, model)
                return response
            except Exception as e:
                return f"Error generating questions and answers: {e}"


    def parse_questions_and_answers(self, qa_text):
        """
        Parses a string containing questions and answers into a structured list of dictionaries.

        Parameters:
            qa_text (str): The input string containing questions and answers in the format:
                           Q: "Question..."
                           R: "Answer..."

        Returns:
            list: A list of dictionaries, each containing a 'question' and 'answer' key.
        """
        # Regular expressions to match questions and answers
        question_pattern = r"\d+[.)]\s?(.*?)(?:\n|$)"

        # Extract questions and answers using regex
        questions = re.findall(question_pattern, qa_text)

        # Ensure equal number of questions and answers
        return questions

def cosine_similarity(u, v):
    dot_product = np.dot(u, v)
    norm_u = np.linalg.norm(u)
    norm_v = np.linalg.norm(v)
    return dot_product / (norm_u * norm_v)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWGenerateQuestions()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
