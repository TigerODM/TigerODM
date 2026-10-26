import os, sys
from pathlib import Path
import numpy as np
import re
import Orange.data
from AnyQt.QtWidgets import QApplication, QCheckBox, QPushButton
from Orange.data import StringVariable, Table, Domain
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import base_widget, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.IO4IT.utils import utils_md
else:
    from orangecontrib.AAIT.utils import base_widget, help_management
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.IO4IT.utils import utils_md
    from orangecontrib.AAIT.utils.import_uic import uic


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWMarkdownLoader(base_widget.BaseListWidget):
    name = "Markdown Loader"
    description = "Load Markdown files from a folder (recursively) or directly from specific file paths."
    icon = "icons/load_md.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/load_md.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmarkdownloader.ui")
    want_control_area = False
    priority = 1001

    selected_column_name = Setting("input_dir")
    recursive = Setting(False)
    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        md_files = Output("Markdown Files", Orange.data.Table)  # -> (file_path, content)
        data = Output("Data", Orange.data.Table)  # passthrough de l'entrée

    @Inputs.data
    def set_path_table(self, in_data):
        self.data = in_data

        # Always pass through the input data
        self.Outputs.data.send(in_data)

        if in_data is None:
            self.Outputs.md_files.send(self._empty_md_table())
            return

        if self.data:
            # Remplissage du selecteur de colonnes (issu de BaseListWidget)
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)

        self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(500)
        self.setFixedHeight(400)

        self.data = None
        self.autorun = True

        # Checkbox Récursif
        self.checkBoxRecursive = self.findChild(QCheckBox, 'checkBoxRecursive')
        self.checkBoxRecursive.setChecked(self.recursive)
        self.checkBoxRecursive.stateChanged.connect(self._on_recursive_toggled)

        # Run Button
        self.pushButton_run = self.findChild(QPushButton, 'pushButton_send')
        self.pushButton_run.clicked.connect(self.run)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))
        self.post_initialized()

    def _on_recursive_toggled(self, state):
        self.recursive = self.checkBoxRecursive.isChecked()
        if self.data is not None:
            self.run()

    def update_parameters(self):
        if self.data is not None:
            self.run()

    def _empty_md_table(self) -> Table:
        domain = Domain([], metas=[StringVariable("file_path"), StringVariable("content")])
        X = np.empty((0, 0))
        metas = np.empty((0, 2), dtype=object)
        return Table.from_numpy(domain, X, metas=metas)

    def run(self):
        self.error("")
        self.warning("")

        if self.data is None:
            self.Outputs.md_files.send(self._empty_md_table())
            return

        if not self.selected_column_name in self.data.domain:
            self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
            self.Outputs.md_files.send(self._empty_md_table())
            return

        # Récupération sécurisée des chemins depuis la colonne sélectionnée
        try:
            if hasattr(self.data, "get_column"):
                input_paths = self.data.get_column(self.selected_column_name)
            else:
                # Fallback au cas où get_column n'existe pas
                col_idx = self.data.domain.index(self.selected_column_name)
                input_paths = [row[col_idx].value for row in self.data]
        except Exception as e:
            self.error(f"Error reading column data: {e}")
            return

        md_rows = []
        seen_paths = set()

        for p_val in input_paths:
            if not p_val:
                continue

            p_str = str(p_val)
            if not os.path.exists(p_str):
                continue

            p = Path(p_str)

            # CAS 1 : C'est un fichier direct
            if p.is_file():
                if p.suffix.lower() == ".md" and p not in seen_paths:
                    seen_paths.add(p)
                    try:
                        md_rows.append([str(p), utils_md.try_read_text(p)])
                    except Exception:
                        md_rows.append([str(p), ""])

            # CAS 2 : C'est un répertoire
            elif p.is_dir():
                patterns = ["*.md"]
                found_paths = []
                for patt in patterns:
                    if self.recursive:
                        found_paths.extend(p.rglob(patt))
                    else:
                        found_paths.extend(p.glob(patt))

                for fp in found_paths:
                    if fp not in seen_paths and fp.is_file():
                        seen_paths.add(fp)
                        try:
                            md_rows.append([str(fp), utils_md.try_read_text(fp)])
                        except Exception:
                            md_rows.append([str(fp), ""])

        # Formatage des données de sortie
        domain = Domain([], metas=[StringVariable("file_path"), StringVariable("content")])
        X = np.empty((len(md_rows), 0))
        metas = np.array(md_rows, dtype=object) if md_rows else np.empty((0, 2), dtype=object)
        md_table = Table.from_numpy(domain, X, metas=metas)

        self.Outputs.md_files.send(md_table)

    def post_initialized(self):
        pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWMarkdownLoader()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()