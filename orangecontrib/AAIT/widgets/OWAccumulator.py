from Orange.widgets import widget
import sys
import os

from AnyQt.QtWidgets import QApplication, QPushButton, QCheckBox
from Orange.widgets.settings import Setting
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
    auto_send = Setting(True)

    class Inputs:
        data = Input("Input Data", Table, auto_summary=False)
        trigger = Input("Trigger", Table, auto_summary=False)

    class Outputs:
        sample = Output("Output", Table, auto_summary=False)
        preview = Output("Preview", Table, auto_summary=False)

    def __init__(self):
        super().__init__()

        # --- Chargement du fichier UI ---
        uic.loadUi(self.gui, self)
        self.setFixedSize(500,300)

        # --- Récupération dynamique des widgets ---
        self.checkBox_send = self.findChild(QCheckBox, 'checkBox_send')
        self.pushButton_send = self.findChild(QPushButton, 'pushButton_send')
        self.pushButton_purge = self.findChild(QPushButton, 'pushButton_purge')

        # --- Variables d’état ---
        self.data = None
        self.out_data = None

        # --- Bouton "Send Data" (envoi sans purge) ---
        self.pushButton_send.clicked.connect(lambda: self.push(clean=False))

        # --- Bouton "Purge" (vidage manuel) ---
        # Recupere depuis le .ui sous le nom "pushButton_purge" s'il existe, sinon cree au vol.
        self.pushButton_purge.clicked.connect(self.purge)

        # --- Checkbox auto-send (etat restaure depuis le Setting) ---
        self.checkBox_send.setChecked(self.auto_send)
        self.checkBox_send.toggled.connect(self.on_auto_send_changed)

        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def on_auto_send_changed(self):
        """Memorise l'etat de l'auto-send et envoie immediatement si on vient de l'activer."""
                                 
        self.auto_send = self.checkBox_send.isChecked()
        if self.auto_send:
            self.push(clean=False)

    def push(self, clean=False):
        """Envoie les donnees accumulees.

        clean=False -> envoie sans vider (les donnees continuent de s'accumuler).
        clean=True  -> envoie puis vide l'accumulateur (flush / purge manuel).
        """
        self.warning("")
        if self.data is None:
            self.Outputs.sample.send(None)
            self.warning("Accumulator is empty, nothing to send.")
            return

        self.out_data = self.data.copy()
        self.Outputs.sample.send(self.out_data)

        if clean:
            self.data = None
            self.Outputs.preview.send(None)

    def purge(self):
        """Vide l'accumulateur sans rien envoyer sur "Output".

        N'emet rien sur sample (la sortie aval garde sa derniere valeur) :
        on remet juste le tampon a None et on vide la preview.
        """
        self.warning("")
        self.data = None
        self.Outputs.preview.send(None)

    @Inputs.trigger
    def on_trigger(self, signal_data):
        """Un vrai signal (table non None) declenche un envoi + purge.
        On ignore les None (ex. debranchement en amont) pour ne pas vider par accident."""
        if signal_data is None:
            return
        if self.data is not None:
            self.push(clean=False)
            self.information("Data sent on trigger.")
                            

    @Inputs.data
    def set_data(self, dataset):
        """Accumule les donnees entrantes, en fusionnant les colonnes si necessaire."""
        self.error("")  # Clear previous errors
        self.information("")
        self.warning("")

        # Une entree None n'efface JAMAIS l'accumulateur : le vidage est uniquement
        # manuel (bouton "Send Data and Purge" ou trigger). On ignore donc le None.
        if dataset is None:
            return
                                                           
        # on unlink le domaine pour les donnees qui rentrent
        dataset = unlink_domain(dataset)

        if self.data is None:
            # Premiere table recue
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

                # 2. Identifier les noms d'attributs reguliers et de meta-attributs uniques
                current_regular_names = set(v.name for v in self.data.domain.variables)
                new_regular_names = set(v.name for v in dataset.domain.variables)
                current_metas_names = set(v.name for v in self.data.domain.metas)
                new_metas_names = set(v.name for v in dataset.domain.metas)

                all_vars_names = current_regular_names | new_regular_names
                all_metas_names = current_metas_names | new_metas_names

                # 3. Filtrer les variables uniques pour creer le nouveau domaine
                all_vars = sorted([unique_vars[name] for name in all_vars_names if name not in all_metas_names],
                                  key=lambda x: x.name)
                all_metas = sorted([unique_vars[name] for name in all_metas_names], key=lambda x: x.name)

                new_domain = Domain(all_vars, metas=all_metas)

                data_expanded = self.data.transform(new_domain)
                dataset_expanded = dataset.transform(new_domain)

                # 6. Concatenate the rows of the two uniformly expanded tables
                                                                                                   
                self.data = concatenate_tables_harmonized([unlink_domain(data_expanded), unlink_domain(dataset_expanded)])
            except Exception as e:
                self.error(f"Data tables could not be aggregated/concatenated. Error: {e}")
                return

        # Apercu live du tampon accumule (independant de l'envoi sur "Output")
        self.Outputs.preview.send(self.data)

        if self.auto_send:
            self.push(clean=False)

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
