import os

from AnyQt.QtCore import Qt, QTimer
from AnyQt.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QPushButton,
    QDialog,
    QLabel,
    QTextBrowser
)
from markdown import markdown

import Orange.data
from Orange.widgets import widget
from Orange.widgets.settings import Setting
from Orange.widgets.widget import Output


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import help_management
else:
    from orangecontrib.AAIT.utils import help_management


class PromptSettingsDialog(QDialog):
    """Prompt Settings window (right part of the sketch).

    Left side: a large, comfortable text field to write the full prompt.
    Right side: a vertical list of template buttons. Clicking one writes a
    predefined prompt (edit the TEMPLATES dict below) into the left field.
    """

    # Edit these to change what gets written into the description when a
    # template button is pressed.
    TEMPLATES = {
        "Service calling": """# Services
You have access to the following services.

## Service_1
### Description
Describe what the service does and when to use it.

### Parameters
- param1: description.
- param2: description.

## Service_2
### Description
Describe what the service does and when to use it.

### Parameters
- param1: description.
- param2: description.

## How to use a service
When you decide to use a service, use the following format:

```json
{
    "service": "<service_name>",
    "parameters": {
        "<param1>": "...",
        "<param2>": "...",
        ...
    }
}
```
""",

        "Code generator": """You have the ability to generate Python code. Use the following format:
```python
<your_code>
```
""",

        "Formated answer": """You must answer in the following format:
```json
{
    "<field1>": <value>,
    "<field2>": <value>,
    "<field3>": <value>,
    ...
}
```
""",

        "Agent (VLM)": """# Context
You are an AI assistant capable of solving tasks by performing actions.
You have two independant ways to perform actions:

1. Generate Python code
2. Invoke a service

After every action, you will receive the result before continuing.
Never assume or predict the result of an action. Wait for the observation before deciding the next step.

---

# Python
Generate Python code using the following format:

```python
<your_code>
```

The code is executed in a persistent Python environment: variables, imports, functions and files created during previous executions remain available.
After execution, you will receive stdout and stderr.

Use Python for tasks such as:

- Manipulating files
- Manipulating data
- Performing calculations
    
---

# Services
When you decide to invoke a service, use the following format:

```json
{
    "service": "<service_name>",
    "parameters": {
        "<param1>": "...",
        "<param2>": "...",
        ...
    }
}
```

You have access to the following services. Do not invent or invoke any other service. If another capability is needed, use Python instead.

## VisionModel

### Description
VisionModel loads an image, analyses its visual content and answers your prompt.
Invoke this service whenever information must be extracted from an image:

- OCR
- Extracting a date, an amount...
- Identifying its type
- Generating a description

### Parameters
- image_path: absolute path of an image file
- prompt: instruction sent to the vision model

---

# Working method
Solve the task step by step. At each step:

1. Decide the next action.
2. Perform exactly one action.
3. Wait for the result.
4. Continue.

Once you have finished, briefly summarize what you did, then end your response with [DONE].
Do not generate any additional Python code or invoke any service after completing the task.
"""
    }


    TOOLTIPS = {
        "Service calling": "Guide the model to use one or more services to complete the user's request.\nReplace the example service names, parameters and descriptions with your own.\n\nLeave the text inside curly braces { } unchanged, as it defines the required JSON output format.",
        "Code generator": "Your model will generate Python code that can be executed to perform actions.\nYou can execute the generated code using the 'Execute Script' widget.",
        "Formated answer": "This skill is ideal for extracting structured data from a document.\nReplace <fieldX> with the actual field names you want to extract.\nDo not modify <value>; it is a placeholder that the model will replace with the extracted value.",
        "Agent (VLM)": "Example of an agentic prompt to process files thanks to a Vision Language Model.\nBuild your workflow with a loop and 3 skill branches:\n- Python\n- Tool: VisionModel\n- Task finished: [DONE]."
    }

    def __init__(self, parent=None, prompt_text=""):
        super().__init__(parent)
        self.setWindowTitle("Skill")
        self.resize(900, 650)

        outer_layout = QVBoxLayout()

        main_layout = QHBoxLayout()

        # --- Left: prompt text ---
        left_layout = QVBoxLayout()
        left_label = QLabel("Description")
        left_layout.addWidget(left_label)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setAcceptRichText(False)
        self.prompt_edit.setPlaceholderText("Write your description (prompt) here...")
        if prompt_text:
            self.prompt_edit.setPlainText(prompt_text)
        left_layout.addWidget(self.prompt_edit)

        main_layout.addLayout(left_layout, stretch=3)

        # --- Right: template selector ---
        right_layout = QVBoxLayout()
        right_layout.setAlignment(Qt.AlignTop)

        templates_label = QLabel("Advanced skills")
        font = templates_label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        templates_label.setFont(font)
        right_layout.addWidget(templates_label)

        for template_name in self.TEMPLATES:
            template_button = QPushButton(template_name)
            template_button.setMinimumHeight(40)
            template_button.setToolTip(self.TOOLTIPS[template_name])

            template_button.clicked.connect(
                lambda checked=False, name=template_name: self.on_apply_template(name)
            )

            right_layout.addWidget(template_button)


        main_layout.addLayout(right_layout, stretch=2)

        outer_layout.addLayout(main_layout)

        # --- Bottom: confirm button ---
        confirm_layout = QHBoxLayout()
        confirm_layout.setAlignment(Qt.AlignRight)

        self.confirm_button = QPushButton("Confirm")
        self.confirm_button.clicked.connect(self.accept)
        confirm_layout.addWidget(self.confirm_button)

        outer_layout.addLayout(confirm_layout)

        self.setLayout(outer_layout)

    def on_apply_template(self, template_name):
        template_text = self.TEMPLATES.get(template_name, "")
        # append() always starts the new content on its own paragraph/line,
        # so whatever the user already wrote is preserved above it.
        self.prompt_edit.append(template_text)

    def get_prompt_text(self):
        return self.prompt_edit.toPlainText()


class OWSkillsManager(widget.OWWidget):
    name = "Agentic - Skills Manager"
    description = "Create and manage LLM prompts and their answer parsing rules"
    category = "AAIT - AGENTIC"
    icon = "icons/owskillsmanager.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owskillsmanager.svg"
    want_control_area = False
    priority = 1060

    # Settings
    request = Setting("")
    index_selected_prompt = Setting(0)
    prompt_settings = Setting([])

    class Outputs:
        data = Output("Data", Orange.data.Table)
        settings = Output("Skills", list)

    def __init__(self):
        super().__init__()
        # Qt Management
        self.resize(750, 550)
        self.setMinimumWidth(470)
        self.setMinimumHeight(400)

        self.build_left_panel()
        self.load_prompts_from_settings()

        # Data Management
        self.data = None
        self.autorun = True
        self.post_initialized()
        QTimer.singleShot(0, lambda: help_management.override_help_action(self) if help_management else None)

    def build_left_panel(self):
        """Build the main prompt-list window (list + preview + +/-/Edit + bottom buttons)."""
        main_layout = QVBoxLayout()
        self.mainArea.layout().addLayout(main_layout)

        # --- Top area: list | preview | +/-/edit buttons ---
        top_layout = QHBoxLayout()

        # Prompt list
        list_layout = QVBoxLayout()
        self.prompt_list = QListWidget()
        self.prompt_list.currentItemChanged.connect(self.on_prompt_selected)
        self.prompt_list.itemChanged.connect(self.on_prompt_renamed)
        list_layout.addWidget(self.prompt_list)
        top_layout.addLayout(list_layout, stretch=1)

        # Preview
        preview_layout = QVBoxLayout()
        self.preview_text = QTextBrowser()
        self.preview_text.setOpenExternalLinks(True)
        preview_layout.addWidget(self.preview_text)
        top_layout.addLayout(preview_layout, stretch=2)

        # +/-/Edit buttons
        button_layout = QVBoxLayout()
        button_layout.setAlignment(Qt.AlignTop)

        self.add_button = QPushButton("+")
        self.add_button.setFixedWidth(40)
        self.add_button.clicked.connect(self.on_add_prompt)
        button_layout.addWidget(self.add_button)

        self.remove_button = QPushButton("-")
        self.remove_button.setFixedWidth(40)
        self.remove_button.clicked.connect(self.on_remove_prompt)
        button_layout.addWidget(self.remove_button)

        self.edit_button = QPushButton("Edit")
        self.edit_button.setFixedWidth(60)
        self.edit_button.clicked.connect(self.on_edit_prompt)
        button_layout.addWidget(self.edit_button)

        self.export_button = QPushButton("Export")
        self.export_button.setFixedWidth(60)
        self.export_button.clicked.connect(self.on_export)
        self.import_button = QPushButton("Import")
        self.import_button.setFixedWidth(60)
        self.import_button.clicked.connect(self.on_import)
        button_layout.addStretch()
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.import_button)

        top_layout.addLayout(button_layout, stretch=0)

        main_layout.addLayout(top_layout, stretch=1)
        main_layout.addSpacing(20)

        # --- User request field ---
        request_layout = QVBoxLayout()
        request_label = QLabel("Request")
        request_layout.addWidget(request_label)

        self.request_edit = QTextEdit()
        self.request_edit.setPlaceholderText("Enter your request here...")
        self.request_edit.setText(self.request)
        self.request_edit.setMaximumHeight(80)
        request_layout.addWidget(self.request_edit)

        main_layout.addLayout(request_layout, stretch=0)

        # --- Bottom area: 2 unspecified buttons ---
        bottom_layout = QHBoxLayout()
        bottom_layout.setAlignment(Qt.AlignRight)

        self.send_button = QPushButton("Send Skill")
        self.send_button.clicked.connect(self.send)
        bottom_layout.addWidget(self.send_button)

        main_layout.addLayout(bottom_layout)

    def update_preview(self, text):
        self.preview_text.setHtml(
            markdown(
                text,
                extensions=[
                    "fenced_code",
                    "tables",
                ],
            )
        )

    def load_prompts_from_settings(self):
        """Populate the list widget from previously saved prompt_settings.

        List-widget row order always mirrors the order of self.prompt_settings,
        so a row index doubles as the index into self.prompt_settings.
        """
        for entry in self.prompt_settings:
            name = entry.get("name") or self._make_item_label(entry.get("description", ""))
            entry["name"] = name  # backfill for prompts saved before renaming existed
            item = self._make_list_item(name)
            self.prompt_list.addItem(item)
        if self.prompt_settings:
            self.prompt_list.setCurrentRow(self.index_selected_prompt)

    def on_prompt_selected(self, current, previous):
        entry = self._get_selected_entry()
        self.update_preview(entry.get("description", "") if entry else "")
        self.index_selected_prompt = self.prompt_list.currentRow()

    def on_add_prompt(self):
        dialog = PromptSettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            prompt_text = dialog.get_prompt_text()
            if not prompt_text.strip():
                return
            name = self._make_item_label(prompt_text)
            entry = {"description": prompt_text, "name": name}
            self.prompt_settings.append(entry)

            item = self._make_list_item(name)
            self.prompt_list.addItem(item)
            self.prompt_list.setCurrentRow(self.prompt_list.count() - 1)

    def on_remove_prompt(self):
        row = self.prompt_list.currentRow()
        if row >= 0:
            self.prompt_list.takeItem(row)
            del self.prompt_settings[row]

    def on_edit_prompt(self):
        row = self.prompt_list.currentRow()
        if row < 0 or row >= len(self.prompt_settings):
            return
        entry = self.prompt_settings[row]
        dialog = PromptSettingsDialog(
            self,
            prompt_text=entry.get("description", ""),
        )
        if dialog.exec() == QDialog.Accepted:
            updated_entry = {
                "description": dialog.get_prompt_text(),
                "name": entry.get("name", self._make_item_label(entry.get("description", ""))),
            }
            self.prompt_settings[row] = updated_entry
            # Note: the displayed name/label is intentionally left untouched here -
            # it's now independently editable by double-clicking the list item.
            if row == self.prompt_list.currentRow():
                self.update_preview(updated_entry["description"])

    def on_prompt_renamed(self, item):
        """Called when the user finishes double-click-editing a list item's name."""
        row = self.prompt_list.row(item)
        if not (0 <= row < len(self.prompt_settings)):
            return

        new_name = item.text().strip()
        if not new_name:
            # Don't allow an empty name - restore the previous one.
            new_name = self.prompt_settings[row].get("name") or self._make_item_label(
                self.prompt_settings[row].get("description", "")
            )
            self.prompt_list.blockSignals(True)
            item.setText(new_name)
            self.prompt_list.blockSignals(False)

        self.prompt_settings[row]["name"] = new_name


    def on_export(self):
        self.warning("")
        if not self.prompt_settings:
            self.warning("Nothing to export")
            return

        rows = []
        for row in self.prompt_settings:
            name = row["name"]
            prompt = row["description"]
            rows.append([name, prompt])

        import Orange.widgets.data.owsave as save_py
        saver = save_py.OWSave()

        var_name = Orange.data.StringVariable("skill")
        var_prompt = Orange.data.StringVariable("description")
        domain = Orange.data.Domain([], metas=[var_name, var_prompt])
        table = Orange.data.Table.from_list(domain=domain, rows=rows)

        saver.data = table
        saver.save_file_as()


    def on_import(self):
        self.error("")

        import Orange.widgets.data.owfile as file_py
        loader = file_py.OWFile()
        loader.browse_file()
        data = loader.data

        if not "skill" in data.domain:
            self.error('You need a "skill" column in the imported file (name of the skill).')
            return
        if not "description" in data.domain:
            self.error('You need a "description" column in the imported file (description of the skill).')
            return

        self.prompt_settings = []
        for row in data:
            name = row["skill"].value
            description = row["description"].value
            self.prompt_settings.append({"name": name, "description": description})

        self.prompt_list.clear()
        self.load_prompts_from_settings()


    @staticmethod
    def _make_list_item(name):
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        return item

    @staticmethod
    def _make_item_label(prompt_text, max_length=40):
        first_line = prompt_text.strip().splitlines()[0] if prompt_text.strip() else ""
        if len(first_line) > max_length:
            first_line = first_line[:max_length].rstrip() + "..."
        return first_line or "(empty prompt)"

    def get_request_text(self):
        return self.request_edit.toPlainText()

    def _get_selected_entry(self):
        """Return the {"description": ..., "name": ...} dict for the currently
        selected prompt, or None.

        Looks it up by row index in self.prompt_settings rather than storing the
        dict on the QListWidgetItem itself, since PyQt reconstructs plain dict/list
        values on every item.data() call instead of returning the original object -
        mutating that reconstructed copy silently loses the edit.
        """
        row = self.prompt_list.currentRow()
        if 0 <= row < len(self.prompt_settings):
            return self.prompt_settings[row]
        return None

    def send(self):
        """Send the selected prompt's text and its parser settings on separate outputs."""
        # Save request in settings
        self.request = self.get_request_text()

        # Get the selected skill
        entry = self._get_selected_entry()
        if entry is None:
            self.Outputs.data.send(None)
            self.Outputs.settings.send(None)
            return

        var1 = Orange.data.StringVariable("role")
        var2 = Orange.data.StringVariable("type")
        var3 = Orange.data.StringVariable("content")
        domain = Orange.data.Domain([], metas=[var1, var2, var3])
        table = Orange.data.Table.from_list(domain, rows=[["system", "text", entry.get("description", "")],
                                                          ["user", "text", self.get_request_text()]])

        self.Outputs.data.send(table)


    def run(self):
        # Send Data / Settings
        pass

    def post_initialized(self):
        pass


if __name__ == "__main__":
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(OWSkillsManager).run()