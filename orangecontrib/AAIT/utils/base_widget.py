import os
from AnyQt.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem
from AnyQt.QtCore import pyqtSignal
import Orange
from Orange.widgets import gui, widget
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
else:
    from orangecontrib.AAIT.utils.import_uic import uic


class BaseListWidget(widget.OWWidget, openclass=True):
    """
    Base Orange widget providing a filterable list of variables from the input data domain.

    This class automatically:
      - Adds a `FilterableVariableList` UI component.
      - Handles input data and populates the list with variables.
      - Restores the last selected variable (`selected_column_name`).

    ______________________________________________________________________________________
    How to use:
    ⚠️ The linked .ui file **must include a `QWidget` named "placeholder"`**, where the
    variable list will be inserted (see owexecutescript_TEST.ui).

    1. Inherit from `BaseListWidget` instead of `Orange.widgets.OWWidget`.
       Your widget will automatically have the attribute `selected_column_name`.

    2. Use `selected_column_name` in your `run()` function to determine
       which column should be processed. For example, check if it's in
       `data.domain` or verify its type (e.g., `StringVariable`).

    3. Pass `selected_column_name` to any threaded function you use:
       ```python
       thread_management.Thread(self.my_function, self.data, self.selected_column_name)
       ```

    4. Update your processing functions (e.g., `generate_answers`, `create_embeddings`,
       `execute_scripts_in_table`) to accept the column name as an argument.

    5. Remove any `uic.loadUi(self.gui, self)` calls from your widget, as the UI is already loaded automatically by `BaseListWidget`.

    6. If you only need "Data" as input and "Data" as output, remove the Inputs, Outputs and set() methods from your widget.
       They are already defined in BaseListWidget.

       ⚠️ Optional: Only if you truly need to customize input handling, you can
       override the `set_data()` method. In that case, make sure to update
       the `var_selector` (a `FilterableVariableList`) like this:

       ```python
       self.var_selector.add_variables(self.data.domain)
       self.var_selector.select_variable_by_name(self.selected_column_name)
       ```
    7. You can use
        autorun = Setting(True)
        and self.autorun = True / self.autorun = False
        to control whether the process is triggered automatically when input data is received.

    8.self.data is the input data stream. Make sure to create
        new_data = self.data.copy()
        to avoid issues when the process is triggered several time via a push button.
    """
    # Settings
    selected_column_name = Setting("Default")  # set the targeted column by default as "Default"

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.data:
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        if self.autorun:
            self.run()


    def __init__(self):
        super().__init__()
        # Load the .ui file if defined
        if self.gui and os.path.exists(self.gui):
            uic.loadUi(self.gui, self)

        # --- Insert filterable variable list ---
        self.var_selector = FilterableVariableList(self)
        placeholder = self.findChild(QWidget, "placeholder")  # add a QWidget in your .ui
        if placeholder:
            self.var_selector.setParent(placeholder)
            self.var_selector.setGeometry(0, 0, placeholder.width(), placeholder.height())
            self.var_selector.show()
        self.var_selector.selected_variable.connect(self.on_variable_selected)

        # Data management
        self.data = None
        # If self.autorun exists, it is preserved. Otherwise, it is set to True.
        self.autorun = getattr(self, "autorun", True)

    def on_variable_selected(self, var_name):
        """Update the selected column when the user clicks an item."""
        self.selected_column_name = var_name




# Widget Qt pour sélectionner des variables dans un widget Orange
class FilterableVariableList(QWidget):
    """
    A scrollable list of Orange variables with:
      - Single selection
      - Colored icons based on type
      - Filter field at the top
    """
    selected_variable = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_vars = []

        # Layout
        self.layout = QVBoxLayout(self)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter variables...")
        self.layout.addWidget(self.filter_edit)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.layout.addWidget(self.list_widget)

        # Connect filter
        self.filter_edit.textChanged.connect(self.apply_filter)
        # Connect variable selection
        self.list_widget.itemSelectionChanged.connect(self.on_selection_changed)


    def add_variables(self, variables):
        """Store all variables and populate the list"""
        self.all_vars = variables
        self.populate_list(self.all_vars)

    def populate_list(self, variables):
        """Populate the QListWidget with items and icons using Orange standard icons"""
        self.list_widget.clear()
        if variables is not None:
            for var in variables:
                item = QListWidgetItem(var.name)
                item.setIcon(gui.attributeIconDict[var])  # <-- standard Orange icon
                self.list_widget.addItem(item)

    def apply_filter(self, text):
        """Filter the list based on input"""
        text = text.lower()
        filtered = [v for v in self.all_vars if text in v.name.lower()]
        self.populate_list(filtered)

    def on_selection_changed(self):
        selected = self.get_selected_name()
        if selected:
            self.selected_variable.emit(selected)

    def get_selected_name(self):
        """Get the selected variable's name"""
        selected_items = self.list_widget.selectedItems()
        return selected_items[0].text() if selected_items else None

    def select_variable_by_name(self, name):
        """Select an item in the list by its variable name."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.text() == name:
                self.list_widget.setCurrentItem(item)
                self.list_widget.scrollToItem(item)  # optional: ensure it's visible
                return
