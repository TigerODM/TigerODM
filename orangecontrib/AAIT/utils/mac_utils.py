import platform


if platform.system() == "Darwin":
    import os
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        from Orange.widgets.orangecontrib.AAIT.utils import SimpleDialogQt
    else:
        from orangecontrib.AAIT.utils import SimpleDialogQt
    import sys
    import time
    import shutil
    import subprocess
    import re

    from AnyQt.QtCore import QObject, QThread, Signal, Slot, Qt
    from AnyQt.QtWidgets import (
        QApplication,QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QMessageBox
    )


    # ---------------------- Worker de copie (thread de fond) ----------------------
    class _CopyWorker(QObject):
        progress = Signal(int, float)   # (pct 0..100, speed_MBps)
        finished = Signal(bool)         # True = success, False = cancelled
        errored  = Signal(str)          # message d'erreur

        def __init__(self, src: str, dest: str, chunk_mb: int = 8):
            super().__init__()
            self.src  = os.path.abspath(src)
            self.dest = os.path.abspath(dest)
            self._cancel = False
            self._chunk = chunk_mb * 1024 * 1024

        @Slot()
        def cancel(self):
            self._cancel = True

        def _iter_files(self, src):
            if os.path.isfile(src):
                yield ("", src)
                return
            # Conserver le répertoire top-level sous dest (comme Finder)
            for root, _, files in os.walk(src):
                rel = os.path.relpath(root, os.path.dirname(src))
                for name in files:
                    yield (rel, os.path.join(root, name))

        def _total_size(self, items):
            total = 0
            for _, p in items:
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
            return total

        @Slot()
        def run(self):
            try:
                if not os.path.exists(self.src):
                    raise FileNotFoundError(f"Source not found: {self.src}")
                os.makedirs(self.dest, exist_ok=True)

                # Liste matérielle pour total + parcours
                items = list(self._iter_files(self.src))
                if not items:
                    # Rien à copier : succès immédiat
                    self.progress.emit(100, 0.0)
                    self.finished.emit(True)
                    return

                total = self._total_size(items)
                done  = 0
                last_t = time.time()
                last_b = 0

                topname = os.path.basename(os.path.normpath(self.src))
                is_dir  = os.path.isdir(self.src)

                for relroot, srcfile in items:
                    if self._cancel:
                        self.finished.emit(False)
                        return

                    rel = relroot if relroot != "." else (topname if is_dir else "")
                    tgt_dir  = os.path.join(self.dest, rel) if rel else self.dest
                    os.makedirs(tgt_dir, exist_ok=True)
                    tgt_file = os.path.join(tgt_dir, os.path.basename(srcfile))

                    try:
                        with open(srcfile, "rb") as fi, open(tgt_file, "wb") as fo:
                            while True:
                                if self._cancel:
                                    self.finished.emit(False)
                                    return
                                buf = fi.read(self._chunk)
                                if not buf:
                                    break
                                fo.write(buf)
                                done += len(buf)

                                # mise à jour ~5x/s
                                now = time.time()
                                dt  = now - last_t
                                if dt >= 0.2:
                                    db = done - last_b
                                    speed = (db / dt) / (1024 * 1024) if dt > 0 else 0.0
                                    pct = 100 if total == 0 else int(done * 100 / max(1, total))
                                    self.progress.emit(pct, speed)
                                    last_t, last_b = now, done

                        # métadonnées (mtime, perms si possible)
                        try:
                            shutil.copystat(srcfile, tgt_file, follow_symlinks=True)
                        except Exception:
                            pass

                        # flush final sur ce fichier
                        pct = 100 if total == 0 else int(done * 100 / max(1, total))
                        self.progress.emit(pct, 0.0)

                    except Exception as e:
                        self.errored.emit(str(e))
                        return

                self.finished.emit(True)

            except Exception as e:
                self.errored.emit(str(e))


    # ---------------------- Boîte de dialogue de progression ----------------------
    class _CopyDialog(QDialog):
        def __init__(self, src: str, dest: str, title: str = "Copy in progress", parent=None):
            super().__init__(parent)
            self.setWindowTitle(title)
            self.setModal(True)
            self.resize(600, 180)

            # libellés
            self._label_paths = QLabel(
                f"<b>Source</b>: {src}<br><b>Destination</b>: {dest}"
            )
            self._label_paths.setTextFormat(Qt.RichText)
            self._bar = QProgressBar()
            self._bar.setRange(0, 100)
            self._bar.setValue(0)

            self._info = QLabel("0% — 0.0 MB/s")
            self._info.setStyleSheet("color:#0a58ca;")
            self._ascii = QLabel("░" * 40)
            self._ascii.setStyleSheet("font-family: Menlo, Monaco, Consolas, monospace;")

            self._btn_cancel = QPushButton("Annuler")
            self._btn_cancel.setStyleSheet("background:#f8d7da;color:#842029;")
            self._btn_cancel.clicked.connect(self._on_cancel)

            lay = QVBoxLayout(self)
            lay.addWidget(self._label_paths)
            lay.addWidget(self._bar)
            lay.addWidget(self._info)
            lay.addWidget(self._ascii)
            lay.addWidget(self._btn_cancel, alignment=Qt.AlignRight)

            # thread & worker
            self._thread = QThread(self)
            self._worker = _CopyWorker(src, dest)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)

            self._worker.progress.connect(self._on_progress)
            self._worker.finished.connect(self._on_finished)
            self._worker.errored.connect(self._on_error)

            self._result = None  # True / False / None (erreur)

        def start(self):
            self._thread.start()

        @Slot(int, float)
        def _on_progress(self, pct: int, mbps: float):
            self._bar.setValue(pct)
            self._info.setText(f"{pct}% — {mbps:.1f} MB/s")
            filled = min(40, int(pct * 40 / 100))
            self._ascii.setText("█" * filled + "░" * (40 - filled))

        @Slot(bool)
        def _on_finished(self, ok: bool):
            self._result = ok
            self._thread.quit()
            self._thread.wait(2000)
            self.accept()

        @Slot(str)
        def _on_error(self, msg: str):
            self._result = None
            self._thread.quit()
            self._thread.wait(2000)
            QMessageBox.critical(self, "Erreur de copie", msg)
            self.reject()

        @Slot()
        def _on_cancel(self):
            self._worker.cancel()
            self._btn_cancel.setEnabled(False)
            self._btn_cancel.setText("Annulation…")


    # ---------------------- API publique ----------------------
    def mac_copy_with_anyqt_progress(src: str, dest: str, title: str = "Copy in progress", parent=None) -> bool:
        """
        Ouvre une fenêtre AnyQt avec barre de progression, ASCII bar et débit.
        :returns: True (succès), False (annulé), lève OSError si erreur de lancement.
        """
        src = os.path.abspath(src)
        if not os.path.exists(src):
            SimpleDialogQt.BoxError("Error file not exist : "+src)
            return

        dest = os.path.abspath(dest)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Source not found: {src}")
        os.makedirs(dest, exist_ok=True)

        app = QApplication.instance()
        owns_app = False
        if app is None:
            app = QApplication(sys.argv)
            owns_app = True

        dlg = _CopyDialog(src, dest, title, parent)
        dlg.start()
        # compat exec/exec_ selon backend
        exec_fn = getattr(dlg, "exec", None) or getattr(dlg, "exec_", None)
        exec_fn()

        result = dlg._result
        if owns_app:
            # On ne ferme pas l'app si l'hôte (Orange) doit continuer à l'utiliser.
            pass

        if result is None:
            # une erreur a déjà été affichée
            raise OSError("Copy failed (internal error).")
        return bool(result)

    def _run_osascript(script: str) -> subprocess.CompletedProcess:
        """
        Exécute un script AppleScript et renvoie le CompletedProcess.
        Ne lève pas, pour qu'on puisse distinguer Cancel (code != 0).
        """
        # On passe une seule -e avec tout le script pour éviter les soucis d'échappement multi -e
        return subprocess.run(
            ["osascript", "-e", script],
            text=True,
            capture_output=True
        )

    def _parse_extensions_from_filter(file_filter: str):
        """
        Convertit un filtre du style 'Images (*.jpg;*.png;*.jpeg)' en liste d'extensions ['jpg','png','jpeg'].
        Si rien, retourne [] (pas de filtrage côté AppleScript).
        """
        m = re.search(r"\(([^)]+)\)", file_filter or "")
        if not m:
            return []
        patterns = m.group(1)
        exts = []
        for token in re.split(r"[;,\s]+", patterns):
            token = token.strip()
            if not token:
                continue
            # *.jpg -> jpg ; .png -> png ; * -> (ignore)
            token = token.lstrip("*.").lstrip(".")
            if token and token != "*":
                exts.append(token.lower())
        # Supprime doublons en conservant l'ordre
        seen = set()
        out = []
        for e in exts:
            if e not in seen:
                seen.add(e)
                out.append(e)
        return out

    def _to_applescript_list_str(values):
        """
        Transforme ['jpg','png'] en AppleScript {"jpg","png"}.
        Si values est vide -> renvoie 'missing value' (pas d'arg).
        """
        if not values:
            return "missing value"
        quoted = ",".join(f"\"{v}\"" for v in values)
        return "{%s}" % quoted

    def _escape_as_text(s: str) -> str:
        """Échappe pour AppleScript (guillemets et backslashes)."""
        return s.replace("\\", "\\\\").replace("\"", "\\\"")

    # ----------------------------
    # 1) Sélection de dossier
    # ----------------------------

    def select_folder_macos(title: str = "Select a folder") -> str:
        """
        Ouvre un panneau 'choose folder' natif macOS et renvoie un chemin POSIX (str) ou '' si annulé.
        Toujours au premier plan via activation de System Events.
        """
        title_ = _escape_as_text(title or "Select a folder")
        # 'choose folder' renvoie un alias ; 'POSIX path of' le convertit.
        script = f'''
        with timeout of 3600 seconds
            tell application "System Events" to activate
            set _dlgTitle to "{title_}"
            try
                set _f to choose folder with prompt _dlgTitle
                set _p to POSIX path of _f
                return _p
            on error number -128
                return ""
            end try
        end timeout
        '''
        cp = _run_osascript(script)
        out = cp.stdout.strip()
        return out

    # ----------------------------
    # 2) Sélection de fichier(s)
    # ----------------------------

    def select_file_macos(multi_select: bool = False,
                          file_filter: str = "All Files (*.*)",
                          dialog_title: str = "Select File(s)") -> str:
        """
        Panneau natif macOS pour sélectionner un ou plusieurs fichiers.
        - multi_select=False -> renvoie un chemin (str) ou '' si annulé
          (pour compatibilité Windows, ici on renvoie aussi '' si annulé)
        - multi_select=True  -> renvoie des chemins séparés par ';'
        Le filtrage par extension utilise 'of type {"jpg","png",...}' lorsqu'on peut déduire des extensions.
        """
        title_ = _escape_as_text(dialog_title or "Select File(s)")
        exts = _parse_extensions_from_filter(file_filter)
        of_type = _to_applescript_list_str(exts)

        multi_flag = "with multiple selections allowed" if multi_select else ""
        of_type_clause = "" if of_type == "missing value" else f"of type {of_type}"

        # On renvoie POSIX path(s). En cas de multi, on joint par ';' côté AppleScript pour éviter des surprises d'encodage.
        if multi_select:
            script = f'''
            with timeout of 3600 seconds
                tell application "System Events" to activate
                set _dlgTitle to "{title_}"
                try
                    set _fs to choose file {of_type_clause} {multi_flag} with prompt _dlgTitle
                    set _list to {{}}
                    repeat with _f in _fs
                        set end of _list to POSIX path of _f
                    end repeat

                    -- On change temporairement le séparateur texte d'AppleScript
                    set oldDelims to AppleScript's text item delimiters
                    set AppleScript's text item delimiters to "//////"
                    set _joined to _list as text
                    set AppleScript's text item delimiters to oldDelims

                    return _joined
                on error number -128
                    return ""
                end try
            end timeout
            '''
            cp = _run_osascript(script)
            raw = cp.stdout.strip()
            if not raw:
                return ""
            return raw  # le string avec les chemins séparés par //////
        else:
            script = f'''
            with timeout of 3600 seconds
                tell application "System Events" to activate
                set _dlgTitle to "{title_}"
                try
                    set _f to choose file {of_type_clause} with prompt _dlgTitle
                    return POSIX path of _f
                on error number -128
                    return ""
                end try
            end timeout
            '''
            cp = _run_osascript(script)
            return cp.stdout.strip()


    # ----------------------------
    # 3) Enregistrer sous (nouveau fichier)
    # ----------------------------

    def select_new_file_macos(file_filter: str = "All Files (*.*)",
                              dialog_title: str = "Create New File") -> str:
        """
        Panneau natif macOS 'choose file name' (NSSavePanel). Renvoie le chemin (str) ou '' si annulé.
        On applique une extension par défaut si déductible du filtre (ex: '*.txt' -> '.txt').
        """
        title_ = _escape_as_text(dialog_title or "Create New File")
        exts = _parse_extensions_from_filter(file_filter)
        default_ext = exts[0] if exts else ""  # On prend la première extension du filtre si dispo

        script = f'''
        with timeout of 3600 seconds
            tell application "System Events" to activate
            set _dlgTitle to "{title_}"
            try
                set _f to choose file name with prompt _dlgTitle
                set _p to POSIX path of _f
                return _p
            on error number -128
                return ""
            end try
        end timeout
        '''
        cp = _run_osascript(script)
        path = cp.stdout.strip()
        if not path:
            return ""
        # Si pas d'extension et qu'on en a une par défaut, on l'ajoute.
        base, ext = os.path.splitext(path)
        if default_ext and not ext:
            # normalise: 'txt' -> '.txt'
            if not default_ext.startswith("."):
                default_ext = "." + default_ext
            path = path + default_ext
        return path

    # ----------------------------
    # 4) Message box native (display dialog)
    # ----------------------------

    def BoxMessage_macos(text: str, mode: int = 0, title: str = None) -> int:
        """
        Affiche une boîte AppleScript 'display dialog' :
          mode = 0 -> stop (rouge)   -> titre défaut "Error"
          mode = 1 -> caution (jaune)-> titre défaut "Warning"
          mode = 2 -> note (bleu)    -> titre défaut "Information"
        Renvoie 1 si 'OK' cliqué, 0 si annulé/fermé.
        """
        if mode not in (0, 1, 2):
            raise ValueError("mode doit être 0=Error, 1=Warning, 2=Info")

        icon = {0: "stop", 1: "caution", 2: "note"}[mode]
        if title is None:
            title = {0: "Error", 1: "Warning", 2: "Information"}[mode]

        title_ = _escape_as_text(title)
        text_  = _escape_as_text(text)

        script = f'''
        with timeout of 3600 seconds
            tell application "System Events" to activate
            try
                display dialog "{text_}" with title "{title_}" buttons {{"OK"}} default button "OK" with icon {icon} giving up after 0
                return "OK"
            on error number -128
                return "CANCEL"
            end try
        end timeout
        '''
        cp = _run_osascript(script)
        return 1 if cp.stdout.strip() == "OK" else 0





# if __name__ == "__main__":
#     from AnyQt.QtWidgets import QApplication
#     import sys
#     app = QApplication(sys.argv)
