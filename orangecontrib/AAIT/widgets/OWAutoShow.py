import os
import sys

from AnyQt.QtWidgets import QApplication, QTreeWidgetItem
from Orange.widgets.settings import Setting
from Orange.widgets import widget
from orangecanvas.application.canvasmain import CanvasMainWindow
from collections import defaultdict

from AnyQt.QtGui import QFont, QColor
from AnyQt.QtCore import QTimer, Qt

# On prépare le style pour la colonne de droite
italic_font = QFont()
italic_font.setItalic(True)
italic_font.setPointSize(9) # Optionnel: un poil plus petit pour le nom technique
gray_color = QColor("gray")

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWAutoShow(widget.OWWidget):
    name = "Auto Show (UNSTABLE)"
    description = "This widget allows you to select which widget you want to automatically open when starting a workflow."
    category = "AAIT - TOOLBOX"
    icon = "icons/autoshow.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/autoshow.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owautoshow.ui")
    want_control_area = False
    priority = 1060

    # Settings
    selected_widgets = Setting([])

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(450)
        uic.loadUi(self.gui, self)

        self.thread = None
        self.existing_widgets = None

        # Connect the tree items
        self.treeWidget.itemChanged.connect(self.on_item_checked)

        # Get all existing items
        self.existing_widgets = self.get_existing_widgets()
        # Populate the tree widget
        self.populate_tree()
        # Restore the selection from Setting
        self.select_from_setting()
        # Open selected widgets
        self.show_widgets()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))


    def on_item_checked(self, item, column):
        if column != 0:
            return

        type_widget = item.data(0, Qt.UserRole)
        if type_widget is None:
            return

        # On crée l'entrée avec le nom et la classe
        entry = (item.text(0), type_widget)

        if item.checkState(0) == Qt.Checked:
            self.selected_widgets.append(entry)
        else:
            # On retire une occurrence si elle existe
            if entry in self.selected_widgets:
                self.selected_widgets.remove(entry)

        print("Selected for autoshow:", len(self.selected_widgets))


    def populate_tree(self):
        if not self.existing_widgets:
            self.error("No widget found on the Orange window.")
            return

        self.treeWidget.clear()
        # Optionnel : définir une seule colonne ou plusieurs
        self.treeWidget.setHeaderLabels(["Widgets", "Types"])

        # existing_widgets est ton dict { 'Data': [('File', <obj>), ...], ... }
        for category, widgets in self.existing_widgets.items():
            # Parent (Catégorie) - On l'étale sur les deux colonnes (ou pas)
            parent_item = QTreeWidgetItem([category])
            # --- ON REMET LE GRAS ICI ---
            font = parent_item.font(0)
            font.setBold(True)
            parent_item.setFont(0, font)

            self.treeWidget.addTopLevelItem(parent_item)

            for title, name, widget_obj in widgets:
                # Création de l'item avec 2 colonnes : [Titre, NomTechnique]
                child_item = QTreeWidgetItem([title, name])

                # --- Style de la colonne 0 (Le Titre) ---
                child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable)
                child_item.setCheckState(0, Qt.Unchecked)
                child_item.setData(0, Qt.UserRole, type(widget_obj))

                # --- Style de la colonne 1 (Le Nom Technique) ---
                child_item.setFont(1, italic_font)
                child_item.setForeground(1, gray_color)

                parent_item.addChild(child_item)

        self.treeWidget.expandAll()


    def select_from_setting(self):
        self.warning("")
        if not self.selected_widgets:
            return

        tree = self.treeWidget
        tree.blockSignals(True)  # block signals so on_item_checked is NOT called
        try:
            valid_widgets = []

            for title, widget_type in self.selected_widgets:
                found = False

                # Iterate over top-level items (categories)
                for i in range(tree.topLevelItemCount()):
                    parent = tree.topLevelItem(i)

                    # Iterate over children (actual widgets)
                    for j in range(parent.childCount()):
                        child = parent.child(j)

                        # Match title + widget type
                        if (
                                child.text(0) == title
                                and child.data(0, Qt.UserRole) == widget_type
                        ):
                            # Only check if not already checked
                            if child.checkState(0) != Qt.Checked:
                                child.setCheckState(0, Qt.Checked)
                            found = True
                            break  # stop at first match

                    if found:
                        break

                # Keep only widgets that exist in the tree
                if found:
                    valid_widgets.append((title, widget_type))

            # Replace selected_widgets with valid ones
            if len(self.selected_widgets) != len(valid_widgets):
                diff = abs(len(self.selected_widgets) - len(valid_widgets))
                self.warning(f"{diff} widget(s) missing from the initial configuration.")
            self.selected_widgets = valid_widgets

        finally:
            tree.blockSignals(False)  # re-enable signals


    def show_widgets(self):
        for item in self.selected_widgets:
            title = item[0]
            widget_type = item[1]  # C'est le string "QPushButton" etc.

            # On parcourt chaque liste de widgets dans le dictionnaire
            for category_list in self.existing_widgets.values():
                for w in category_list:
                    # w[0] = title, w[2] = obj_widget
                    # On compare le titre ET le nom de la classe de l'objet
                    if w[0] == title and type(w[2]) == widget_type:
                        # On vérifie si la méthode reshow existe pour éviter un crash
                        if hasattr(w[2], 'reshow'):
                            w[2].reshow()


    def get_existing_widgets(self):
        # Get the MainWindow
        app = QApplication.instance()
        main_windows = []
        for item in app.topLevelWidgets():
            if isinstance(item, CanvasMainWindow):
                main_windows.append(item)
        if len(main_windows) == 0:
            self.error("Could not detect the main Orange window !")
            return
        elif len(main_windows) > 1:
            # TODO: Find main window with memory address of self
            self.error("Several main Orange windows detected ! Not implemented yet !")
            return

        scheme_edit_widget = main_windows[0].current_document()
        dict_of_items = scheme_edit_widget._SchemeEditWidget__widgetManager._OWWidgetManager__item_for_node

        existing_widgets = defaultdict(list)
        for key, value in dict_of_items.items():
            category = key.description.category
            title = key.title
            name = key.description.name
            obj_widget = value.widget
            # Plus besoin de vérifier si la catégorie existe !
            existing_widgets[category].append((title, name, obj_widget))
        return existing_widgets

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWAutoShow()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
