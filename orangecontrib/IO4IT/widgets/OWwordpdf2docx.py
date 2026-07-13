import os
import sys
from pathlib import Path

import Orange.data
from AnyQt.QtWidgets import QApplication, QCheckBox

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


def _import_convert_to_pdf():
    """Import paresseux de `convert_to_pdf` (PageIndex)."""
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        from Orange.widgets.orangecontrib.AAIT.llm.PageIndex_functions import convert_to_pdf
    else:
        from orangecontrib.AAIT.llm.PageIndex_functions import convert_to_pdf
    return convert_to_pdf


class OWwordpdf2docx(widget.OWWidget):
    name = "WordPdf2Docx"
    description = "Convert PDF to DOCX and/or DOCX to PDF for every file in a directory"
    icon = "icons/wordpdf2docx.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/wordpdf2docx.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/wordpdf2docx.ui")
    want_control_area = False
    priority = 3000
    category = "AAIT - TOOLBOX"
    strConvertPdfToDocx : str =Setting('True')
    strConvertDocxToPdf : str =Setting('False')
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
            self.strConvertPdfToDocx = 'True'
        else:
            self.strConvertPdfToDocx = 'False'
        self._update_basic_option_enabled()

    def on_checkbox_toggled2(self):
        if self.check_box2.isChecked():
            self.strConvertDocxToPdf = 'True' 
        else:
            self.strConvertDocxToPdf = 'False'

    def on_checkbox_toggled3(self):
        if self.check_box3.isChecked():
            self.strIgnoreExistingOuput = 'True'  
        else:
            self.strIgnoreExistingOuput ='False'

    def on_checkbox_toggled4(self):
        if self.check_box4.isChecked():
            self.strForceBasicConvertion = 'True'  
        else:
            self.strForceBasicConvertion ='False'

    def _update_basic_option_enabled(self):
        self.check_box4.setEnabled(self.check_box.isChecked())

    def __init__(self):
        super().__init__()
        
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)


        self.check_box = self.findChild(QCheckBox, 'checkBox')
        self.check_box2 = self.findChild(QCheckBox, 'checkBox_2')
        self.check_box3 = self.findChild(QCheckBox, 'checkBox_3')
        self.check_box4 = self.findChild(QCheckBox, 'checkBox_4')


        self.check_box.setChecked(self.strConvertPdfToDocx == 'True')
        self.check_box2.setChecked(self.strConvertDocxToPdf == 'True')
        self.check_box3.setChecked(self.strIgnoreExistingOuput == 'True')
        self.check_box4.setChecked(self.strForceBasicConvertion == 'True')


        self.check_box.stateChanged.connect(self.on_checkbox_toggled)
        self.check_box2.stateChanged.connect(self.on_checkbox_toggled2)
        self.check_box3.stateChanged.connect(self.on_checkbox_toggled3)
        self.check_box4.stateChanged.connect(self.on_checkbox_toggled4)

        self._update_basic_option_enabled()

        # Data Management
        self.data = None
        self.thread = None
        self.autorun = True
        self.result = None
        self.post_initialized()

    def run(self):
        self.error("")
        convert_pdf = (self.strConvertPdfToDocx == 'True')
        convert_docx = (self.strConvertDocxToPdf == 'True')

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
        ignore_existing_docx=False
        if self.strIgnoreExistingOuput=="True":
            ignore_existing_docx=True
        forceBasicConvertion=True
        if self.strForceBasicConvertion=='False':
            forceBasicConvertion=False

        # Définition du traitement complet directement dans le corps de run
        def worker_process():
            errors = []
            pdf_tasks = []
            docx_tasks = []

            # 1. Scan global initial pour compter tous les fichiers
            for in_dir, out_dir in zip(input_dir, output_dir):
                if not in_dir or not out_dir:
                    continue
                in_dir, out_dir = str(in_dir), str(out_dir)
                if not os.path.exists(in_dir):
                    continue

                for root, _, files in os.walk(in_dir):
                    for name in files:
                        src = Path(root) / name
                        rel = os.path.relpath(root, in_dir)
                        dst_dir = Path(out_dir) if rel == "." else Path(out_dir) / rel
                        
                        if convert_pdf and name.lower().endswith(".pdf"):
                            dst = dst_dir / f"{src.stem}.docx"
                            if not (ignore_existing_docx and dst.exists()):
                                pdf_tasks.append((src, dst))
                        elif convert_docx and name.lower().endswith((".docx", ".doc")):
                            dst = dst_dir / f"{src.stem}.pdf"
                            if not (ignore_existing_docx and dst.exists()):
                                docx_tasks.append((src, dst))

            total_files = len(pdf_tasks) + len(docx_tasks)
            if total_files == 0:
                return "Success"

            processed_count = 0

            # 2. Exécution séquentielle : PDF -> DOCX
            for src, dst in pdf_tasks:
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    word_converter.convert_pdf_structure(
                        [str(src.parent)], 
                        [str(dst.parent)], 
                        ignore_exsting_out_put=ignore_existing_docx, 
                        forceBasicConvertion=forceBasicConvertion
                    )
                except Exception as e:
                    errors.append(f"Erreur PDF->DOCX ({src.name}): {e}")
                
                processed_count += 1
                try:
                    self.thread.progress.emit((processed_count / total_files) * 100)
                except Exception:
                    pass

            # 3. Exécution séquentielle : DOCX -> PDF
            if docx_tasks:
                convert_to_pdf = _import_convert_to_pdf()
                for src, dst in docx_tasks:
                    try:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        convert_to_pdf(Path(src), Path(dst))
                    except Exception as e:
                        errors.append(f"Erreur DOCX->PDF ({src.name}): {e}")
                    
                    processed_count += 1
                    try:
                        self.thread.progress.emit((processed_count / total_files) * 100)
                    except Exception:
                        pass

            if errors:
                return "\n".join(errors)
            return "Success"

        # Connexion et démarrage du thread avec la fonction interne unifiée
        self.thread = thread_management.Thread(worker_process)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.result = result
            if result == "Success":
                self.error("")
            else:
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