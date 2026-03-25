import os
from AnyQt.QtWidgets import QApplication, QLineEdit
import Orange.data
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWExtraChunks(widget.OWWidget):
    name = "Extra Chunks"
    description = "Extract surrounding chunks from a dataset"
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/extra_chunks.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/extra_chunks.png"
    want_control_area = False
    priority = 1001
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owextrachunks.ui")

    class Inputs:
        complete_data = Input("Complete Dataset", Orange.data.Table)
        selected_data = Input("Chunks", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)
        concatenate_data = Output("Concatenate Data", Orange.data.Table)

    extra_chunks: int = Setting(2)

    @Inputs.complete_data
    def set_complete_data(self, data):
        self.complete_data = data
        if self.autorun:
            self.process()

    @Inputs.selected_data
    def set_selected_data(self, data):
        self.selected_data = data
        if self.autorun:
            self.process()

    def __init__(self):
        super().__init__()
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        self.complete_data = None
        self.selected_data = None
        self.autorun = True

        self.edit_extrachunks = self.findChild(QLineEdit, 'QExtraChunks')
        self.edit_extrachunks.setText(str(self.extra_chunks))
        self.edit_extrachunks.textChanged.connect(self.update_extrachunks)
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def update_extrachunks(self, text):
        self.extra_chunks = int(text) if text.isdigit() else 2

    def process(self):
        self.error("")
        self.warning("")

        if self.complete_data is None or self.selected_data is None:
            self.Outputs.concatenate_data.send(None)
            self.Outputs.data.send(None)
            return

        domain = self.complete_data.domain
        if "path" not in domain:
            self.error('You need a "path" column in your input tables.')
            self.Outputs.concatenate_data.send(None)
            self.Outputs.data.send(None)
            return

        if "Chunks index" not in domain:
            self.error('You need a "Chunks index" column in your input tables.')
            self.Outputs.concatenate_data.send(None)
            self.Outputs.data.send(None)
            return

        if "Chunks" not in domain:
            self.error('You need a "Chunks" column in your input tables.')
            self.Outputs.concatenate_data.send(None)
            self.Outputs.data.send(None)
            return

        index_var = domain["Chunks index"]
        path_var = domain["path"]
        chunks_var = domain["Chunks"]

        selected_indices_by_path = {}
        for row in self.selected_data:
            path_value = row[path_var]
            index_value = int(row[index_var])
            if path_value not in selected_indices_by_path:
                selected_indices_by_path[path_value] = []
            selected_indices_by_path[path_value].append(index_value)

        complete_indices_by_path = {}
        complete_chunks_by_path = {}
        for row in self.complete_data:
            path_value = row[path_var]
            index_value = int(row[index_var])
            text_chunk = row[chunks_var]
            if path_value not in complete_indices_by_path:
                complete_indices_by_path[path_value] = []
                complete_chunks_by_path[path_value] = {}
            complete_indices_by_path[path_value].append(index_value)
            complete_chunks_by_path[path_value][index_value] = text_chunk

        full_indices = set()
        for path_value, selected_indices in selected_indices_by_path.items():
            if path_value in complete_indices_by_path:
                complete_indices = complete_indices_by_path[path_value]
                min_idx, max_idx = min(complete_indices), max(complete_indices)
                for idx in selected_indices:
                    start_idx = max(min_idx, idx - self.extra_chunks)
                    end_idx = min(max_idx, idx + self.extra_chunks)
                    full_indices.update((path_value, i) for i in range(start_idx, end_idx + 1))

        selected_rows = [row for row in self.complete_data if (row[path_var], int(row[index_var])) in full_indices]
        output_data = Orange.data.Table(self.complete_data.domain, selected_rows)
        self.Outputs.data.send(output_data)

        merged_results = self.merge_chunks(selected_rows)
        concat_domain = Orange.data.Domain([], metas=[
            Orange.data.StringVariable("path"),
            Orange.data.StringVariable("Merged Chunks")
        ])
        merged_table = Orange.data.Table.from_list(concat_domain, merged_results)
        self.Outputs.concatenate_data.send(merged_table)

    def remove_overlap(self, text1, text2):
        if not text1 or text1 == Orange.data.Value:
            return str(text2) if text2 else ""
        if not text2 or text2 == Orange.data.Value:
            return str(text1) if text1 else ""

        text1 = str(text1)
        text2 = str(text2)

        max_overlap = min(len(text1), len(text2))
        for i in range(max_overlap, 0, -1):
            if text1[-i:] == text2[:i]:
                return text1 + text2[i:]
        return text1 + text2

    def merge_chunks(self, rows):
        doc_groups = {}
        for row in rows:
            path = row[self.complete_data.domain["path"]]
            chunk = row[self.complete_data.domain["Chunks"]]
            index = int(row[self.complete_data.domain["Chunks index"]])
            if path not in doc_groups:
                doc_groups[path] = {}
            doc_groups[path][index] = chunk  # Stocke les chunks avec leur index

        merged_results = []

        # 2. Parcourir les indices sélectionnés et récupérer leurs voisins
        for row in self.selected_data:
            path = row[self.complete_data.domain["path"]]
            index = int(row[self.complete_data.domain["Chunks index"]])

            if path not in doc_groups:
                continue  # Si le path n'existe pas, on passe

            # Définir les indices voisins à récupérer
            start_idx = index - self.extra_chunks
            end_idx = index + self.extra_chunks

            # Fusionner les chunks environnants
            merged_text = ""
            for i in range(start_idx, end_idx + 1):
                if i in doc_groups[path]:  # Vérifie que l'index existe
                    merged_text = self.remove_overlap(merged_text, doc_groups[path][i])

            merged_results.append([path, merged_text])

        return merged_results


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = OWExtraChunks()
    window.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()