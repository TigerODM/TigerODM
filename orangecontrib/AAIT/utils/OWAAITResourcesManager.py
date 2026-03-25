import os
import sys
import time
import re
from urllib.parse import urljoin

from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QListWidget,
    QLineEdit,
)

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import (MetManagement, SimpleDialogQt)
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import GetFromRemote
else:
    from orangecontrib.AAIT.utils import (MetManagement, SimpleDialogQt)
    from orangecontrib.AAIT.utils.MetManagement import GetFromRemote


class RepositoryManager(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Repository Manager")
        self.setModal(True)
        self.setMinimumWidth(500)

        # Main layout
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Repository list
        list_label = QLabel("Current Repositories:")
        layout.addWidget(list_label)
        self.repo_list = QListWidget()
        layout.addWidget(self.repo_list)

        # Add Repository Group Box
        add_group = QGroupBox("Add Repository")
        add_layout = QVBoxLayout()
        add_group.setLayout(add_layout)

        # File selection
        file_layout = QHBoxLayout()
        self.file_button = QPushButton("Select New Repository")
        self.file_button.clicked.connect(self.add_repository)
        file_layout.addWidget(self.file_button)
        add_layout.addLayout(file_layout)

        # URL input
        url_layout = QHBoxLayout()
        url_label = QLabel("Or enter repository URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter URL here...")
        self.url_add_button = QPushButton("Add URL")
        self.url_add_button.clicked.connect(self.add_url_repository)

        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.url_add_button)
        add_layout.addLayout(url_layout)

        layout.addWidget(add_group)

        # Remove button
        self.remove_button = QPushButton("Remove Selected Repository")
        self.remove_button.clicked.connect(self.remove_repository)
        layout.addWidget(self.remove_button)

        # Load existing repositories
        self.load_repositories()

    def load_repositories(self):
        """Load existing repositories into the list"""
        self.repo_list.clear()
        repositories = self.parent().current_repositories
        self.repo_list.addItems(repositories)

    def add_repository(self):
        """Add a new repository"""
        folder = MetManagement.get_aait_store_remote_ressources_path()
        file = SimpleDialogQt.BoxSelectExistingFile(
            self,
            default_dir=folder,
            extention="Aiit file (*.aait)"
        )
        if file == "":
            return

        if MetManagement.get_size(file) == 0:
            folder = os.path.dirname(os.path.abspath(file)).replace("\\", "/")
            if folder == "":
                return
            if folder[-1] != "/":
                folder += "/"
            if folder not in self.parent().current_repositories:
                self.parent().current_repositories.append(folder)
                self.repo_list.addItem(folder)
                self.save_repositories_to_file()

        self.parent().update_requirements()

    def remove_repository(self):
        """Remove selected repository"""
        current_item = self.repo_list.currentItem()
        if current_item:
            repo = current_item.text()
            self.parent().current_repositories.remove(repo)
            self.repo_list.takeItem(self.repo_list.row(current_item))
            self.save_repositories_to_file()
            self.parent().update_requirements()

    def add_url_repository(self):
        """Add a new repository from URL"""
        url = self.url_input.text().strip()

        if url.endswith(".aait"):
            url = str(urljoin(url, "."))

        if url.endswith('.aait') and not MetManagement.IsStoreCompressed(url):
            temp_url = url.split("/")[:-1]
            url = "/".join(temp_url) + "/"

        if not url:
            SimpleDialogQt.BoxWarning("Please enter a URL")
            return

        # Basic URL validation
        if not url.startswith(('http://', 'https://')):
            SimpleDialogQt.BoxWarning("Please enter a valid URL starting with http:// or https://")
            return

        # Use the same logic as file paths
        if url not in self.parent().current_repositories:
            self.parent().current_repositories.append(url)
            self.repo_list.addItem(url)
            self.url_input.clear()
            self.save_repositories_to_file()
            self.parent().update_requirements()

    def save_repositories_to_file(self):
        """Save current repositories to remote_ressources_path.txt"""
        try:
            local_store_path = MetManagement.get_local_store_path()
            path_file = os.path.join(local_store_path, "remote_ressources_path.txt")

            # Create a lock file
            lock_file = path_file + ".lock"
            while os.path.exists(lock_file):
                time.sleep(0.1)

            # Create lock
            with open(lock_file, 'w') as f:
                f.write('locked')

            try:
                # Write all repositories to the file
                with open(path_file, 'w') as f:
                    for repo in self.parent().current_repositories:
                        f.write(repo + '\n')

            finally:
                # Remove lock
                if os.path.exists(lock_file):
                    os.remove(lock_file)

        except Exception as e:
            print(f"Error saving repositories: {e}")


class OWAAITResourcesManager(QMainWindow):
    dossier_du_script = os.path.dirname(os.path.abspath(__file__))

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("AAIT Resources Manager")
        self.setMinimumWidth(700)

        self.requirements = []
        self.current_repositories = []

        # Central widget
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        # Main layout of central widget
        root_layout = QVBoxLayout()
        central_widget.setLayout(root_layout)


        # download section
        group_box = QGroupBox("Download new minimum working example")
        group_layout = QVBoxLayout()
        group_box.setLayout(group_layout)

        # Elements are presented horizontally
        h_layout = QHBoxLayout()
        v_layout_button_combo_box = QVBoxLayout()

        # Add repository management button
        self.manage_repos_button = QPushButton('Manage Repositories')
        self.manage_repos_button.clicked.connect(self.show_repository_manager)
        v_layout_button_combo_box.addWidget(self.manage_repos_button)

        # Add combo box and other elements
        self.comboBox = QComboBox()
        self.comboBox.setMinimumSize(200, 10)
        v_layout_button_combo_box.addWidget(self.comboBox)

        self.saveButton = QPushButton('Download')
        self.label_info = QLabel('')
        v_layout_button_combo_box.addWidget(self.saveButton)
        v_layout_button_combo_box.addWidget(self.label_info)

        # Add the vertical layout to horizontal layout
        h_layout.addLayout(v_layout_button_combo_box)

        # Add h_layout to group_layout
        group_layout.addLayout(h_layout)
        root_layout.addWidget(group_box)

        # Nouveau layout horizontal
        h_layout2 = QHBoxLayout()

        # Chemin du dossier local
        local_path = MetManagement.get_local_store_path()

        # Bouton "local store"
        self.open_button = QPushButton("open local store")
        self.open_button.clicked.connect(self.open_explorer)
        h_layout2.addWidget(self.open_button)

        # Label sélectionnable
        self.selectableLabel = QLabel(local_path)
        self.selectableLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        h_layout2.addWidget(self.selectableLabel)

        # Ajouter au layout principal
        root_layout.addLayout(h_layout2)

        root_layout.setContentsMargins(5, 5, 5, 5)

        # Connect signals
        self.comboBox.currentIndexChanged.connect(self.handleComboBoxChange)
        self.saveButton.clicked.connect(self.saveFile)

        # Initialize repositories
        self.load_repositories()


    def open_explorer(self):
        path = MetManagement.get_local_store_path()
        if sys.platform.startswith("Darwin") or sys.platform.startswith("darwin"):
            import subprocess
            subprocess.run(["open", path])
            return
        elif sys.platform.startswith("win"):
            os.startfile(path)
            return
        # other platform -> nothing

    def load_repositories(self):
        """Load repositories from remote_ressources_path.txt"""
        try:
            local_store_path = MetManagement.get_local_store_path()
            path_file = os.path.join(local_store_path, "remote_ressources_path.txt")

            if os.path.exists(path_file):
                with open(path_file, 'r') as f:
                    repositories = [line.strip() for line in f if line.strip()]
                    self.current_repositories = repositories
            else:
                # If file doesn't exist, start with default repository
                default_repo = MetManagement.get_aait_store_remote_ressources_path()
                if default_repo:
                    self.current_repositories = [default_repo]
                    # Create the file with default repository
                    with open(path_file, 'w') as f:
                        f.write(default_repo + '\n')
                else:
                    self.current_repositories = []

        except Exception as e:
            print(f"Error loading repositories: {e}")
            self.current_repositories = []

        self.update_requirements()
        self.populate_combo_box()

    def populate_combo_box(self):
        # clean combo box if we change of repository
        self.comboBox.clear()
        workflows = []
        descriptions = dict()

        if not self.requirements:
            return

        for element in self.requirements:
            # Get repository name - handle both file and folder paths
            repo_path = element['repository']
            if repo_path.endswith('.aait'):
                repo_name = os.path.basename(repo_path)
            else:
                # For folder paths, get the last directory name
                repo_name = os.path.basename(os.path.dirname(repo_path))

            name = f"{element['name']} ({repo_name})"
            workflows.append(name)
            descriptions[name] = element["description"][0]

        self.descriptions = descriptions
        print(self.descriptions)
        self.comboBox.addItems(workflows)

        if workflows:
            self.handleComboBoxChange(0)

    def handleComboBoxChange(self, index):
        selected_file = self.comboBox.itemText(index)
        if selected_file == "":
            self.label_info.setText("")
            return

        # Set the label to the description
        description = self.descriptions.get(selected_file, "")
        self.label_info.setText(description)

    def read_description(self, file_name):
        # Chemin du fichier texte contenant la description
        description_file_path = os.path.join(
            self.dossier_du_script,
            'ows_example',
            f'{os.path.splitext(file_name)[0]}.txt'
        )

        # Lire le contenu du fichier s'il existe, sinon retourner une chaîne vide
        if os.path.exists(description_file_path):
            with open(description_file_path, 'r') as file:
                description = file.read()
        else:
            description = ""

        print("alllloooo: ", description)
        return description

    def saveFile(self):
        # Get selected file and remove repository info from display name
        selected_display = self.comboBox.currentText()
        match = re.search(r'\((.*?)\)', selected_display)
        reposit = match.group(1) if match else ''

        if not reposit.endswith('.aait'):
            selected_display = re.sub(r'\(.*?\)', '()', selected_display)

        current_repos = self.current_repositories.copy()

        # Find the corresponding requirement
        selected_requirement = None
        for req in self.requirements:
            display_name = f"{req['name']} ({os.path.basename(req['repository'])})"
            repository = req['repository'].split("/")[-2]
            if display_name == selected_display and repository == reposit:
                selected_requirement = req
                break

        if selected_requirement:
            self.label_info.setText('Synchronization in progress')
            QApplication.processEvents()

            # Set the correct repository for download
            MetManagement.set_aait_store_remote_ressources_path(selected_requirement['repository'])

            # Get just the name without repository info
            file_name = selected_requirement['name']

            try:
                GetFromRemote(file_name, repo_if_necessary=reposit)
                self.label_info.setText('Download completed')
            except Exception as e:
                self.label_info.setText(f'Error: {str(e)}')
            finally:
                QApplication.processEvents()

        try:
            local_store_path = MetManagement.get_local_store_path()
            path_file = os.path.join(local_store_path, "remote_ressources_path.txt")

            # Create a lock file
            lock_file = path_file + ".lock"
            while os.path.exists(lock_file):
                time.sleep(0.1)

            # Create lock
            with open(lock_file, 'w') as f:
                f.write('locked')

            try:
                # Write all repositories to the file
                with open(path_file, 'w') as f:
                    for repo in current_repos:
                        f.write(repo + '\n')
            finally:
                # Remove lock
                if os.path.exists(lock_file):
                    os.remove(lock_file)

        except Exception as e:
            print(f"Error saving repositories: {e}")

    def show_repository_manager(self):
        """Show the repository manager dialog"""
        dialog = RepositoryManager(self)
        dialog.exec()

    def update_requirements(self):
        """Update requirements from all repositories"""
        self.requirements = []

        # Store the current repositories before we start
        current_repos = self.current_repositories.copy()

        for repo in current_repos:
            # Set the remote resources path temporarily
            MetManagement.set_aait_store_remote_ressources_path(repo)
            repo_requirements = MetManagement.get_aait_store_requirements_json()
            if repo_requirements:
                # Add repository information to each requirement
                for req in repo_requirements:
                    req['repository'] = repo
                self.requirements.extend(repo_requirements)

        # Write repositories back to file
        try:
            local_store_path = MetManagement.get_local_store_path()
            path_file = os.path.join(local_store_path, "remote_ressources_path.txt")

            # Create a lock file
            lock_file = path_file + ".lock"
            while os.path.exists(lock_file):
                time.sleep(0.1)

            # Create lock
            with open(lock_file, 'w') as f:
                f.write('locked')

            try:
                # Write all repositories to the file
                with open(path_file, 'w') as f:
                    for repo in current_repos:
                        f.write(repo + '\n')
            finally:
                # Remove lock
                if os.path.exists(lock_file):
                    os.remove(lock_file)

        except Exception as e:
            print(f"Error saving repositories: {e}")

        self.populate_combo_box()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = OWAAITResourcesManager()
    window.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()