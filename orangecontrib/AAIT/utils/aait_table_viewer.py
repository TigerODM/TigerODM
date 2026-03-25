#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
orange_tab_viewer.py
--------------------
Viewer autonome (AnyQt) pour fichiers .tab (Orange Data Mining) :
- Lit un .tab via Orange.data.Table.from_file()
- Convertit toutes les valeurs en chaînes pour l'affichage
- Affiche une table moderne (thème sombre, tri par colonne)
- Colorise les cellules si valeur = "[color]texte" (ex. [red]Erreur)
- Optionnel : auto-refresh sur modification du fichier --watch <ms>

Dépendances : AnyQt, Orange3
"""

from __future__ import annotations
import sys, os, argparse, re
from typing import List, Tuple, Optional, Dict

from AnyQt.QtCore import Qt, QTimer, QFileSystemWatcher, QDateTime, QSize
from AnyQt.QtGui import QPalette, QColor, QFont, QStandardItemModel, QStandardItem, QAction
from AnyQt.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFileDialog, QTableView, QStatusBar, QToolBar, QAbstractItemView, QStyleFactory, QHeaderView
)

from Orange.data import Table, Domain

# ---------- Colorisation via tag "[color]texte" ----------
COLOR_TAG_RE = re.compile(r"^\s*\[(?P<color>[a-zA-Z]+)\]\s*(?P<text>.*)\s*$")

NAMED_COLORS: Dict[str, QColor] = {
    "red": QColor("#d84a4a"),
    "green": QColor("#2da44e"),
    "blue": QColor("#2f81f7"),
    "orange": QColor("#f29900"),
    "yellow": QColor("#e3b341"),
    "purple": QColor("#8957e5"),
    "magenta": QColor("#d527b7"),
    "pink": QColor("#ff5ca7"),
    "teal": QColor("#1f8a70"),
    "cyan": QColor("#00acc1"),
    "grey": QColor("#5b6470"),
    "gray": QColor("#5b6470"),
    "black": QColor("#111111"),
    "white": QColor("#ffffff"),
}

def best_foreground_for(bg: QColor) -> QColor:
    r, g, b = bg.red(), bg.green(), bg.blue()
    yiq = ((r*299) + (g*587) + (b*114)) / 1000
    return QColor("#000000") if yiq > 150 else QColor("#ffffff")

# ---------- Palette sombre ----------
def nice_dark_palette() -> QPalette:
    p = QPalette()
    bg = QColor(11, 11, 15)
    panel = QColor(17, 23, 31)
    text = QColor(234, 234, 234)
    muted = QColor(170, 184, 200)
    highlight = QColor(30, 96, 180)
    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.Base, QColor(15, 20, 27))
    p.setColor(QPalette.AlternateBase, QColor(19, 26, 34))
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, panel)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.Highlight, highlight)
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ToolTipBase, panel)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.PlaceholderText, muted)
    return p

# ---------- Conversion Orange Table -> matrice de chaînes ----------
def orange_table_to_strings(data: Table) -> Tuple[List[str], List[List[str]]]:
    """
    Convertit une Orange.data.Table en :
      - headers: liste de noms de colonnes
      - rows: liste de lignes (valeurs converties en str)
    Concatène attributes + class_vars + metas (dans cet ordre).
    """
    dom: Domain = data.domain
    attrs = list(dom.attributes)
    class_vars = list(dom.class_vars) if dom.class_vars else []
    metas = list(dom.metas) if dom.metas else []

    headers = [v.name for v in attrs] + [v.name for v in class_vars] + [str(v.name) for v in metas]

    cols = []
    for var in attrs + class_vars:
        col, _ = data.get_column_view(var)
        cols.append(col)
    for mv in metas:
        col, _ = data.get_column_view(mv)
        cols.append(col)

    n_rows = len(data)
    n_cols = len(cols)

    rows: List[List[str]] = []
    for i in range(n_rows):
        out_row: List[str] = []
        for j in range(n_cols):
            val = cols[j][i]
            s = "" if val is None else str(val)
            if s.lower() == "nan":
                s = ""
            out_row.append(s)
        rows.append(out_row)
    return headers, rows

# ---------- Modèle Qt ----------
class StringTableModel(QStandardItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.enable_color_tags: bool = True

    def load(self, headers: List[str], rows: List[List[str]]):
        self.clear()
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(rows))

        for r, row in enumerate(rows):
            for c, raw_value in enumerate(row):
                display_text, bg_color = self._parse_color_tag(raw_value) if self.enable_color_tags else (raw_value, None)
                item = QStandardItem(display_text)
                item.setEditable(False)
                if bg_color is not None:
                    fg = best_foreground_for(bg_color)
                    item.setBackground(bg_color)
                    item.setForeground(fg)
                self.setItem(r, c, item)

    @staticmethod
    def _parse_color_tag(value: str):
        if not isinstance(value, str):
            return str(value), None
        m = COLOR_TAG_RE.match(value)
        if not m:
            return value, None
        color_name = m.group("color").strip().lower()
        text = m.group("text")
        qcolor = NAMED_COLORS.get(color_name)
        return text, qcolor

# ---------- Fenêtre principale ----------
class MainWindow(QMainWindow):
    def __init__(self, path: Optional[str], watch_ms: Optional[int]):
        super().__init__()
        self.setWindowTitle("Orange .tab Viewer — AnyQt")
        self.setMinimumSize(QSize(1000, 600))

        self.path: Optional[str] = path
        self.watch_ms: Optional[int] = watch_ms
        self.last_mtime: Optional[float] = None

        self._apply_style()
        self._setup_ui()
        self._setup_toolbar()
        self._setup_watch()

        if self.path:
            self.load_tab(self.path)

    def _apply_style(self):
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        QApplication.setPalette(nice_dark_palette())
        f = QFont(); f.setPointSize(10)
        QApplication.setFont(f)

    def _setup_ui(self):
        central = QWidget(self); self.setCentralWidget(central)
        lay = QVBoxLayout(central); lay.setContentsMargins(12, 10, 12, 10); lay.setSpacing(8)

        top = QHBoxLayout()
        self.info = QLabel("Aucun fichier chargé")
        self.info.setStyleSheet("color:#9ad0ff;")
        self.color_hint = QLabel("Tags couleur : [red]/[green]/[blue]/[orange]/…")
        self.color_hint.setStyleSheet("color:#8aa0b2;")
        top.addWidget(self.info, 1); top.addWidget(self.color_hint, 0)
        lay.addLayout(top)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setCornerButtonEnabled(False)
        self.table.setShowGrid(False)
        self.table.setStyleSheet("""
            QTableView {
                gridline-color: #1f2630;
                selection-background-color: #1e60b4;
                selection-color: #ffffff;
                outline: 0;
                border: 1px solid #2a3442;
                border-radius: 10px;
                background: #0f141b;
            }
            QHeaderView::section {
                background: #111827;
                color: #9ad0ff;
                border: 0;
                padding: 8px;
            }
        """)
        self.model = StringTableModel(self)
        self.table.setModel(self.model)
        lay.addWidget(self.table, 1)

        sb = QStatusBar(self)
        sb.setStyleSheet("QStatusBar{border-top:1px solid #1f2630;}")
        self.setStatusBar(sb)

    def _setup_toolbar(self):
        tb = QToolBar("Fichier", self)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        act_open = QAction("Ouvrir…", self)
        act_open.triggered.connect(self.choose_file)
        tb.addAction(act_open)

        act_reload = QAction("Recharger", self)
        act_reload.triggered.connect(self.reload)
        tb.addAction(act_reload)

        tb.addSeparator()

        act_quit = QAction("Quitter", self)
        act_quit.triggered.connect(self.close)
        tb.addAction(act_quit)

    def _setup_watch(self):
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._on_fs_change)
        self.watcher.directoryChanged.connect(self._on_fs_change)

        self.poll = QTimer(self)
        self.poll.timeout.connect(self._check_mtime)
        if self.watch_ms and self.watch_ms > 0:
            self.poll.start(max(300, self.watch_ms))

    # ---- Fichier .tab ----
    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un .tab Orange", os.path.dirname(self.path or ".") or ".", "Orange .tab (*.tab);;Tous les fichiers (*.*)")
        if not path:
            return
        self.load_tab(path)

    def load_tab(self, path: str):
        try:
            data = Table.from_file(path)
        except Exception as e:
            self.statusBar().showMessage(f"Erreur de lecture: {e}", 6000)
            return

        headers, rows = orange_table_to_strings(data)
        self.model.load(headers, rows)
        self.table.resizeColumnsToContents()
        for c in range(self.model.columnCount()):
            w = max(self.table.columnWidth(c), 80)
            self.table.setColumnWidth(c, min(w, 420))

        self.path = path
        self.last_mtime = self._safe_mtime(path)
        self._watch_register(path)

        ts = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.info.setText(f"{os.path.basename(path)} — {len(rows)} lignes, {len(headers)} colonnes  |  MAJ {ts}")
        self.statusBar().showMessage("Chargé.", 2000)

    def reload(self):
        if not self.path:
            return
        self.load_tab(self.path)

    # ---- Watch helpers ----
    def _watch_register(self, path: str):
        try:
            self.watcher.removePaths(self.watcher.files() + self.watcher.directories())
        except Exception:
            pass
        if os.path.isfile(path):
            self.watcher.addPath(path)
        folder = os.path.dirname(path) or "."
        if os.path.isdir(folder):
            self.watcher.addPath(folder)

    def _on_fs_change(self, _):
        # petit délai pour laisser l'éditeur terminer l'écriture
        QTimer.singleShot(150, self.reload)

    def _safe_mtime(self, path: str) -> Optional[float]:
        try:
            return os.path.getmtime(path)
        except Exception:
            return None

    def _check_mtime(self):
        if not self.path:
            return
        new_m = self._safe_mtime(self.path)
        if new_m is None:
            return
        if self.last_mtime is None or new_m != self.last_mtime:
            self.last_mtime = new_m
            self.reload()

# ---------- CLI ----------
def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Viewer .tab Orange (casting string + color tags).")
    ap.add_argument("tab", nargs="?", help="Chemin du fichier .tab")
    ap.add_argument("--watch", type=int, default=0, help="Intervalle de vérification (ms). 0 = désactivé.")
    return ap.parse_args(argv)

def main():
    args = parse_args(sys.argv[1:])
    app = QApplication(sys.argv)
    win = MainWindow(path=args.tab, watch_ms=args.watch)
    win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
