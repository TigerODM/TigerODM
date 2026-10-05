# ---------------------------------------------------------------------------
# Interface de diagnostic des widgets Orange, lançable depuis le Canvas.
#
# Style calqué sur le mini-Notepad (AnyQt, EditorMainWindow lié à une fenêtre
# parente). L'utilisateur peut choisir :
#   - les catégories à analyser (vide = toutes),
#   - le grain de l'analyse (ajout ou non des librairies pip par widget),
#   - la comparaison à une référence et la couverture par les workflows.
# Une fenêtre secondaire « Validation des workflows » lance les tutoriels
# (tutorial.json) et les autres batchs .json, et compare leur sortie (OK/NOK).
#
# Lancement depuis le Canvas :
#
#   def open_widget_diagnostic(self):
#       try:
#           from orangecontrib.AAIT.utils.tools.widget_diagnostic import EditorMainWindow
#           if not hasattr(self, "_widget_diagnostic") or self._widget_diagnostic is None:
#               self._widget_diagnostic = EditorMainWindow(self)
#           self._widget_diagnostic.show()
#           self._widget_diagnostic.raise_()
#           self._widget_diagnostic.activateWindow()
#       except Exception as e:
#           import logging
#           logging.error(f"Failed to open widget diagnostic window: {e}")
# ---------------------------------------------------------------------------

import os
import re
import sys
import traceback
from pathlib import Path

from AnyQt.QtCore import QSettings, Qt, QUrl
from AnyQt.QtGui import QColor, QDesktopServices
from AnyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Import robuste du module de logique (package Orange OU exécution directe)
try:
    from . import widget_diagnostic_core as core
except (ImportError, ValueError):
    try:
        from orangecontrib.AAIT.utils.tools import widget_diagnostic_core as core
    except Exception:
        import widget_diagnostic_core as core


# ── Constantes d'affichage ──────────────────────────────────────────────────

COLOR_OK = QColor("#2e7d32")
COLOR_NOK = QColor("#c62828")
COLOR_ERR = QColor("#e65100")
COLOR_MOD = QColor("#e65100")
BG_RERUN = QColor("#ffe0b2")

# Colonne présente dans les données/exports mais masquée à l'écran (T3).
HIDDEN_ON_SCREEN = {core.COLUMN_LABELS["launch"]}

EXPORT_FILTERS = "Excel (*.xlsx);;CSV (*.csv);;Orange tab (*.tab);;Tous les fichiers (*.*)"
_FILTER_EXT = {"Excel": ".xlsx", "CSV": ".csv", "Orange": ".tab"}


# ── Utilitaires ─────────────────────────────────────────────────────────────

def settings():
    """Préférences persistantes (C1)."""
    return QSettings("TigerODM", "WidgetDiagnostic")


def s_bool(key, default):
    v = settings().value(key, default)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "oui")
    return bool(v) if v is not None else default


def s_str(key, default=""):
    v = settings().value(key, default)
    return default if v is None else str(v)


def s_list(key):
    v = settings().value(key, [])
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v else []
    return [str(x) for x in v]


def ask_export_path(parent, title, suggested_name):
    """Boîte « Enregistrer sous » : nom et extension modifiables, dossier
    mémorisé, confirmation avant d'écraser un fichier existant (S3).
    Renvoie le chemin choisi ou None."""
    last_dir = s_str("export/last_dir", "")
    start = str(Path(last_dir) / suggested_name) if last_dir and Path(last_dir).is_dir() \
        else suggested_name
    path, flt = QFileDialog.getSaveFileName(parent, title, start, EXPORT_FILTERS)
    if not path:
        return None
    p = Path(path)
    if not p.suffix:
        for key, ext in _FILTER_EXT.items():
            if flt.startswith(key):
                p = p.with_suffix(ext)
                break
        else:
            p = p.with_suffix(".xlsx")
        # L'extension a été ajoutée après la boîte : on revérifie l'écrasement.
        if p.exists():
            r = QMessageBox.question(
                parent, "Fichier existant",
                f"Le fichier existe déjà :\n{p}\n\nVoulez-vous le remplacer ?")
            if r != QMessageBox.StandardButton.Yes:
                return None
    settings().setValue("export/last_dir", str(p.parent))
    return str(p)


def launch_path_from_command(cmd):
    """Chemin du .py contenu dans la commande « Lancer le widget »."""
    found = re.findall(r'"([^"]+)"', cmd or "")
    return found[-1] if found else ""


def open_in_file_manager(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# ═══════════════════════════════════════════════════════════════════════════
#  Fenêtre principale : diagnostic des widgets
# ═══════════════════════════════════════════════════════════════════════════

class EditorMainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TigerODM — Diagnostic des widgets")
        self.resize(1400, 900)
        self.setMinimumSize(900, 600)

        self._running = False
        self._cancel = False
        self._headers = []
        self._rows = []
        self._metadata = []
        self._diagnostic_done = False
        self._validation_win = None
        self._has_dev = False        # widgets de dev présents sur la machine ?
        self._coverage = None        # dict de core.load_coverage() du dernier run
        self._cov_filtered = False   # diagnostic filtré par catégorie ?

        self._build_ui()
        self._load_categories()
        self._detect_dev_widgets()
        self._restore_settings()
        self._refresh_ref_status()

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        top = QHBoxLayout()

        # --- Catégories ---
        gb_cat = QGroupBox("Catégories à analyser")
        cat_layout = QVBoxLayout(gb_cat)
        cat_layout.addWidget(QLabel("Aucune cochée = toutes les catégories."))
        self.cat_list = QListWidget()
        self.cat_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        cat_layout.addWidget(self.cat_list)
        cat_btns = QHBoxLayout()
        btn_all = QPushButton("Tout cocher")
        btn_none = QPushButton("Tout décocher")
        btn_all.clicked.connect(lambda: self._set_all_categories(True))
        btn_none.clicked.connect(lambda: self._set_all_categories(False))
        cat_btns.addWidget(btn_all)
        cat_btns.addWidget(btn_none)
        cat_btns.addStretch(1)
        cat_layout.addLayout(cat_btns)
        top.addWidget(gb_cat, 2)

        right = QVBoxLayout()

        # --- Options d'analyse ---
        gb_opt = QGroupBox("Options d'analyse")
        opt_layout = QVBoxLayout(gb_opt)

        self.cb_packages = QCheckBox("Détailler les librairies pip (plus lent)")
        self.cb_packages.setToolTip(
            "Coché : une ligne par (widget, librairie) — analyse récursive des imports.\n"
            "Décoché : une ligne par widget, sans librairies — beaucoup plus rapide."
        )
        opt_layout.addWidget(self.cb_packages)

        # Option prod/dev : affichée seulement si des widgets de dev existent.
        self.dev_box = QWidget()
        dev_row = QHBoxLayout(self.dev_box)
        dev_row.setContentsMargins(0, 0, 0, 0)
        dev_row.addWidget(QLabel("Versions dev des widgets :"))
        self.cmb_dev = QComboBox()
        self.cmb_dev.addItem("Ignorer", core.DEV_IGNORE)
        self.cmb_dev.addItem("Considérer séparément", core.DEV_SEPARATE)
        self.cmb_dev.setToolTip(
            "Sur une machine de dev, un widget peut exister en version prod\n"
            "(site-packages\\orangecontrib\\…) et en version dev\n"
            "(site-packages\\Orange\\widgets\\orangecontrib\\…).\n\n"
            "Ignorer : seules les versions prod sont analysées.\n"
            "Considérer séparément : les deux sont listées, avec une colonne 'Version'.\n\n"
            "Dans les deux cas, la couverture et les workflows à relancer ne\n"
            "concernent que la prod (les tutoriels testent la prod)."
        )
        dev_row.addWidget(self.cmb_dev, 1)
        opt_layout.addWidget(self.dev_box)

        self.cb_coverage = QCheckBox("Afficher la couverture par les tutoriels")
        self.cb_coverage.setToolTip(
            "Ajoute les colonnes 'Couvert par (workflows)' et 'Identifiant widget',\n"
            "l'onglet 'Couverture', le taux de couverture au récapitulatif et une\n"
            "feuille 'Couverture' à l'export .xlsx (champ tested_widgets)."
        )
        self.cb_cov_batches = QCheckBox("Inclure aussi les autres batchs .json")
        self.cb_cov_batches.setToolTip(
            "Compte aussi les tested_widgets des autres fichiers .json présents\n"
            "à côté de tutorial.json (libellés « Batch <fichier> : <nom> »)."
        )
        self.cb_coverage.toggled.connect(
            lambda on: self.cb_cov_batches.setEnabled(on and not self._running))
        opt_layout.addWidget(self.cb_coverage)
        cov_sub = QHBoxLayout()
        cov_sub.addSpacing(20)
        cov_sub.addWidget(self.cb_cov_batches, 1)
        opt_layout.addLayout(cov_sub)
        right.addWidget(gb_opt)

        # --- Référence (S5) ---
        gb_ref = QGroupBox("Référence (versions pip + hash des .py)")
        ref_layout = QVBoxLayout(gb_ref)
        self.lbl_ref_status = QLabel()
        self.lbl_ref_status.setWordWrap(True)
        ref_layout.addWidget(self.lbl_ref_status)
        self.lbl_ref_path = QLabel()
        self.lbl_ref_path.setWordWrap(True)
        self.lbl_ref_path.setStyleSheet("color:#666;")
        self.lbl_ref_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ref_layout.addWidget(self.lbl_ref_path)
        ref_btns = QHBoxLayout()
        self.cb_compare = QCheckBox("Comparer le diagnostic à la référence")
        self.cb_compare.setToolTip(
            "Ajoute les colonnes 'Modifié vs réf.' et, en mode détaillé,\n"
            "'Version lib (réf → actuelle)'.\n\n"
            "Nécessaire pour tout ce qui repose sur la modification des .py :\n"
            "filtre 'Modifiés vs réf.', workflows à relancer (onglet Couverture,\n"
            "récapitulatif, colonne 'À relancer' de la validation)."
        )
        self.btn_save_ref = QPushButton("Figer l'état actuel comme référence…")
        self.btn_save_ref.setToolTip(
            "Enregistre les versions pip installées et le hash des .py de widgets\n"
            "à l'emplacement fixe (aait_store/Parameters). Remplace la référence actuelle."
        )
        self.btn_save_ref.clicked.connect(self._save_reference)
        ref_btns.addWidget(self.cb_compare, 1)
        ref_btns.addWidget(self.btn_save_ref)
        ref_layout.addLayout(ref_btns)
        self.lbl_cmp_hint = QLabel(
            "La comparaison active aussi le filtre « Modifiés vs réf. » et le calcul "
            "des workflows à relancer.")
        self.lbl_cmp_hint.setWordWrap(True)
        self.lbl_cmp_hint.setStyleSheet("color:#666; font-style:italic;")
        ref_layout.addWidget(self.lbl_cmp_hint)
        right.addWidget(gb_ref)

        # --- Actions ---
        act_row = QHBoxLayout()
        self.btn_run = QPushButton("Lancer le diagnostic")
        self.btn_run.clicked.connect(self._run)
        self.btn_export = QPushButton("Exporter…")
        self.btn_export.setToolTip(
            "Enregistre le diagnostic (nom et format au choix ; .xlsx recommandé :\n"
            "tableau, récapitulatif, couverture et métadonnées dans un seul fichier).")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_results)
        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.clicked.connect(self._request_cancel)
        self.btn_cancel.setEnabled(False)
        act_row.addWidget(self.btn_run)
        act_row.addWidget(self.btn_export)
        act_row.addWidget(self.btn_cancel)
        right.addLayout(act_row)
        right.addStretch(1)

        top.addLayout(right, 3)
        root.addLayout(top)

        # --- Progression + bandeau couverture ---
        self.progress = QProgressBar()
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.lbl_coverage = QLabel("")
        self.lbl_coverage.setWordWrap(True)
        root.addWidget(self.lbl_coverage)

        # --- Onglets ---
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_diag_tab(), "Diagnostic")
        self.tabs.addTab(self._build_cov_tab(), "Couverture")
        self.tabs.setTabEnabled(1, False)
        root.addWidget(self.tabs, 1)

        # --- Validation des workflows (S1, S2) ---
        self.btn_validation = QPushButton("Validation des workflows (tutoriels et batchs)…")
        self.btn_validation.setToolTip(
            "Lance les workflows de tutorial.json ou d'un autre batch .json et compare\n"
            "leur sortie à la sortie attendue (OK/NOK). La colonne « À relancer »\n"
            "utilise le dernier diagnostic s'il a été fait avec la comparaison à la\n"
            "référence et la couverture.")
        self.btn_validation.clicked.connect(self._open_validation)
        root.addWidget(self.btn_validation)

        self.setCentralWidget(central)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Prêt.")

    def _build_diag_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)

        # Recherche + filtres rapides (T1)
        flt = QHBoxLayout()
        self.le_search = QLineEdit()
        self.le_search.setPlaceholderText("Rechercher (widget, fichier, catégorie, librairie…)")
        self.le_search.setClearButtonEnabled(True)
        self.le_search.textChanged.connect(self._apply_filters)
        flt.addWidget(self.le_search, 2)
        self.f_not_ok = QCheckBox("Statut ≠ OK")
        self.f_modified = QCheckBox("Modifiés vs réf.")
        self.f_uncovered = QCheckBox("Non couverts")
        for cb in (self.f_not_ok, self.f_modified, self.f_uncovered):
            cb.toggled.connect(self._apply_filters)
            flt.addWidget(cb)
        self.lbl_rows = QLabel("")
        self.lbl_rows.setStyleSheet("color:#666;")
        flt.addWidget(self.lbl_rows)
        lay.addLayout(flt)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        lay.addWidget(self.table, 1)
        self._set_filters_available()
        return w

    def _build_cov_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        top = QHBoxLayout()
        lbl = QLabel("Cliquez sur un widget pour l'afficher dans l'onglet Diagnostic.")
        lbl.setStyleSheet("color:#666;")
        top.addWidget(lbl, 1)
        self.btn_cov_rerun = QPushButton("Valider les tutoriels à relancer…")
        self.btn_cov_rerun.setToolTip(
            "Ouvre la validation sur tutorial.json et coche les tutoriels\n"
            "dont un widget testé a son .py modifié (sans les lancer).")
        self.btn_cov_rerun.setEnabled(False)
        self.btn_cov_rerun.clicked.connect(self._validate_rerun)
        top.addWidget(self.btn_cov_rerun)
        lay.addLayout(top)

        self.cov_tree = QTreeWidget()
        self.cov_tree.setColumnCount(2)
        self.cov_tree.setHeaderLabels(["Élément", "Détail"])
        self.cov_tree.itemClicked.connect(self._cov_item_clicked)
        lay.addWidget(self.cov_tree, 1)
        return w

    # ---------- Préférences (C1) ----------
    def _restore_settings(self):
        self.cb_packages.setChecked(s_bool("opts/packages", False))
        self.cb_coverage.setChecked(s_bool("opts/coverage", True))
        self.cb_cov_batches.setChecked(s_bool("opts/cov_batches", False))
        self.cb_cov_batches.setEnabled(self.cb_coverage.isChecked())
        self._want_compare = s_bool("opts/compare", False)
        if self._has_dev:
            i = self.cmb_dev.findData(s_str("opts/dev_mode", core.DEV_IGNORE))
            self.cmb_dev.setCurrentIndex(max(i, 0))
        checked = set(s_list("opts/categories"))
        for i in range(self.cat_list.count()):
            it = self.cat_list.item(i)
            if (it.data(Qt.ItemDataRole.UserRole) or "") in checked:
                it.setCheckState(Qt.CheckState.Checked)
        geo = settings().value("geometry/main")
        if geo is not None:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    def _save_settings(self):
        st = settings()
        st.setValue("opts/packages", self.cb_packages.isChecked())
        st.setValue("opts/coverage", self.cb_coverage.isChecked())
        st.setValue("opts/cov_batches", self.cb_cov_batches.isChecked())
        st.setValue("opts/compare", self.cb_compare.isChecked())
        if self._has_dev:
            st.setValue("opts/dev_mode", self.cmb_dev.currentData())
        st.setValue("opts/categories", [c or "" for c in self._selected_categories()])
        st.setValue("geometry/main", self.saveGeometry())

    def closeEvent(self, event):
        try:
            self._save_settings()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------- Catégories ----------
    def _load_categories(self):
        self.cat_list.clear()
        try:
            cats = core.get_all_categories()
        except Exception as e:
            self.status.showMessage("Impossible de lire le registry Orange.")
            QMessageBox.warning(
                self, "Registry indisponible",
                f"Impossible de charger les catégories :\n{e}",
            )
            return
        for c in cats:
            label = c if c else "(sans catégorie)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, c)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.cat_list.addItem(item)
        self.status.showMessage(f"{len(cats)} catégorie(s) détectée(s).")

    def _set_all_categories(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.cat_list.count()):
            self.cat_list.item(i).setCheckState(state)

    def _selected_categories(self):
        out = []
        for i in range(self.cat_list.count()):
            item = self.cat_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out  # vide => toutes (géré par le core)

    # ---------- Versions dev ----------
    def _detect_dev_widgets(self):
        """Masque l'option prod/dev s'il n'y a aucun widget de dev sur la machine."""
        try:
            self._has_dev = core.has_dev_widgets()
        except Exception:
            self._has_dev = False
        self.dev_box.setVisible(self._has_dev)
        if not self._has_dev:
            self.cmb_dev.setCurrentIndex(self.cmb_dev.findData(core.DEV_IGNORE))

    def _dev_mode(self):
        return self.cmb_dev.currentData() if self._has_dev else core.DEV_IGNORE

    # ---------- Référence (S5, S6) ----------
    def _refresh_ref_status(self):
        try:
            p = core.reference_path()
            self.lbl_ref_path.setText(f"Emplacement : {p}")
            info = core.reference_info()
            if info:
                created, machine, n_files = info
                self.lbl_ref_status.setText(
                    f"✔ Référence du {created} — machine {machine} — {n_files} fichier(s) .py")
                self.lbl_ref_status.setStyleSheet("color:#2e7d32;")
                self.cb_compare.setEnabled(not self._running)
                if getattr(self, "_want_compare", None) is not None:
                    self.cb_compare.setChecked(self._want_compare)
                    self._want_compare = None
            else:
                txt = ("✖ Référence illisible." if core.reference_exists()
                       else "✖ Aucune référence enregistrée.")
                self.lbl_ref_status.setText(txt)
                self.lbl_ref_status.setStyleSheet("color:#c62828;")
                self.cb_compare.setChecked(False)
                self.cb_compare.setEnabled(False)
        except Exception as e:
            self.lbl_ref_path.setText("Emplacement de la référence indisponible.")
            self.lbl_ref_status.setText(str(e))

    def _save_reference(self):
        if self._running:
            return

        info = core.reference_info()
        if info:
            r = QMessageBox.question(
                self, "Remplacer la référence",
                f"Une référence existe déjà (du {info[0]}, machine {info[1]}).\n\n"
                "Voulez-vous la remplacer par l'état actuel ?")
            if r != QMessageBox.StandardButton.Yes:
                return

        cats = self._selected_categories()
        if cats:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Filtre de catégories actif")
            box.setText(
                f"{len(cats)} catégorie(s) sont cochées.\n\n"
                "Une référence limitée à ces catégories fera apparaître tous les autres "
                "widgets comme « nouveaux » lors des prochaines comparaisons.\n\n"
                "Quelles catégories voulez-vous inclure dans la référence ?")
            b_all = box.addButton("Toutes les catégories (recommandé)",
                                  QMessageBox.ButtonRole.AcceptRole)
            b_sel = box.addButton("Seulement la sélection", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_all)
            box.exec()
            clicked = box.clickedButton()
            if clicked is b_all:
                cats = []
            elif clicked is not b_sel:
                return

        self._running = True
        self._cancel = False
        self._set_controls_enabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setValue(0)
        self.status.showMessage("Construction de la référence…")

        def cb(done, total, message):
            if total > 0:
                self.progress.setMaximum(total)
                self.progress.setValue(done)
            self.status.showMessage(f"[{done}/{total}] {message}")
            QApplication.processEvents()

        try:
            ref = core.build_reference(
                selected_categories=cats,
                progress_callback=cb,
                should_cancel=lambda: self._cancel,
            )
            if self._cancel:
                self.status.showMessage("Référence non enregistrée (annulation).")
            else:
                p = core.save_reference_default(ref)
                n_files = len(ref.get("files", {}))
                n_pkgs = len(ref.get("packages", {}))
                self.status.showMessage(f"Référence enregistrée : {p}", 4000)
                QMessageBox.information(
                    self, "Référence enregistrée",
                    f"Référence créée :\n{p}\n\n"
                    f"{n_files} fichier(s) .py hashé(s)\n{n_pkgs} paquet(s) pip figé(s)",
                )
        except Exception:
            QMessageBox.critical(self, "Erreur", traceback.format_exc())
            self.status.showMessage("Erreur durant la création de la référence.")
        finally:
            self._running = False
            self._set_controls_enabled(True)
            self.btn_cancel.setEnabled(False)
            self._refresh_ref_status()

    # ---------- Export (S3, S4) ----------
    def _export_results(self):
        if not self._rows:
            QMessageBox.information(
                self, "Exporter",
                "Aucun diagnostic à exporter pour le moment.\nLancez d'abord une analyse.")
            return
        suggested = core.default_output_name(
            include_packages=(core.COLUMN_LABELS["package"] in self._headers), ext=".xlsx")
        path = ask_export_path(self, "Exporter le diagnostic", suggested)
        if not path:
            return
        try:
            p = core.write_rows(path, self._headers, self._rows, metadata=self._metadata,
                                coverage=self._coverage, filtered=self._cov_filtered)
            self.status.showMessage(f"Exporté : {p}", 6000)
            QMessageBox.information(
                self, "Exporté", f"Diagnostic exporté ({len(self._rows)} ligne(s)) :\n{p}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur d'export", str(e))

    # ---------- Exécution ----------
    def _request_cancel(self):
        self._cancel = True
        self.status.showMessage("Annulation demandée…")

    def _set_controls_enabled(self, enabled: bool):
        self.btn_run.setEnabled(enabled)
        self.cb_packages.setEnabled(enabled)
        self.cat_list.setEnabled(enabled)
        self.cb_compare.setEnabled(enabled and core.reference_info() is not None)
        self.btn_save_ref.setEnabled(enabled)
        self.cb_coverage.setEnabled(enabled)
        self.cb_cov_batches.setEnabled(enabled and self.cb_coverage.isChecked())
        self.cmb_dev.setEnabled(enabled)
        self.btn_export.setEnabled(enabled and bool(self._rows))
        # Validation des workflows : disponible sans diagnostic (S2), mais pas
        # pendant qu'une analyse tourne dans le thread principal.
        self.btn_validation.setEnabled(enabled)

    def _run(self):
        if self._running:
            return

        cats = self._selected_categories()
        include = self.cb_packages.isChecked()

        reference = None
        if self.cb_compare.isChecked():
            if not core.reference_exists():
                QMessageBox.warning(
                    self, "Référence absente",
                    "Aucune référence enregistrée.\n"
                    "Cliquez d'abord sur « Figer l'état actuel comme référence… ».",
                )
                return
            try:
                reference = core.load_reference_default()
            except Exception as e:
                QMessageBox.critical(
                    self, "Référence illisible",
                    f"Impossible de charger la référence :\n{e}",
                )
                return

        coverage = None
        if self.cb_coverage.isChecked():
            try:
                coverage = core.load_coverage(include_batches=self.cb_cov_batches.isChecked())
                if not coverage.get("sources"):
                    self.status.showMessage(
                        "Couverture : aucun fichier de workflows lisible, colonnes vides.")
            except Exception as e:
                coverage = None
                QMessageBox.warning(self, "Couverture",
                                    f"Lecture des tested_widgets impossible :\n{e}")

        self._running = True
        self._cancel = False
        self._set_controls_enabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setValue(0)
        self.status.showMessage("Analyse en cours…")
        self._metadata = core.collect_metadata()

        def cb(done, total, message):
            if total > 0:
                self.progress.setMaximum(total)
                self.progress.setValue(done)
            self.status.showMessage(f"[{done}/{total}] {message}")
            # L'analyse importe des modules de widgets : on reste dans le thread
            # principal (pas d'objet Qt hors GUI-thread) et on garde l'UI réactive.
            QApplication.processEvents()

        try:
            headers, rows = core.run_diagnostic(
                selected_categories=cats,
                include_packages=include,
                reference=reference,
                progress_callback=cb,
                should_cancel=lambda: self._cancel,
                coverage=coverage,
                dev_mode=self._dev_mode(),
            )
            self._headers, self._rows = headers, rows
            self._coverage = coverage
            self._cov_filtered = bool(cats)
            self._populate_table(headers, rows)
            self._refresh_coverage()
            self._diagnostic_done = True
            if self._cancel:
                self.status.showMessage(f"Annulé — {len(rows)} ligne(s) partielle(s).")
            else:
                self.status.showMessage(
                    f"Terminé — {len(rows)} ligne(s). Cliquez sur « Exporter… » pour enregistrer.")
            self._save_settings()
        except Exception:
            QMessageBox.critical(self, "Erreur", traceback.format_exc())
            self.status.showMessage("Erreur durant l'analyse.")
        finally:
            self._running = False
            self._set_controls_enabled(True)
            self.btn_cancel.setEnabled(False)
            self._refresh_ref_status()
            # La fenêtre de validation, si ouverte, met à jour « À relancer ».
            if self._validation_win is not None and not self._validation_win.is_running():
                self._validation_win.refresh_rerun()

    # ---------- Table de diagnostic ----------
    def _col(self, key):
        lab = core.COLUMN_LABELS[key]
        return self._headers.index(lab) if lab in self._headers else None

    def _populate_table(self, headers, rows):
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(headers)

        c_stat, c_file = self._col("statut"), self._col("file_status")
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                it = QTableWidgetItem("" if val is None else str(val))
                if c == 0:
                    it.setData(Qt.ItemDataRole.UserRole, r)   # index dans self._rows
                if c == c_stat and str(val or "").strip().upper() != "OK":
                    it.setForeground(COLOR_NOK)                # T2
                if c == c_file and core._file_is_modified(val):
                    it.setForeground(COLOR_MOD)
                    f = it.font(); f.setBold(True); it.setFont(f)
                self.table.setItem(r, c, it)
        for c, h in enumerate(headers):
            self.table.setColumnHidden(c, h in HIDDEN_ON_SCREEN)
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        if header.count():
            header.setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        self._set_filters_available()
        self._apply_filters()

    def _set_filters_available(self):
        has = lambda k: core.COLUMN_LABELS[k] in self._headers
        self.f_modified.setEnabled(has("file_status"))
        self.f_uncovered.setEnabled(has("coverage"))
        if not has("file_status"):
            self.f_modified.setChecked(False)
        if not has("coverage"):
            self.f_uncovered.setChecked(False)
        self.f_modified.setText("Modifiés vs réf." if has("file_status")
                                else "Modifiés vs réf. (comparaison inactive)")
        self.f_modified.setToolTip("" if has("file_status") else
                                   "Relancez le diagnostic avec « Comparer le diagnostic "
                                   "à la référence » cochée.")
        self.f_uncovered.setToolTip("" if has("coverage") else
                                    "Disponible après un diagnostic avec la couverture.")

    def _apply_filters(self):
        if not self._headers:
            self.lbl_rows.setText("")
            return
        text = self.le_search.text().strip().lower()
        c_stat, c_file = self._col("statut"), self._col("file_status")
        c_cov, c_var = self._col("coverage"), self._col("variant")
        visible_cols = [c for c in range(self.table.columnCount())
                        if not self.table.isColumnHidden(c)]

        def txt(r, c):
            if c is None:
                return ""
            it = self.table.item(r, c)
            return it.text() if it is not None else ""

        shown = 0
        for r in range(self.table.rowCount()):
            ok = True
            if text:
                ok = any(text in txt(r, c).lower() for c in visible_cols)
            if ok and self.f_not_ok.isChecked():
                ok = txt(r, c_stat).strip().upper() != "OK"
            if ok and self.f_modified.isChecked() and c_file is not None:
                ok = core._file_is_modified(txt(r, c_file))
            if ok and self.f_uncovered.isChecked() and c_cov is not None:
                ok = not txt(r, c_cov).strip() and txt(r, c_var) != "dev"
            self.table.setRowHidden(r, not ok)
            shown += ok
        self.lbl_rows.setText(f"{shown} / {self.table.rowCount()} ligne(s)")

    def _table_menu(self, pos):
        it = self.table.itemAt(pos)
        if it is None:
            return
        first = self.table.item(it.row(), 0)
        idx = first.data(Qt.ItemDataRole.UserRole) if first is not None else None
        c_launch = self._col("launch")
        if idx is None or c_launch is None:
            return
        cmd = str(self._rows[idx][c_launch] or "")
        py = launch_path_from_command(cmd)
        menu = QMenu(self)
        a_copy = menu.addAction("Copier la commande de lancement")
        a_copy.setEnabled(bool(cmd))
        a_dir = menu.addAction("Ouvrir le dossier du fichier .py")
        a_dir.setEnabled(bool(py) and Path(py).parent.is_dir())
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is a_copy:
            QApplication.clipboard().setText(cmd)
            self.status.showMessage("Commande copiée dans le presse-papiers.", 3000)
        elif chosen is a_dir:
            open_in_file_manager(Path(py).parent)

    # ---------- Couverture (bandeau + onglet, S7) ----------
    def _coverage_report(self):
        if not self._rows:
            return None
        try:
            return core.coverage_report(self._headers, self._rows,
                                        self._coverage, self._cov_filtered)
        except Exception:
            return None

    def _refresh_coverage(self):
        rep_ = self._coverage_report()
        self.cov_tree.clear()
        if not rep_:
            self.lbl_coverage.setText("")
            self.tabs.setTabEnabled(1, False)
            self.btn_cov_rerun.setEnabled(False)
            return
        warn = rep_["covered_not_ok"] or rep_["orphans"] or rep_["invalid"]
        self.lbl_coverage.setStyleSheet("color:#e65100;" if warn else
                                        ("color:#2e7d32;" if rep_["compare"] else "color:#555;"))
        self.lbl_coverage.setText(core.coverage_short_text(rep_))
        self.tabs.setTabEnabled(1, True)

        def group(title, items, detail_fn=None, widget_fn=None, warn=False, expanded=False):
            g = QTreeWidgetItem([f"{title} ({len(items)})", ""])
            f = g.font(0); f.setBold(True); g.setFont(0, f)
            if warn and items:
                g.setForeground(0, COLOR_ERR)
            for x in items:
                label, detail = detail_fn(x) if detail_fn else (str(x), "")
                ch = QTreeWidgetItem([label, detail])
                if widget_fn:
                    ch.setData(0, Qt.ItemDataRole.UserRole, widget_fn(x))
                    ch.setToolTip(0, "Cliquez pour afficher ce widget dans l'onglet Diagnostic.")
                g.addChild(ch)
            self.cov_tree.addTopLevelItem(g)
            g.setExpanded(expanded and bool(items))
            return g

        if rep_["compare"]:
            group("Workflows à relancer (widget .py modifié)", rep_["to_rerun"],
                  lambda x: (x[0], ", ".join(x[1])), warn=True, expanded=True)
        else:
            g = QTreeWidgetItem(["Workflows à relancer (widget .py modifié)",
                                 core.RERUN_UNAVAILABLE])
            f = g.font(0); f.setBold(True); g.setFont(0, f)
            g.setForeground(1, QColor("#888"))
            g.setToolTip(1, "Relancez le diagnostic avec « Comparer le diagnostic "
                            "à la référence » cochée.")
            self.cov_tree.addTopLevelItem(g)
        group("Widgets couverts mais statut ≠ OK", rep_["covered_not_ok"],
              lambda x: (x[0], f"{x[1]}  —  {', '.join(x[2])}"),
              widget_fn=lambda x: x[0], warn=True, expanded=True)
        group("Identifiants orphelins" + (" (diagnostic filtré)" if rep_["filtered"] else ""),
              rep_["orphans"], lambda x: (x[0], x[1]), warn=True, expanded=True)
        group("Identifiants invalides", rep_["invalid"], lambda x: (x[0], x[1]),
              warn=True, expanded=True)
        group("Workflows sans tested_widgets", rep_["without"], lambda x: (x, ""))
        group("Widgets prod non couverts", sorted(rep_["uncovered"], key=lambda x: (x[1], x[0])),
              lambda x: (x[0], x[1]), widget_fn=lambda x: x[0])
        group("Widgets couverts par plusieurs workflows", rep_["multi"],
              lambda x: (x[0], ", ".join(x[1])), widget_fn=lambda x: x[0])
        cats = sorted(rep_["by_category"].items())
        group("Couverture par catégorie", cats,
              lambda x: (x[0], f"{x[1][0]} / {x[1][1]}  ({core._pct(x[1][0], x[1][1])})"))
        self.cov_tree.resizeColumnToContents(0)
        self.btn_cov_rerun.setEnabled(rep_["compare"] and any(
            t.startswith(core.workflow_label("")) for t, _ in rep_["to_rerun"]))
        self.btn_cov_rerun.setToolTip(
            "Ouvre la validation sur tutorial.json et coche les tutoriels\n"
            "dont un widget testé a son .py modifié (sans les lancer)."
            if rep_["compare"] else
            "Indisponible : comparaison à la référence inactive lors du dernier diagnostic.")

    def _cov_item_clicked(self, item, _col):
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if not name:
            return
        for cb in (self.f_not_ok, self.f_modified, self.f_uncovered):
            cb.setChecked(False)
        self.le_search.setText(str(name))
        self.tabs.setCurrentIndex(0)

    def _validate_rerun(self):
        win = self._open_validation()
        if win is not None:
            win.select_source(None)       # tutorial.json
            win.check_rerun()

    # ---------- Infos fournies à la fenêtre de validation ----------
    def rerun_info(self):
        """(modified, message) pour la fenêtre de validation.
        modified : {clé_minuscule: nom} des widgets PROD modifiés vs référence,
        ou None si le dernier diagnostic ne permet pas de le déterminer."""
        if not self._rows:
            return None, "aucun diagnostic lancé"
        try:
            modified = core.modified_prod_widgets(self._headers, self._rows)
        except Exception:
            modified = None
        if modified is None:
            if core.COLUMN_LABELS["file_status"] not in self._headers:
                return None, "dernier diagnostic sans comparaison à la référence"
            return None, "dernier diagnostic sans couverture"
        return modified, ""

    # ---------- Validation des workflows ----------
    def _open_validation(self):
        if self._validation_win is None:
            self._validation_win = WorkflowValidationWindow(self)
        win = self._validation_win
        if not win.is_running():
            win.reload()
        win.show()
        win.raise_()
        win.activateWindow()
        return win


# ═══════════════════════════════════════════════════════════════════════════
#  Fenêtre secondaire : validation des workflows (tutoriels + batchs)
# ═══════════════════════════════════════════════════════════════════════════

# Colonnes de la table (même ordre que core.workflow_headers)
W_NAME, W_DESC, W_OWS, W_RES, W_DET, W_DUR, W_TESTED, W_RERUN = range(8)


class WorkflowValidationWindow(QMainWindow):
    """Lance les workflows d'un fichier .json un par un, compare la sortie à la
    sortie attendue (OK/NOK) et exporte les résultats.

    La liste « Workflows » propose tutorial.json (les tutoriels) en premier,
    puis les autres batchs .json présents à côté. Les batchs ne sont pas des
    tutoriels : leur première colonne s'appelle « Nom »."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TigerODM — Validation des workflows")
        self.resize(1300, 800)
        self.setMinimumSize(900, 520)
        self._running = False
        self._cancel = False
        self._sources = []        # [{path: Path|None, label, count}] ; None = tutorial.json
        self._source_path = None  # source affichée (None = tutorial.json)
        self._entries = []
        self._row_results = {}    # ligne -> dernier résultat (dict)
        self._rerun = {}          # ligne -> [widgets modifiés]
        self._rerun_available = False
        self._rerun_msg = ""
        self._thread = None
        self._queue = []
        self._queue_total = 0
        self._queue_done = 0
        self._current_row = -1
        self._api_started_by_us = False
        self._build_ui()
        geo = settings().value("geometry/validation")
        if geo is not None:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        sel = QHBoxLayout()
        sel.addWidget(QLabel("Workflows :"))
        self.cmb_source = QComboBox()
        self.cmb_source.setToolTip(
            "Tutoriels = workflows de tutorial.json.\n"
            "Batchs = autres fichiers .json présents à côté (même format).")
        self.cmb_source.currentIndexChanged.connect(self._on_source_changed)
        sel.addWidget(self.cmb_source, 1)
        self.btn_refresh = QPushButton("Actualiser la liste")
        self.btn_refresh.clicked.connect(self.reload)
        sel.addWidget(self.btn_refresh)
        root.addLayout(sel)

        self.lbl_path = QLabel()
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setStyleSheet("color:#666;")
        root.addWidget(self.lbl_path)

        # Ligne 1 : lancement
        run_row = QHBoxLayout()
        self.btn_run_all = QPushButton("Lancer tous")
        self.btn_run_all.clicked.connect(self._run_all)
        self.btn_run_checked = QPushButton("Lancer les cochés")
        self.btn_run_checked.clicked.connect(self._run_checked)
        self.btn_rerun_failed = QPushButton("Relancer les NOK/ERREUR")
        self.btn_rerun_failed.setToolTip("Relance les workflows dont le dernier résultat est NOK ou ERREUR.")
        self.btn_rerun_failed.clicked.connect(self._run_failed)
        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._request_cancel)
        self.btn_export = QPushButton("Exporter…")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export)
        for b in (self.btn_run_all, self.btn_run_checked, self.btn_rerun_failed, self.btn_cancel):
            run_row.addWidget(b)
        run_row.addStretch(1)
        run_row.addWidget(self.btn_export)
        root.addLayout(run_row)

        # Ligne 2 : cases à cocher (V1)
        chk_row = QHBoxLayout()
        self.btn_check_all = QPushButton("Tout cocher")
        self.btn_check_all.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_check_none = QPushButton("Tout décocher")
        self.btn_check_none.clicked.connect(lambda: self._set_all_checked(False))
        self.btn_check_rerun = QPushButton("Cocher : à relancer")
        self.btn_check_rerun.setToolTip(
            "Coche les workflows dont un widget testé (prod) a son .py modifié par\n"
            "rapport à la référence, d'après le dernier diagnostic.")
        self.btn_check_rerun.clicked.connect(self.check_rerun)
        for b in (self.btn_check_all, self.btn_check_none, self.btn_check_rerun):
            chk_row.addWidget(b)
        chk_row.addStretch(1)
        root.addLayout(chk_row)

        # Compteur permanent (V3)
        self.lbl_counter = QLabel("")
        f = self.lbl_counter.font(); f.setBold(True); self.lbl_counter.setFont(f)
        root.addWidget(self.lbl_counter)

        # Disponibilité de « À relancer » (dépend de la comparaison à la référence)
        self.lbl_rerun_info = QLabel("")
        self.lbl_rerun_info.setWordWrap(True)
        root.addWidget(self.lbl_rerun_info)

        self.progress = QProgressBar()
        root.addWidget(self.progress)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.itemChanged.connect(lambda *_: self._update_buttons())
        root.addWidget(self.table, 1)

        self.setCentralWidget(central)
        self.status = QStatusBar()
        self.setStatusBar(self.status)

    def is_running(self):
        return self._running

    def _is_tutorial(self):
        return self._source_path is None

    def _kind(self):
        return "tutoriel(s)" if self._is_tutorial() else "workflow(s)"

    # ---------- Sources ----------
    def reload(self):
        """(Re)liste tutorial.json + les autres batchs et recharge la source
        sélectionnée (ou la dernière utilisée)."""
        if self._running:
            return
        previous = self._source_path if self.cmb_source.count() else \
            (s_str("validation/source", "") or None)
        self._sources = []
        try:
            if core.tutorial_exists():
                n = len(core.load_tutorials())
                self._sources.append({"path": None, "label": f"Tutoriels (tutorial.json) — {n}",
                                      "count": n})
        except Exception:
            pass
        skipped = []
        try:
            batches, skipped = core.list_workflow_batches()
            for b in batches:
                self._sources.append({"path": b["path"],
                                      "label": f"Batch : {b['label']} — {b['count']} workflow(s)",
                                      "count": b["count"]})
        except Exception as e:
            self.status.showMessage(f"Liste des batchs indisponible : {e}")
        self.btn_refresh.setToolTip(
            ("Fichiers .json ignorés :\n" + "\n".join(f"- {n} : {r}" for n, r in skipped))
            if skipped else "")

        self.cmb_source.blockSignals(True)
        self.cmb_source.clear()
        idx = 0
        for i, src in enumerate(self._sources):
            self.cmb_source.addItem(src["label"])
            tip = str(src["path"]) if src["path"] else str(core.tutorial_json_path())
            self.cmb_source.setItemData(i, tip, Qt.ItemDataRole.ToolTipRole)
            if previous is not None and str(src["path"] or "") == str(previous or ""):
                idx = i
        self.cmb_source.setCurrentIndex(idx if self._sources else -1)
        self.cmb_source.blockSignals(False)

        if not self._sources:
            self._source_path = None
            self._entries = []
            try:
                where = core.tutorials_dir()
            except Exception:
                where = "(emplacement indisponible)"
            self.lbl_path.setText(f"Dossier : {where}")
            self.status.showMessage("Aucun fichier de workflows (.json) trouvé.")
            self._populate_initial()
            return
        self._load_entries(self._sources[idx]["path"])

    def select_source(self, path):
        """Affiche la source `path` (None = tutorial.json) si elle est listée."""
        if self._running:
            return
        for i, src in enumerate(self._sources):
            if str(src["path"] or "") == str(path or ""):
                if i != self.cmb_source.currentIndex():
                    self.cmb_source.setCurrentIndex(i)
                return

    def _on_source_changed(self, index):
        if self._running or index < 0 or index >= len(self._sources):
            return
        self._load_entries(self._sources[index]["path"])

    def _load_entries(self, path):
        self._source_path = path
        settings().setValue("validation/source", str(path) if path else "")
        try:
            shown = path if path is not None else core.tutorial_json_path()
            self.lbl_path.setText(f"Fichier : {shown}")
            name = Path(shown).name
        except Exception:
            self.lbl_path.setText("Fichier tutorial.json : emplacement indisponible.")
            name = "tutorial.json"
        loaded_msg = ""
        try:
            self._entries = core.load_tutorials(path)
            loaded_msg = f"{len(self._entries)} {self._kind()} chargé(s) depuis {name}."
        except Exception as e:
            self._entries = []
            self.status.showMessage(f"{name} introuvable ou invalide.")
            QMessageBox.warning(self, "Validation des workflows",
                                f"Impossible de lire {name} :\n{e}")
        self._row_results = {}
        self._populate_initial()
        if loaded_msg:
            self.status.showMessage(f"{loaded_msg} {self._rerun_msg}".strip())

    # ---------- Table ----------
    def _populate_initial(self):
        self.table.blockSignals(True)
        headers = core.workflow_headers(self._is_tutorial())
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(self._entries))
        for r, e in enumerate(self._entries):
            name = QTableWidgetItem(str(e.get("name", "") or e.get("key_name", "")))
            name.setFlags(name.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            name.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(r, W_NAME, name)
            self.table.setItem(r, W_DESC, QTableWidgetItem(str(e.get("description", ""))))
            self.table.setItem(r, W_OWS, QTableWidgetItem(str(e.get("ows_file", ""))))
            self.table.setItem(r, W_RES, QTableWidgetItem("—"))
            self.table.setItem(r, W_DET, QTableWidgetItem(""))
            self.table.setItem(r, W_DUR, QTableWidgetItem(""))
            tested = core.declared_widgets(e)
            it = QTableWidgetItem(", ".join(tested) if tested else "(non renseigné)")
            if not tested:
                it.setForeground(QColor("#999"))
            self.table.setItem(r, W_TESTED, it)
            self.table.setItem(r, W_RERUN, QTableWidgetItem(""))
        self.table.blockSignals(False)
        self.refresh_rerun()

    def refresh_rerun(self):
        """Recalcule la colonne « À relancer » à partir du dernier diagnostic
        (fenêtre parente), sans toucher aux résultats déjà obtenus."""
        self._rerun = {}
        parent = self.parent()
        modified, why = (parent.rerun_info() if parent is not None
                         and hasattr(parent, "rerun_info") else (None, "fenêtre de diagnostic absente"))
        self._rerun_available = modified is not None
        if modified is None:
            self._rerun_msg = f"À relancer : indisponible ({why})."
            self.lbl_rerun_info.setText(
                f"« À relancer » inactif : {why}. Cette colonne et le bouton « Cocher : à "
                "relancer » ne fonctionnent qu'après un diagnostic lancé avec « Comparer le "
                "diagnostic à la référence » et la couverture cochées.")
            self.lbl_rerun_info.setStyleSheet("color:#888; font-style:italic;")
        else:
            for r, e in enumerate(self._entries):
                names = core.rerun_for_entry(e, modified)
                if names:
                    self._rerun[r] = names
            n = len(self._rerun)
            self._rerun_msg = (f"{n} à relancer d'après le dernier diagnostic." if n
                               else "Aucun à relancer d'après le dernier diagnostic.")
            self.lbl_rerun_info.setText(
                f"« À relancer » d'après le dernier diagnostic (comparé à la référence) : "
                f"{n} workflow(s).")
            self.lbl_rerun_info.setStyleSheet("color:#e65100;" if n else "color:#2e7d32;")
        self.table.blockSignals(True)
        hdr = self.table.horizontalHeaderItem(W_RERUN)
        if hdr is not None:
            hdr.setText("À relancer (widget modifié)" if self._rerun_available
                        else "À relancer (comparaison inactive)")
            hdr.setToolTip("" if self._rerun_available else self.lbl_rerun_info.text())
        for r in range(self.table.rowCount()):
            names = self._rerun.get(r, [])
            it = QTableWidgetItem(", ".join(names) if self._rerun_available else "—")
            if names:
                it.setForeground(COLOR_MOD)
            elif not self._rerun_available:
                it.setForeground(QColor("#aaa"))
                it.setToolTip(core.RERUN_UNAVAILABLE)
            self.table.setItem(r, W_RERUN, it)
            for c in range(self.table.columnCount()):
                cell = self.table.item(r, c)
                if cell is not None:
                    cell.setBackground(BG_RERUN if names else QColor(0, 0, 0, 0))
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self._update_counter()
        self._update_buttons()

    def _set_result_cells(self, row, res):
        status = res.get("status", "") if isinstance(res, dict) else "ERREUR"
        detail = res.get("detail", "") if isinstance(res, dict) else "résultat inattendu"
        dur = res.get("duration_s", "") if isinstance(res, dict) else ""
        self.table.blockSignals(True)
        it = QTableWidgetItem(status)
        color = {"OK": COLOR_OK, "NOK": COLOR_NOK, "ERREUR": COLOR_ERR}.get(status)
        if color is not None:
            it.setForeground(color)
        cells = {W_RES: it, W_DET: QTableWidgetItem(str(detail)),
                 W_DUR: QTableWidgetItem("" if dur == "" else f"{dur}")}
        for c, cell in cells.items():
            if row in self._rerun:
                cell.setBackground(BG_RERUN)
            self.table.setItem(row, c, cell)
        self.table.blockSignals(False)

    def _checked_rows(self):
        return [r for r in range(self.table.rowCount())
                if self.table.item(r, W_NAME) is not None
                and self.table.item(r, W_NAME).checkState() == Qt.CheckState.Checked]

    def _set_all_checked(self, on):
        st = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            it = self.table.item(r, W_NAME)
            if it is not None:
                it.setCheckState(st)
        self.table.blockSignals(False)
        self._update_buttons()

    def check_rerun(self):
        """Coche uniquement les workflows à relancer (N7)."""
        if not self._rerun:
            self.status.showMessage(self._rerun_msg or "Aucun workflow à relancer.", 5000)
            return
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            it = self.table.item(r, W_NAME)
            if it is not None:
                it.setCheckState(Qt.CheckState.Checked if r in self._rerun
                                 else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.table.scrollToItem(self.table.item(min(self._rerun), W_NAME))
        self._update_buttons()
        self.status.showMessage(
            f"{len(self._rerun)} workflow(s) coché(s) — cliquez sur « Lancer les cochés ».")

    def _failed_rows(self):
        return [r for r, res in sorted(self._row_results.items())
                if res.get("status") in ("NOK", "ERREUR")]

    def _update_counter(self):
        st = [res.get("status", "") for res in self._row_results.values()]
        n_ok, n_nok, n_err = st.count("OK"), st.count("NOK"), st.count("ERREUR")
        not_run = len(self._entries) - len(self._row_results)
        rr = str(len(self._rerun)) if getattr(self, "_rerun_available", False) else "n/d"
        parts = [f"OK {n_ok}", f"NOK {n_nok}", f"Erreur {n_err}",
                 f"Non lancés {not_run}", f"À relancer {rr}"]
        self.lbl_counter.setText("  ·  ".join(parts))

    def _update_buttons(self):
        idle = not self._running
        has = bool(self._entries)
        self.cmb_source.setEnabled(idle)
        self.btn_refresh.setEnabled(idle)
        self.btn_run_all.setEnabled(idle and has)
        self.btn_run_checked.setEnabled(idle and bool(self._checked_rows()))
        self.btn_rerun_failed.setEnabled(idle and bool(self._failed_rows()))
        self.btn_check_all.setEnabled(idle and has)
        self.btn_check_none.setEnabled(idle and has)
        self.btn_check_rerun.setEnabled(idle and bool(self._rerun))
        self.btn_check_rerun.setToolTip(
            "Coche les workflows dont un widget testé (prod) a son .py modifié par\n"
            "rapport à la référence, d'après le dernier diagnostic."
            if getattr(self, "_rerun_available", False) else
            "Indisponible : relancez le diagnostic avec « Comparer le diagnostic à la\n"
            "référence » et la couverture cochées.")
        self.btn_cancel.setEnabled(self._running)
        self.btn_export.setEnabled(idle and bool(self._row_results))

    # ---------- Clic droit : ouvrir le workflow (V6) ----------
    def _table_menu(self, pos):
        it = self.table.itemAt(pos)
        if it is None or it.row() >= len(self._entries):
            return
        entry = self._entries[it.row()]
        path, tried = core.resolve_ows_path(entry)
        menu = QMenu(self)
        a_open = menu.addAction("Ouvrir le workflow dans Orange…")
        a_open.setEnabled(path is not None)
        a_dir = menu.addAction("Ouvrir le dossier du .ows")
        a_dir.setEnabled(path is not None)
        a_copy = menu.addAction("Copier le chemin du .ows")
        a_copy.setEnabled(path is not None)
        if path is None and entry.get("ows_file"):
            a_open.setText("Ouvrir le workflow dans Orange… (fichier .ows introuvable)")
            a_open.setToolTip("Chemins essayés :\n" + "\n".join(str(t) for t in tried))
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is a_open:
            self._open_in_orange(path)
        elif chosen is a_dir:
            open_in_file_manager(Path(path).parent)
        elif chosen is a_copy:
            QApplication.clipboard().setText(str(path))
            self.status.showMessage("Chemin copié dans le presse-papiers.", 3000)

    def _open_in_orange(self, path):
        r = QMessageBox.question(
            self, "Ouvrir le workflow",
            f"Ouvrir ce workflow dans Orange ?\n\n{path}\n\n"
            "Il s'ouvrira dans le Canvas (éventuellement dans une nouvelle fenêtre).")
        if r != QMessageBox.StandardButton.Yes:
            return
        # Fenêtre du Canvas = parent de la fenêtre de diagnostic.
        diag = self.parent()
        canvas = diag.parent() if diag is not None else None
        for meth in ("open_scheme_file", "load_scheme"):
            fn = getattr(canvas, meth, None)
            if callable(fn):
                try:
                    fn(str(path))
                    return
                except Exception as e:
                    QMessageBox.warning(self, "Ouverture impossible",
                                        f"Le Canvas n'a pas pu ouvrir le workflow :\n{e}")
                    return
        # Hors Canvas : application associée au .ows par le système.
        open_in_file_manager(path)

    # ---------- Exécution ----------
    def _request_cancel(self):
        self._cancel = True
        self.status.showMessage("Annulation demandée…")

    def _set_running(self, running):
        self._running = running
        self._update_buttons()

    def _run_all(self):
        self._run_indices(list(range(len(self._entries))))

    def _run_checked(self):
        rows = self._checked_rows()
        if not rows:
            QMessageBox.information(self, "Lancer les cochés", "Cochez au moins un workflow.")
            return
        self._run_indices(rows)

    def _run_failed(self):
        self._run_indices(self._failed_rows())

    def _run_indices(self, indices):
        if self._running or not self._entries or not indices:
            return
        self._cancel = False
        self._set_running(True)
        self._queue = list(indices)
        self._queue_total = len(self._queue)
        self._queue_done = 0
        self.progress.setMaximum(self._queue_total)
        self.progress.setValue(0)
        # L'API sera démarrée par run_tutorial ; on retient si elle tournait déjà,
        # pour ne fermer à la fin que ce que nous avons lancé.
        try:
            self._api_started_by_us = not core.api_is_running()
        except Exception:
            self._api_started_by_us = False
        self._run_next()

    def _run_next(self):
        if self._cancel or not self._queue:
            self._finish_batch()
            return
        self._current_row = self._queue.pop(0)
        entry = self._entries[self._current_row]
        self.status.showMessage(
            f"[{self._queue_done + 1}/{self._queue_total}] {entry.get('name', '')}")
        self._set_result_cells(self._current_row, {"status": "…", "detail": ""})
        try:
            Thread = core.thread_management_module().Thread
        except Exception as e:
            QMessageBox.critical(self, "Threads indisponibles",
                                 f"thread_management introuvable :\n{e}")
            self._finish_batch()
            return
        # run_tutorial est exécuté dans un thread : l'UI reste réactive.
        self._thread = Thread(core.run_tutorial, entry)
        self._thread.result.connect(self._on_result)
        self._thread.finish.connect(self._on_finish)
        self._thread.start()

    def _on_result(self, res):
        if not isinstance(res, dict):
            res = {"status": "ERREUR", "detail": "résultat inattendu"}
        res["rerun"] = (", ".join(self._rerun.get(self._current_row, []))
                        if self._rerun_available else core.RERUN_UNAVAILABLE)
        self._row_results[self._current_row] = res
        self._set_result_cells(self._current_row, res)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self._update_counter()

    def _on_finish(self):
        self._queue_done += 1
        self.progress.setValue(self._queue_done)
        self._thread = None
        self._run_next()

    def _finish_batch(self):
        suffix = " (annulé)" if self._cancel else ""
        if self._api_started_by_us:
            self.status.showMessage(f"Terminé{suffix} — arrêt de l'API…")
            QApplication.processEvents()
            try:
                core.stop_api()
            except Exception:
                pass
            self._api_started_by_us = False
        self.status.showMessage(f"Terminé{suffix}.")
        self._set_running(False)
        self._update_counter()

    def closeEvent(self, event):
        # Fermeture en cours de route : on arrête d'enchaîner et on ferme l'API
        # si nous l'avions démarrée.
        self._cancel = True
        if self._api_started_by_us:
            try:
                core.stop_api()
            except Exception:
                pass
            self._api_started_by_us = False
        try:
            settings().setValue("geometry/validation", self.saveGeometry())
        except Exception:
            pass
        super().closeEvent(event)

    # ---------- Export ----------
    def _export(self):
        results = [self._row_results[r] for r in sorted(self._row_results)]
        if not results:
            QMessageBox.information(self, "Exporter", "Aucun résultat à exporter.")
            return
        if self._is_tutorial():
            suggested = core.default_tutorial_output_name(".xlsx", prefix="tutoriels")
        else:
            suggested = core.default_tutorial_output_name(
                ".xlsx", prefix=f"batch_{Path(self._source_path).stem}")
        path = ask_export_path(self, "Exporter les résultats", suggested)
        if not path:
            return
        headers, rows = core.tutorial_results_to_rows(results, is_tutorial=self._is_tutorial())
        try:
            meta = list(core.collect_metadata())
            meta.append(("Colonne « À relancer »",
                         self._rerun_msg if self._rerun_available
                         else core.RERUN_UNAVAILABLE))
            p = core.write_rows(path, headers, rows, metadata=meta)
            self.status.showMessage(f"Exporté : {p}", 6000)
            QMessageBox.information(self, "Exporté", f"Résultats exportés :\n{p}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur d'export", str(e))


def main():
    app = QApplication(sys.argv)
    w = EditorMainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
