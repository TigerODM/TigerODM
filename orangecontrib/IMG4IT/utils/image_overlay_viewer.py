#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys
import numpy as np
import tifffile as tiff

from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont, QCursor
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QVBoxLayout, QWidget
)


# ------------------ Image utils ------------------

def normalize(img: np.ndarray) -> np.ndarray:
    img = img.astype(np.float32)
    img -= float(np.nanmin(img))
    mx = float(np.nanmax(img))
    if mx > 0:
        img /= mx
    return np.clip(img, 0.0, 1.0)


def build_overlay_rgb(img_r: np.ndarray, img_b: np.ndarray, img_g: np.ndarray | None = None) -> np.ndarray:
    def _ensure_2d_first_channel(img: np.ndarray) -> np.ndarray:
        # Si pas 2D: prendre le 1er canal (axe -1)
        if img.ndim != 2:
            if img.size == 0:
                raise ValueError("Image vide.")
            img = np.asarray(img)
            # On prend le canal 0 sur le dernier axe (H,W,C -> H,W)
            img = img[..., 0]
        return img

    def _linear_resample_to_uint8(img: np.ndarray) -> np.ndarray:
        # Si 16-bit ou plus (ou float), remapper linéairement en uint8 0..255
        if img.dtype == np.uint16 or img.dtype == np.int16 or img.dtype == np.uint32 or img.dtype == np.int32 or img.dtype == np.uint64 or img.dtype == np.int64:
            img_f = img.astype(np.float32)
            mn = float(np.nanmin(img_f))
            mx = float(np.nanmax(img_f))
            if not np.isfinite(mn) or not np.isfinite(mx) or mx <= mn:
                return np.zeros_like(img, dtype=np.uint8)
            img_f = (img_f - mn) / (mx - mn)
            return (np.clip(img_f, 0.0, 1.0) * 255.0).astype(np.uint8)

        if img.dtype == np.float16 or img.dtype == np.float32 or img.dtype == np.float64:
            img_f = img.astype(np.float32)
            mn = float(np.nanmin(img_f))
            mx = float(np.nanmax(img_f))
            if not np.isfinite(mn) or not np.isfinite(mx) or mx <= mn:
                return np.zeros_like(img_f, dtype=np.uint8)
            img_f = (img_f - mn) / (mx - mn)
            return (np.clip(img_f, 0.0, 1.0) * 255.0).astype(np.uint8)

        # uint8 / autres: inchangé
        return img

    # --- appliqué à chaque image ---
    img_r = _linear_resample_to_uint8(_ensure_2d_first_channel(img_r))
    img_b = _linear_resample_to_uint8(_ensure_2d_first_channel(img_b))
    if img_g is not None:
        img_g = _linear_resample_to_uint8(_ensure_2d_first_channel(img_g))

    # Vérifs inchangées (mais maintenant on garantit du 2D)
    if img_r.ndim != 2 or img_b.ndim != 2 or (img_g is not None and img_g.ndim != 2):
        raise ValueError("Les images doivent être 2D (grayscale).")
    if img_r.shape != img_b.shape or (img_g is not None and img_g.shape != img_r.shape):
        raise ValueError("Toutes les images doivent avoir la même taille (H, W).")

    r = normalize(img_r)
    b = normalize(img_b)
    g = normalize(img_g) if img_g is not None else np.zeros_like(r)

    rgb = np.zeros((*img_r.shape, 3), dtype=np.float32)
    rgb[..., 0] = r   # Rouge = image1
    rgb[..., 2] = b   # Bleu  = image2
    rgb[..., 1] = g   # Vert  = image3 (option)
    return rgb


def rgb_to_qimage(rgb01: np.ndarray) -> QImage:
    rgb8 = (np.clip(rgb01, 0, 1) * 255).astype(np.uint8)
    h, w, _ = rgb8.shape
    rgb8 = np.ascontiguousarray(rgb8)
    return QImage(rgb8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


# ------------------ Legend ------------------

def make_legend_pixmap(label_r: str, label_b: str, label_g: str | None = None, w: int = 380, h: int = 250) -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(20, 20, 20, 230))
    p.drawRoundedRect(0, 0, w, h, 14, 14)

    p.setPen(QPen(QColor(255, 255, 255), 1))
    p.setFont(QFont("Arial", 12, QFont.Weight.Bold))
    p.drawText(16, 28, "Légende")

    # ✅ Ordre demandé : Rouge, Bleu, Vert(optionnel)
    items = [
        ("Image 1 → Rouge", QColor(220, 40, 40), label_r),
        ("Image 2 → Bleu",  QColor(60, 120, 255), label_b),
    ]
    if label_g is not None:
        items.append(("Image 3 → Vert", QColor(60, 200, 80), label_g))

    y = 50
    for title, color, fname in items:
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(16, y, 18, 18, 4, 4)

        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.setFont(QFont("Arial", 11, QFont.Weight.DemiBold))
        p.drawText(44, y + 14, title)

        p.setPen(QPen(QColor(200, 200, 200), 1))
        p.setFont(QFont("Arial", 9))
        p.drawText(44, y + 34, fname)

        y += 55

    p.end()
    return pm


# ------------------ Zoom/Pan + mouse coords ------------------

class ImageLabel(QLabel):
    mouseMoved = pyqtSignal(int, int)  # row, col
    mouseLeft = pyqtSignal()

    def __init__(self, src_pm: QPixmap, img_w: int, img_h: int):
        super().__init__()
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setStyleSheet("background:#111; border-radius:10px;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._src_pm = src_pm
        self._img_w = img_w
        self._img_h = img_h

        # zoom/pan state in IMAGE coords
        self._zoom = 1.0
        self._min_zoom = 0.2
        self._max_zoom = 50.0
        self._center = QPointF(img_w / 2.0, img_h / 2.0)

        self._dragging = False
        self._last_pos = None

        # computed each rebuild:
        self._crop_rect_img = (0, 0, img_w, img_h)  # left, top, cw, ch
        self._pm_rect_widget = None  # x0,y0,pw,ph

        self._rebuild_view()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rebuild_view()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.mouseLeft.emit()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_pos = e.position()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._last_pos = None
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        # Pan
        if self._dragging and self._last_pos is not None:
            dp = e.position() - self._last_pos
            self._last_pos = e.position()

            # Convert widget delta to image delta using current crop mapping
            # We use displayed pixmap rect so pan speed feels consistent with zoom.
            if self._pm_rect_widget is not None:
                x0, y0, pw, ph = self._pm_rect_widget
                left, top, cw, ch = self._crop_rect_img
                if pw > 0 and ph > 0:
                    dx_img = -dp.x() * (cw / pw)
                    dy_img = -dp.y() * (ch / ph)
                    self._center.setX(self._center.x() + dx_img)
                    self._center.setY(self._center.y() + dy_img)
                    self._clamp_center()
                    self._rebuild_view()

        # Emit coords (even during pan)
        rc = self._widget_to_image_rc(e.position().x(), e.position().y())
        if rc is None:
            self.mouseLeft.emit()
        else:
            self.mouseMoved.emit(rc[0], rc[1])

        super().mouseMoveEvent(e)

    def wheelEvent(self, e):
        angle = e.angleDelta().y()
        if angle == 0:
            return

        factor = 1.15 if angle > 0 else 1 / 1.15

        # Anchor zoom under mouse if possible
        anchor_xy = self._widget_to_image_xy(e.position().x(), e.position().y())

        old_zoom = self._zoom
        self._zoom = float(np.clip(self._zoom * factor, self._min_zoom, self._max_zoom))
        if self._zoom == old_zoom:
            return

        if anchor_xy is not None:
            ax, ay = anchor_xy
            # After zoom, keep anchor point under mouse by adjusting center
            # Compute view sizes in image pixels
            vw_old = self._img_w / old_zoom
            vh_old = self._img_h / old_zoom
            vw_new = self._img_w / self._zoom
            vh_new = self._img_h / self._zoom

            cx, cy = self._center.x(), self._center.y()
            relx = ax - cx
            rely = ay - cy

            sx = vw_new / vw_old
            sy = vh_new / vh_old

            self._center = QPointF(ax - relx * sx, ay - rely * sy)

        self._clamp_center()
        self._rebuild_view()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_R:
            self._zoom = 1.0
            self._center = QPointF(self._img_w / 2.0, self._img_h / 2.0)
            self._rebuild_view()
            return
        super().keyPressEvent(e)

    def _clamp_center(self):
        vw = self._img_w / self._zoom
        vh = self._img_h / self._zoom
        half_w = vw / 2.0
        half_h = vh / 2.0
        cx = float(np.clip(self._center.x(), half_w, self._img_w - half_w))
        cy = float(np.clip(self._center.y(), half_h, self._img_h - half_h))
        self._center = QPointF(cx, cy)

    def _rebuild_view(self):
        vw = max(1, int(round(self._img_w / self._zoom)))
        vh = max(1, int(round(self._img_h / self._zoom)))

        left = int(round(self._center.x() - vw / 2))
        top = int(round(self._center.y() - vh / 2))

        left = max(0, min(left, self._img_w - vw))
        top = max(0, min(top, self._img_h - vh))

        self._crop_rect_img = (left, top, vw, vh)

        view_pm = self._src_pm.copy(left, top, vw, vh)
        scaled = view_pm.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(scaled)

        # rect of pixmap inside the label
        x0 = (self.width() - scaled.width()) // 2
        y0 = (self.height() - scaled.height()) // 2
        self._pm_rect_widget = (x0, y0, scaled.width(), scaled.height())

    def _widget_to_image_xy(self, xw: float, yw: float):
        if self._pm_rect_widget is None:
            return None
        x0, y0, pw, ph = self._pm_rect_widget
        if xw < x0 or yw < y0 or xw >= x0 + pw or yw >= y0 + ph:
            return None

        u = (xw - x0) / pw
        v = (yw - y0) / ph

        left, top, cw, ch = self._crop_rect_img
        xi = left + u * cw
        yi = top + v * ch

        xi = float(np.clip(xi, 0, self._img_w - 1))
        yi = float(np.clip(yi, 0, self._img_h - 1))
        return xi, yi

    def _widget_to_image_rc(self, xw: float, yw: float):
        xy = self._widget_to_image_xy(xw, yw)
        if xy is None:
            return None
        xi, yi = xy
        col = int(xi)
        row = int(yi)
        col = max(0, min(self._img_w - 1, col))
        row = max(0, min(self._img_h - 1, row))
        return row, col

    @property
    def zoom(self) -> float:
        return self._zoom


# ------------------ Main window ------------------

class OverlayViewer(QMainWindow):
    def __init__(self, rgb01: np.ndarray, label_r: str, label_b: str, label_g: str | None = None):
        super().__init__()
        self.setWindowTitle("Overlay RGB (Qt)")
        self.rgb01 = rgb01
        self.label_r = label_r
        self.label_b = label_b
        self.label_g = label_g

        qimg = rgb_to_qimage(self.rgb01)
        src_pm = QPixmap.fromImage(qimg)

        h, w, _ = rgb01.shape
        self.image_label = ImageLabel(src_pm, img_w=w, img_h=h)

        self.legend_label = QLabel()
        self.legend_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.legend_label.setPixmap(make_legend_pixmap(self.label_r, self.label_b, self.label_g))

        self.coord_label = QLabel("Ligne: —  Colonne: —    Zoom: 1.00×   (R: reset)")
        self.coord_label.setStyleSheet("QLabel { color:#EEE; background:#222; padding:6px 10px; border-radius:8px; }")

        self.export_btn = QPushButton("Exporter…")
        self.export_btn.clicked.connect(self.export_png)

        self.image_label.mouseMoved.connect(self.on_mouse_coords)
        self.image_label.mouseLeft.connect(self.on_mouse_leave)

        side = QVBoxLayout()
        side.addWidget(self.legend_label, 0)
        side.addSpacing(10)
        side.addWidget(self.coord_label, 0)
        side.addStretch(1)
        side.addWidget(self.export_btn, 0)

        main = QHBoxLayout()
        main.addWidget(self.image_label, 1)
        main.addLayout(side, 0)

        root = QWidget()
        root.setLayout(main)
        root.setStyleSheet("QWidget { background:#111; }")
        self.setCentralWidget(root)
        self.resize(1350, 800)

    def on_mouse_coords(self, row: int, col: int):
        self.coord_label.setText(f"Ligne: {row}   Colonne: {col}    Zoom: {self.image_label.zoom:.2f}×   (R: reset)")

    def on_mouse_leave(self):
        self.coord_label.setText(f"Ligne: —  Colonne: —    Zoom: {self.image_label.zoom:.2f}×   (R: reset)")

    def export_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer l'overlay", "overlay_rgb.png", "PNG (*.png)")
        if not path:
            return

        img_pm = QPixmap.fromImage(rgb_to_qimage(self.rgb01))
        leg_pm = make_legend_pixmap(self.label_r, self.label_b, self.label_g)

        out = QPixmap(img_pm.width() + leg_pm.width() + 20, max(img_pm.height(), leg_pm.height()))
        out.fill(QColor(15, 15, 15))

        p = QPainter(out)
        p.drawPixmap(0, 0, img_pm)
        p.drawPixmap(img_pm.width() + 20, 0, leg_pm)
        p.end()

        out.save(path, "PNG")
        print(f"✅ Exporté : {path}")


# ------------------ Entry point ------------------

def main():
    parser = argparse.ArgumentParser(description="Overlay TIFF -> Qt viewer (R=image1, B=image2, G=option)")
    parser.add_argument("image1", help="Image TIFF → canal rouge")
    parser.add_argument("image2", help="Image TIFF → canal bleu")
    parser.add_argument("--green", default=None, help="Image TIFF optionnelle → canal vert")
    args = parser.parse_args()

    img_r = tiff.imread(args.image1)
    img_b = tiff.imread(args.image2)
    img_g = tiff.imread(args.green) if args.green else None

    rgb = build_overlay_rgb(img_r, img_b, img_g)

    label_r = os.path.basename(args.image1)
    label_b = os.path.basename(args.image2)
    label_g = os.path.basename(args.green) if args.green else None

    app = QApplication(sys.argv)
    w = OverlayViewer(rgb, label_r, label_b, label_g)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
