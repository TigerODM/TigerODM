
from Orange.widgets.widget import OWWidget, Input,Output
from AnyQt.QtWidgets import QApplication
import os
import Orange
import sys
# importe ton viewer sans le modifier
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IMG4IT.utils.tiff16_viewer import batch_process_tiff_files
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import create_trigger_table
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.IMG4IT.utils.tiff16_viewer import batch_process_tiff_files
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.AAIT.utils.MetManagement import create_trigger_table
    from orangecontrib.AAIT.utils.import_uic import uic

class OWImageApplyTransform(OWWidget):
    name = "Image Transformation"
    description = "Apply a transformation to an image"
    icon = "icons/image_transform.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/image_transform.png"
    priority = 10
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_image_apply_transform.ui")
    want_control_area = False
    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)
        data_error = Output("Error", Orange.data.Table)
    def __init__(self):
        super().__init__()
        # Crée le viewer directement avec le chemin fixe
        self.list_image=[]
        self.transform_image=[]
        self.path_out=[]
        self.input_data=None

        uic.loadUi(self.gui, self)
        # Qt Management
        self.setFixedWidth(478)
        self.setFixedHeight(400)

    @Inputs.data
    def set_data(self, in_data):
        self.error("")
        if in_data is None:
            self.Outputs.data.send(None)
            self.Outputs.data_error.send(create_trigger_table())
            return

        if 0!=self.load_list_image_domaine(in_data):
            self.error("input Domain need Image or path Column")
            self.Outputs.data.send(None)
            self.Outputs.data_error.send(create_trigger_table())
            return
        if 0!=self.load_transform_domain(in_data):
            self.error("input Domain need transform column")
            self.Outputs.data.send(None)
            self.Outputs.data_error.send(create_trigger_table())
            return
        if 0!=self.load_path_out_domain(in_data):
            self.error("input Domain need path_out")
            self.Outputs.data.send(None)
            self.Outputs.data_error.send(create_trigger_table())
            return
        self.input_data=in_data
        self.run()

    def load_transform_domain(self,in_data):
        del self.transform_image[:]
        try:
            in_data.domain["transform"]
        except KeyError:
            return 1
        if type(in_data.domain["transform"]).__name__ != 'StringVariable':
            return 1
        for element in in_data.get_column("transform"):
            self.transform_image.append(element)
        return 0

    def load_path_out_domain(self,in_data):
        del self.path_out[:]
        try:
            in_data.domain["path_out"]
        except KeyError:
            return 1
        if type(in_data.domain["path_out"]).__name__ != 'StringVariable':
            return 1
        for element in in_data.get_column("path_out"):
            self.path_out.append(element)
        return 0





    def load_list_image_domaine(self,in_data):
        if 0==self.load_list_image_domaine_image(in_data):
            return 0
        if 0==self.load_list_image_domaine_path(in_data):
            return 0
        return 1

    def load_list_image_domaine_image(self,in_data):
        del self.list_image[:]
        try:
            in_data.domain["image"]
        except KeyError:
            return 1

        if type(in_data.domain["image"]).__name__ != 'StringVariable':
            return 1
        try:
            path_directory_of_image=str(in_data.domain["image"].attributes['origin'])
        except Exception:
            return 1

        for element in in_data.get_column("image"):
            self.list_image.append(path_directory_of_image+"/"+str(element))
        return 0
    def load_list_image_domaine_path(self,in_data):
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
        self.thread = thread_management.Thread(batch_process_tiff_files, self.list_image, self.path_out,self.transform_image)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            ok_idx = [i for i, r in enumerate(result["results"]) if r.get("ok") is True]
            not_ok_idx = [i for i, r in enumerate(result["results"]) if r.get("ok") is False]
            if len(not_ok_idx) == 0:
                self.Outputs.data.send(self.input_data)
                self.Outputs.data_error.send(None)
                return
            if len(ok_idx) == 0:
                try:
                    errors = [r.get("error", "unknown error") for r in result["results"] if not r.get("ok")]
                    msg = "\n".join(errors)
                    self.error(msg)
                except Exception:
                    self.error("error occurs")
                self.Outputs.data.send(None)
                self.Outputs.data_error.send(self.input_data)
                return

            subset = [self.input_data[i] for i in ok_idx]

            # Crée une nouvelle table avec le même domaine
            new_table = Orange.data.Table.from_list(self.input_data.domain, subset)

            subset_error = [self.input_data[i] for i in not_ok_idx]

            # Crée une nouvelle table avec le même domaine
            new_table_error = Orange.data.Table.from_list(self.input_data.domain, subset_error)
            self.error("error occurs")
            self.Outputs.data.send(new_table)
            self.Outputs.data_error.send(new_table_error)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        print("Transformation finished")
        self.progressBarFinished()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWImageApplyTransform()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
    # from Orange.widgets.orangecontrib.IMG4IT.utils.tiff16_viewer import transform_tiff16_to_tiff8
    #
    # print("ici")
    # spec = "Transform | Min(I16) = 59221 | Max(I16) = 65535 | Mode = Sigmoide"
    # info = transform_tiff16_to_tiff8(r"C:\pozipokaze\toto.tif", r"C:\pozipokaze\toto_out.tif", spec)
    # print(info)