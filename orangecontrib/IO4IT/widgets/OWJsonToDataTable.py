import os
import sys
import json
import Orange
from Orange.widgets.widget import Input, Output
from AnyQt.QtWidgets import QApplication
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import  QCheckBox
from Orange.data import Table, Domain, StringVariable
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert
    from Orange.widgets.orangecontrib.AAIT.utils import base_widget
else:
    from orangecontrib.HLIT_dev.remote_server_smb import convert
    from orangecontrib.AAIT.utils import base_widget

class OWJsonToDataTable(base_widget.BaseListWidget):
    name = "JsonToDataTable"
    description = "Convert Json to Orange data table. You need to pass a content in input."
    icon = "icons/json-file.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/json-file.png"
    priority = 3000
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_json_to_data_table.ui")
    want_control_area = False
    category = "AAIT - TOOLBOX"
    selected_column_name = Setting("content")
    data_table_to_json=Setting("False")

    class Inputs:
        data = Input("Data", Orange.data.Table)
        path = Input("Path to json", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        if in_data is None:
            return
        self.data = in_data
        if self.data:
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        self.run()

    @Inputs.path
    def set_path(self, in_data):
        if in_data is None:
            return
        if self.data_table_to_json == "True":
            self.warning("")
            return
        self.path = in_data #in_data est le chemin pas l entree in_data
        if self.path:
            self.var_selector.add_variables(self.path.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        self.run()

    class Outputs:
        data = Output("Data", Orange.data.Table)

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(500)
        self.setFixedHeight(450)
        self.data = None
        self.path = None
        self.check_box_data_table_to_json=self.findChild(QCheckBox, "checkBox")
        if self.data_table_to_json=="True":
            self.check_box_data_table_to_json.setChecked(True)
        else:
            self.check_box_data_table_to_json.setChecked(False)
        self.check_box_data_table_to_json.stateChanged.connect(self.on_checkbox_toggled)


    def on_checkbox_toggled(self):
        if self.check_box_data_table_to_json.isChecked():
            self.data_table_to_json="True"
        else:
            self.data_table_to_json = "False"


    def run(self):
        self.error("")
        self.warning("")
        if self.data_table_to_json=="True":
            try:
                json_data = convert.convert_data_table_to_json(self.data)

                if json_data is None:
                    content = ""
                else:
                    content = json.dumps(json_data, ensure_ascii=False, indent=4)

                domain = Domain([], metas=[StringVariable("content")])

                out_data = Table.from_list(
                    domain,
                    [[content]]
                )

                self.Outputs.data.send(out_data)
                return
            except Exception as e:
                self.error(f"Error: {e}")
                self.Outputs.data.send(None)
                self.data = None
                self.path = None
                return





        try :
            if self.data:
                obj = []
                values = self.data.get_column(self.selected_column_name)

                for row_index, raw in enumerate(values):
                    try:
                        if isinstance(raw, str):
                            if raw.strip() == "":
                                continue
                            current_obj = json.loads(raw)
                            if isinstance(current_obj, str):
                                current_obj = json.loads(current_obj)
                        else:
                            current_obj = raw

                        if isinstance(current_obj, list):
                            obj.extend(current_obj)
                        else:
                            obj.append(current_obj)
                    except Exception as e:
                        self.error(f"Error: {e}")
                        self.Outputs.data.send(None)
                        self.data = None
                        self.path = None
                        return


            if self.path:
                raw = self.path.get_column(self.selected_column_name)[0]
                with open(raw, "r", encoding="utf-8") as f:
                    obj = json.load(f)
            data = convert.convert_json_implicite_to_data_table(obj)
            self.Outputs.data.send(data)
            self.data = None
            self.path = None
        except Exception as e:
            self.error(f"Error: {e}")
            self.Outputs.data.send(None)
            self.data = None
            self.path = None

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWJsonToDataTable()
    my_widget.show()

    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())