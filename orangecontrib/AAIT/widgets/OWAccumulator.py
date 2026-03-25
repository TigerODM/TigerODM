from Orange.widgets import widget
import sys
import os

from AnyQt.QtWidgets import QApplication, QPushButton, QCheckBox
from Orange.widgets.utils.signals import Input, Output
from Orange.data import Domain, Table
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
    from Orange.widgets.orangecontrib.AAIT.utils.unlink_table_domain import unlink_domain,concatenate_tables_harmonized
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management
    from orangecontrib.AAIT.utils.unlink_table_domain import unlink_domain,concatenate_tables_harmonized

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWAccumulator(widget.OWWidget):
    name = "Data Accumulator (Flexible Columns)"
    description = "Allows for data accumulation by concatenation, automatically merging non-matching columns."
    priority = 10
    category = "AAIT - TOOLBOX"
    icon = "icons/owaccumulator.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owaccumulator.png"

    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owaccumulator.ui")

    want_main_area = True
    want_control_area = False

    class Inputs:
        data = Input("Input Data", Table, auto_summary=False)
        trigger = Input("Trigger", Table, auto_summary=False)

    class Outputs:
        sample = Output("Output", Table, auto_summary=False)

    def __init__(self):
        super().__init__()

        # --- Chargement du fichier UI ---
        uic.loadUi(self.gui, self)

        # --- Récupération dynamique des widgets ---
        self.checkBox_send = self.findChild(QCheckBox, 'checkBox_send')
        self.pushButton_send = self.findChild(QPushButton, 'pushButton_send')

        # --- Variables d’état ---
        self.data = None
        self.out_data = None
        self.str_auto_send = "True"  # valeur par défaut ; peut être persistée via ini

        # --- Initialisation de la checkbox ---
        if self.checkBox_send is not None:
            # Restauration de l’état précédent
            if self.str_auto_send != "False":
                self.checkBox_send.setChecked(True)
            else:
                self.checkBox_send.setChecked(False)

            # ✅ Connexion au changement d’état
            self.checkBox_send.stateChanged.connect(self.update_auto_send_state)

        # ---- Connexion du bouton manuel ----
        if self.pushButton_send is not None:
            self.pushButton_send.clicked.connect(self.push)

        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def update_auto_send_state(self):
        self.str_auto_send = "True" if self.checkBox_send.isChecked() else "False"

    def push(self):
        """Sends the accumulated data and resets the accumulator."""
        if self.data is not None:
            self.out_data = self.data.copy()
            self.Outputs.sample.send(self.out_data)
        else:
            self.Outputs.sample.send(None)
            self.warning("Accumulator is empty, nothing to send.")

    @Inputs.trigger
    def on_trigger(self, signal_data):
        """Handles the incoming trigger signal."""
        if self.data is not None:
            self.Outputs.sample.send(self.data.copy())
            self.information("Data sent on trigger.")
            self.data = None

    @Inputs.data
    def set_data(self, dataset):
        """Accumulates incoming data, merging columns if necessary, with robust variable handling."""
        self.error("")  # Clear previous errors
        self.information("")
        if dataset is None:
            self.data = None
            self.Outputs.sample.send(None)
            return
        # on unlink le domaine pour les données qui rentre
        dataset=unlink_domain(dataset)


        if self.data is None:
            # Première table reçue
            self.data = dataset.copy()
        else:
            try:
                # Fusion flexible des domaines
                current_all_vars = self.data.domain.variables + self.data.domain.metas
                new_all_vars = dataset.domain.variables + dataset.domain.metas

                unique_vars = {}
                for var in current_all_vars + new_all_vars:
                    if var.name not in unique_vars:
                        unique_vars[var.name] = var

                # 2. Identifier les noms d'attributs réguliers et de méta-attributs uniques
                current_regular_names = set(v.name for v in self.data.domain.variables)
                new_regular_names = set(v.name for v in dataset.domain.variables)
                current_metas_names = set(v.name for v in self.data.domain.metas)
                new_metas_names = set(v.name for v in dataset.domain.metas)

                all_vars_names = current_regular_names | new_regular_names
                all_metas_names = current_metas_names | new_metas_names

                # 3. Filtrer les variables uniques pour créer le nouveau domaine
                all_vars = sorted([unique_vars[name] for name in all_vars_names if name not in all_metas_names],
                                  key=lambda x: x.name)
                all_metas = sorted([unique_vars[name] for name in all_metas_names], key=lambda x: x.name)

                new_domain = Domain(all_vars, metas=all_metas)

                data_expanded = self.data.transform(new_domain)
                dataset_expanded = dataset.transform(new_domain)

                # 6. Concatenate the rows of the two uniformly expanded tables
                #self.data = data_expanded.__class__.concatenate((data_expanded, dataset_expanded))
                self.data = concatenate_tables_harmonized([unlink_domain(data_expanded), unlink_domain(dataset_expanded)])
            except Exception as e:
                self.error(f"Data tables could not be aggregated/concatenated. Error: {e}")
                return

        if self.checkBox_send and self.checkBox_send.isChecked():
            self.Outputs.sample.send(self.data)

    def post_initialized(self):
        pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWAccumulator()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
