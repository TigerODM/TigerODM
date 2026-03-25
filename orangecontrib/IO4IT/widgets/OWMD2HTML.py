import os
import sys

import markdown
import html2text

import Orange.data
from Orange.data import StringVariable
from AnyQt.QtWidgets import QApplication
from Orange.widgets.settings import Setting
from Orange.widgets.utils.signals import Input, Output
from AnyQt.QtWidgets import QComboBox

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, base_widget
else:
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import thread_management, base_widget


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWMD2HTML(base_widget.BaseListWidget):
    name = "Markdown ⇄ HTML"
    description = "This widget converts text content between Markdown and HTML formats."
    category = "AAIT - TOOLBOX"
    icon = "icons/owmd2html.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owmd2html.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmd2html.ui")
    want_control_area = False
    priority = 1060

    # Settings
    transform = Setting("Markdown to HTML")

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

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
        self.setFixedHeight(500)
        # uic.loadUi(self.gui, self)
        # Combobox for Ascending or Descending choice
        self.combobox_transform = self.findChild(QComboBox, "comboBox")
        self.combobox_transform.setCurrentIndex(self.combobox_transform.findText(self.transform))
        self.combobox_transform.currentTextChanged.connect(self.on_transform_changed)

        # Data Management
        self.data = None
        self.autorun = True
        self.thread = None
        self.result = None
        self.post_initialized()


    def on_transform_changed(self, text):
        self.transform = text
        self.run()


    def run(self):
        self.warning("")
        self.error("")

        # If Thread is already running, interrupt it
        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            return

        if not self.selected_column_name in self.data.domain:
            self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
            self.Outputs.data.send(None)
            return

        if not isinstance(self.data.domain[self.selected_column_name], StringVariable):
            self.error('You must select a text variable.')
            self.Outputs.data.send(None)
            return

        # Start progress bar
        self.progressBarInit()

        # Thread management
        self.thread = thread_management.Thread(md2html_on_table, self.data, self.selected_column_name, self.transform)
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


def md2html_on_table(table, column_name, transform="Markdown to HTML", progress_callback=None, argself=None):
    """
    Convert text in a specified column of an Orange Table between Markdown and HTML.

    Args:
        table (Orange.data.Table): The table containing the text to convert.
        column_name (str): Name of the column containing the text to transform.
        transform (str, optional): Direction of conversion. Either
            "Markdown to HTML" or "HTML to Markdown". Defaults to "Markdown to HTML".
        progress_callback (callable, optional): Function called with progress percentage (0-100)
            during conversion. Defaults to None.
        argself (object, optional): Object with a boolean attribute `stop` to allow
            early interruption. Defaults to None.

    Returns:
        Orange.data.Table: A new table with an additional meta column containing
        the converted text. The column is named "HTML" for Markdown → HTML conversion,
        or "Markdown" for HTML → Markdown conversion.

    Raises:
        ValueError: If `column_name` does not exist in the table.
    """
    if column_name not in table.domain:
        raise ValueError(f"Column '{column_name}' not found.")

    data = table.copy()
    if transform == "Markdown to HTML":
        func = markdown.markdown
        name = "HTML"
    else:
        func = html2text.html2text
        name = "Markdown"

    results = []
    for i, row in enumerate(data):
        text = row[column_name].value
        text_converted = func(text)
        results.append(text_converted)

        if progress_callback is not None:
            progress_value = float(100 * (i + 1) / len(data))
            progress_callback(progress_value)
        if argself is not None:
            if argself.stop:
                break

    var = StringVariable(name=name)
    data = data.add_column(var, results, to_metas=True)
    return data


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWMD2HTML()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
