import os
import sys
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

import numpy as np
from Orange.data import Table, Domain, Variable, DiscreteVariable
from Orange.widgets import widget
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output

from AnyQt.QtWidgets import (
    QApplication,
    QWidget,
    QComboBox,
    QPushButton,
    QCheckBox,
    QSizePolicy,
)
from AnyQt.QtCore import QTimer

# Importations conditionnelles pour refléter l'environnement Orange add-on
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic  # noqa: F401
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import (
        apply_modification_from_python_file,
    )
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic  # type: ignore  # noqa: F401
    from orangecontrib.AAIT.utils.initialize_from_ini import (  # type: ignore
        apply_modification_from_python_file,
    )
    from orangecontrib.AAIT.utils import help_management

# Maps display name -> (include_matched, include_only_a, include_only_b)
JOIN_TYPES: List[Tuple[str, str]] = [
    ("Full Outer Join  (A ∪ B)", "full_outer"),
    ("Inner Join       (A ∩ B)", "inner"),
    ("Left Join        (all A + B match)", "left"),
    ("Right Join       (all B + A match)", "right"),
    ("Left Anti Join   (only A unmatched)", "left_anti"),
    ("Right Anti Join  (only B unmatched)", "right_anti"),
    ("Index Join       (Merge on row index)", "index"),
    ("Broadcast        (Impute with B row 0)", "broadcast"),
]
JOIN_LABELS = [label for label, _ in JOIN_TYPES]
JOIN_CODES = [code for _, code in JOIN_TYPES]


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWFusionNN(widget.OWWidget):
    """Fusion NxM avec sélection du type de jointure."""

    name = "Fusion NxM"
    description = "Merge two Tables on a key or by index/broadcast with configurable join type."
    category = "AAIT - TOOLBOX"
    icon = "icons/owfusion_nm.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owfusion_nm.png"
    priority = 1095

    want_main_area = True
    want_control_area = False

    # Paramètres persistés
    key1_a: Optional[str] = Setting(None)
    key1_b: Optional[str] = Setting(None)
    join_type: str = Setting("full_outer")
    auto_send: bool = Setting(True)

    class Inputs:
        data_a = Input("Table 1", Table)
        data_b = Input("Table 2", Table)

    class Outputs:
        data = Output("Data", Table)

    class Error(widget.OWWidget.Error):
        no_keys = widget.Msg("Sélectionnez une clé pour A et B.")
        fusion_error = widget.Msg("Erreur de fusion: {}")

    def __init__(self) -> None:
        super().__init__()

        self._data_a: Optional[Table] = None
        self._data_b: Optional[Table] = None

        # Charger UI
        self.gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owfusion_nm.ui")
        self.form: QWidget = uic.loadUi(self.gui)
        self.mainArea.layout().addWidget(self.form)
        self.form.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.cb_key1_a: QComboBox = self.form.cb_key1_a
        self.cb_key1_b: QComboBox = self.form.cb_key1_b
        self.cb_join_type: QComboBox = self.form.cb_join_type
        self.btn_send: QPushButton = self.form.pushButton_send
        self.chk_auto: QCheckBox = self.form.checkBox_send

        # Populate join type combo
        self.cb_join_type.addItems(JOIN_LABELS)
        if self.join_type in JOIN_CODES:
            self.cb_join_type.setCurrentIndex(JOIN_CODES.index(self.join_type))

        # Restore auto_send checkbox state and sync Run button
        self.chk_auto.setChecked(self.auto_send)
        self.btn_send.setEnabled(not self.auto_send)

        # Connections
        self.cb_key1_a.currentIndexChanged.connect(self._on_key_changed)
        self.cb_key1_b.currentIndexChanged.connect(self._on_key_changed)
        self.cb_join_type.currentIndexChanged.connect(self._on_join_type_changed)
        self.chk_auto.stateChanged.connect(self._on_auto_send_changed)
        self.btn_send.clicked.connect(self._apply_fusion)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    @Inputs.data_a
    def set_data_a(self, data: Optional[Table]):
        self._data_a = data
        self._update_combos()
        if self.auto_send:
            self._apply_fusion()

    @Inputs.data_b
    def set_data_b(self, data: Optional[Table]):
        self._data_b = data
        self._update_combos()
        if self.auto_send:
            self._apply_fusion()

    def _on_auto_send_changed(self, state: int) -> None:
        self.auto_send = bool(state)
        self.btn_send.setEnabled(not self.auto_send)
        if self.auto_send:
            self._apply_fusion()

    def _on_join_type_changed(self, index: int) -> None:
        self.join_type = JOIN_CODES[index]
        if self.auto_send:
            self._apply_fusion()

    def _on_key_changed(self) -> None:
        """Appelé quand l'utilisateur change une clé."""
        self.key1_a = self.cb_key1_a.currentText() or None
        self.key1_b = self.cb_key1_b.currentText() or None
        if self.auto_send:
            self._apply_fusion()

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_var_names(table: Optional[Table]) -> List[str]:
        if table is None:
            return []
        domain = table.domain
        names = [v.name for v in domain.attributes]
        names.extend(v.name for v in domain.class_vars)
        names.extend(v.name for v in domain.metas)
        seen = set()
        return [n for n in names if not (n in seen or seen.add(n))]

    @staticmethod
    def _get_column(table: Table, var_name: str) -> np.ndarray:
        domain = table.domain
        for i, var in enumerate(domain.attributes):
            if var.name == var_name:
                return table.X[:, i]
        for i, var in enumerate(domain.class_vars):
            if var.name == var_name:
                if table.Y.ndim == 1:
                    return table.Y if i == 0 else np.full(len(table), np.nan)
                return table.Y[:, i]
        for i, var in enumerate(domain.metas):
            if var.name == var_name:
                return table.metas[:, i]
        return np.array([])

    @staticmethod
    def _find_var(table: Table, var_name: str) -> Tuple[Optional[Variable], str, int]:
        domain = table.domain
        for i, var in enumerate(domain.attributes):
            if var.name == var_name:
                return var, "attr", i
        for i, var in enumerate(domain.class_vars):
            if var.name == var_name:
                return var, "class", i
        for i, var in enumerate(domain.metas):
            if var.name == var_name:
                return var, "meta", i
        return None, "", -1

    @staticmethod
    def _is_valid_key(value) -> bool:
        if value is None:
            return False
        try:
            return not np.isnan(value)
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _keys_equal(v1, v2) -> bool:
        if not OWFusionNN._is_valid_key(v1) or not OWFusionNN._is_valid_key(v2):
            return False
        return v1 == v2

    def _update_combos(self) -> None:
        """Met à jour les comboboxes avec les noms de variables."""
        names_a = self._get_var_names(self._data_a)
        names_b = self._get_var_names(self._data_b)

        # Mise à jour combo A
        self.cb_key1_a.blockSignals(True)
        current_a = self.cb_key1_a.currentText()
        self.cb_key1_a.clear()
        self.cb_key1_a.addItems(names_a)
        if self.key1_a and self.key1_a in names_a:
            self.cb_key1_a.setCurrentText(self.key1_a)
        elif current_a in names_a:
            self.cb_key1_a.setCurrentText(current_a)
        elif names_a:
            self.cb_key1_a.setCurrentIndex(0)
        self.cb_key1_a.blockSignals(False)

        # Mise à jour combo B
        self.cb_key1_b.blockSignals(True)
        current_b = self.cb_key1_b.currentText()
        self.cb_key1_b.clear()
        self.cb_key1_b.addItems(names_b)
        if self.key1_b and self.key1_b in names_b:
            self.cb_key1_b.setCurrentText(self.key1_b)
        elif current_b in names_b:
            self.cb_key1_b.setCurrentText(current_b)
        elif names_b:
            self.cb_key1_b.setCurrentIndex(0)
        self.cb_key1_b.blockSignals(False)

    def _apply_fusion(self) -> None:
        """Effectue la fusion des tables."""
        if self._data_a is None or self._data_b is None:
            self.Outputs.data.send(None)
            return

        self.Error.clear()

        key_a = self.cb_key1_a.currentText() or None
        key_b = self.cb_key1_b.currentText() or None
        self.key1_a = key_a
        self.key1_b = key_b

        # Validation uniquement si on nécessite une clé
        if self.join_type not in ["index", "broadcast"] and (not key_a or not key_b):
            self.Error.no_keys()
            self.Outputs.data.send(None)
            return

        try:
            result = self._merge_tables(self._data_a, self._data_b, key_a, key_b, self.join_type)
            self.Outputs.data.send(result)
        except Exception as e:
            self.Error.fusion_error(str(e))
            self.Outputs.data.send(None)

    def _merge_tables(self, table_a: Table, table_b: Table,
                      key_a: Optional[str], key_b: Optional[str], join_type: str) -> Table:

        matches: List[Tuple[int, int]] = []
        rows_a_only: List[int] = []
        rows_b_only: List[int] = []

        if join_type == "index":
            # Concaténation par index de ligne
            len_a, len_b = len(table_a), len(table_b)
            min_len = min(len_a, len_b)
            matches = [(i, i) for i in range(min_len)]
            rows_a_only = list(range(min_len, len_a))
            rows_b_only = list(range(min_len, len_b))

        elif join_type == "broadcast":
            # Imputation de la ligne 0 de la table B sur toutes les lignes de A
            len_a, len_b = len(table_a), len(table_b)
            if len_b > 0:
                matches = [(i, 0) for i in range(len_a)]
                rows_a_only = []
            else:
                matches = []
                rows_a_only = list(range(len_a))
            rows_b_only = []

        else:
            # Jointures traditionnelles par clés
            col_a = self._get_column(table_a, key_a)
            col_b = self._get_column(table_b, key_b)

            index_b: Dict = defaultdict(list)
            for j, val in enumerate(col_b):
                if self._is_valid_key(val):
                    try:
                        index_b[val].append(j)
                    except TypeError:
                        pass

            matched_a = np.zeros(len(col_a), dtype=bool)
            matched_b = np.zeros(len(col_b), dtype=bool)

            for i, val_a in enumerate(col_a):
                if not self._is_valid_key(val_a):
                    continue

                indices_b = index_b.get(val_a)
                if indices_b is None:
                    indices_b = [j for j, val_b in enumerate(col_b) if self._keys_equal(val_a, val_b)]

                for j in indices_b:
                    matches.append((i, j))
                    matched_a[i] = True
                    matched_b[j] = True

            only_a = [i for i, m in enumerate(matched_a) if not m]
            only_b = [j for j, m in enumerate(matched_b) if not m]

            if join_type == "inner":
                rows_a_only, rows_b_only = [], []
            elif join_type == "left":
                rows_a_only, rows_b_only = only_a, []
            elif join_type == "right":
                rows_a_only, rows_b_only = [], only_b
            elif join_type == "left_anti":
                matches, rows_a_only, rows_b_only = [], only_a, []
            elif join_type == "right_anti":
                matches, rows_a_only, rows_b_only = [], [], only_b
            else:  # full_outer
                rows_a_only, rows_b_only = only_a, only_b

        out_domain = self._build_output_domain(table_a, table_b, key_a, key_b, join_type)
        n_rows = len(matches) + len(rows_a_only) + len(rows_b_only)

        if n_rows == 0:
            return Table.from_numpy(out_domain,
                                    np.empty((0, len(out_domain.attributes)), dtype=float),
                                    np.empty((0, len(out_domain.class_vars)), dtype=float),
                                    np.empty((0, len(out_domain.metas)), dtype=object))

        X_out, Y_out, M_out = self._allocate_output_arrays(out_domain, n_rows)

        # Remplir les données
        row = 0

        for i, j in matches:
            self._fill_row(X_out, Y_out, M_out, row, out_domain,
                           table_a, table_b, i, j, key_a, key_b, join_type)
            row += 1
        for i in rows_a_only:
            self._fill_row(X_out, Y_out, M_out, row, out_domain,
                           table_a, table_b, i, None, key_a, key_b, join_type)
            row += 1
        for j in rows_b_only:
            self._fill_row(X_out, Y_out, M_out, row, out_domain,
                           table_a, table_b, None, j, key_a, key_b, join_type)
            row += 1

        result = Table.from_numpy(out_domain, X_out, Y_out, M_out)
        result.name = f"{table_a.name or 'A'} ⋈ {table_b.name or 'B'}"

        return result

    def _build_output_domain(self, table_a: Table, table_b: Table,
                             key_a: Optional[str], key_b: Optional[str], join_type: str) -> Domain:
        # La clé commune n'a pas de sens pour un index ou broadcast merge
        same_key = (key_a == key_b) and (key_a is not None) and join_type not in ["index", "broadcast"]

        names_a = set(self._get_var_names(table_a))
        names_b = set(self._get_var_names(table_b))
        overlap = names_a & names_b

        key_var_b, _, _ = self._find_var(table_b, key_b) if same_key else (None, "", -1)

        def clone_variable(var: Variable, new_name: str, is_merged_key: bool = False) -> Variable:
            if isinstance(var, DiscreteVariable):
                if is_merged_key and isinstance(key_var_b, DiscreteVariable):
                    merged_values = list(var.values)
                    for v in key_var_b.values:
                        if v not in merged_values:
                            merged_values.append(v)
                    return DiscreteVariable(new_name, values=merged_values)
                return DiscreteVariable(new_name, values=var.values)
            return var.__class__(new_name)

        out_attrs: List[Variable] = []
        out_classes: List[Variable] = []
        out_metas: List[Variable] = []

        # Table A
        for cat, vars_list in [("attr", table_a.domain.attributes),
                               ("class", table_a.domain.class_vars),
                               ("meta", table_a.domain.metas)]:
            for var in vars_list:
                is_merged = (same_key and var.name == key_a)
                new_name = var.name + "_A" if (var.name in overlap and not is_merged) else var.name
                cloned = clone_variable(var, new_name, is_merged_key=is_merged)
                if cat == "attr":
                    out_attrs.append(cloned)
                elif cat == "class":
                    out_classes.append(cloned)
                elif cat == "meta":
                    out_metas.append(cloned)

        # Table B
        for cat, vars_list in [("attr", table_b.domain.attributes),
                               ("class", table_b.domain.class_vars),
                               ("meta", table_b.domain.metas)]:
            for var in vars_list:
                if same_key and var.name == key_b:
                    continue
                new_name = var.name + "_B" if var.name in overlap else var.name
                cloned = clone_variable(var, new_name, is_merged_key=False)
                if cat == "attr":
                    out_attrs.append(cloned)
                elif cat == "class":
                    out_classes.append(cloned)
                elif cat == "meta":
                    out_metas.append(cloned)

        return Domain(out_attrs, out_classes, out_metas)

    def _allocate_output_arrays(self, domain: Domain, n_rows: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        X_out = np.full((n_rows, len(domain.attributes)), np.nan, dtype=float)
        Y_out = np.full((n_rows, len(domain.class_vars)), np.nan, dtype=float)
        M_out = np.full((n_rows, len(domain.metas)), np.nan, dtype=object)

        return X_out, Y_out, M_out

    def _fill_row(self, X_out: np.ndarray, Y_out: np.ndarray, M_out: np.ndarray,
                  row_idx: int, out_domain: Domain,
                  table_a: Table, table_b: Table,
                  idx_a: Optional[int], idx_b: Optional[int],
                  key_a: Optional[str], key_b: Optional[str], join_type: str) -> None:

        same_key = (key_a == key_b) and (key_a is not None) and join_type not in ["index", "broadcast"]

        for target_array, vars_list in [(X_out, out_domain.attributes),
                                        (Y_out, out_domain.class_vars),
                                        (M_out, out_domain.metas)]:
            for out_idx, out_var in enumerate(vars_list):
                value = self._get_var_value(out_var, table_a, table_b,
                                            idx_a, idx_b, key_a, key_b, same_key)
                target_array[row_idx, out_idx] = value

    def _get_var_value(self, out_var: Variable, table_a: Table, table_b: Table,
                       idx_a: Optional[int], idx_b: Optional[int],
                       key_a: Optional[str], key_b: Optional[str], same_key: bool):
        var_name = out_var.name

        # Déterminer si c'est une variable de A ou B
        if same_key and var_name == key_a:
            if idx_a is not None:
                table, idx, source_name = table_a, idx_a, key_a
            else:
                table, idx, source_name = table_b, idx_b, key_b
        elif var_name.endswith("_A"):
            source_name = var_name[:-2]
            table, idx = table_a, idx_a
        elif var_name.endswith("_B"):
            source_name = var_name[:-2]
            table, idx = table_b, idx_b
        else:
            # Pas de suffixe: chercher d'abord dans A, puis dans B
            source_name = var_name
            var_a, _, _ = self._find_var(table_a, source_name)
            if var_a is not None:
                table, idx = table_a, idx_a
            else:
                table, idx = table_b, idx_b

        # Si pas d'index, retourner None
        if idx is None:
            return None

        # Extraire la valeur
        var, vtype, vidx = self._find_var(table, source_name)
        if var is None:
            return None

        # Récupérer la valeur brute
        raw_value = np.nan
        if vtype == "attr":
            raw_value = table.X[idx, vidx]
        elif vtype == "class":
            if table.Y.ndim == 1:
                raw_value = table.Y[idx] if vidx == 0 else np.nan
            else:
                raw_value = table.Y[idx, vidx]
        elif vtype == "meta":
            raw_value = table.metas[idx, vidx]

        if same_key and var_name == key_a and table is table_b and isinstance(out_var, DiscreteVariable):
            if isinstance(var, DiscreteVariable) and isinstance(raw_value, (int, float)) and not np.isnan(raw_value):
                try:
                    str_val = var.values[int(raw_value)]
                    return float(out_var.values.index(str_val))
                except (IndexError, ValueError):
                    pass

        return raw_value


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = OWFusionNN()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()