from Orange.widgets.widget import OWWidget, Input
import os, sys
from AnyQt.QtWidgets import  QApplication
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
else:
    from orangecontrib.AAIT.utils import MetManagement




class OWLoaderFinished(OWWidget):
    name = "Unlock input ready to work"
    description = "Unlock api rest then input is ready to work"
    icon = "icons/unlock.png"
    want_control_area = False
    category = "AAIT - API"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/unlock.png"
    priority = 3001
    class Inputs:
        signal_ready_do_work = Input("is ready do work", str, auto_summary=False)

    def __init__(self):
        super().__init__()

    @Inputs.signal_ready_do_work
    def set_data(self, str_data):
        self.error("")
        folder_path=MetManagement.get_api_local_folder_admin_locker()
        os.makedirs(folder_path, exist_ok=True)
        file_to_delete=[folder_path+"/"+str_data+".lk"]
        if 0!=MetManagement.reset_files(file_to_delete):
            self.error("error can not unlock "+folder_path+"/"+str_data+".lk")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWLoaderFinished()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
