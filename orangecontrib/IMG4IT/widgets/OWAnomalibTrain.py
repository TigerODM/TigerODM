import os
import sys
import numpy as np
import cv2
import torch
import pandas as pd
from pathlib import Path

from Orange.data import StringVariable, Domain, Table
from AnyQt.QtWidgets import QApplication, QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
import Orange

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, base_widget
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import thread_management, base_widget
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file

_IMG_SIZE        = 256
_TRAIN_BATCH     = 16
_EVAL_BATCH      = 1
_NORMAL_DIR      = "train/good"
_NORMAL_TEST_DIR = "test/good"
_ABNORMAL_DIR    = "test/defauts"
_BACKBONE        = "resnet18"
_LAYERS          = ["layer1", "layer2"]
_PRE_TRAINED     = True
_MAX_EPOCHS      = 1
_ACCELERATOR     = "auto"


def _get_top_k_mean(roi_matrix, k=100):
    flat = roi_matrix.flatten()
    if len(flat) < k:
        k = len(flat)
    return float(np.mean(np.partition(flat, -k)[-k:]))


def _coords_from_pct(pct_tuple, size):
    ys, ye, xs, xe = pct_tuple
    return (int(ys * size / 100), int(ye * size / 100),
            int(xs * size / 100), int(xe * size / 100))


def _apply_clahe_color(img_path):
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return cv2.cvtColor(clahe.apply(img), cv2.COLOR_GRAY2BGR)


def run_training(input_data, col_name, params, progress_callback=None):
    os.environ["TRUST_REMOTE_CODE"] = "1"
    try:
        from anomalib.data import Folder
        from anomalib.engine import Engine
        from anomalib.models import Patchcore
        from anomalib.deploy import ExportType

        dataset_root = str(input_data[0][col_name].value)
        if not os.path.isdir(dataset_root):
            return None, f"Dossier dataset introuvable : {dataset_root}"

        zone_pct       = params["zone_pct"]
        zone_threshold = params["zone_threshold"]
        top_k_pixels   = params["top_k_pixels"]
        apply_clahe    = params["apply_clahe"]

        run_path = Path(dataset_root) / "output"
        run_path.mkdir(parents=True, exist_ok=True)
        visuels_dir = run_path / "images_indexees"
        visuels_dir.mkdir(exist_ok=True)

        if progress_callback:
            progress_callback(5)

        datamodule = Folder(
            name="dataset",
            root=dataset_root,
            normal_dir=_NORMAL_DIR,
            normal_test_dir=_NORMAL_TEST_DIR,
            abnormal_dir=_ABNORMAL_DIR,
            train_batch_size=_TRAIN_BATCH,
            eval_batch_size=_EVAL_BATCH,
            num_workers=0,
            image_size=(_IMG_SIZE, _IMG_SIZE),
        )

        model = Patchcore(backbone=_BACKBONE, pre_trained=_PRE_TRAINED, layers=_LAYERS)
        engine = Engine(max_epochs=_MAX_EPOCHS, default_root_dir=str(run_path),
                        accelerator=_ACCELERATOR, devices=1)

        if progress_callback:
            progress_callback(10)

        engine.fit(datamodule=datamodule, model=model)

        if progress_callback:
            progress_callback(60)

        predictions = engine.predict(datamodule=datamodule, model=model)

        if progress_callback:
            progress_callback(75)

        data_summary = []
        idx = 1

        if predictions:
            for batch in predictions:
                for i in range(len(batch["image_path"])):
                    img_path    = batch["image_path"][i]
                    filename    = os.path.basename(img_path)
                    anomaly_map = batch["anomaly_map"][i].squeeze().cpu().numpy()

                    score_glob = round(float(batch["pred_score"][i]), 4)
                    y_s, y_e, x_s, x_e = _coords_from_pct(zone_pct, _IMG_SIZE)
                    score_zone = round(_get_top_k_mean(anomaly_map[y_s:y_e, x_s:x_e], top_k_pixels), 4)

                    reel       = "DEFAUT" if "defauts" in str(img_path).lower() else "OK"
                    pred_zone  = "DEFAUT" if score_zone >= zone_threshold else "OK"
                    validation = "BON" if pred_zone == reel else "ERREUR"

                    orig = (_apply_clahe_color(img_path) if apply_clahe else None) or cv2.imread(img_path)
                    img_name = ""
                    if orig is not None:
                        orig      = cv2.resize(orig, (_IMG_SIZE, _IMG_SIZE))
                        amap_norm = cv2.normalize(anomaly_map, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                        hmap      = cv2.applyColorMap(amap_norm, cv2.COLORMAP_JET)
                        overlay   = cv2.addWeighted(orig, 0.7, hmap, 0.3, 0)
                        cv2.rectangle(overlay, (x_s, y_s), (x_e, y_e), (255, 255, 255), 2)
                        cv2.rectangle(overlay, (2, 2), (70, 40), (0, 0, 0), -1)
                        cv2.putText(overlay, f"ID:{idx}", (10, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                        img_name = f"ID_{idx:03d}_{validation}_{filename}"
                        cv2.imwrite(str(visuels_dir / img_name), np.hstack((orig, overlay)))

                    data_summary.append({
                        "ID": idx, "Fichier": filename, "Reel": reel,
                        "Score_Zone": score_zone, "Seuil_Zone": zone_threshold,
                        "IA_Zone": pred_zone, "Verdict": validation,
                        "Score_Glob_IA": score_glob, "Image": img_name,
                    })
                    idx += 1

            pd.DataFrame(data_summary).to_excel(run_path / "Rapport_Final.xlsx", index=False)

        if progress_callback:
            progress_callback(90)

        export_dir = run_path / "model"
        engine.export(model=model, export_type=ExportType.TORCH, export_root=str(export_dir))
        model_pt_path = ""
        for f in export_dir.rglob("*.pt"):
            model_pt_path = str(f)
            break

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        if progress_callback:
            progress_callback(100)

        domain    = Domain([], metas=[StringVariable("path"), StringVariable("results_path")])
        out_table = Table.from_list(domain, [[model_pt_path or str(run_path), str(run_path)]])
        return out_table, None

    except Exception as e:
        import traceback
        return None, f"{str(e)}\n{traceback.format_exc()}"


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWAnomalibTrain(base_widget.BaseListWidget):
    name        = "Anomalib Training"
    description = "Entraîne un modèle PatchCore sur un dataset et génère un rapport d'analyse par zone."
    icon        = "icons/anomaly_detection.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/anomaly_detection.png"
    gui               = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_anomalib_train.ui")
    want_control_area = False
    priority          = 1060

    selected_path_column = Setting("path")
    auto_send            = Setting(False)
    zone_ys              = Setting(10.0)
    zone_ye              = Setting(20.0)
    zone_xs              = Setting(38.0)
    zone_xe              = Setting(50.0)
    zone_threshold       = Setting(0.22)
    top_k_pixels         = Setting(100)
    apply_clahe          = Setting(True)

    class Inputs:
        data = Input("Dataset Path", Orange.data.Table)

    class Outputs:
        model_data = Output("Model Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, data):
        self.data = data
        if self.data:
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_path_column)
        self.check_ready()
        if self.auto_send and self.data is not None:
            self.run()

    def __init__(self):
        super().__init__()
        self.data   = None
        self.thread = None

        # Zone spinboxes — connectées aux settings via lambda
        self.spin_ys = self.findChild(QDoubleSpinBox, 'doubleSpinBox_zone_ys')
        self.spin_ye = self.findChild(QDoubleSpinBox, 'doubleSpinBox_zone_ye')
        self.spin_xs = self.findChild(QDoubleSpinBox, 'doubleSpinBox_zone_xs')
        self.spin_xe = self.findChild(QDoubleSpinBox, 'doubleSpinBox_zone_xe')
        self.spin_th = self.findChild(QDoubleSpinBox, 'doubleSpinBox_zone_threshold')
        self.spin_tk = self.findChild(QSpinBox,       'spinBox_top_k')
        self.cb_clahe = self.findChild(QCheckBox,     'checkBox_clahe')

        self.pushButton_send = self.findChild(QPushButton, 'pushButton_send')
        self.checkBox_send   = self.findChild(QCheckBox,   'checkBox_send')

        # Restauration des settings dans l'UI
        if self.spin_ys: self.spin_ys.setValue(self.zone_ys)
        if self.spin_ye: self.spin_ye.setValue(self.zone_ye)
        if self.spin_xs: self.spin_xs.setValue(self.zone_xs)
        if self.spin_xe: self.spin_xe.setValue(self.zone_xe)
        if self.spin_th: self.spin_th.setValue(self.zone_threshold)
        if self.spin_tk: self.spin_tk.setValue(self.top_k_pixels)
        if self.cb_clahe: self.cb_clahe.setChecked(self.apply_clahe)

        # Connexions settings ↔ widgets
        if self.spin_ys: self.spin_ys.valueChanged.connect(lambda v: setattr(self, 'zone_ys', v))
        if self.spin_ye: self.spin_ye.valueChanged.connect(lambda v: setattr(self, 'zone_ye', v))
        if self.spin_xs: self.spin_xs.valueChanged.connect(lambda v: setattr(self, 'zone_xs', v))
        if self.spin_xe: self.spin_xe.valueChanged.connect(lambda v: setattr(self, 'zone_xe', v))
        if self.spin_th: self.spin_th.valueChanged.connect(lambda v: setattr(self, 'zone_threshold', v))
        if self.spin_tk: self.spin_tk.valueChanged.connect(lambda v: setattr(self, 'top_k_pixels', v))
        if self.cb_clahe: self.cb_clahe.toggled.connect(lambda v: setattr(self, 'apply_clahe', v))

        if self.checkBox_send:
            self.checkBox_send.setChecked(self.auto_send)
            self.checkBox_send.toggled.connect(lambda v: setattr(self, 'auto_send', v))
        if self.pushButton_send:
            self.pushButton_send.clicked.connect(self.run)

        self.post_initialized()

    def check_ready(self):
        if self.pushButton_send is not None:
            self.pushButton_send.setEnabled(self.data is not None)

    def run(self):
        self.error("")
        self.warning("")

        if self.thread is not None:
            self.thread.safe_quit()

        if self.data is None:
            self.Outputs.model_data.send(None)
            return

        col_name = self.selected_path_column
        try:
            self.data.domain[col_name]
        except (KeyError, ValueError):
            self.error(f"Colonne '{col_name}' introuvable dans la table d'entrée.")
            return

        params = {
            "zone_pct":       (self.zone_ys, self.zone_ye, self.zone_xs, self.zone_xe),
            "zone_threshold": self.zone_threshold,
            "top_k_pixels":   self.top_k_pixels,
            "apply_clahe":    self.apply_clahe,
        }

        self.progressBarInit()
        if self.pushButton_send:
            self.pushButton_send.setEnabled(False)

        self.thread = thread_management.Thread(run_training, self.data, col_name, params)
        self.thread.progress.connect(self.progressBarSet)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_result(self, result_tuple):
        out_table, err_msg = result_tuple
        if err_msg:
            self.error(err_msg)
            self.Outputs.model_data.send(None)
        else:
            self.Outputs.model_data.send(out_table)

    def handle_finish(self):
        self.progressBarFinished()
        if self.pushButton_send:
            self.pushButton_send.setEnabled(True)

    def post_initialized(self):
        self.check_ready()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = OWAnomalibTrain()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
