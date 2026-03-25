from Orange.widgets.widget import OWWidget, Input, Output
from AnyQt.QtWidgets import QApplication
import os
import Orange
import sys
from functools import partial
from Orange.widgets import gui
from orangewidget.settings import Setting

# importe ton viewer sans le modifier
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IMG4IT.utils.reacalage_image import batch_process_tiff_register
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
else:
    from orangecontrib.IMG4IT.utils.reacalage_image import batch_process_tiff_register
    from orangecontrib.AAIT.utils import thread_management


class OWImageRigidTransform(OWWidget):
    name = "Compute Rigid Transformation"
    description = "Apply a transformation to an image"
    icon = "icons/recalage.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/recalage.png"
    priority = 10

    want_control_area = True
    use_fourier_mellin = Setting(False)

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    def __init__(self):
        super().__init__()

        self.list_image = []
        self.path_out = []
        self.input_data = None

        gui.checkBox(
            self.controlArea,
            self,
            "use_fourier_mellin",
            "Fourier–Mellin (-pi/2<R<pi/2)",
            callback=self._on_method_changed,
        )

    # ✅ IMPORTANT: handler Input DOIT être au niveau de la classe (pas dans __init__)
    @Inputs.data
    def set_data(self, in_data):
        self.error("")
        if in_data is None:
            self.Outputs.data.send(None)
            return

        if 0 != self.load_list_image_domaine(in_data):
            self.error("input Domain need Image or path Column")
            self.Outputs.data.send(None)
            return
        if 0 != self.load_path_out_domain(in_data):
            self.error("input Domain need path_mov")
            self.Outputs.data.send(None)
            return

        self.input_data = in_data
        self.run()

    def _on_method_changed(self):
        # relance si on a déjà une entrée valide
        if self.input_data is not None and self.list_image and self.path_out:
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
        self.progressBarInit()

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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWImageRigidTransform()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
