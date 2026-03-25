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
        if data_in is None:
            return
        self.in_data = data_in
        if self.data_filter_in is None:
            return
        self.run()

    @Inputs.data_for_filter
    def set_path_table(self, in_data_filter):
        if in_data_filter is None:
            return

        total_columns = len(in_data_filter.domain.attributes) + len(in_data_filter.domain.class_vars) + len(
            in_data_filter.domain.metas)
        self.error("")
        if total_columns != 1:
            self.error("error filter_input can only use 1 column in this version")
            return
        if len(in_data_filter.domain.metas) != 1:
            self.error("error filter_input can only use Stringvariable")
            return
        if not isinstance(in_data_filter.domain.metas[0], Orange.data.StringVariable):
            self.error("error filter_input can only use Stringvariable.")
            return

        self.data_filter_in = in_data_filter
        if self.in_data is not None:
            self.run()

            # if total_columns != 1:
            #
            #     return
            #
            # print("in_data_filter")
            # print(in_data_filter)

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
        filter_var = self.data_filter_in.domain.metas[0]
        filter_var_name = filter_var.name

        # On utilise .index() ou une recherche directe dans le domaine
        match_var = self.in_data.domain[filter_var_name]
        if match_var is None or not match_var.is_string:
            self.error(f"La colonne '{filter_var_name}' est absente ou n'est pas une StringVariable.")
            return

        # On accède directement à l'attribut .metas (Tableau numpy d'objets pour les strings)
        filter_col_idx = self.data_filter_in.domain.metas.index(filter_var)
        filter_values = self.data_filter_in.metas[:, filter_col_idx]
        values_filter_set = {str(v) for v in filter_values if v and v != ""}

        # Au lieu de boucler sur les 'rows', on récupère toute la colonne d'un coup
        data_col_idx = self.in_data.domain.metas.index(match_var)
        data_values = self.in_data.metas[:, data_col_idx]

        # La compréhension sur un array numpy est souvent plus rapide que sur des objets 'Row'
        mask = np.array([str(val) in values_filter_set for val in data_values])

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
