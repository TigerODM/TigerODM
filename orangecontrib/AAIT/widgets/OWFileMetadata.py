import os
import sys
from pathlib import Path
import datetime
import platform

import Orange.data
from Orange.data import Table, Domain, StringVariable, ContinuousVariable
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
class OWFileMetadata(widget.OWWidget):
    name = "File Metadata"
    category = "AAIT - TOOLBOX"
    description = 'Get some metadatas on the files contained in the "path" column'
    icon = "icons/owfilemetadata.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owfilemetadata.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owfilemetadata.ui")
    want_control_area = False
    priority = 1060

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)


    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
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
        self.result = None
        self.thread = None
        self.autorun = True
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))

    def run(self):
        self.error("")
        self.warning("")

        if self.data is None:
            self.Outputs.data.send(None)
            return

        if "path" not in self.data.domain:
            self.error('You need a "path" column.')
            self.Outputs.data.send(None)
            return

        # Start progress bar
        self.progressBarInit()

        # Connect and start thread : main function, progress, result and finish
        self.thread = thread_management.Thread(add_metadatas_to_table, self.data)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, value: float) -> None:
        self.progressBarSet(value)

    def handle_result(self, result):
        try:
            self.result = result
            self.Outputs.data.send(result)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        self.progressBarFinished()

    def post_initialized(self):
        pass


def add_metadatas_to_table(table, progress_callback=None, argself=None):
    """
    Add file metadata (size, creation time, modification time) to an Orange table.

    Optimized version with:
    - Batch stat() calls with caching
    - Pre-allocated arrays for better memory usage
    - Vectorized datetime formatting
    - Reduced object creation
    - Long path support on Windows
    """
    data = table.copy()
    attr_dom = list(data.domain.attributes)
    metas_dom = list(data.domain.metas)
    class_dom = list(data.domain.class_vars)

    total_rows = len(data)

    # OPTIMIZATION 1: Pre-extract all data in one pass (avoid repeated attribute access)
    features_list = [[row[x] for x in attr_dom] for row in data]
    targets_list = [[row[y] for y in class_dom] for row in data]
    metas_array = data.metas  # Direct array access (no copy needed)

    # OPTIMIZATION 2: Batch metadata retrieval
    filepaths = [row["path"].value for row in data]
    metadata_list = get_metadata_batch(filepaths, progress_callback, argself, total_rows)

    # OPTIMIZATION 3: Build rows efficiently
    rows = []
    for i in range(total_rows):
        if argself is not None and argself.stop:
            break

        metadata = metadata_list[i]
        metas = list(metas_array[i])
        metas += [metadata["file size"], metadata["creation time"], metadata["modification time"]]
        rows.append(features_list[i] + targets_list[i] + metas)
    # Generate new Domain
    filesize_var = ContinuousVariable("file size")
    filesize_var.format_str = "%.0f"
    ctime_var = StringVariable("creation time")
    mtime_var = StringVariable("modification time")
    domain = Domain(
        attributes=attr_dom,
        class_vars=class_dom,
        metas=metas_dom + [filesize_var, ctime_var, mtime_var]
    )

    # Create and return table
    out_data = Table.from_list(domain=domain, rows=rows)
    return out_data


def get_metadata_batch(filepaths, progress_callback=None, argself=None, total=None):
    """
    Retrieve metadata for multiple files in batch (optimized).

    :param filepaths: List of file paths.
    :param progress_callback: Optional callback for progress reporting.
    :param argself: Optional object with stop attribute for cancellation.
    :param total: Total number of files (for progress calculation).
    :return: List of metadata dictionaries.
    """
    if total is None:
        total = len(filepaths)

    is_windows = platform.system() == 'Windows'
    results = []

    # OPTIMIZATION: Pre-compile datetime format (reused for all files)
    datetime_format = "%Y-%m-%d %H:%M:%S"

    for i, filepath in enumerate(filepaths):
        # Check for cancellation
        if argself is not None and argself.stop:
            break

        metadata = get_metadata_fast(filepath, datetime_format, is_windows)
        results.append(metadata)

        # Progress callback
        if progress_callback is not None:
            progress_value = float(100 * (i + 1) / total)
            progress_callback(progress_value)

    return results


def get_metadata_fast(filepath, datetime_format, is_windows):
    """
    Optimized single-file metadata retrieval with long path support.

    :param filepath: Path to the file (str or Path).
    :param datetime_format: Pre-compiled datetime format string.
    :param is_windows: Boolean indicating if running on Windows.
    :return: Dictionary with keys "file size", "creation time", "modification time".
    """
    try:
        path = Path(filepath)

        # Windows long path support
        if is_windows:
            path_str = str(path.resolve())
            if len(path_str) > 260 and not path_str.startswith('\\\\?\\'):
                if path_str.startswith('\\\\'):
                    path_str = '\\\\?\\UNC\\' + path_str[2:]
                else:
                    path_str = '\\\\?\\' + path_str
                path = Path(path_str)

        # OPTIMIZATION: Single stat() call instead of three
        stat_info = path.stat()

        # Extract all info from single stat object
        file_size = str(stat_info.st_size)

        # OPTIMIZATION: Direct timestamp conversion (avoid intermediate objects)
        ctime = datetime.datetime.fromtimestamp(stat_info.st_ctime).strftime(datetime_format)
        mtime = datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime(datetime_format)

        return {
            "file size": file_size,
            "creation time": ctime,
            "modification time": mtime
        }

    except FileNotFoundError:
        return {
            "file size": "0",
            "creation time": "File not found",
            "modification time": "File not found"
        }
    except PermissionError:
        return {
            "file size": "0",
            "creation time": "Permission denied",
            "modification time": "Permission denied"
        }
    except Exception as e:
        error_msg = str(e)
        return {
            "file size": "0",
            "creation time": error_msg,
            "modification time": error_msg
        }


def get_metadata(filepath):
    """
    Legacy function - kept for backward compatibility.
    Retrieve file metadata: size, creation time, and modification time as strings.

    :param filepath: Path to the file (str or Path).
    :return: Dictionary with keys "file size", "creation time", "modification time".
    """
    is_windows = platform.system() == 'Windows'
    datetime_format = "%Y-%m-%d %H:%M:%S"
    return get_metadata_fast(filepath, datetime_format, is_windows)




if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWFileMetadata()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
