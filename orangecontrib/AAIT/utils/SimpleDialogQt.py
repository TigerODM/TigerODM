import sys

from AnyQt.QtWidgets import (QApplication, QDialog, QFileDialog, QLabel,QPushButton,
                             QMessageBox, QVBoxLayout,QSpinBox,QHBoxLayout)


from AnyQt import QtSvg,QtGui
def BoxInfo(text):
    """
    Open A simple info box
    """
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Information)
    msg.setText(text)
    msg.setWindowTitle("Information")
    msg.setStandardButtons(QMessageBox.Ok)
    msg.exec()


def BoxWarning(text):
    """
    Open A simple warning box
    """
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Warning)
    msg.setText(text)
    msg.setWindowTitle("Warning")
    msg.setStandardButtons(QMessageBox.Ok)
    msg.exec()


def BoxError(text):
    """
    Open A simple error box
    """
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Critical)
    msg.setText(text)
    msg.setWindowTitle("Error")
    msg.setStandardButtons(QMessageBox.Ok)
    msg.exec()


def BoxSelectFolder(argself, default_path=None):
    """
    return "" if nothing was selected else the path
    """
    if default_path == None or default_path == "":
        folder = QFileDialog.getExistingDirectory()
    else:
        folder = QFileDialog.getExistingDirectory(argself, caption="Select a folder", directory=default_path)
    return folder.replace("\\", "/")

def BoxSelectExistingFile(argself,default_dir="",extention="All Files (*);;Text Files (*.txt)"):
    """
    return "" if nothing was selected else the path
    """
    try:  # Qt 6
        readonly = QFileDialog.Option.ReadOnly
    except AttributeError:  # Qt 5
        readonly = QFileDialog.ReadOnly

    fileName, _ = QFileDialog.getOpenFileName(
        argself, "Sélectionner un fichier", default_dir,
        options=readonly
    )

    if fileName:
        fileName=fileName.replace("\\", "/")
        return fileName
    else:
        return ""


def BoxYesNo(question):
    """
    return True if Yes is clicked, False in other cases
    """
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Warning)
    msg.setText(question)
    msg.setStandardButtons(QMessageBox.No | QMessageBox.Yes)
    ret = msg.exec()
    if ret == msg.Yes:
        return True
    return False


class ProgressDialog(QDialog):
    """
    to use :
    dialog_progress = ProgressDialog(title="hello",content="blablalblagblal")
    dialog_progress.show()
    # do something
    dialog_progress.stop()
    """
    def __init__(self, title="Title",content="blablabla",parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        layout = QVBoxLayout(self)
        self.label = QLabel(content, self)
        layout.addWidget(self.label)

    def show(self):
        super().show()
        QApplication.processEvents()

    def closeEvent(self, event):
        # ignore click on x
        event.ignore()

    def stop(self):
        self.accept()



def transformboutontools2wrench(bouttontool):
    """
        usage :
        self.bouttontool= self.findChild(QtWidgets.QToolButton, 'toolButton')
        SimpleDialogQt.transformboutontools2wrench(self.bouttontool)

    """
    wrench_svg = b"""<?xml version="1.0" encoding="iso-8859-1"?>
    <svg version="1.1" id="Capa_1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" x="0px" y="0px"
    	 viewBox="0 0 303.848 303.848" style="enable-background:new 0 0 303.848 303.848;" xml:space="preserve">
    <g>
    	<path d="M297.023,52.375l-3.74-8.728l-50.361,50.348h-33.503l0.026-33.49l49.943-50.039l-9.023-3.618
    		c-10.129-4.055-20.739-6.105-31.543-6.105c-46.909,0-85.072,38.156-85.072,85.04c0,9.293,1.53,18.471,4.557,27.327L10.714,240.682
    		C3.798,247.584,0,256.775,0,266.543s3.805,18.953,10.714,25.842c6.896,6.915,16.08,10.72,25.849,10.72s18.946-3.805,25.849-10.72
    		L189.27,165.533c9.467,3.515,19.383,5.296,29.551,5.296c46.884,0,85.027-38.15,85.027-85.046
    		C303.848,74.214,301.553,62.98,297.023,52.375z M218.821,157.975c-9.891,0-19.493-1.986-28.542-5.887l-4.004-1.735L53.323,283.298
    		c-8.965,8.965-24.576,8.965-33.529,0c-4.48-4.467-6.947-10.431-6.947-16.755c0-6.337,2.468-12.288,6.947-16.768l133.492-133.472
    		l-1.555-3.927c-3.406-8.573-5.135-17.526-5.135-26.594c0-39.801,32.404-72.186,72.218-72.186c5.81,0,11.575,0.701,17.198,2.095
    		L196.584,55.19l-0.039,51.665h51.691l40.193-40.181c1.71,6.195,2.558,12.59,2.558,19.113
    		C290.994,125.59,258.622,157.975,218.821,157.975z M46.061,265.689c0,5.135-4.165,9.3-9.3,9.3c-5.141,0-9.306-4.165-9.306-9.3
    		c0-5.148,4.165-9.312,9.306-9.312C41.89,256.376,46.061,260.541,46.061,265.689z"/>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    <g>
    </g>
    </svg>
    """
    renderer = QtSvg.QSvgRenderer(wrench_svg)
    pixmap = QtGui.QPixmap(24, 24)  # pixmal size
    pixmap.fill(QtGui.QColor("transparent"))  # Fond transparent
    painter = QtGui.QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    bouttontool.setIconSize(pixmap.size())  # Ajuste la taille de l'icône
    bouttontool.setFixedSize(pixmap.size())  # Ajuste la taille du bouton
    # Appliquer l'icône au bouton
    bouttontool.setIcon(QtGui.QIcon(pixmap))




class NumberInputDialog(QDialog):
    """
    usage
    selected_value = get_number_from_dialog("select a number between 1 et 100 :", 1, 100)
    print("result :", selected_value)
    """
    def __init__(self, text, value_min, value_max, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select a Number")

        layout = QVBoxLayout(self)

        # Ajout du texte descriptif
        self.label = QLabel(text, self)
        layout.addWidget(self.label)

        # Ajout du spinbox
        self.spinbox = QSpinBox(self)
        self.spinbox.setMinimum(value_min)
        self.spinbox.setMaximum(value_max)
        layout.addWidget(self.spinbox)

        # Boutons OK et Annuler
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK", self)
        self.cancel_button = QPushButton("Cancel", self)

        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        # Connexions des boutons
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def get_value(self):
        return self.spinbox.value()

def get_number_from_dialog(text, value_min, value_max):
    """
    usage
    selected_value = get_number_from_dialog("select a number between 1 et 100 :", 1, 100)
    print("result :", selected_value)
    """
    ## surement fausse alarme de pyflakes
    _ = QApplication(sys.argv) if not QApplication.instance() else QApplication.instance()
    dialog = NumberInputDialog(text, value_min, value_max)
    if dialog.exec():
        return dialog.get_value()
    return None
