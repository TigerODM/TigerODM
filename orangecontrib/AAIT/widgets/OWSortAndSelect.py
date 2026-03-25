import os
import sys
import numpy as np

import Orange.data
from AnyQt.QtWidgets import QApplication, QCheckBox, QSpinBox, QComboBox
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtCore import QTimer


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, base_widget, help_management
else:
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import thread_management, base_widget, help_management


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWSortAndSelect(base_widget.BaseListWidget):
    name = "Sort & Select"
    description = "This widget sorts the data table on the selected column and keeps the selected number of rows."
    category = "AAIT - TOOLBOX"
    icon = "icons/owsortandselect.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owsortandselect.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owsortandselect.ui")
    want_control_area = False
    priority = 1060

    # Settings
    order = Setting("Ascending")
    limit_rows = Setting(False)
    number_of_rows = Setting(5)

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
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(500)
        # Combobox for Ascending or Descending choice
        self.combobox_order = self.findChild(QComboBox, "comboBox")
        self.combobox_order.setCurrentIndex(self.combobox_order.findText(self.order))
        self.combobox_order.currentTextChanged.connect(self.on_order_changed)
        # Checkbox to limit output
        self.checkbox_limit_rows = self.findChild(QCheckBox, "checkBox_2")
        self.checkbox_limit_rows.setChecked(self.limit_rows)
        self.checkbox_limit_rows.toggled.connect(self.toogle_row_limit)
        # Spinbox to choose the number of rows in output
        self.spinbox_number_of_rows = self.findChild(QSpinBox, "spinBox")
        self.spinbox_number_of_rows.setValue(self.number_of_rows)
        self.spinbox_number_of_rows.setEnabled(self.limit_rows)
        self.spinbox_number_of_rows.valueChanged.connect(self.set_row_limit)

        # Data Management
        self.data = None
        self.autorun = True
        self.thread = None
        self.result = None
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))


    def on_order_changed(self, text):
        self.order = text
        self.run()

    def toogle_row_limit(self, checked):
        self.spinbox_number_of_rows.setEnabled(checked)
        self.limit_rows = checked
        self.run()

    def set_row_limit(self, value):
        self.number_of_rows = value
        self.run()


    def run(self):
        self.warning("")
        self.error("")

        # If Thread is already running, interrupt it
        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            return

        if not self.selected_column_name in self.data.domain:
            self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
            self.Outputs.data.send(None)
            return

        if self.checkbox_limit_rows.isChecked():
            number_of_rows = self.number_of_rows
        else:
            number_of_rows = None

        # Start progress bar
        self.progressBarInit()

        # Thread management
        self.thread = thread_management.Thread(sort_table_by_column, self.data, self.selected_column_name, self.order, number_of_rows)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()


    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.result = result
            self.Outputs.data.send(result)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        self.progressBarFinished()


    def post_initialized(self):
        pass


def sort_table_by_column(table, column_name, order="Ascending", n=None):
    """
    Sort an Orange Table by a column name (feature, class, or meta) and return top n rows.

    Args:
        table (Orange.data.Table): The table to sort.
        column_name (str): Name of the column to sort by.
        order (str): "Ascending" or "Descending".
        n (int or None): Number of rows to return. If None, return all.

    Returns:
        Orange.data.Table: Sorted table with at most n rows.
    """
    var = table.domain[column_name]
    if var is None:
        raise ValueError(f"Column '{column_name}' not found.")

    ascending = False
    if order == "Ascending":
        ascending = True

    # Determine which array to use
    if var in table.domain.attributes:
        values = table.X[:, table.domain.index(var)]
    elif var in table.domain.class_vars:
        values = table.Y
    else:  # meta
        values = table.metas[:, table.domain.metas.index(var)]

    # Sort indices
    if np.issubdtype(values.dtype, np.number):
        sorted_indices = np.argsort(values if ascending else -values, kind="mergesort")
    else:
        sorted_indices = np.argsort(values, kind="mergesort")
        if not ascending:
            sorted_indices = sorted_indices[::-1]

    # Limit number of rows if n is specified
    if n is not None:
        sorted_indices = sorted_indices[:n]

    return table[sorted_indices]

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWSortAndSelect()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
