import sys
from Orange.widgets.settings import Setting
from Orange.widgets import widget
from Orange.widgets.utils.signals import  Output
from AnyQt.QtWidgets import QApplication,QMainWindow
from AnyQt.QtCore import QTimer
import os
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import help_management
class OWQuadrantclicker(widget.OWWidget):
    name = "Quadrant Clicker"
    description = "Choose which quadrant widgets are displayed in at startup"
    category = "AAIT - TOOLBOX"
    icon = "icons/quadrantclicker.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/quadrantclicker.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owquadrant_clicker.ui")
    want_control_area = False
    priority = 1089

    str_checkbox_statut: str = Setting("False")

    class Outputs:
        output_autoshow  = Output("AutoShowConfiguration", str, auto_summary=False)

    def minimize_all_qmainwindows(self):
        for w in QApplication.topLevelWidgets():
            try:
                if isinstance(w, QMainWindow):
                    w.showMinimized()
            except Exception as e:
                print(e)

    def __init__(self):
        super().__init__()
        uic.loadUi(self.gui, self)
        if self.str_checkbox_statut=="False":
            self.checkBox.setChecked(False)
        else:
            self.checkBox.setChecked(True)

        self.btn_tl.clicked.connect(lambda: self._p("top-left"))
        self.btn_tr.clicked.connect(lambda: self._p("top-right"))
        self.btn_bl.clicked.connect(lambda: self._p("bottom-left"))
        self.btn_br.clicked.connect(lambda: self._p("bottom-right"))

        # # Edges
        self.btn_top.clicked.connect(lambda: self._p("top"))
        self.btn_bottom.clicked.connect(lambda: self._p("bottom"))
        self.btn_left.clicked.connect(lambda: self._p("left"))
        self.btn_right.clicked.connect(lambda: self._p("right"))
        #
        # # Bottom action buttons
        self.btn_fs.clicked.connect(lambda: self._p("fullscreen"))
        self.btn_disabled.clicked.connect(lambda: self._p("none"))

        self.pushButton_free.clicked.connect(self.send_free)


        self.checkBox.toggled.connect(self.on_checkbox_toggled)

        if self.str_checkbox_statut != "False":
            QTimer.singleShot(50, self.minimize_all_qmainwindows)

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def send_free(self):
        delta_h=int(self.spinBox_dh.value())
        if delta_h+int(self.spinBox_h.value())>100:
            delta_h=100-int(self.spinBox_h.value())

        delta_l=int(self.spinBox_dl.value())
        if delta_l+int(self.spinBox_l.value())>100:
            delta_l=100-int(self.spinBox_l.value())


        str_value=f"v{str(self.spinBox_h.value())}_dv{str(delta_h)}_h{str(self.spinBox_l.value())}_dh{str(delta_l)}"
        self.label.setText("Selected position : "+str(str_value))
        self.Outputs.output_autoshow.send(str(str_value))



    def _p(self, s: str):
        self.label.setText("Selected position : "+str(s))
        self.Outputs.output_autoshow.send(str(s))

    def on_checkbox_toggled(self, checked: bool):
        if checked:
            self.str_checkbox_statut = "True"
        else:
            self.str_checkbox_statut = "False"





if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWQuadrantclicker()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()

