import os
import sys

from Orange.data import Table, Domain, StringVariable
from AnyQt.QtWidgets import QApplication
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtCore import QTimer



if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import base_widget, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import base_widget, help_management

@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWExtractTokens(base_widget.BaseListWidget):
    name = "Extract Tokens"
    description = "This widget extracts the tokens from your input data."
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/owextracttokens.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owextracttokens.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owextracttokens.ui")
    want_control_area = False
    priority = 1060
    selected_column_name = Setting("content")

    class Inputs:
        data = Input("Data", Table)

    class Outputs:
        data_row = Output("Tokens to row", Table)
        data_column = Output("Tokens to column", Table)

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
        self.setFixedHeight(600)
        #uic.loadUi(self.gui, self)

        # Data Management
        self.data = None
        self.autorun = True
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def run(self):
        self.warning("")
        self.error("")

        if self.data is None:
            self.Outputs.data_row.send(None)
            self.Outputs.data_column.send(None)
            return

        if not self.selected_column_name in self.data.domain:
            self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
            self.Outputs.data_row.send(None)
            self.Outputs.data_column.send(None)
            return

        if not hasattr(self.data, "tokens"):
            self.Outputs.data_row.send(self.data)
            self.Outputs.data_column.send(self.data)
            self.warning("There is no tokens in the input table.")
            return

        out_data_row = tokens_to_row(self.data)
        out_data_column = tokens_to_column(self.data)

        self.Outputs.data_row.send(out_data_row)
        self.Outputs.data_column.send(out_data_column)


    def post_initialized(self):
        pass


def tokens_to_row(table):
    # Get original domain
    domain = table.domain

    # Create new domain: same attributes + one new StringVariable for the token
    token_var = StringVariable("Tokens_1")
    new_domain = Domain(domain.attributes, domain.class_vars, metas=list(domain.metas) + [token_var])

    new_data_rows = []
    for i, row in enumerate(table):
        tokens = table.tokens[i]  # list of tokens for this row
        for token in tokens:
            # Duplicate the row's values
            attrs = list(row)  # attribute values
            metas = list(row.metas) + [token]  # append token as a new meta

            new_data_rows.append(attrs + metas)

    # Build and return the new Table
    return Table.from_list(new_domain, new_data_rows)


def tokens_to_column(table):
    # Step 1: Get max number of tokens across all rows
    max_tokens = max(len(tokens) for tokens in table.tokens)

    # Step 2: Create new domain
    token_vars = [StringVariable(f"Tokens_{i+1}") for i in range(max_tokens)]
    new_domain = Domain(
        table.domain.attributes,
        table.domain.class_vars,
        list(table.domain.metas) + token_vars  # add token vars as metas
    )

    new_data_rows = []
    for i, row in enumerate(table):
        tokens = list(table.tokens[i])

        # Pad token list to max_tokens with empty strings
        padded_tokens = tokens + [''] * (max_tokens - len(tokens))

        # Build row: attributes + class_vars + metas + tokens
        attrs = list(row)
        metas = list(row.metas) + padded_tokens

        new_data_rows.append(attrs + metas)

    return Table.from_list(new_domain, new_data_rows)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWExtractTokens()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
