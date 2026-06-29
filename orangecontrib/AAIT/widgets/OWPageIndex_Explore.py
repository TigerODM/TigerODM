import os
import sys
import json
import copy

import Orange.data
from Orange.data import Table, Domain, StringVariable
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import PageIndex_functions, prompt_management
    from Orange.widgets.orangecontrib.AAIT.llm.answers_llama import load_model, run_query, count_tokens, split_think, conversation_to_text
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.llm import PageIndex_functions, prompt_management
    from orangecontrib.AAIT.llm.answers_llama import load_model, run_query, count_tokens, split_think, conversation_to_text
    from orangecontrib.AAIT.utils import thread_management, help_management
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWPageIndexExplore(widget.OWWidget):
    name = "PageIndex - Explore"
    description = "Look through your processed database with PageIndexes to answer a request"
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/owpageindex_explore.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owpageindex_explore.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owpageindex_explore.ui")
    want_control_area = False
    priority = 1060


    class Inputs:
        data = Input("Request Table", Orange.data.Table)
        path_table = Input("Path Table", Orange.data.Table)
        LLM = Input("LLM", str, auto_summary=False)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.autorun:
            self.run()

    @Inputs.path_table
    def set_path_table(self, in_path_table):
        self.path_table = in_path_table
        if self.autorun:
            self.run()

    @Inputs.LLM
    def set_LLM(self, in_LLM_path):
        self.LLM_path = in_LLM_path
        if self.autorun:
            self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(598)
        self.setFixedHeight(471)
        uic.loadUi(self.gui, self)

        # Data Management
        self.data = None
        self.path_table = None
        self.LLM_path = None

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

        if self.path_table is None:
            self.Outputs.data.send(None)
            return

        if self.LLM_path is None:
            self.Outputs.data.send(None)
            return

        if not os.path.exists(self.LLM_path):
            self.error(f'Your LLM path does not exist: {self.LLM_path}.')
            self.Outputs.data.send(None)
            return

        if not "path" in self.path_table.domain:
            self.warning(f'"path" variable required in your Path Table.')
            self.Outputs.data.send(None)
            return

        if not "request" in self.data.domain:
            self.warning(f'"request" variable required in your Request Table.')
            self.Outputs.data.send(None)
            return

        if "Answer" in self.data.domain:
            self.error(f'You must not have an "Answer" variable in your Data Table.')
            self.Outputs.data.send(None)
            return

        if "Conversation" in self.data.domain:
            self.error(f'You must not have an "Conversation" variable in your Data Table.')
            self.Outputs.data.send(None)
            return


        path = self.path_table[0]["path"].value
        if not os.path.isdir(path):
            self.error(f"Selected path is not a directory: {path}.")
            self.Outputs.data.send(None)
            return

        database_index_path = os.path.join(path, "database_index.json")
        if not os.path.exists(database_index_path):
            self.error(f"The Database Index does not exist: {database_index_path} not found.")
            self.Outputs.data.send(None)
            return

        with open(database_index_path, "r", encoding="utf-8") as f:
            database_index = json.load(f)

        # Start progress bar
        self.progressBarInit()

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        self.thread = thread_management.Thread(self.explore_page_index_for_table, self.data, path, database_index, self.LLM_path)
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
        self.progressBarFinished()

    def post_initialized(self):
        pass



    def explore_page_index_for_table(self, table, dirpath, database_index, LLM_path, progress_callback=None, argself=None):
        # Copie des données d'entrée
        data = copy.deepcopy(table)

        # Chargement modèle (llama_cpp)
        n_ctx = 32768
        LLM = load_model(model_path=LLM_path, use_gpu=True, n_ctx=n_ctx)

        # Génération sur la colonne "prompt"
        answers = []
        conversations = []
        print(data)
        for i, row in enumerate(data):
            request = row["request"].value
            # try:
            answer, conversation = self.explore_page_index(question=request, dirpath=dirpath, database_index=database_index, LLM=LLM)
            # except Exception as e:
            #     answer = f"An error happened: {e}"
            #     conversation = "Errors happened"
            #     self.error(f"An error happened: {e}")
            #     print(e)
            answers.append(answer)
            conversations.append(conversation)


            if progress_callback is not None:
                progress_value = float(100 * (i + 1) / len(data))
                progress_callback(progress_value)
            if argself is not None:
                if argself.stop:
                    break

        # Add "Answer" column to the input data
        answer_var = StringVariable("Answer")
        conv_var = StringVariable("Conversation")
        # Add the scores as a meta attribute to the table
        data = data.add_column(answer_var, answers, to_metas=True)
        data = data.add_column(conv_var, conversations, to_metas=True)
        return data



    def explore_page_index(self, question, dirpath, database_index, LLM, progress_callback=None, argself=None):
        # Parameters
        margin = 5000
        max_iter = 15

        # Default values
        final_answer = "Reached maximum number of iterations"
        filepath = ""

        # Keep only ID, names and summaries to show the root to the LLM
        documents_summaries = show_summaries(database_index=database_index)
        current_index = database_index

        # Build prompt and conversation
        user_prompt = prompts["user_prompt"].format(DATABASE_INDEX=documents_summaries, QUERY=question)
        conversation = [
            {"role": "system", "content": prompts["search_argent_system_2"]},
            {"role": "user", "content": [{"type": "text", "text": user_prompt}]}
        ]

        # Start the search loop
        ephemeral_messages = []
        for step in range(max_iter):
            # Apply Qwen template to the entire conversation
            prompt = prompt_management.apply_template_to_conversation_2("qwen", conversation)
            #print("\n\n\n\nPROMPT:\n\n", prompt)
            # Verify length
            # Todo : do something if it's too long ?
            prompt_length = count_tokens(LLM, prompt)
            self.label_1.setText(f"Step {step} - {str(prompt_length)} tokens currently in memory.")
            # Generate an answer
            answer = run_query(prompt=prompt, model=LLM, max_tokens=0, progress_callback=progress_callback, argself=argself)
            # Remove the Thinking
            answer = split_think(answer)[1]
            # Add the entry to the conversation
            import re
            if "```tool" in answer:
                answer = re.findall(r"(```tool[\s\S]*?```)", answer)[0]
            conversation.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})

            # Detect if a tool has been called
            tool, args = PageIndex_functions.identify_tool_call_2(answer)
            if tool is not None:
                # Do animation for a tool !
                #TODO

                # Clear ephemeral messages to free some token memory
                PageIndex_functions.clear_ephemeral_messages(ephemeral_messages, conversation, tools=["view_documents", "get_pages"])


            if tool == "view_documents":
                self.label_2.setText("Analyse des documents disponibles...")
                tool_prompt = tool_prompts["view_documents"].format(tool=tool, documents_summaries=documents_summaries)

                conversation.append({"role": "user", "content": [{"type": "text", "text": tool_prompt}]})
                ephemeral_message = {
                    "idx": len(conversation) - 1,
                    "tool": tool,
                    "replacement": f"# Appel outil\n{tool}\n\n# Résultat outil\n[Hidden for memory reason]"
                }
                ephemeral_messages.append(ephemeral_message)


            elif tool == "select_document":
                # Clear previously selected document in case another document has been selected
                PageIndex_functions.clear_ephemeral_messages(ephemeral_messages, conversation, tools=["select_document"])

                doc_name = args[0]
                doc_infos = PageIndex_functions.select_document(doc_name, database_index)
                self.label_2.setText(f"Sélection du document {doc_name}")
                if doc_infos == {}:
                    conversation.append({"role": "user", "content": [{"type": "text", "text": f"# Appel outil\n{tool}\n\nNom du document incorrect"}]})
                    continue

                path = doc_infos["path"]
                name = doc_infos["name"]
                page_index = doc_infos["page_index"]
                tool_prompt = f"""# Appel outil
{tool}

# Résultat outil
## Document sélectionné
{name}
## Index
{page_index}"""

                conversation.append({"role": "user", "content": [{"type": "text", "text": tool_prompt}]})
                ephemeral_message = {
                    "idx": len(conversation) - 1,
                    "tool": tool,
                    "replacement": f"# Appel outil\n{tool}\n\n# Résultat outil\n[Hidden for memory reason]"
                }
                ephemeral_messages.append(ephemeral_message)


            elif tool == "select":
                # Clear previously selected object in case another object has been selected
                PageIndex_functions.clear_ephemeral_messages(ephemeral_messages, conversation, tools=["select"])

                obj_id = args[0]
                obj_infos = PageIndex_functions.select(obj_id, current_index, dirpath)

                if obj_infos == {}:
                    conversation.append({"role": "user", "content": [{"type": "text", "text": f"# Appel outil\n{tool}\n\nNom incorrect"}]})
                    continue

                path = obj_infos["path"]
                name = obj_infos["name"]
                if os.path.isdir(path):
                    self.label_2.setText(f"Sélection du dossier : {name}")
                    current_index = search_for_index(path)
                    if current_index is None:
                        conversation.append({"role": "user", "content": [{"type": "text", "text": f"# Appel outil\n{tool}\n\nERROR: this folder cannot be explored."}]})
                    else:
                        documents_summaries = show_summaries(current_index)
                        tool_prompt = tool_prompts["select_dir"].format(tool=tool, args=f"{obj_id}", documents_summaries=documents_summaries)
                        conversation.append({"role": "user", "content": [{"type": "text", "text": tool_prompt}]})
                        ephemeral_message = {
                            "idx": len(conversation) - 1,
                            "tool": tool,
                            "replacement": f"# Appel outil\n{tool}({obj_id})\n\n# Résultat outil\n[Hidden for memory reason]"
                        }
                        ephemeral_messages.append(ephemeral_message)

                elif os.path.isfile(path):
                    self.label_2.setText(f"Sélection du fichier : {name}")
                    filepath = path
                    page_index = obj_infos["page_index"]
                    tool_prompt = tool_prompts["select_file"].format(tool=tool, args=f"{obj_id}", name=name, page_index=page_index)
                    conversation.append({"role": "user", "content": [{"type": "text", "text": tool_prompt}]})
                    ephemeral_message = {
                        "idx": len(conversation) - 1,
                        "tool": tool,
                        "replacement": f"# Appel outil\n{tool}({obj_id})\n\n# Résultat outil\n[Hidden for memory reason]"
                    }
                    ephemeral_messages.append(ephemeral_message)


            elif tool == "read_file":
                if not filepath:
                    conversation.append({"role": "user", "content": [{"type": "text", "text": "Aucun document sélectionné."}]})
                    continue
                start_page = args[0]
                end_page = args[1]
                self.label_2.setText(f"Lecture des pages {start_page} - {end_page}")
                pages_text = PageIndex_functions.get_pages(path=filepath, start=start_page, end=end_page, limit=15)
                tool_prompt = tool_prompts["get_pages"].format(tool=tool, args=f"{start_page}, {end_page}", pages_text=pages_text)

                conversation.append({"role": "user", "content": [{"type": "text", "text": tool_prompt}]})
                ephemeral_message = {
                    "idx": len(conversation) - 1,
                    "tool": tool,
                    "replacement": f"# Appel outil\n{tool}({start_page}, {end_page})\n\n# Résultat outil\n[Hidden for memory reason]"
                }
                ephemeral_messages.append(ephemeral_message)


            elif tool == "Unknown tool":
                tool_prompt = "The tool you tried to call has not been recognized."
                conversation.append({"role": "user", "content": [{"type": "text", "text": tool_prompt}]})

            else:
                if "<answer>" in answer:
                    final_answer = answer.split("<answer>")[1].split("</answer>")[0].strip()
                    break
                if "[FINISHED]" in answer:
                    final_answer = answer.split("[FINISHED]")[0].strip()
                    break

                else:
                    # Log or append LLM text as fallback
                    conversation.append({"role": "user", "content": [{"type": "text", "text": "`LLM output not recognized as tool or final answer, so continue. For final answer, terminate with [FINISHED]`."}]})
                    continue

            print(conversation[-1])

        return final_answer, conversation_to_text(conversation)




def show_summaries(database_index):
    documents_summaries = []
    for entry in database_index:
        documents_summaries.append({"unique_id": entry["unique_id"], "type": entry["type"], "name": entry["name"], "summary": entry["summary"]})
    # Turn it into a string for the LLM
    documents_summaries = f"{documents_summaries}"
    return documents_summaries

def search_for_index(path):
    index_name = "database_index.json"
    index_path = os.path.join(path, index_name)
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            database_index = json.load(f)
        return database_index
    else:
        return None


prompts = {
    # {PAGE_INDEX}
    # {QUESTION}
    "search_agent": """# Contexte
Tu es un assistant avec accès à deux outils :
1. Un outil pour sélectionner un document
2. Un outil pour parcourir les pages d'un document sélectionné

Tu disposes d’un ensemble de documents, chacun décrit par un résumé.


# Règles
- Tu n'as PAS le droit d'inventer ou de deviner.
- Tu n'as PAS le droit de conclure que la réponse n'existe pas **sans** avoir lu de pages pertinentes avec l’outil.
- Tu peux utiliser les outils autant que tu veux jusqu'à avoir suffisamment d'informations.

---

# Comportement attendu
## Étape 1 — Sélection du document
- Si la question concerne les documents → tu DOIS d'abord sélectionner un document
- Choisis le document le plus pertinent en te basant sur les résumés fournis
- Tu ne peux pas appeler `get_pages` sans avoir sélectionné un document

## Étape 2 — Lecture des pages
- Une fois le document sélectionné → tu peux appeler `get_pages`

---

# Utilisation d'un outil
## Outil 1 - Sélection d'un document
Réponds avec

```tool
select_document(<doc_name>)
```

puis attend le résultat avant de continuer tout réflexion ou rédaction de réponse. 
Tu vas recevoir un plan du document, te permettant de cibler les pages qui t'intéressent.


## Outil 2 - Lecture de pages
Réponds avec

```tool
get_pages(<page_debut>, <page_fin>)
```

puis attend le résultat avant de continuer toute réflexion ou rédaction de réponse.

---

# Arrêt
Lorsque tu as suffisamment d'informations pour répondre :
- Tu dois répondre directement à la question
- Tu ne dois PAS appeler l'outil
- Ta réponse doit être complète et précise

Format de réponse final :
```final
<ta réponse ici>
```

---

# Documents disponibles
{DOCUMENTS_SUMMARIES}


# Question
{QUESTION}""",


    "search_agent_3_tools": """# Contexte
Tu es un assistant avec accès à trois outils :
1. Un outil pour ouvrir voir l'ensemble des documents disponibles
2. Un outil pour sélectionner un document
3. Un outil pour parcourir les pages d'un document sélectionné


# Règles
- Tu n'as PAS le droit d'inventer ou de deviner.
- Tu peux utiliser les outils autant que tu veux jusqu'à avoir suffisamment d'informations.

---


# Comportement attendu
## Étape 1 - Visualisation des documents disponibles

## Étape 2 — Sélection d'un document
- Si la question concerne les documents → tu DOIS d'abord sélectionner un document
- Choisis le document le plus pertinent en te basant sur les résumés fournis
- Tu ne peux pas appeler `get_pages` sans avoir sélectionné un document

## Étape 3 — Lecture des pages
- Une fois le document sélectionné → tu peux appeler `get_pages`

---

# Utilisation d'un outil
Lorsque tu utilises un outil, respecte les 2 consignes suivantes :
- attend le résultat avant de continuer toute réflexion ou rédaction de réponse
- après avoir reçu le résultat, récapitule toute information pertinente que tu aurais reçue. S'il n'y en a pas, indique brièvement que ça ne t'a pas aidé.


## Outil 1 - Visualisation des documents disponibles
```tool
view_documents()
```

Tu vas recevoir un ensemble de documents avec leurs résumés.


## Outil 2 - Sélection d'un document
```tool
select_document(<doc_name>)
```

Tu vas recevoir un plan du document, te permettant de cibler les pages qui t'intéressent.


## Outil 3 - Lecture de pages
```tool
get_pages(<page_debut>, <page_fin>)
```

Tu vas recevoir le contenu des pages demandées.


---


# Arrêt
Lorsque tu as suffisamment d'informations pour répondre :
- Tu dois répondre directement à la question
- Tu ne dois PAS appeler d'outil
- Ta réponse doit être complète et précise

Format de réponse final :
```final
<ta réponse ici>
```

---


# Question
{QUESTION}""",


    "search_agent_with_subfolders": """# Contexte
Tu es un assistant cherchant à répondre à une requête. Tu disposes d'un ensemble de documents (dossiers et fichiers) à explorer et tu as accès à deux outils :
1. Un outil pour sélectionner un dossier ou un fichier
2. Un outil pour parcourir les pages d'un fichier sélectionné


---


# Règles
- Tu n'as PAS le droit d'inventer le résultat d'un outil : attend qu'il soit exécuté par `user` pour toi.
- Tu peux utiliser les outils autant que tu veux jusqu'à avoir suffisamment d'informations.
- N'hésite pas à parcourir plusieurs documents s'ils te paraissent pertinents.


---


# Comportement attendu
## Étape 1 - Analyse de la requête
- Si la requête concerne les documents → tu DOIS explorer la base de données
- Sinon, tu peux répondre directement à la requête

## Étape 2 (répétable)
### Étape 2.a — Sélection de document
- Sélectionne un dossier ou fichier pertinent en te basant sur les résumés fournis

### Étape 2.b — Lecture de pages
- Une fois qu'un fichier est sélectionné → tu peux appeler `get_pages`


---


# Utilisation d'un outil
Lorsque tu utilises un outil, respecte les 2 consignes suivantes :
- attend le résultat avant de continuer toute réflexion ou rédaction de réponse
- après avoir reçu le résultat, récapitule toute information pertinente que tu aurais reçue. S'il n'y en a pas, indique brièvement que ça ne t'a pas aidé.


## Outil 1 - Sélection d'un dossier ou d'un fichier
```tool
select(<unique_id>)
```

Tu vas recevoir le contenu du dossier ou fichier demandé, pour poursuivre ton exploration.


## Outil 2 - Lecture de pages
```tool
get_pages(<page_debut>, <page_fin>)
```

Tu vas recevoir le contenu des pages demandées.


---


# Arrêt
Lorsque tu as suffisamment d'informations pour répondre :
- Tu dois répondre directement à la question
- Tu ne dois PAS appeler d'outil
- Ta réponse doit être complète et précise

Format de réponse final :
```final
<ta réponse ici>
```


---


# Base de documents (root)
{SUMMARIES}


---


# Requête
{QUESTION}""",


    "search_argent_system": """You are a helpful assistant. 
Your goal is to answer a query. You can explore the provided documents using tools.

# Tools
You have access to the following functions:

<tools>
{"function": {"description": "Select a file or folder by its unique_id to focus the search.", "name": "select", "parameters": {"properties": {"unique_id": {"description": "The ID from the database", "type": "integer"}}, "required": ["unique_id"], "type": "object"}}, "type": "function"}
{"function": {"description": "Read specific pages from the currently selected file. You must have selected a file with "select" to use this function.", "name": "read_file", "parameters": {"properties": {"page_end": {"type": "integer"}, "page_start": {"type": "integer"}}, "required": ["page_start", "page_end"], "type": "object"}}, "type": "function"}
</tools>

If you choose to call a function, use the following format:

<tool_call>
<function=example_function_name>
<parameter=example_parameter_1>
value_1
</parameter>
<parameter=example_parameter_2>
value_2
</parameter>
</function>
</tool_call>


# RULES:
- DECISION-FIRST: Before calling a tool, clearly state:
  1. Which files, folders or pages are most promising
  2. Why they are relevant to the query

- MEMORY STRATEGY:
  Maintain an internal shortlist of the most relevant items (files, folders, pages, e.g. top 1–3 candidates).
  Update this shortlist after each observation.

- EXPLORATION STRATEGY:
  Always start with the most promising file or folder first.
  Only move to another item if the current one is insufficient.

- PAGE SELECTION:
  When exploring files, choose page ranges based on expected structure (e.g., definitions early, procedures later).
  Do NOT enumerate multiple hypothetical parameter sets.

- STEP-BY-STEP:
  1. Select a file or folder
  2. If a folder is selected, narrow down to relevant files inside it
  3. Select a relevant file
  4. Read targeted pages from files when applicable
  5. Note any important findings, useful context, or promising leads that may help later
  6. Update relevance ranking of files/folders
  7. Iterate if needed

- COMPLETION:
  When enough evidence is gathered, end your answer with a "[FINISHED]" tag.

- LANGUAGE:
  Match the user’s language.""",


    "search_argent_system_2": """You are a helpful assistant. 
Your goal is to answer a query. You can explore the provided documents using tools.

# Tools
You have access to the following functions:

<tools>
{"function": {"description": "Select a file or folder by its unique_id to focus the search.", "name": "select", "parameters": {"properties": {"unique_id": {"description": "The ID from the database", "type": "integer"}}, "required": ["unique_id"], "type": "object"}}, "type": "function"}
{"function": {"description": "Read specific pages from the currently selected file. You must have selected a file with "select" to use this function.", "name": "read_file", "parameters": {"properties": {"page_end": {"type": "integer"}, "page_start": {"type": "integer"}}, "required": ["page_start", "page_end"], "type": "object"}}, "type": "function"}
</tools>

If you choose to call a function, use the following format:

<tool_call>
<function=example_function_name>
<parameter=example_parameter_1>
value_1
</parameter>
<parameter=example_parameter_2>
value_2
</parameter>
</function>
</tool_call>


# RULES:
- DECISION-FIRST: Before calling a tool, clearly state:
  1. Which files, folders or pages are most promising
  2. Why they are relevant to the query

- EXPLORATION STRATEGY:
  Always start with the most promising file or folder first.
  Only move to another item if the current one is insufficient.

- PAGE SELECTION:
  When exploring files, choose page ranges based on expected structure (e.g., definitions early, procedures later).
  Do NOT enumerate multiple hypothetical parameter sets.

- STEP-BY-STEP:
  1. Select a file or folder
  2. If a folder is selected, narrow down to relevant files inside it
  3. Select a relevant file
  4. Read targeted pages from files when applicable
  5. Note any important findings, useful context, or promising leads that may help later
  6. Update relevance ranking of files/folders
  7. Iterate if needed

- COMPLETION:
  When enough evidence is gathered, end your answer with a "[FINISHED]" tag.

- LANGUAGE:
  Match the user’s language.""",

    "user_prompt": """# Database (root)
{DATABASE_INDEX}


# Query
{QUERY}"""
}


tool_prompts = {
    "view_doc":"""# Appel outil
{tool}

# Résultat outil
{documents_summaries}""",


    "select_dir": """# Appel outil
{tool}({args})

# Résultat outil
## Contenu du dossier
{documents_summaries}


# Reminder
Before continuing your search, list any interesting files or folders along with their IDs.""",


    "select_file":"""# Appel outil
{tool}({args})

# Résultat outil
## Document sélectionné
{name}
## Index
{page_index}""",


    "get_pages":"""# Appel outil
{tool}({args})

# Résultat outil
{pages_text}


# Reminder
If you need to continue searching, note any elements that contribute to answering the question.""",
}



if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWPageIndexExplore()

    my_widget.show()
    # if hasattr(app, "exec"):
    #     app.exec()
    # else:
    #     app.exec_()


    table = Table.from_list(Domain([], metas=[StringVariable("request")]), rows=[["Comment changer l'huile de turbine du FAMA K209 ?"]])
    LLM_path = r"C:\Users\lucas\AppData\Local\Programs\aait_store\Models\NLP\Qwen3.5-9B-GGUF\Qwen3.5-9B-Q6_K.gguf"
    database_path = r"C:\Users\lucas\Documents\Projets\IFIA\RAG\Dataset\Test_PageIndex"
    my_widget.data = table
    my_widget.LLM_path = LLM_path
    my_widget.path_table = Table.from_list(Domain([], metas=[StringVariable("path")]), rows=[[database_path]])

    my_widget.run()
