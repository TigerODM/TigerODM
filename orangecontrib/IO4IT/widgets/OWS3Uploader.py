import os
import boto3
from Orange.widgets.widget import OWWidget, Input, Output
from Orange.widgets.settings import Setting
from Orange.widgets import gui
from AnyQt.QtWidgets import QLineEdit, QFileDialog, QApplication
from Orange.data import Table


class OWS3FileDownloader(OWWidget):
    name = "S3 File Uploader"
    description = "Upload the listed files from a local directory to S3."
    icon = "icons/upload.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/upload.png"
    priority = 20
    category = "AAIT - API"
    # Paramètres utilisateur
    access_key = Setting("")
    secret_key = Setting("")
    bucket_name = Setting("")
    download_path = Setting("")

    class Inputs:
        data = Input("Data", Table)

    class Outputs:
        data = Output("Data", Table)

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

        gui.button(self.controlArea, self, "Envoyer les fichiers dans s3", callback=self.upload_files)

    def update_settings(self):
        self.access_key = self.access_key_input.text()
        self.secret_key = self.secret_key_input.text()
        self.bucket_name = self.bucket_input.text()
        self.upload_files()

    def select_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Sélectionner un répertoire")
        if directory:
            self.download_path = directory

    @Inputs.data
    def set_data(self, data):
        self.data = data
        if self.data is not None and len(self.data.domain) > 0:
            if "folder_path" in self.data.domain:
                self.download_path = self.data.get_column("folder_path")[0]
                self.upload_files()

    def upload_files(self):
        self.error("")
        self.information("")
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
            files = os.listdir(self.download_path)  # Liste tout (fichiers + dossiers)
            files_only = [f for f in files if os.path.isfile(os.path.join(self.download_path, f))]
            # print("files_only ::: ", files_only)
            for file in files_only:
               s3.upload_file(self.download_path + "/" + file, self.bucket_name, file)
            self.information("Upload terminé !")
            self.Outputs.data.send(self.data)


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