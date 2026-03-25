# https://orange3.readthedocs.io/projects/orange-development/en/latest/tutorial-settings.html


import ctypes
import os
import sys

import Orange.data
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input
from AnyQt.QtCore import QTimer



if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWOptimisationSendScore(widget.OWWidget):
    name = "Optimisation - Send score"
    description = "Send the score Optuna"
    category = "AAIT - ALGORITHM"
    icon = "icons/optimisation.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/optimisation.png"

    priority = 1021
    dossier_du_script = os.path.dirname(os.path.abspath(__file__))
    want_control_area = False
    partie_1 = ""
    partie_2 = ""
    CaptionDuLabelPourGoto = ""
    AddAcondition = 0
    liste_a_afficher_comboBox_selection_label = []
    in_pointer = None

    class Inputs:
        score_input = Input("Score", Orange.data.Table)
        in_pointer = Input("end of the loop", str, auto_summary=False)  # sended as the widget is created

    # c est ce decorateur qui est fait qu il se passe quelque
    @Inputs.score_input
    def set_input(self, dataset):
        self.score_input = dataset

        if self.in_pointer != None:
            ctypes.cast(self.in_pointer, ctypes.py_object).value.itere(self.score_input)

    @Inputs.in_pointer
    def set_pointer(self, dataset):
        if dataset:
            self.in_pointer = int(dataset)

    def __init__(self):

        self.current_data_standard_input = None
        self.current_data_search_space = None
        self.current_data_previous_study = None

        super().__init__()  # je pense que c'est pour garder les config entre deux executions
        #setup_shared_variables(self)

        self.setFixedWidth(480)
        self.setFixedHeight(354)
        self.setAutoFillBackground(True)
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

if __name__ == "__main__":
    from AnyQt.QtWidgets import QApplication

    app = QApplication(sys.argv)
    mon_objet = OWOptimisationSendScore()
    mon_objet.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
