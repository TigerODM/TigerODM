import os
import sys

import Orange.data
from AnyQt.QtWidgets import QApplication,QCheckBox

from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.IO4IT.ocr_function import word_converter
else:
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.IO4IT.ocr_function import word_converter

class OWwordpdf2docx(widget.OWWidget):
    name = "WordPdf2Docx"
    description = "Convert pdf from a directory to docx using word"
    icon = "icons/wordpdf2docx.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/wordpdf2docx.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/wordpdf2docx.ui")
    want_control_area = False
    priority = 3000
    category = "AAIT - TOOLBOX"
    strIgnoreExistingOuput :str =Setting('True')
    strForceBasicConvertion :str =Setting('False')

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.autorun:
            self.run()
    def on_checkbox_toggled(self):
        if self.check_box.isChecked():
            self.strIgnoreExistingOuput='True'
        else:
            self.strIgnoreExistingOuput = 'False'

    def on_checkbox_toggled2(self):
        if self.check_box2.isChecked():
            self.strForceBasicConvertion='True'
        else:
            self.strForceBasicConvertion = 'False'
    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.check_box= self.findChild(QCheckBox, 'checkBox')
        self.check_box2= self.findChild(QCheckBox, 'checkBox_2')
        if self.strIgnoreExistingOuput=='True':
            self.check_box.setChecked(True)
        else:
            self.check_box.setChecked(False)

        if self.strForceBasicConvertion=='False':
            self.check_box2.setChecked(False)
        else:
            self.check_box2.setChecked(True)
        self.check_box.stateChanged.connect(self.on_checkbox_toggled)
        self.check_box2.stateChanged.connect(self.on_checkbox_toggled2)

        # Data Management
        self.data = None
        self.thread = None
        self.autorun = True
        self.result = None
        self.post_initialized()

    def run(self):
        self.error("")
        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            return


        # Verification of in_data
        self.error("")
        try:
            self.data.domain["input_dir"]
        except KeyError:
            self.error('You need a "input_dir" column in input data')
            return

        if type(self.data.domain["input_dir"]).__name__ != 'StringVariable':
            self.error('"input_dir" column needs to be a Text')
            return
        try:
            self.data.domain["output_dir"]
        except KeyError:
            self.error('You need a "output_dir" column in input data')
            return

        if type(self.data.domain["output_dir"]).__name__ != 'StringVariable':
            self.error('"output_dir" column needs to be a Text')
            return
        input_dir = self.data.get_column("input_dir")
        output_dir = self.data.get_column("output_dir")

        # Start progress bar
        self.progressBarInit()
        # Connect and start thread : main function, progress, result and finish
        # --> progress is used in the main function to track progress (with a callback)
        # --> result is used to collect the result from main function
        # --> finish is just an empty signal to indicate that the thread is finished
        ignore_existing_docx=False
        if self.strIgnoreExistingOuput=="True":
            ignore_existing_docx=True
        forceBasicConvertion=True
        if self.strForceBasicConvertion=='False':
            forceBasicConvertion=False
        self.thread = thread_management.Thread(word_converter.convert_pdf_structure, input_dir, output_dir,ignore_exsting_out_put=ignore_existing_docx,forceBasicConvertion=forceBasicConvertion)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.result = result
            self.error(result)
            self.Outputs.data.send(self.data)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        print("conversion finished")
        self.progressBarFinished()

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWwordpdf2docx()
    my_widget.show()
    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
