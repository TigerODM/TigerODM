from Orange.widgets.widget import OWWidget, Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from AnyQt.QtCore import Qt, QSize
import os
import Orange
import numpy as np
import sys
from pathlib import Path
# importe ton viewer sans le modifier
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IMG4IT.utils.tiff16_viewer import view_tiff_qt
else:
    from orangecontrib.IMG4IT.utils.tiff16_viewer import view_tiff_qt

class OWTiff16Viewer(OWWidget):
    name = "XRAY Viewer"
    description = "Show 16 bit image viewer"
    icon = "icons/viewer_xray_icon.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/viewer_xray_icon.png"
    priority = 10
    want_control_area = False
    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        crop = Output("Crop", Orange.data.Table)
        calibration = Output("Calibration", Orange.data.Table)

    # État persistant de la coche "Couleur d'origine (sans filtre)"
    original_color = Setting(False)

    PLACEHOLDER_MSG = (
        "Aucune image en entrée.\n\n"
        "Connectez une source de données possédant une colonne « image » ou « path ».\n"
        "Formats supportés : tif, tiff, jpg, jpeg, png, bmp."
    )
    PLACEHOLDER_SIZE = QSize(480, 340)

    def __init__(self):
        super().__init__()
        self.data = None
        self.list_image = []
        self.viewer = None
        self._placeholder = None
        # Panneau d'accueil tant qu'aucune image n'est connectée
        self._show_placeholder(self.PLACEHOLDER_MSG)

    # -------------------------------------------------
    # Empêche l'ouverture maximisée quand seul le placeholder est affiché
    # -------------------------------------------------
    def sizeHint(self):
        if getattr(self, "viewer", None) is None:
            return QSize(self.PLACEHOLDER_SIZE)
        return super().sizeHint()

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "viewer", None) is None:
            if self.isMaximized() or self.isFullScreen():
                self.showNormal()
            self.resize(self.PLACEHOLDER_SIZE)

    # -------------------------------------------------
    # Zone principale : viewer ou panneau d'accueil
    # -------------------------------------------------
    def _clear_main_area(self):
        layout = self.mainArea.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    def _make_placeholder(self, message):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon = QLabel("🖼️")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 48px;")

        title = QLabel("XRAY Viewer")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 600; color: #444;")

        msg = QLabel(message)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size: 13px; color: #666;")

        lay.addStretch(1)
        lay.addWidget(icon)
        lay.addWidget(title)
        lay.addSpacing(8)
        lay.addWidget(msg)
        lay.addStretch(1)
        return w

    def _show_placeholder(self, message):
        self._clear_main_area()
        self.viewer = None
        self._placeholder = self._make_placeholder(message)
        self.mainArea.layout().addWidget(self._placeholder)

    @Inputs.data
    def set_data(self, in_data):
        self.error("")
        if in_data is None:
            self.data = None
            self.list_image = []
            self._show_placeholder(self.PLACEHOLDER_MSG)
            return

        self.data = in_data
        self.list_image= []
        self.run()


    def load_list_image_domaine(self,in_data):
        if 0==self.load_list_image_domaine_image(in_data):
            return 0
        if 0==self.load_list_image_domaine_path(in_data):
            return 0
        return 1

    def load_list_image_domaine_image(self,in_data):
        del self.list_image[:]
        try:
            in_data.domain["image"]
        except KeyError:
            return 1

        if type(in_data.domain["image"]).__name__ != 'StringVariable':
            return 1
        try:
            path_directory_of_image=str(in_data.domain["image"].attributes['origin'])
        except Exception:
            return 1

        for element in in_data.get_column("image"):
            self.list_image.append(path_directory_of_image+"/"+str(element))
        return 0
    def load_list_image_domaine_path(self,in_data):
        del self.list_image[:]
        try:
            in_data.domain["path"]
        except KeyError:
            return 1

        if type(in_data.domain["path"]).__name__ != 'StringVariable':
            return 1
        for element in in_data.get_column("path"):
            self.list_image.append(element)
        return 0


    def run(self):
        self.error("")
        if self.data is None:
            self._show_placeholder(self.PLACEHOLDER_MSG)
            return
        if 0!=self.load_list_image_domaine(self.data):
            self.error("input Domain need Image or path Column")
            self._show_placeholder(
                "La table d'entrée doit contenir une colonne « image » ou « path »."
            )
            return
        liste_file=self.list_image

        # Garde uniquement les images supportées (tif/tiff/jpg/jpeg/png/bmp)
        supported = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp")
        tif_files = [
            str(p) for p in liste_file
            if str(Path(p).suffix.lower()) in supported
        ]
        if len(tif_files) == 0:
            self.error('You need at least one supported image (tif/jpg/png/bmp)')
            self._show_placeholder(
                "Aucune image supportée trouvée.\n"
                "Formats acceptés : tif, tiff, jpg, jpeg, png, bmp."
            )
            return

        # Passe toute la liste au viewer : il affiche une image aléatoire
        # et propose un bouton pour en tirer une autre au hasard.
        self.viewer = view_tiff_qt(tif_files, parent=self)

        # Connecte le signal de crop du viewer -> propagation de la sortie
        try:
            self.viewer.cropExported.connect(self._on_crop_exported)
        except Exception:
            pass
        # Connecte le signal de calibration du viewer -> sortie "sizeOfPixel"
        try:
            self.viewer.calibrationExported.connect(self._on_calibration_exported)
        except Exception:
            pass
        # Restaure l'état persistant de la coche "Couleur d'origine (sans filtre)"
        try:
            self.viewer.chk_original_color.setChecked(bool(self.original_color))
            self.viewer.chk_original_color.toggled.connect(self._on_original_color_toggled)
        except Exception:
            pass

        self._clear_main_area()
        self.mainArea.layout().addWidget(self.viewer)

    def _on_original_color_toggled(self, checked):
        """Mémorise l'état de la coche dans les settings du widget."""
        self.original_color = bool(checked)

    def _on_crop_exported(self, cropped_path, ref_path, line, col, delta_line, delta_col):
        """Reçoit le crop, le chemin d'origine et les coordonnées, puis envoie la sortie 'Crop'."""
        self.error("")
        try:
            attrs = [
                Orange.data.ContinuousVariable("line"),
                Orange.data.ContinuousVariable("col"),
                Orange.data.ContinuousVariable("delta_line"),
                Orange.data.ContinuousVariable("delta_col"),
            ]
            path_var = Orange.data.StringVariable("path")
            path_ref_var = Orange.data.StringVariable("path_ref")
            domain = Orange.data.Domain(attrs, metas=[path_var, path_ref_var])

            X = np.array([[float(line), float(col),
                           float(delta_line), float(delta_col)]], dtype=float)
            metas = np.array([[str(cropped_path), str(ref_path)]], dtype=object)

            table = Orange.data.Table.from_numpy(domain, X, metas=metas)
            table.name = "cropped_image"
            self.Outputs.crop.send(table)
        except Exception as e:
            self.error(f"Crop output error: {e}")
            self.Outputs.crop.send(None)

    def _on_calibration_exported(self, ref_path, size_of_pixel, distance,
                                 pixel_length, x0, y0, x1, y1, unit):
        """Reçoit la calibration et envoie une sortie 'Data' avec une colonne sizeOfPixel."""
        self.error("")
        try:
            attrs = [
                Orange.data.ContinuousVariable("sizeOfPixel"),
                Orange.data.ContinuousVariable("distance"),
                Orange.data.ContinuousVariable("pixel_length"),
                Orange.data.ContinuousVariable("x0"),
                Orange.data.ContinuousVariable("y0"),
                Orange.data.ContinuousVariable("x1"),
                Orange.data.ContinuousVariable("y1"),
            ]
            path_ref_var = Orange.data.StringVariable("path_ref")
            unit_var = Orange.data.StringVariable("unit")
            domain = Orange.data.Domain(attrs, metas=[path_ref_var, unit_var])

            X = np.array([[float(size_of_pixel), float(distance), float(pixel_length),
                           float(x0), float(y0), float(x1), float(y1)]], dtype=float)
            metas = np.array([[str(ref_path), str(unit)]], dtype=object)

            table = Orange.data.Table.from_numpy(domain, X, metas=metas)
            table.name = "calibration"
            self.Outputs.calibration.send(table)
        except Exception as e:
            self.error(f"Calibration output error: {e}")
            self.Outputs.calibration.send(None)
if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWTiff16Viewer()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
    # from Orange.widgets.orangecontrib.IMG4IT.utils.tiff16_viewer import transform_tiff16_to_tiff8
    #
    # print("ici")
    # spec = "Transform | Min(I16) = 59221 | Max(I16) = 65535 | Mode = Sigmoide"
    # info = transform_tiff16_to_tiff8(r"C:\Users\jean-\Desktop\pozipokaze\toto.tif", r"C:\Users\jean-\Desktop\pozipokaze\toto_out.tif", spec)
    # print(info)