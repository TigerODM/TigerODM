import os
import sys
import platform
import numpy as np
import datetime as datetime
import Orange
import Orange.data
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import (
    QApplication, QWidget, QCheckBox, QVBoxLayout, QSizePolicy,
    QPushButton, QHBoxLayout, QScrollArea
)
from AnyQt.QtCore import QTimer

# Conditional imports to mirror Orange add-on layout
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management

try:
    import importlib.metadata as importlib_metadata
except Exception:  # pragma: no cover
    import importlib_metadata  # type: ignore


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWAddColumns(widget.OWWidget):
    name = "Add columns"
    description = "Add selected columns (OS/Python/Orange/packages, etc.) to an input Table."
    category = "AAIT - TOOLBOX"
    icon = "icons/owenvinfo.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owenvinfo.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owaddcolumns.ui")
    priority = 1094

    want_main_area = True
    want_control_area = False

    # Settings pour sauvegarder l'état des cases à cocher
    selected_columns = Setting([])

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    def __init__(self):
        super().__init__()

        # 1) Charger ton .ui d’origine dans un enfant
        self.form: QWidget = uic.loadUi(self.gui)
        self.mainArea.layout().addWidget(self.form)
        self.form.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(470, 300)

        # 2) Récupérer ce que le .ui pourrait contenir
        self.Description = getattr(self.form, "Description", None)
        self.varsLayout: QVBoxLayout = getattr(self.form, "varsLayout", None)
        self.btnSelectAll = getattr(self.form, "btnSelectAll", None)
        self.btnClearAll = getattr(self.form, "btnClearAll", None)
        self.btnApply = getattr(self.form, "btnApply", None)

        # 3) Si la zone de sélection n'existe pas dans le .ui d’origine, on la crée
        if self.varsLayout is None:
            self._build_fallback_selector_panel()

        # 4) Etat interne
        self._var_checks: dict[str, QCheckBox] = {}
        self._current_data: Orange.data.Table | None = None

        # 5) Peupler et connecter
        self._available_keys, _ = self._collect()

        current_keys = set(self._available_keys)
        saved_keys = set(self.selected_columns or [])

        # Colonnes cochées dans les anciens settings mais supprimées du code
        obsolete_checked = saved_keys - current_keys

        # Erreur UNIQUEMENT si une ancienne colonne cochée n'existe plus
        if obsolete_checked:
            self.error(
                f"Settings obsolètes détectés. "
                f"Colonnes supprimées : {sorted(obsolete_checked)}"
            )

        # Nettoyage automatique des settings :
        # on conserve uniquement les colonnes encore valides
        self.selected_columns = [
            k for k in self.selected_columns
            if k in current_keys
        ]

        self._build_dynamic_checkboxes(self._available_keys)

        if self.btnSelectAll:
            self.btnSelectAll.clicked.connect(self._select_all)
        if self.btnClearAll:
            self.btnClearAll.clicked.connect(self._clear_all)
        if self.btnApply:
            self.btnApply.clicked.connect(self._apply)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    # ---------- Panneau de fallback ----------
    def _build_fallback_selector_panel(self):
        panel = QWidget(self)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        vroot = QVBoxLayout(panel)
        vroot.setContentsMargins(12, 12, 12, 12)
        vroot.setSpacing(8)

        # Ligne de boutons
        h = QHBoxLayout()

        self.btnSelectAll = QPushButton("Tout cocher", panel)
        self.btnClearAll = QPushButton("Tout décocher", panel)

        h.addWidget(self.btnSelectAll)
        h.addWidget(self.btnClearAll)
        h.addStretch(1)

        self.btnApply = QPushButton("Appliquer", panel)
        h.addWidget(self.btnApply)

        vroot.addLayout(h)

        # Scroll + conteneur
        scroll = QScrollArea(panel)
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        inner = QWidget(scroll)
        inner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.varsLayout = QVBoxLayout(inner)
        self.varsLayout.setContentsMargins(6, 6, 6, 6)
        self.varsLayout.setSpacing(6)

        scroll.setWidget(inner)

        vroot.addWidget(scroll)

        # Ajouter le panneau
        self.mainArea.layout().addWidget(panel)

    # ---------- Dependencies ----------
    @staticmethod
    def _dependencies_freeze_space() -> str:
        try:
            dists = sorted(
                importlib_metadata.distributions(),
                key=lambda d: (d.metadata.get("Name", "") or "").lower()
            )

            parts = []

            for dist in dists:
                name = (dist.metadata.get("Name") or "").strip()
                version = getattr(dist, "version", None)

                if name and version:
                    parts.append(f"{name}=={version}")

            return "\n\r".join(parts)

        except Exception as e:
            return f"Error collecting dependencies: {e}"

    def _collect(self):
        keys = [
            "Row number",
            "Current Time",
            "OS",
            "Machine",
            "Processor",
            "Python Version",
            "Python Executable",
            "Dependencies"
        ]

        vals = [
            None,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            platform.platform(),
            platform.machine(),
            platform.processor() or platform.machine(),
            sys.version.replace("\n", " "),
            sys.executable,
            self._dependencies_freeze_space(),
        ]

        return keys, vals

    # ---------- Cases à cocher ----------
    def _build_dynamic_checkboxes(self, keys):
        if not self.varsLayout:
            return

        # Nettoyer
        while self.varsLayout.count():
            item = self.varsLayout.takeAt(0)
            w = item.widget()

            if w:
                w.setParent(None)

        self._var_checks.clear()

        for k in keys:
            cb = QCheckBox(k)

            if self.selected_columns:
                cb.setChecked(k in self.selected_columns)
            else:
                cb.setChecked(True)

            cb.stateChanged.connect(self._update_selected_columns)

            self.varsLayout.addWidget(cb)
            self._var_checks[k] = cb

        self.varsLayout.addStretch(1)

    # ---------- Mise à jour settings ----------
    def _update_selected_columns(self):
        self.selected_columns = [
            k for k, cb in self._var_checks.items()
            if cb.isChecked()
        ]

    # ---------- Slots ----------
    def _select_all(self):
        for cb in self._var_checks.values():
            cb.setChecked(True)

    def _clear_all(self):
        for cb in self._var_checks.values():
            cb.setChecked(False)

    # ---------- Entrée ----------
    @Inputs.data
    def set_data(self, data: Orange.data.Table | None):
        self._current_data = data
        self._apply()

    # ---------- Application ----------
    def _apply(self):
        self.error("")

        data = self._current_data

        if data is None:
            self.Outputs.data.send(None)
            return

        keys, vals = self._collect()
        kv = dict(zip(keys, vals))

        # Utiliser uniquement les colonnes encore valides
        selected_keys = [
            k for k in self.selected_columns
            if k in kv
        ]

        if not selected_keys:
            self.Outputs.data.send(data)
            return

        matches = [k for k in selected_keys if k in data.domain]

        if matches:
            self.error(f"Your input data cannot contain these columns: {matches}")
            self.Outputs.data.send(None)
            return

        existing_meta_vars = list(data.domain.metas)
        new_meta_vars = [
            Orange.data.StringVariable.make(k)
            for k in selected_keys
        ]

        new_domain = Orange.data.Domain(
            attributes=list(data.domain.attributes),
            class_vars=list(data.domain.class_vars),
            metas=existing_meta_vars + new_meta_vars,
        )

        n = len(data)

        left = (
            data.metas
            if (data.metas is not None and data.metas.size)
            else np.empty((n, len(existing_meta_vars)), dtype=object)
        )

        right = np.empty((n, len(new_meta_vars)), dtype=object)

        for j, k in enumerate(selected_keys):
            if k == "Row number":
                right[:, j] = np.arange(1, n + 1).astype(object)
            else:
                right[:, j] = kv.get(k, "")

        metas = np.hstack([left, right]) if left.size else right

        out = Orange.data.Table(
            new_domain,
            data.X,
            data.Y,
            metas=metas,
            W=data.W
        )

        out.name = data.name or "Data with added columns"

        self.Outputs.data.send(out)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    w = OWAddColumns()
    w.show()

    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()