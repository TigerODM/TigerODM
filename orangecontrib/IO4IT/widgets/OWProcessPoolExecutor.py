import os
import sys
from AnyQt.QtWidgets import QSpinBox, QLabel, QPushButton, QGroupBox, QCheckBox
from AnyQt.QtCore import QTimer
from Orange.widgets import widget
from Orange.widgets.utils.signals import Output
from Orange.widgets.settings import Setting

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IO4IT.utils import pool_exec_utils
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.IO4IT.utils import pool_exec_utils
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import help_management


class OWProcessPoolExecutor(widget.OWWidget):
    name = "Process Pool Executor"
    description = "Create and configure a Process Pool Executor"
    category = "AAIT - TOOLBOX"
    icon = "icons/process_pool_executor.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/process_pool_executor.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owprocesspoolexecutor.ui")
    want_control_area = False
    priority = 900

    str_workers: str = Setting("4")
    str_autosend: str = Setting("False")

    class Outputs:
        executor = Output("ProcessPoolExecutor", object)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(470)
        self.setFixedHeight(300)

        uic.loadUi(self.gui, self)

        self.executor = None
        self.current_workers = None

        self.cpu_label = self.findChild(QLabel, "cpu_label")
        self.spin_workers = self.findChild(QSpinBox, "spin_workers")
        self.info_label = self.findChild(QLabel, "info_label")
        self.group_box = self.findChild(QGroupBox, "groupBox")
        self.checkBox_send = self.findChild(QCheckBox, "checkBox_send")
        self.pushButton_send = self.findChild(QPushButton, "pushButton_send")

        # Initialisation de la vue du nombre de CPU et SpinBox
        max_cpus = max(1, pool_exec_utils.available_cpus())
        if self.cpu_label:
            self.cpu_label.setText(pool_exec_utils.cpu_label_text())

        if self.spin_workers:
            self.spin_workers.setMinimum(1)
            self.spin_workers.setMaximum(max_cpus)

            # Restauration du nombre de workers depuis les Settings
            try:
                val = int(self.str_workers)
            except ValueError:
                val = min(4, max_cpus)
            self.spin_workers.setValue(min(max(1, val), max_cpus))
            self.spin_workers.valueChanged.connect(self._on_workers_changed)

        # Restauration de l'état Auto Send
        if self.checkBox_send:
            self.checkBox_send.setChecked(self.str_autosend == "True")
            self.checkBox_send.clicked.connect(self._on_autorun_toggled)

        # Bouton d'exécution manuelle
        if self.pushButton_send:
            self.pushButton_send.setEnabled(self.str_autosend != "True")
            self.pushButton_send.clicked.connect(self.create_or_update_clicked)

        self.error("")
        self.warning("")
        self.post_initialized()

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

        # Lancement automatique initial si activé dans les Settings
        if self.str_autosend == "True":
            self.create_or_update_clicked()

    # ------------------------------------------------------------------
    # Settings & UI Synchronization
    # ------------------------------------------------------------------
    def update_setting_from_qt_view(self):
        """Met à jour les attributs de Setting à partir des composants Qt."""
        if self.spin_workers:
            self.str_workers = str(self.spin_workers.value())

        if self.checkBox_send:
            self.str_autosend = "True" if self.checkBox_send.isChecked() else "False"

        if self.pushButton_send and self.checkBox_send:
            self.pushButton_send.setEnabled(not self.checkBox_send.isChecked())

    def _on_autorun_toggled(self):
        self.update_setting_from_qt_view()
        if self.str_autosend == "True":
            self.create_or_update_clicked()

    def _on_workers_changed(self):
        self.update_setting_from_qt_view()
        if self.str_autosend == "True":
            self.create_or_update_clicked()

    # ------------------------------------------------------------------
    # Core Logic
    # ------------------------------------------------------------------
    def onDeleteWidget(self):
        pool_exec_utils.shutdown_executor(self.executor)
        self.executor = None
        super().onDeleteWidget()

    def create_or_update_clicked(self):
        # Sécurisation en cas d'absence du spin_workers
        new_workers = int(self.spin_workers.value()) if self.spin_workers else 1
        self.executor, self.current_workers, msg, _changed = pool_exec_utils.create_or_update_executor(
            self.executor, self.current_workers, new_workers
        )
        if self.info_label:
            self.info_label.setText(msg)
        self.Outputs.executor.send(self.executor)

    def post_initialized(self):
        pass

if __name__ == "__main__":
    from AnyQt.QtWidgets import QApplication
    sys.argv.append("-s")
    app = QApplication(sys.argv)
    my_widget = OWProcessPoolExecutor()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()