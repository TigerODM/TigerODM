import os
import sys
import base64
import ast
from openai import OpenAI
import Orange
from Orange.data import StringVariable
from Orange.widgets.widget import OWWidget, Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QApplication, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.IO4IT.utils import keys_manager
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.IO4IT.utils import keys_manager

class ChatGpt(OWWidget):
    name = "CallChatGptApi"
    description = "Call to chatgpt API. You need to provide a prompt and an api_keys. You call also add an image_paths and a system_prompt if you want."
    icon = "icons/chatgpt.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/chatgpt.png"
    priority = 3000
    max_tokens = Setting(4096)
    temperature = Setting(0)
    model = Setting("gpt-4o")
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owchatgpt.ui")
    want_control_area = False
    category = "AAIT - LLM INTEGRATION"

    class Inputs:
        data = Input("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        if in_data is None:
            return
        if "prompt" not in in_data.domain:
            self.error("input table need a prompt column")
            return
        self.prompt = in_data.get_column("prompt")[0]
        if "image_paths" in in_data.domain:
            self.image_paths = in_data.get_column("image_paths")[0]
        if "api_keys" not in in_data.domain:
            self.api_keys = keys_manager.lire_config_cli_api("CHAT_GPT")
            if keys_manager.lire_config_cli_api("CHAT_GPT") is None:
                self.error("input table need a api_keys column or a folder API with you CHAT_GPT keys in aait store")
        if self.api_keys is None:
            self.api_keys = in_data.get_column("api_keys")[0]
        if "system_prompt" in in_data.domain:
            self.system_prompt = in_data.get_column("system_prompt")[0]
        self.data = in_data
        self.run()

    class Outputs:
        data = Output("Data", Orange.data.Table)

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(400)
        self.setFixedHeight(300)
        uic.loadUi(self.gui, self)
        self.edit_model = self.findChild(QLineEdit, 'modelName')
        self.edit_model.setPlaceholderText("Model name")
        self.edit_model.setText(self.model)
        self.edit_model.editingFinished.connect(self.update_parameters)

        self.edit_max_tokens = self.bind_spinbox("boxMaxTokens", self.max_tokens)
        self.edit_temperature = self.bind_spinbox("boxTemperature", self.temperature, is_double=True)
        self.pushButton_call_api =self.findChild(QPushButton, 'callApi')
        self.pushButton_call_api.clicked.connect(self.run)

        self.data = None
        self.prompt = None
        self.image_paths = None
        self.api_keys = None
        self.system_prompt = ""
        self.text_response = None
        self.thread = None
        self.run()

    def bind_spinbox(self, name, value, is_double=False):
        widget_type = QDoubleSpinBox if is_double else QSpinBox
        box = self.findChild(widget_type, name)
        box.setValue(value)
        box.editingFinished.connect(self.update_parameters)
        return box

    def update_parameters(self):
        self.max_tokens = self.edit_max_tokens.value()
        self.temperature = self.edit_temperature.value()
        self.model = self.edit_model.text()

    def generate_answers(self):
        try:
            client = OpenAI(api_key=self.api_keys)
            system_content = []
            if getattr(self, "system_prompt", None):
                system_content = [{"type": "input_text", "text": str(self.system_prompt)}]

            user_content = []
            if isinstance(self.prompt, list):
                user_content.extend(self.prompt)
            else:
                user_content.append({"type": "input_text", "text": str(self.prompt)})

            if getattr(self, "image_paths", None):
                # normalize image_paths to a list
                if isinstance(self.image_paths, str):
                    self.image_paths = ast.literal_eval(self.image_paths)

                for img_path in self.image_paths:
                    filename = os.path.basename(img_path)
                    user_content.append({"type": "input_text", "text": f"Photo : {filename}"})

                    with open(img_path, "rb") as f:
                        b64_img = base64.b64encode(f.read()).decode("utf-8")

                    mime = "image/png" if filename.lower().endswith(".png") else "image/jpeg"
                    user_content.append({
                        "type": "input_image",
                        "image_url": f"data:{mime};base64,{b64_img}",
                    })

            response = client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ],
                #max_output_tokens=self.max_tokens,
                # temperature=self.temperature,
            )
            self.text_response = response.output_text



            if self.text_response is None:
                self.error("No response from model.")

        except Exception as e:
            self.error(f"Error: {e}")
            return

    def run(self):
        self.error("")
        self.warning("")
        if self.data is None:
            return

        if self.prompt == "" or self.prompt is None:
            self.error("No prompt provided.")
            return

        if self.api_keys is None:
            self.error("No api keys provided.")
            return

        self.progressBarInit()
        self.thread = thread_management.Thread(self.generate_answers)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    def handle_progress(self, progress) -> None:
        value = progress[0]
        text = progress[1]
        if value is not None:
            self.progressBarSet(value)
        if text is None:
            self.textBrowser.setText("")
        else:
            self.textBrowser.insertPlainText(text)

    def handle_result(self, result):
        new_name_column = StringVariable("answer")
        table = self.data.add_column(new_name_column, [self.text_response])
        self.Outputs.data.send(table)

    def handle_finish(self):
        print("Generation finished")
        self.progressBarFinished()

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = ChatGpt()
    my_widget.show()

    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
