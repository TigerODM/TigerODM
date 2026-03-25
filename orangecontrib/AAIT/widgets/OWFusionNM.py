import os
import sys
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

import numpy as np
from Orange.data import Table, Domain, Variable, DiscreteVariable, StringVariable
from Orange.widgets import widget
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output

from AnyQt.QtWidgets import (
    QApplication,
    QWidget,
    QComboBox,
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


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWFusionNN(widget.OWWidget):
    """Fusion NxM simplifiée avec gestion correcte des types Orange."""

    name = "Fusion NxM"
    description = "Merge two Tables on a key; add the non-matched rows."
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

        self.cb_key1_a: QComboBox = getattr(self.form, "cb_key1_a")
        self.cb_key1_b: QComboBox = getattr(self.form, "cb_key1_b")
        self.cb_key1_a.currentIndexChanged.connect(self._on_key_changed)
        self.cb_key1_b.currentIndexChanged.connect(self._on_key_changed)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    @Inputs.data_a
    def set_data_a(self, data: Optional[Table]):
        self._data_a = data
        self._update_combos()
        self._apply_fusion()

    @Inputs.data_b
    def set_data_b(self, data: Optional[Table]):
        self._data_b = data
        self._update_combos()
        self._apply_fusion()

    @staticmethod
    def _get_var_names(table: Optional[Table]) -> List[str]:
        """Retourne les noms de toutes les variables d'une table."""
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
        """Extrait une colonne d'une table par nom de variable."""
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
        """Trouve une variable et retourne (variable, type, index)."""
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
        """Vérifie si une valeur peut être utilisée comme clé de fusion."""
        if value is None:
            return False
        try:
            return not np.isnan(value)
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _keys_equal(v1, v2) -> bool:
        """Compare deux valeurs de clés."""
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

    def _on_key_changed(self) -> None:
        """Appelé quand l'utilisateur change une clé."""
        self.key1_a = self.cb_key1_a.currentText() or None
        self.key1_b = self.cb_key1_b.currentText() or None
        self._apply_fusion()

    def _apply_fusion(self) -> None:
        """Effectue la fusion des tables."""
        # Vérifications préliminaires
        if self._data_a is None or self._data_b is None:
            self.Outputs.data.send(None)
            return

        self.Error.clear()

        if not self.key1_a or not self.key1_b:
            self.Error.no_keys()
            self.Outputs.data.send(None)
            return

        try:
            result = self._merge_tables(self._data_a, self._data_b, self.key1_a, self.key1_b)
            self.Outputs.data.send(result)
        except Exception as e:
            self.Error.fusion_error(str(e))
            self.Outputs.data.send(None)

    def _merge_tables(self, table_a: Table, table_b: Table, key_a: str, key_b: str) -> Table:
        """Fusionne deux tables sur leurs clés."""
        # Extraire les colonnes de clés
        col_a = self._get_column(table_a, key_a)
        col_b = self._get_column(table_b, key_b)

        # Construire l'index B: valeur -> liste d'indices
        index_b: Dict[any, List[int]] = defaultdict(list)
        for j, val in enumerate(col_b):
            if self._is_valid_key(val):
                try:
                    index_b[val].append(j)
                except TypeError:
                    # Non-hashable, on gérera avec fallback
                    pass

        # Trouver les correspondances
        matches: List[Tuple[int, int]] = []
        matched_a = np.zeros(len(col_a), dtype=bool)
        matched_b = np.zeros(len(col_b), dtype=bool)

        for i, val_a in enumerate(col_a):
            if not self._is_valid_key(val_a):
                continue

            # Chercher dans l'index
            indices_b = index_b.get(val_a)
            if indices_b is None:
                # Fallback: comparaison directe
                indices_b = [j for j, val_b in enumerate(col_b) if self._keys_equal(val_a, val_b)]

            for j in indices_b:
                matches.append((i, j))
                matched_a[i] = True
                matched_b[j] = True

        # Lignes non appariées
        only_a = [i for i, m in enumerate(matched_a) if not m]
        only_b = [j for j, m in enumerate(matched_b) if not m]

        # Construire le domaine de sortie
        out_domain = self._build_output_domain(table_a, table_b, key_a, key_b)

        # Construire les données de sortie
        n_rows = len(matches) + len(only_a) + len(only_b)
        X_out, Y_out, M_out = self._allocate_output_arrays(out_domain, n_rows)

        # Remplir les données
        row = 0

        # Lignes appariées (A + B)
        for i, j in matches:
            self._fill_row(X_out, Y_out, M_out, row, out_domain, table_a, table_b, i, j, key_a, key_b)
            row += 1

        # Lignes A uniquement
        for i in only_a:
            self._fill_row(X_out, Y_out, M_out, row, out_domain, table_a, table_b, i, None, key_a, key_b)
            row += 1

        # Lignes B uniquement
        for j in only_b:
            self._fill_row(X_out, Y_out, M_out, row, out_domain, table_a, table_b, None, j, key_a, key_b)
            row += 1

        # Créer la table de sortie
        result = Table.from_numpy(out_domain, X_out, Y_out, M_out)
        result.name = f"{table_a.name or 'A'} ⋈ {table_b.name or 'B'}"

        return result

    def _build_output_domain(self, table_a: Table, table_b: Table,
                            key_a: str, key_b: str) -> Domain:
        """Construit le domaine de sortie avec toutes les variables en StringVariable."""
        same_key = (key_a == key_b)

        # Collecter tous les noms pour détecter les overlaps
        names_a = set(self._get_var_names(table_a))
        names_b = set(self._get_var_names(table_b))
        overlap = names_a & names_b

        out_metas: List[Variable] = []

        # Ajouter variables de A (toutes en metas/string)
        for var in list(table_a.domain.attributes) + list(table_a.domain.class_vars) + list(table_a.domain.metas):
            if var.name in overlap and not (same_key and var.name == key_a):
                out_metas.append(StringVariable(var.name + "_A"))
            else:
                out_metas.append(StringVariable(var.name))

        # Ajouter variables de B (toutes en metas/string)
        for var in list(table_b.domain.attributes) + list(table_b.domain.class_vars) + list(table_b.domain.metas):
            if same_key and var.name == key_b:
                continue  # Éviter duplication de la clé
            if var.name in overlap:
                out_metas.append(StringVariable(var.name + "_B"))
            else:
                out_metas.append(StringVariable(var.name))

        # Tout en metas (pas d'attributes ni de class_vars)
        return Domain([], [], out_metas)

    def _rename_var(self, var: Variable, suffix: str) -> Variable:
        """Crée une nouvelle variable avec un suffixe (toujours en StringVariable)."""
        new_name = var.name + suffix
        # Toujours retourner une StringVariable pour éviter les problèmes de types
        return StringVariable(new_name)

    def _allocate_output_arrays(self, domain: Domain, n_rows: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Alloue les arrays de sortie (tout en metas/string)."""
        # Pas d'attributes ni de class_vars, tout est en metas
        X_out = np.empty((n_rows, 0), dtype=float)
        Y_out = np.empty((n_rows, 0), dtype=float)
        M_out = np.full((n_rows, len(domain.metas)), "", dtype=object)

        return X_out, Y_out, M_out

    def _fill_row(self, X_out: np.ndarray, Y_out: np.ndarray, M_out: np.ndarray,
                  row_idx: int, out_domain: Domain,
                  table_a: Table, table_b: Table,
                  idx_a: Optional[int], idx_b: Optional[int],
                  key_a: str, key_b: str) -> None:
        """Remplit une ligne de sortie avec les données de A et/ou B (tout en metas/string)."""
        same_key = (key_a == key_b)

        # Tout est en metas maintenant
        for out_idx, out_var in enumerate(out_domain.metas):
            value = self._get_var_value(out_var, table_a, table_b, idx_a, idx_b, key_a, key_b, same_key, "meta")
            # Convertir en string
            if value is None or (isinstance(value, float) and np.isnan(value)):
                M_out[row_idx, out_idx] = ""
            elif isinstance(value, (list, tuple, np.ndarray)):
                M_out[row_idx, out_idx] = str(value)
            else:
                M_out[row_idx, out_idx] = str(value)

    def _get_var_value(self, out_var: Variable, table_a: Table, table_b: Table,
                      idx_a: Optional[int], idx_b: Optional[int],
                      key_a: str, key_b: str, same_key: bool, var_type: str):
        """Récupère la valeur d'une variable depuis la table source appropriée."""
        var_name = out_var.name

        # Déterminer si c'est une variable de A ou B
        if var_name.endswith("_A"):
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
        raw_value = None
        if vtype == "attr":
            raw_value = table.X[idx, vidx]
        elif vtype == "class":
            if table.Y.ndim == 1:
                raw_value = table.Y[idx] if vidx == 0 else np.nan
            else:
                raw_value = table.Y[idx, vidx]
        elif vtype == "meta":
            raw_value = table.metas[idx, vidx]

        # Convertir les variables discrètes en leurs noms de valeurs
        if isinstance(var, DiscreteVariable) and raw_value is not None:
            try:
                if not np.isnan(raw_value):
                    value_idx = int(raw_value)
                    if 0 <= value_idx < len(var.values):
                        return var.values[value_idx]
            except (ValueError, TypeError):
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
