import os
import shutil
import sys
import tempfile
from pathlib import Path

import Orange.data
from AnyQt.QtWidgets import QApplication, QCheckBox, QLabel

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


def convert_single_pdf_to_docx(src: Path, dst: Path, force_basic_convertion: bool) -> None:
    """Convertit UN pdf vers UN docx dont le nom/chemin est imposé.

    `word_converter.convert_pdf_structure` ne sait travailler que sur des
    répertoires : on passe donc par un répertoire temporaire, puis on déplace
    le fichier produit vers `dst`.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_in = Path(tmp) / "in"
        tmp_out = Path(tmp) / "out"
        tmp_in.mkdir()
        tmp_out.mkdir()
        shutil.copy2(str(src), str(tmp_in / src.name))
        word_converter.convert_pdf_structure(
            [str(tmp_in)],
            [str(tmp_out)],
            ignore_exsting_out_put=False,
            forceBasicConvertion=force_basic_convertion,
        )
        produced = sorted(tmp_out.rglob("*.docx"))
        if not produced:
            raise RuntimeError("aucun docx produit par la conversion")
        os.replace(str(produced[0]), str(dst))


class OWwordpdf2docx(widget.OWWidget):
    name = "WordPdf2Docx"
    description = "Convert PDF to DOCX and/or DOCX to PDF"
    icon = "icons/wordpdf2docx.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/wordpdf2docx.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/wordpdf2docx.ui")
    want_control_area = False
    priority = 3000
    category = "AAIT - TOOLBOX"
    strDirectoryMode: str = Setting('True')
    strFileMode: str = Setting('False')
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

    # ------------------------------------------------------------------ modes
    def on_mode_dir_toggled(self):
        if self._mode_updating:
            return
        self._mode_updating = True
        try:
            if not self.check_box_mode_dir.isChecked() and not self.check_box_mode_file.isChecked():
                self.check_box_mode_dir.setChecked(True)
            self.check_box_mode_file.setChecked(not self.check_box_mode_dir.isChecked())
        finally:
            self._mode_updating = False
        self._store_mode()

    def on_mode_file_toggled(self):
        if self._mode_updating:
            return
        self._mode_updating = True
        try:
            if not self.check_box_mode_dir.isChecked() and not self.check_box_mode_file.isChecked():
                self.check_box_mode_file.setChecked(True)
            self.check_box_mode_dir.setChecked(not self.check_box_mode_file.isChecked())
        finally:
            self._mode_updating = False
        self._store_mode()

    def _store_mode(self):
        self.strDirectoryMode = 'True' if self.check_box_mode_dir.isChecked() else 'False'
        self.strFileMode = 'True' if self.check_box_mode_file.isChecked() else 'False'
        self._update_options_enabled()

    # ------------------------------------------------------------- checkboxes
    def on_checkbox_toggled(self):
        if self.check_box.isChecked():
            self.strConvertPdfToDocx = 'True'
        else:
            self.strConvertPdfToDocx = 'False'
        self._update_options_enabled()

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

    def _update_options_enabled(self):
        file_mode = self.check_box_mode_file.isChecked()
        # en mode fichier, le sens de conversion est déduit du couple path / path_out
        self.check_box.setEnabled(not file_mode)
        self.check_box2.setEnabled(not file_mode)
        self.check_box4.setEnabled(file_mode or self.check_box.isChecked())
        if self.label_description is not None:
            if file_mode:
                self.label_description.setText(
                    "Convert each file from the \"path\" column to the \"path_out\" column "
                    "(.pdf -> .docx or .docx -> .pdf)")
            else:
                self.label_description.setText(
                    "Convert PDF <-> DOCX for every file, from input_dir to output_dir")

    def __init__(self):
        super().__init__()
        
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(380)
        uic.loadUi(self.gui, self)

        self._mode_updating = True

        self.check_box_mode_dir = self.findChild(QCheckBox, 'checkBox_mode_dir')
        self.check_box_mode_file = self.findChild(QCheckBox, 'checkBox_mode_file')
        self.check_box = self.findChild(QCheckBox, 'checkBox')
        self.check_box2 = self.findChild(QCheckBox, 'checkBox_2')
        self.check_box3 = self.findChild(QCheckBox, 'checkBox_3')
        self.check_box4 = self.findChild(QCheckBox, 'checkBox_4')
        self.label_description = self.findChild(QLabel, 'Description')

        # sécurité : si les deux settings sont incohérents, on retombe sur le
        # mode historique (dossier)
        file_mode = (self.strFileMode == 'True' and self.strDirectoryMode != 'True')
        self.check_box_mode_dir.setChecked(not file_mode)
        self.check_box_mode_file.setChecked(file_mode)

        self.check_box.setChecked(self.strConvertPdfToDocx == 'True')
        self.check_box2.setChecked(self.strConvertDocxToPdf == 'True')
        self.check_box3.setChecked(self.strIgnoreExistingOuput == 'True')
        self.check_box4.setChecked(self.strForceBasicConvertion == 'True')

        self.check_box_mode_dir.stateChanged.connect(self.on_mode_dir_toggled)
        self.check_box_mode_file.stateChanged.connect(self.on_mode_file_toggled)
        self.check_box.stateChanged.connect(self.on_checkbox_toggled)
        self.check_box2.stateChanged.connect(self.on_checkbox_toggled2)
        self.check_box3.stateChanged.connect(self.on_checkbox_toggled3)
        self.check_box4.stateChanged.connect(self.on_checkbox_toggled4)

        self._mode_updating = False
        self._store_mode()

        # Data Management
        self.data = None
        self.thread = None
        self.autorun = True
        self.result = None
        self.post_initialized()

    # -------------------------------------------------------------- utilities
    def _check_string_column(self, column_name):
        """Retourne True si la colonne existe et est de type Text."""
        try:
            self.data.domain[column_name]
        except KeyError:
            self.error('You need a "%s" column in input data' % column_name)
            return False
        if type(self.data.domain[column_name]).__name__ != 'StringVariable':
            self.error('"%s" column needs to be a Text' % column_name)
            return False
        return True

    # -------------------------------------------------------------------- run
    def run(self):
        self.error("")

        # if thread is running quit
        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            return

        ignore_existing_docx = (self.strIgnoreExistingOuput == 'True')
        force_basic_convertion = (self.strForceBasicConvertion == 'True')

        if self.strFileMode == 'True':
            worker_process = self._build_file_worker(ignore_existing_docx, force_basic_convertion)
        else:
            worker_process = self._build_directory_worker(ignore_existing_docx, force_basic_convertion)

        if worker_process is None:
            return

        # Start progress bar
        self.progressBarInit()

        # Connexion et démarrage du thread avec la fonction interne unifiée
        self.thread = thread_management.Thread(worker_process)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    # --------------------------------------------------------- mode répertoire
    def _build_directory_worker(self, ignore_existing_docx, force_basic_convertion):
        convert_pdf = (self.strConvertPdfToDocx == 'True')
        convert_docx = (self.strConvertDocxToPdf == 'True')

        # Verification of in_data
        if not self._check_string_column("input_dir"):
            return None
        if not self._check_string_column("output_dir"):
            return None

        input_dir = self.data.get_column("input_dir")
        output_dir = self.data.get_column("output_dir")

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
                        forceBasicConvertion=force_basic_convertion
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

        return worker_process

    # ------------------------------------------------------------ mode fichier
    def _build_file_worker(self, ignore_existing_docx, force_basic_convertion):
        # Verification of in_data
        if not self._check_string_column("path"):
            return None
        if not self._check_string_column("path_out"):
            return None

        path_in = self.data.get_column("path")
        path_out = self.data.get_column("path_out")

        def worker_process():
            errors = []
            tasks = []

            # 1. Construction et validation des couples path / path_out
            for index, (p_in, p_out) in enumerate(zip(path_in, path_out), start=1):
                if not p_in or not p_out:
                    continue
                src = Path(str(p_in))
                dst = Path(str(p_out))
                src_ext = src.suffix.lower()
                dst_ext = dst.suffix.lower()

                if src_ext == ".pdf" and dst_ext == ".docx":
                    direction = "pdf2docx"
                elif src_ext in (".docx", ".doc") and dst_ext == ".pdf":
                    direction = "docx2pdf"
                else:
                    errors.append(
                        f"Ligne {index} : couple invalide ({src.name} -> {dst.name}), "
                        f"attendu .pdf -> .docx ou .docx -> .pdf")
                    continue

                if not src.exists():
                    errors.append(f"Ligne {index} : fichier introuvable ({src})")
                    continue

                if ignore_existing_docx and dst.exists():
                    continue

                tasks.append((direction, src, dst))

            total_files = len(tasks)
            if total_files == 0:
                if errors:
                    return "\n".join(errors)
                return "Success"

            convert_to_pdf = None
            if any(direction == "docx2pdf" for direction, _, _ in tasks):
                convert_to_pdf = _import_convert_to_pdf()

            processed_count = 0

            # 2. Exécution séquentielle, fichier par fichier
            for direction, src, dst in tasks:
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if direction == "pdf2docx":
                        convert_single_pdf_to_docx(src, dst, force_basic_convertion)
                    else:
                        convert_to_pdf(Path(src), Path(dst))
                except Exception as e:
                    if direction == "pdf2docx":
                        errors.append(f"Erreur PDF->DOCX ({src.name}): {e}")
                    else:
                        errors.append(f"Erreur DOCX->PDF ({src.name}): {e}")

                processed_count += 1
                try:
                    self.thread.progress.emit((processed_count / total_files) * 100)
                except Exception:
                    pass

            if errors:
                return "\n".join(errors)
            return "Success"

        return worker_process

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
