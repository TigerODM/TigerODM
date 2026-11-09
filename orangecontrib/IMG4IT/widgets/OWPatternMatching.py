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
    from Orange.widgets.orangecontrib.AAIT.utils.thread_management import Thread
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.thread_management import Thread


# ---------------------------------------------------------------------------
# Fonctions utilitaires (pures, sans Qt -> utilisables dans le thread)
# ---------------------------------------------------------------------------
def _load_template(path, use_alpha_mask=False):
    """
    Charge un template en niveaux de gris.
    Si l'image a un canal alpha (PNG transparent) et que use_alpha_mask est actif,
    renvoie aussi un masque binaire (255 = pixel pris en compte, 0 = ignoré).
    Retour : (gray, mask) ; mask vaut None si aucun pixel n'est transparent.
    """
    if not use_alpha_mask:
        # Comportement historique strict : lecture directe en niveaux de gris
        return cv.imdecode(np.fromfile(path, dtype=np.uint8), cv.IMREAD_GRAYSCALE), None

    raw = cv.imdecode(np.fromfile(path, dtype=np.uint8), cv.IMREAD_UNCHANGED)
    if raw is None:
        return None, None

    # PNG 16 bits -> 8 bits
    if raw.dtype == np.uint16:
        raw = (raw / 257).astype(np.uint8)
    elif raw.dtype != np.uint8:
        raw = cv.normalize(raw, None, 0, 255, cv.NORM_MINMAX).astype(np.uint8)

    mask = None
    if raw.ndim == 2:
        gray = raw
    elif raw.shape[2] == 4:
        gray = cv.cvtColor(raw, cv.COLOR_BGRA2GRAY)
        alpha = raw[:, :, 3]
        opaque = alpha > 127
        if not opaque.any():
            # Template entièrement transparent : inutilisable
            return None, None
        if not opaque.all():
            # La couleur "sous" la transparence est arbitraire (souvent noire) :
            # on la remplace par une couleur contrastée avec la partie opaque.
            fill = 255 if float(gray[opaque].mean()) < 128 else 0
            gray = gray.copy()
            gray[~opaque] = fill
            mask = np.where(opaque, 255, 0).astype(np.uint8)
            # Cas typique : trait noir sur fond transparent -> la zone opaque
            # est uniforme, la corrélation est indéfinie. On inclut alors une
            # fine marge de fond (contrasté) autour du trait.
            if float(gray[opaque].std()) < 1e-6:
                h, w = gray.shape
                margin = max(2, min(h, w) // 30)
                k = cv.getStructuringElement(cv.MORPH_RECT, (2 * margin + 1, 2 * margin + 1))
                mask = cv.dilate(mask, k)
            if mask.all():
                mask = None
    elif raw.shape[2] == 3:
        gray = cv.cvtColor(raw, cv.COLOR_BGR2GRAY)
    else:
        gray = raw[:, :, 0]

    return gray, mask


def _build_scales(multiscale, scale_min, scale_max, scale_steps):
    if not multiscale:
        return [1.0]
    lo, hi = sorted((float(scale_min), float(scale_max)))
    steps = max(1, int(scale_steps))
    scales = np.linspace(lo, hi, steps).tolist()
    return scales


def _match_template(img_gray, tpl, mask, threshold):
    """
    Template matching (avec masque éventuel).
    Renvoie (boxes Nx4 [x1, y1, x2, y2], scores N).
    """
    th, tw = tpl.shape
    H, W = img_gray.shape
    if th > H or tw > W:
        return np.empty((0, 4), dtype=np.int32), np.empty((0,), dtype=np.float32)

    if mask is None:
        res = cv.matchTemplate(img_gray, tpl, cv.TM_CCOEFF_NORMED)
    else:
        try:
            res = cv.matchTemplate(img_gray, tpl, cv.TM_CCOEFF_NORMED, mask=mask)
        except cv.error:
            # Anciennes versions d'OpenCV : masque non supporté en CCOEFF_NORMED
            res = cv.matchTemplate(img_gray, tpl, cv.TM_CCORR_NORMED, mask=mask)

        # Avec masque, les zones uniformes donnent NaN / inf : on les neutralise
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)

    ys, xs = np.where(res >= threshold)
    if xs.size == 0:
        return np.empty((0, 4), dtype=np.int32), np.empty((0,), dtype=np.float32)
    scores = res[ys, xs].astype(np.float32)
    boxes = np.stack([xs, ys, xs + tw, ys + th], axis=1).astype(np.int32)
    return boxes, scores


class OWPatternMatching(OWWidget):
    name = "Pattern Matcher - rollback"
    description = "Detects objects using template matching"
    icon = "icons/ow_pattern_matching.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/ow_pattern_matching.png"

    priority = 25
    want_control_area = False

    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_pattern_matching.ui")
    threshold_val = settings.Setting(0.8)
    overlap_val = settings.Setting(0.3)
    generate_preview = settings.Setting("False")
    str_autosend = settings.Setting("True")

    # Nouvelles options
    use_alpha_mask = settings.Setting("False")
    multiscale = settings.Setting("False")
    scale_min = settings.Setting(0.8)
    scale_max = settings.Setting(1.2)
    scale_steps = settings.Setting(5)

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
        self.thread = None
        self._run_id = 0
        self._run_domain = None

        self.setFixedWidth(478)
        self.setFixedHeight(655)

        uic.loadUi(self.gui, self)

        # Setup Threshold
        self.spinThreshold.setValue(self.threshold_val)
        self.spinThreshold.valueChanged.connect(self.update_threshold)

        # Setup Overlap (NMS)
        self.spinOverlap.setValue(self.overlap_val)
        self.spinOverlap.valueChanged.connect(self.update_overlap)

        self.checkBox_preview.setChecked(self.generate_preview != "False")
        self.checkBox_preview.stateChanged.connect(self.toogle_preview)

        # Transparence PNG (masque alpha)
        if hasattr(self, "checkBox_alpha_mask"):
            self.checkBox_alpha_mask.setChecked(self.use_alpha_mask == "True")
            self.checkBox_alpha_mask.stateChanged.connect(self.toggle_alpha_mask)

        # Multi-échelle
        if hasattr(self, "checkBox_multiscale"):
            self.checkBox_multiscale.setChecked(self.multiscale == "True")
            self.checkBox_multiscale.stateChanged.connect(self.toggle_multiscale)
        if hasattr(self, "spinScaleMin"):
            self.spinScaleMin.setValue(self.scale_min)
            self.spinScaleMin.valueChanged.connect(self.update_scale_min)
        if hasattr(self, "spinScaleMax"):
            self.spinScaleMax.setValue(self.scale_max)
            self.spinScaleMax.valueChanged.connect(self.update_scale_max)
        if hasattr(self, "spinScaleSteps"):
            self.spinScaleSteps.setValue(self.scale_steps)
            self.spinScaleSteps.valueChanged.connect(self.update_scale_steps)
        self._refresh_scale_widgets()

        # Setup Auto-send et Bouton Run
        self.checkBox_autosend.setChecked(self.str_autosend == "True")
        self.checkBox_autosend.stateChanged.connect(self.toggle_autosend)
        self.btnRun.clicked.connect(self.run_multi_matching)

    # ------------------------------------------------------------------
    # Callbacks UI : on mémorise seulement les paramètres.
    # Le calcul se lance à la réception d'un signal (si auto-send) ou via Run.
    # ------------------------------------------------------------------
    def toggle_autosend(self):
        self.str_autosend = "True" if self.checkBox_autosend.isChecked() else "False"

    def toogle_preview(self, enabled):
        self.generate_preview = "True" if self.checkBox_preview.isChecked() else "False"

    def toggle_alpha_mask(self, _):
        self.use_alpha_mask = "True" if self.checkBox_alpha_mask.isChecked() else "False"

    def toggle_multiscale(self, _):
        self.multiscale = "True" if self.checkBox_multiscale.isChecked() else "False"
        self._refresh_scale_widgets()

    def _refresh_scale_widgets(self):
        enabled = self.multiscale == "True"
        for name in ("spinScaleMin", "spinScaleMax", "spinScaleSteps",
                     "label_scale_min", "label_scale_max", "label_scale_steps"):
            if hasattr(self, name):
                getattr(self, name).setEnabled(enabled)

    def update_scale_min(self, val):
        self.scale_min = float(val)

    def update_scale_max(self, val):
        self.scale_max = float(val)

    def update_scale_steps(self, val):
        self.scale_steps = int(val)

    def update_threshold(self, val):
        self.threshold_val = val

    def update_overlap(self, val):
        self.overlap_val = val

    # ------------------------------------------------------------------
    # Entrées
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # NMS
    # ------------------------------------------------------------------
    @staticmethod
    def non_max_suppression(boxes, overlapThresh=0.3, scores=None):
        """
        Même NMS qu'avant (critère overlap > overlapThresh),
        MAIS au lieu de garder la bbox 'i' brute, on renvoie une bbox fusionnée:
        - centre = moyenne des centres (bbox i + celles supprimées avec elle)
        - taille = celle de la bbox i
        Si `scores` est fourni (mode multi-échelle), la bbox 'i' est celle de
        meilleur score : sa taille correspond donc à l'échelle la plus pertinente.
        Sans `scores`, comportement historique (tri sur y2).
        """
        if len(boxes) == 0:
            return []

        boxes = np.asarray(boxes, dtype=np.float32)

        out_boxes = []

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]

        area = (x2 - x1 + 1.0) * (y2 - y1 + 1.0)
        if scores is not None:
            idxs = np.argsort(np.asarray(scores), kind="stable")
        else:
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

            suppress = np.concatenate(([last], suppress_rel))
            idxs = np.delete(idxs, suppress)

        return np.round(np.asarray(out_boxes)).astype("int")

    # ------------------------------------------------------------------
    # Lancement (thread principal)
    # ------------------------------------------------------------------
    def _send_none(self):
        self.Outputs.data.send(None)
        self.Outputs.preview.send(None)
        self.Outputs.no_match.send(None)
        self.Outputs.center.send(None)

    def run_multi_matching(self):
        self.error("")
        self.warning("")

        # Arrêt d'un éventuel calcul en cours
        if self.thread is not None:
            self.thread.safe_quit()
            self.thread = None
            self.progressBarFinished()

        if self.input_data is None or self.input_reference is None:
            self._send_none()
            return

        existing_columns = [var.name for var in self.input_data.domain.variables + self.input_data.domain.metas]
        if "transform" in existing_columns or "name_out" in existing_columns:
            self.error("Colonne existante")
            self._send_none()
            return

        # Extraction des données Orange AVANT le thread (pas d'accès aux Tables dans le thread)
        scenes = [(self._get_path(self.input_data, i), list(self.input_data[i].list))
                  for i in range(len(self.input_data))]
        refs = [self._get_path(self.input_reference, i) for i in range(len(self.input_reference))]

        base_path_raw = scenes[0][0] if scenes else None
        base_dir = Path(base_path_raw).parent if base_path_raw else Path.cwd()

        params = {
            "threshold": float(self.threshold_val),
            "overlap": float(self.overlap_val),
            "preview": self.generate_preview != "False",
            "preview_dir": str(base_dir / "previews"),
            "use_alpha_mask": self.use_alpha_mask == "True",
            "multiscale": self.multiscale == "True",
            "scale_min": float(self.scale_min),
            "scale_max": float(self.scale_max),
            "scale_steps": int(self.scale_steps),
        }

        self._run_domain = self.input_data.domain
        self._run_id += 1
        run_id = self._run_id

        self.progressBarInit()
        self.thread = Thread(self._process, scenes, refs, params)
        self.thread.progress.connect(lambda v, rid=run_id: self.handle_progress(v, rid))
        self.thread.result.connect(lambda r, rid=run_id: self.handle_result(r, rid))
        self.thread.finish.connect(lambda rid=run_id: self.handle_finish(rid))
        self.thread.start()

    def handle_progress(self, value, run_id=None):
        if run_id is not None and run_id != self._run_id:
            return
        self.progressBarSet(int(value))

    def handle_finish(self, run_id=None):
        if run_id is not None and run_id != self._run_id:
            return
        print("Pattern matching finished")
        self.progressBarFinished()

    def handle_result(self, result, run_id=None):
        if run_id is not None and run_id != self._run_id:
            return  # résultat d'un calcul annulé
        try:
            if result is None:
                self._send_none()
                return
            if result.get("error"):
                self.error(result["error"])
                self._send_none()
                return
            if result.get("warnings"):
                self.warning(" | ".join(result["warnings"][:5]))

            in_domain = self._run_domain
            all_rows = result["all_rows"]
            no_match_rows = result["no_match_rows"]
            center_rows = result["center_rows"]
            preview_list = result["preview_list"]

            # Data
            if all_rows:
                new_metas = list(in_domain.metas) + [
                    StringVariable("transform"),
                    StringVariable("name_out")
                ]
                new_domain = Domain(in_domain.attributes, in_domain.class_vars, metas=new_metas)
                self.Outputs.data.send(Table.from_list(new_domain, all_rows))
            else:
                self.Outputs.data.send(None)

            # No match
            if no_match_rows:
                self.Outputs.no_match.send(Table.from_list(in_domain, no_match_rows))
            else:
                self.Outputs.no_match.send(None)

            # Preview (comportement historique : rien si aucun match)
            if all_rows and preview_list:
                self.Outputs.preview.send(
                    Table.from_list(Domain([], metas=[StringVariable("path")]), preview_list))
            else:
                self.Outputs.preview.send(None)

            # Center
            if center_rows:
                center_domain = Domain([], metas=[
                    StringVariable("path"),
                    StringVariable("col_centre"),
                    StringVariable("line_centre")
                ])
                self.Outputs.center.send(Table.from_list(center_domain, center_rows))
            else:
                self.Outputs.center.send(None)
        except Exception as e:
            print("Erreur lors de l'envoi des sorties :", e)
            self.error(str(e))
            self._send_none()

    # ------------------------------------------------------------------
    # Calcul (thread secondaire) : aucun appel Qt / Orange ici
    # ------------------------------------------------------------------
    def _process(self, scenes, refs, params, progress_callback):
        try:
            return self._process_impl(scenes, refs, params, progress_callback)
        except Exception as e:
            return {"error": f"Erreur pendant le matching : {e}"}

    def _process_impl(self, scenes, refs, params, progress_callback):
        warnings = []
        all_rows, preview_list, no_match_rows, center_rows = [], [], [], []

        threshold = params["threshold"]
        overlap = params["overlap"]
        do_preview = params["preview"]
        preview_dir = Path(params["preview_dir"])
        scales = _build_scales(params["multiscale"], params["scale_min"],
                               params["scale_max"], params["scale_steps"])
        use_scores = params["multiscale"]

        if do_preview:
            preview_dir.mkdir(parents=True, exist_ok=True)

        # 1. Préparation des templates (une seule fois pour toutes les images)
        #    templates[i_ref] = liste de (scale, tpl, mask)
        templates = []
        base_sizes = []  # (h_ref, w_ref) du template d'origine, par référence
        for i_ref, p_ref in enumerate(refs):
            variants = []
            base_size = None
            if p_ref:
                try:
                    gray, mask = _load_template(p_ref, params["use_alpha_mask"])
                except Exception as e:
                    gray, mask = None, None
                    warnings.append(f"Référence illisible : {p_ref} ({e})")

                if gray is not None:
                    # Partie prise en compte du template uniforme -> matching impossible
                    valid = gray[mask > 0] if mask is not None else gray
                    if params["use_alpha_mask"] and valid.size and float(valid.std()) < 1e-6:
                        warnings.append(f"Référence {i_ref} uniforme (aucun contraste) : ignorée")
                    else:
                        h0, w0 = gray.shape
                        base_size = (h0, w0)
                        for s in scales:
                            if abs(s - 1.0) < 1e-9:
                                t, m = gray, mask
                            else:
                                nw, nh = int(round(w0 * s)), int(round(h0 * s))
                                if nw < 4 or nh < 4:
                                    continue
                                interp = cv.INTER_AREA if s < 1.0 else cv.INTER_LINEAR
                                t = cv.resize(gray, (nw, nh), interpolation=interp)
                                m = None
                                if mask is not None:
                                    m = cv.resize(mask, (nw, nh), interpolation=cv.INTER_NEAREST)
                                    if not m.any():
                                        continue
                            variants.append((s, t, m))
                elif p_ref:
                    warnings.append(f"Référence non chargée : {p_ref}")
            templates.append(variants)
            base_sizes.append(base_size)

        n_variants = sum(len(v) for v in templates)
        total_steps = max(1, len(scenes) * max(1, n_variants))
        done = 0

        def step(n=1):
            nonlocal done
            done += n
            progress_callback(min(100.0, done / total_steps * 100.0))

        # 2. Boucle sur les images
        for p_scene, row_list in scenes:
            if not p_scene:
                step(max(1, n_variants))
                continue
            try:
                file_bytes = np.fromfile(p_scene, dtype=np.uint8)
                img_color = cv.imdecode(file_bytes, cv.IMREAD_COLOR)
            except Exception as e:
                print(f"Erreur de lecture : {p_scene} -> {e}")
                img_color = None
            if img_color is None:
                step(max(1, n_variants))
                continue

            img_gray = cv.cvtColor(img_color, cv.COLOR_BGR2GRAY)
            base_path = Path(p_scene)

            found_any = False
            centers_col, centers_line = [], []

            for i_ref, variants in enumerate(templates):
                boxes_list, scores_list = [], []
                for (_s, tpl, m) in variants:
                    b, sc = _match_template(img_gray, tpl, m, threshold)
                    if len(b):
                        boxes_list.append(b)
                        scores_list.append(sc)
                    step()

                if not boxes_list:
                    continue

                raw_boxes = np.concatenate(boxes_list, axis=0)
                raw_scores = np.concatenate(scores_list, axis=0)

                final_boxes = self.non_max_suppression(
                    raw_boxes, overlapThresh=overlap,
                    scores=raw_scores if use_scores else None)

                if len(final_boxes) == 0:
                    continue
                found_any = True

                # Tri en ordre de lecture (lignes puis colonnes)
                final_boxes = sorted(final_boxes, key=lambda b: b[1])
                if use_scores:
                    ref_h = int(np.median([b[3] - b[1] for b in final_boxes]))
                else:
                    ref_h = base_sizes[i_ref][0]  # comportement historique : h_ref
                row_idx = 0
                clustered = []
                prev_y = final_boxes[0][1]
                for box in final_boxes:
                    if abs(box[1] - prev_y) > (ref_h // 4):
                        row_idx += 1
                    prev_y = box[1]
                    clustered.append((row_idx, box))
                clustered.sort(key=lambda item: (item[0], item[1][0]))
                final_boxes = [item[1] for item in clustered]

                for i, (x1, y1, x2, y2) in enumerate(final_boxes):
                    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                    if do_preview:
                        cv.rectangle(img_color, (x1, y1), (x2, y2), (255, 0, 255), 2)

                    cx = int(round((x1 + x2) / 2.0))
                    cy = int(round((y1 + y2) / 2.0))
                    centers_col.append(str(cx))
                    centers_line.append(str(cy))

                    if use_scores:
                        # Multi-échelle : taille réelle de la détection
                        dl, dc = y2 - y1, x2 - x1
                    else:
                        # Comportement historique : taille du template
                        dl, dc = base_sizes[i_ref]
                    transform_cmd = (f"Crop | line = {y1} | col = {x1} | "
                                     f"delta_line = {dl} | delta_col = {dc}")
                    output_filename = f"{base_path.stem}_ref{i_ref}_{i}{base_path.suffix}"
                    all_rows.append(list(row_list) + [transform_cmd, output_filename])

            if n_variants == 0:
                step()

            if found_any:
                center_rows.append([str(p_scene), " ".join(centers_col), " ".join(centers_line)])
            else:
                no_match_rows.append(list(row_list))

            if do_preview:
                preview_path = str(preview_dir / f"preview_{base_path.name}")
                rgb = cv.cvtColor(img_color, cv.COLOR_BGR2RGB)
                try:
                    tiff.imwrite(preview_path, rgb, compression=None)
                    preview_list.append([preview_path])
                except Exception as e:
                    print(f"Erreur écriture preview : {e}")

        progress_callback(100.0)
        return {
            "all_rows": all_rows,
            "no_match_rows": no_match_rows,
            "center_rows": center_rows,
            "preview_list": preview_list,
            "warnings": warnings,
        }

    def onDeleteWidget(self):
        if self.thread is not None:
            self.thread.safe_quit()
            self.thread = None
        super().onDeleteWidget()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = OWPatternMatching()
    w.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
