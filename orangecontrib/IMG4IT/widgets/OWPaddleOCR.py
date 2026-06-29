import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
import sys
import tempfile
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
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, MetManagement
    from Orange.widgets.orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import thread_management, MetManagement
    from orangecontrib.AAIT.utils.local_store_sync import get_path_or_retrieve
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file



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
        self.error("")

        local_store_path = MetManagement.get_local_store_path()
        det_model_path = os.path.join(local_store_path, "Models", "ComputerVision", "PaddleOCR", "PP-OCRv5_server_det")
        rec_model_path = os.path.join(local_store_path, "Models", "ComputerVision", "PaddleOCR", "latin_PP-OCRv5_mobile_rec")

        if not os.path.exists(det_model_path) or not os.path.exists(rec_model_path):
            try:
                get_path_or_retrieve("Paddle OCR")
            except Exception as e:
                self.error(str(e))
                return

        if os.path.exists(det_model_path) and os.path.exists(rec_model_path):
            self.model = PaddleOCR(
                text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
                text_recognition_model_dir=rec_model_path,
                text_detection_model_name="PP-OCRv5_server_det",
                text_detection_model_dir=det_model_path,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
            self.information("Paddle OCR model successfully loaded.")

        else:
            self.error("Paddle OCR model could not be loaded. Do you have 'latin_PP-OCRv5_mobile_rec' and 'PP-OCRv5_server_det' in your AAIT store ?")

    def run(self):
        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            return

        if self.model is None:
            self.load_model()
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
        print("OCR Finished")
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
            filepath = row["path"].value.strip("'").strip('"')
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
    # Apply OCR
    results = model.predict(filepath)
    results = results[0] if results and results[0] else []

    # Concatenate all detected text
    full_text = ""
    for text in results["rec_texts"]:
        full_text += text + "\n"
    return {0: full_text}


def apply_OCR_on_pdf(filepath, model, dpi=300):
    """
    Convert each PDF page to a temporary PNG, apply OCR,
    return {page_number: extracted_text}.
    """
    doc = fitz.open(filepath)
    result_per_page = {}

    try:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)

            # Render page
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)

            # Create temporary PNG
            with tempfile.NamedTemporaryFile(
                suffix=".png",
                delete=False
            ) as tmp:
                tmp_path = tmp.name

            try:
                pix.save(tmp_path)

                # Same OCR logic as apply_OCR_on_image
                results = model.predict(tmp_path)
                results = results[0] if results and results[0] else []

                full_text = ""
                for text in results["rec_texts"]:
                    full_text += text + "\n"

                result_per_page[page_num + 1] = full_text

            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

    finally:
        doc.close()

    return result_per_page


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWPaddleOCR()
    my_widget.show()
    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
