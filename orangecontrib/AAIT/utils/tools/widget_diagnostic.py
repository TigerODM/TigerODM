# widget_diagnostic.py
# ---------------------------------------------------------------------------
# Interface de diagnostic des widgets Orange, lançable depuis le Canvas.
#
# Style calqué sur le mini-Notepad (AnyQt, EditorMainWindow lié à une fenêtre
# parente). L'utilisateur peut choisir :
#   - les catégories à analyser (vide = toutes),
#   - le grain de l'analyse (ajout ou non des librairies pip par widget),
#   - le fichier de sortie (.csv / .xlsx / .tab).
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

import sys
import traceback
from pathlib import Path

from AnyQt.QtCore import Qt
from AnyQt.QtGui import QAction, QColor, QKeySequence
from AnyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
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


class EditorMainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TigerODM — Diagnostic des widgets")
        self.resize(1400, 880)
        self.setMinimumSize(900, 600)

        self._running = False
        self._cancel = False
        self._headers = []
        self._rows = []
        self._metadata = []
        self._diagnostic_done = False
        self._tutorial_win = None

        self._build_menu()
        self._build_ui()
        self._load_categories()
        self._refresh_ref_status()

    # ---------- Menu ----------
    def _build_menu(self):
        m_file = self.menuBar().addMenu("Fichier")

        self.act_export = QAction("Exporter les résultats…", self)
        self.act_export.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.act_export.triggered.connect(self._export_results)
        self.act_export.setEnabled(False)
        m_file.addAction(self.act_export)

        m_file.addSeparator()
        act_quit = QAction("Fermer", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Close)
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        # --- Bandeau options (catégories + grain) ---
        top = QHBoxLayout()

        # Catégories
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

        # Grain + sortie
        gb_opt = QGroupBox("Options d'analyse")
        opt_layout = QVBoxLayout(gb_opt)

        self.cb_packages = QCheckBox("Analyser les librairies pip de chaque widget (grain fin)")
        self.cb_packages.setChecked(False)
        self.cb_packages.setToolTip(
            "Coché : une ligne par (widget, librairie) — analyse récursive des imports.\n"
            "Décoché : une ligne par widget, sans librairies — beaucoup plus rapide."
        )
        opt_layout.addWidget(self.cb_packages)

        opt_layout.addWidget(QLabel("Fichier de sortie :"))
        out_row = QHBoxLayout()
        self.le_output = QLineEdit()
        self.le_output.setPlaceholderText("Optionnel — laisse vide pour seulement afficher")
        btn_browse = QPushButton("Parcourir…")
        btn_browse.clicked.connect(self._choose_output)
        out_row.addWidget(self.le_output, 1)
        out_row.addWidget(btn_browse)
        opt_layout.addLayout(out_row)
        opt_layout.addWidget(QLabel("Formats : .csv (défaut), .xlsx, .tab"))

        # --- Référence / comparaison ---
        opt_layout.addWidget(QLabel("Référence (versions pip + hash des .py) :"))
        self.lbl_ref_path = QLabel()
        self.lbl_ref_path.setWordWrap(True)
        self.lbl_ref_path.setStyleSheet("color:#666;")
        opt_layout.addWidget(self.lbl_ref_path)
        self.lbl_ref_status = QLabel()
        opt_layout.addWidget(self.lbl_ref_status)

        ref_btns = QHBoxLayout()
        self.cb_compare = QCheckBox("Comparer le diagnostic à la référence")
        self.cb_compare.setToolTip(
            "Si la référence existe, ajoute les colonnes '.py modifié ?'\n"
            "et 'Version lib (réf → actuelle)'."
        )
        self.btn_save_ref = QPushButton("Enregistrer / mettre à jour la référence")
        self.btn_save_ref.setToolTip(
            "Fige les versions pip installées et le hash des .py de widgets\n"
            "à l'emplacement fixe (aait_store/Parameters)."
        )
        self.btn_save_ref.clicked.connect(self._save_reference)
        ref_btns.addWidget(self.cb_compare, 1)
        ref_btns.addWidget(self.btn_save_ref)
        opt_layout.addLayout(ref_btns)

        opt_layout.addStretch(1)

        # Actions
        act_row = QHBoxLayout()
        self.btn_run = QPushButton("Lancer le diagnostic")
        self.btn_run.clicked.connect(self._run)
        self.btn_save = QPushButton("Enregistrer")
        self.btn_save.setToolTip(
            "Enregistre le diagnostic courant dans le fichier de sortie.\n"
            "Si le champ est vide, ouvre une boîte de dialogue."
        )
        self.btn_save.clicked.connect(self._save_diagnostic)
        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.clicked.connect(self._request_cancel)
        self.btn_cancel.setEnabled(False)
        act_row.addWidget(self.btn_run)
        act_row.addWidget(self.btn_save)
        act_row.addWidget(self.btn_cancel)
        opt_layout.addLayout(act_row)

        top.addWidget(gb_opt, 3)
        root.addLayout(top)

        # --- Progression ---
        self.progress = QProgressBar()
        self.progress.setValue(0)
        root.addWidget(self.progress)

        # --- Table de résultats ---
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        # --- Bouton tutoriels (tout en bas, grisé tant que pas de diagnostic) ---
        self.btn_tutorials = QPushButton("Lancer les tutoriels (validation OK/NOK)…")
        self.btn_tutorials.setEnabled(False)
        self.btn_tutorials.setToolTip(
            "Disponible une fois le premier diagnostic terminé.\n"
            "Ouvre une fenêtre pour lancer les workflows tutoriels et comparer\n"
            "leur sortie à la sortie attendue (OK/NOK)."
        )
        self.btn_tutorials.clicked.connect(self._open_tutorials)
        root.addWidget(self.btn_tutorials)

        self.setCentralWidget(central)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Prêt.")

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

    # ---------- Sortie ----------
    def _choose_output(self):
        include = self.cb_packages.isChecked()
        suggested = core.default_output_name(include_packages=include, ext=".csv")
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Fichier de sortie", suggested,
            "CSV (*.csv);;Excel (*.xlsx);;Orange tab (*.tab);;Tous les fichiers (*.*)",
        )
        if path_str:
            self.le_output.setText(path_str)

    def _refresh_ref_status(self):
        try:
            p = core.reference_path()
            self.lbl_ref_path.setText(f"Emplacement : {p}")
            if core.reference_exists():
                self.lbl_ref_status.setText("✔ Référence présente.")
                self.lbl_ref_status.setStyleSheet("color:#2e7d32;")
                self.cb_compare.setEnabled(True)
            else:
                self.lbl_ref_status.setText("✖ Aucune référence enregistrée.")
                self.lbl_ref_status.setStyleSheet("color:#c62828;")
                self.cb_compare.setChecked(False)
                self.cb_compare.setEnabled(False)
        except Exception as e:
            self.lbl_ref_path.setText("Emplacement de la référence indisponible.")
            self.lbl_ref_status.setText(str(e))

    def _save_reference(self):
        if self._running:
            return

        cats = self._selected_categories()
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

    def _save_diagnostic(self):
        """Enregistre le diagnostic courant. Utilise le chemin du champ
        'Fichier de sortie' ; si vide, ouvre une boîte de dialogue."""
        if not self._rows:
            QMessageBox.information(
                self, "Enregistrer",
                "Aucun diagnostic à enregistrer pour le moment.\n"
                "Lance d'abord une analyse.",
            )
            return

        path = self.le_output.text().strip()
        if not path:
            suggested = core.default_output_name(
                include_packages=("Package pip" in self._headers), ext=".csv"
            )
            path, _ = QFileDialog.getSaveFileName(
                self, "Enregistrer le diagnostic", suggested,
                "CSV (*.csv);;Excel (*.xlsx);;Orange tab (*.tab);;Tous les fichiers (*.*)",
            )
            if not path:
                return
            self.le_output.setText(path)

        try:
            p = core.write_rows(path, self._headers, self._rows, metadata=self._metadata)
            self.status.showMessage(f"Enregistré : {p}", 4000)
            QMessageBox.information(
                self, "Enregistré",
                f"Diagnostic enregistré ({len(self._rows)} ligne(s)) :\n{p}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur d'enregistrement", str(e))

    def _export_results(self):
        if not self._rows:
            QMessageBox.information(self, "Export", "Aucun résultat à exporter.")
            return
        suggested = self.le_output.text().strip() or core.default_output_name(
            include_packages=("Package pip" in self._headers), ext=".csv"
        )
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Exporter les résultats", suggested,
            "CSV (*.csv);;Excel (*.xlsx);;Orange tab (*.tab);;Tous les fichiers (*.*)",
        )
        if not path_str:
            return
        try:
            p = core.write_rows(path_str, self._headers, self._rows, metadata=self._metadata)
            self.status.showMessage(f"Exporté : {p}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Erreur d'export", str(e))

    # ---------- Exécution ----------
    def _request_cancel(self):
        self._cancel = True
        self.status.showMessage("Annulation demandée…")

    def _set_controls_enabled(self, enabled: bool):
        self.btn_run.setEnabled(enabled)
        self.cb_packages.setEnabled(enabled)
        self.le_output.setEnabled(enabled)
        self.cat_list.setEnabled(enabled)
        self.cb_compare.setEnabled(enabled)
        self.btn_save_ref.setEnabled(enabled)
        # Le bouton tutoriels ne s'active qu'une fois un diagnostic terminé,
        # et jamais pendant qu'une opération tourne.
        self.btn_tutorials.setEnabled(enabled and self._diagnostic_done)

    def _run(self):
        if self._running:
            return

        cats = self._selected_categories()
        include = self.cb_packages.isChecked()
        out_path = self.le_output.text().strip()

        # Référence (comparaison) éventuelle
        reference = None
        if self.cb_compare.isChecked():
            if not core.reference_exists():
                QMessageBox.warning(
                    self, "Référence absente",
                    "Aucune référence enregistrée.\n"
                    "Clique « Enregistrer / mettre à jour la référence » d'abord.",
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

        self._running = True
        self._cancel = False
        self._set_controls_enabled(False)
        self.btn_cancel.setEnabled(True)
        self.act_export.setEnabled(False)
        self.progress.setValue(0)
        self.status.showMessage("Analyse en cours…")

        # Métadonnées du test, figées au moment du lancement.
        self._metadata = core.collect_metadata()

        def cb(done, total, message):
            if total > 0:
                self.progress.setMaximum(total)
                self.progress.setValue(done)
            self.status.showMessage(f"[{done}/{total}] {message}")
            # Garde l'UI réactive (et permet le clic sur "Annuler").
            # L'analyse importe des modules de widgets : on reste donc dans
            # le thread principal pour éviter tout objet Qt hors GUI-thread.
            QApplication.processEvents()

        try:
            headers, rows = core.run_diagnostic(
                selected_categories=cats,
                include_packages=include,
                reference=reference,
                progress_callback=cb,
                should_cancel=lambda: self._cancel,
            )
            self._headers, self._rows = headers, rows
            self._populate_table(headers, rows)
            self._diagnostic_done = True

            if self._cancel:
                self.status.showMessage(f"Annulé — {len(rows)} ligne(s) partielle(s).")
            elif out_path:
                p = core.write_rows(out_path, headers, rows, metadata=self._metadata)
                self.status.showMessage(f"Terminé — {len(rows)} ligne(s) — enregistré : {p}")
                QMessageBox.information(
                    self, "Diagnostic terminé",
                    f"{len(rows)} ligne(s) générée(s).\nFichier enregistré :\n{p}",
                )
            else:
                self.status.showMessage(f"Terminé — {len(rows)} ligne(s) (non enregistré).")

            self.act_export.setEnabled(bool(rows))

        except Exception:
            QMessageBox.critical(self, "Erreur", traceback.format_exc())
            self.status.showMessage("Erreur durant l'analyse.")
        finally:
            self._running = False
            self._set_controls_enabled(True)
            self.btn_cancel.setEnabled(False)
            self._refresh_ref_status()

    def _populate_table(self, headers, rows):
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(headers)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem("" if val is None else str(val)))
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        if header.count():
            header.setStretchLastSection(True)
        self.table.setSortingEnabled(True)

    # ---------- Tutoriels ----------
    def _open_tutorials(self):
        if self._tutorial_win is None:
            self._tutorial_win = TutorialRunnerWindow(self)
        self._tutorial_win.reload()
        self._tutorial_win.show()
        self._tutorial_win.raise_()
        self._tutorial_win.activateWindow()


class TutorialRunnerWindow(QMainWindow):
    """Fenêtre secondaire : lance les workflows tutoriels un par un,
    compare la sortie à la sortie attendue (OK/NOK) et exporte en Excel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TigerODM — Tutoriels (validation OK/NOK)")
        self.resize(1240, 780)
        self.setMinimumSize(820, 520)
        self._running = False
        self._cancel = False
        self._entries = []
        self._results = []
        self._thread = None
        self._queue = []
        self._queue_total = 0
        self._queue_done = 0
        self._current_row = -1
        self._n_ok = 0
        self._api_started_by_us = False
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        self.lbl_path = QLabel()
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setStyleSheet("color:#666;")
        root.addWidget(self.lbl_path)

        btns = QHBoxLayout()
        self.btn_run_all = QPushButton("Lancer tous")
        self.btn_run_all.clicked.connect(self._run_all)
        self.btn_run_sel = QPushButton("Lancer la sélection")
        self.btn_run_sel.clicked.connect(self._run_selected)
        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._request_cancel)
        self.btn_export = QPushButton("Exporter Excel…")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export)
        btns.addWidget(self.btn_run_all)
        btns.addWidget(self.btn_run_sel)
        btns.addWidget(self.btn_cancel)
        btns.addStretch(1)
        btns.addWidget(self.btn_export)
        root.addLayout(btns)

        self.progress = QProgressBar()
        root.addWidget(self.progress)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        self.setCentralWidget(central)
        self.status = QStatusBar()
        self.setStatusBar(self.status)

    # ---------- Chargement ----------
    def reload(self):
        try:
            self.lbl_path.setText(f"Fichier : {core.tutorial_json_path()}")
        except Exception:
            self.lbl_path.setText("Fichier tutorial.json : emplacement indisponible.")
        try:
            self._entries = core.load_tutorials()
            self.status.showMessage(f"{len(self._entries)} tutoriel(s) chargé(s).")
        except Exception as e:
            self._entries = []
            self.status.showMessage("tutorial.json introuvable ou invalide.")
            QMessageBox.warning(
                self, "Tutoriels",
                f"Impossible de lire tutorial.json :\n{e}",
            )
        self._results = []
        self._populate_initial()

    def _populate_initial(self):
        self.table.setColumnCount(len(core.TUTORIAL_HEADERS))
        self.table.setHorizontalHeaderLabels(core.TUTORIAL_HEADERS)
        self.table.setRowCount(len(self._entries))
        for r, e in enumerate(self._entries):
            self.table.setItem(r, 0, QTableWidgetItem(str(e.get("name", ""))))
            self.table.setItem(r, 1, QTableWidgetItem(str(e.get("description", ""))))
            self.table.setItem(r, 2, QTableWidgetItem(str(e.get("ows_file", ""))))
            self.table.setItem(r, 3, QTableWidgetItem("—"))
            self.table.setItem(r, 4, QTableWidgetItem(""))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.btn_export.setEnabled(False)

    # ---------- Exécution ----------
    def _request_cancel(self):
        self._cancel = True
        self.status.showMessage("Annulation demandée…")

    def _set_running(self, running):
        self._running = running
        self.btn_run_all.setEnabled(not running)
        self.btn_run_sel.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.btn_export.setEnabled(not running and bool(self._results))

    def _set_status_cell(self, row, status, detail):
        it = QTableWidgetItem(status)
        color = {"OK": "#2e7d32", "NOK": "#c62828", "ERREUR": "#e65100"}.get(status)
        if color:
            it.setForeground(QColor(color))
        self.table.setItem(row, 3, it)
        self.table.setItem(row, 4, QTableWidgetItem(detail))

    def _run_all(self):
        self._run_indices(list(range(len(self._entries))))

    def _run_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if not rows:
            QMessageBox.information(self, "Sélection", "Sélectionne au moins une ligne.")
            return
        self._run_indices(rows)

    def _run_indices(self, indices):
        if self._running or not self._entries or not indices:
            return
        self._cancel = False
        self._set_running(True)
        self._queue = list(indices)
        self._queue_total = len(self._queue)
        self._queue_done = 0
        self._results = []
        self._n_ok = 0
        self.progress.setMaximum(self._queue_total)
        self.progress.setValue(0)
        # L'API sera démarrée par run_tutorial ; on retient si elle tournait
        # déjà, pour ne fermer à la fin que ce que nous avons lancé.
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
        self._set_status_cell(self._current_row, "…", "")
        try:
            Thread = core.thread_management_module().Thread
        except Exception as e:
            QMessageBox.critical(self, "Threads indisponibles",
                                 f"thread_management introuvable :\n{e}")
            self._finish_batch()
            return
        # run_tutorial est exécuté dans un thread : l'UI reste réactive.
        self._thread = Thread(core.run_tutorial, entry)
        self._thread.result.connect(self._on_tutorial_result)
        self._thread.finish.connect(self._on_tutorial_finish)
        self._thread.start()

    def _on_tutorial_result(self, res):
        if isinstance(res, dict):
            self._results.append(res)
            if res.get("status") == "OK":
                self._n_ok += 1
            self._set_status_cell(self._current_row,
                                  res.get("status", ""), res.get("detail", ""))
        else:
            self._set_status_cell(self._current_row, "ERREUR", "résultat inattendu")
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _on_tutorial_finish(self):
        self._queue_done += 1
        self.progress.setValue(self._queue_done)
        self._thread = None
        self._run_next()

    def _finish_batch(self):
        total = len(self._results)
        suffix = " (annulé)" if self._cancel else ""
        # Fermer l'API si c'est nous qui l'avons démarrée.
        if self._api_started_by_us:
            self.status.showMessage(f"Terminé{suffix} — {self._n_ok}/{total} OK — arrêt de l'API…")
            QApplication.processEvents()
            try:
                core.stop_api()
            except Exception:
                pass
            self._api_started_by_us = False
        self.status.showMessage(f"Terminé{suffix} — {self._n_ok}/{total} OK")
        self._set_running(False)

    def closeEvent(self, event):
        # Si on ferme en cours de route : on arrête d'enchaîner et on ferme
        # l'API si nous l'avions démarrée.
        self._cancel = True
        if self._api_started_by_us:
            try:
                core.stop_api()
            except Exception:
                pass
            self._api_started_by_us = False
        super().closeEvent(event)

    # ---------- Export ----------
    def _export(self):
        if not self._results:
            QMessageBox.information(self, "Export", "Aucun résultat à exporter.")
            return
        suggested = core.default_tutorial_output_name(".xlsx")
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Exporter les résultats", suggested,
            "Excel (*.xlsx);;CSV (*.csv);;Tous les fichiers (*.*)",
        )
        if not path_str:
            return
        headers, rows = core.tutorial_results_to_rows(self._results)
        try:
            p = core.write_rows(path_str, headers, rows, metadata=core.collect_metadata())
            self.status.showMessage(f"Exporté : {p}", 4000)
            QMessageBox.information(self, "Export", f"Résultats exportés :\n{p}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur d'export", str(e))


def main():
    app = QApplication(sys.argv)
    w = EditorMainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
