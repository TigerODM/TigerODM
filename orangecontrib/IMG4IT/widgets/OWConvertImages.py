import os
from PIL import Image
import pillow_heif
import Orange
from Orange.data import Table, Domain, StringVariable
from Orange.widgets.widget import OWWidget, Input, Output
from AnyQt.QtWidgets import QApplication

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
else:
    from orangecontrib.AAIT.utils import thread_management

class OWConvertImages(OWWidget):
    name = "Convert Images"
    description = "Takes one or more folders as input. In these folders, if a .zip file is found, extract the images it contains, convert them to JPG, and reduce their resolution to decrease the image file size."
    icon = "icons/resize-picture.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/resize-picture.svg"
    priority = 3000
    want_control_area = False

    class Inputs:
        data = Input("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.data is None:
            return
        if "path" not in in_data.domain:
            self.error("No path provided.")
            return
        if "converted_path" not in in_data.domain:
            self.error("No converted_path provided.")
            return
        self.path = in_data.get_column("path")
        self.converted_path = in_data.get_column("converted_path")
        self.run()

    class Outputs:
        data = Output("Data", Orange.data.Table)

    def __init__(self):
        super().__init__()
        self.data = None
        self.converted_path = None
        self.path = None
        self.MAX_SIZE = (1200, 1200)
        self.new_image_paths = []
        self.run()

    def convert_images(self, progress_callback=None):
        pillow_heif.register_heif_opener()
        for i in range(len(self.path)):
            image_paths = []
            for root, dirs, files in os.walk(self.path[i]):
                for fname in files:
                    if fname.lower().endswith((".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heif", ".heic")):
                        image_paths.append(os.path.join(root, fname))
            os.makedirs(self.converted_path[i], exist_ok=True)
            for image_path in image_paths:
                ext = os.path.splitext(image_path)[1].lower()
                image_path = image_path.replace("\\", "/")
                if ext in [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heif", ".heic"]:
                    try:
                        image = Image.open(image_path)
                        if image.mode != 'RGB':
                            image = image.convert('RGB')
                        image.thumbnail(self.MAX_SIZE)
                        new_filename = os.path.splitext(os.path.basename(image_path))[0] + ".jpg"
                        new_path = os.path.join(self.converted_path[i], new_filename)
                        image.save(new_path, format="JPEG", quality=90)
                        self.new_image_paths.append([str(new_path)])
                        # Supprimer l'original (facultatif)
                        # os.remove(img_path)
                    except Exception as e:
                        print(f"Erreur de conversion {image_path} : {e}")
            if progress_callback is not None:
                progress_value = float(100 * (i + 1) / len(self.path))
                progress_callback(progress_value)
        return self.new_image_paths

    def run(self):
        self.error("")
        self.warning("")
        if self.path is None:
            return
        if self.converted_path is None:
            return

        self.progressBarInit()
        self.thread = thread_management.Thread(self.convert_images)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, progress) -> None:
        value = progress
        if value is not None:
            self.progressBarSet(value)

    def handle_result(self):
        X = [[] for _ in self.new_image_paths]
        domain = Domain([], metas=[StringVariable("image_paths")])
        table = Table.from_numpy(domain, X, metas= self.new_image_paths)
        self.Outputs.data.send(table)
        self.new_image_paths = []

    def handle_finish(self):
        print("Generation finished")
        self.progressBarFinished()


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    my_widget = OWConvertImages()
    my_widget.show()
    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
