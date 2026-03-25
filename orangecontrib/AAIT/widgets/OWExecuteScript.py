import os
import re
import io
import sys
import code
import subprocess
import contextlib
import traceback


from Orange.data import Table, Domain, StringVariable
from AnyQt.QtWidgets import QApplication, QCheckBox, QPushButton
from AnyQt import QtWidgets, QtGui
from Orange.widgets.settings import Setting
from AnyQt.QtCore import QTimer



if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, base_widget, help_management
else:
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import thread_management, base_widget, help_management


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWExecuteScript(base_widget.BaseListWidget):
    name = "Execute Script"
    description = "Locally execute the scripts contained in the column 'Script'."
    category = "AAIT - TOOLBOX"
    icon = "icons/owexecutescript.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owexecutescript.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owexecutescript_TEST.ui")
    want_control_area = False
    priority = 1060

    # Settings
    interactive = Setting(False)

    # class Inputs:
    #     data = Input("Data", Orange.data.Table)
    #
    # class Outputs:
    #     data = Output("Data", Orange.data.Table)
    #
    # @Inputs.data
    # def set_data(self, in_data):
    #     self.data = in_data
    #     if self.data:
    #         self.var_selector.add_variables(self.data.domain)
    #         self.var_selector.select_variable_by_name(self.selected_column_name)
    #     if self.autorun:
    #         self.run()

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(500)
        # uic.loadUi(self.gui, self)
        # Checkbox
        self.checkbox_mode = self.findChild(QCheckBox, 'checkBox')
        self.checkbox_mode.setChecked(self.interactive)
        self.checkbox_mode.toggled.connect(self.toogle_persistent)
        # Button Show
        self.button_show = self.findChild(QPushButton, 'pushButton')
        self.button_show.clicked.connect(self.show_script)
        # Button Reset
        self.button_reset = self.findChild(QPushButton, "pushButton_2")
        self.button_reset.clicked.connect(self.reset_state)


        # Data Management
        self.data = None
        self.code = None
        self.console = None
        self.script_text = ""
        self.autorun = True
        self.thread = None
        self.result = None
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))


    def toogle_persistent(self, enabled):
        if enabled:
            self.interactive = True
            if self.console is None:
                self.console = SmartConsole()
        else:
            self.interactive = False

    def reset_state(self):
        self.console = SmartConsole()
        self.script_text = ""

    def show_script(self):
        popup = ScriptPopup(self.script_text, self)
        if hasattr(popup, "exec"):
            popup.exec()
        else:
            popup.exec_()
    # def on_variable_selected(self, var_name):
    #     """Update the selected column when the user clicks an item."""
    #     self.selected_column_name = var_name


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
            return

        if not isinstance(self.data.domain[self.selected_column_name], StringVariable):
            self.error('You must select a text variable.')
            return

        # Start progress bar
        self.progressBarInit()

        # Thread management
        if self.interactive:
            # Interactive mode: Run in main thread for GUI compatibility
            self.result = self.execute_scripts_in_table(self.data, self.selected_column_name)
            self.handle_result(self.result)
            self.handle_finish()
        else:
            self.thread = thread_management.Thread(self.execute_scripts_in_table, self.data, self.selected_column_name)
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
        print("Scripts executed !")
        self.progressBarFinished()


    def post_initialized(self):
        pass


    def execute_scripts_in_table(self, table, selected_var, progress_callback=None, argself=None):
        # Copy of input data
        data = table.copy()
        attr_dom = list(data.domain.attributes)
        metas_dom = list(data.domain.metas)
        class_dom = list(data.domain.class_vars)

        # Iterate on the data Table
        rows = []
        for i, row in enumerate(data):
            # Get the rest of the data
            features = [row[x] for x in attr_dom]
            targets = [row[y] for y in class_dom]
            metas = list(data.metas[i])
            # Execute the script for the given row
            output, error = self.execute_script(row[selected_var].value)
            # Store the output / error
            new_row = features + targets + metas + [output, error]
            rows.append(new_row)
            if progress_callback is not None:
                progress_value = float(100 * (i + 1) / len(data))
                progress_callback(progress_value)
            if argself is not None:
                if argself.stop:
                    break

        # Create new Domain for new columns
        script_dom = [StringVariable("Script output"), StringVariable("Script error")]
        domain = Domain(attributes=attr_dom, metas=metas_dom + script_dom, class_vars=class_dom)
        # Create and return table
        out_data = Table.from_list(domain=domain, rows=rows)
        return out_data


    def execute_script(self, script: str):
        if self.interactive:
            if self.console is None:
                self.console = SmartConsole()

            executable_code = f"exec({script!r})"
            self.script_text += f"\n\n{script}" if self.script_text else script


            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.console.last_error = ""
                try:
                    self.console.push(executable_code)
                except Exception:
                    pass  # all errors are captured in showtraceback

            output = stdout.getvalue()
            # Append any exception trace
            error = stderr.getvalue() + self.console.last_error
            return output, error

        else:
            try:
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    text=True,
                    check=True
                )
                return result.stdout, result.stderr
            except subprocess.CalledProcessError as e:
                return e.stdout, e.stderr


class SmartConsole(code.InteractiveConsole):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_error = ""
        self.push("import matplotlib; matplotlib.use('QtAgg')")

    def push(self, line):
        if line.startswith("!pip "):
            cmd = line[1:].split()
            subprocess.check_call([sys.executable, "-m"] + cmd)
            return False
        return super().push(line)

    def showtraceback(self):
        # Capture the exception instead of printing to terminal
        self.last_error = traceback.format_exc()




class PythonHighlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)

        # Styles simples : couleur + gras/italique
        keyword_format = QtGui.QTextCharFormat()
        keyword_format.setForeground(QtGui.QColor("#569CD6"))
        keyword_format.setFontWeight(QtGui.QFont.Bold)

        builtin_format = QtGui.QTextCharFormat()
        builtin_format.setForeground(QtGui.QColor("#4EC9B0"))

        string_format = QtGui.QTextCharFormat()
        string_format.setForeground(QtGui.QColor("#CE9178"))

        comment_format = QtGui.QTextCharFormat()
        comment_format.setForeground(QtGui.QColor("#6A9955"))
        comment_format.setFontItalic(True)

        number_format = QtGui.QTextCharFormat()
        number_format.setForeground(QtGui.QColor("#B5CEA8"))

        # Expressions régulières associées aux styles
        self.rules = []
        keywords = [
            "def", "class", "if", "elif", "else", "while", "for", "try", "except",
            "finally", "with", "as", "return", "import", "from", "pass", "break",
            "continue", "and", "or", "not", "in", "is", "lambda", "yield", "None",
            "True", "False"
        ]
        self.rules += [(r"\b" + kw + r"\b", keyword_format) for kw in keywords]

        builtins = [
            "print", "len", "range", "int", "float", "str", "list", "dict", "set", "tuple"
        ]
        self.rules += [(r"\b" + bi + r"\b", builtin_format) for bi in builtins]

        self.rules.append((r"\".*?\"|'.*?'", string_format))   # chaînes
        self.rules.append((r"#.*", comment_format))            # commentaires
        self.rules.append((r"\b[0-9]+\b", number_format))      # nombres

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for match in re.finditer(pattern, text):
                start, end = match.span()
                self.setFormat(start, end - start, fmt)





# --- Popup window to display code ---
class ScriptPopup(QtWidgets.QDialog):
    def __init__(self, code_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Script Viewer")
        self.resize(600, 400)

        layout = QtWidgets.QVBoxLayout(self)

        self.code_view = QtWidgets.QPlainTextEdit()
        self.code_view.setReadOnly(True)
        self.code_view.setFont(QtGui.QFont("Courier New", 10))
        self.code_view.setPlainText(code_text)

        layout.addWidget(self.code_view)

        # Apply Python syntax highlighting
        self.highlighter = PythonHighlighter(self.code_view.document())



if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWExecuteScript()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
