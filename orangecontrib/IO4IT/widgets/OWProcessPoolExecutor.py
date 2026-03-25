import os
import sys
from AnyQt.QtWidgets import QSpinBox, QLabel, QPushButton, QGroupBox
from Orange.widgets import widget
from Orange.widgets.utils.signals import Output

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IO4IT.utils import pool_exec_utils
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.IO4IT.utils import pool_exec_utils
    from orangecontrib.AAIT.utils.import_uic import uic


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

    class Outputs:
        executor = Output("ProcessPoolExecutor", object)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(470)
        self.setFixedHeight(300)

        # We don't need a separate layout for the main widget anymore
        # as the UI file now contains a QGroupBox that will manage the layout.
        uic.loadUi(self.gui, self)

        self.executor = None
        self.current_workers = None

        # Rendre les widgets accessibles
        self.cpu_label: QLabel = self.findChild(QLabel, "cpu_label")
        self.spin_workers: QSpinBox = self.findChild(QSpinBox, "spin_workers")
        self.btn_create: QPushButton = self.findChild(QPushButton, "btn_create")
        self.info_label: QLabel = self.findChild(QLabel, "info_label")
        self.group_box = self.findChild(QGroupBox, "groupBox")

        # Configuration des widgets
        self.cpu_label.setText(pool_exec_utils.cpu_label_text())
        self.spin_workers.setMinimum(1)
        max_cpus = max(1, pool_exec_utils.available_cpus())
        self.spin_workers.setMaximum(max_cpus)
        self.spin_workers.setValue(min(4, max_cpus))

        self.btn_create.clicked.connect(self.create_or_update_clicked)

        self.error("")
        self.warning("")
        self.post_initialized()

    def onDeleteWidget(self):
        pool_exec_utils.shutdown_executor(self.executor)
        self.executor = None
        super().onDeleteWidget()

    def create_or_update_clicked(self):
        new_workers = int(self.spin_workers.value())
        self.executor, self.current_workers, msg, _changed = pool_exec_utils.create_or_update_executor(
            self.executor, self.current_workers, new_workers
        )
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