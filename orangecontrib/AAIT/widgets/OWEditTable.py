import sys
import os
import numpy as np
import html

import Orange.data
from Orange.data import ContinuousVariable, DiscreteVariable, StringVariable, TimeVariable, Domain, Table
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtWidgets import QTableWidget, QTableWidgetItem, QComboBox, QPushButton, QCheckBox, QHBoxLayout
from AnyQt.QtCore import QTimer, Qt
from copy import deepcopy
from Orange.widgets.settings import Setting

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import widget_positioning,help_management
else:
    from orangecontrib.AAIT.utils import widget_positioning,help_management


class OWEditTable(widget.OWWidget):
    name = "Edit Table"
    description = "Display and edit input data in a table format"
    category = "AAIT - TOOLBOX"
    icon = "icons/owedittable.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owedittable.svg"
    want_control_area = False
    priority = 1003
    str_WidgetPositionning: str=Setting("None")
    str_Auto_send: str=Setting("False")

    class Inputs:
        data = Input("Data", Orange.data.Table)
        input_autoshow = Input("AutoShowConfiguration", str, auto_summary=False)

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


    @Inputs.input_autoshow
    def set_input_autoshow(self, le_str):
        if le_str is not None:
            self.str_WidgetPositionning=str(le_str)


    def __init__(self):
        super().__init__()
        # Set up the layout and table
        self.table_widget = QTableWidget()
        self.mainArea.layout().addWidget(self.table_widget)

        bottom_layout = QHBoxLayout()
        self.checkbox_auto = QCheckBox("Auto send")
        bottom_layout.addWidget(self.checkbox_auto)

        # Add a "Save Changes" button to trigger output
        self.btn_confirm = QPushButton("Confirm")
        self.btn_confirm.clicked.connect(self.save_changes_to_data)
        bottom_layout.addWidget(self.btn_confirm)

        self.btn_copy_clipboard = QPushButton("Copy in html format")
        self.btn_copy_clipboard.clicked.connect(self.copy_html_to_clipboard)
        bottom_layout.addWidget(self.btn_copy_clipboard)

        self.mainArea.layout().addLayout(bottom_layout)

        # Data Management
        self.data = None
        self.modified_data = {}
        self.updated_data = None
        if self.str_Auto_send!="True":
            self.checkbox_auto.setChecked(False)
        else:
            self.checkbox_auto.setChecked(True)
        self.checkbox_auto.clicked.connect(self.update_autocheck)
        widget_positioning.show_and_adjust_at_opening(self,str(self.str_WidgetPositionning))
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def update_autocheck(self):
        if self.checkbox_auto.isChecked():
            self.str_Auto_send = "True"
        else:
            self.str_Auto_send ="False"

    def populate_table(self):
        """Fill QTableWidget with data from the Orange Table."""
        # Disconnect previous signal if already connected
        try:
            self.table_widget.itemChanged.disconnect(self.store_modification_cells)
        except TypeError:
            pass

        # Clear previous content/widgets to force full refresh
        self.table_widget.clear()

        # Use the full domain: attributes + class vars + metas
        all_vars = (
            list(self.data.domain.attributes)
            + list(self.data.domain.class_vars)
            + list(self.data.domain.metas)
        )

        # Set row and column counts
        self.table_widget.setRowCount(len(self.data))
        self.table_widget.setColumnCount(len(all_vars))

        # Set headers
        headers = [var.name for var in all_vars]
        self.table_widget.setHorizontalHeaderLabels(headers)

        # Fill table with data
        for row in range(len(self.data)):
            for col, var in enumerate(all_vars):
                value = str(self.data[row][var])  # Get value as string
                if isinstance(var, Orange.data.DiscreteVariable):
                    # Create a combo box for discrete variables
                    combo = QComboBox()
                    combo.addItems(var.values)  # Add possible values
                    combo.setCurrentText(value)  # Set current value
                    self.table_widget.setCellWidget(row, col, combo)
                    combo.currentTextChanged.connect(
                        lambda new_value, r=row, c=var.name: self.store_modification_combo(r, c, new_value)
                    )
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
        if self.str_Auto_send=="True":
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


    def copy_html_to_clipboard(self):
        if self.data is None:
            self.Error.unknown("Aucune table en entrée.")
            return

        def get_role(var, domain):
            if var in domain.attributes:
                return "feature"
            elif var in domain.class_vars:
                return "target"
            elif var in domain.metas:
                return "meta"
            return "-"

        def get_type_name(var):
            if isinstance(var, ContinuousVariable):
                return "Numeric"
            elif isinstance(var, DiscreteVariable):
                return "Categoriel"
            elif isinstance(var, StringVariable):
                return "String"
            elif isinstance(var, TimeVariable):
                return "Time"
            return "-"

        def get_meta(var, domain):
            return f"{get_type_name(var)} • {get_role(var, domain)}"

        all_vars = list(self.data.domain.attributes) + list(self.data.domain.class_vars) + list(self.data.domain.metas)

        html_parts = []
        html_parts.append("<html>")
        html_parts.append("<head><meta charset='utf-8'></head>")
        html_parts.append("<body style='font-family: Arial, Helvetica, sans-serif; background: #ffffff; margin: 4px;'>")

        html_parts.append(
            "<div style='overflow-x:auto;'>"
            "<table style='border-collapse: collapse; min-width: 400px; background: white;'>"
        )

        # HEADER
        html_parts.append("<thead><tr>")
        for var in all_vars:
            name = html.escape(var.name)
            meta = html.escape(get_meta(var, self.data.domain))
            html_parts.append(
                "<th style='"
                "background: #dbe5f1; "
                "color: #000000; "
                "padding: 2px 4px; "
                "border: 1px solid #b8cce4; "
                "text-align: left; "
                "vertical-align: top; "
                "min-width: 45px;"
                "'>"
                f"<div style='font-size: 9px; font-weight: bold; margin-bottom: 1px; white-space: nowrap; line-height: 1.0;'>{name}</div>"
                f"<div style='font-size: 6px; color: #444444; white-space: nowrap; line-height: 1.0;'>{meta}</div>"
                "</th>"
            )
        html_parts.append("</tr></thead>")

        # BODY
        html_parts.append("<tbody>")
        for i in range(self.table_widget.rowCount()):

            if i % 2 == 0:
                bg = "#ffffff"
            else:
                bg = "#f7fbff"

            html_parts.append("<tr>")
            for j, var in enumerate(all_vars):
                combo = self.table_widget.cellWidget(i, j)
                if combo is not None and isinstance(combo, QComboBox):
                    val = combo.currentText()
                else:
                    item = self.table_widget.item(i, j)
                    if item is not None:
                        val = item.text()
                    else:
                        val = "?"

                if val in ("?", "", "None"):
                    val_html = "<span style='color:#777777; font-style: italic;'>?</span>"
                else:
                    val_html = html.escape(val)

                html_parts.append(
                    "<td style='"
                    f"background: {bg}; "
                    "border: 1px solid #d9d9d9; "
                    "padding: 1px 4px; "
                    "font-size: 7px; "
                    "color: #000000; "
                    "vertical-align: top; "
                    "white-space: nowrap; "
                    "line-height: 1.0;"
                    "'>"
                    f"{val_html}"
                    "</td>"
                )
            html_parts.append("</tr>")
        html_parts.append("</tbody>")

        html_parts.append("</table></div>")
        html_parts.append("</body></html>")

        final_html = "\n".join(html_parts)

        QApplication.clipboard().setText(final_html)


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