import os, sys
from pathlib import Path
import numpy as np

from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Domain, StringVariable, Table
from AnyQt.QtWidgets import QCheckBox, QApplication
from Orange.widgets.settings import Setting


try:
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.IO4IT.utils import utils_md
except ImportError:
    from orangecontrib.IO4IT.utils import utils_md
    from orangecontrib.AAIT.utils.import_uic import uic


class OWMarkdownLoader(widget.OWWidget):
    name = "Markdown Loader"
    description = "Load all Markdown files from a folder (recursively)."
    icon = "icons/load_md.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/load_md.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmarkdownloader.ui")
    want_control_area = False
    priority = 1001
    recursive = Setting(False)
    class Inputs:
        data = Input("Data", Table)

    class Outputs:
        md_files = Output("Markdown Files", Table)  # -> (file_path, content)
        data = Output("Data", Table)  # passthrough de l'entrée

    def __init__(self):
        super().__init__()

        self.in_data = None
        self.input_dir = None
        uic.loadUi(self.gui, self)


        self.checkBoxRecursive = self.findChild(QCheckBox, 'checkBoxRecursive')
        # These lines MUST be after super().__init__()
        if self.recursive:
            self.checkBoxRecursive.setChecked(True)
        else:
            self.checkBoxRecursive.setChecked(False)
        self.recursive = self.checkBoxRecursive.isChecked()
        self.checkBoxRecursive.stateChanged.connect(self._on_recursive_toggled)

        self.warning("")

    def _on_recursive_toggled(self, _state):
        self.recursive = self.checkBoxRecursive.isChecked()
        # If a directory is already set, re-run the production
        if self.input_dir:
            self._produce()

    @Inputs.data
    def set_data(self, in_data: Table | None):
        self.in_data = in_data
        self.warning("")

        # Always pass through the input data
        self.Outputs.data.send(in_data)

        if not in_data:
            # If no input data, send an empty table
            self.Outputs.md_files.send(self._empty_md_table())
            self.Description.setText(
                "This widget loads Markdown files from a folder. The path must be in a column named 'input_dir'.")
            return

        # Look for the 'input_dir' column and get the first folder
        try:
            input_dir_column = in_data.domain["input_dir"]
            self.input_dir = str(in_data[0, input_dir_column].value)
        except (KeyError, IndexError, AttributeError):
            self.warning('"input_dir" (Text) is required in the input data.')
            self.Outputs.md_files.send(self._empty_md_table())
            self.Description.setText("Error: 'input_dir' (Text) column not found or is empty.")
            return

        self.Description.setText(f"Dossier : {self.input_dir}")
        self._produce()

    def _empty_md_table(self) -> Table:
        domain = Domain([], metas=[StringVariable("file_path"), StringVariable("content")])
        X = np.empty((0, 0))
        metas = np.empty((0, 2), dtype=object)
        return Table.from_numpy(domain, X, metas=metas)

    def _produce(self):
        if not self.input_dir or not os.path.isdir(self.input_dir):
            self.warning(f"Invalid directory path: '{self.input_dir}'")
            self.Outputs.md_files.send(self._empty_md_table())
            return
        base = Path(self.input_dir)
        patterns = ["*.md"]
        paths = []

        for patt in patterns:
            if self.recursive:
                paths.extend(base.rglob(patt))
            else:
                paths.extend(base.glob(patt))

        md_rows = []
        for p in sorted(set(paths)):
            try:
                md_rows.append([str(p), utils_md.try_read_text(p)])
            except Exception:
                md_rows.append([str(p), ""])
        domain = Domain([], metas=[StringVariable("file_path"), StringVariable("content")])
        X = np.empty((len(md_rows), 0))
        metas = np.array(md_rows, dtype=object) if md_rows else np.empty((0, 2), dtype=object)
        md_table = Table.from_numpy(domain, X, metas=metas)

        self.Outputs.md_files.send(md_table)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWMarkdownLoader()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()