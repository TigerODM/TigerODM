import sys
import os
import numpy as np

import Orange.data
from Orange.data import ContinuousVariable, DiscreteVariable, StringVariable, TimeVariable, Domain, Table
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtWidgets import QTableWidget, QTableWidgetItem, QComboBox, QPushButton
from AnyQt.QtCore import QTimer, Qt
from copy import deepcopy


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils import help_management


class OWEditTable(widget.OWWidget):
    name = "Edit Table"
    description = "Display and edit input data in a table format"
    category = "AAIT - TOOLBOX"
    icon = "icons/owedittable.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owedittable.svg"
    want_control_area = False
    priority = 1003

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    class Error(widget.OWWidget.Error):
        unknown = widget.Msg("{}")

    @Inputs.data
    def set_data(self, data):
        """Receive data input and populate the table."""
        self.Error.unknown.clear()
        if data is not None:
            self.data = data
            self.populate_table()
        else:
            self.Outputs.data.send(None)


    def __init__(self):
        super().__init__()
        # Set up the layout and table
        self.table_widget = QTableWidget()
        self.mainArea.layout().addWidget(self.table_widget)

        # Add a "Save Changes" button to trigger output
        self.btn_confirm = QPushButton("Confirm")
        self.btn_confirm.clicked.connect(self.save_changes_to_data)
        self.mainArea.layout().addWidget(self.btn_confirm)

        # Data Management
        self.data = None
        self.modified_data = {}
        self.updated_data = None
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))


    def populate_table(self):
        """Fill QTableWidget with data from the Orange Table."""
        # Set row and column counts
        self.table_widget.setRowCount(len(self.data))
        self.table_widget.setColumnCount(len(list(self.data.domain)))

        # Set headers
        headers = [var.name for var in list(self.data.domain)]
        self.table_widget.setHorizontalHeaderLabels(headers)

        # Fill table with data
        for row in range(len(self.data)):
            for col, var in enumerate(list(self.data.domain)):
                value = str(self.data[row][var])  # Get value as string
                if isinstance(var, Orange.data.DiscreteVariable):
                    # Create a combo box for discrete variables
                    combo = QComboBox()
                    combo.addItems(var.values)  # Add possible values
                    combo.setCurrentText(value)  # Set current value
                    self.table_widget.setCellWidget(row, col, combo)
                    combo.currentTextChanged.connect(lambda new_value=value, r=row, c=var.name: self.store_modification_combo(r, c, new_value))
                else:
                    # Set as editable text for continuous and string variables
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)  # Make cells editable
                    item.setData(Qt.UserRole, (row, var.name))  # Store the row and column as metadata
                    self.table_widget.setItem(row, col, item)
        # Connect the table to store user's modifications
        self.table_widget.itemChanged.connect(self.store_modification_cells)

        # Reset the modifications and the updated table
        self.modified_data = {}
        self.updated_data = deepcopy(self.data)

        # Send the data through
        self.send_output()


    def store_modification_combo(self, row, col, new_value):
        """Store the modified values in a dictionary."""
        if col not in self.modified_data:
            self.modified_data[col] = {}  # Initialize with empty dict
        self.modified_data[col][row] = new_value


    def store_modification_cells(self, item):
        """Store the modified values in a dictionary for text cells."""
        row, col = item.data(Qt.UserRole)  # Retrieve row and column from metadata
        new_value = item.text()
        if col not in self.modified_data:
            self.modified_data[col] = {}  # Initialize with empty dict
        self.modified_data[col][row] = new_value


    def save_changes_to_data(self):
        """Modify original columns, create backup columns with original values, and send the modified table."""
        # Copy the data and domains (attributes, classes, metas)
        self.updated_data = self.data.copy()
        new_attributes = list(self.updated_data.domain.attributes)
        new_class_vars = list(self.updated_data.domain.class_vars)
        new_metas = list(self.updated_data.domain.metas)

        # Prepare new tables (X, Y, metas) as a copy of previous tables
        new_data_X = self.updated_data.X.copy()
        new_data_Y = self.updated_data.Y.copy()
        new_data_metas = self.updated_data.metas.copy()

        # Go through the dictionary containing the modifications
        for col_name, changes in self.modified_data.items():
            # Handle Attributes
            if col_name in [attr.name for attr in self.updated_data.domain.attributes]:
                col_idx = self.updated_data.domain.attributes.index(self.updated_data.domain[col_name])
                # Create backup column and update original
                new_data_X, new_attributes = self.modify_with_backup(
                    self.updated_data.domain, new_data_X, new_attributes, col_name, col_idx, changes
                )
            # Handle Class Variables
            elif col_name in [cls.name for cls in self.updated_data.domain.class_vars]:
                col_idx = self.updated_data.domain.class_vars.index(self.updated_data.domain[col_name])
                new_data_Y, new_class_vars = self.modify_with_backup(
                    self.updated_data.domain, new_data_Y, new_class_vars, col_name, col_idx, changes
                )
            # Handle Metas
            elif col_name in [meta.name for meta in self.updated_data.domain.metas]:
                col_idx = self.updated_data.domain.metas.index(self.updated_data.domain[col_name])
                new_data_metas, new_metas = self.modify_with_backup(
                    self.updated_data.domain, new_data_metas, new_metas, col_name, col_idx, changes
                )

        # Create a new domain and Table
        try:
            new_domain = Domain(new_attributes, new_class_vars, new_metas)
            self.updated_data = Table.from_numpy(new_domain, new_data_X, new_data_Y, new_data_metas)
            self.Error.unknown.clear()
        except Exception as e:
            self.Error.unknown(f"You cannot change the values of a column that has already been modified in another Edit Table widget. (detail: {e})")
            self.updated_data = self.data.copy()

        # Clear the error and send the output Table
        self.send_output()


    def modify_with_backup(self, domain, data, domain_list, col_name, col_idx, changes):
        """
        Modify original column values and create a backup column with original values.

        Parameters:
            domain (Orange.data.Domain): The domain of the Orange Data Table.
            data (np.array): The table to modify (X, Y or metas).
            domain_list (list): The corresponding domain list (attributes, class_vars, metas).
            col_name (str): The name of the column to process.
            col_idx (int): The index of the column in the np array.
            changes (dict): A dictionary mapping row indices to new values.

        Returns:
            data (np.array): Updated data with modifications.
            domain_list (list): Updated domain list with the backup column added.
        """
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        # Get the original column
        original_col = data[:, col_idx].copy()

        # Modify the original column
        var = domain[col_name]
        if isinstance(var, TimeVariable):
            for row_idx, new_value in changes.items():
                try:
                    original_col[int(row_idx)] = var.parse(new_value)
                except ValueError as e:
                    self.Error.unknown(f"Invalid date format: {e}")
                    raise ValueError("Invalid date format")

        elif isinstance(var, ContinuousVariable):
            for row_idx, new_value in changes.items():
                try:
                    original_col[int(row_idx)] = float(new_value)
                except ValueError as e:
                    self.Error.unknown(f"Invalid continuous value: {e}")
                    raise ValueError("Invalid continuous value")

        elif isinstance(var, DiscreteVariable):
            for row_idx, new_value in changes.items():
                try:
                    original_col[int(row_idx)] = var.values.index(new_value)
                except ValueError as e:
                    self.Error.unknown(f"Value not in categories: {new_value}. {e}")
                    raise ValueError("Value not in categories")

        elif isinstance(var, StringVariable):
            original_col = original_col.astype(object)
            for row_idx, new_value in changes.items():
                original_col[int(row_idx)] = str(new_value)

        # Create a backup column and corresponding variable
        backup_col_name = f"{col_name} (Original)"
        backup_var = type(var)(backup_col_name, getattr(var, "values", None))
        data = np.column_stack((data, data[:, col_idx]))  # Add original values as backup
        domain_list.append(backup_var)  # Add backup variable to domain

        # Replace the original column with the modified one
        data[:, col_idx] = original_col
        return data, domain_list


    def send_output(self):
        """Send the modified table with duplicated columns."""
        self.Outputs.data.send(self.updated_data)
        return


if __name__ == "__main__":
    app = QApplication(sys.argv)
    obj = OWEditTable()
    obj.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
