
from Orange.widgets.widget import OWWidget, Input
from AnyQt.QtWidgets import QApplication
import os
import Orange
import sys
from pathlib import Path
# importe ton viewer sans le modifier
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IMG4IT.utils.tiff16_viewer import view_tiff_qt
else:
    from orangecontrib.IMG4IT.utils.tiff16_viewer import view_tiff_qt

class OWTiff16Viewer(OWWidget):
    name = "XRAY Viewer"
    description = "Show 16 bit image viewer"
    icon = "icons/viewer_xray_icon.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/viewer_xray_icon.png"
    priority = 10
    want_control_area = False
    class Inputs:
        data = Input("Data", Orange.data.Table)


    def __init__(self):
        super().__init__()
        # Crée le viewer directement avec le chemin fixe
        self.viewer = None#view_tiff_qt(r"C:\Users\jean-\Desktop\pozipokaze\toto.tif", parent=self)
        # Insère le viewer dans la zone principale
        #self.mainArea.layout().addWidget(self.viewer)

    @Inputs.data
    def set_data(self, in_data):
        self.error("")
        if in_data is None:
            return

        self.data = in_data
        self.list_image= []
        self.run()


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
        if self.data is None:
            return
        if 0!=self.load_list_image_domaine(self.data):
            self.error("input Domain need Image or path Column")
            self.Outputs.data.send(None)
            return
        liste_file=self.list_image



        if len(liste_file)!=1:
            self.error('You need only one input images')


            return
        path_img=liste_file[0]
        if str(Path(path_img).suffix.lower())!=".tif":
            self.error('You need a tif image')
            return
        self.viewer =view_tiff_qt(liste_file[0], parent=self)
        layout = self.mainArea.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        layout.addWidget(self.viewer)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWTiff16Viewer()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
    # from Orange.widgets.orangecontrib.IMG4IT.utils.tiff16_viewer import transform_tiff16_to_tiff8
    #
    # print("ici")
    # spec = "Transform | Min(I16) = 59221 | Max(I16) = 65535 | Mode = Sigmoide"
    # info = transform_tiff16_to_tiff8(r"C:\Users\jean-\Desktop\pozipokaze\toto.tif", r"C:\Users\jean-\Desktop\pozipokaze\toto_out.tif", spec)
    # print(info)