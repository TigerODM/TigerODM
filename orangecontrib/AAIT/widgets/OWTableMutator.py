import Orange
import os
import sys
from Orange.widgets import widget
from Orange.widgets.widget import Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QPushButton, QCheckBox, QRadioButton
import numpy as np
from Orange.data import Table, Domain
from Orange.data import ContinuousVariable, DiscreteVariable, StringVariable, TimeVariable


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.AAIT.utils.import_uic import uic
# ----------------------------------------------------------------------
# Entrée : in_data
# Sortie : out_data
#
# Règles :
# - on prend toutes les colonnes (features, target, metas)
# - une colonne doit s'appeler exactement "ColName"
# - les valeurs de cette colonne deviennent les noms des colonnes en sortie
# - ces valeurs doivent être toutes différentes et non vides
# - la sortie est une transposée
# - tout est sorti en StringVariable
# - la première colonne de sortie s'appelle aussi "ColName"
#   pour permettre une transposée de transposée
# ----------------------------------------------------------------------
class OWTableMutator(widget.OWWidget):
    name = "Table Mutator"
    description = "Apply a transform to a datatable."
    icon = "icons/OWmutator.svg"
    category = "AAIT - ALGORITHM"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/OWmutator.svg"
    priority = 1145
    keywords = "transform datatable"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmutator.ui")
    want_control_area = False
    strauto: str = Setting('False')
    operation_mode: str = Setting("")

    class Inputs:
        data = Input("In data", Orange.data.Table)


    class Outputs:
        out_data = Output("Out data", Orange.data.Table)
    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.data=None
        self.checkbox_interface = self.findChild(QCheckBox, 'checkBox')
        self.radio_transpose = self.findChild(QRadioButton, 'radioButton_transpose')
        self.radioButton_cast_numeric = self.findChild(QRadioButton, 'radioButton_cast_numeric')
        self.radioButton_cast_string=self.findChild(QRadioButton, 'radioButton_cast_string')
        self.radioButton_multiply_colname = self.findChild(QRadioButton, 'radioButton_multiply_colname')
        self.radioButton_add_colname = self.findChild(QRadioButton, 'radioButton_add_colname')




        self.push_button_run = self.findChild(QPushButton, 'pushButton')
        if self.strauto == 'False':
            self.checkbox_interface.setChecked(False)
        else:
            self.checkbox_interface.setChecked(True)

        # Chargement radio depuis setting
        if self.operation_mode == "Transpose":
            self.radio_transpose.setChecked(True)
        else:
            self.radio_transpose.setChecked(False)

        if self.operation_mode == "CastNumeric":
            self.radioButton_cast_numeric.setChecked(True)
        else:
            self.radioButton_cast_numeric.setChecked(False)

        if self.operation_mode == "CastString":
            self.radioButton_cast_string.setChecked(True)
        else:
            self.radioButton_cast_string.setChecked(False)

        if self.operation_mode == "Mul":
            self.radioButton_multiply_colname.setChecked(True)
        else:
            self.radioButton_multiply_colname.setChecked(False)

        if self.operation_mode == "Add":
            self.radioButton_add_colname.setChecked(True)
        else:
            self.radioButton_add_colname.setChecked(False)




        self.push_button_run.clicked.connect(self.run)
        self.checkbox_interface.toggled.connect(self.on_auto_toggled)

        self.radio_transpose.toggled.connect(self.on_radio_transpose_toggled)
        self.radioButton_cast_numeric.toggled.connect(self.on_radio_cast_nuemric_toggled)
        self.radioButton_cast_string.toggled.connect(self.on_radioButton_cast_string_toggled)
        self.radioButton_add_colname.toggled.connect(self.on_radioButton_add_colname_toggled)
        self.radioButton_multiply_colname.toggled.connect(self.on_radioButton_mul_colname_toggled)



        if self.strauto == 'True':
            self.run()

    def on_auto_toggled(self, checked):
        if checked:
            self.strauto = "True"
        else:
            self.strauto = "False"


    def on_radio_cast_nuemric_toggled(self,checked):
        if checked:
            self.operation_mode = "CastNumeric"


    def on_radio_transpose_toggled(self, checked):
        if checked:
            self.operation_mode = "Transpose"

    def on_radioButton_cast_string_toggled(self,checked):
        if checked:
            self.operation_mode = "CastString"

    def on_radioButton_add_colname_toggled(self,checked):
        if checked:
            self.operation_mode = "Add"

    def on_radioButton_mul_colname_toggled(self,checked):
        if checked:
            self.operation_mode = "Mul"



    @Inputs.data
    def set_data(self, data):
        if data is None:
            self.Outputs.out_data.send(None)
            return
        self.data=data
        self.run()
    def run(self):
        self.error("")
        if self.operation_mode == "Transpose":
            self.run_translate()
            return

        if self.operation_mode == "CastNumeric":
            self.run_numeric()
            return

        if self.operation_mode == "CastString":
            self.run_string()
            return

        if self.operation_mode == "Add":
            try:
                self.run_add()
            except Exception as e:
                self.error(str(e))
            return
        if self.operation_mode == "Mul":
            try:
                self.run_mul()
            except Exception as e:
                self.error(str(e))
            return
        self.error("please check an option")
        return

    def run_translate(self):
        self.error("")
        in_data=self.data
        if in_data is None:
            return

        if len(in_data) == 0:
            self.error("in_data est vide.")
            self.Outputs.out_data.send(None)
            return

        # Toutes les variables du domaine
        attrs = list(in_data.domain.attributes)
        class_vars = list(in_data.domain.class_vars)
        metas = list(in_data.domain.metas)

        all_vars = attrs + class_vars + metas

        if not all_vars:
            self.error("Aucune colonne trouvée dans in_data.")
            self.Outputs.out_data.send(None)
            return

        # Recherche de la colonne ColName
        colname_var = None
        for var in all_vars:
            if var.name == "ColName":
                colname_var = var
                break

        if colname_var is None:
            self.error("Erreur : aucune colonne nommée 'ColName' n'a été trouvée dans in_data.")
            self.Outputs.out_data.send(None)
            return


        # Conversion robuste vers string compatible Orange
        def cell_to_str(row, var):
            try:
                return var.str_val(row[var])
            except Exception:
                try:
                    s = str(row[var])
                    if s == "?" or s.lower() == "nan":
                        return ""
                    return s
                except Exception:
                    return ""

        # Récupération des futurs noms de colonnes depuis ColName
        future_col_names = [cell_to_str(row, colname_var) for row in in_data]

        # Vérification : non vides
        empty_positions = [i for i, v in enumerate(future_col_names) if v is None or str(v).strip() == ""]
        if empty_positions:
            self.error("Erreur : la colonne 'ColName' contient une ou plusieurs valeurs vides ou manquantes. Impossible de créer les noms de colonnes.")
            self.Outputs.out_data.send(None)
            return


        # Vérification : unicité
        seen = set()
        duplicates = []
        for v in future_col_names:
            if v in seen and v not in duplicates:
                duplicates.append(v)
            seen.add(v)

        if duplicates:
            self.error("Erreur : la colonne 'ColName' contient des doublons : "+ ", ".join(duplicates))
            self.Outputs.out_data.send(None)
            return

        # Colonnes à transposer = toutes sauf ColName
        vars_to_transpose = [var for var in all_vars if var != colname_var]

        if not vars_to_transpose:
            self.error("Erreur : aucune colonne à transposer en dehors de 'ColName'.")
            self.Outputs.out_data.send(None)
            return

        # Construction des lignes de sortie
        # 1ère valeur = nom de la colonne d'origine, stocké dans la colonne "ColName"
        # valeurs suivantes = valeurs par ligne d'origine
        rows_out = []
        for var in vars_to_transpose:
            new_row = [var.name]
            for row in in_data:
                new_row.append(cell_to_str(row, var))
            rows_out.append(new_row)

        # La première colonne s'appelle "ColName" pour permettre une re-transposée
        out_col_names = ["ColName"] + future_col_names

        # Tout en StringVariable
        out_meta_vars = [StringVariable(name) for name in out_col_names]
        out_domain = Domain([], metas=out_meta_vars)

        # Création table Orange
        out_data = Table.from_list(out_domain, rows_out)
        self.Outputs.out_data.send(out_data)

    def run_numeric(self):
        self.error("")
        in_data=self.data
        if in_data is None:
            return
        out_data = self.cast_possible_columns_to_numeric_features(in_data)
        self.Outputs.out_data.send(out_data)
    # -------------------------------------------------------------------
    def cast_possible_columns_to_numeric_features(self,table: Table) -> Table:
        """
        Prend une Orange Table en entrée.
        - Parcourt toutes les colonnes : features, targets, metas
        - Si une colonne peut être convertie en numérique à partir de ses valeurs,
          elle devient une ContinuousVariable placée dans les features
        - Tout le reste est laissé inchangé dans son rôle d'origine
        - Les valeurs manquantes restent manquantes

        Règles de conversion :
        - ContinuousVariable : déjà numérique => déplacée en feature
        - TimeVariable : considérée convertible => transformée en ContinuousVariable en feature
        - DiscreteVariable : conversion via les labels
        - StringVariable : conversion via les chaînes
        """

        def is_missing(v):
            if v is None:
                return True
            if isinstance(v, str):
                s = v.strip()
                return s == "" or s.lower() in {"nan", "none", "null", "?"}
            try:
                return bool(np.isnan(v))
            except Exception:
                return False

        def normalize_numeric_string(s: str) -> str:
            s = s.strip()
            # tolérance simple pour les décimales françaises
            if "," in s and "." not in s:
                s = s.replace(",", ".")
            return s

        def try_float_from_any(v):
            if is_missing(v):
                return np.nan, True

            if isinstance(v, (int, float, np.integer, np.floating)):
                try:
                    return float(v), True
                except Exception:
                    return None, False

            if isinstance(v, str):
                s = normalize_numeric_string(v)
                try:
                    return float(s), True
                except Exception:
                    return None, False

            # fallback
            try:
                s = normalize_numeric_string(str(v))
                return float(s), True
            except Exception:
                return None, False

        def extract_raw_column_values(tab: Table, var):
            """
            Renvoie une liste Python des valeurs 'lisibles' de la colonne :
            - Continuous/Time : valeurs numériques brutes
            - Discrete : labels
            - String/meta : objets/chaînes tels quels
            """
            col = tab.get_column(var)

            if isinstance(var, ContinuousVariable):
                return list(col)

            if isinstance(var, TimeVariable):
                return list(col)

            if isinstance(var, DiscreteVariable):
                out = []
                values = list(var.values)
                for x in col:
                    if is_missing(x):
                        out.append(None)
                    else:
                        try:
                            idx = int(x)
                            if 0 <= idx < len(values):
                                out.append(values[idx])
                            else:
                                out.append(None)
                        except Exception:
                            out.append(None)
                return out

            if isinstance(var, StringVariable):
                return list(col)

            return list(col)

        def column_can_be_numeric_and_values(tab: Table, var):
            """
            Retourne :
            - (True, np.array float)) si convertible
            - (False, None) sinon
            """
            # Déjà numérique
            if isinstance(var, ContinuousVariable):
                arr = tab.get_column(var).astype(float, copy=True)
                return True, arr

            # Time -> numérique brut
            if isinstance(var, TimeVariable):
                arr = tab.get_column(var).astype(float, copy=True)
                return True, arr

            raw_vals = extract_raw_column_values(tab, var)
            converted = np.full(len(raw_vals), np.nan, dtype=float)

            for i, v in enumerate(raw_vals):
                num, ok = try_float_from_any(v)
                if not ok:
                    return False, None
                converted[i] = num

            return True, converted

        n_rows = len(table)

        original_attrs = list(table.domain.attributes)
        original_class_vars = list(table.domain.class_vars)
        original_metas = list(table.domain.metas)

        all_vars_in_order = original_attrs + original_class_vars + original_metas

        new_attrs = []
        new_class_vars = []
        new_metas = []

        attr_data = []
        class_data = []
        meta_data = []

        for var in all_vars_in_order:
            convertible, numeric_values = column_can_be_numeric_and_values(table, var)

            if convertible:
                # Toute colonne convertible devient feature continue
                new_var = ContinuousVariable(var.name)
                new_attrs.append(new_var)
                attr_data.append(numeric_values.reshape(n_rows, 1))
            else:
                # Sinon on laisse inchangé, dans son rôle d'origine
                if var in original_attrs:
                    new_attrs.append(var)
                    col = table.get_column(var)
                    attr_data.append(np.asarray(col, dtype=float).reshape(n_rows, 1))

                elif var in original_class_vars:
                    new_class_vars.append(var)
                    col = table.get_column(var)
                    if isinstance(var, (ContinuousVariable, TimeVariable)):
                        class_data.append(np.asarray(col, dtype=float).reshape(n_rows, 1))
                    else:
                        class_data.append(np.asarray(col, dtype=float).reshape(n_rows, 1))

                elif var in original_metas:
                    new_metas.append(var)
                    raw_vals = extract_raw_column_values(table, var)
                    meta_data.append(np.asarray(raw_vals, dtype=object).reshape(n_rows, 1))

        X = np.hstack(attr_data) if attr_data else np.empty((n_rows, 0), dtype=float)
        Y = np.hstack(class_data) if class_data else np.empty((n_rows, 0), dtype=float)
        M = np.hstack(meta_data) if meta_data else np.empty((n_rows, 0), dtype=object)

        new_domain = Domain(new_attrs, new_class_vars, new_metas)
        return Table.from_numpy(new_domain, X, Y, M)

    def run_string(self):
        self.error("")
        in_data=self.data
        if in_data is None:
            return
        out_data = self.cast_all_columns_to_meta_stringvariables(in_data)
        self.Outputs.out_data.send(out_data)

    def cast_all_columns_to_meta_stringvariables(self,table: Table) -> Table:
        """
        Convertit toutes les colonnes d'une Orange Table en StringVariable
        et les place toutes dans les metas.

        - toutes les features deviennent metas StringVariable
        - toutes les target deviennent metas StringVariable
        - toutes les metas deviennent metas StringVariable
        - aucune exception
        - les noms de colonnes sont conservés
        - les valeurs manquantes deviennent ""
        """

        def is_missing(v):
            if v is None:
                return True
            if isinstance(v, str):
                s = v.strip()
                return s == "" or s.lower() in {"nan", "none", "null", "?"}
            try:
                return bool(np.isnan(v))
            except Exception:
                return False

        def value_to_string(var, v):
            if is_missing(v):
                return ""

            if isinstance(var, DiscreteVariable):
                try:
                    idx = int(v)
                    if 0 <= idx < len(var.values):
                        return str(var.values[idx])
                    return ""
                except Exception:
                    return ""

            return str(v)

        n_rows = len(table)
        all_vars = list(table.domain.attributes) + list(table.domain.class_vars) + list(table.domain.metas)

        new_metas = []
        meta_parts = []

        for var in all_vars:
            col = table.get_column(var)
            str_vals = [value_to_string(var, v) for v in col]
            new_metas.append(StringVariable(var.name))
            meta_parts.append(np.array(str_vals, dtype=object).reshape(n_rows, 1))

        M = np.hstack(meta_parts) if meta_parts else np.empty((n_rows, 0), dtype=object)
        new_domain = Domain([], [], new_metas)

        return Table.from_numpy(
            new_domain,
            X=np.empty((n_rows, 0), dtype=float),
            Y=np.empty((n_rows, 0), dtype=float),
            metas=M
        )

    def run_mul(self):
        self.error("")
        in_data=self.data
        if in_data is None:
            return

        out_data = self.apply_colname_on_all_continuous_columns(in_data, col_name="ColName", operation="mul")

        self.Outputs.out_data.send(out_data)

    def run_add(self):
        self.error("")
        in_data=self.data
        if in_data is None:
            return
        print("ici")
        out_data = self.apply_colname_on_all_continuous_columns(in_data, col_name="ColName", operation="add")
        print("la")
        self.Outputs.out_data.send(out_data)

    def apply_colname_on_all_continuous_columns(self,table: Table, col_name: str = "ColName", operation: str = "add") -> Table:
        """
        Applique une opération ligne à ligne entre la colonne `col_name`
        et toutes les colonnes ContinuousVariable de la table, sauf elle-même.

        Paramètres
        ----------
        table : Orange.data.Table
            Table d'entrée.
        col_name : str
            Nom de la colonne de référence.
        operation : str
            "add" pour addition
            "mul" pour multiplication

        Retour
        ------
        Orange.data.Table
            Nouvelle table avec les colonnes Continuous modifiées.

        Règles
        ------
        - `col_name` doit exister
        - `col_name` doit être une ContinuousVariable
        - seules les ContinuousVariable sont modifiées
        - traitement sur features, class_vars et metas
        - `col_name` elle-même n'est pas modifiée
        """

        if operation not in {"add", "mul"}:
            raise ValueError("operation doit valoir 'add' ou 'mul'.")

        domain = table.domain
        n = len(table)

        all_vars = list(domain.attributes) + list(domain.class_vars) + list(domain.metas)

        ref_var = None
        for var in all_vars:
            if var.name == col_name:
                ref_var = var
                break

        if ref_var is None:
            raise ValueError(f"Colonne '{col_name}' introuvable.")

        if not isinstance(ref_var, ContinuousVariable):
            raise ValueError(f"La colonne '{col_name}' doit être une ContinuousVariable.")

        ref_values = np.asarray(table.get_column(ref_var), dtype=float)

        X = np.array(table.X, dtype=float, copy=True) if table.X.size else np.empty((n, 0), dtype=float)
        Y = np.array(table.Y, dtype=float, copy=True) if table.Y.size else np.empty((n, 0), dtype=float)
        M = np.array(table.metas, dtype=object, copy=True) if table.metas.size else np.empty((n, 0), dtype=object)

        # Features
        for j, var in enumerate(domain.attributes):
            if var.name == col_name:
                continue
            if isinstance(var, ContinuousVariable):
                if operation == "add":
                    X[:, j] = X[:, j] + ref_values
                else:
                    X[:, j] = X[:, j] * ref_values

        # Targets
        for j, var in enumerate(domain.class_vars):
            if var.name == col_name:
                continue
            if isinstance(var, ContinuousVariable):
                if operation == "add":
                    Y[:, j] = Y[:, j] + ref_values
                else:
                    Y[:, j] = Y[:, j] * ref_values

        # Metas
        for j, var in enumerate(domain.metas):
            if var.name == col_name:
                continue
            if isinstance(var, ContinuousVariable):
                col_vals = np.asarray(table.get_column(var), dtype=float)
                if operation == "add":
                    M[:, j] = col_vals + ref_values
                else:
                    M[:, j] = col_vals * ref_values

        return Table.from_numpy(domain, X, Y, M)

if __name__ == "__main__":
    from AnyQt.QtWidgets import QApplication

    app = QApplication(sys.argv)
    my_widget = OWTableMutator()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()