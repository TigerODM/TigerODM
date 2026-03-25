import sys
import os

import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.widget import  MultiInput
from Orange.widgets.utils.signals import Output
from Orange.data import Table


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class POW_Wfactory(widget.OWWidget):
    name = "Widget Factory"
    description = "Simply create widget"
    category = "AAIT - TOOLBOX"
    icon = "icons/widgetFactory.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/widgetFactory.svg"
    priority = 1900

    # to  be continued
    class Inputs:
        data = MultiInput(
            "Data", Table, replaces=["in_data"], default=True
        )
        object = MultiInput(
            "Object", object, replaces=["in_object"], default=False, auto_summary=False
        )

    class Outputs:
        data_out = Output("Data Out", Orange.data.Table)

    signal_names = ("data")

    def post_initialized(self):
        return

    def __init__(self):
        super().__init__()
        self.in_data = None
        self.out_data = None
        self.in_datas = None
        self.in_object = None
        self.in_objects = None
        self.in_learner = None
        self.in_learners = None
        self.in_classifier = None
        self.in_classifiers = None
        self.out_datas = None
        self.out_object = None
        self.out_objects = None
        self.out_learner = None
        self.out_learners = None
        self.out_classifier = None
        self.out_classifiers = None
        self.post_initialized()

        for name in self.signal_names:
            setattr(self, name, [])

    def remove_input(self, index, signal):
        if signal == "data":
            data = []
            if self.in_data is not None:
                self.in_data = None
            else:
                data = self.in_datas
                data.pop(index)
                self.in_datas = None
            if len(data) == 1:
                self.in_data = data[0]
            if len(data) > 1:
                self.in_datas = data
        if signal == "object":
            objects = []
            if self.in_object is not None:
                self.in_object = None
            else:
                objects = self.in_objects
                objects.pop(index)
                self.in_objects = None
            if len(objects) == 1:
                self.in_object = objects[0]
            if len(objects) > 1:
                self.in_objects = objects
        self.run()

    @Inputs.data
    def set_data(self, index, data):
        self.in_datas[index] = data
        self.run()

    @Inputs.data.insert
    def insert_data(self, index, data):
        if index == 0:
            self.in_data = data
        else:
            dic = []
            if index == 1:
                dic.append(self.in_data)
                self.in_data = None
            if index > 1:
                dic = self.in_datas
            dic.append(data)
            self.in_datas = dic
        self.run()

    @Inputs.data.remove
    def remove_data(self, index):
        self.remove_input(index, "data")


    @Inputs.object
    def set_object(self, index, object):
        self.set_input(index, object, "object")

    @Inputs.object.insert
    def insert_object(self, index, object):
        if index == 0:
            self.in_object = object
        else:
            dic = []
            if index == 1:
                dic.append(self.in_object)
                self.in_object = None
            if index > 1:
                dic = self.in_objects
            dic.append(object)
            self.in_objects = dic
        self.run()

    @Inputs.object.remove
    def remove_object(self, index):
        self.remove_input(index, "object")

    def run(self):
        self.module_kernel_run()
        if self.out_data != None:
            self.Outputs.data_out.send(self.out_data)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = POW_Wfactory()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()