import os
import sys
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

import numpy as np
from Orange.widgets import widget
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Table, Domain, Variable, DiscreteVariable

from AnyQt.QtWidgets import (
    QApplication,
    QWidget,
    QComboBox,
    QPushButton,
    QCheckBox,
    QSizePolicy,
)
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic  # noqa: F401
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import (
        apply_modification_from_python_file,
    )
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import (
        apply_modification_from_python_file,
    )
    from orangecontrib.AAIT.utils import help_management

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
Source = tuple


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

        self.cb_join_type.addItems(JOIN_LABELS)
        if self.join_type in JOIN_CODES:
            self.cb_join_type.setCurrentIndex(JOIN_CODES.index(self.join_type))

        self.chk_auto.setChecked(self.auto_send)
        self.btn_send.setEnabled(not self.auto_send)

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
        self.key1_a = self.cb_key1_a.currentText() or None
        self.key1_b = self.cb_key1_b.currentText() or None
        if self.auto_send:
            self._apply_fusion()

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _domain_parts(table: Table):
        d = table.domain
        return [("attr", d.attributes), ("class", d.class_vars), ("meta", d.metas)]

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
        if isinstance(value, str):
            return value != ""
        try:
            return not np.isnan(value)
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _keys_equal(v1, v2) -> bool:
        if not OWFusionNN._is_valid_key(v1) or not OWFusionNN._is_valid_key(v2):
            return False
        return v1 == v2

    @staticmethod
    def _missing(var: Variable):
        """Valeur manquante selon le type Orange : "" pour du texte, NaN sinon."""
        return "" if var.is_string else np.nan

    @staticmethod
    def _with_name(var: Variable, new_name: str) -> Variable:
        """Même variable sous un autre nom (Variable.name est en lecture seule)."""
        if hasattr(var, "renamed"):
            return var.renamed(new_name)
        return var.copy(name=new_name)

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

    def _key_values(self, table: Table, var_name: str) -> np.ndarray:
        """Valeurs de la clé, en libellés pour une variable catégorielle.

        Les codes internes (0, 1, 2…) dépendent de l'ordre des modalités de
        chaque table : on compare donc les libellés, pas les codes.
        """
        values = self._get_column(table, var_name)
        var = self._find_var(table, var_name)[0]
        if var is not None and var.is_discrete:
            return np.array(
                [None if (v is None or np.isnan(v)) else var.values[int(v)] for v in values],
                dtype=object,
            )
        return values

    def _match_rows(self, table_a: Table, table_b: Table,
                    key_a: Optional[str], key_b: Optional[str], join_type: str):
        """Calcule les paires (i, j) appariées et les lignes orphelines de A et B."""
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
            return matches, rows_a_only, rows_b_only

        if join_type == "broadcast":
            if len(table_b) > 0:
                matches = [(i, 0) for i in range(len(table_a))]
            else:
                rows_a_only = list(range(len(table_a)))
            return matches, rows_a_only, rows_b_only

        col_a = self._key_values(table_a, key_a)
        col_b = self._key_values(table_b, key_b)

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
            return matches, [], []
        if join_type == "left":
            return matches, only_a, []
        if join_type == "right":
            return matches, [], only_b
        if join_type == "left_anti":
            return [], only_a, []
        if join_type == "right_anti":
            return [], [], only_b
        return matches, only_a, only_b  # full_outer

    def _merge_tables(self, table_a: Table, table_b: Table,
                      key_a: Optional[str], key_b: Optional[str], join_type: str) -> Table:
        matches, rows_a_only, rows_b_only = self._match_rows(table_a, table_b, key_a, key_b, join_type)

        # Pour chaque ligne de sortie : indice de la ligne source dans A et dans B (-1 = absente)
        idx_a = np.array([i for i, _ in matches] + rows_a_only + [-1] * len(rows_b_only), dtype=int)
        idx_b = np.array([j for _, j in matches] + [-1] * len(rows_a_only) + rows_b_only, dtype=int)
        n_rows = len(idx_a)

        out_domain, sources = self._build_output_domain(table_a, table_b, key_a, key_b, join_type)
        out_vars = list(out_domain.attributes) + list(out_domain.class_vars) + list(out_domain.metas)

        columns = [self._output_column(src, out_var, table_a, table_b, idx_a, idx_b)
                   for out_var, src in zip(out_vars, sources)]

        n_x = len(out_domain.attributes)
        n_y = len(out_domain.class_vars)

        def stack(cols, dtype):
            if not cols:
                return np.empty((n_rows, 0), dtype=dtype)
            return np.column_stack(cols).astype(dtype)

        X = stack(columns[:n_x], float)
        Y = stack(columns[n_x:n_x + n_y], float) if n_y else None
        M = stack(columns[n_x + n_y:], object)

        result = Table.from_numpy(out_domain, X, Y, M)
        result.name = f"{table_a.name or 'A'} ⋈ {table_b.name or 'B'}"
        return result

    def _build_output_domain(self, table_a: Table, table_b: Table,
                             key_a: Optional[str], key_b: Optional[str],
                             join_type: str) -> Tuple[Domain, List[Source]]:
        """Construit le domaine de sortie et, en parallèle, la source de chaque colonne.

        Les variables d'origine sont réutilisées telles quelles ; elles ne sont
        renommées (suffixe _A / _B) qu'en cas de conflit de nom.
        """
        same_key = (key_a == key_b) and (key_a is not None) and join_type not in ["index", "broadcast"]

        overlap = set(self._get_var_names(table_a)) & set(self._get_var_names(table_b))

        key_var_a = self._find_var(table_a, key_a)[0] if same_key else None
        key_var_b = self._find_var(table_b, key_b)[0] if same_key else None

        parts: Dict[str, Tuple[List[Variable], List[Source]]] = {
            "attr": ([], []), "class": ([], []), "meta": ([], []),
        }

        def add(cat: str, out_var: Variable, source: Source) -> None:
            parts[cat][0].append(out_var)
            parts[cat][1].append(source)

        for cat, vars_list in self._domain_parts(table_a):
            for var in vars_list:
                if same_key and var.name == key_a:
                    add(cat, self._merged_key_var(key_var_a, key_var_b), ("key", key_var_a, key_var_b))
                elif var.name in overlap:
                    add(cat, self._with_name(var, var.name + "_A"), ("A", var))
                else:
                    add(cat, var, ("A", var))

        for cat, vars_list in self._domain_parts(table_b):
            for var in vars_list:
                if same_key and var.name == key_b:
                    continue
                if var.name in overlap:
                    add(cat, self._with_name(var, var.name + "_B"), ("B", var))
                else:
                    add(cat, var, ("B", var))

        domain = Domain(parts["attr"][0], parts["class"][0], parts["meta"][0])
        sources = parts["attr"][1] + parts["class"][1] + parts["meta"][1]
        return domain, sources

    @staticmethod
    def _merged_key_var(var_a: Variable, var_b: Variable) -> Variable:
        """Variable de la clé commune : celle de A, élargie aux modalités de B si besoin."""
        if isinstance(var_a, DiscreteVariable) and isinstance(var_b, DiscreteVariable):
            extra = [v for v in var_b.values if v not in var_a.values]
            if extra:
                return DiscreteVariable(var_a.name, values=list(var_a.values) + extra)
        return var_a

    def _output_column(self, source: Source, out_var: Variable,
                       table_a: Table, table_b: Table,
                       idx_a: np.ndarray, idx_b: np.ndarray) -> np.ndarray:
        missing = self._missing(out_var)
        tag = source[0]

        if tag == "A":
            src = source[1]
            values = self._convert(self._get_column(table_a, src.name), src, out_var)
            return self._take(values, idx_a, missing)

        if tag == "B":
            src = source[1]
            values = self._convert(self._get_column(table_b, src.name), src, out_var)
            return self._take(values, idx_b, missing)

        # Clé commune : valeur de A si la ligne vient de A, sinon valeur de B
        _, var_a, var_b = source
        col = self._take(self._convert(self._get_column(table_a, var_a.name), var_a, out_var), idx_a, missing)
        col_b = self._take(self._convert(self._get_column(table_b, var_b.name), var_b, out_var), idx_b, missing)
        from_b = idx_a < 0
        col[from_b] = col_b[from_b]
        return col

    @staticmethod
    def _take(values: np.ndarray, idx: np.ndarray, missing) -> np.ndarray:
        """values[idx], avec `missing` là où idx == -1."""
        dtype = object if (isinstance(missing, str) or values.dtype == object) else float
        out = np.full(len(idx), missing, dtype=dtype)
        mask = idx >= 0
        if mask.any():
            out[mask] = values[idx[mask]]
        return out

    @staticmethod
    def _convert(values: np.ndarray, src_var: Variable, out_var: Variable) -> np.ndarray:
        """Exprime les valeurs de src_var dans le codage de out_var.

        Utile surtout pour la clé fusionnée, quand A et B n'ont pas le même type
        ou pas les mêmes modalités.
        """
        if out_var.is_discrete:
            out_values = list(out_var.values)
            if src_var.is_discrete:
                if list(src_var.values) == out_values:
                    return values
                lookup = {i: out_values.index(v) for i, v in enumerate(src_var.values) if v in out_values}
                res = np.full(len(values), np.nan)
                for k, v in enumerate(values):
                    if v is not None and not np.isnan(v):
                        res[k] = lookup.get(int(v), np.nan)
                return res
            res = np.full(len(values), np.nan)
            for k, v in enumerate(values):
                s = str(v)
                if s in out_values:
                    res[k] = out_values.index(s)
            return res

        if src_var.is_discrete and out_var.is_string:
            return np.array(
                ["" if (v is None or np.isnan(v)) else src_var.values[int(v)] for v in values],
                dtype=object,
            )

        return values


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = OWFusionNN()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()