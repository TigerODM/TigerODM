# OWSplitPath.py
from __future__ import annotations

from pathlib import Path
from typing import Tuple
import sys
import numpy as np
from AnyQt.QtWidgets import QApplication, QCheckBox
from Orange.data import StringVariable
from Orange.widgets.settings import Setting
import os
from AnyQt.QtCore import QTimer


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import base_widget, help_management
else:
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import  base_widget, help_management





# =========================
# Widget
# =========================
@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWSplitPath(base_widget.BaseListWidget):
    name = "Split Path"
    description = "Normalize path (resolve) and split into directory and file name."
    icon = "icons/split_path.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/split_path.png"
    category = "AAIT - TOOLBOX"

    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owsplitpath.ui")
    want_control_area = False
    priority = 100
    # Settings
    autorun = Setting(True)
    with_file_name_extension = Setting(False)
    with_file_name_without_extension = Setting(False)
    with_parent_dir_name_column = Setting(False)


    def _safe_str(self,x) -> str:
        if x is None:
            return ""
        try:
            if isinstance(x, float) and np.isnan(x):
                return ""
        except Exception:
            pass
        return str(x)

    def normalize_path(self,p: str) -> str:
        """Normalize a path using pathlib.resolve(strict=False)."""
        s = self._safe_str(p).strip()
        if not s:
            return ""

        try:
            return Path(s).expanduser().resolve(strict=False).as_posix()
        except Exception:
            # fallback: return raw string if pathlib fails
            return s

    def split_dir_file(self,p: str) -> Tuple[str, str]:
        if not p:
            return "", ""
        try:
            pp = Path(p)
            return pp.parent.as_posix(), pp.name
        except Exception:
            return "", p

    def _split_name_parts(self, filename: str) -> Tuple[str, str]:
        """
        Retourne (stem, extension_sans_point).
        Ex: "tata.txt" -> ("tata", "txt")
            "archive.tar.gz" -> ("archive.tar", "gz")
            ".gitignore" -> (".gitignore", "")
        """
        if not filename:
            return "", ""
        try:
            p = Path(filename)
            ext = p.suffix[1:] if p.suffix.startswith(".") else p.suffix  # sans le point
            return p.stem, ext
        except Exception:
            # fallback simple
            if "." in filename and not filename.startswith("."):
                base, ext = filename.rsplit(".", 1)
                return base, ext
            return filename, ""

    def _parent_dir_name(self, directory: str) -> str:
        """
        Retourne le nom du dossier parent final.
        Ex: "C:/toto/titi" -> "titi"
        """
        if not directory:
            return ""
        try:
            return Path(directory).name
        except Exception:
            return directory.rstrip("/\\").split("/")[-1].split("\\")[-1]

    def __init__(self):
        super().__init__()
        self.setFixedWidth(470)
        self.setFixedHeight(500)
        self.data = None
        self.checkbox_mode = self.findChild(QCheckBox, 'checkBox_send')


        self.checkBox_file_name_extension= self.findChild(QCheckBox, 'checkBox_file_name_extension')
        self.checkBox_file_name_without_extension= self.findChild(QCheckBox, 'checkBox_file_name_without_extension')
        self.checkBox_parent_dir_name_column= self.findChild(QCheckBox, 'checkBox_parent_dir_name_column')

        self.checkbox_mode.setChecked(self.autorun)



        self.checkBox_file_name_extension.setChecked(self.with_file_name_extension)
        self.checkBox_file_name_without_extension.setChecked(self.with_file_name_without_extension)
        self.checkBox_parent_dir_name_column.setChecked(self.with_parent_dir_name_column)



        self.checkbox_mode.stateChanged.connect(self.toogle_persistent)
        self.checkBox_file_name_extension.stateChanged.connect(self.toogle_name_extension)
        self.checkBox_file_name_without_extension.stateChanged.connect(self.toogle_file_name_without_extension)
        self.checkBox_parent_dir_name_column.stateChanged.connect(self.toogle_parent_dir_name_column)




        self.pushButton_send.clicked.connect(self.run)
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def run(self):
        self.warning("")
        self.error("")

        if self.data is None:
            self.Outputs.data.send(None)
            return
        if not self.selected_column_name in self.data.domain:
            self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
            return

        # colonnes toujours ajoutées
        if "path_dir" in self.data.domain:
            self.error('cannot be used with "path_dir" in input')
            return
        if "file_name" in self.data.domain:
            self.error('cannot be used with "file_name" in input')
            return

        # colonnes optionnelles
        if self.with_file_name_extension and "file_name_extension" in self.data.domain:
            self.error('cannot be used with "file_name_extension" in input')
            return
        if self.with_file_name_without_extension and "file_name_without_extension" in self.data.domain:
            self.error('cannot be used with "file_name_without_extension" in input')
            return
        if self.with_parent_dir_name_column and "parent_dir_name" in self.data.domain:
            self.error('cannot be used with "parent_dir_name" in input')
            return

        list_dir = []
        name_path = []
        list_ext = []  # sans point
        list_stem = []  # sans extension
        list_parent = []  # nom du dossier parent

        for row in self.data:
            current_path = str(row[self.selected_column_name].value)
            raw = self._safe_str(current_path)
            norm = self.normalize_path(raw)
            d, name = self.split_dir_file(norm)

            list_dir.append(d)
            name_path.append(name)

            stem, ext = self._split_name_parts(name)
            if self.with_file_name_extension:
                list_ext.append(ext)
            if self.with_file_name_without_extension:
                list_stem.append(stem)
            if self.with_parent_dir_name_column:
                list_parent.append(self._parent_dir_name(d))

        out_put_data = self.data.copy()

        # toujours
        out_put_data = out_put_data.add_column(StringVariable("path_dir"), list_dir, to_metas=True)
        out_put_data = out_put_data.add_column(StringVariable("file_name"), name_path, to_metas=True)

        # optionnel
        if self.with_file_name_extension:
            out_put_data = out_put_data.add_column(StringVariable("file_name_extension"), list_ext, to_metas=True)

        if self.with_file_name_without_extension:
            out_put_data = out_put_data.add_column(StringVariable("file_name_without_extension"), list_stem,
                                                   to_metas=True)

        if self.with_parent_dir_name_column:
            out_put_data = out_put_data.add_column(StringVariable("parent_dir_name"), list_parent, to_metas=True)

        self.Outputs.data.send(out_put_data)

    def toogle_persistent(self, enabled):
        if self.checkbox_mode.isChecked():
            self.autorun = True
        else:
            self.autorun = False

    def toogle_name_extension(self, enabled):
        if self.checkBox_file_name_extension.isChecked():
            self.with_file_name_extension = True
        else:
            self.with_file_name_extension = False

    def toogle_file_name_without_extension(self, enabled):
        if self.checkBox_file_name_without_extension.isChecked():
            self.with_file_name_without_extension = True
        else:
            self.with_file_name_without_extension = False


    def toogle_parent_dir_name_column(self, enabled):
        if self.checkBox_parent_dir_name_column.isChecked():
            self.with_parent_dir_name_column = True
        else:
            self.with_parent_dir_name_column = False


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWSplitPath()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
