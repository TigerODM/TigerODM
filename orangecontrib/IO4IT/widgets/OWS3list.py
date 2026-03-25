import boto3
from Orange.widgets.widget import OWWidget, Output
from Orange.widgets.settings import Setting
from Orange.widgets import gui
from AnyQt.QtWidgets import QLineEdit, QApplication
from Orange.data import Table, Domain, StringVariable, ContinuousVariable
import os

class OWS3FileLister(OWWidget):
    name = "S3 File Lister"
    description = "List the files in an S3 bucket and display their details."
    icon = "icons/list_aws.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/list_aws.png"
    priority = 10
    category = "AAIT - API"

    # Paramètres utilisateur
    access_key = Setting("")
    secret_key = Setting("")
    bucket_name = Setting("")
    allowed_extensions = Setting("*")
    folder_name = Setting("")

    class Outputs:
        data = Output("Data", Table)

    def __init__(self):
        super().__init__()

        # Interface utilisateur
        self.access_key_input = QLineEdit(self)
        self.access_key_input.setPlaceholderText("AWS Access Key")
        self.access_key_input.setText(self.access_key)
        self.access_key_input.editingFinished.connect(self.update_settings)
        gui.widgetBox(self.controlArea, orientation='vertical').layout().addWidget(self.access_key_input)

        self.secret_key_input = QLineEdit(self)
        self.secret_key_input.setPlaceholderText("AWS Secret Key")
        self.secret_key_input.setText(self.secret_key)
        self.secret_key_input.editingFinished.connect(self.update_settings)
        gui.widgetBox(self.controlArea, orientation='vertical').layout().addWidget(self.secret_key_input)

        self.bucket_input = QLineEdit(self)
        self.bucket_input.setPlaceholderText("Bucket S3")
        self.bucket_input.setText(self.bucket_name)
        self.bucket_input.editingFinished.connect(self.update_settings)
        gui.widgetBox(self.controlArea, orientation='vertical').layout().addWidget(self.bucket_input)

        self.extensions_input = QLineEdit(self)
        self.extensions_input.setPlaceholderText("Extensions files from S3")
        self.extensions_input.setText(",".join(self.allowed_extensions))
        self.extensions_input.editingFinished.connect(self.update_settings)
        gui.widgetBox(self.controlArea, orientation='vertical').layout().addWidget(self.extensions_input)

        # self.folder_input = QLineEdit(self)
        # self.folder_input.setPlaceholderText("Folder files from S3")
        # self.folder_input.setText(self.folder_name)
        # self.folder_input.editingFinished.connect(self.update_settings)
        # gui.widgetBox(self.controlArea, orientation='vertical').layout().addWidget(self.extensions_input)

        gui.button(self.controlArea, self, "Lister les fichiers", callback=self.list_files)

    def update_settings(self):
        self.access_key = self.access_key_input.text()
        self.secret_key = self.secret_key_input.text()
        self.bucket_name = self.bucket_input.text()
        self.allowed_extensions = self.extensions_input.text()
        self.folder_name = self.folder_input.text()

    def list_files(self):
        self.error(None)
        try:
            session = boto3.Session(
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key
            )
            s3 = session.client("s3")
            response = s3.list_objects_v2(Bucket=self.bucket_name, Prefix = self.folder_name)
            if self.allowed_extensions == "*":
                self.allowed_extensions = "*"
            elif isinstance(self.allowed_extensions, str):
                self.allowed_extensions = tuple(ext.strip().lower() for ext in self.allowed_extensions.split(","))

            if "Contents" in response:
                data = []
                meta = []
                for obj in response["Contents"]:
                    if self.allowed_extensions == "*" or self.allowed_extensions == "" or obj["Key"].lower().endswith(self.allowed_extensions):
                        data.append([str(obj["Size"])])
                        meta.append([obj["Key"],obj["LastModified"].strftime("%Y-%m-%d %H:%M:%S")])

            domain = Domain(
                [ContinuousVariable("Taille (bytes)")], metas=[StringVariable("Nom"), StringVariable("Date")]
            )
            orange_table = Table.from_numpy(domain, data, metas=meta)
            self.Outputs.data.send(orange_table)

        except Exception as e:
            self.error(str(e))

if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = OWS3FileLister()
    window.show()


    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
