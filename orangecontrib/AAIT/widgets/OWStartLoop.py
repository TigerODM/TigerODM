import os
import sys
import Orange.data
from Orange.data import Domain, Table,  ContinuousVariable
from Orange.widgets.utils.signals import Input,Output
from Orange.widgets.widget import OWWidget
import numpy as np
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QCheckBox, QPushButton
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.unlink_table_domain import unlink_domain
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.unlink_table_domain import unlink_domain
    from orangecontrib.AAIT.utils import help_management

class LoopStartWidget(OWWidget):
    name = "Loop Start"
    description = "Widget to start a loop with data table input and output."
    icon = "icons/startloop.png"
    category = "AAIT - ALGORITHM"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/startloop.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owstartloop.ui")
    want_control_area = False
    priority = 1010
    str_iterate_still_nb_line_dont_change: str = Setting("False")
    str_iter_of_line_number: str = Setting("False")
    class Inputs:
        data_in = Input("Data In", Orange.data.Table)
        # in_pointer = Input("End of the Loop Do-While", str, auto_summary=False)

    class Outputs:
        data_out = Output("Data Out", Orange.data.Table)
        out_pointer = Output("Begin of the Loop Do-While", str, auto_summary=False)

    def __init__(self):
        super().__init__()

        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.checkBox_iteration_until_number_of_line_dont_change = self.findChild(QCheckBox, 'checkBox')
        self.checkBox_iteration_on_the_number_of_line = self.findChild(QCheckBox, 'checkBox_2')
        self.pushButton=self.findChild(QPushButton, 'pushButton')
        self.pushButton.clicked.connect(self.button_reintialise_action)

        if self.str_iterate_still_nb_line_dont_change !="False":
            self.checkBox_iteration_until_number_of_line_dont_change.setChecked(True)
        else:
            self.checkBox_iteration_until_number_of_line_dont_change.setChecked(False)
        self.checkBox_iteration_until_number_of_line_dont_change.stateChanged.connect(self.update_checkBox_iteration_until_number_of_line_dont_change)
        if self.str_iter_of_line_number !="False":
            self.checkBox_iteration_on_the_number_of_line.setChecked(True)
        else:
            self.checkBox_iteration_on_the_number_of_line.setChecked(False)
        self.checkBox_iteration_on_the_number_of_line.stateChanged.connect(self.updat_checkBox_iteration_on_the_number_of_line)
        self.iter = 0
        self.data = None
        self.ready=0

        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def set_ready(self):
        self.ready=1

    def button_reintialise_action(self):
        self.iter = 0
        dataset = self.data
        self.set_data(dataset)
        self.send_pointer()

    def update_checkBox_iteration_until_number_of_line_dont_change(self):
        if self.checkBox_iteration_until_number_of_line_dont_change.isChecked():
            self.str_iterate_still_nb_line_dont_change="True"
            self.checkBox_iteration_on_the_number_of_line.setChecked(False)
        else:
            self.str_iterate_still_nb_line_dont_change = "False"

    def updat_checkBox_iteration_on_the_number_of_line(self):
        if self.checkBox_iteration_on_the_number_of_line.isChecked():
            self.str_iter_of_line_number="True"
            self.checkBox_iteration_until_number_of_line_dont_change.setChecked(False)
        else:
            self.str_iter_of_line_number = "False"


    @Inputs.data_in
    def set_data(self, dataset):
        if dataset is None:
            print("No data received.")
            return
        self.send_pointer()
        self.error("")
        self.data=None
        if self.str_iterate_still_nb_line_dont_change =="True":
            self.data=dataset
            self._process_when_ready()
            return



        if self.str_iter_of_line_number =="True":
            self.data=dataset
            self._execute_iter_of_line_number_when_ready()
            return
        error_code_check_iter_column=self.check_iter_column(dataset)
        if error_code_check_iter_column==1:
            self.data=self.add_iter_column(dataset)
        elif error_code_check_iter_column==0:
            self.data = dataset
        else:
            self.error("error remove iter column in input data!!!")
            return
        self._process_when_ready()

    def add_iter_column(self,in_data_orange):
        iter_var = ContinuousVariable("iter")
        new_domain = Domain(in_data_orange.domain.attributes + (iter_var,), in_data_orange.domain.class_var, in_data_orange.domain.metas)
        iter_values = np.ones((len(in_data_orange), 1))  # column of 0
        # merge
        new_X = np.hstack((in_data_orange.X, iter_values))
        return Table(new_domain, new_X, in_data_orange.Y, in_data_orange.metas)

    def check_iter_column(self,in_data_orange):
        """
        Checks the presence and validity of the categorical variable 'iter' in in_data.

        Returns:
        - 0 if 'iter' is a categorical variable with only "0" and "1" as values.
        - 1 if 'iter' is missing from the domain.
        - 2 if 'iter' exists but is either not continuous.
        """
        # Check if "iter" exists in the domain
        if "iter" not in in_data_orange.domain:
            return 1  # "iter" does not exist

        iter_var = in_data_orange.domain["iter"]

        # Check if "iter" is continuous
        if not iter_var.is_continuous:
            return 2  # "iter" is not continuous

        return 0  # Everything is correct


    def get_nb_line(self):
        """Return the number of lines to be called from another widget."""
        return 0 if self.data is None else len(self.data)

    def get_iter(self):
        return self.iter

    def reinitialize_iter(self):
        self.iter = 0
        return


    def is_allow_to_change_line_number(self):
        """Return if we are allowed to change the number of line to be called from another widget."""
        return self.str_iterate_still_nb_line_dont_change

    def iter_of_line_number(self):
        return self.str_iter_of_line_number

    def execute_iter_of_line_number(self):
        table = Table.from_table(domain=self.data.domain, source=self.data, row_indices=[self.iter])
        self.iter += 1
        self.Outputs.data_out.send(unlink_domain(table))

    def get_column_name_and_type(self):
        """Return the name and type of 'data_in' to be called from another widget."""
        if self.data is None:
            return [[], []]
        column_names = []
        column_types = []

        for element in self.data.domain.variables + self.data.domain.metas:
            column_names.append(str(element.name))
            column_types.append(str(type(element)))
        return column_names, column_types

    def get_in_data(self):
        return self.data

    def _process_when_ready(self):
        """
        Robuste: n'exécute process_data() qu'une seule fois,
        même si appelée plusieurs fois avant ready == 1.
        """

        # Incrémente un token pour invalider les anciens timers
        self._process_wait_token = getattr(self, "_process_wait_token", 0) + 1
        token = self._process_wait_token

        def _tick():
            # Ignore les anciens callbacks
            if token != getattr(self, "_process_wait_token", 0):
                return

            if getattr(self, "data", None) is None:
                return

            if getattr(self, "ready", 0) == 1:
                # Consomme le token pour empêcher double exécution
                self._process_wait_token += 1
                self.process_data()
                return

            QTimer.singleShot(50, _tick)

        _tick()

    def _execute_iter_of_line_number_when_ready(self):
        """
        Robuste: n'exécute execute_iter_of_line_number() qu'une seule fois,
        même si cette fonction est appelée plusieurs fois avant ready==1.
        """
        # Incrémente un token à chaque "demande" (annule les anciens timers)
        self._iter_wait_token = getattr(self, "_iter_wait_token", 0) + 1
        token = self._iter_wait_token

        def _tick():
            # Ignore les callbacks obsolètes
            if token != getattr(self, "_iter_wait_token", 0):
                return

            if getattr(self, "data", None) is None:
                return

            if getattr(self, "ready", 0) == 1:
                # Consomme le token pour empêcher toute double exécution
                self._iter_wait_token += 1
                self.execute_iter_of_line_number()
                return

            QTimer.singleShot(100, _tick)

        _tick()



    def process_data(self):
        """Main process executed when data is available."""
        if self.data is not None:
            #new_data=copy.deepcopy(self.data)
            self.Outputs.data_out.send(unlink_domain(self.data))  # Envoie les données en sortie
        else:
            print("No data sent.")


    def send_pointer(self):
        """Send a pointer to the current class for the loop."""
        pointer = str(id(self))
        self.Outputs.out_pointer.send(pointer)

if __name__ == "__main__":
    from AnyQt.QtWidgets import QApplication

    app = QApplication(sys.argv)
    obj = LoopStartWidget()
    obj.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
