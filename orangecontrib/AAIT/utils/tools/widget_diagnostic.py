# widget_diagnostic.py
# ---------------------------------------------------------------------------
# Interface de diagnostic des widgets Orange, lançable depuis le Canvas.
#
# L'utilisateur peut choisir :
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
from AnyQt.QtGui import QAction, QKeySequence
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
        self.resize(1150, 720)

        self._running = False
        self._cancel = False
        self._headers = []
        self._rows = []
        self._metadata = []

        self._build_menu()
        self._build_ui()
        self._load_categories()

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

        self.cb_dates = QCheckBox("Inclure les colonnes de dates (création / modification)")
        self.cb_dates.setChecked(False)
        self.cb_dates.setToolTip(
            "Décoché : masque les colonnes 'Date Création' et 'Date Modification'."
        )
        opt_layout.addWidget(self.cb_dates)

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
        self.cb_dates.setEnabled(enabled)
        self.le_output.setEnabled(enabled)
        self.cat_list.setEnabled(enabled)

    def _run(self):
        if self._running:
            return

        cats = self._selected_categories()
        include = self.cb_packages.isChecked()
        include_dates = self.cb_dates.isChecked()
        out_path = self.le_output.text().strip()

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
                include_dates=include_dates,
                progress_callback=cb,
                should_cancel=lambda: self._cancel,
            )
            self._headers, self._rows = headers, rows
            self._populate_table(headers, rows)

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


def main():
    app = QApplication(sys.argv)
    w = EditorMainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()