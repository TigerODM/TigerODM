import os
import re
import sys
from json_repair import repair_json


from Orange.data import Table, Domain, StringVariable
from AnyQt.QtWidgets import QApplication
from Orange.widgets.settings import Setting
from AnyQt.QtCore import QTimer



if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.AAIT.utils import base_widget, help_management
else:
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.AAIT.utils import base_widget, help_management


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWSkillsIdentifier(base_widget.BaseListWidget):
    name = "Agentic - Skills Identifier"
    description = "Identify the skills used by a language model (tool usage, code, data extraction...)."
    category = "AAIT - AGENTIC"
    icon = "icons/owexecutescript.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owexecutescript.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owexecutescript_TEST.ui")
    want_control_area = False
    priority = 1060

    # Settings
    selected_column_name = Setting("content")


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(500)
        # uic.loadUi(self.gui, self)

        # Data Management
        self.data = None
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))


    def run(self):
        self.warning("")
        self.error("")

        if self.data is None:
            self.Outputs.data.send(None)
            return

        if not self.selected_column_name in self.data.domain:
            self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
            return

        if not isinstance(self.data.domain[self.selected_column_name], StringVariable):
            self.error('You must select a text variable.')
            return


        out_data = self.parse(self.data)
        self.Outputs.data.send(out_data)


    def parse(self, data):

        row = data[-1]
        answer = row[self.selected_column_name].value

        entries = []

        # Detect skills
        entries.extend(parse_python(answer))
        entries.extend(parse_json_tool(answer))
        entries.extend(parse_json_data(answer))
        entries.extend(parse_question(answer))

        # Fallback: no skill detected
        if not entries:
            entries.append({
                "skill": "None",
                "content": answer,
            })

        return build_output_table(entries)


    def post_initialized(self):
        pass


def parse_python(text):
    results = []

    for match in PYTHON_RE.finditer(text):
        results.append({
            "skill": "python",
            "content": match.group(1).strip(),
        })

    return results


def parse_json_tool(text):
    results = []

    for raw in extract_json_strings(text):

        repaired, obj = repair_and_load(raw)

        if not isinstance(obj, dict):
            continue

        if "tool" not in obj or "arguments" not in obj:
            continue

        result = {
            "skill": obj["tool"],   # <-- tool name becomes the skill
            "content": raw,
        }

        arguments = obj.get("arguments", {})

        if isinstance(arguments, dict):
            result.update(arguments)

        results.append(result)

    return results


def parse_json_data(text):
    results = []

    for raw in extract_json_strings(text):

        repaired, obj = repair_and_load(raw)

        if not isinstance(obj, dict):
            continue

        if "tool" in obj and "arguments" in obj:
            continue

        result = {
            "skill": "data",
            "content": raw,
        }
        result.update(obj)
        results.append(result)
    return results


CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def parse_question(text):
    # Remove fenced code blocks
    plain_text = CODE_BLOCK_RE.sub("", text).strip()

    if "?" in plain_text:
        return [{
            "skill": "question",
            "content": plain_text,
        }]

    return []



PYTHON_RE = re.compile(r"```python\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json_strings(text):
    """
    Yield every balanced {...} block found in the text.

    The block is not required to be valid JSON.
    """
    depth = 0
    inside_string = False
    escape = False
    start = None

    for i, c in enumerate(text):

        if escape:
            escape = False
            continue

        if c == "\\":
            escape = True
            continue

        if c == '"':
            inside_string = not inside_string
            continue

        if inside_string:
            continue

        if c == "{":
            if depth == 0:
                start = i
            depth += 1

        elif c == "}":
            if depth:
                depth -= 1

                if depth == 0 and start is not None:
                    yield text[start:i + 1]
                    start = None



def repair_and_load(raw):
    """
    Try to repair malformed JSON and return the parsed object.
    """
    try:
        repaired = repair_json(raw)
        return repaired, repair_json(raw, return_objects=True)
    except Exception:
        return None, None


def build_output_table(entries):
    # Collect every dynamic key except the fixed columns
    extra_keys = set()

    for entry in entries:
        extra_keys.update(
            k for k in entry
            if k not in ("skill", "content")
        )

    extra_keys = sorted(extra_keys)

    metas = [
        StringVariable("skill"),
        StringVariable("content"),
    ] + [
        StringVariable(key)
        for key in extra_keys
    ]

    domain = Domain([], metas=metas)

    rows = []

    for entry in entries:

        row = [
            entry.get("skill", ""),
            entry.get("content", ""),
        ]

        row.extend(
            str(entry.get(key, ""))
            for key in extra_keys
        )

        rows.append(row)

    return Table.from_list(domain, rows)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWSkillsIdentifier()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
