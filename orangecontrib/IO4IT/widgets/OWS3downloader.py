import os
import boto3
from Orange.widgets.widget import OWWidget, Input
from Orange.widgets.settings import Setting
from Orange.widgets import gui
from AnyQt.QtWidgets import QLineEdit, QFileDialog, QApplication
from Orange.data import Table

class OWS3FileDownloader(OWWidget):
    name = "S3 File Downloader"
    description = "Download the listed files from S3 to a local directory."
    icon = "icons/download.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/download.png"
    priority = 20
    category = "AAIT - API"

    # Paramètres utilisateur
    access_key = Setting("")
    secret_key = Setting("")
    bucket_name = Setting("")
    download_path = Setting("")

    class Inputs:
        data = Input("Data", Table)

    def __init__(self):
        super().__init__()
        self.data = None

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

        self.path_button = gui.button(self.controlArea, self, "Choisir un répertoire", callback=self.select_directory)

        gui.button(self.controlArea, self, "Télécharger les fichiers", callback=self.download_files)

    def update_settings(self):
        self.access_key = self.access_key_input.text()
        self.secret_key = self.secret_key_input.text()
        self.bucket_name = self.bucket_input.text()

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Sélectionner un répertoire")
        if directory:
            self.download_path = directory

    @Inputs.data
    def set_data(self, data):
        self.data = data

    def download_files(self):
        if self.data is None:
            self.error("Aucune donnée reçue.")
            return

        if not self.download_path:
            self.error("Veuillez choisir un répertoire de téléchargement.")
            return

        try:
            session = boto3.Session(
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key
            )
            s3 = session.client("s3")
            for elem in self.data:
                file_key = elem["Nom"].value
                local_file_path = os.path.join(self.download_path, file_key)

                os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                s3.download_file(self.bucket_name, file_key, local_file_path)
            self.information("Téléchargement terminé !")

        except Exception as e:
            print(e)
            self.error(str(e))


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = OWS3FileDownloader()
    window.show()

    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
