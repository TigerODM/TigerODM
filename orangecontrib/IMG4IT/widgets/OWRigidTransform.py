import os
import sys
from functools import partial
import Orange
from Orange.widgets.widget import Input, Output
from orangewidget.settings import Setting
from AnyQt.QtWidgets import QApplication, QCheckBox, QPushButton

# importe ton viewer sans le modifier
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IMG4IT.utils.reacalage_image import batch_process_tiff_register
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, base_widget
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.IMG4IT.utils.reacalage_image import batch_process_tiff_register
    from orangecontrib.AAIT.utils import thread_management, base_widget
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file

ParentWidget = getattr(base_widget, "BaseWidget", getattr(base_widget, "BaseListWidget", Orange.widgets.widget.OWWidget))


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWImageRigidTransform(ParentWidget):
    name = "Compute Rigid Transformation"
    description = "Apply a transformation to an image"
    icon = "icons/recalage.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/recalage.png"
    priority = 10

    # Liaison avec le fichier .ui
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_image_rigid_transform.ui")
    want_control_area = False

    use_fourier_mellin = Setting(False)
    auto_send = Setting(True)

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    def __init__(self):
        super().__init__()

        self.list_image = []
        self.path_out = []
        self.input_data = None

        # Sécurité : masque le sélecteur parasite si hérité de AAIT
        if hasattr(self, "var_selector") and self.var_selector:
            self.var_selector.hide()

        # Connexions aux widgets de l'interface
        self.checkBox_fourier_mellin = self.findChild(QCheckBox, 'checkBox_fourier_mellin')
        self.checkBox_send = self.findChild(QCheckBox, 'checkBox_send')
        self.pushButton_run = self.findChild(QPushButton, 'pushButton_run')

        if self.checkBox_fourier_mellin:
            self.checkBox_fourier_mellin.setChecked(self.use_fourier_mellin)
            self.checkBox_fourier_mellin.toggled.connect(self._on_fourier_mellin_toggled)

        if self.checkBox_send:
            self.checkBox_send.setChecked(self.auto_send)
            self.checkBox_send.toggled.connect(self._on_auto_send_toggled)

        if self.pushButton_run:
            self.pushButton_run.clicked.connect(self.run)

        self.check_ready()

    def check_ready(self):
        """Active le bouton seulement si les données sont prêtes."""
        if self.pushButton_run:
            is_ready = bool(self.input_data is not None and self.list_image and self.path_out)
            self.pushButton_run.setEnabled(is_ready)

    def _on_auto_send_toggled(self, checked: bool):
        self.auto_send = checked
        if self.auto_send and self.input_data is not None and self.list_image and self.path_out:
            self.run()

    def _on_fourier_mellin_toggled(self, checked: bool):
        self.use_fourier_mellin = checked
        self._on_method_changed()

    def _on_method_changed(self):
        # relance si on a déjà une entrée valide
        if self.auto_send and self.input_data is not None and self.list_image and self.path_out:
            self.run()

    # ✅ IMPORTANT: handler Input DOIT être au niveau de la classe (pas dans __init__)
    @Inputs.data
    def set_data(self, in_data):
        self.error("")
        if in_data is None:
            self.input_data = None
            self.check_ready()
            self.Outputs.data.send(None)
            return

        if 0 != self.load_list_image_domaine(in_data):
            self.error("input Domain need Image or path Column")
            self.check_ready()
            self.Outputs.data.send(None)
            return
        if 0 != self.load_path_out_domain(in_data):
            self.error("input Domain need path_mov")
            self.check_ready()
            self.Outputs.data.send(None)
            return

        self.input_data = in_data
        self.check_ready()

        if self.auto_send:
            self.run()

    def load_path_out_domain(self, in_data):
        del self.path_out[:]
        try:
            in_data.domain["path_mov"]
        except KeyError:
            return 1
        if type(in_data.domain["path_mov"]).__name__ != 'StringVariable':
            return 1
        for element in in_data.get_column("path_mov"):
            self.path_out.append(element)
        return 0

    def load_list_image_domaine(self, in_data):
        if 0 == self.load_list_image_domaine_image(in_data):
            return 0
        if 0 == self.load_list_image_domaine_path(in_data):
            return 0
        return 1

    def load_list_image_domaine_image(self, in_data):
        del self.list_image[:]
        try:
            in_data.domain["image"]
        except KeyError:
            return 1

        if type(in_data.domain["image"]).__name__ != 'StringVariable':
            return 1
        try:
            path_directory_of_image = str(in_data.domain["image"].attributes['origin'])
        except Exception:
            return 1

        for element in in_data.get_column("image"):
            self.list_image.append(path_directory_of_image + "/" + str(element))
        return 0

    def load_list_image_domaine_path(self, in_data):
        del self.list_image[:]
        try:
            in_data.domain["path"]
        except KeyError:
            return 1

        if type(in_data.domain["path"]).__name__ != 'StringVariable':
            return 1
        for element in in_data.get_column("path"):
            self.list_image.append(element)
        return 0

    def run(self):
        self.error("")
        if not self.list_image or not self.path_out:
            return

        self.progressBarInit()
        if self.pushButton_run:
            self.pushButton_run.setEnabled(False)

        # ⚠️ IMPORTANT: garder exactement les mêmes args (list_image, path_out)
        # et juste injecter use_fourier_mellin en "keyword only"
        func = partial(batch_process_tiff_register, use_fourier_mellin=self.use_fourier_mellin)

        self.thread = thread_management.Thread(func, self.list_image, self.path_out)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        var = Orange.data.StringVariable("transform")
        dom = Orange.data.Domain([], metas=[var])

        rows = [[s] for s in result]
        table = Orange.data.Table.from_list(dom, rows)
        self.Outputs.data.send(table)

    def handle_finish(self):
        print("Transformation finished")
        self.progressBarFinished()
        self.check_ready()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWImageRigidTransform()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()