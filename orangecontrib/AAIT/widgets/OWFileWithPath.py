import os
import sys

import Orange.data
from AnyQt.QtWidgets import QApplication, QPushButton
from Orange.data import StringVariable
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtWidgets import QCheckBox
from Orange.widgets.settings import Setting
from AnyQt.QtCore import QTimer
from pathlib import Path
import numpy as np
import pandas as pd
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import base_widget, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import base_widget, help_management
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWFileWithPath(base_widget.BaseListWidget):
    name = "File with Path"
    category = "AAIT - TOOLBOX"
    description = "Load some tabular data specified with a filepath ('.../data/example.xlsx')."
    icon = "icons/owfilewithpath.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owfilewithpath.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owfilewithpath.ui")
    want_control_area = False
    priority = 1060

    # Settings
    selected_column_name = Setting("path")

    class Inputs:
        filepath = Input("Path", str, auto_summary=False)
        path_table = Input("Path Table", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    strloadAsString: str = Setting('False')
    strloadWithPandaReader: str = Setting('False')
    strRenameColumns: str = Setting('False')

    @Inputs.filepath
    def set_filepath(self, in_filepath):
        if in_filepath is not None:
            self.filepath = in_filepath
            self.run()

    @Inputs.path_table
    def set_path_table(self, in_path_table):
        self.in_path_table = in_path_table
        if self.in_path_table is None:
            self.Outputs.data.send(None)
            return
        if self.in_path_table is not None:
            self.var_selector.add_variables(self.in_path_table.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)

            self.filepath = in_path_table[0][self.selected_column_name].value
            self.run()

        if self.autorun:
            self.run()


    def __init__(self):
        super().__init__()
        # Qt Management
        #uic.loadUi(self.gui, self)
        self.setFixedWidth(500)
        self.setFixedHeight(450)
        self.checkbox_interface = self.findChild(QCheckBox, 'checkBox')
        self.checkbox_panda = self.findChild(QCheckBox, 'checkBox_2')


        if self.strloadAsString!="True":
            self.checkbox_interface.setChecked(False)
        else:
            self.checkbox_interface.setChecked(True)

        if self.strloadWithPandaReader != "True":
            self.checkbox_panda.setChecked(False)
        else:
            self.checkbox_panda.setChecked(True)


        self.checkbox_interface.stateChanged.connect(self.on_checkbox_toggled)
        self.checkbox_panda.stateChanged.connect(self.on_checkbox_panda_toggled)
        self.checkbox_rename = self.findChild(QCheckBox, 'checkBox_rename_cols')
        if self.strRenameColumns == "False":
            self.checkbox_rename.setChecked(False)
        else:
            self.checkbox_rename.setChecked(True)
        self.checkbox_rename.stateChanged.connect(self.on_checkbox_rename_toggled)

        # Data Management
        self.filepath = None
        self.in_path_table = None
        self.data = None
        self.autorun = True
        self.post_initialized()

        self.pushButton_run = self.findChild(QPushButton, 'pushButton_send')
        self.pushButton_run.clicked.connect(self.run)
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))
    def on_checkbox_toggled(self):
        if self.checkbox_interface.isChecked():
            self.strloadAsString="True"
        else:
            self.strloadAsString="False"

    def on_checkbox_panda_toggled(self):
        if self.checkbox_panda.isChecked():
            self.strloadWithPandaReader="True"
        else:
            self.strloadWithPandaReader="False"

    def on_checkbox_rename_toggled(self):
        if self.checkbox_rename.isChecked():
            self.strRenameColumns = "True"
        else:
            self.strRenameColumns = "False"

    def safe_repr_val(self, var, val, missing_as_empty=False):
        """
        Version robuste de var.repr_val(val) :
        - gère les valeurs NaN/Inf
        - gère les erreurs de datetime.fromtimestamp (OSError invalid argument)
        """
        try:
            if var.is_string:
                s = var.str_val(val)  # pas de guillemets
            else:
                s = var.repr_val(val)
            if missing_as_empty and s == "?":
                return ""
            return s
        except (ValueError, OverflowError, OSError):
            # cas des TimeVariable avec timestamp invalide
            return "" if missing_as_empty else "?"

    def load_table_as_strings(self,filepath: str) -> Orange.data.Table:
        """
        Charge un fichier Orange et renvoie un Table où toutes les colonnes
        (features, class, metas) sont converties en StringVariable et placées en metas.
        """
        missing_as_empty=True # si on passe a True on met "" à la place de ?
        t = Orange.data.Table.from_file(filepath)
        dom = t.domain

        # 2) Toutes les variables d'origine
        all_vars = list(dom.attributes) + list(dom.class_vars) + list(dom.metas)

        # 3) Créer des StringVariable correspondantes
        new_metas = tuple(Orange.data.StringVariable(v.name) for v in all_vars)

        # 4) Domaine final : que des metas
        new_domain = Orange.data.Domain([], None, new_metas)

        # 5) Créer table vide
        t_str = Orange.data.Table.from_domain(new_domain, len(t))

        # 6) Remplissage sécurisé
        for j, src_var in enumerate(all_vars):
            col_data = t.get_column(src_var)
            text_vals = [self.safe_repr_val(src_var, v, missing_as_empty) for v in col_data]
            t_str.metas[:, j] = text_vals

        # 7) Métadonnées
        t_str.name = t.name
        t_str.ids = t.ids
        t_str.attributes = dict(getattr(t, "attributes", {}))

        return t_str

    def load_table_with_pandas_as_strings(
            self,
            filepath: str
    ) -> Orange.data.Table:
        """
        Charge un fichier avec pandas et renvoie une table Orange dont toutes
        les colonnes sont des StringVariable placées dans les métadonnées.

        Les valeurs manquantes sont remplacées par une chaîne vide "".

        Formats pris en charge :
            - CSV : .csv
            - TSV / texte tabulé : .tsv, .tab
            - Excel : .xlsx, .xls, .xlsm, .xlsb, .ods
            - JSON : .json
            - JSON Lines : .jsonl, .ndjson
            - Parquet : .parquet
            - Feather : .feather
            - Pickle pandas : .pkl, .pickle
            - HTML : .html, .htm
            - XML : .xml
        """
        path = Path(filepath)
        extension = path.suffix.lower()
        try:
            if extension == ".csv":
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    first_line = f.readline()

                # Choix du séparateur le plus fréquent
                sep = max((";", ",", "\t", "|"), key=first_line.count)

                df = pd.read_csv(
                    filepath,
                    sep=sep,
                    engine="c",
                    dtype=str,
                    keep_default_na=False,
                    on_bad_lines="error",
                )

            elif extension in {".tsv", ".tab"}:
                df = pd.read_csv(
                    filepath,
                    sep="\t",
                    dtype=str,
                    keep_default_na=False
                )

            elif extension in {".xlsx", ".xls", ".xlsm", ".xlsb", ".ods"}:
                df = pd.read_excel(
                    filepath,
                    dtype=str,
                    keep_default_na=False
                )

            elif extension == ".json":
                df = pd.read_json(
                    filepath,
                    dtype=False
                )

            elif extension in {".jsonl", ".ndjson"}:
                df = pd.read_json(
                    filepath,
                    lines=True,
                    dtype=False
                )

            elif extension == ".parquet":
                df = pd.read_parquet(filepath)

            elif extension == ".feather":
                df = pd.read_feather(filepath)

            elif extension in {".pkl", ".pickle"}:
                df = pd.read_pickle(filepath)

            elif extension in {".html", ".htm"}:
                tables = pd.read_html(filepath)

                if not tables:
                    raise ValueError(
                        f"No HTML table was found in the file: {filepath}"
                    )

                # On utilise la première table trouvée dans le fichier HTML.
                df = tables[0]

            elif extension == ".xml":
                df = pd.read_xml(filepath)

            else:
                self.error(f"Unsupported pandas file format: {extension or '(no extension)'}")
                return None
        except Exception as e:
            self.error(f"Failed to load file with panda:", e)
            return None
        # Certains lecteurs pandas ne prennent pas en charge dtype=str ou
        # keep_default_na=False. On harmonise donc toutes les données ici.
        df = df.fillna("")

        # Conversion de chaque valeur en chaîne, sans transformer les chaînes
        # vides en "nan", "None" ou "<NA>".
        for column in df.columns:
            df[column] = df[column].map(
                lambda value: "" if pd.isna(value) else str(value)
            )

        # Orange exige des noms de variables sous forme de chaînes.
        column_names = [str(column) for column in df.columns]

        new_metas = tuple(
            Orange.data.StringVariable(column_name)
            for column_name in column_names
        )

        new_domain = Orange.data.Domain(
            [],
            None,
            new_metas
        )

        metas_array = df.to_numpy(dtype=object)

        t_str = Orange.data.Table.from_numpy(
            new_domain,
            X=np.empty((len(df), 0), dtype=float),
            Y=None,
            metas=metas_array
        )

        t_str.name = path.stem

        return t_str


    def force_rename_columns(self, table: Orange.data.Table) -> Orange.data.Table:
        def clone_var(var, new_name):
            # Recréer la variable avec le nouveau nom selon son type
            if var.is_discrete:
                new_var = Orange.data.DiscreteVariable(new_name, values=var.values)
            else:
                new_var = type(var)(new_name)

            new_var.attributes = var.attributes.copy()
            return new_var

        dom = table.domain
        attrs, cvars, metas = [], [], []
        idx = 1

        for var in dom.attributes:
            attrs.append(clone_var(var, f"col_{idx}"))
            idx += 1

        for var in dom.class_vars:
            cvars.append(clone_var(var, f"col_{idx}"))
            idx += 1

        for var in dom.metas:
            metas.append(clone_var(var, f"col_{idx}"))
            idx += 1

        new_domain = Orange.data.Domain(attrs, cvars, metas)
        W = table.W if table.has_weights() else None

        new_table = Orange.data.Table.from_numpy(new_domain, table.X, table.Y, table.metas, W)
        new_table.name = table.name
        new_table.ids = table.ids
        new_table.attributes = dict(getattr(table, "attributes", {}))
        return new_table

    def run(self):
        self.error("")
        self.warning("")
        if self.strloadAsString!="False" and self.strloadWithPandaReader!="False":
            self.error("Only Standard or Pandas can be selected")
            self.Outputs.data.send(None)
            return

        if self.filepath is None:
            self.Outputs.data.send(None)
            return

        self.filepath = self.filepath.strip('"')
        if not os.path.exists(self.filepath):
            self.error("error input file doesn t exist")
            self.Outputs.data.send(None)
            return
        if self.in_path_table is not None:
              # Verification of in_data
            if not self.selected_column_name in self.in_path_table.domain:
                self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
                self.Outputs.data.send(None)
                return

            if not isinstance(self.in_path_table.domain[self.selected_column_name], StringVariable):
                self.error('You must select a text variable.')
                self.Outputs.data.send(None)
                return

        if self.strloadAsString!="False":
            out_data = self.load_table_as_strings(self.filepath)
        elif self.strloadWithPandaReader!="False":
            out_data = self.load_table_with_pandas_as_strings(self.filepath)
        else:
            out_data = Orange.data.Table.from_file(self.filepath)

        if self.strRenameColumns != "False":
            out_data = self.force_rename_columns(out_data)

        out_data.name = self.filepath
        self.Outputs.data.send(out_data)


    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWFileWithPath()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
