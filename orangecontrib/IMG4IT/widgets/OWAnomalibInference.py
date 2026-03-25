import os
import sys
import numpy as np
import cv2
from pathlib import Path


from Orange.data import StringVariable, ContinuousVariable, Domain, Table
from AnyQt.QtWidgets import QApplication, QPushButton, QCheckBox
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
import Orange

from anomalib.deploy import TorchInferencer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, base_widget
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import thread_management, base_widget
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


def run_inference(images_table, image_col_name, model_table, progress_callback=None):
    os.environ["TRUST_REMOTE_CODE"] = "1"
    try:
        path_out_var = None
        for var in images_table.domain.variables + images_table.domain.metas:
            if var.name == "path_out":
                path_out_var = var
                break

        if path_out_var is None:
            return None, "Erreur : La colonne 'path_out' est introuvable dans la table d'images en entrée."

        model_path = str(model_table[0]["path"].value)

        if not os.path.exists(model_path):
            return None, f"Modèle introuvable au chemin : {model_path}"

        try:
            inferencer = TorchInferencer(path=model_path)
        except Exception as e:
            return None, f"Erreur de chargement du modèle : {str(e)}"

        score_var = ContinuousVariable("Score_Anomalie")
        verdict_var = StringVariable("Verdict")
        heatmap_var = StringVariable("Heatmap_Path")

        new_metas = images_table.domain.metas + (score_var, verdict_var, heatmap_var)
        new_domain = Domain(images_table.domain.attributes, images_table.domain.class_vars, new_metas)

        new_data = []
        total_images = len(images_table)

        for i, row in enumerate(images_table):
            img_path = str(row[image_col_name].value)
            filename = os.path.basename(img_path)

            raw_path_out = row[path_out_var].value
            if not raw_path_out or str(raw_path_out).lower() == "nan":
                current_output_dir = "./heatmaps_output"
            else:
                current_output_dir = str(raw_path_out)

            output_dir_path = Path(current_output_dir)
            output_dir_path.mkdir(parents=True, exist_ok=True)

            abs_img_path = os.path.abspath(img_path)

            if os.path.exists(abs_img_path):
                test_img = cv2.imread(abs_img_path, cv2.IMREAD_UNCHANGED)
                if test_img is None:
                    score = np.nan
                    verdict = "ERREUR_LECTURE_OPENCV"
                    heatmap_path_str = ""
                else:
                    try:
                        predictions = inferencer.predict(image=abs_img_path)
                        score = float(predictions.pred_score.item())
                        verdict = "ANOMALIE" if predictions.pred_label else "OK"

                        anomaly_map = predictions.anomaly_map.squeeze().cpu().numpy()
                        anomaly_map_norm = cv2.normalize(anomaly_map, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                        heatmap_color = cv2.applyColorMap(anomaly_map_norm, cv2.COLORMAP_JET)

                        if len(test_img.shape) == 2:
                            original_img = cv2.cvtColor(test_img, cv2.COLOR_GRAY2BGR)
                        else:
                            original_img = test_img

                        original_img = cv2.resize(original_img, (heatmap_color.shape[1], heatmap_color.shape[0]))

                        if original_img.dtype != np.uint8:
                            original_img = cv2.normalize(original_img, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

                        superimposed_img = cv2.addWeighted(original_img, 0.5, heatmap_color, 0.5, 0)

                        heatmap_path = output_dir_path.resolve() / f"heatmap_{filename}"
                        heatmap_path_str = str(heatmap_path)

                        success, encoded_image = cv2.imencode('.jpg', superimposed_img)
                        if success:
                            encoded_image.tofile(heatmap_path_str)
                        else:
                            pass

                    except Exception as img_err:
                        score = np.nan
                        verdict = "ERREUR_INFERENCE"
                        heatmap_path_str = ""
            else:
                score = np.nan
                verdict = "ERREUR_IMAGE"
                heatmap_path_str = ""

            row_vars = [row[var] for var in images_table.domain.variables]
            row_metas = [row[var] for var in images_table.domain.metas]

            new_row = row_vars + row_metas + [score, verdict, heatmap_path_str]
            new_data.append(new_row)

            if progress_callback:
                progress_callback((i + 1) / total_images * 100)

        out_table = Table.from_list(new_domain, new_data)
        return out_table, None

    except Exception as e:
        return None, str(e)


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWAnomalibInference(base_widget.BaseListWidget):
    name = "Anomalib Inference"
    description = "Run Anomalib inference on a list of images using a trained model."
    category = "Computer Vision"
    icon = "icons/anomaly_detection.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/anomaly_detection.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_anomalib_inference.ui")
    want_control_area = False
    priority = 1070

    auto_send = Setting(False)
    selected_path_column = Setting("path")

    class Inputs:
        images_data = Input("Images Data", Orange.data.Table)
        model_data = Input("Model Data", Orange.data.Table)

    class Outputs:
        result_data = Output("Result Data", Orange.data.Table)

    @Inputs.images_data
    def set_images_data(self, data):
        self.images_data = data
        if self.images_data:
            self.var_selector.add_variables(self.images_data.domain)
            self.var_selector.select_variable_by_name(self.selected_path_column)

        self.check_ready()

        if self.auto_send and self.images_data is not None and self.model_data is not None:
            self.run()

    @Inputs.model_data
    def set_model_data(self, data):
        self.model_data = data
        self.check_ready()

        if self.auto_send and self.images_data is not None and self.model_data is not None:
            self.run()

    def __init__(self):
        super().__init__()
        self.images_data = None
        self.model_data = None
        self.thread = None
        self.result = None

        self.pushButton_send = self.findChild(QPushButton, 'pushButton_send')
        self.checkBox_send = self.findChild(QCheckBox, 'checkBox_send')

        if self.checkBox_send:
            self.checkBox_send.setChecked(self.auto_send)
            self.checkBox_send.toggled.connect(self._on_autorun_toggled)

        if self.pushButton_send is not None:
            self.pushButton_send.clicked.connect(self.run)

        self.post_initialized()

    def _on_autorun_toggled(self, checked: bool):
        self.auto_send = checked
        if self.auto_send and self.images_data is not None and self.model_data is not None:
            self.run()

    def check_ready(self):
        if self.pushButton_send is not None:
            if self.images_data is not None and self.model_data is not None:
                self.pushButton_send.setEnabled(True)
            else:
                self.pushButton_send.setEnabled(False)

    def run(self):
        self.error("")
        self.warning("")

        if self.thread is not None:
            if hasattr(self.thread, 'safe_quit'):
                self.thread.safe_quit()

        if self.images_data is None or self.model_data is None:
            self.Outputs.result_data.send(None)
            return

        col_name = self.selected_path_column
        try:
            attr = self.images_data.domain[col_name]
        except (KeyError, ValueError):
            self.error(f"Colonne d'image '{col_name}' introuvable.")
            return

        try:
            attr_model = self.model_data.domain["path"]
        except (KeyError, ValueError):
            self.error("Colonne 'path' introuvable dans la table du modèle.")
            return

        self.progressBarInit()
        if self.pushButton_send is not None:
            self.pushButton_send.setEnabled(False)

        self.thread = thread_management.Thread(
            run_inference,
            self.images_data,
            col_name,
            self.model_data
        )
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result_tuple):
        try:
            result_table, err_msg = result_tuple

            if err_msg:
                self.error(err_msg)
                self.Outputs.result_data.send(None)
            else:
                self.result = result_table
                self.Outputs.result_data.send(result_table)
        except Exception as e:
            self.Outputs.result_data.send(None)
            return

    def handle_finish(self):
        self.progressBarFinished()
        if self.pushButton_send is not None:
            self.pushButton_send.setEnabled(True)

    def post_initialized(self):
        pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWAnomalibInference()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
