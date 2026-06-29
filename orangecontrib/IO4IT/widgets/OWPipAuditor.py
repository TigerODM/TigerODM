import os
import sys
import Orange.data
from Orange.widgets import widget
from Orange.data import Domain, StringVariable, Table
from AnyQt.QtWidgets import QApplication
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Output, Input
from AnyQt.QtCore import QTimer
from datetime import datetime

# Importations conditionnelles selon l'architecture du projet
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.IO4IT.utils.environment_collector import EnvironmentCollector
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.AAIT.utils import thread_management, help_management
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.IO4IT.utils.environment_collector import EnvironmentCollector
    from orangecontrib.AAIT.utils.import_uic import uic


# ---------------------------------------------------------------------------
# Helpers (module-level, utilisables hors widget et dans les threads)
# ---------------------------------------------------------------------------
 
def get_pip_freeze_dict() -> dict:
    """
    Retourne un dict {package_name_lower: version} via importlib.metadata.
    N'utilise pas de subprocess.
    """
    collector = EnvironmentCollector()
    freeze_str = collector._dependencies_freeze_space()
    packages = {}
    for line in freeze_str.splitlines():
        line = line.strip().strip("\r")
        if "==" in line:
            name, version = line.split("==", 1)
            packages[name.lower()] = version
    return packages
 
 
def _make_table(rows: list, columns: list) -> Table:
    """Construit une Orange Table avec les colonnes (StringVariable) spécifiées."""
    metas = [StringVariable(col) for col in columns]
    domain = Domain([], metas=metas)
    return Table.from_list(domain, rows)


def run_audit(saved_packages: dict) -> tuple:
    current_packages = get_pip_freeze_dict()
    all_keys = set(saved_packages.keys()) | set(current_packages.keys())

    diff_rows = []

    for pkg in sorted(all_keys):
        saved_v = saved_packages.get(pkg, "(Absent)")
        current_v = current_packages.get(pkg, "(Nouveau)")

        if saved_v == "(Absent)":
            status = "➕ Nouveau"
        elif current_v == "(Nouveau)":
            status = "❌ Manquant"
        elif saved_v != current_v:
            status = "⚠️ Différent"
        else:
            status = "✅ OK"

        # Table différences : 4 colonnes complètes
        diff_rows.append([pkg, saved_v, current_v, status])


    diff_cols    = ["Package", "Saved Version", "Current Version", "Status"]
    

    diff_table     = _make_table(diff_rows,     diff_cols)     if diff_rows     else None
    
    return diff_table
 
 
# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWPipAuditor(widget.OWWidget):
    name = "Pip Auditor"
    description = "Snapshot and compare pip freeze environment"
    category = "AAIT - TOOLBOX"
    icon = "icons/pip_auditor.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/pip_auditor.png"
 
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owpipauditor.ui")
 
    want_control_area = False
    priority = 1100
    
 
    # ------------------------------------------------------------------
    # Settings persistants
    # ------------------------------------------------------------------
    saved_freeze = Setting(None, schema_only=True)       # Snapshot sauvegardé (dict pkg→version)
    snapshot_time = Setting(None)
    autorun: bool = Setting(False)         # Checkbox "Lancer automatiquement au démarrage"
    trigger_on_signal = Setting(False)      # Checkbox "Run on signal"
    # ------------------------------------------------------------------
    # Entrées
    # ------------------------------------------------------------------
    class Inputs:
        data = Input("Data", Orange.data.Table)

    # ------------------------------------------------------------------
    # Sorties
    # ------------------------------------------------------------------
    class Outputs:
        diff_table = Output("Results", Orange.data.Table)       # Comparaison packages
        info_table = Output("Infos", Orange.data.Table)     
        data = Output("Data", Orange.data.Table) # Sortie "Passthrough"
 
    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------
    def __init__(self):
        super().__init__()
        self.setFixedWidth(470)
        self.setFixedHeight(351)
        uic.loadUi(self.gui, self)
 
        self.thread = None
        self._last_results = (None, None, None)  # (diff, current, previous)
 
        # Connexion des boutons définis dans le .ui
        self.pushButton_snapshot.clicked.connect(self.take_snapshot)
        self.pushButton_run.clicked.connect(self.run)
 
        # Checkbox autorun (doit être définie dans owpipauditor.ui avec le nom checkBox_autorun)
        self.checkBox_autorun.setChecked(self.autorun)
        self.checkBox_autorun.stateChanged.connect(self._on_autorun_changed)

        self.checkBox_trigger.setChecked(self.trigger_on_signal)
        self.checkBox_trigger.stateChanged.connect(self._on_trigger_changed)
 
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))
 
        # Démarrage automatique si l'option est activée et qu'un snapshot existe
        if self.autorun and self.saved_freeze:
            QTimer.singleShot(100, self.run)
    
    @Inputs.data
    def set_data(self, data):
        # On renvoie immédiatement la donnée en sortie (Passthrough)
        self.Outputs.data.send(data)
    
        # Si on reçoit une donnée non nulle et que l'option est activée
        if data is not None and self.trigger_on_signal:
            # On lance la comparaison
            self.run()
 
    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_autorun_changed(self, state: int):
        """Persistance de la checkbox autorun."""
        self.autorun = bool(state)

    def _on_trigger_changed(self, state: int):
        self.trigger_on_signal = bool(state)
 
    def take_snapshot(self):
        """Sauvegarde l'état pip courant dans le Setting."""
        try:
            self.saved_freeze = dict(get_pip_freeze_dict())
            self.snapshot_time = datetime.now()
            self.error("")
            self.warning("")
            self.information(
                f"Snapshot réussi : {len(self.saved_freeze)} packages sauvegardés."
            )
        except Exception as e:
            self.error(f"Erreur Snapshot: {str(e)}")
 
    def run(self):
        """Compare le snapshot sauvegardé avec l'environnement courant et émet les 3 sorties."""
        self.error("")
        self.warning("")
 
        if self.saved_freeze is None:
            self.error("Aucun snapshot sauvegardé.")
            return
 
        if self.thread is not None:
            self.thread.safe_quit()
 
        self.progressBarInit()
 
        self.thread = thread_management.Thread(run_audit, self.saved_freeze)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()
 
    # ------------------------------------------------------------------
    # Handlers thread
    # ------------------------------------------------------------------
    def handle_progress(self, value: float):
        self.progressBarSet(value)
 
    def handle_result(self, result):
        try:
            self.clear_messages()
            diff_table = result
            
            if diff_table is None:
                return
            
            ref_time = self.snapshot_time
            now_time = datetime.now()

            info_rows = [[
                ref_time.strftime("%Y-%m-%d %H:%M:%S") if ref_time else "N/A",
                now_time.strftime("%Y-%m-%d %H:%M:%S"),
            ]]

            info_table = _make_table(info_rows, ["Snapshot time", "Comparison time"])

            self.Outputs.diff_table.send(diff_table)
            self.Outputs.info_table.send(info_table)

            status_idx = diff_table.domain.metas.index(diff_table.domain["Status"])
            n_diff = sum(1 for row in diff_table.metas if str(row[status_idx]) != "✅ OK")

            self.information(
                f"Audit terminé : {n_diff} différence(s)."
            )

        except Exception as e:
            self.clear_messages()
            self.error(f"Erreur lors de l'envoi des tables: {e}")

 
    def handle_finish(self):
        self.progressBarFinished()
        self.thread = None
 
    # ------------------------------------------------------------------
    # Hook post-init (override si besoin dans une sous-classe)
    # ------------------------------------------------------------------
    def post_initialized(self):
        pass
 
 
# ---------------------------------------------------------------------------
# Lancement standalone
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWPipAuditor()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
 