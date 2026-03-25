import os
import sys
import re
import Orange.data

from Orange.widgets import widget
from Orange.widgets.widget import Input, Output
from Orange.data import Table, Domain, StringVariable

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QPushButton, QCheckBox
from AnyQt.QtCore import QTimer


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWConcatRules(widget.OWWidget):
    name = "Intersect CN2 Rules"
    description = "Concat CN2 Rules from data."
    category = "AAIT - ALGORITHM"
    icon = "icons/owCN2_intersect_rules.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owCN2_intersect_rules.svg"
    priority = 1145
    keywords = "cn2 rule concat"
    want_control_area = False
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owconcatrules.ui")

    class Inputs:
        rules = Input("Rules", Orange.data.Table)
        new_rules = Input("New rules", Orange.data.Table)

    class Outputs:
        concat_rules = Output("Concat Rules", Orange.data.Table)

    strauto: str = Setting('False')

    @Inputs.rules
    def set_rules(self, data):
        new_data = self.fake_table_from_min_max(data)
        self.rules_data = new_data
        self.Outputs.concat_rules.send(None)
        if self.strauto == 'True' or self.strauto == 'Middle':
            self.run()
            if self.strauto == 'Middle':
                self.strauto = 'False'
                self.checkbox_interface.setChecked(False)

    @Inputs.new_rules
    def set_new_rules(self, data):
        new_data = self.fake_table_from_min_max(data)
        self.new_rules_data = new_data
        self.Outputs.concat_rules.send(None)
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
        self.new_rules_data = None
        self.btn_run = self.findChild(QPushButton, "pushButton")
        self.btn_run.clicked.connect(self.run)

        self.btn_run_first_rule = self.findChild(QPushButton, "pushButton_2")
        self.btn_run_first_rule.clicked.connect(self.send_first_rule)
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

    def send_first_rule(self):
        self.error("")
        if self.rules_data is None:
            self.error("you need rule data")
            return
        self.Outputs.concat_rules.send(self.rules_data)

    def fake_table_from_min_max(self, input_data):
        if input_data is None:
            return input_data
        if "regle" in input_data.domain:
            return input_data
        if "Feature" in input_data.domain and "Min." in input_data.domain and "Max." in input_data.domain:
            str_rules = ""
            idx_min = input_data.domain.index("Min.")
            idx_max = input_data.domain.index("Max.")
            idx_feature = input_data.domain.index("Feature")
            for line in input_data:
                if line[idx_min] == "?":
                    continue
                if line[idx_max] == "?":
                    continue
                to_add = str(line[idx_feature]) + " >= " + str(line[idx_min])
                to_add += " and " + str(line[idx_feature]) + " <= " + str(line[idx_max])

                if str_rules != "":
                    str_rules += " and "
                str_rules += to_add
            meta = [[str_rules]]  # 1 ligne, 1 colonne meta

            domain = Domain([], metas=[StringVariable("regle")])
            data = [[]]  # Ajoute une ligne vide pour correspondre aux métas

            table = Table.from_numpy(domain, data, metas=meta)
            return table

        if "name" in input_data.domain and "min" in input_data.domain and "max" in input_data.domain:
            str_rules = ""
            idx_min = input_data.domain.index("min")
            idx_max = input_data.domain.index("max")
            idx_feature = input_data.domain.index("name")
            for line in input_data:
                if line[idx_min] == "?":
                    continue
                if line[idx_max] == "?":
                    continue
                to_add = str(line[idx_feature]) + " >= " + str(line[idx_min])
                to_add += " and " + str(line[idx_feature]) + " <= " + str(line[idx_max])

                if str_rules != "":
                    str_rules += " and "
                str_rules += to_add
            meta = [[str_rules]]  # 1 ligne, 1 colonne meta

            domain = Domain([], metas=[StringVariable("regle")])
            data = [[]]  # Ajoute une ligne vide pour correspondre aux métas

            table = Table.from_numpy(domain, data, metas=meta)
            return table

        return input_data

    def del_space_debut_fin(self, text_to_edit):
        if text_to_edit[0] == " ":
            text_to_edit = text_to_edit[1:]
        if text_to_edit[-1] == " ":
            text_to_edit = text_to_edit[:-1]
        return text_to_edit

    def post_initialized(self):
        """
        used for overloading only
        """
        return

    def on_checkbox_toggled(self, state):
        if state == 2:  # Qt.Checked (valeur 2 pour "coché")
            self.strauto = 'True'
        elif state == 0:  # Qt.Unchecked (valeur 0 pour "décoché")
            self.strauto = 'False'
        elif state == 1:
            self.strauto = 'Middle'

    def normalize_rule(self, unit_rule):
        unit_rule = re.sub(r'(?<!>)>(?!=)', '>=', unit_rule)
        unit_rule = re.sub(r'(?<!<)<(?!=)', '<=', unit_rule)
        return unit_rule

    def needs_normalization(self, unit_rule):
        # Vérifie s'il y a un > non suivi de =, ou un < non suivi de =
        return bool(re.search(r'(?<!>)>(?!=)|(?<!<)<(?!=)', unit_rule))

    def run(self):
        self.error("")
        if self.rules_data is None or self.new_rules_data is None:
            self.error("You must have rules and new rules")
            return

        datas = [self.rules_data, self.new_rules_data]
        rules = []
        for i in range(len(datas)):
            if "regle" in datas[i].domain:
                index = datas[i].domain.index("regle")
                for line in datas[i]:
                    current_rules = line[index].value
                    if current_rules == "TRUE":
                        continue
                    regl_list = current_rules.split(" and ")
                    for unit_rule in regl_list:
                        if self.needs_normalization(unit_rule) and "->" not in unit_rule:
                            unit_rule = self.normalize_rule(unit_rule)
                        current_var, current_symb, current_value = re.split(r'(<=|>=)', unit_rule)
                        current_var = self.del_space_debut_fin(current_var)
                        current_symb = self.del_space_debut_fin(current_symb)
                        current_value = float(self.del_space_debut_fin(current_value))
                        ajoute = True
                        for idx, element in enumerate(rules):
                            if element[0] == current_var and element[1] == current_symb:
                                ajoute = False
                                if current_symb == "<=":
                                    rules[idx][2] = min(current_value, rules[idx][2])
                                else:
                                    print(element[2], rules[idx][2])
                                    rules[idx][2] = max(current_value, rules[idx][2])
                                break
                        if ajoute:
                            rules.append([current_var, current_symb, float(current_value)])
        new_rules = ""
        for idx, rule in enumerate(rules):
            if idx != 0:
                new_rules = new_rules + " and "
            new_rules = new_rules + rule[0] + " " + rule[1] + " " + str(rule[2])

        if new_rules == "":
            new_rules = "TRUE"
        data = [[]]
        domain = Domain([],
                        metas=[StringVariable('regle')])
        self.new_rules_data = None
        self.Outputs.concat_rules.send(Table.from_numpy(domain, data, metas=[[new_rules]]))


if __name__ == "__main__":
    from AnyQt.QtWidgets import QApplication

    app = QApplication(sys.argv)
    my_widget = OWConcatRules()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()