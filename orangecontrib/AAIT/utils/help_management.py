from AnyQt.QtWidgets import QAction
from AnyQt.QtCore import QUrl
from AnyQt.QtGui import QDesktopServices

"""
Pour utiliser cette fonction dans vos widgets : 
    - Il faut rajouter la dernière ligne du __init__ du widget la ligne suivante : 
        QTimer.singleShot(0, lambda: help_management.override_help_action(self, "nom du fichier html"))
"""


def override_help_action(argself):
    help_action = argself.findChild(QAction, "action-help")
    if help_action is None:
        return
    try:
        help_action.triggered.disconnect()
    except Exception:
        pass
    help_action.setEnabled(True)
    help_action.triggered.connect(lambda: open_help(argself.name))


def open_help(name):
    html_filename = name.lower().replace(" ", "_")+".html"
    print(html_filename)
    url = "https://tigerodm.com/public/documentation/dossier_html/"+ html_filename
    QDesktopServices.openUrl(QUrl(url))