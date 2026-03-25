import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
import sys
import numpy as np

import fitz
from PIL import Image
from paddleocr import PaddleOCR

import Orange.data
from Orange.data import Table, Domain, StringVariable, ContinuousVariable
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, SimpleDialogQt
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import GetFromRemote, get_local_store_path
else:
    from orangecontrib.AAIT.utils import thread_management, SimpleDialogQt
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils.MetManagement import GetFromRemote, get_local_store_path



@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWPaddleOCR(widget.OWWidget):
    name = "Paddle OCR"
    description = "Apply OCR on the PDF documents present in the 'path' column of the input Table"
    icon = "icons/paddleocr.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/paddleocr.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owpaddleocr.ui")
    want_control_area = False
    priority = 1212

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.autorun:
            self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        # Data Management
        self.data = None
        self.model = None
        self.thread = None
        self.autorun = True
        self.result = None
        self.load_model()
        self.post_initialized()

    def load_model(self):
        local_store_path = get_local_store_path()
        model_path = os.path.join(local_store_path, "Models", "ComputerVision", ".paddleocr", "whl")
        load = True
        if not os.path.exists(model_path):
            load = False
            self.error("PaddleOCR model is not in your computer. This widget cannot process your data.")
            if not SimpleDialogQt.BoxYesNo("Model isn't in your computer. Do you want to download it from AAIT store?"):
                return
            try:
                if 0 == GetFromRemote("Paddle OCR"):
                    load = True
                    self.error("")
            except:
                SimpleDialogQt.BoxError("Unable to get the Model.")
                return
        if load:
            self.model = PaddleOCR(use_angle_cls=True, lang="fr",
                                   det_model_dir=os.path.join(model_path, "det"),
                                   rec_model_dir=os.path.join(model_path, "rec"),
                                   cls_model_dir=os.path.join(model_path, "cls"),
                                   show_log=False)
            self.information("Paddle OCR model successfully loaded.")

    def run(self):
        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            return

        if self.model is None:
            return

        # Verification of in_data
        self.error("")
        try:
            self.data.domain["path"]
        except KeyError:
            self.error('You need a "path" column in input data')
            return

        if type(self.data.domain["path"]).__name__ != 'StringVariable':
            self.error('"path" column needs to be a Text')
            return

        # Start progress bar
        self.progressBarInit()

        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        self.thread = thread_management.Thread(self.apply_OCR_on_Table, self.data, self.model)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.result = result
            self.Outputs.data.send(result)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        print("Embeddings finished")
        self.progressBarFinished()

    def post_initialized(self):
        pass


    def apply_OCR_on_Table(self, table, model, progress_callback=None, argself=None):
        # Copy of input data
        data = table.copy()
        attr_dom = list(data.domain.attributes)
        metas_dom = list(data.domain.metas)
        class_dom = list(data.domain.class_vars)

        # Iterate on the data Table
        rows = []
        for i, row in enumerate(data):
            # Get the rest of the data
            features = [row[x] for x in attr_dom]
            targets = [row[y] for y in class_dom]
            metas = list(data.metas[i])
            filepath = row["path"].value
            result_per_page = apply_OCR(filepath, model)
            for key, value in result_per_page.items():
                new_row = features + targets + metas + [key, value]
                rows.append(new_row)
            if progress_callback is not None:
                progress_value = float(100 * (i + 1) / len(data))
                progress_callback(progress_value)
            if argself is not None:
                if argself.stop:
                    break

        # Create new Domain for new columns
        ocr_dom = [ContinuousVariable("Page n°"), StringVariable("OCR Extraction")]
        domain = Domain(attributes=attr_dom, metas=metas_dom + ocr_dom, class_vars=class_dom)

        # Create and return table
        out_data = Table.from_list(domain=domain, rows=rows)
        return out_data


def apply_OCR(filepath, model):
    """
    Apply OCR to a file (PDF or image), returning a dict of page_number -> text.

    Args:
        filepath (str): Path to the file (PDF, PNG, JPG, etc.)
        model: An initialized PaddleOCR model instance.

    Returns:
        dict[int, str]: page_number -> recognized text
    """
    if not os.path.exists(filepath):
        return {-1: "File not found"}

    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".pdf":
        return apply_OCR_on_pdf(filepath, model)
    elif ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"]:
        return apply_OCR_on_image(filepath, model)
    else:
        return {-1: f"Unsupported file extension: {ext}"}


def apply_OCR_on_image(filepath, model):
    # Load image as RGB
    img = Image.open(filepath).convert("RGB")
    img = np.array(img)

    # Apply OCR
    results = model.ocr(img, cls=True)
    result_ocr = results[0] if results and results[0] else []

    # Concatenate all detected text
    full_text = ""
    for line in result_ocr:
        text = line[1][0]
        # confidence = line[1][1]  # available if needed
        full_text += text + "\n"

    return {0: full_text}


def apply_OCR_on_pdf(filepath, model, dpi=300):
    # Load the document
    doc = fitz.open(filepath)
    # Iterate over pages
    result_per_page = {}
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)

        # Render page to a pixmap (RGB image)
        mat = fitz.Matrix(dpi/72, dpi/72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)

        # Apply OCR
        results = model.ocr(img, cls=True)
        result_ocr = results[0] if results and results[0] else []

        # Concatenate all detected text
        full_text = ""
        for line in result_ocr:
            text = line[1][0]
            # confidence = line[1][1] # maybe useful later
            full_text += text + "\n"
        result_per_page[page_num+1] = full_text
    return result_per_page


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWPaddleOCR()
    my_widget.show()
    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
