import os
import sys
import Orange.data
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QLineEdit, QComboBox, QApplication

# Adapte ces imports selon ton arborescence locale
try:
    from orangecontrib.AAIT.utils import thread_management, base_widget
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
except ImportError:
    pass

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IMG4IT.utils.image_detection_methods import run_detection_thread, DETECTORS
else:
    from orangecontrib.IMG4IT.utils.image_detection_methods import run_detection_thread, DETECTORS

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWShapeDetector(base_widget.BaseListWidget):
    name = "Shape Detector"
    description = "Detects shape in X-Ray images using various methods."
    icon = "icons/circle_detect.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owshapedetector.ui")
    want_control_area = False
    priority = 1060

    # --- Settings (Sauvegardés dans l'interface) ---
    method: str = Setting("Hough Transform")
    minDist: str = Setting("12")
    param1: str = Setting("50")
    param2: str = Setting("20")
    minRadius: str = Setting("11")
    maxRadius: str = Setting("18")
    selected_column_name = Setting("image_path") # Nom de la colonne contenant l'image

    class Inputs:
        data = Input("Images Data", Orange.data.Table)

    class Outputs:
        data = Output("Detected Data", Orange.data.Table)
        infos = Output("Information", Orange.data.Table)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(470)
        self.setFixedHeight(550)

        # --- Connexion des éléments UI ---
        # Méthode de détection
        self.edit_method = self.findChild(QComboBox, "comboBox_method")
        self.edit_method.addItems(list(DETECTORS.keys()))
        self.edit_method.setCurrentText(self.method)
        self.edit_method.currentTextChanged.connect(self.update_method)

        # Paramètres Hough (Tu devras créer ces QLineEdit dans ton designer Qt)
        self.edit_minDist = self.findChild(QLineEdit, 'lineEdit_minDist')
        self.edit_minDist.setText(str(self.minDist))
        self.edit_minDist.textChanged.connect(lambda t: setattr(self, 'minDist', t))

        self.edit_param1 = self.findChild(QLineEdit, 'lineEdit_param1')
        self.edit_param1.setText(str(self.param1))
        self.edit_param1.textChanged.connect(lambda t: setattr(self, 'param1', t))

        self.edit_param2 = self.findChild(QLineEdit, 'lineEdit_param2')
        self.edit_param2.setText(str(self.param2))
        self.edit_param2.textChanged.connect(lambda t: setattr(self, 'param2', t))

        self.edit_minRadius = self.findChild(QLineEdit, 'lineEdit_minRadius')
        self.edit_minRadius.setText(str(self.minRadius))
        self.edit_minRadius.textChanged.connect(lambda t: setattr(self, 'minRadius', t))

        self.edit_maxRadius = self.findChild(QLineEdit, 'lineEdit_maxRadius')
        self.edit_maxRadius.setText(str(self.maxRadius))
        self.edit_maxRadius.textChanged.connect(lambda t: setattr(self, 'maxRadius', t))

        self.data = None
        self.thread = None
        self.autorun = True

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        # Mise à jour du sélecteur de colonnes (hérité de BaseListWidget)
        if self.data:
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        if self.autorun:
            self.run()

    def update_method(self, text):
        self.method = text
        # Tu pourrais ici cacher/afficher les champs paramètres en fonction de la méthode choisie
        # Exemple : if text == "Blob Detection": self.edit_minDist.hide() ...

    def run(self):
        self.error("")
        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            return

        # Regrouper les paramètres pour les envoyer au thread
        params = {
            "minDist": self.minDist,
            "param1": self.param1,
            "param2": self.param2,
            "minRadius": self.minRadius,
            "maxRadius": self.maxRadius
        }

        self.progressBarInit()

        # Démarrage du thread avec notre fonction métier
        self.thread = thread_management.Thread(
            run_detection_thread,
            self.data,
            self.selected_column_name,
            self.method,
            params
        )
        self.thread.progress.connect(self.progressBarSet)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.progressBarFinished)
        self.thread.start()

    def handle_result(self, result):
        try:
            # result[0] contient la nouvelle table, result[1] les infos
            self.Outputs.data.send(result[0])
            self.Outputs.infos.send(result[1])
        except Exception as e:
            print("Erreur :", e)
            self.Outputs.data.send(None)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWShapeDetector()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()