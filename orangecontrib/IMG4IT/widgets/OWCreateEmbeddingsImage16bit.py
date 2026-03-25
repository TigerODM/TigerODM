import os
import sys

import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
import Orange
from Orange.data import ContinuousVariable
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.IMG4IT.utils import compute_embedding_16b
else:
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.IMG4IT.utils import compute_embedding_16b

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWCreateEmbeddings(widget.OWWidget):
    name = "X ray embedding"
    description = "Create embeddings on tif image 16 bit"
    #category = "AAIT - LLM INTEGRATION"
    icon = "icons/embedding_Xray.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/embedding_Xray.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owembedding_img16b.ui")
    want_control_area = False
    priority = 1060

    class Inputs:
        data = Input("Data", Orange.data.Table)
        model = Input("Image Model", str, auto_summary=False)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.error("")
        if in_data is None:
            self.Outputs.data.send(None)
            return

        self.data = in_data
        if self.model is None:
            self.error("error need a model")
            self.Outputs.data.send(None)
            return
        self.run()
        # if self.autorun:
        #     self.run()
    @Inputs.model
    def set_model(self, model):
        self.error("")
        if model is None:
            self.Outputs.data.send(None)
            return
        if "resnet50-0676ba61.pth" in model:
            self.model="resnet50"
        elif "dinov2-base"in model:
            self.model="dinov2"
        else :
            self.error("This model can not be loaded")
            self.model=None
            self.Outputs.data.send(None)
            return

        if self.data is None:
            self.error("error need data")
            self.Outputs.data.send(None)
            return
        self.run()
    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.list_image=[]
        # Data Management
        self.model = None
        self.data = None
        self.thread = None
        self.autorun = True
        self.result = None
        self.post_initialized()

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
        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            return


        # Verification of in_data
        self.error("")
        self.list_image=[]
        if 0!=self.load_list_image_domaine(self.data):
            self.error("input Domain need Image or path Column")
            self.Outputs.data.send(None)
            return

        if len(self.list_image)==0:
            self.error('You need input images')
            return

        for element in self.list_image:
            if element[-4:]!=".tif":
                if element[-4:] != ".TIF" :
                    print(element)
                    print(element[-4:])
                    self.error('only tif image in this version')
                    return


        # Start progress bar
        self.progressBarInit()

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished

        if self.model=="dinov2":
            self.thread = thread_management.Thread(compute_embedding_16b.compute_dinov2_embedding, self.list_image)
        elif self.model=="resnet50":
            self.thread = thread_management.Thread(compute_embedding_16b.compute_resnet_embedding, self.list_image)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            out_data=self.data
            if out_data==None:
                self.Outputs.data.send(None)
                return
            for i in range(len(result)):
                out_data = out_data.add_column(ContinuousVariable(self.model+"_"+str(i)), result[i])
            self.Outputs.data.send(out_data)


        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        print("Embeddings finished")
        self.progressBarFinished()

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWCreateEmbeddings()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
