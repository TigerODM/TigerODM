import os
import sys
from pathlib import Path
import Orange
import cv2 as cv
import numpy as np
from Orange.widgets.widget import OWWidget, Input, Output
from Orange.widgets import settings
from AnyQt.QtWidgets import QApplication
from Orange.data import Table, Domain, StringVariable
import tifffile as tiff
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.AAIT.utils.import_uic import uic


class OWPatternMatching(OWWidget):
    name = "Pattern Matcher"
    description = "Detects objects using template matching"
    icon = "icons/ow_pattern_matching.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/ow_pattern_matching.png"

    priority = 25

    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_pattern_matching.ui")
    threshold_val = settings.Setting(0.8)
    overlap_val = settings.Setting(0.3)
    generate_preview = settings.Setting("False")
    str_autosend = settings.Setting("True")

    class Inputs:
        data_images = Input("Images to Process", Orange.data.Table)
        reference_images = Input("Reference Images", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)
        preview = Output("Preview Image", Orange.data.Table)
        no_match = Output("Images without match", Orange.data.Table)
        center = Output("Center", Orange.data.Table)

    def __init__(self):
        super().__init__()
        self.input_data = None
        self.input_reference = None
        self.setFixedWidth(478)
        self.setFixedHeight(460)

        uic.loadUi(self.gui, self)

        # Setup Threshold
        self.spinThreshold.setValue(self.threshold_val)
        self.spinThreshold.valueChanged.connect(self.update_threshold)

        # Setup Overlap (NMS)
        self.spinOverlap.setValue(self.overlap_val)
        self.spinOverlap.valueChanged.connect(self.update_overlap)

        if self.generate_preview == "False":
            self.checkBox_preview.setChecked(False)
        else:
            self.checkBox_preview.setChecked(True)
        self.checkBox_preview.stateChanged.connect(self.toogle_preview)

        # Setup Auto-send et Bouton Run
        if self.str_autosend == "True":
            self.checkBox_autosend.setChecked(True)
        else:
            self.checkBox_autosend.setChecked(False)
        self.checkBox_autosend.stateChanged.connect(self.toggle_autosend)
        self.btnRun.clicked.connect(self.run_multi_matching)

    def toggle_autosend(self):
        if self.checkBox_autosend.isChecked():
            self.str_autosend = "True"
        else:
            self.str_autosend = "False"

    def toogle_preview(self, enabled):
        if self.checkBox_preview.isChecked():
            self.generate_preview = "True"
        else:
            self.generate_preview = "False"
        self.check_and_run()

    def update_threshold(self, val):
        self.threshold_val = val
        self.check_and_run()

    @Inputs.data_images
    def set_data_images(self, data):
        self.input_data = data
        self.check_and_run()

    @Inputs.reference_images
    def set_reference_images(self, data):
        self.input_reference = data
        self.check_and_run()

    def check_and_run(self):
        if self.input_data and self.input_reference:
            if self.str_autosend == "True":
                self.run_multi_matching()

    def _get_path(self, table, row_index=0):
        if not table or len(table) <= row_index:
            return None
        domain = table.domain
        row = table[row_index]
        if "path" in domain:
            return str(row["path"])
        elif "image" in domain:
            origin = domain["image"].attributes.get('origin', '')
            return os.path.join(origin, str(row["image"]))
        return None

    def non_max_suppression(self, boxes, overlapThresh=0.3):
        """
        Même NMS qu'avant (critère overlap > overlapThresh),
        MAIS au lieu de garder la bbox 'i' brute, on renvoie une bbox fusionnée:
        - centre = moyenne des centres (bbox i + celles supprimées avec elle)
        - taille = celle de la bbox i (donc "taille d'origine" typique du template)
        Entrée/sortie inchangées.
        """
        if len(boxes) == 0:
            return []

        boxes = np.asarray(boxes, dtype=np.float32)

        pick = []
        out_boxes = []

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]

        area = (x2 - x1 + 1.0) * (y2 - y1 + 1.0)
        idxs = np.argsort(y2)

        while len(idxs) > 0:
            last = len(idxs) - 1
            i = idxs[last]

            xx1 = np.maximum(x1[i], x1[idxs[:last]])
            yy1 = np.maximum(y1[i], y1[idxs[:last]])
            xx2 = np.minimum(x2[i], x2[idxs[:last]])
            yy2 = np.minimum(y2[i], y2[idxs[:last]])

            w = np.maximum(0.0, xx2 - xx1 + 1.0)
            h = np.maximum(0.0, yy2 - yy1 + 1.0)

            overlap = (w * h) / area[idxs[:last]]

            suppress_rel = np.where(overlap > overlapThresh)[0]

            group_idxs = [int(i)]
            if suppress_rel.size:
                group_idxs.extend(idxs[suppress_rel].astype(int).tolist())

            gcx = np.mean((x1[group_idxs] + x2[group_idxs]) * 0.5)
            gcy = np.mean((y1[group_idxs] + y2[group_idxs]) * 0.5)

            wi = (x2[i] - x1[i])
            hi = (y2[i] - y1[i])

            nx1 = gcx - wi * 0.5
            ny1 = gcy - hi * 0.5
            nx2 = nx1 + wi
            ny2 = ny1 + hi

            out_boxes.append([nx1, ny1, nx2, ny2])
            pick.append(i)

            suppress = np.concatenate(([last], suppress_rel))
            idxs = np.delete(idxs, suppress)

        return np.round(np.asarray(out_boxes)).astype("int")

    def run_multi_matching(self):
        self.error("")
        if self.input_data is None or self.input_reference is None:
            self.Outputs.data.send(None)
            self.Outputs.preview.send(None)
            self.Outputs.no_match.send(None)
            self.Outputs.center.send(None)
            return

        existing_columns = [var.name for var in self.input_data.domain.variables + self.input_data.domain.metas]

        if "transform" in existing_columns or "name_out" in existing_columns:
            self.error("Colonne existante")
            self.Outputs.data.send(None)
            self.Outputs.preview.send(None)
            self.Outputs.no_match.send(None)
            self.Outputs.center.send(None)
            return

        all_rows = []
        preview_list = []
        no_match_rows = []
        center_rows = []

        # 1. Création du dossier de destination pour les previews
        base_path_raw = self._get_path(self.input_data, 0)
        base_dir = Path(base_path_raw).parent if base_path_raw else Path.cwd()

        preview_dir = base_dir / "previews"
        if self.generate_preview != "False":
            preview_dir.mkdir(parents=True, exist_ok=True)

        # Loop through each image to process
        for i_img in range(len(self.input_data)):
            p_scene = self._get_path(self.input_data, i_img)
            if not p_scene:
                continue

            try:
                file_bytes = np.fromfile(p_scene, dtype=np.uint8)
                img_color = cv.imdecode(file_bytes, cv.IMREAD_COLOR)
            except Exception as e:
                print(f"Erreur de lecture : {p_scene} -> {e}")
                continue

            if img_color is None:
                continue

            img_gray = cv.cvtColor(img_color, cv.COLOR_BGR2GRAY)
            base_path = Path(p_scene)

            found_any_match_for_this_image = False
            centers_col = []
            centers_line = []

            # Loop through each reference pattern
            for i_ref in range(len(self.input_reference)):
                p_ref = self._get_path(self.input_reference, i_ref)

                try:
                    ref_bytes = np.fromfile(p_ref, dtype=np.uint8)
                    template = cv.imdecode(ref_bytes, cv.IMREAD_GRAYSCALE)
                except Exception:
                    continue

                if template is None:
                    continue

                h_ref, w_ref = template.shape
                res = cv.matchTemplate(img_gray, template, cv.TM_CCOEFF_NORMED)
                loc = np.where(res >= self.threshold_val)

                raw_boxes = [[pt[0], pt[1], pt[0] + w_ref, pt[1] + h_ref] for pt in zip(*loc[::-1])]

                final_boxes = self.non_max_suppression(raw_boxes, overlapThresh=self.overlap_val)

                if len(final_boxes) > 0:
                    found_any_match_for_this_image = True
                    tolerance = 50
                    final_boxes = sorted(final_boxes, key=lambda b: (b[1] // tolerance, b[0]))

                for i, (x1, y1, x2, y2) in enumerate(final_boxes):
                    cv.rectangle(img_color, (x1, y1), (x2, y2), (255, 0, 255), 2)

                    cx = int(round((x1 + x2) / 2.0))
                    cy = int(round((y1 + y2) / 2.0))
                    centers_col.append(str(cx))
                    centers_line.append(str(cy))

                    transform_cmd = f"Crop | line = {y1} | col = {x1} | delta_line = {h_ref} | delta_col = {w_ref}"
                    output_filename = f"{base_path.stem}_ref{i_ref}_{i}{base_path.suffix}"

                    all_rows.append(list(self.input_data[i_img].list) + [transform_cmd, output_filename])

            if found_any_match_for_this_image:
                center_rows.append([str(p_scene), " ".join(centers_col), " ".join(centers_line)])
            else:
                no_match_rows.append(list(self.input_data[i_img].list))

            # Sauvegarde de la preview
            if self.generate_preview != "False":
                preview_filename = f"preview_{base_path.name}"
                preview_path = str(preview_dir / preview_filename)

                rgb = cv.cvtColor(img_color, cv.COLOR_BGR2RGB)

                try:
                    tiff.imwrite(preview_path, rgb, compression=None)
                    preview_list.append([preview_path])
                except Exception as e:
                    print(f"Erreur écriture preview : {e}")
            else:
                pass

        # Envoi des données aux sorties Orange
        if not all_rows:
            self.Outputs.data.send(None)
            self.Outputs.preview.send(None)

            if no_match_rows:
                self.Outputs.no_match.send(Table.from_list(self.input_data.domain, no_match_rows))
            else:
                self.Outputs.no_match.send(None)

            if center_rows:
                center_domain = Domain([], metas=[
                    StringVariable("path"),
                    StringVariable("col_centre"),
                    StringVariable("line_centre")
                ])
                self.Outputs.center.send(Table.from_list(center_domain, center_rows))
            else:
                self.Outputs.center.send(None)
            return

        # Préparation du Domaine Orange avec "name_out"
        new_metas = list(self.input_data.domain.metas) + [
            StringVariable("transform"),
            StringVariable("name_out")
        ]
        new_domain = Domain(self.input_data.domain.attributes, self.input_data.domain.class_vars, metas=new_metas)

        self.Outputs.data.send(Table.from_list(new_domain, all_rows))

        if no_match_rows:
            self.Outputs.no_match.send(Table.from_list(self.input_data.domain, no_match_rows))
        else:
            self.Outputs.no_match.send(None)

        if self.generate_preview != "False" and preview_list:
            self.Outputs.preview.send(Table.from_list(Domain([], metas=[StringVariable("path")]), preview_list))
        else:
            self.Outputs.preview.send(None)

        if center_rows:
            center_domain = Domain([], metas=[
                StringVariable("path"),
                StringVariable("col_centre"),
                StringVariable("line_centre")
            ])
            self.Outputs.center.send(Table.from_list(center_domain, center_rows))
        else:
            self.Outputs.center.send(None)

    def update_overlap(self, val):
        self.overlap_val = val
        self.check_and_run()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = OWPatternMatching()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()