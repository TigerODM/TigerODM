import os
import sys
import numpy as np

import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import help_management


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWSelectRowsDynamic(widget.OWWidget):
    name = "Select Rows Dynamic"
    description = "Select a row from a second entry"
    category = "AAIT - TOOLBOX"
    icon = "icons/select_dynamic_row.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/select_dynamic_row.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owselect_row_dynamic.ui")
    want_control_area = False
    priority = 1060

    class Inputs:
        data = Input("data", Orange.data.Table)
        data_for_filter = Input("input_for_filtering", Orange.data.Table)

    class Outputs:
        data_matching = Output("Matching Data", Orange.data.Table)
        data_unmatching = Output("UnMatching Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, data_in):
        self.in_data = data_in
        if data_in is None:
            self.Outputs.data_matching.send(None)
            self.Outputs.data_unmatching.send(None)
            return
        if self.data_filter_in is None:
            return
        self.run()

    @Inputs.data_for_filter
    def set_path_table(self, in_data_filter):
        self.data_filter_in = in_data_filter
        if in_data_filter is None:
            self.Outputs.data_matching.send(None)
            self.Outputs.data_unmatching.send(None)
            return

        total_columns = (
            len(in_data_filter.domain.attributes)
            + len(in_data_filter.domain.class_vars)
            + len(in_data_filter.domain.metas)
        )
        self.error("")
        if total_columns == 0:
            self.error("error filter_input must contain at least 1 column")
            self.data_filter_in = None
            self.Outputs.data_matching.send(None)
            self.Outputs.data_unmatching.send(None)
            return

        if self.in_data is not None:
            self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.data_filter_in = None
        self.in_data = None
        self.autorun = True
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def run(self):
        self.error("")
        filter_vars = (
            list(self.data_filter_in.domain.attributes)
            + list(self.data_filter_in.domain.class_vars)
            + list(self.data_filter_in.domain.metas)
        )

        if not filter_vars:
            self.error("error filter_input must contain at least 1 column")
            self.Outputs.data_matching.send(None)
            self.Outputs.data_unmatching.send(None)
            return

        match_vars = []
        for filter_var in filter_vars:
            try:
                match_vars.append(self.in_data.domain[filter_var.name])
            except (KeyError, IndexError):
                self.error(f"La colonne '{filter_var.name}' est absente.")
                self.Outputs.data_matching.send(None)
                self.Outputs.data_unmatching.send(None)
                return

        def normalize_value(value):
            if value is None:
                return None
            text = str(value).strip()
            if not text or text == "?":
                return None
            return text

        def make_key(row, variables):
            return tuple(normalize_value(row[var]) for var in variables)

        values_filter_set = {
            make_key(row, filter_vars)
            for row in self.data_filter_in
        }

        mask = np.fromiter(
            (
                make_key(row, match_vars) in values_filter_set
                for row in self.in_data
            ),
            dtype=bool,
            count=len(self.in_data),
        )

        matched_table = self.in_data[mask] if np.any(mask) else None
        unmatched_table = self.in_data[~mask] if np.any(~mask) else None

        self.Outputs.data_matching.send(matched_table)
        self.Outputs.data_unmatching.send(unmatched_table)

    def post_initialized(self):
        pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWSelectRowsDynamic()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
