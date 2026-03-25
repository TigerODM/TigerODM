import os
from pathlib import Path
import sys
from collections import defaultdict

import Orange.data
from Orange.data import Table
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, help_management
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import thread_management, help_management


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWFileSyncChecker(widget.OWWidget):
    name = "File Sync Checker"
    description = 'Verify if the files contained in Data are the same as the files contained in Reference. The verification is done thanks to both the "path" and "file size" columns.'
    category = "AAIT - TOOLBOX"
    icon = "icons/owfilesyncchecker.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owfilesyncchecker.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owfilesyncchecker.ui")
    want_control_area = False
    priority = 1060

    class Inputs:
        data = Input("Data", Orange.data.Table)
        reference = Input("Reference", Orange.data.Table)

    class Outputs:
        data = Output("Files only in Data", Orange.data.Table)
        processed = Output("Files in Data & Reference", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.autorun:
            self.run()

    @Inputs.reference
    def set_reference(self, in_reference):
        self.reference = in_reference
        if self.autorun:
            self.run()


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)

        # Data Management
        self.data = None
        self.reference = "default"
        self.autorun = True
        self.thread = None
        self.result = None
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def run(self):
        self.warning("")
        self.error("")

        # If Thread is already running, interrupt it
        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            self.Outputs.processed.send(None)
            return

        if self.reference == "default":
            self.Outputs.data.send(None)
            self.Outputs.processed.send(None)
            return

        if self.reference is None:
            self.warning('There is no Reference table. All the files in Data will be considered as new files.')
            self.Outputs.data.send(self.data)
            self.Outputs.processed.send(None)
            return

        if "root_dir" not in self.data.domain or "root_dir" not in self.reference.domain:
            self.error('You need a "root_dir" column in both Data and Reference tables.')
            self.Outputs.data.send(None)
            self.Outputs.processed.send(None)
            return

        if "relative_path" not in self.data.domain or "relative_path" not in self.reference.domain:
            self.error('You need a "relative_path" column in both Data and Reference tables.')
            self.Outputs.data.send(None)
            self.Outputs.processed.send(None)
            return

        if "path" not in self.data.domain or "path" not in self.reference.domain:
            self.error('You need a "path" column in both Data and Reference tables.')
            self.Outputs.data.send(None)
            self.Outputs.processed.send(None)
            return

        if "file size" not in self.data.domain:
            self.warning('There is no "file size" column in your Data table. All the files in Data will be considered as new files.')
            self.Outputs.data.send(self.data)
            self.Outputs.processed.send(None)
            return

        if "file size" not in self.reference.domain:
            self.warning('There is no "file size" column in your Reference table. All the files in Data will be considered as new files.')
            self.Outputs.data.send(self.data)
            self.Outputs.processed.send(None)
            return

        # Start progress bar
        self.progressBarInit()

        # Start threading
        self.thread = thread_management.Thread(self.check_for_sync, self.data, self.reference)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()


    def check_for_sync(self, table_data, table_reference, progress_callback=None, argself=None):
        new_root_dir = table_data[0]["root_dir"].value

        # Build lookup dictionary: (path, size) -> list of rows
        ref_lookup = defaultdict(list)
        for row in table_reference:
            relative_path = row["relative_path"].value.replace("\\", "/")
            file_size = row["file size"].value
            ref_lookup[(relative_path, file_size)].append(row)

        new_data_rows = []
        new_ref_rows = []

        root_meta = table_reference.domain["root_dir"]
        path_meta = table_reference.domain["path"]
        root_idx = table_reference.domain.metas.index(root_meta)
        path_idx = table_reference.domain.metas.index(path_meta)

        for row in table_data:
            relative_path = row["relative_path"].value.replace("\\", "/")
            file_size = row["file size"].value
            key = (relative_path, file_size)

            if key in ref_lookup:
                for ref_row in ref_lookup[key]:
                    vals = list(ref_row)
                    metas = list(ref_row.metas)
                    metas[root_idx] = new_root_dir
                    metas[path_idx] = os.path.join(new_root_dir, relative_path).replace("\\", "/")
                    new_ref_rows.append(vals + metas)
            else:
                vals = list(row)
                metas = list(row.metas)
                new_data_rows.append(vals + metas)

        out_data = Table.from_list(table_data.domain, new_data_rows)
        out_processed = Table.from_list(table_reference.domain, new_ref_rows)

        return out_data, out_processed



    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        data = result[0]
        processed_data = result[1]
        try:
            self.Outputs.data.send(data)
            self.Outputs.processed.send(processed_data)
            self.data = None
            self.reference = "default"
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        self.progressBarFinished()


    def post_initialized(self):
        pass


def progress_update(value, progress_callback):
    if progress_callback is not None:
        progress_value = float(value)
        progress_callback(progress_value)


def remove_from_table(filepath, table):
    """
    Remove rows from the Orange table where 'path' matches the given filepath.
    """
    filepath = Path(filepath).resolve()

    filtered_table = Table.from_list(
        domain=table.domain,
        rows=[row for row in table
              if Path(str(row["path"].value)).resolve() != filepath]
    )
    return filtered_table


def get_common_path(paths):
    """
    Find the common root directory among a list of file paths.

    - If the list contains only one path, the parent directory of that path
      is returned (to ensure the result is always a directory).
    - If the list contains multiple paths, their deepest shared parent
      directory is returned using os.path.commonpath.

    Parameters
    ----------
    paths : list[pathlib.Path] or list[str]
        A list of file or directory paths.

    Returns
    -------
    pathlib.Path
        The common root directory as a Path object.
    """
    paths = [str(p) for p in paths]

    if len(paths) == 1:
        return Path(paths[0]).parent
    else:
        return Path(os.path.commonpath(paths))



if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWFileSyncChecker()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
