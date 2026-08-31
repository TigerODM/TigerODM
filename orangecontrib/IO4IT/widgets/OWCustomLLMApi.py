import os
import sys

import Orange.data
from AnyQt.QtWidgets import QApplication, QLabel
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import (
    QLineEdit, QTextBrowser, QSpinBox, QDoubleSpinBox, QPushButton, QCheckBox, QFileDialog
)

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.IO4IT.utils import custom_api
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.IO4IT.utils import custom_api
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWCustomLLMApi(widget.OWWidget):
    name = "Custom LLM API"
    description = ("Call a company-internal /chat/completions API, using the widely "
                    "adopted chat-completions message format, on the 'prompt' column "
                    "of the input data. Add an 'image paths' column to send images to "
                    "vision-capable models. Route, auth header and optional client "
                    "certificate (.pem) are configurable per instance.")
    category = "AAIT - LLM INTEGRATION"
    icon = "icons/owcustomllmapi.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owcustomllmapi.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owcustomllmapi.ui")
    want_control_area = False
    priority = 1090

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    base_url = Setting("")
    route = Setting("/v1/chat/completions")
    header_name = Setting("Authorization")
    auth_scheme = Setting("Bearer")
    api_key = Setting("")
    cert_path = Setting("")
    cert_is_ca = Setting(False)
    use_proxy = Setting(False)
    proxy_url = Setting("")
    model = Setting("")
    max_tokens = Setting(4096)
    temperature = Setting(0.4)

    @Inputs.data
    def set_data(self, in_data):
        self.error("")
        self.data = in_data
        if in_data is None:
            self.Outputs.data.send(None)
            return
        if "prompt" not in in_data.domain:
            self.error("Input table needs a 'prompt' column.")
            self.Outputs.data.send(None)
            return
        if "Answer" in in_data.domain:
            self.error('You cannot have "Answer" in your input data. Please rename or remove the column.')
            self.Outputs.data.send(None)
            return
        self.run()

    def __init__(self):
        super().__init__()
        self.setFixedWidth(700)
        self.setFixedHeight(695)
        uic.loadUi(self.gui, self)

        self.label_description = self.findChild(QLabel, 'Description')

        self.line_base_url = self.findChild(QLineEdit, 'lineBaseUrl')
        self.line_base_url.setText(self.base_url)
        self.line_base_url.editingFinished.connect(self.update_parameters)

        self.line_route = self.findChild(QLineEdit, 'lineRoute')
        self.line_route.setText(self.route)
        self.line_route.editingFinished.connect(self.update_parameters)

        self.line_header_name = self.findChild(QLineEdit, 'lineHeaderName')
        self.line_header_name.setText(self.header_name)
        self.line_header_name.editingFinished.connect(self.update_parameters)

        self.line_auth_scheme = self.findChild(QLineEdit, 'lineAuthScheme')
        self.line_auth_scheme.setText(self.auth_scheme)
        self.line_auth_scheme.editingFinished.connect(self.update_parameters)

        self.line_api_key = self.findChild(QLineEdit, 'lineApiKey')
        self.line_api_key.setText(self.api_key)
        self.line_api_key.editingFinished.connect(self.update_parameters)

        self.line_cert_path = self.findChild(QLineEdit, 'lineCertPath')
        self.line_cert_path.setText(self.cert_path)
        self.line_cert_path.editingFinished.connect(self.update_parameters)

        self.button_browse_cert = self.findChild(QPushButton, 'buttonBrowseCert')
        self.button_browse_cert.clicked.connect(self.browse_cert)

        self.check_cert_is_ca = self.findChild(QCheckBox, 'checkCertIsCa')
        self.check_cert_is_ca.setChecked(self.cert_is_ca)
        self.check_cert_is_ca.stateChanged.connect(self.update_parameters)

        self.check_use_proxy = self.findChild(QCheckBox, 'checkUseProxy')
        self.check_use_proxy.setChecked(self.use_proxy)
        self.check_use_proxy.stateChanged.connect(self.update_parameters)

        self.line_proxy_url = self.findChild(QLineEdit, 'lineProxyUrl')
        self.line_proxy_url.setText(self.proxy_url)
        self.line_proxy_url.editingFinished.connect(self.update_parameters)

        self.line_model = self.findChild(QLineEdit, 'lineModel')
        self.line_model.setText(self.model)
        self.line_model.editingFinished.connect(self.update_parameters)

        self.box_max_tokens = self.findChild(QSpinBox, 'boxMaxTokens')
        self.box_max_tokens.setValue(self.max_tokens)
        self.box_max_tokens.editingFinished.connect(self.update_parameters)

        self.box_temperature = self.findChild(QDoubleSpinBox, 'boxTemperature')
        self.box_temperature.setValue(self.temperature)
        self.box_temperature.editingFinished.connect(self.update_parameters)

        self.push_button_run = self.findChild(QPushButton, 'pushButtonRun')
        self.push_button_run.clicked.connect(self.run)

        self.textBrowser = self.findChild(QTextBrowser, 'textBrowser')

        self.data = None
        self.thread = None
        self.can_run = True
        self.result = None

        self.post_initialized()

    def update_parameters(self):
        self.base_url = self.line_base_url.text().strip()
        self.route = self.line_route.text().strip() or "/v1/chat/completions"
        self.header_name = self.line_header_name.text().strip() or "Authorization"
        self.auth_scheme = self.line_auth_scheme.text().strip()
        self.api_key = self.line_api_key.text()
        self.cert_path = self.line_cert_path.text().strip()
        self.cert_is_ca = self.check_cert_is_ca.isChecked()
        self.use_proxy = self.check_use_proxy.isChecked()
        self.proxy_url = self.line_proxy_url.text().strip()
        self.model = self.line_model.text().strip()
        self.max_tokens = self.box_max_tokens.value()
        self.temperature = self.box_temperature.value()

    def browse_cert(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select a .pem file", "", "PEM files (*.pem);;All files (*)")
        if path:
            self.line_cert_path.setText(path)
            self.update_parameters()

    def build_config(self):
        return {
            "base_url": self.base_url,
            "route": self.route,
            "header_name": self.header_name,
            "auth_scheme": self.auth_scheme,
            "api_key": self.api_key,
            "cert_path": self.cert_path,
            "cert_is_ca": self.cert_is_ca,
            "use_proxy": self.use_proxy,
            "proxy_url": self.proxy_url,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

    def run(self):
        self.error("")
        self.warning("")

        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        if self.data is None:
            self.Outputs.data.send(None)
            return
        if "prompt" not in self.data.domain:
            self.error("Input table needs a 'prompt' column.")
            self.Outputs.data.send(None)
            return

        if not self.base_url:
            self.error("Base URL is required.")
            self.Outputs.data.send(None)
            return

        if not self.api_key:
            self.error("API key is required.")
            self.Outputs.data.send(None)
            return

        if not self.can_run:
            return

        self.progressBarInit()
        self.textBrowser.setText("")

        self.thread = thread_management.Thread(custom_api.generate_answers, self.data, self.build_config())
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
        if result is None:
            self.error("Unable to reach the API or an error occurred during generation.")
            self.Outputs.data.send(None)
            return
        try:
            self.result = result
            self.Outputs.data.send(result)
        except Exception as e:
            print("An error occurred when sending out_data:", e)
            self.Outputs.data.send(None)
            return

    def handle_finish(self):
        print("Generation finished")
        self.progressBarFinished()

    def post_initialized(self):
        pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWCustomLLMApi()
    my_widget.show()
    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
