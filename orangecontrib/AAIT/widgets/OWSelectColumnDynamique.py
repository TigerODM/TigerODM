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
    """Retourne les listes (attributs, classes, métas) d'une table.

    - Si la table est ``None``, renvoie trois listes vides.

    Paramètres
    ----------
    table: Orange.data.Table | None
        Table Orange en entrée.

    Retour
    ------
    tuple[list[Variable], list[Variable], list[Variable]]
        Listes des variables d'attributs, de classes et de métadonnées.
    """
    if table is None:
        return [], [], []
    d = table.domain
    return list(d.attributes), list(d.class_vars), list(d.metas)


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWSelectColumnDynamique(widget.OWWidget):
    """Widget pour filtrer des colonnes selon des noms fournis.

    Deux entrées permettent de piloter la sélection:
    - « Columns Strict (names) »: sélection par noms exacts;
    - « Columns Contains (names) »: sélection par inclusion (sans casse).
    """
    name = "Select Columns Dynamic"
    description = "Filter Data columns based on two inputs: exact names and ‘contient’ names."
    category = "AAIT - TOOLBOX"
    icon = "icons/owselectcolumndynamique.png"  # placeholder icon
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owselectcolumndynamique.png"  # dev icon if available
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

    def __init__(self) -> None:
        """Initialise le widget et charge l'UI (si présente).

        - Prépare les références aux tables d'entrée (données, colonnes strictes,
          colonnes par inclusion).
        - Ajoute la forme au `mainArea`.
        """
        super().__init__()
        self.gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owselect_column_dynamic.ui")

        self._data: Optional[Orange.data.Table] = None
        self._columns_driver_strict: Optional[Orange.data.Table] = None
        self._columns_driver_contains: Optional[Orange.data.Table] = None
        self.form: QWidget = uic.loadUi(self.gui)
        self.mainArea.layout().addWidget(self.form)
        self.form.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Pas d'UI interactive: le comportement est entièrement piloté par les données

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    # ---------- Inputs ----------
    @Inputs.data
    def set_data(self, data: Optional[Orange.data.Table]) -> None:
        """Réceptionne la table de données principale puis applique le filtre.

        Paramètres
        ----------
        data: Orange.data.Table | None
            Table à filtrer.
        """
        self._data = data
        self._apply()

    @Inputs.columns_strict
    def set_columns_strict(self, data: Optional[Orange.data.Table]) -> None:
        """Réceptionne les noms de colonnes à faire correspondre strictement.

        Attendu: exactement une variable méta `StringVariable` contenant les noms.
        Applique ensuite le filtre.
        """
        self._columns_driver_strict = data
        self._apply()

    @Inputs.columns_contains
    def set_columns_contains(self, data: Optional[Orange.data.Table]) -> None:
        """Réceptionne les motifs de noms de colonnes (recherche par inclusion).

        Attendu: exactement une variable méta `StringVariable` contenant les motifs
        (comparaison insensible à la casse). Applique ensuite le filtre.
        """
        self._columns_driver_contains = data
        self._apply()

    # ---------- Helper ----------

    def _collect_names_from_table(self, df: Optional[Orange.data.Table]) -> Set[str]:
        """Extrait l'ensemble des noms depuis une table de pilotage.

        La table doit contenir exactement une colonne méta de type
        `StringVariable`. Chaque ligne fournit un nom ou un motif.

        Paramètres
        ----------
        df: Orange.data.Table | None
            Table contenant une unique méta chaîne.

        Retour
        ------
        set[str]
            Ensemble des valeurs (chaînes) extraites.
        """
        names: Set[str] = set()
        if df is None:
            return names
        # N'autoriser qu'une unique variable méta chaîne (même politique que SelectRowsDynamic)
        total_columns = len(df.domain.attributes) + len(df.domain.class_vars) + len(df.domain.metas)
        if total_columns != 1:
            return names
        if len(df.domain.metas) != 1:
            return names
        if not isinstance(df.domain.metas[0], Orange.data.StringVariable):
            return names
        for row in df:
            val = row.metas[0]
            if val is None:
                continue
            names.add(str(val))
        return names

    def _sync_selection_from_driver(self) -> Set[str]:
        """Fusionne les noms en provenance des deux entrées.

        Méthode conservée pour compatibilité si appelée à l'extérieur.

        Retour
        ------
        set[str]
            Union des noms stricts et des motifs « contient ».
        """
        s1 = self._collect_names_from_table(self._columns_driver_strict)
        s2 = self._collect_names_from_table(self._columns_driver_contains)
        return s1.union(s2)

    # ---------- Core ----------
    def _apply(self) -> None:
        """Applique le filtrage des colonnes et émet la table filtrée.

        - Récupère les listes de noms stricts et de motifs « contient »;
        - Sélectionne les variables du domaine correspondant aux critères;
        - Construit une nouvelle table si au moins une variable correspond;
        - Émet la sortie « Filtered Data ».
        """
        # S'assurer que des données sont présentes
        data = self._data
        if data is None:
            self.Outputs.data.send(None)
            self.Outputs.unmatching.send(None)
            return

        # Rassembler les noms sélectionnés (depuis les tables de pilotage)
        # Noms stricts et motifs « contient » (comparaison insensible à la casse)
        strict_names = {n.strip() for n in self._collect_names_from_table(self._columns_driver_strict) if n and n.strip()}
        contains_patterns = {n.strip() for n in self._collect_names_from_table(self._columns_driver_contains) if n and n.strip()}
        patterns_l = [n.lower() for n in contains_patterns]

        attrs, class_vars, metas = _all_variables(data)

        def match(vname: str) -> bool:
            if vname in strict_names:
                return True
            vn = vname.lower()
            return any(pat in vn for pat in patterns_l)

        selected_attrs = [v for v in attrs if match(v.name)]
        selected_class = [v for v in class_vars if match(v.name)]
        selected_metas = [v for v in metas if match(v.name)]

        unselected_attrs = [v for v in attrs if not match(v.name)]
        unselected_class = [v for v in class_vars if not match(v.name)]
        unselected_metas = [v for v in metas if not match(v.name)]

        # Construire la table filtrée si nécessaire
        if selected_attrs or selected_class or selected_metas:
            dom_sel = Orange.data.Domain(selected_attrs, selected_class, selected_metas)
            tbl_sel = Orange.data.Table.from_table(dom_sel, data)
        else:
            tbl_sel = None

        # Construire la table non-filtrée (complément) si nécessaire
        if unselected_attrs or unselected_class or unselected_metas:
            dom_unsel = Orange.data.Domain(unselected_attrs, unselected_class, unselected_metas)
            tbl_unsel = Orange.data.Table.from_table(dom_unsel, data)
        else:
            tbl_unsel = None

        self.Outputs.data.send(tbl_sel)
        self.Outputs.unmatching.send(tbl_unsel)

    class Error(widget.OWWidget.Error):
        pass


if __name__ == "__main__":
    # Exécution autonome pour tester le widget manuellement
    app = QApplication(sys.argv)
    w = OWSelectColumnDynamique()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()