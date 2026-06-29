import os
import sys
import math
import Orange.data
from Orange.widgets import widget
from Orange.widgets.widget import Input, Output
from Orange.data import Table, Domain, StringVariable
from Orange.statistics.basic_stats import BasicStats

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWRuleGenerator(widget.OWWidget):
    name = "Rule Generator"
    description = "Génère une règle de filtrage numérique (min <= col <= max) à partir d'une table."
    icon = "icons/rule_generator.svg"
    category = "AAIT - ALGORITHM"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/rule_generator.svg"
    priority = 1150
    keywords = "Rule Generator min max filtre bornes"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_rule_generator.ui")
    want_control_area = False

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        rules = Output("Rules", Orange.data.Table)

    @Inputs.data
    def set_data(self, data):
        self.data = data
        self.Outputs.rules.send(None)
        self.run()

    def __init__(self):
        super().__init__()
        # Set the fixed width and height of the widget
        self.setFixedWidth(550)
        self.setFixedHeight(300)

        # Load the user interface file
        uic.loadUi(self.gui, self)

        self.data = None
        self.post_initialized()

    def post_initialized(self):
        """Utilisé pour la surcharge uniquement."""
        return

    def run(self):
        self.error("")
        self.warning("")

        if self.data is None:
            self.Outputs.rules.send(None)
            return

        num_attrs = [a for a in self.data.domain.attributes if a.is_continuous]
        if not num_attrs:
            self.warning("Aucune colonne numérique trouvée dans les données.")
            self.Outputs.rules.send(None)
            return

        parts = []
        for attr in num_attrs:                      # <-- fix : BasicStats appelé une variable à la fois
            stat = BasicStats(self.data, attr)
            lo = stat.min
            hi = stat.max
            if math.isnan(lo) or math.isnan(hi):
                continue
            parts.append(f"{lo} <= {attr.name} <= {hi}")

        if not parts:
            self.warning("Toutes les colonnes sont vides.")
            self.Outputs.rules.send(None)
            return

        rule_str = " and ".join(parts)

        sv = StringVariable("regle")
        domain = Domain([], metas=[sv])
        out_table = Table.from_list(domain, [[rule_str]])
        self.Outputs.rules.send(out_table)


if __name__ == "__main__":
    from AnyQt.QtWidgets import QApplication
    app = QApplication(sys.argv)
    my_widget = OWRuleGenerator()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()