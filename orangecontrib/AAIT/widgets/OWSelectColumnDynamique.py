"""Widget Orange pour sélectionner dynamiquement des colonnes.

Ce module fournit un widget qui filtre les colonnes d'une table Orange
en fonction de deux flux d'entrée optionnels:
- un flux de noms de colonnes à faire correspondre de manière stricte;
- un flux de noms utilisés comme motifs « contient » (insensible à la casse).

Le widget renvoie une nouvelle table ne contenant que les variables
dont le nom correspond à l'un ou l'autre des critères.
"""

import sys

import Orange
import Orange.data
import os
from AnyQt.QtWidgets import QApplication
from AnyQt.QtWidgets import (
    QWidget,
    QSizePolicy,
)
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from typing import Optional, Set, Tuple, List
from AnyQt.QtCore import QTimer

# Import conditionnel pour reproduire l'arborescence des add-ons Orange
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic  # noqa: F401 (kept for consistency)
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic  # type: ignore  # noqa: F401
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file  # type: ignore
    from orangecontrib.AAIT.utils import help_management


def _all_variables(table: Optional[Orange.data.Table]) -> Tuple[List[Orange.data.Variable], List[Orange.data.Variable], List[Orange.data.Variable]]:
    if table is None:
        return [], [], []
    d = table.domain
    return list(d.attributes), list(d.class_vars), list(d.metas)


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWSelectColumnDynamique(widget.OWWidget):
    name = "Select Columns Dynamic"
    description = "Filter Data columns based on two inputs: exact names and ‘contient’ names."
    category = "AAIT - TOOLBOX"
    icon = "icons/owselectcolumndynamique.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owselectcolumndynamique.png"
    priority = 1061

    want_main_area = True
    want_control_area = False

    class Inputs:
        data = Input("Data", Orange.data.Table)
        columns_strict = Input("Columns Strict (names)", Orange.data.Table)
        columns_contains = Input("Columns Contains (names)", Orange.data.Table)

    class Outputs:
        data = Output("Filtered Data", Orange.data.Table)
        unmatching = Output("Unmatched Data", Orange.data.Table)

    class Error(widget.OWWidget.Error):
        invalid_columns_strict = widget.Msg(
            "Input 'Columns Strict (names)' must contain exactly 1 column, and this column must be a StringVariable or a DiscreteVariable."
        )
        invalid_columns_contains = widget.Msg(
            "Input 'Columns Contains (names)' must contain exactly 1 column, and this column must be a StringVariable or a DiscreteVariable."
        )

    def __init__(self) -> None:
        super().__init__()
        self.gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owselect_column_dynamic.ui")

        self._data: Optional[Orange.data.Table] = None
        self._columns_driver_strict: Optional[Orange.data.Table] = None
        self._columns_driver_contains: Optional[Orange.data.Table] = None
        self.form: QWidget = uic.loadUi(self.gui)
        self.mainArea.layout().addWidget(self.form)
        self.form.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    # ---------- Inputs ----------
    @Inputs.data
    def set_data(self, data: Optional[Orange.data.Table]) -> None:
        self._data = data
        self._apply()

    @Inputs.columns_strict
    def set_columns_strict(self, data: Optional[Orange.data.Table]) -> None:
        self._columns_driver_strict = data
        self._apply()

    @Inputs.columns_contains
    def set_columns_contains(self, data: Optional[Orange.data.Table]) -> None:
        self._columns_driver_contains = data
        self._apply()

    # ---------- Helper ----------
    def _get_single_driver_var(self, df: Optional[Orange.data.Table]) -> Optional[Orange.data.Variable]:
        if df is None:
            return None

        all_vars = list(df.domain.attributes) + list(df.domain.class_vars) + list(df.domain.metas)
        if len(all_vars) != 1:
            return None

        var = all_vars[0]
        if not isinstance(var, (Orange.data.StringVariable, Orange.data.DiscreteVariable)):
            return None

        return var

    def _is_valid_driver_table(self, df: Optional[Orange.data.Table]) -> bool:
        if df is None:
            return True
        return self._get_single_driver_var(df) is not None

    def _collect_names_from_table(self, df: Optional[Orange.data.Table]) -> Set[str]:
        names: Set[str] = set()
        if df is None:
            return names

        var = self._get_single_driver_var(df)
        if var is None:
            return names

        for row in df:
            val = row[var]
            if val is None:
                continue
            sval = str(val).strip()
            if sval and sval != "?":
                names.add(sval)
        return names

    def _collect_names_list_from_table(self, df: Optional[Orange.data.Table]) -> List[str]:
        names: List[str] = []
        if df is None:
            return names

        var = self._get_single_driver_var(df)
        if var is None:
            return names

        seen = set()
        for row in df:
            val = row[var]
            if val is None:
                continue
            sval = str(val).strip()
            if sval and sval != "?" and sval not in seen:
                names.append(sval)
                seen.add(sval)
        return names

    def _sync_selection_from_driver(self) -> Set[str]:
        s1 = self._collect_names_from_table(self._columns_driver_strict)
        s2 = self._collect_names_from_table(self._columns_driver_contains)
        return s1.union(s2)

    # ---------- Core ----------
    def _apply(self) -> None:
        self.Error.invalid_columns_strict.clear()
        self.Error.invalid_columns_contains.clear()

        if not self._is_valid_driver_table(self._columns_driver_strict):
            self.Error.invalid_columns_strict()
            self.Outputs.data.send(None)
            self.Outputs.unmatching.send(None)
            return

        if not self._is_valid_driver_table(self._columns_driver_contains):
            self.Error.invalid_columns_contains()
            self.Outputs.data.send(None)
            self.Outputs.unmatching.send(None)
            return

        data = self._data
        if data is None:
            self.Outputs.data.send(None)
            self.Outputs.unmatching.send(None)
            return

        strict_names_list = [n.strip() for n in self._collect_names_list_from_table(self._columns_driver_strict) if n and n.strip()]
        contains_patterns_list = [n.strip() for n in self._collect_names_list_from_table(self._columns_driver_contains) if n and n.strip()]

        strict_names = set(strict_names_list)

        attrs, class_vars, metas = _all_variables(data)

        def match(vname: str) -> bool:
            if vname in strict_names:
                return True
            vn = vname.lower()
            for pat in contains_patterns_list:
                if pat.lower() in vn:
                    return True
            return False

        def get_order_key(vname: str):
            for i, name in enumerate(strict_names_list):
                if vname == name:
                    return (0, i, vname.lower())

            vn = vname.lower()
            for i, pat in enumerate(contains_patterns_list):
                if pat.lower() in vn:
                    return (1, i, vname.lower())

            return (999999, 999999, vname.lower())

        selected_attrs = [v for v in attrs if match(v.name)]
        selected_class = [v for v in class_vars if match(v.name)]
        selected_metas = [v for v in metas if match(v.name)]

        selected_attrs.sort(key=lambda v: get_order_key(v.name))
        selected_class.sort(key=lambda v: get_order_key(v.name))
        selected_metas.sort(key=lambda v: get_order_key(v.name))

        unselected_attrs = [v for v in attrs if v not in selected_attrs]
        unselected_class = [v for v in class_vars if v not in selected_class]
        unselected_metas = [v for v in metas if v not in selected_metas]

        if selected_attrs or selected_class or selected_metas:
            dom_sel = Orange.data.Domain(selected_attrs, selected_class, selected_metas)
            tbl_sel = Orange.data.Table.from_table(dom_sel, data)
        else:
            tbl_sel = None

        if unselected_attrs or unselected_class or unselected_metas:
            dom_unsel = Orange.data.Domain(unselected_attrs, unselected_class, unselected_metas)
            tbl_unsel = Orange.data.Table.from_table(dom_unsel, data)
        else:
            tbl_unsel = None

        self.Outputs.data.send(tbl_sel)
        self.Outputs.unmatching.send(tbl_unsel)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = OWSelectColumnDynamique()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()