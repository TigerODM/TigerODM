import os
import re
import sys
import json
import shutil

import Orange.data
from Orange.widgets import widget
from Orange.data import StringVariable
from AnyQt.QtWidgets import QApplication
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import PageIndex_functions
    from Orange.widgets.orangecontrib.AAIT.llm import prompt_management
    from Orange.widgets.orangecontrib.AAIT.llm.answers_llama import load_model, load_model_with_handler, run_query, split_think
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.llm import PageIndex_functions
    from orangecontrib.AAIT.llm import prompt_management
    from orangecontrib.AAIT.llm.answers_llama import load_model, load_model_with_handler, run_query, split_think
    from orangecontrib.AAIT.utils import thread_management, help_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file

nb_image_to_find_start = 15
image_batch_size = 10


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWPageIndexCreate(widget.OWWidget):
    name = "PageIndex - Create"
    description = "Process all pdf, pptx and docx files at a given location to create a PageIndex for each of them and a DatabaseIndex to store the results."
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/owpageindex_create.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owpageindex_create.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owpageindex_create.ui")
    want_control_area = False
    priority = 1060

    # Settings
    selected_column_name = Setting("path")

    class Inputs:
        data = Input("Data", Orange.data.Table)
        VLM = Input("VLM", str, auto_summary=False)
        LLM = Input("LLM", str, auto_summary=False)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.autorun:
            self.run()

    @Inputs.VLM
    def set_VLM(self, in_VLM_path):
        self.VLM_path = in_VLM_path
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
        self.setFixedWidth(470)
        self.setFixedHeight(395)
        uic.loadUi(self.gui, self)

        # Data Management
        self.data = None
        self.VLM_path = None
        self.LLM_path = None
        self.thread = None
        self.autorun = True
        self.result = None
        self.use_gpu = True
        self.count = 0
        self.nb_entry = 1
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

        if self.VLM_path is None:
            self.Outputs.data.send(None)
            return

        if self.LLM_path is None:
            self.Outputs.data.send(None)
            return

        if not os.path.exists(self.VLM_path):
            self.error(f'Your VLM path does not exist: {self.VLM_path}')
            self.Outputs.data.send(None)
            return

        if not os.path.exists(self.LLM_path):
            self.error(f'Your LLM path does not exist: {self.LLM_path}.')
            self.Outputs.data.send(None)
            return

        # Verification of selected column
        if not self.selected_column_name in self.data.domain:
            self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
            self.Outputs.data.send(None)
            return

        if not isinstance(self.data.domain[self.selected_column_name], StringVariable):
            self.error('You must select a text variable.')
            self.Outputs.data.send(None)
            return

        path = self.data[0][self.selected_column_name].value
        if not os.path.isdir(path):
            self.error(f"Selected path is not a directory: {path}.")
            self.Outputs.data.send(None)
            return

        supported_ext = (".pdf", ".pptx", ".docx")
        nb_folders = sum(1 for _, dirs, _ in os.walk(path) for _ in dirs)
        nb_files = sum(1 for _, _, files in os.walk(path) for f in files if f.lower().endswith(supported_ext))
        self.nb_entry = nb_files + nb_folders

        # Start progress bar
        self.progressBarInit()

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        self.thread = thread_management.Thread(self.create_database_index, path, self.VLM_path, self.LLM_path)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.result = result
            # Todo : analyse the database and return a report !
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        self.progressBarFinished()
        self.count = 0

    def post_initialized(self):
        pass

    def create_database_index(self, dirpath, VLM_path, LLM_path, progress_callback=None, argself=None):
        """
        Recursively builds a PageIndex for a directory and all its contents.

        For each entry in dirpath:
          - Files  → create_page_index() directly
          - Folders → recurse, then create_page_index() from the children's indexes

        Finally, creates a PageIndex for dirpath itself, based on all children indexes.
        """
        children_indexes = []
        # Sort entries so files and folders are processed in a deterministic order
        entries = sorted(os.scandir(dirpath), key=lambda e: (e.is_file(), e.name))
        for entry in entries:
            if entry.is_dir():
                # Recurse first — we need the folder's index before we can use it
                folder_index = self.create_database_index(entry.path, VLM_path, LLM_path, progress_callback, argself)
                if folder_index is not None:
                    children_indexes.append(folder_index)

            elif entry.is_file():
                page_index = self.create_page_index(entry.path, VLM_path, LLM_path, progress_callback, argself)
                if page_index is not None:
                    children_indexes.append(page_index)

            if progress_callback is not None:
                progress_callback(float(100*self.count/self.nb_entry))

        if not children_indexes:
            return None

        # Create the Database Index inside this directory
        database_path = os.path.join(dirpath, "database_index.json")
        with open(database_path, "w", encoding="utf-8") as f:
            json.dump(children_indexes, f, ensure_ascii=False, indent=2)

        # Create the directory's PageIndex
        error = ""
        try:
            directory_summary = self.summarize_folder(children_indexes, LLM_path)
        except Exception as e:
            directory_summary = "An error occurred !"
            error = e
        self.count += 1
        directory_index = {
                "unique_id": self.count,
                "path": dirpath.replace("\\", "/"),
                "type": "folder",
                "name": os.path.basename(dirpath),
                "summary": directory_summary,
                "page_index": error
            }
        return directory_index


    def create_page_index(self, filepath, VLM_path, LLM_path, progress_callback=None, argself=None):
        # Supported extensions
        supported_ext = (".pdf", ".pptx", ".docx")

        # Control on file extension
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filepath)[1].lower()
        if not ext in supported_ext:
            return None

        self.count += 1

        # Optional : output_dir to save the results of each step - Set to None not to save results
        output_dir = re.sub(r"\.[^.]+$", "_images_PI", filepath)

        # Create PageIndex on the file
        self.label_1.setText(f"{self.nb_entry} files & folders detected - Processing {self.count} / {self.nb_entry}")
        self.label_2.setText(f"Currently processing {filename}...")
        try:
            # Step 1 - Extract PDF pages & convert them to images
            image_paths, text_per_page = PageIndex_functions.extract_pages(path=filepath, output_dir=output_dir)

            # Step 2 - Find the start of the document with VLM
            self.label_3.setText("Step 1/6 - Searching for the start of the document")
            VLM = load_model_with_handler(VLM_path, verbose=True, use_gpu=self.use_gpu)
            start = PageIndex_functions.find_start_of_document(image_paths=image_paths, model=VLM, N=nb_image_to_find_start)

            # Step 3 - Go through pages to extract the structure of the document
            self.label_3.setText("Step 2/6 - Generating a global structure")
            global_structure = PageIndex_functions.find_document_structure(image_paths=image_paths,
                                                                           start=start,
                                                                           model=VLM,
                                                                           batch_size=image_batch_size,
                                                                           output_dir=output_dir,
                                                                           label=self.label_3)
            VLM.close()

            # Step 4 - Clear the TOC from duplicates and artifacts with LLM
            self.label_3.setText("Step 3/6 - Analysing and cleaning the table of contents")
            LLM = load_model(LLM_path, n_ctx=32768, use_gpu=self.use_gpu)
            clean_toc = PageIndex_functions.clear_toc(global_structure=global_structure, model=LLM,
                                                      output_dir=output_dir)

            # Step 5 - Transform the text TOC into a JSON formatted TOC
            self.label_3.setText("Step 4/6 - Transforming the table of content into a JSON structure")
            json_toc = PageIndex_functions.toc_to_json(clean_toc=clean_toc, model=LLM, output_dir=output_dir)

            # Step 6 - Generate PageIndex (adjust JSON structure)
            self.label_3.setText("Step 5/6 - Finalising the page index with page intervals")
            page_index = PageIndex_functions.generate_PageIndex(json_toc=json_toc, text_per_page=text_per_page,
                                                                output_dir=output_dir)

            # Step 7 - Generate a brief summary about the document, thanks to 1st page and table of content
            self.label_3.setText("Step 6/6 - Generating a short summary to identify the document amongst others")
            LLM.close()
            VLM = load_model_with_handler(VLM_path, verbose=False, use_gpu=self.use_gpu)
            summary = PageIndex_functions.generate_summary_VLM(toc=clean_toc,
                                                               name=filename,
                                                               image_path=[image_paths[0]],
                                                               model=VLM,
                                                               output_dir=output_dir)

            VLM.close()
        except Exception as e:
            summary = "An error occurred !"
            page_index = e

        file_data = {
            "unique_id": self.count,
            "path": filepath.replace("\\", "/"),
            "type": "file",
            "name": filename,
            "summary": summary,
            "page_index": f"{page_index}"
        }
        if output_dir:
            shutil.rmtree(output_dir, ignore_errors=True)
        return file_data


    def summarize_folder(self, database_index, LLM_path, progress_callback=None, argself=None):
        prompt = """# Contexte
Voici un ensemble de documents prevenant d'un dossier, avec des résumés de leur contenu.
Génère un résumé décrivant le **sujet** et ce que l'on peut trouver dans ce dossier. 
L'objectif est que, en lisant ce résumé, on puisse rapidement savoir si ce dossier contient les informations recherchées.

# Instructions :
- Résume le sujet et le contenu.
- N'utilise pas plus de 5 phrases, avec des mot-clés pertinents.
- N'ajoute pas d'opinion, commentaire ou phrase explicative.

# Documents
"""
        for entry in database_index:
            prompt += f"## Nom\n{entry['name']}\n"
            prompt += f"## Résumé\n{entry['summary']}\n"

        LLM = load_model(LLM_path, n_ctx=32768, use_gpu=self.use_gpu)
        prompt = prompt_management.apply_prompt_template("qwen", user_prompt=prompt)
        answer = run_query(prompt, LLM)
        summary = split_think(answer)[1]
        if LLM is not None:
            LLM.close()
        return summary



if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWPageIndexCreate()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
