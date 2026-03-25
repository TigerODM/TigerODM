# https://orange3.readthedocs.io/projects/orange-development/en/latest/tutorial-settings.html


import ctypes
import os
import sys

import Orange.data
from AnyQt.QtCore import QTimer
from AnyQt.QtWidgets import QButtonGroup, QLabel, QRadioButton
from Orange.widgets import  widget
from Orange.widgets.settings import Setting
from Orange.widgets.widget import Input, Output

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils import help_management


class OWOptimisationSelection(widget.OWWidget):
    name = "Optimization - Selection"
    description = "Choose whether you want Optuna to run automatically or not"
    icon = "icons/owoptimisationselection.png"
    category = "AAIT - ALGORITHM"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owoptimisationselection.png"

    priority = 1022
    want_control_area = False
    dossier_du_script = os.path.dirname(os.path.abspath(__file__))
    # Les paramètres du widget
    radio_choice = Setting(2)  # Pour stocker l'index de la sélection
    in_pointer = None

    class Inputs:
        data = Input("Data", Orange.data.Table)
        in_pointer = Input("Get study for the loop", str, auto_summary=False)  # sended as the widget is created

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.in_pointer
    def set_pointer(self, dataset):
        if dataset:
            self.in_pointer = int(dataset)

    @Inputs.data
    def set_data(self, in_data):
        self.data = []
        data = in_data
        column_name = "Source ID"
        # Vérifier si la colonne existe dans le domaine des attributs
        column_exists = column_name in [attr.name for attr in data.domain]
        if column_exists:
            column_index = data.domain.index(column_name)
            d = []
            for i in range(len(data)):
                if data[i][column_index] == "created":
                    d = data[i]
            self.data = Orange.data.Table(data.domain, [d])
        else:
            self.data = in_data

        if self.in_pointer is not None:
            if len(self.data) == 1:
                ctypes.cast(self.in_pointer, ctypes.py_object).value.change_last_ligne(self.data)

        if self.radio_choice == 0:
            self.Outputs.data.send(self.data)


    def __init__(self):
        super().__init__()

        self.data = None

        # Utiliser self.controlArea.layout() pour s'assurer que les widgets sont ajoutés à la zone de contrôle
        self.label = QLabel("Choose an option :")
        self.mainArea.layout().addWidget(self.label)

        # Créer un groupe de boutons radio
        self.radio_group = QButtonGroup(self)

        # Bouton radio 1
        self.radio1 = QRadioButton("Automatically")
        self.radio1.setChecked(self.radio_choice == 0)  # Cocher par défaut si radio_choice est 0
        self.radio1.toggled.connect(self.on_radio_changed)
        self.mainArea.layout().addWidget(self.radio1)
        self.radio_group.addButton(self.radio1, 0)

        # Bouton radio 2
        self.radio2 = QRadioButton("Manually")
        self.radio2.setChecked(self.radio_choice == 1)  # Cocher si radio_choice est 1
        self.radio2.toggled.connect(self.on_radio_changed)
        self.mainArea.layout().addWidget(self.radio2)
        self.radio_group.addButton(self.radio2, 1)

        # Bouton radio 3
        self.radio3 = QRadioButton("No data")
        self.radio3.setChecked(self.radio_choice == 2)  # Cocher si radio_choice est 1
        self.radio3.toggled.connect(self.on_radio_changed)
        self.mainArea.layout().addWidget(self.radio3)
        self.radio_group.addButton(self.radio3, 2)

        self.setFixedWidth(480)
        self.setFixedHeight(354)
        self.setAutoFillBackground(True)

        # Initialiser le timer pour un délai de 5 secondes
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)  # S'assurer que le timer ne se déclenche qu'une fois
        self.timer.timeout.connect(self.select_radio3)
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))



    def on_radio_changed(self):
        # Détecte quel bouton est sélectionné
        selected_button = self.radio_group.checkedId()
        if selected_button == 0:
            self.Outputs.data.send(self.data)
        elif selected_button == 1:
            self.Outputs.data.send(self.data)
            self.timer.start(200)
        elif selected_button == 2:
            print("No data")
        # Mise à jour du paramètre de sauvegarde
        self.radio_choice = selected_button


    def select_radio3(self):
        # Sélectionner le bouton radio 2 après 5 secondes
        self.radio3.setChecked(True)

if __name__ == "__main__":
    from AnyQt.QtWidgets import QApplication

    app = QApplication(sys.argv)
    mon_objet = OWOptimisationSelection()
    mon_objet.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()


