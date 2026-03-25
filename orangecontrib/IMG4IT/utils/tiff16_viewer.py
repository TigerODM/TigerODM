# -*- coding: utf-8 -*-
"""
Viewer TIFF 16 bits avec réglage d'étalement, zoom/pan
+ modes: linéaire, gamma 0.5, gamma 2.0, sigmoide,
         log, inverse-log, exponentielle, racine √, racine ³,
         HE (global), CLAHE (local via scikit-image si dispo),
         Wallis (local), Canny (edges via scikit-image si dispo)

NOUVEAU:
- Checkbox "Relative Min/Max (%)":
    OFF: spec/affichage en Min (I16) / Max (I16) (comportement actuel)
    ON : spec/affichage en Min(%) / Max(%) (valeurs des sliders)
         => transform_tiff16_to_tiff8 recalcule Min/Max I16 à chaque image, à partir de ces percentiles

AJOUTS (sans refactor, uniquement des ajouts):
- Binarisation (dans la chaîne 16->8, comme la sigmoïde, donc dépend de lv/hv):
    * UI: "Seuillage (binaire)" + seuil en % (sur t) ou absolu I16 + "Inverser"
    * Spec: "Binarize(%) = N" ou "Binarize (I16) = V" + "Binarize invert = 0/1"
- Modes supplémentaires (dans la chaîne 16->8, basés sur t):
    * Gradient Horizontal (d/dx)
    * Gradient Vertical   (d/dy)
    * Sobel (magnitude)

AJOUT (sans refactor, uniquement des ajouts):
- Sélection souris (clic maintenu + drag) sur l'image:
    Au relâchement, écrit dans la zone de texte:
      Crop | line = xxxx | col = yyyyy | delta_line = dxxxx | delta_col = dyyyy
    avec min/max de la zone (delta >= 0) et clamp aux bornes image.

AJOUT (sans refactor, uniquement des ajouts):
- Opération Draw:
    Draw | col = 50.0 49.0 | line = 59.0 15.0 | type = cross
    Draw | col = 50.0 49.0 | line = 59.0 15.0 | type = invcross

    => produit une image de sortie = image d'entrée + croix centrées sur les pixels demandés.
       cross    : centre BLANC, bras NOIRS (rayon=3)
       invcross : centre NOIR,  bras BLANCS (rayon=3)
       Tronquée aux bords (clamp).

Le champ de texte en bas affiche une spec complète "Transform | ..." réutilisable en batch.

Dépendances: AnyQt, numpy, tifffile, scipy
Optionnel: scikit-image (CLAHE + Canny)
"""
import sys
import os
import re
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
import tifffile as tiff
from AnyQt import QtWidgets, QtGui, QtCore
from scipy.ndimage import uniform_filter
from scipy.ndimage import sobel as ndi_sobel  # Sobel (scipy)
from pathlib import Path

# --- CLAHE + Canny optionnels via scikit-image ---
try:
    from skimage import exposure as sk_exposure
    from skimage import feature as sk_feature
    HAS_SKIMAGE = True
except Exception:
    HAS_SKIMAGE = False

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IMG4IT.utils.reacalage_image import apply_transform_to_image_file
else:
    from orangecontrib.IMG4IT.utils.reacalage_image import apply_transform_to_image_file

from scipy.ndimage import gaussian_filter
import pydicom
# -------------------------------
# Safe cast helpers (évite float(None))
# -------------------------------
def _safe_float(x):
    return float(x) if x is not None else None


def _safe_int(x):
    return int(x) if x is not None else None


# -------------------------------
# AJOUT: Convert spec parsing (Convert | out = dcm/png/jpg | pdf_zoom=... | jpeg_quality=...)
# -------------------------------
def _parse_convert_spec(spec: str) -> Dict[str, Any]:
    """
    Parse best-effort d'une spec Convert.

    Exemples supportés:
      - "Convert | out = dcm"
      - "Convert | out = png | pdf_zoom = 2.0 | pdf_page_index = 0"
      - "Convert | out = jpg | jpeg_quality = 95"
    """
    if not isinstance(spec, str):
        return {"out": None, "pdf_page_index": 0, "pdf_zoom": 2.0, "jpeg_quality": 95}

    raw = spec.strip().replace('"', " ")
    out = None

    m_out = re.search(r"\bout\s*=\s*([a-zA-Z0-9\.]+)\b", raw, flags=re.I)
    if m_out:
        out = m_out.group(1).strip().lower()
        if out.startswith("."):
            out = out[1:]
        if out == "jpeg":
            out = "jpg"

    def _get_int(name: str, default: int) -> int:
        m = re.search(rf"\b{name}\s*=\s*(-?\d+)", raw, flags=re.I)
        try:
            return int(m.group(1)) if m else int(default)
        except Exception:
            return int(default)

    def _get_float(name: str, default: float) -> float:
        m = re.search(rf"\b{name}\s*=\s*([0-9]*\.?[0-9]+)", raw, flags=re.I)
        try:
            return float(m.group(1)) if m else float(default)
        except Exception:
            return float(default)

    return {
        "out": out,
        "pdf_page_index": _get_int("pdf_page_index", 0),
        "pdf_zoom": _get_float("pdf_zoom", 2.0),
        "jpeg_quality": _get_int("jpeg_quality", 95),
    }


# -------------------------------
# AJOUT: Binarize helpers (dans la chaîne 16->8)
# -------------------------------
def _binarize_from_t(t: np.ndarray, thr_t: float, invert: bool = False) -> np.ndarray:
    """
    t: float32 dans [0,1]
    thr_t: seuil en [0,1]
    retourne uint8 binaire (0/255), avec option invert.
    """
    thr_t = float(thr_t)
    if thr_t < 0.0:
        thr_t = 0.0
    elif thr_t > 1.0:
        thr_t = 1.0

    m = (t >= thr_t)
    if invert:
        m = ~m
    return (m.astype(np.uint8) * 255)


# -------------------------------
# AJOUT: Gradient/Sobel helpers (dans la chaîne 16->8)
# -------------------------------
def _normalize_to_u8_from_float01(a: np.ndarray) -> np.ndarray:
    """Normalise un float array (>=0) vers uint8 0..255 via max()."""
    a = np.asarray(a, dtype=np.float32)
    mx = float(np.max(a)) if a.size else 0.0
    if mx <= 0.0:
        return np.zeros(a.shape, dtype=np.uint8)
    y = (a / mx) * 255.0
    return np.clip(y, 0.0, 255.0).astype(np.uint8)


def _gradient_x_u8(t: np.ndarray) -> np.ndarray:
    """Gradient horizontal |d/dx| sur t∈[0,1] -> uint8."""
    _dy, dx = np.gradient(t.astype(np.float32), edge_order=1)
    return _normalize_to_u8_from_float01(np.abs(dx))


def _gradient_y_u8(t: np.ndarray) -> np.ndarray:
    """Gradient vertical |d/dy| sur t∈[0,1] -> uint8."""
    dy, _dx = np.gradient(t.astype(np.float32), edge_order=1)
    return _normalize_to_u8_from_float01(np.abs(dy))


def _sobel_mag_u8(t: np.ndarray) -> np.ndarray:
    """Magnitude Sobel sur t∈[0,1] -> uint8 (normalisé)."""
    gx = ndi_sobel(t.astype(np.float32), axis=1, mode="reflect")
    gy = ndi_sobel(t.astype(np.float32), axis=0, mode="reflect")
    mag = np.sqrt(gx * gx + gy * gy, dtype=np.float32)
    return _normalize_to_u8_from_float01(mag)


# -------------------------------
# Utils image / histogramme
# -------------------------------
def qimage_from_gray_uint8(arr_u8: np.ndarray) -> QtGui.QImage:
    """Convertit un ndarray uint8 (H, W) en QImage Grayscale8 sans copie."""
    if arr_u8.dtype != np.uint8 or arr_u8.ndim != 2:
        raise ValueError("qimage_from_gray_uint8 attend un array (H, W) en uint8.")
    if not arr_u8.flags["C_CONTIGUOUS"]:
        arr_u8 = np.ascontiguousarray(arr_u8)
    h, w = arr_u8.shape
    bytes_per_line = arr_u8.strides[0]
    qimg = QtGui.QImage(arr_u8.data, w, h, bytes_per_line,
                        QtGui.QImage.Format.Format_Grayscale8)
    qimg._arr_ref = arr_u8  # garder réf vivante
    return qimg


def hist_uint16(arr_u16: np.ndarray) -> np.ndarray:
    return np.bincount(arr_u16.ravel(), minlength=65536)


def percentile_from_hist(hist: np.ndarray, total_px: int, p: float) -> int:
    """Retourne une valeur 16 bits au percentile p en s'appuyant sur l'histogramme 65536 bins."""
    if p <= 0:
        return 0
    if p >= 100:
        return 65535
    target = total_px * (p / 100.0)
    cdf = np.cumsum(hist, dtype=np.int64)
    idx = int(np.searchsorted(cdf, target, side="left"))
    return int(np.clip(idx, 0, 65535))


def compute_low_high_from_percentiles(arr16: np.ndarray, low_p: int, high_p: int) -> Tuple[int, int]:
    """Calcule (lv,hv) I16 depuis percentiles sur l'image donnée."""
    arr16 = np.ascontiguousarray(arr16)
    h = hist_uint16(arr16)
    total_px = int(arr16.size)
    lv = percentile_from_hist(h, total_px, float(low_p))
    hv = percentile_from_hist(h, total_px, float(high_p))
    if hv <= lv:
        hv = min(lv + 1, 65535)
    return int(lv), int(hv)


# -------------------------------
# HE / CLAHE / Wallis
# -------------------------------
def he_on_unit_float(t: np.ndarray, nbins: int = 256) -> np.ndarray:
    t = np.clip(t.astype(np.float32), 0.0, 1.0)
    hh, bins = np.histogram(t, bins=int(max(2, nbins)), range=(0.0, 1.0))
    cdf = np.cumsum(hh).astype(np.float32)
    if cdf[-1] <= 0:
        return t
    cdf /= cdf[-1]
    bin_centers = (bins[:-1] + bins[1:]) * 0.5
    y = np.interp(t.ravel(), bin_centers, cdf).reshape(t.shape).astype(np.float32)
    return y


def wallis_filter(t: np.ndarray, win_size: int,
                  mu_target: float = 50.0, sigma_target: float = 30.0) -> np.ndarray:
    """
    Wallis filter sur image normalisée t ∈ [0,1].
    mu_target/sigma_target en échelle 0..255.
    """
    t = t.astype(np.float32)

    local_mean = uniform_filter(t, size=win_size, mode="reflect")
    local_mean_sq = uniform_filter(t * t, size=win_size, mode="reflect")
    local_var = np.maximum(local_mean_sq - local_mean * local_mean, 1e-6)
    local_std = np.sqrt(local_var, dtype=np.float32)

    mu_c = mu_target / 255.0
    sigma_c = sigma_target / 255.0
    y = (t - local_mean) * (sigma_c / (local_std + 1e-6)) + mu_c
    return np.clip(y, 0.0, 1.0).astype(np.float32)


def clahe_on_unit_float(t: np.ndarray, clip_limit: float = 0.01, nbins: int = 256) -> np.ndarray:
    t = np.clip(t.astype(np.float32), 0.0, 1.0)
    if HAS_SKIMAGE:
        y = sk_exposure.equalize_adapthist(
            t,
            clip_limit=float(max(1e-6, clip_limit)),
            nbins=int(max(2, nbins)),
        )
        return y.astype(np.float32, copy=False)
    return he_on_unit_float(t, nbins=nbins)

# -------------------------------
# AJOUT: Helpers de filtrage
# -------------------------------
def apply_high_pass_filter(t: np.ndarray, sigma: float = 3.0) -> np.ndarray:
    """Filtre Passe-Haut (Adaptatif : gère I16 natif et float 0..1)."""
    f32 = t.astype(np.float32)
    low_freq = gaussian_filter(f32, sigma=sigma)
    if t.dtype == np.uint16:
        return np.clip(f32 - low_freq + 32768.0, 0, 65535).astype(np.uint16)
    else:
        return np.clip(f32 - low_freq + 0.5, 0.0, 1.0)

def apply_sharpen_filter(t: np.ndarray, amount: float = 1.0, radius: float = 1.0) -> np.ndarray:
    """Filtre Sharpen (Adaptatif : gère I16 natif et float 0..1)."""
    f32 = t.astype(np.float32)
    blurred = gaussian_filter(f32, sigma=radius)
    sharpened = f32 + amount * (f32 - blurred)
    if t.dtype == np.uint16:
        return np.clip(sharpened, 0, 65535).astype(np.uint16)
    else:
        return np.clip(sharpened, 0.0, 1.0)

# -------------------------------
# Viewer
# -------------------------------
class ImageView(QtWidgets.QGraphicsView):
    """Widget avec zoom + pan à la souris + émission des coords souris."""
    mouseMoved = QtCore.Signal(int, int)  # (col, row)

    # signal rectangle crop (col, row, delta_col, delta_line)
    cropSelected = QtCore.Signal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._img_w = 0
        self._img_h = 0
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.viewport().installEventFilter(self)

        # RubberBand de sélection (crop)
        self._rb = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Shape.Rectangle, self.viewport())
        self._rb.hide()
        self._rb_origin = None
        self._rb_active = False
        self._prev_drag_mode = self.dragMode()

        # Pan au clic droit
        self._pan_active = False
        self._pan_last_pos = None

    def eventFilter(self, obj, ev):
        if obj is self.viewport() and ev.type() == QtCore.QEvent.CursorChange:
            if self.viewport().cursor().shape() != QtCore.Qt.CrossCursor:
                QtCore.QTimer.singleShot(0, lambda: self.viewport().setCursor(QtCore.Qt.CrossCursor))
                return True
        return super().eventFilter(obj, ev)

    def set_image_size(self, w: int, h: int):
        self._img_w = int(max(0, w))
        self._img_h = int(max(0, h))

    def wheelEvent(self, event: QtGui.QWheelEvent):
        zoom_in_factor = 1.25
        zoom_out_factor = 1 / zoom_in_factor
        f = zoom_in_factor if event.angleDelta().y() > 0 else zoom_out_factor
        self.scale(f, f)

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        # Pan au clic droit
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            self._pan_active = True
            self._pan_last_pos = event.pos()
            self.viewport().setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            # Démarre sélection rectangle
            self._rb_active = True
            self._rb_origin = event.pos()
            self._prev_drag_mode = self.dragMode()
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)

            self._rb.setGeometry(QtCore.QRect(self._rb_origin, QtCore.QSize()))
            self._rb.show()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        # Pan au clic droit
        if getattr(self, "_pan_active", False) and self._pan_last_pos is not None:
            dp = event.pos() - self._pan_last_pos
            self._pan_last_pos = event.pos()
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - dp.x())
            vbar.setValue(vbar.value() - dp.y())
            event.accept()
            return

        sp = self.mapToScene(event.pos())
        x = int(np.floor(sp.x()))
        y = int(np.floor(sp.y()))
        if 0 <= x < self._img_w and 0 <= y < self._img_h:
            self.mouseMoved.emit(x, y)
        else:
            self.mouseMoved.emit(-1, -1)

        if self._rb_active and self._rb_origin is not None:
            rect = QtCore.QRect(self._rb_origin, event.pos()).normalized()
            self._rb.setGeometry(rect)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        # fin pan clic droit
        if getattr(self, "_pan_active", False) and event.button() == QtCore.Qt.MouseButton.RightButton:
            self._pan_active = False
            self._pan_last_pos = None
            self.viewport().setCursor(QtCore.Qt.CursorShape.CrossCursor)
            event.accept()
            return

        if self._rb_active and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._rb.hide()
            self._rb_active = False

            self.setDragMode(self._prev_drag_mode)

            if self._rb_origin is None:
                super().mouseReleaseEvent(event)
                return

            p0 = self._rb_origin
            p1 = event.pos()
            self._rb_origin = None

            s0 = self.mapToScene(p0)
            s1 = self.mapToScene(p1)

            x0 = int(np.floor(s0.x()))
            y0 = int(np.floor(s0.y()))
            x1 = int(np.floor(s1.x()))
            y1 = int(np.floor(s1.y()))

            if self._img_w > 0 and self._img_h > 0:
                x0 = int(np.clip(x0, 0, self._img_w - 1))
                x1 = int(np.clip(x1, 0, self._img_w - 1))
                y0 = int(np.clip(y0, 0, self._img_h - 1))
                y1 = int(np.clip(y1, 0, self._img_h - 1))

            col_min = min(x0, x1)
            col_max = max(x0, x1)
            row_min = min(y0, y1)
            row_max = max(y0, y1)

            delta_col = int(max(0, col_max - col_min))
            delta_line = int(max(0, row_max - row_min))

            self.cropSelected.emit(col_min, row_min, delta_col, delta_line)
            event.accept()
            return

        super().mouseReleaseEvent(event)


class Tiff16Viewer(QtWidgets.QWidget):
    def __init__(self, input_path, parent=None):
        super().__init__(parent)

        # --- Résolution dossier / liste images ---
        self.files: List[str] = []
        self.idx = 0
        self._resolve_inputs(input_path)

        # --- État image ---
        self.arr16: Optional[np.ndarray] = None
        self.h = self.w = 0
        self.hist: Optional[np.ndarray] = None
        self.total_px = 0
        self.min_val = 0
        self.max_val = 0
        self._last_img8: Optional[np.ndarray] = None
        self._last_transform_spec: str = ""

        # --- Scene / view ---
        self.scene = QtWidgets.QGraphicsScene()
        self.view = ImageView()
        self.view.setScene(self.scene)
        self.pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)

        # --- Bandeau nom fichier ---
        self.name_label = QtWidgets.QLabel("--")
        self.name_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

        nav = QtWidgets.QHBoxLayout()
        nav.addStretch(1)
        nav.addWidget(self.name_label)

        # --- Coordonnées souris ---
        self.col_edit = QtWidgets.QLineEdit()
        self.col_edit.setReadOnly(True)
        self.col_edit.setFixedWidth(90)
        self.col_edit.setPlaceholderText("Colonne")

        self.row_edit = QtWidgets.QLineEdit()
        self.row_edit.setReadOnly(True)
        self.row_edit.setFixedWidth(90)
        self.row_edit.setPlaceholderText("Ligne")

        self.val_edit = QtWidgets.QLineEdit()
        self.val_edit.setReadOnly(True)
        self.val_edit.setFixedWidth(140)
        self.val_edit.setPlaceholderText("Valeur 16b → 8b")

        coords = QtWidgets.QHBoxLayout()
        coords.addWidget(QtWidgets.QLabel("Ligne:"))
        coords.addWidget(self.row_edit)
        coords.addSpacing(8)
        coords.addWidget(QtWidgets.QLabel("Col:"))
        coords.addWidget(self.col_edit)
        coords.addSpacing(8)
        coords.addWidget(QtWidgets.QLabel("Valeur:"))
        coords.addWidget(self.val_edit)
        coords.addStretch(1)

        # --- Sliders percentiles ---
        self.low_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.high_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        for s in (self.low_slider, self.high_slider):
            s.setRange(0, 100)
            s.setTickInterval(5)
            s.setSingleStep(1)
            s.setTracking(True)
        self.low_slider.setValue(2)
        self.high_slider.setValue(98)

        self.low_spin = QtWidgets.QSpinBox()
        self.low_spin.setRange(0, 100)
        self.low_spin.setSuffix(" %")
        self.high_spin = QtWidgets.QSpinBox()
        self.high_spin.setRange(0, 100)
        self.high_spin.setSuffix(" %")
        self.low_spin.setValue(self.low_slider.value())
        self.high_spin.setValue(self.high_slider.value())

        # --- Boutons d'étendue ---
        self.btn_auto = QtWidgets.QPushButton("Auto (2–98%)")
        self.btn_full = QtWidgets.QPushButton("Plein écart (min–max)")
        self.btn_reset = QtWidgets.QPushButton("Réinitialiser vue")

        # --- Boutons contraste ---
        self.btn_lin = QtWidgets.QPushButton("Lineaire")
        self.btn_gam05 = QtWidgets.QPushButton("Gamma 0.5")
        self.btn_gam20 = QtWidgets.QPushButton("Gamma 2.0")
        self.btn_sig = QtWidgets.QPushButton("Sigmoide")

        self.btn_log = QtWidgets.QPushButton("Log")
        self.btn_invlog = QtWidgets.QPushButton("Inverse-Log")
        self.btn_exp = QtWidgets.QPushButton("Exponentielle")
        self.btn_sqrt = QtWidgets.QPushButton("Racine carree")
        self.btn_cbrt = QtWidgets.QPushButton("Racine cubique")
        self.btn_he = QtWidgets.QPushButton("HE (global)")
        self.btn_clahe = QtWidgets.QPushButton("CLAHE")

        # --- boutons Gradient/Sobel ---
        self.btn_gradx = QtWidgets.QPushButton("Grad X")
        self.btn_grady = QtWidgets.QPushButton("Grad Y")
        self.btn_sobel = QtWidgets.QPushButton("Sobel")

        # --- Wallis ---
        self.btn_wallis = QtWidgets.QPushButton("Wallis")
        self.wallis_win_spin = QtWidgets.QSpinBox()
        self.wallis_win_spin.setRange(3, 101)
        self.wallis_win_spin.setSingleStep(2)
        self.wallis_win_spin.setValue(15)

        self.wallis_mu_spin = QtWidgets.QSpinBox()
        self.wallis_mu_spin.setRange(0, 255)
        self.wallis_mu_spin.setValue(127)

        self.wallis_sigma_spin = QtWidgets.QSpinBox()
        self.wallis_sigma_spin.setRange(0, 255)
        self.wallis_sigma_spin.setValue(35)

        # --- HE/CLAHE params ---
        self.he_bins_spin = QtWidgets.QSpinBox()
        self.he_bins_spin.setRange(16, 4096)
        self.he_bins_spin.setSingleStep(16)
        self.he_bins_spin.setValue(256)

        self.clahe_clip_spin = QtWidgets.QDoubleSpinBox()
        self.clahe_clip_spin.setRange(0.001, 0.100)
        self.clahe_clip_spin.setSingleStep(0.001)
        self.clahe_clip_spin.setDecimals(3)
        self.clahe_clip_spin.setValue(0.010)

        # --- Canny ---
        self.btn_canny = QtWidgets.QPushButton("Canny")
        self.btn_canny.setEnabled(HAS_SKIMAGE)
        self.canny_sigma_spin = QtWidgets.QDoubleSpinBox()
        self.canny_sigma_spin.setRange(0.1, 10.0)
        self.canny_sigma_spin.setSingleStep(0.1)
        self.canny_sigma_spin.setDecimals(1)
        self.canny_sigma_spin.setValue(1.2)

        self.canny_low_spin = QtWidgets.QDoubleSpinBox()
        self.canny_low_spin.setRange(0.0, 1.0)
        self.canny_low_spin.setSingleStep(0.01)
        self.canny_low_spin.setDecimals(2)
        self.canny_low_spin.setValue(0.08)

        self.canny_high_spin = QtWidgets.QDoubleSpinBox()
        self.canny_high_spin.setRange(0.0, 1.0)
        self.canny_high_spin.setSingleStep(0.01)
        self.canny_high_spin.setDecimals(2)
        self.canny_high_spin.setValue(0.20)

        # --- Passe-Haut ---
        self.btn_highpass = QtWidgets.QPushButton("Passe-Haut")
        self.hp_sigma_spin = QtWidgets.QDoubleSpinBox()
        self.hp_sigma_spin.setRange(0.1, 50.0)
        self.hp_sigma_spin.setValue(3.0)

        # --- Sharpen ---
        self.btn_sharpen = QtWidgets.QPushButton("Sharpen")
        self.sh_amt_spin = QtWidgets.QDoubleSpinBox()
        self.sh_amt_spin.setRange(0.0, 20.0)
        self.sh_amt_spin.setValue(1.0)
        self.sh_rad_spin = QtWidgets.QDoubleSpinBox()
        self.sh_rad_spin.setRange(0.1, 10.0)
        self.sh_rad_spin.setValue(1.0)

        # --- Checkbox Relative Min/Max ---
        self.chk_relative_minmax = QtWidgets.QCheckBox("Relative Min/Max (%)")
        self.chk_relative_minmax.setChecked(False)
        self.chk_relative_minmax.setToolTip(
            "OFF: spec/affichage en Min/Max I16 (comportement actuel)\n"
            "ON : spec/affichage en Min/Max percentiles (sliders) -> recalcule Min/Max I16 à chaque image en batch."
        )

        # --- Binarize UI ---
        self.chk_threshold = QtWidgets.QCheckBox("Seuillage (binaire)")
        self.chk_threshold.setChecked(False)

        self.thr_mode_combo = QtWidgets.QComboBox()
        self.thr_mode_combo.addItems(["%", "Abs (I16)"])
        self.thr_mode_combo.setToolTip(
            "Binarisation appliquée sur t=(I16-lv)/(hv-lv) ∈ [0,1]\n"
            "- % : thr_t=pct/100\n"
            "- Abs (I16) : thr_t=(thr_i16-lv)/(hv-lv)"
        )

        self.thr_spin = QtWidgets.QSpinBox()
        self.thr_spin.setRange(0, 100)
        self.thr_spin.setSuffix(" %")
        self.thr_spin.setValue(50)

        self.chk_threshold_invert = QtWidgets.QCheckBox("Inverser")
        self.chk_threshold_invert.setChecked(False)

        def _on_thr_mode_changed(_idx: int):
            txt = self.thr_mode_combo.currentText()
            if txt.startswith("%"):
                self.thr_spin.blockSignals(True)
                self.thr_spin.setRange(0, 100)
                self.thr_spin.setSuffix(" %")
                self.thr_spin.setValue(int(np.clip(self.thr_spin.value(), 0, 100)))
                self.thr_spin.blockSignals(False)
            else:
                self.thr_spin.blockSignals(True)
                self.thr_spin.setRange(0, 65535)
                self.thr_spin.setSuffix("")
                self.thr_spin.setValue(int(np.clip(self.thr_spin.value(), 0, 65535)))
                self.thr_spin.blockSignals(False)
            self.update_view()

        self.thr_mode_combo.currentIndexChanged.connect(_on_thr_mode_changed)

        # --- Mode courant ---
        self.contrast_mode = "linear"

        # --- Layouts ---
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Percentile bas"), 0, 0)
        grid.addWidget(self.low_slider, 0, 1)
        grid.addWidget(self.low_spin, 0, 2)
        grid.addWidget(QtWidgets.QLabel("Percentile haut"), 1, 0)
        grid.addWidget(self.high_slider, 1, 1)
        grid.addWidget(self.high_spin, 1, 2)

        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(self.btn_auto)
        btns.addWidget(self.btn_full)
        btns.addWidget(self.btn_reset)
        btns.addStretch(1)

        contrast_btns1 = QtWidgets.QHBoxLayout()
        contrast_btns1.addWidget(QtWidgets.QLabel("Courbe contraste :"))
        for b in (self.btn_lin, self.btn_gam05, self.btn_gam20, self.btn_sig):
            contrast_btns1.addWidget(b)
        contrast_btns1.addStretch(1)

        contrast_btns2 = QtWidgets.QHBoxLayout()
        for b in (self.btn_log, self.btn_invlog, self.btn_exp, self.btn_sqrt, self.btn_cbrt, self.btn_he, self.btn_clahe):
            contrast_btns2.addWidget(b)

        contrast_btns2.addWidget(self.btn_gradx)
        contrast_btns2.addWidget(self.btn_grady)
        contrast_btns2.addWidget(self.btn_sobel)

        contrast_btns2.addWidget(self.btn_wallis)
        contrast_btns2.addWidget(self.btn_canny)
        contrast_btns2.addStretch(1)

        params_row = QtWidgets.QHBoxLayout()
        params_row.addWidget(QtWidgets.QLabel("HE nbins:"))
        params_row.addWidget(self.he_bins_spin)
        params_row.addSpacing(12)
        params_row.addWidget(QtWidgets.QLabel("CLAHE clip:"))
        params_row.addWidget(self.clahe_clip_spin)

        params_row.addSpacing(12)
        params_row.addWidget(QtWidgets.QLabel("Wallis win:"))
        params_row.addWidget(self.wallis_win_spin)
        params_row.addSpacing(6)
        params_row.addWidget(QtWidgets.QLabel("Wallis mean:"))
        params_row.addWidget(self.wallis_mu_spin)
        params_row.addSpacing(6)
        params_row.addWidget(QtWidgets.QLabel("Wallis std:"))
        params_row.addWidget(self.wallis_sigma_spin)

        params_row.addSpacing(12)
        params_row.addWidget(QtWidgets.QLabel("Canny σ:"))
        params_row.addWidget(self.canny_sigma_spin)
        params_row.addSpacing(6)
        params_row.addWidget(QtWidgets.QLabel("low:"))
        params_row.addWidget(self.canny_low_spin)
        params_row.addSpacing(6)
        params_row.addWidget(QtWidgets.QLabel("high:"))
        params_row.addWidget(self.canny_high_spin)

        params_row.addSpacing(12)
        params_row.addWidget(self.chk_relative_minmax)

        params_row.addSpacing(12)
        params_row.addWidget(self.chk_threshold)
        params_row.addWidget(self.thr_mode_combo)
        params_row.addWidget(self.thr_spin)
        params_row.addWidget(self.chk_threshold_invert)
        params_row.addStretch(1)

        params_row.addSpacing(12)
        params_row.addWidget(self.btn_highpass)
        params_row.addWidget(QtWidgets.QLabel("σ:"))
        params_row.addWidget(self.hp_sigma_spin)

        params_row.addSpacing(12)
        params_row.addWidget(self.btn_sharpen)
        params_row.addWidget(QtWidgets.QLabel("Amt:"))
        params_row.addWidget(self.sh_amt_spin)
        params_row.addWidget(QtWidgets.QLabel("Rad:"))
        params_row.addWidget(self.sh_rad_spin)

        # --- Panneau d'infos (spec) ---
        self.info_edit = QtWidgets.QLineEdit()
        self.info_edit.setReadOnly(True)
        self.info_edit.setPlaceholderText("Transform | ...")

        v = QtWidgets.QVBoxLayout(self)
        v.addLayout(nav)
        v.addWidget(self.view, stretch=1)
        v.addLayout(coords)
        v.addLayout(grid)
        v.addLayout(btns)
        v.addLayout(contrast_btns1)
        v.addLayout(contrast_btns2)
        v.addLayout(params_row)
        v.addWidget(self.info_edit)

        # --- Connexions ---
        self.low_slider.valueChanged.connect(self._on_low_slider)
        self.high_slider.valueChanged.connect(self._on_high_slider)
        self.low_spin.valueChanged.connect(self._on_low_spin)
        self.high_spin.valueChanged.connect(self._on_high_spin)

        self.btn_auto.clicked.connect(self.apply_auto)
        self.btn_full.clicked.connect(self.apply_full)
        self.btn_reset.clicked.connect(self.reset_view)

        self.btn_lin.clicked.connect(lambda: self.set_contrast_mode("linear"))
        self.btn_gam05.clicked.connect(lambda: self.set_contrast_mode("gamma05"))
        self.btn_gam20.clicked.connect(lambda: self.set_contrast_mode("gamma20"))
        self.btn_sig.clicked.connect(lambda: self.set_contrast_mode("sigmoid"))

        self.btn_log.clicked.connect(lambda: self.set_contrast_mode("log"))
        self.btn_invlog.clicked.connect(lambda: self.set_contrast_mode("invlog"))
        self.btn_exp.clicked.connect(lambda: self.set_contrast_mode("exp"))
        self.btn_sqrt.clicked.connect(lambda: self.set_contrast_mode("sqrt"))
        self.btn_cbrt.clicked.connect(lambda: self.set_contrast_mode("cbrt"))
        self.btn_he.clicked.connect(lambda: self.set_contrast_mode("he"))
        self.btn_clahe.clicked.connect(lambda: self.set_contrast_mode("clahe"))

        self.btn_gradx.clicked.connect(lambda: self.set_contrast_mode("gradx"))
        self.btn_grady.clicked.connect(lambda: self.set_contrast_mode("grady"))
        self.btn_sobel.clicked.connect(lambda: self.set_contrast_mode("sobel"))

        self.btn_wallis.clicked.connect(lambda: self.set_contrast_mode("wallis"))
        self.btn_canny.clicked.connect(lambda: self.set_contrast_mode("canny"))
        self.btn_highpass.clicked.connect(lambda: self.set_contrast_mode("highpass"))
        self.btn_sharpen.clicked.connect(lambda: self.set_contrast_mode("sharpen"))

        self.he_bins_spin.valueChanged.connect(self.update_view)
        self.clahe_clip_spin.valueChanged.connect(self.update_view)
        self.wallis_win_spin.valueChanged.connect(self.update_view)
        self.wallis_mu_spin.valueChanged.connect(self.update_view)
        self.wallis_sigma_spin.valueChanged.connect(self.update_view)

        self.canny_sigma_spin.valueChanged.connect(self.update_view)
        self.canny_low_spin.valueChanged.connect(self.update_view)
        self.canny_high_spin.valueChanged.connect(self.update_view)
        self.hp_sigma_spin.valueChanged.connect(self.update_view)
        self.sh_amt_spin.valueChanged.connect(self.update_view)
        self.sh_rad_spin.valueChanged.connect(self.update_view)

        self.chk_relative_minmax.stateChanged.connect(self.update_view)

        self.chk_threshold.stateChanged.connect(self.update_view)
        self.thr_spin.valueChanged.connect(self.update_view)
        self.chk_threshold_invert.stateChanged.connect(self.update_view)

        self.view.mouseMoved.connect(self._on_mouse_moved)
        self.view.cropSelected.connect(self._on_crop_selected)

        # --- Charge première image ---
        self._load_current_image()

    def _on_crop_selected(self, col: int, row: int, delta_col: int, delta_line: int):
        crop_spec = f"Crop | line = {row} | col = {col} | delta_line = {delta_line} | delta_col = {delta_col}"
        crop_spec = '"' + crop_spec + '"'
        self.info_edit.setText(crop_spec)
        self._last_transform_spec = crop_spec

    def build_transform_spec_from_ui(self, low_val_i16: int, high_val_i16: int) -> str:
        parts = ["Transform"]

        if self.chk_relative_minmax.isChecked():
            parts.append(f"Min(%) = {int(self.low_slider.value())}")
            parts.append(f"Max(%) = {int(self.high_slider.value())}")
        else:
            parts.append(f"Min (I16) = {int(low_val_i16)}")
            parts.append(f"Max (I16) = {int(high_val_i16)}")

        parts.append(f"Mode = {self._human_mode_name()}")

        if self.contrast_mode == "he":
            parts.append(f"HE bins = {int(self.he_bins_spin.value())}")

        elif self.contrast_mode == "clahe":
            parts.append(f"HE bins = {int(self.he_bins_spin.value())}")
            parts.append(f"CLAHE clip = {float(self.clahe_clip_spin.value()):.3f}")

        elif self.contrast_mode == "wallis":
            parts.append(f"Wallis average={int(self.wallis_mu_spin.value())}")
            parts.append(f"standard deviation={int(self.wallis_sigma_spin.value())}")
            parts.append(f"win_size={int(self.wallis_win_spin.value())}")

        elif self.contrast_mode == "canny":
            parts.append(f"Canny sigma={float(self.canny_sigma_spin.value()):.1f}")
            parts.append(f"low={float(self.canny_low_spin.value()):.2f}")
            parts.append(f"high={float(self.canny_high_spin.value()):.2f}")

        elif self.contrast_mode == "highpass":
            parts.append(f"HP_sigma={float(self.hp_sigma_spin.value()):.1f}")
        elif self.contrast_mode == "sharpen":
            parts.append(f"Sharpen_Amt={float(self.sh_amt_spin.value()):.1f}")
            parts.append(f"Sharpen_Rad={float(self.sh_rad_spin.value()):.1f}")

        if self.chk_threshold.isChecked():
            txt = self.thr_mode_combo.currentText()
            if txt.startswith("%"):
                parts.append(f"Binarize(%) = {int(self.thr_spin.value())}")
            else:
                parts.append(f"Binarize (I16) = {int(self.thr_spin.value())}")
            parts.append(f"Binarize invert = {1 if self.chk_threshold_invert.isChecked() else 0}")

        return " | ".join(parts)

    def get_last_transform_spec(self) -> str:
        return self._last_transform_spec

    def _human_mode_name(self) -> str:
        mapping = {
            "linear": "Lineaire",
            "gamma05": "Gamma 0.5",
            "gamma20": "Gamma 2.0",
            "sigmoid": "Sigmoide",
            "log": "Logarithmique",
            "invlog": "Inverse-Log",
            "exp": "Exponentielle",
            "sqrt": "Racine carree",
            "cbrt": "Racine cubique",
            "he": "HE (global)",
            "clahe": "CLAHE",
            "wallis": "Wallis",
            "canny": "Canny (edges)",
            "gradx": "Gradient Horizontal",
            "grady": "Gradient Vertical",
            "sobel": "Sobel",
        }
        return mapping.get(self.contrast_mode, self.contrast_mode)

    def _update_info_panel(self, low_val_i16: int, high_val_i16: int):
        spec = self.build_transform_spec_from_ui(low_val_i16, high_val_i16)
        self._last_transform_spec = spec
        self.info_edit.setText('"' + spec + '"')

    def _resolve_inputs(self, input_path):
        path = os.path.abspath(input_path)
        if os.path.isdir(path):
            folder = path
            start_file = None
        else:
            folder = os.path.dirname(path) if os.path.dirname(path) else "."
            start_file = os.path.basename(path)

        exts = {".tif", ".tiff"}
        files = [f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in exts]
        files.sort(key=lambda x: x.lower())

        if not files:
            QtWidgets.QMessageBox.critical(None, "Erreur", f"Aucune image .tif/.tiff dans :\n{folder}")
            sys.exit(1)

        self.files = [os.path.join(folder, f) for f in files]

        if start_file:
            try:
                self.idx = files.index(start_file)
            except ValueError:
                self.idx = 0
        else:
            self.idx = 0

    def _load_current_image(self):
        path = self.files[self.idx]
        self._load_image_from_path(path)
        self.view.resetTransform()
        self.update_view()
        self._update_name_label()

    def _load_image_from_path(self, path):
        arr = tiff.imread(path)
        if arr.ndim == 3:
            arr = arr[..., 0]
        if arr.dtype != np.uint16:
            arr = arr.astype(np.uint16, copy=False)
        self.arr16 = np.ascontiguousarray(arr)
        self.h, self.w = self.arr16.shape

        self.hist = hist_uint16(self.arr16)
        self.total_px = int(self.arr16.size)
        self.min_val = int(self.arr16.min())
        self.max_val = int(self.arr16.max())

        self.scene.setSceneRect(0, 0, self.w, self.h)
        self.view.set_image_size(self.w, self.h)

    def _update_name_label(self):
        self.name_label.setText(os.path.basename(self.files[self.idx]))

    def set_contrast_mode(self, mode: str):
        self.contrast_mode = mode
        self.update_view()

    def compute_low_high_values_i16(self) -> Tuple[int, int]:
        low_p, high_p = int(self.low_slider.value()), int(self.high_slider.value())
        if high_p <= low_p:
            high_p = min(low_p + 1, 100)
            for w, val in ((self.high_slider, high_p), (self.high_spin, high_p)):
                w.blockSignals(True)
                w.setValue(val)
                w.blockSignals(False)

        lv = percentile_from_hist(self.hist, self.total_px, low_p)
        hv = percentile_from_hist(self.hist, self.total_px, high_p)
        if hv <= lv:
            hv = min(lv + 1, 65535)
        return int(lv), int(hv)

    @staticmethod
    def apply_curve_pointwise(t: np.ndarray, mode: str) -> np.ndarray:
        if mode == "linear":
            y = t
        elif mode == "gamma05":
            y = np.power(t, 0.5, dtype=np.float32)
        elif mode == "gamma20":
            y = np.power(t, 2.0, dtype=np.float32)
        elif mode == "sigmoid":
            gain = 10.0
            y = 1.0 / (1.0 + np.exp(-gain * (t - 0.5)))
            y = (y - y.min()) / max(1e-12, (y.max() - y.min()))
        elif mode == "log":
            c = 100.0
            y = np.log1p(c * t) / np.log1p(c)
        elif mode == "invlog":
            c = 4.0
            y = (np.expm1(c * t) / np.expm1(c)).astype(np.float32)
        elif mode == "exp":
            k = 0.7
            y = np.power(t, k, dtype=np.float32)
        elif mode == "sqrt":
            y = np.sqrt(t, dtype=np.float32)
        elif mode == "cbrt":
            y = np.power(t, 1.0 / 3.0, dtype=np.float32)
        elif mode == "wallis":
            y = wallis_filter(t, win_size=15)
        else:
            y = t
        return np.clip(y, 0.0, 1.0).astype(np.float32)

    def stretch_to_8bit(self, arr16: np.ndarray, lv: int, hv: int) -> np.ndarray:
        mode = self.contrast_mode
        working_arr16 = arr16
        if mode == "highpass":
            working_arr16 = apply_high_pass_filter(arr16, float(self.hp_sigma_spin.value()))
        elif mode == "sharpen":
            working_arr16 = apply_sharpen_filter(arr16,
                                                    amount=float(self.sh_amt_spin.value()),
                                                    radius=float(self.sh_rad_spin.value()))

        rng = float(max(1, hv - lv))
        # On utilise working_arr16 au lieu de arr16
        t = (working_arr16.astype(np.int32) - lv) / rng
        t = np.clip(t, 0.0, 1.0).astype(np.float32)

        if self.chk_threshold.isChecked():
            txt = self.thr_mode_combo.currentText()
            if txt.startswith("%"):
                thr_t = float(self.thr_spin.value()) / 100.0
            else:
                thr_i16 = int(self.thr_spin.value())
                thr_t = (float(thr_i16) - float(lv)) / float(max(1, hv - lv))
            return _binarize_from_t(t, thr_t, invert=self.chk_threshold_invert.isChecked())

        if mode == "gradx":
            return _gradient_x_u8(t)
        if mode == "grady":
            return _gradient_y_u8(t)
        if mode == "sobel":
            return _sobel_mag_u8(t)

        if mode == "he":
            y = he_on_unit_float(t, nbins=int(self.he_bins_spin.value()))
            return np.clip(y * 255.0, 0.0, 255.0).astype(np.uint8)

        if mode == "clahe":
            y = clahe_on_unit_float(
                t,
                clip_limit=float(self.clahe_clip_spin.value()),
                nbins=int(self.he_bins_spin.value()),
            )
            return np.clip(y * 255.0, 0.0, 255.0).astype(np.uint8)

        if mode == "wallis":
            y = wallis_filter(
                t,
                win_size=int(self.wallis_win_spin.value()),
                mu_target=float(self.wallis_mu_spin.value()),
                sigma_target=float(self.wallis_sigma_spin.value()),
            )
            return np.clip(y * 255.0, 0.0, 255.0).astype(np.uint8)

        if mode == "canny":
            if not HAS_SKIMAGE:
                return np.clip(t * 255.0, 0.0, 255.0).astype(np.uint8)
            sigma = float(self.canny_sigma_spin.value())
            low = float(self.canny_low_spin.value())
            high = float(self.canny_high_spin.value())
            if high < low:
                high = low
            edges = sk_feature.canny(
                t,
                sigma=sigma,
                low_threshold=low,
                high_threshold=high,
            )
            return (edges.astype(np.uint8) * 255)
        if mode == "highpass":
            y = apply_high_pass_filter(t, float(self.hp_sigma_spin.value()))
            return np.clip(y * 255.0, 0.0, 255.0).astype(np.uint8)

        if mode == "sharpen":
            y = apply_sharpen_filter(t,
                                     amount=float(self.sh_amt_spin.value()),
                                     radius=float(self.sh_rad_spin.value()))
            return np.clip(y * 255.0, 0.0, 255.0).astype(np.uint8)

        y = self.apply_curve_pointwise(t, mode)
        return np.clip(y * 255.0, 0.0, 255.0).astype(np.uint8)

    def update_view(self):
        low_val_i16, high_val_i16 = self.compute_low_high_values_i16()
        img8 = self.stretch_to_8bit(self.arr16, low_val_i16, high_val_i16)
        self._last_img8 = img8

        qimg = qimage_from_gray_uint8(img8)
        self.pixmap_item.setPixmap(QtGui.QPixmap.fromImage(qimg))

        extra = ""
        if self.contrast_mode in ("clahe", "canny") and not HAS_SKIMAGE:
            extra = " (skimage indisponible)"

        self.setWindowTitle(
            f"TIFF 16 bits – [{low_val_i16} .. {high_val_i16}] – {self.w}x{self.h} – "
            f"Mode: {self.contrast_mode}{extra}"
        )

        self._update_info_panel(low_val_i16, high_val_i16)

    def _on_low_slider(self, val):
        self.low_spin.blockSignals(True)
        self.low_spin.setValue(val)
        self.low_spin.blockSignals(False)
        self.update_view()

    def _on_high_slider(self, val):
        if val <= self.low_slider.value():
            val = min(self.low_slider.value() + 1, 100)
            self.high_slider.blockSignals(True)
            self.high_slider.setValue(val)
            self.high_slider.blockSignals(False)
        self.high_spin.blockSignals(True)
        self.high_spin.setValue(val)
        self.high_spin.blockSignals(False)
        self.update_view()

    def _on_low_spin(self, val):
        self.low_slider.blockSignals(True)
        self.low_slider.setValue(val)
        self.low_slider.blockSignals(False)
        self.update_view()

    def _on_high_spin(self, val):
        if val <= self.low_spin.value():
            val = min(self.low_spin.value() + 1, 100)
            self.high_spin.blockSignals(True)
            self.high_spin.setValue(val)
            self.high_spin.blockSignals(False)
        self.high_slider.blockSignals(True)
        self.high_slider.setValue(val)
        self.high_slider.blockSignals(False)
        self.update_view()

    def _on_mouse_moved(self, col: int, row: int):
        if col < 0 or row < 0:
            self.col_edit.setText("")
            self.row_edit.setText("")
            self.val_edit.setText("")
            return

        self.col_edit.setText(str(col))
        self.row_edit.setText(str(row))

        try:
            v16 = int(self.arr16[row, col])
        except Exception:
            v16 = None

        v8 = None
        if self._last_img8 is not None:
            try:
                v8 = int(self._last_img8[row, col])
            except Exception:
                v8 = None

        if v16 is None:
            self.val_edit.setText("")
        else:
            self.val_edit.setText(f"{v16}" + (f" \u2192 {v8}" if v8 is not None else ""))

    def apply_auto(self):
        self.low_slider.setValue(2)
        self.high_slider.setValue(98)
        self.update_view()

    def apply_full(self):
        self.low_slider.setValue(0)
        self.high_slider.setValue(100)
        self.update_view()

    def reset_view(self):
        self.view.resetTransform()
        self.update_view()


def view_tiff_qt(input_path, parent=None):
    app = QtWidgets.QApplication.instance()
    owns_app = False
    if app is None:
        app = QtWidgets.QApplication(sys.argv[:1])
        owns_app = True

    w = Tiff16Viewer(input_path, parent=parent)
    w.resize(1200, 950)
    w.show()

    if owns_app:
        sys.exit(app.exec())

    return w


# -------------------------------
# Spec parsing / processing
# -------------------------------
def _normalize_mode_name(s: str) -> str:
    """Mappe un libellé humain -> code interne du viewer."""
    s0 = (s or "").strip().lower()
    s0 = (s0
          .replace("é", "e").replace("è", "e").replace("ê", "e")
          .replace("ï", "i").replace("î", "i")
          .replace("ô", "o").replace("ö", "o").replace("à", "a")
          .replace("ç", "c"))
    s0 = re.sub(r"\s+", " ", s0)

    aliases = {
        "lineaire": "linear",
        "linear": "linear",
        "gamma 0.5": "gamma05",
        "gamma0.5": "gamma05",
        "gamma 2.0": "gamma20",
        "gamma2.0": "gamma20",
        "sigmoide": "sigmoid",
        "sigmoid": "sigmoid",
        "logarithmique": "log",
        "log": "log",
        "inverse-log": "invlog",
        "inverse log": "invlog",
        "exponentielle": "exp",
        "exp": "exp",
        "racine carree": "sqrt",
        "sqrt": "sqrt",
        "racine cubique": "cbrt",
        "cbrt": "cbrt",
        "he (global)": "he",
        "he": "he",
        "clahe": "clahe",
        "wallis": "wallis",
        "canny": "canny",
        "canny (edges)": "canny",
        "canny edges": "canny",
        "gradient horizontal": "gradx",
        "grad x": "gradx",
        "gradx": "gradx",
        "gradient vertical": "grady",
        "grad y": "grady",
        "grady": "grady",
        "sobel": "sobel",
    }
    return aliases.get(s0, s0)


def _parse_transform_spec(spec: str) -> Dict[str, Any]:
    """
    Supporte:
      - Transform | Min (I16) = ... | Max (I16) = ... | Mode = ...
      - Transform | Min(%) = ... | Max(%) = ... | Mode = ...
    + params optionnels:
      HE bins = N
      CLAHE clip = x.xxx
      Wallis average=127 | standard deviation=35 | win_size=15
      Canny sigma=1.2 | low=0.08 | high=0.20

    AJOUT:
      Binarize(%) = N
      Binarize (I16) = V
      Binarize invert = 0/1
    """
    if not isinstance(spec, str):
        raise ValueError("transform_spec doit être une chaîne.")
    raw = spec.strip()

    m_mode = re.search(r"Mode\s*=\s*([^\|]+)", raw, re.I)
    if not m_mode:
        raise ValueError("Chaîne invalide : impossible d'extraire Mode.")
    mode_human = m_mode.group(1).strip()
    mode = _normalize_mode_name(mode_human)

    m_min_i16 = re.search(r"Min\s*\(I16\)\s*=\s*(\d+)", raw, re.I)
    m_max_i16 = re.search(r"Max\s*\(I16\)\s*=\s*(\d+)", raw, re.I)

    m_min_p = re.search(r"Min\s*\(%\)\s*=\s*(\d+)", raw, re.I)
    m_max_p = re.search(r"Max\s*\(%\)\s*=\s*(\d+)", raw, re.I)

    is_relative = bool(m_min_p and m_max_p)

    low_val = high_val = None
    low_p = high_p = None

    if is_relative:
        low_p = int(np.clip(int(m_min_p.group(1)), 0, 100))
        high_p = int(np.clip(int(m_max_p.group(1)), 0, 100))
        if high_p <= low_p:
            high_p = min(low_p + 1, 100)
    else:
        if not (m_min_i16 and m_max_i16):
            raise ValueError("Chaîne invalide : impossible d'extraire Min/Max (I16) ou Min/Max (%).")
        low_val = int(np.clip(int(m_min_i16.group(1)), 0, 65535))
        high_val = int(np.clip(int(m_max_i16.group(1)), low_val + 1, 65535))

    he_bins = None
    m_bins = re.search(r"HE\s*bins\s*=\s*(\d+)", raw, re.I)
    if m_bins:
        he_bins = int(m_bins.group(1))

    clahe_clip = None
    m_clip = re.search(r"CLAHE\s*clip\s*=\s*([0-9]*\.?[0-9]+)", raw, re.I)
    if m_clip:
        clahe_clip = float(m_clip.group(1))

    m_mu = re.search(r"(?:wallis\s*)?(?:average|mean|mu|moyenne)\s*=\s*([0-9]+(?:\.[0-9]+)?)", raw, re.I)
    m_sigma = re.search(r"(?:wallis\s*)?(?:standard\s*deviation|std|sigma|ecart\s*type)\s*=\s*([0-9]+(?:\.[0-9]+)?)", raw, re.I)
    m_win = re.search(r"(?:wallis\s*)?(?:win(?:_)?size|window(?:_)?size|fenetre|taille\s*fenetre)\s*=\s*(\d+)", raw, re.I)

    wallis_mu = float(m_mu.group(1)) if m_mu else None
    wallis_sigma = float(m_sigma.group(1)) if m_sigma else None
    wallis_win = int(m_win.group(1)) if m_win else None

    m_c_sigma = re.search(r"(?:canny\s*)?(?:sigma|σ)\s*=\s*([0-9]+(?:\.[0-9]+)?)", raw, re.I)
    m_c_low = re.search(r"(?:canny\s*)?low\s*=\s*([0-9]*\.?[0-9]+)", raw, re.I)
    m_c_high = re.search(r"(?:canny\s*)?high\s*=\s*([0-9]*\.?[0-9]+)", raw, re.I)

    canny_sigma = float(m_c_sigma.group(1)) if m_c_sigma else None
    canny_low = float(m_c_low.group(1)) if m_c_low else None
    canny_high = float(m_c_high.group(1)) if m_c_high else None

    m_bin_pct = re.search(r"Binarize\s*\(%\)\s*=\s*(\d+)", raw, re.I)
    m_bin_i16 = re.search(r"Binarize\s*\(I16\)\s*=\s*(\d+)", raw, re.I)
    if not m_bin_i16:
        m_bin_i16 = re.search(r"Binarize\s*\(?\s*I16\s*\)?\s*=\s*(\d+)", raw, re.I)
    m_bin_inv = re.search(r"Binarize\s*invert\s*=\s*([01])", raw, re.I)

    bin_is_percent = bool(m_bin_pct)
    bin_value = None
    if m_bin_pct:
        bin_value = int(np.clip(int(m_bin_pct.group(1)), 0, 100))
    elif m_bin_i16:
        bin_value = int(np.clip(int(m_bin_i16.group(1)), 0, 65535))
    bin_invert = bool(int(m_bin_inv.group(1))) if m_bin_inv else False

    m_hp_sigma = re.search(r"HP_sigma\s*=\s*([0-9]*\.?[0-9]+)", raw, re.I)
    m_sh_amt = re.search(r"Sharpen_Amt\s*=\s*([0-9]*\.?[0-9]+)", raw, re.I)
    m_sh_rad = re.search(r"Sharpen_Rad\s*=\s*([0-9]*\.?[0-9]+)", raw, re.I)

    hp_sigma = float(m_hp_sigma.group(1)) if m_hp_sigma else None
    sharpen_amt = float(m_sh_amt.group(1)) if m_sh_amt else None
    sharpen_rad = float(m_sh_rad.group(1)) if m_sh_rad else None

    return {
        "is_relative": is_relative,
        "low_val": low_val,
        "high_val": high_val,
        "low_p": low_p,
        "high_p": high_p,
        "mode_human": mode_human,
        "mode": mode,
        "he_bins": he_bins,
        "clahe_clip": clahe_clip,
        "wallis_mu": wallis_mu,
        "wallis_sigma": wallis_sigma,
        "wallis_win": wallis_win,
        "canny_sigma": canny_sigma,
        "canny_low": canny_low,
        "canny_high": canny_high,
        "binarize_value": bin_value,
        "binarize_is_percent": bin_is_percent,
        "binarize_invert": bin_invert,
        "hp_sigma": hp_sigma,
        "sharpen_amt": sharpen_amt,
        "sharpen_rad": sharpen_rad,
    }




# -------------------------------
# Draw spec parsing / drawing
# -------------------------------
def _parse_draw_spec(spec: str) -> Dict[str, Any]:
    """
    Supporte:
      Draw | col = 50.0 49.0 | line = 59.0 15.0 | type = cross
      Draw | col = ... | line = ... | type = invcross

    - col: liste de colonnes (float ou int)
    - line: liste de lignes (float ou int)
    - type: cross, invcross, rectangle
    """
    if not isinstance(spec, str):
        raise ValueError("draw_spec must be a string.")

    raw = spec.strip().replace('"', ' ')
    raw = re.sub(r'(?i)Draw\s*\|', ' | Draw | ', raw)

    m_type = re.search(r"\btype\s*=\s*([^\|]+)", raw, flags=re.I)
    if not m_type:
        raise ValueError("Draw spec invalide: champ 'type' manquant.")
    draw_type = m_type.group(1).strip().lower()

    def _extract_list(key: str) -> List[float]:
        matches = re.findall(rf"\b{key}\s*=\s*([^\|]+)", raw, flags=re.I)
        if not matches:
            raise ValueError(f"Draw spec invalide: champ '{key}' manquant.")

        vals = []
        for match in matches:
            s = match.strip().replace(",", " ").replace(";", " ")
            parts = [p for p in re.split(r"\s+", s) if p]
            for p in parts:
                try:
                    vals.append(float(p))
                except Exception:
                    raise ValueError(f"Draw spec: valeur non numérique dans {key}: '{p}'")
        return vals

    cols_f = _extract_list("col")
    lines_f = _extract_list("line")

    if len(cols_f) != len(lines_f):
        raise ValueError("Draw spec: col et line doivent avoir la même longueur.")
    if len(cols_f) == 0:
        raise ValueError("Draw spec: listes col/line vides.")

    if draw_type not in ("cross", "invcross", "rectangle"):
        raise ValueError(f"Draw spec: type non supporté: '{draw_type}'.")
    m_w = re.search(r"\b(?:width|delta[_\s]*col)\s*=\s*(\d+)", raw, flags=re.I)
    m_h = re.search(r"\b(?:height|delta[_\s]*line)\s*=\s*(\d+)", raw, flags=re.I)

    width = int(m_w.group(1)) if m_w else 10
    height = int(m_h.group(1)) if m_h else 10

    cols = [int(np.round(c)) for c in cols_f]
    lines = [int(np.round(l)) for l in lines_f]

    return {"type": draw_type, "cols": cols, "lines": lines, "width": width, "height": height}


def _draw_cross_inplace(arr: np.ndarray, x: int, y: int, radius: int = 3):
    """
    cross: centre BLANC, bras NOIRS
    """
    H, W = int(arr.shape[0]), int(arr.shape[1])

    def _in_bounds(xx: int, yy: int) -> bool:
        return (0 <= xx < W) and (0 <= yy < H)

    is_color = (arr.ndim == 3 and arr.shape[2] in (3, 4))

    if np.issubdtype(arr.dtype, np.integer):
        white = np.iinfo(arr.dtype).max
    else:
        white = 1.0

    pts = [(x, y)]
    for k in range(1, int(radius) + 1):
        pts.extend([(x - k, y), (x + k, y), (x, y - k), (x, y + k)])

    for (xx, yy) in pts:
        if not _in_bounds(xx, yy):
            continue
        is_center = (xx == x and yy == y)

        if not is_color:
            arr[yy, xx] = white if is_center else 0
        else:
            if is_center:
                arr[yy, xx, 0] = white
                arr[yy, xx, 1] = white
                arr[yy, xx, 2] = white
            else:
                arr[yy, xx, 0] = 0
                arr[yy, xx, 1] = 0
                arr[yy, xx, 2] = 0
            # alpha inchangé


def _draw_invcross_inplace(arr: np.ndarray, x: int, y: int, radius: int = 3):
    """
    invcross: centre NOIR, bras BLANCS
    """
    H, W = int(arr.shape[0]), int(arr.shape[1])

    def _in_bounds(xx: int, yy: int) -> bool:
        return (0 <= xx < W) and (0 <= yy < H)

    is_color = (arr.ndim == 3 and arr.shape[2] in (3, 4))

    if np.issubdtype(arr.dtype, np.integer):
        white = np.iinfo(arr.dtype).max
    else:
        white = 1.0

    pts = [(x, y)]
    for k in range(1, int(radius) + 1):
        pts.extend([(x - k, y), (x + k, y), (x, y - k), (x, y + k)])

    for (xx, yy) in pts:
        if not _in_bounds(xx, yy):
            continue
        is_center = (xx == x and yy == y)

        if not is_color:
            arr[yy, xx] = 0 if is_center else white
        else:
            if is_center:
                arr[yy, xx, 0] = 0
                arr[yy, xx, 1] = 0
                arr[yy, xx, 2] = 0
            else:
                arr[yy, xx, 0] = white
                arr[yy, xx, 1] = white
                arr[yy, xx, 2] = white
            # alpha inchangé

def _draw_white_rectangle_inplace(arr: np.ndarray, x: int, y: int, w: int, h: int):
    H, W_img = int(arr.shape[0]), int(arr.shape[1])
    is_color = (arr.ndim == 3 and arr.shape[2] in (3, 4))

    if np.issubdtype(arr.dtype, np.integer):
        white = np.iinfo(arr.dtype).max
    else:
        white = 1.0

    epaisseur = 3

    # 1. Sécurité : on restreint les coordonnées aux dimensions de l'image (clamp)
    # Cela évite que le programme plante si le rectangle dépasse de l'image
    x_min = max(0, x)
    x_max = min(W_img, x + w)
    y_min = max(0, y)
    y_max = min(H, y + h)

    # Si le rectangle est complètement en dehors de l'image, on ne fait rien
    if x_min >= x_max or y_min >= y_max:
        return

    # 2. Calcul des limites intérieures (pour l'épaisseur)
    x_in_min = min(x_max, x_min + epaisseur)
    x_in_max = max(x_min, x_max - epaisseur)
    y_in_min = min(y_max, y_min + epaisseur)
    y_in_max = max(y_min, y_max - epaisseur)

    # 3. On "peint" les 4 blocs (Haut, Bas, Gauche, Droite) directement
    if not is_color:
        arr[y_min:y_in_min, x_min:x_max] = white  # Bande du haut
        arr[y_in_max:y_max, x_min:x_max] = white  # Bande du bas
        arr[y_min:y_max, x_min:x_in_min] = white  # Bande de gauche
        arr[y_min:y_max, x_in_max:x_max] = white  # Bande de droite
    else:
        # Pareil pour la couleur (on applique sur les canaux RGB, on ignore l'alpha)
        arr[y_min:y_in_min, x_min:x_max, :3] = white
        arr[y_in_max:y_max, x_min:x_max, :3] = white
        arr[y_min:y_max, x_min:x_in_min, :3] = white
        arr[y_min:y_max, x_in_max:x_max, :3] = white

def draw_on_image_by_spec(src_path: str, dst_path: str, draw_spec: str, *, radius: int = 3) -> Dict[str, Any]:
    cfg = _parse_draw_spec(draw_spec)

    arr = tiff.imread(src_path)
    if arr.ndim == 3 and arr.shape[-1] == 1:
        arr = arr[..., 0]

    out = np.array(arr, copy=True)

    H, W = int(out.shape[0]), int(out.shape[1])

    for (x, y) in zip(cfg["cols"], cfg["lines"]):
        if cfg["type"] == "invcross":
            _draw_invcross_inplace(out, x=int(x), y=int(y), radius=int(radius))
        elif cfg["type"] == "rectangle":
            _draw_white_rectangle_inplace(out, x=int(x), y=int(y), w=cfg.get("width", 10), h=cfg.get("height", 10))
        else:
            _draw_cross_inplace(out, x=int(x), y=int(y), radius=int(radius))

    photometric = None
    if out.ndim == 2:
        photometric = "minisblack"
    elif out.ndim == 3 and out.shape[2] in (3, 4):
        photometric = "rgb"

    tiff.imwrite(dst_path, out, photometric=photometric)

    return {
        "src": src_path,
        "dst": dst_path,
        "operation": "draw",
        "type": cfg["type"],
        "radius": int(radius),
        "points": [{"col": int(c), "line": int(l)} for c, l in zip(cfg["cols"], cfg["lines"])],
        "input_shape": tuple(arr.shape),
        "output_shape": tuple(out.shape),
        "dtype": str(out.dtype),
        "width": int(W),
        "height": int(H),
    }



def _which_op(spec: str) -> str:
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("Operation spec must be a non-empty string.")
    head = spec.strip().split("|", 1)[0].strip().lower()
    if re.match(r"^transf(?:or|ro)?m", head):
        return "transform"
    if head.startswith("crop"):
        return "crop"
    if head.startswith("convert"):
        return "convert"
    if head.startswith("draw"):
        return "draw"
    raise ValueError(f"Unknown operation type in spec header: '{head}'.")


def _is_Rt_spec(spec: str) -> bool:
    if not isinstance(spec, str):
        return False
    return bool(re.search(r"R\s*=\s*\[\[.*?\]\].*t\s*=\s*\[.*?\]", spec, flags=re.I | re.S))


def process_tiff_spec(src_path: str, dst_path: str, spec: str,
                      default_he_bins: int = 256, default_clahe_clip: float = 0.01) -> Dict[str, Any]:
    if _is_Rt_spec(spec):
        return apply_transform_to_image_file(src_path, dst_path, spec)

    op = _which_op(spec)

    if op == "convert":
        # ---- AJOUT: support "Convert | out = dcm/png/jpg/..." + params PDF/JPEG ----
        cfg = _parse_convert_spec(spec)
        out_ext = cfg.get("out")
        dst_eff = dst_path

        if out_ext:
            out_ext = str(out_ext).lower().lstrip(".")
            base, _old = os.path.splitext(dst_eff)
            dst_eff = base + "." + out_ext

        res = convert_file_to_image_best_effort(
            src_path=src_path,
            dst_path=dst_eff,
            pdf_page_index=int(cfg.get("pdf_page_index", 0)),
            pdf_zoom=float(cfg.get("pdf_zoom", 2.0)),
            jpeg_quality=int(cfg.get("jpeg_quality", 95)),
        )
        res["operation"] = "convert"
        res["dst"] = dst_eff
        return res

    if op == "transform":
        res = transform_tiff16_to_tiff8(
            src_path=src_path,
            dst_path=dst_path,
            transform_spec=spec,
            default_he_bins=default_he_bins,
            default_clahe_clip=default_clahe_clip,
        )
        res["operation"] = "transform"
        return res

    if op == "crop":
        res = crop_tiff_by_spec(src_path=src_path, dst_path=dst_path, crop_spec=spec)
        res["operation"] = "crop"
        return res

    if op == "draw":
        res = draw_on_image_by_spec(src_path=src_path, dst_path=dst_path, draw_spec=spec)
        res["operation"] = "draw"
        return res

    raise ValueError(f"Unsupported operation: {op}")


def transform_tiff16_to_tiff8(src_path: str, dst_path: str, transform_spec: str,
                              default_he_bins: int = 256, default_clahe_clip: float = 0.01) -> Dict[str, Any]:
    """
    Transform conforme viewer.

    IMPORTANT:
    - Si spec contient Min(%) / Max(%), on recalcule lv/hv I16 sur l'image source (à chaque fois).
    """
    cfg = _parse_transform_spec(transform_spec)
    mode = cfg["mode"]

    arr = tiff.imread(src_path)
    if arr.ndim == 3:
        arr = arr[..., 0]
    if arr.dtype != np.uint16:
        arr = arr.astype(np.uint16, copy=False)
    arr16 = np.ascontiguousarray(arr)
    h, w = arr16.shape

    # --- AJOUT: Filtrage 16 bits natif avant calcul Min/Max ---
    if mode == "highpass":
        sigma = cfg.get("hp_sigma") if cfg.get("hp_sigma") is not None else 3.0
        arr16 = apply_high_pass_filter(arr16, sigma=sigma)
    elif mode == "sharpen":
        amt = cfg.get("sharpen_amt") if cfg.get("sharpen_amt") is not None else 1.0
        rad = cfg.get("sharpen_rad") if cfg.get("sharpen_rad") is not None else 1.0
        arr16 = apply_sharpen_filter(arr16, amount=amt, radius=rad)
    # ----------------------------------------------------------

    if cfg.get("is_relative"):
        lv, hv = compute_low_high_from_percentiles(arr16, int(cfg["low_p"]), int(cfg["high_p"]))
    else:
        lv, hv = int(cfg["low_val"]), int(cfg["high_val"])

    he_bins = cfg["he_bins"] if cfg["he_bins"] is not None else int(default_he_bins)
    clahe_clip = cfg["clahe_clip"] if cfg["clahe_clip"] is not None else float(default_clahe_clip)

    rng = float(max(1, hv - lv))
    t = (arr16.astype(np.int32) - lv) / rng
    t = np.clip(t, 0.0, 1.0).astype(np.float32)

    bval = cfg.get("binarize_value", None)
    if bval is not None:
        if cfg.get("binarize_is_percent", False):
            thr_t = float(bval) / 100.0
        else:
            thr_i16 = int(bval)
            thr_t = (float(thr_i16) - float(lv)) / float(max(1, hv - lv))
        out = _binarize_from_t(t, thr_t, invert=bool(cfg.get("binarize_invert", False)))
        tiff.imwrite(dst_path, out, dtype=np.uint8, photometric='minisblack')
        return {
            "src": src_path, "dst": dst_path,
            "height": int(h), "width": int(w),
            "mode": mode,
            "minmax_relative": bool(cfg.get("is_relative")),
            "low_p": _safe_int(cfg.get("low_p")) if cfg.get("is_relative") else None,
            "high_p": _safe_int(cfg.get("high_p")) if cfg.get("is_relative") else None,
            "low_val": int(lv), "high_val": int(hv),
            "binarize_value": _safe_int(bval),
            "binarize_is_percent": bool(cfg.get("binarize_is_percent")),
            "binarize_invert": bool(cfg.get("binarize_invert")),
        }

    if mode == "gradx":
        out = _gradient_x_u8(t)
        tiff.imwrite(dst_path, out, dtype=np.uint8, photometric='minisblack')
        return {"src": src_path, "dst": dst_path, "height": int(h), "width": int(w),
                "mode": mode, "minmax_relative": bool(cfg.get("is_relative")),
                "low_val": int(lv), "high_val": int(hv)}

    if mode == "grady":
        out = _gradient_y_u8(t)
        tiff.imwrite(dst_path, out, dtype=np.uint8, photometric='minisblack')
        return {"src": src_path, "dst": dst_path, "height": int(h), "width": int(w),
                "mode": mode, "minmax_relative": bool(cfg.get("is_relative")),
                "low_val": int(lv), "high_val": int(hv)}

    if mode == "sobel":
        out = _sobel_mag_u8(t)
        tiff.imwrite(dst_path, out, dtype=np.uint8, photometric='minisblack')
        return {"src": src_path, "dst": dst_path, "height": int(h), "width": int(w),
                "mode": mode, "minmax_relative": bool(cfg.get("is_relative")),
                "low_val": int(lv), "high_val": int(hv)}

    if mode == "he":
        y = he_on_unit_float(t, nbins=int(he_bins))
        out = np.clip(y * 255.0, 0.0, 255.0).astype(np.uint8)

    elif mode == "clahe":
        y = clahe_on_unit_float(t, clip_limit=float(clahe_clip), nbins=int(he_bins))
        out = np.clip(y * 255.0, 0.0, 255.0).astype(np.uint8)

    elif mode == "wallis":
        mu_t = cfg.get("wallis_mu") if cfg.get("wallis_mu") is not None else 127.0
        sigma_t = cfg.get("wallis_sigma") if cfg.get("wallis_sigma") is not None else 35.0
        win_sz = cfg.get("wallis_win") if cfg.get("wallis_win") is not None else 15
        y = wallis_filter(t, win_size=int(win_sz), mu_target=float(mu_t), sigma_target=float(sigma_t))
        out = np.clip(y * 255.0, 0.0, 255.0).astype(np.uint8)

    elif mode == "canny":
        if not HAS_SKIMAGE:
            raise RuntimeError("Mode Canny demandé, mais scikit-image est indisponible.")
        sigma = cfg.get("canny_sigma") if cfg.get("canny_sigma") is not None else 1.2
        low = cfg.get("canny_low") if cfg.get("canny_low") is not None else 0.08
        high = cfg.get("canny_high") if cfg.get("canny_high") is not None else 0.20
        if high < low:
            high = low
        edges = sk_feature.canny(t, sigma=float(sigma), low_threshold=float(low), high_threshold=float(high))
        out = (edges.astype(np.uint8) * 255)

    else:
        y = Tiff16Viewer.apply_curve_pointwise(t, mode)
        out = np.clip(y * 255.0, 0.0, 255.0).astype(np.uint8)

    tiff.imwrite(dst_path, out, dtype=np.uint8, photometric='minisblack')

    return {
        "src": src_path,
        "dst": dst_path,
        "height": int(h),
        "width": int(w),
        "mode": mode,
        "minmax_relative": bool(cfg.get("is_relative")),
        "low_p": _safe_int(cfg.get("low_p")) if cfg.get("is_relative") else None,
        "high_p": _safe_int(cfg.get("high_p")) if cfg.get("is_relative") else None,
        "low_val": int(lv),
        "high_val": int(hv),
        "he_bins": int(he_bins) if mode in ("he", "clahe") else None,
        "clahe_clip": float(clahe_clip) if mode == "clahe" else None,
        "wallis_mu": _safe_float(cfg.get("wallis_mu")) if mode == "wallis" else None,
        "wallis_sigma": _safe_float(cfg.get("wallis_sigma")) if mode == "wallis" else None,
        "wallis_win": _safe_int(cfg.get("wallis_win")) if mode == "wallis" else None,
        "canny_sigma": _safe_float(cfg.get("canny_sigma")) if mode == "canny" else None,
        "canny_low": _safe_float(cfg.get("canny_low")) if mode == "canny" else None,
        "canny_high": _safe_float(cfg.get("canny_high")) if mode == "canny" else None,
        "binarize_value": _safe_int(cfg.get("binarize_value")),
        "binarize_is_percent": bool(cfg.get("binarize_is_percent")) if cfg.get("binarize_value") is not None else None,
        "binarize_invert": bool(cfg.get("binarize_invert")) if cfg.get("binarize_value") is not None else None,
    }


# -------------------------------
# Batch helpers
# -------------------------------
def batch_process_tiff_folder(
    input_dir: str,
    output_dir: str,
    spec: str,
    default_he_bins: int = 256,
    default_clahe_clip: float = 0.01,
) -> Dict[str, Any]:
    if not os.path.isdir(input_dir):
        raise ValueError(f"Input directory does not exist or is not a directory: {input_dir}")

    os.makedirs(output_dir, exist_ok=True)

    exts = {".tif", ".tiff"}
    names = sorted(
        [n for n in os.listdir(input_dir) if os.path.splitext(n)[1].lower() in exts],
        key=lambda s: s.lower()
    )

    # ---- AJOUT: si Convert | out = dcm (ou autre), forcer extension de sortie en batch ----
    convert_cfg = None
    try:
        if isinstance(spec, str) and spec.strip().lower().startswith("convert"):
            convert_cfg = _parse_convert_spec(spec)
    except Exception:
        convert_cfg = None
    force_out_ext = None
    if convert_cfg and convert_cfg.get("out"):
        force_out_ext = str(convert_cfg["out"]).lower().lstrip(".")

    results: List[Dict[str, Any]] = []
    processed = 0
    failed = 0

    for idx, name in enumerate(names):
        src = os.path.join(input_dir, name)

        if force_out_ext:
            base = os.path.splitext(name)[0]
            dst_name = base + "." + force_out_ext
        else:
            dst_name = name

        dst = os.path.join(output_dir, dst_name)

        print("process", idx + 1, "/", len(names))
        try:
            info = process_tiff_spec(
                src_path=src,
                dst_path=dst,
                spec=spec,
                default_he_bins=default_he_bins,
                default_clahe_clip=default_clahe_clip,
            )
            info.update({"src": src, "dst": dst, "ok": True})
            results.append(info)
            processed += 1
        except Exception as e:
            print(str(e))
            results.append({"src": src, "dst": dst, "ok": False, "error": str(e)})
            failed += 1

    return {
        "input_dir": os.path.abspath(input_dir),
        "output_dir": os.path.abspath(output_dir),
        "spec": spec,
        "total": len(names),
        "processed": processed,
        "failed": failed,
        "results": results,
    }


def batch_process_tiff_files(
    input_files: List[str],
    output_files: List[str],
    spec: List[str],
    progress_callback=None,
    argself=None
) -> Dict[str, Any]:
    default_he_bins = 256
    default_clahe_clip = 0.01

    if len(input_files) != len(output_files):
        raise ValueError("input_files and output_files must have the same length.")

    results: List[Dict[str, Any]] = []
    processed = 0
    failed = 0

    total = len(input_files)
    for idx, (src, dst) in enumerate(zip(input_files, output_files), start=0):
        print(f"process {idx + 1}/{total}")

        if progress_callback is not None:
            progress_value = float(100 * (idx + 1) / total)
            progress_callback(progress_value)

        if argself is not None and getattr(argself, "stop", False):
            break

        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        if os.path.exists(dst) and not str(spec[idx]).strip().lower().startswith("convert"):
            os.remove(dst)
        try:
            info = process_tiff_spec(
                src_path=src,
                dst_path=dst,
                spec=spec[idx],
                default_he_bins=default_he_bins,
                default_clahe_clip=default_clahe_clip,
            )
            if isinstance(info, str):
                results.append({"src": src, "dst": dst, "ok": True})
            else:
                info.update({"src": src, "dst": dst, "ok": True})
                results.append(info)
            processed += 1
        except Exception as e:
            print("error batch_process_tiff_files", e)
            results.append({"src": src, "dst": dst, "ok": False, "error": str(e)})
            failed += 1

    return {
        "spec": spec,
        "total": total,
        "processed": processed,
        "failed": failed,
        "results": results,
    }


def convert_file_to_image_best_effort(
    src_path: str,
    dst_path: str,
    *,
    pdf_page_index: int = 0,
    pdf_zoom: float = 2.0,
    jpeg_quality: int = 95,
) -> dict:
    """
    Convertit au mieux un fichier d'entrée (image classique ou PDF 1 page) vers une image.

    Support:
      - Images: tif/tiff/png/jpg/jpeg/bmp/webp/heic/heif/... via Pillow si dispo
               + fallback tifffile pour certains TIFF.
               dcm (dicom) seulement en lecture
      - PDF: rendu via PyMuPDF (fitz), refuse si plus d'1 page.

    Note HEIF/HEIC:
      - Pillow peut les ouvrir si le plugin pillow_heif est installé (tu l'as dans tes deps).
      - Ici on enregistre un hook best-effort: si pillow_heif est présent, il s'active.
    """
    import os
    import numpy as np
    import tifffile as tiff  # AJOUT: évite UnboundLocalError (import local plus bas)
    src_path = src_path.replace("\\", "/")
    dst_path = dst_path.replace("\\", "/")

    in_path = os.path.abspath(src_path)
    out_path = os.path.abspath(dst_path)

    if not os.path.isfile(in_path):
        raise FileNotFoundError(in_path)

    if Path(out_path).exists():
        raise FileExistsError(f"Output already exists, not overwriting: {out_path}")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    ext_in = os.path.splitext(in_path)[1].lower()
    ext_out = os.path.splitext(out_path)[1].lower().lstrip(".")
    if ext_out not in ("png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp", "dcm"):
        raise ValueError(f"Extension de sortie non supportée: .{ext_out}")

    # ---------- PDF -> image ----------
    if ext_in == ".pdf":
        import fitz  # PyMuPDF
        from PIL import Image

        doc = fitz.open(in_path)
        try:
            page_count = doc.page_count
            if page_count != 1:
                raise ValueError(f"PDF multi-pages ({page_count} pages) non supporté (attendu: 1 page).")

            page = doc.load_page(int(pdf_page_index))
            mat = fitz.Matrix(float(pdf_zoom), float(pdf_zoom))

            pix = page.get_pixmap(matrix=mat, alpha=True)

            w, h = pix.width, pix.height
            n = pix.n
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape((h, w, n))

            if n == 4:
                im_rgba = Image.fromarray(arr, mode="RGBA")
                bg = Image.new("RGB", im_rgba.size, (255, 255, 255))
                bg.paste(im_rgba, mask=im_rgba.getchannel("A"))
                im = bg
            elif n == 3:
                im = Image.fromarray(arr, mode="RGB")
            else:
                im_l = Image.fromarray(arr[..., 0], mode="L")
                im = im_l.convert("RGB")

            if ext_out in ("jpg", "jpeg"):
                im.save(out_path, format="JPEG", quality=int(jpeg_quality), optimize=True)
            else:
                im.save(out_path)

            return {
                "ok": True,
                "input": in_path,
                "output": out_path,
                "input_type": "pdf",
                "pages": page_count,
                "page_index": int(pdf_page_index),
                "pdf_zoom": float(pdf_zoom),
                "output_format": ext_out,
                "width": int(im.size[0]),
                "height": int(im.size[1]),
                "mode": im.mode,
                "alpha_flattened_on_white": True,
            }
        finally:
            doc.close()

    # ---------- AJOUT: TIFF -> DICOM (.dcm) ----------
    if ext_in in (".tif", ".tiff") and ext_out == "dcm":
        try:
            from pydicom.dataset import Dataset, FileMetaDataset
            from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid
        except Exception as e_imp:
            raise RuntimeError(f"Sortie .dcm demandée, mais pydicom indisponible: {e_imp}") from e_imp

        arr = tiff.imread(in_path)
        if arr.ndim == 3:
            if arr.shape[-1] == 1:
                arr = arr[..., 0]
            else:
                arr = arr[..., 0]
        if arr.ndim != 2:
            raise RuntimeError(f"TIFF->DCM: forme non supportée (attendu 2D): {arr.shape}")

        if arr.dtype != np.uint16:
            if np.issubdtype(arr.dtype, np.floating):
                a = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
                mn = float(a.min()) if a.size else 0.0
                mx = float(a.max()) if a.size else 1.0
                if mx <= mn:
                    mx = mn + 1.0
                a = (a - mn) * (65535.0 / (mx - mn))
                arr = np.clip(a, 0.0, 65535.0).astype(np.uint16)
            else:
                arr = arr.astype(np.uint16, copy=False)

        arr = np.ascontiguousarray(arr)

        file_meta = FileMetaDataset()
        file_meta.FileMetaInformationVersion = b"\x00\x01"
        file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.ImplementationClassUID = generate_uid()

        ds = Dataset()
        ds.file_meta = file_meta
        ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID

        ds.PatientName = "ANON"
        ds.PatientID = "ANON"
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.Modality = "OT"
        ds.InstanceNumber = 1

        ds.Rows = int(arr.shape[0])
        ds.Columns = int(arr.shape[1])
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME1"
        ds.PixelRepresentation = 0

        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PlanarConfiguration = 0

        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.PixelData = arr.tobytes()

        ds.save_as(out_path, write_like_original=False)

        return {
            "ok": True,
            "input": in_path,
            "output": out_path,
            "input_type": "tiff",
            "output_format": "dcm",
            "width": int(arr.shape[1]),
            "height": int(arr.shape[0]),
            "dtype": str(arr.dtype),
            "via": "tifffile->pydicom",
        }

    # ---------- DICOM (.dcm) -> image ----------
    if ext_in in (".dcm", ".dicom"):
        import numpy as np

        ds = pydicom.dcmread(in_path, force=True)

        try:
            arr = ds.pixel_array
        except Exception as e_px:
            raise RuntimeError(
                f"Lecture DICOM OK, mais impossible de décoder PixelData (codec manquant?) : {e_px}"
            ) from e_px

        if arr.ndim == 3:
            arr = arr[0]
        elif arr.ndim != 2:
            raise RuntimeError(f"DICOM: forme non supportée: {arr.shape}")

        photo = str(getattr(ds, "PhotometricInterpretation", "")).upper()

        if ext_out == "dcm":
            ds2 = ds.copy()

            if arr.dtype == np.int16:
                ds2.PixelRepresentation = 1
            else:
                ds2.PixelRepresentation = 0
                if arr.dtype != np.uint16:
                    arr = arr.astype(np.uint16)

            ds2.BitsAllocated = 16
            ds2.BitsStored = 16
            ds2.HighBit = 15
            ds2.SamplesPerPixel = 1
            ds2.PhotometricInterpretation = "MONOCHROME2"

            ds2.Rows, ds2.Columns = int(arr.shape[0]), int(arr.shape[1])
            ds2.PixelData = arr.tobytes()

            try:
                from pydicom.uid import ExplicitVRLittleEndian
                ds2.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                ds2.is_implicit_VR = False
                ds2.is_little_endian = True
            except Exception:
                pass

            ds2.save_as(out_path, write_like_original=False)

            return {
                "ok": True,
                "input": in_path,
                "output": out_path,
                "input_type": "dicom",
                "output_format": "dcm",
                "width": int(arr.shape[1]),
                "height": int(arr.shape[0]),
                "dtype": str(arr.dtype),
                "photometric_in": photo or None,
                "via": "pydicom",
            }

        if ext_out not in ("tif", "tiff"):
            raise RuntimeError("ecriture autorisée depuis dcm : seulement le tif!!!")

        import tifffile as tiff

        if np.issubdtype(arr.dtype, np.integer):
            info = np.iinfo(arr.dtype)
            arr = info.max - arr
        else:
            arr = arr.max() - arr

        if arr.dtype == np.int16:
            pass
        elif arr.dtype != np.uint16:
            arr = arr.astype(np.uint16)

        tiff.imwrite(out_path, arr)

        return {
            "ok": True,
            "input": in_path,
            "output": out_path,
            "input_type": "dicom",
            "output_format": ext_out,
            "width": int(arr.shape[1]),
            "height": int(arr.shape[0]),
            "dtype": str(arr.dtype),
            "photometric_in": photo or None,
            "via": "pydicom->tifffile",
            "note": "TIFF 16 bits inversé (blanc <-> noir).",
        }

    # ---------- Image -> image ----------
    try:
        import pillow_heif  # noqa: F401
        try:
            pillow_heif.register_heif_opener()
        except Exception:
            pass
    except Exception:
        pass

    try:
        from PIL import Image

        with Image.open(in_path) as im:
            try:
                im.seek(0)
            except Exception:
                pass

            if ext_out in ("jpg", "jpeg"):
                im2 = im.convert("RGB")
                im2.save(out_path, format="JPEG", quality=int(jpeg_quality), optimize=True)
                out_im = im2
            else:
                im.save(out_path)
                out_im = im

            return {
                "ok": True,
                "input": in_path,
                "output": out_path,
                "input_type": "image",
                "input_ext": ext_in,
                "output_format": ext_out,
                "width": int(out_im.size[0]),
                "height": int(out_im.size[1]),
                "mode": str(out_im.mode),
                "via": "Pillow",
            }

    except Exception as e_pil:
        if ext_in not in (".tif", ".tiff"):
            raise RuntimeError(f"Impossible d'ouvrir l'image via Pillow: {e_pil}") from e_pil

        import tifffile as tiff
        arr = tiff.imread(in_path)

        if arr.ndim >= 3 and arr.shape[0] in (3, 4) and arr.dtype == np.uint8:
            arr = np.moveaxis(arr, 0, -1)

        if arr.ndim == 3 and arr.shape[-1] not in (3, 4):
            arr = arr[..., 0]

        if arr.dtype == np.uint16:
            mn = int(arr.min())
            mx = int(arr.max())
            if mx <= mn:
                mx = mn + 1
            arr8 = ((arr.astype(np.float32) - mn) * (255.0 / (mx - mn))).clip(0, 255).astype(np.uint8)
            arr = arr8
        elif arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)

        from PIL import Image
        if arr.ndim == 2:
            im = Image.fromarray(arr, mode="L")
        elif arr.ndim == 3 and arr.shape[-1] == 3:
            im = Image.fromarray(arr, mode="RGB")
        elif arr.ndim == 3 and arr.shape[-1] == 4:
            im = Image.fromarray(arr, mode="RGBA")
        else:
            raise RuntimeError(f"TIFF fallback: forme non supportée: {arr.shape}, dtype={arr.dtype}")

        if ext_out in ("jpg", "jpeg"):
            im = im.convert("RGB")
            im.save(out_path, format="JPEG", quality=int(jpeg_quality), optimize=True)
        else:
            im.save(out_path)

        return {
            "ok": True,
            "input": in_path,
            "output": out_path,
            "input_type": "image",
            "input_ext": ext_in,
            "output_format": ext_out,
            "width": int(im.size[0]),
            "height": int(im.size[1]),
            "mode": im.mode,
            "via": "tifffile->Pillow",
            "note": "Fallback tifffile utilisé (Pillow a échoué).",
        }



# ============================================================
# AJOUT UNIQUEMENT : support
# Crop | col = ... | line = ... | delta_line = ... | delta_col = ... | type = center
# À COLLER EN FIN DE FICHIER, sans rien modifier d'autre.
# ============================================================

def _extract_number_list_from_spec(spec: str, key: str) -> List[float]:
    matches = re.findall(rf"\b{key}\s*=\s*([^\|]+)", spec, flags=re.I)
    if not matches:
        return []

    vals = []
    for m in matches:
        s = m.strip().replace(",", " ").replace(";", " ")
        parts = [p for p in re.split(r"\s+", s) if p]
        for p in parts:
            try:
                vals.append(float(p))
            except Exception:
                raise ValueError(f"Valeur non numérique dans {key}: '{p}'")
    return vals


def _build_indexed_output_path(dst_path: str, index_1based: int) -> str:
    base, ext = os.path.splitext(dst_path)
    return f"{base}_{index_1based:04d}{ext}"


def _compute_center_crop_window(
    H: int,
    W: int,
    center_col: float,
    center_line: float,
    delta_col: int,
    delta_line: int,
) -> Tuple[int, int, int, int]:
    """
    Retourne une fenêtre de taille fixe:
      largeur  = delta_col
      hauteur  = delta_line

    centrée au mieux sur (center_col, center_line), puis décalée si nécessaire
    pour rester entièrement dans l'image, SANS changer la taille.
    """
    if delta_col <= 0 or delta_line <= 0:
        raise ValueError("delta_col et delta_line doivent être > 0.")

    if delta_col > W or delta_line > H:
        raise ValueError(
            f"Crop center impossible sans padding: taille demandée "
            f"({delta_col}, {delta_line}) > taille image ({W}, {H})."
        )

    x0 = int(np.round(float(center_col) - (delta_col - 1) / 2.0))
    y0 = int(np.round(float(center_line) - (delta_line - 1) / 2.0))

    x0 = max(0, min(x0, W - delta_col))
    y0 = max(0, min(y0, H - delta_line))

    x1 = x0 + delta_col
    y1 = y0 + delta_line

    return int(x0), int(y0), int(x1), int(y1)


def _parse_crop_spec(spec: str) -> Dict[str, Any]:
    """
    Version étendue:
    - ancien format:
        Crop | line = 10 | col = 20 | delta_line = 30 | delta_col = 40
    - nouveau format:
        Crop | col = 38 88 | line = 31 31 | delta_line = 33 | delta_col = 35 | type = center
    """
    if not isinstance(spec, str):
        raise ValueError("crop_spec must be a string.")

    raw = spec.strip().replace('"', " ")

    def get_int(pattern):
        m = re.search(pattern, raw, flags=re.I)
        return int(m.group(1)) if m else None

    m_type = re.search(r"\btype\s*=\s*([^\|]+)", raw, flags=re.I)
    crop_type = m_type.group(1).strip().lower() if m_type else "legacy"

    dline = get_int(r"\bdelta[_\s]*line\s*=\s*(\d+)")
    dcol = get_int(r"\bdelta[_\s]*col\s*=\s*(\d+)")

    if dline is None or dcol is None:
        raise ValueError("Invalid crop spec: delta_line and delta_col are required.")

    if dline <= 0 or dcol <= 0:
        raise ValueError("delta_line and delta_col must be positive integers.")

    if crop_type == "center":
        cols_f = _extract_number_list_from_spec(raw, "col")
        lines_f = _extract_number_list_from_spec(raw, "line")

        if not cols_f or not lines_f:
            raise ValueError("Crop center invalide: champs 'col' et 'line' requis.")

        if len(cols_f) != len(lines_f):
            raise ValueError("Crop center invalide: 'col' et 'line' doivent avoir la même longueur.")

        cols = [int(np.round(v)) for v in cols_f]
        lines = [int(np.round(v)) for v in lines_f]

        return {
            "type": "center",
            "cols": cols,
            "lines": lines,
            "delta_line": int(dline),
            "delta_col": int(dcol),
        }

    line = get_int(r"\bline\s*=\s*(-?\d+)")
    col = get_int(r"\bcol\s*=\s*(-?\d+)")

    if line is None or col is None:
        raise ValueError(
            "Invalid crop spec. Expected either legacy crop or center crop."
        )

    return {
        "type": "legacy",
        "line": int(line),
        "col": int(col),
        "delta_line": int(dline),
        "delta_col": int(dcol),
    }


def crop_tiff_by_spec(src_path: str, dst_path: str, crop_spec: str) -> Dict[str, Any]:
    """
    Redéfinition compatible:
    - mode legacy: comportement existant inchangé
    - mode center: plusieurs centres possibles, taille fixe conservée
    """
    arr = tiff.imread(src_path)

    if arr.ndim == 2:
        if arr.dtype not in (np.uint8, np.uint16):
            raise ValueError(f"Unsupported dtype for 2D image: {arr.dtype}")
        fmt = ("mono16" if arr.dtype == np.uint16 else "mono", arr.dtype)
    elif arr.ndim == 3:
        H, W, C = arr.shape
        if arr.dtype == np.uint8 and C in (3, 4):
            fmt = ("rgb" if C == 3 else "rgba", np.uint8)
        elif arr.dtype == np.uint8 and C == 1:
            arr = arr[..., 0]
            fmt = ("mono", np.uint8)
        else:
            raise ValueError(f"Unsupported 3D image shape/dtype: {arr.shape}, {arr.dtype}")
    else:
        raise ValueError(f"Unsupported image ndim: {arr.ndim}")

    H, W = arr.shape[:2]
    cfg = _parse_crop_spec(crop_spec)

    photometric = "minisblack" if fmt[0] in ("mono", "mono16") else "rgb"

    # -------------------------------------------------
    # Mode legacy : comportement d'origine
    # -------------------------------------------------
    if cfg["type"] != "center":
        line = int(cfg["line"])
        col = int(cfg["col"])
        dline = int(cfg["delta_line"])
        dcol = int(cfg["delta_col"])

        y0 = max(0, line)
        x0 = max(0, col)
        y1 = min(H, y0 + dline)
        x1 = min(W, x0 + dcol)

        if y1 <= y0 or x1 <= x0:
            raise ValueError("Crop is empty after clamping to image bounds.")

        roi = np.ascontiguousarray(arr[y0:y1, x0:x1, ...])
        tiff.imwrite(dst_path, roi, photometric=photometric)

        return {
            "src": src_path,
            "dst": dst_path,
            "input_shape": tuple(arr.shape),
            "output_shape": tuple(roi.shape),
            "dtype": str(roi.dtype),
            "crop_type": "legacy",
            "crop_requested": {
                "line": line,
                "col": col,
                "delta_line": dline,
                "delta_col": dcol,
            },
            "crop_effective": {
                "y0": int(y0), "x0": int(x0), "y1": int(y1), "x1": int(x1)
            },
        }

    # -------------------------------------------------
    # Nouveau mode center
    # -------------------------------------------------
    dline = int(cfg["delta_line"])
    dcol = int(cfg["delta_col"])
    cols = cfg["cols"]
    lines = cfg["lines"]

    outputs = []
    single_output = (len(cols) == 1)

    for i, (cx, cy) in enumerate(zip(cols, lines), start=1):
        x0, y0, x1, y1 = _compute_center_crop_window(
            H=H,
            W=W,
            center_col=cx,
            center_line=cy,
            delta_col=dcol,
            delta_line=dline,
        )

        roi = np.ascontiguousarray(arr[y0:y1, x0:x1, ...])

        current_dst = dst_path if single_output else _build_indexed_output_path(dst_path, i)
        tiff.imwrite(current_dst, roi, photometric=photometric)

        eff_center_col = x0 + (dcol - 1) / 2.0
        eff_center_line = y0 + (dline - 1) / 2.0

        outputs.append({
            "dst": current_dst,
            "requested_center": {
                "col": int(cx),
                "line": int(cy),
            },
            "effective_center": {
                "col": float(eff_center_col),
                "line": float(eff_center_line),
            },
            "crop_effective": {
                "y0": int(y0),
                "x0": int(x0),
                "y1": int(y1),
                "x1": int(x1),
            },
            "output_shape": tuple(roi.shape),
        })

    return {
        "src": src_path,
        "dst": dst_path if single_output else None,
        "input_shape": tuple(arr.shape),
        "dtype": str(arr.dtype),
        "crop_type": "center",
        "delta_line": int(dline),
        "delta_col": int(dcol),
        "n_outputs": int(len(outputs)),
        "outputs": outputs,
    }

# ------------------
# Exemples:
#
# Viewer:
# w = view_tiff_qt("C:/img.tif")
# print(w.get_last_transform_spec())
#
# Draw:
# spec = "Draw | col = 50.0 49.0 | line = 59.0 15.0 | type = cross"
# spec = "Draw | col = 50.0 49.0 | line = 59.0 15.0 | type = invcross"
# process_tiff_spec("in.tif", "out_draw.tif", spec)
#
# Convert TIFF->DCM:
# process_tiff_spec("in.tif", "out_any.ext", "Convert | out = dcm")
#
# Batch TIFF folder -> DCM:
# batch_process_tiff_folder("C:/in_folder", "C:/out_folder", "Convert | out = dcm")
