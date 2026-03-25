import os
import sys
import re
import Orange.data
from Orange.widgets import widget
from Orange.widgets.widget import Input, Output
from Orange.data import Table, Domain, DiscreteVariable
from AnyQt.QtWidgets import QPushButton, QCheckBox
from Orange.widgets.settings import Setting
from AnyQt.QtCore import QTimer

# from fontTools.varLib.mutator import curr

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWApplyRules(widget.OWWidget):
    name = "Apply Rules to data"
    description = "Apply Rules to data fron an over workflow."
    icon = "icons/apply_rules.svg"
    category = "AAIT - ALGORITHM"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/apply_rules.svg"
    priority = 1145
    keywords = "Apply Rules to data"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owapplyrules.ui")
    want_control_area = False

    class Inputs:
        rules = Input("Rules", Orange.data.Table)
        data = Input("Data", Orange.data.Table)

    class Outputs:
        out_data = Output("Out data", Orange.data.Table)

    strauto: str = Setting('False')

    @Inputs.rules
    def set_rules(self, data):
        self.rules_data = data
        self.Outputs.out_data.send(None)
        if self.strauto == 'True' or self.strauto == 'Middle':
            self.run()
            if self.strauto == 'Middle':
                self.strauto = 'False'
                self.checkbox_interface.setChecked(False)

    @Inputs.data
    def set_new_point_from_scatter_plot(self, data):
        self.data = data
        self.Outputs.out_data.send(None)
        if self.strauto == 'True' or self.strauto == 'Middle':
            self.run()
            if self.strauto == 'Middle':
                self.strauto = 'False'
                self.checkbox_interface.setChecked(False)

    def __init__(self):
        super().__init__()
        # Set the fixed width and height of the widget
        self.setFixedWidth(470)
        self.setFixedHeight(300)

        # Load the user interface file
        uic.loadUi(self.gui, self)
        self.rules_data = None
        self.data = None
        self.btn_run = self.findChild(QPushButton, "pushButton")
        self.btn_run.clicked.connect(self.run)

        self.checkbox_interface = self.findChild(QCheckBox, 'checkBox')
        if self.strauto == 'Middle':
            self.strauto = 'False'
        if self.strauto == 'False':
            self.checkbox_interface.setChecked(False)
        if self.strauto == 'True':
            self.checkbox_interface.setChecked(True)
        self.checkbox_interface.stateChanged.connect(self.on_checkbox_toggled)

        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def post_initialized(self):
        """
        used for overloading only
        """
        return

    def del_space_debut_fin(self, text_to_edit):
        if text_to_edit[0] == " ":
            text_to_edit = text_to_edit[1:]
        if text_to_edit[-1] == " ":
            text_to_edit = text_to_edit[:-1]
        return text_to_edit

    def normalize_rule(self, unit_rule):
        unit_rule = re.sub(r'(?<!>)>(?!=)', '>=', unit_rule)
        unit_rule = re.sub(r'(?<!<)<(?!=)', '<=', unit_rule)
        return unit_rule

    def needs_normalization(self, unit_rule):
        # Vérifie s'il y a un > non suivi de =, ou un < non suivi de =
        return bool(re.search(r'(?<!>)>(?!=)|(?<!<)<(?!=)', unit_rule))

    def run(self):
        self.error("")
        self.warning("")
        if self.rules_data is None or self.data is None:
            self.error("You must have rules and data")
            self.Outputs.out_data.send(None)
            return

        data_regle = self.rules_data
        data_value = self.data
        num_col_regle = data_regle.domain.index("regle")
        a_recuperer = []
        var_not_in_domain = []
        value_in_rule_not_in_domain = []
        error = False
        for i in range(len(data_value)):
            a_recuperer.append(False)
        for regle in data_regle:
            current_regle = regle[num_col_regle]

            ## cette partie permet de gérer le cas ou dans une règle une variable n'est pas présente dans les données d'entrées et de pas avoir une erreur
            regl_list = str(current_regle).split(" and ")
            compteur = 0
            for unit_rule in regl_list:
                compteur = compteur + 1
                if self.needs_normalization(unit_rule) and "->" not in unit_rule:
                    unit_rule = self.normalize_rule(unit_rule)
                current_var, current_symb, current_value = re.split(r'(<=|>=)', unit_rule)
                current_var = self.del_space_debut_fin(current_var)
                if current_var not in data_value.domain:
                    var_not_in_domain.append(current_var)
                    if compteur != 1:
                        current_var = "and " + current_var
                    value_in_rule_not_in_domain.append(current_var + " " + current_symb + current_value)
            if len(var_not_in_domain) > 0:
                self.warning("Warning " + ",".join(var_not_in_domain) + " not in possible variable")

                for j, element in enumerate(value_in_rule_not_in_domain):
                    current_regle = str(current_regle).replace(element, "")

            # if current rules start with "     and " we need to remove the begin of the rule
            test_current_regle = str(current_regle)
            # print("#####")
            # print(test_current_regle)
            # print(type(test_current_regle))
            # print("##########################")
            while (test_current_regle[0] == " "):
                test_current_regle = test_current_regle[1:]
            if len(test_current_regle) >= 4:
                if test_current_regle[:4] == "and ":
                    test_current_regle = test_current_regle[4:]
                    current_regle = test_current_regle
                    print(current_regle)
            for i in range(len(data_value)):
                new_regle = str(current_regle)

                for j in range(len(data_value[i])):
                    new_regle = new_regle.replace(data_value.domain[j].name, str(data_value[i][j].value))
                a_recuperer[i] = 0

                try:
                    if eval(new_regle):
                        a_recuperer[i] = 1
                except Exception as e:
                    error = True
                    print(f"Error : {e}")
                    self.error("You have to edit your rule to be correct. Check meta in input data too!")
        data = []
        for idx, element in enumerate(a_recuperer):
            d = []
            for i, elem in enumerate(data_value[idx]):
                d.append(elem)
            d.append(str(int(element)))
            data.append(d)

        # Construction du nouveau domaine
        domain_attrs = list(data_value.domain.attributes)  # Récupération des attributs
        target_var = DiscreteVariable("ok", values=["0", "1"])  # Variable cible
        target_var.colors = [(255, 0, 0),  # Rouge foncé (Dark Red) pour "0"
                             (0, 255, 0)]  # Vert foncé (Dark Green) pour "1"

        # Gestion des métadonnées (si présentes)
        meta_vars = list(data_value.domain.metas) if data_value.domain.metas else []

        # Création du nouveau domaine avec les métadonnées incluses
        new_domain = Domain(domain_attrs, target_var, metas=meta_vars)

        # Création de la table avec les nouvelles données
        out_data = Table.from_list(new_domain, data)

        # Récupération et réintégration des métadonnées
        if meta_vars:
            out_data.metas = data_value.metas  # Copie des métadonnées depuis l'entrée

        # Envoi des données si pas d'erreur
        if not error:
            self.Outputs.out_data.send(out_data)

    def on_checkbox_toggled(self, state):
        if state == 2:  # Qt.Checked (valeur 2 pour "coché")
            self.strauto = 'True'
        elif state == 0:  # Qt.Unchecked (valeur 0 pour "décoché")
            self.strauto = 'False'
        elif state == 1:
            self.strauto = 'Middle'


if __name__ == "__main__":
    from AnyQt.QtWidgets import QApplication

    app = QApplication(sys.argv)
    my_widget = OWApplyRules()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()