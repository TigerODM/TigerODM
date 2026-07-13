import os
import re
import sys
import json
import uuid
import pathlib
import unicodedata

from AnyQt.QtWidgets import QLabel, QPushButton, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy, QListWidgetItem, QToolTip, QGridLayout, QMenu, QShortcut
from AnyQt.QtCore import pyqtSignal, Qt, QEvent, QTimer
from AnyQt.QtGui import QCursor, QGuiApplication, QAction, QKeySequence
from Orange.widgets import widget
from Orange.widgets.settings import Setting
from Orange.data import Table
from AnyQt.QtWidgets import QApplication, QMainWindow

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm.okNokGpu import has_gpu_with_min_vram, auto_choose_model
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import get_local_store_path, reset_files
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert, management_workflow_sans_api
else:
    from orangecontrib.AAIT.llm.okNokGpu import has_gpu_with_min_vram, auto_choose_model
    from orangecontrib.AAIT.utils.MetManagement import get_local_store_path, reset_files
    from orangecontrib.AAIT.utils import thread_management
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
    from orangecontrib.HLIT_dev.remote_server_smb import convert, management_workflow_sans_api

id_RAG = "Request_RAG"
num_RAG = "input_0"

id_folder = "Folder"
num_folder = "input_0"

id_model = "Model"
num_model = "input_0"

id_conv = "Conversations"
num_conv = "input_0"

id_attach = "Attachment"
num_attach = "input_0"
mode_attach = "Link"

ip_port = "127.0.0.1:8000"
name_conv_length = 35


def data_to_json_str(workflow_id, num_input, col_names, col_types, values, timeout=100000000):
    payload = {
        "workflow_id": workflow_id,
        "timeout": timeout,
        "data": [
            {
                "num_input": num_input,
                "values": [
                    col_names,
                    col_types,
                    values
                ]
            }
        ]
    }
    return json.dumps(payload)


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWLeTigre(widget.OWWidget):
    name = "Le Tigre"
    description = "Pilotage du workflow de recherche documentaire et d'appel LLM"
    icon = "icons/tiger.png"
    category = "AAIT - API"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/tiger.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ChatbotTigerODM.ui")
    want_control_area = False
    priority = 1089

    signal_label_update = pyqtSignal(QLabel, str)

    # Settings
    large_font = Setting(False)
    model_mode = Setting("0")  # 0 auto, 1 leger, 2 intensif

    def __init__(self):
        super().__init__()
        self.minimum_vram=6.9
        # Charge l'UI dans un widget séparé
        self.ui = uic.loadUi(self.gui)

        self.resize(800, 600)  # taille initiale
        # IMPORTANT pour Orange : mettre le widget dans mainArea
        layout = self.mainArea.layout()
        if layout is None:
            layout = QVBoxLayout(self.mainArea)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        else:
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

        layout.addWidget(self.ui)

        # --- Aliases pour ne pas casser ton code existant ---
        self.tabWidget = self.ui.tabWidget
        self.scrollArea_display = self.ui.scrollArea_display
        self.textEdit_request = self.ui.textEdit_request
        self.btn_send = self.ui.btn_send
        self.btn_folder = self.ui.btn_folder
        self.btn_model = self.ui.btn_model
        self.btn_attachment = self.ui.btn_attachment
        self.btn_newConv = self.ui.btn_newConv
        self.btn_delConv = self.ui.btn_delConv
        self.list_conversations = self.ui.list_conversations
        self.scrollArea_display.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # UI Groupboxes
        self.groupBox_bdd = self.ui.groupBox_2
        self.groupBox_model = self.ui.groupBox_3
        # UI Labels
        self.label_conversation = self.ui.label_conversation
        self.label_folder = self.ui.label_folder
        self.label_model = self.ui.label_model
        self.label_freeText = self.ui.label_freeText
        self.label_attachment = self.ui.label_attachment
        # UI Setting objects
        self.checkbox_fontsize = self.ui.checkbox_fontsize
        self.combobox_model_mode = self.ui.combobox_model_mode
        self.combobox_model_mode_locked = True
        self.combobox_model_mode.installEventFilter(self)
        self.apply_model_mode_lock_state()
        self.checkbox_fontsize.setChecked(self.large_font)
        if self.model_mode == "1":
            self.combobox_model_mode.setCurrentIndex(1)
        elif self.model_mode == "2":
            self.combobox_model_mode.setCurrentIndex(2)
        else:
            self.combobox_model_mode.setCurrentIndex(0)
        self.checkbox_fontsize.stateChanged.connect(self.update_font_bool)
        self.combobox_model_mode.currentIndexChanged.connect(self.update_model_mode)
        self.update_font()

        self.scrollArea_display.setWidgetResizable(True)
        self.widget_display = self.scrollArea_display.widget()

        display_layout = self.widget_display.layout()
        if display_layout is None:
            display_layout = QVBoxLayout(self.widget_display)
            display_layout.setContentsMargins(0, 0, 0, 0)
            display_layout.setSpacing(6)
        self.vLayout_display = display_layout
        self.vLayout_display.addStretch()



        # Ctrl+Enter shortcut on send_request
        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.activated.connect(lambda: self.run(self.send_request))

        self.btn_send.clicked.connect(lambda: self.run(self.send_request))
        self.btn_folder.clicked.connect(lambda: self.run(self.load_folder))
        self.btn_model.clicked.connect(self.open_model_menu)
        self.btn_attachment.clicked.connect(lambda: self.run(self.load_attachment))
        self.btn_newConv.clicked.connect(lambda: self.run(self.create_new_conversation))
        self.btn_delConv.clicked.connect(lambda: self.run(self.delete_conversation))

        self.signal_label_update.connect(self.update_label)
        self.list_conversations.itemClicked.connect(lambda: self.run(self.load_conversation))

        self.thread = None
        self.model = None
        self.folder_is_selected = False
        self.conv_is_selected = False
        self.attach_is_selected = False
        self.full_answer = ""
        self.store_path = get_local_store_path()
        self.current_assistant_card = None
        self.is_thinking = None
        self.current_thinking_card = None
        self.current_source_card = None
        self.n_ctx = 32768
        self.current_task = None
        self.pdf_window = None
        self.in_think = True
        self.pending_model_path = None

        # Conversation management
        self.conv_folder = os.path.join(self.store_path, "conversations")
        os.makedirs(self.conv_folder, exist_ok=True)
        self.conversation_path = ""
        self.update_conversations_list()

        # Tuning
        self.rotator = ButtonIconRotator(self.btn_send)
        self.textEdit_request.files_dropped.connect(
            lambda paths: self.run(lambda: self.load_attachment(paths))
        )

        # Retire l'onglet à l'index 0
        self.tabWidget.removeTab(2)

        self.used_model_path = "Random"

        # si (pas assez de vram ou que l'on force l eco) et que l'on ne force pas sur GPU
        if (has_gpu_with_min_vram(self.minimum_vram) == False or self.model_mode == "1") and self.model_mode != "2":
            self.warning("TigerChat Light pour laptop sans GPU Intel Iris ou Nvidia : pièce jointe et base de connaissance désactivée")
            self.btn_folder.setEnabled(False)
            self.btn_attachment.setEnabled(False)
            self.ui.groupBox_2.installEventFilter(self)
            self.btn_attachment.installEventFilter(self)

        self.label_model.setText(auto_choose_model())
        # Réduit Orange et les autres widgets
        self.minimize_all_qmainwindows()
        # Ouvre Le Tigre en grand
        self.showMaximized()

    def apply_model_mode_lock_state(self):
        if self.combobox_model_mode_locked:
            self.combobox_model_mode.setStyleSheet("""
                QComboBox {
                    color: gray;
                    background-color: #eeeeee;
                }
            """)
        else:
            self.combobox_model_mode.setStyleSheet("")

    def eventFilter(self, source, event):
        # Windows/Linux : control alt clic droit
        # macOS         : cmd option clic droit
        if source is self.combobox_model_mode:
            if event.type() == QEvent.Type.MouseButtonPress:
                mods = event.modifiers()

                if sys.platform == "darwin":
                    unlock_shortcut = (
                        event.button() == Qt.MouseButton.RightButton
                        and mods & Qt.KeyboardModifier.MetaModifier
                        and mods & Qt.KeyboardModifier.AltModifier
                    )
                else:
                    unlock_shortcut = (
                        event.button() == Qt.MouseButton.RightButton
                        and mods & Qt.KeyboardModifier.ControlModifier
                        and mods & Qt.KeyboardModifier.AltModifier
                    )

                if unlock_shortcut:
                    self.combobox_model_mode_locked = not self.combobox_model_mode_locked
                    self.apply_model_mode_lock_state()
                    return True

            if self.combobox_model_mode_locked:
                if event.type() in (
                    QEvent.Type.MouseButtonPress,
                    QEvent.Type.MouseButtonRelease,
                    QEvent.Type.MouseButtonDblClick,
                    QEvent.Type.Wheel,
                    QEvent.Type.KeyPress,
                    QEvent.Type.KeyRelease,
                    QEvent.Type.ContextMenu,
                    QEvent.Type.FocusIn,
                ):
                    return True

        # Check if the event is coming from your GroupBox AND is a Mouse Enter
        if source is self.ui.groupBox_2 and event.type() == QEvent.Type.Enter:
            # Show tooltip INSTANTLY at the current mouse position
            QToolTip.showText(QCursor.pos(), "Désactivé sur laptop CPU", source)
            return True  # Event handled
        if source is self.btn_attachment and event.type() == QEvent.Type.Enter:
            # Show tooltip INSTANTLY at the current mouse position
            QToolTip.showText(QCursor.pos(), "Désactivé sur laptop CPU")
            return True  # Event handled
        return super().eventFilter(source, event)

    def minimize_all_qmainwindows(self):
        for w in QApplication.topLevelWidgets():
            try:
                if isinstance(w, QMainWindow):
                    w.showMinimized()
            except Exception as e:
                print(e)

    def update_font_bool(self):
        checkbox_value = self.checkbox_fontsize.isChecked()
        self.large_font = checkbox_value
        self.warning("Veuillez redémarrer TigerChat pour que le changement soit pris en compte.")

    def update_model_mode(self):
        self.model_mode = str(self.combobox_model_mode.currentIndex())
        self.warning("Veuillez redémarrer TigerChat pour que le changement soit pris en compte.")

    def update_font(self):
        if not self.large_font:
            return
        font = self.label_folder.font()
        font.setPointSize(12)
        self.label_folder.setFont(font)

        font = self.label_conversation.font()
        font.setPointSize(12)
        self.label_conversation.setFont(font)

        font = self.label_model.font()
        font.setPointSize(12)
        self.label_model.setFont(font)

        font = self.label_freeText.font()
        font.setPointSize(12)
        self.label_freeText.setFont(font)
        self.label_freeText.setStyleSheet("color: red;")

        font = self.label_attachment.font()
        font.setPointSize(12)
        self.label_attachment.setFont(font)

        font = self.groupBox_bdd.font()
        font.setPointSize(12)
        self.groupBox_bdd.setFont(font)

        font = self.groupBox_model.font()
        font.setPointSize(12)
        self.groupBox_model.setFont(font)

        font = self.textEdit_request.font()
        font.setPointSize(12)
        self.textEdit_request.setFont(font)

        font = self.list_conversations.font()
        font.setPointSize(12)
        self.list_conversations.setFont(font)

    def run(self, func):
        # Clear error & warning
        self.error("")
        self.warning("")

        # Clear freeText label
        self.signal_label_update.emit(self.label_freeText, "")

        # Disable all buttons
        for button in self.findChildren(QPushButton):
            button.setEnabled(False)
        self.list_conversations.setEnabled(False)

        # If Thread is already running, interrupt it
        if self.thread is not None:
            if self.thread.isRunning():
                self.thread.safe_quit()

        # Store which task is currently running
        self.current_task = func.__name__

        # Reset all the API folders, in case the workflow crashed or was suddenly closed
        id_s = [id_RAG, id_folder, id_conv, id_attach]
        for id in id_s:
            management_workflow_sans_api.reset_workflow(id)

        self.rotator.start()

        # Connect and start thread : main function, progress, result and finish
        self.thread = thread_management.Thread(func)
        self.thread.progress.connect(self.handle_progress)
        self.thread.result.connect(self.handle_result)
        self.thread.finish.connect(self.handle_finish)
        self.thread.start()

    ### Send button
    def send_request(self, progress_callback):
        text = self.label_model.text().strip().lower()
        if text == "" or text == "modèle":
            self.label_freeText.setText("Veuillez nourrir le tigre avec un modèle local (.gguf) avant de continuer.")
            return

        # Get the request, return if it's empty
        request = self.textEdit_request.toPlainText()
        if not request:
            return

        progress_callback(("clear_request", 0))

        # If a folder is selected, enable RAG
        RAG = "Yes" if self.folder_is_selected else "No"

        # Handle conversation
        if not self.conversation_path:
            id = str(uuid.uuid4())
            filename = sanitize_filename(request)
            conversation_id = filename[:name_conv_length] + "__id__" + id
            self.conversation_path = os.path.join(self.conv_folder, conversation_id) + ".pkl"
            self.conv_is_selected = False

        # Prepare the input json
        workflow_id = id_RAG
        num_input = num_RAG
        data_json = data_to_json_str(workflow_id=workflow_id,
                                     num_input=num_input,
                                     col_names=["content", "RAG", "model_path", "conv_path"],
                                     col_types=["str", "str", "str", "str"],
                                     values=[[request, RAG, self.used_model_path, self.conversation_path]])

        # Create user card
        progress_callback(("user", request))

        # POST Input
        management_workflow_sans_api.input_workflow(data_json=data_json)

        # GET Status / Output
        generated = False
        while True:
            response = management_workflow_sans_api.output_workflow(workflow_id=workflow_id)
            if response:
                status = response["_statut"]
                # If EngineLLM has been reached
                if status == "Stream" and not generated:
                    if self.folder_is_selected:
                        self.signal_label_update.emit(self.label_freeText, "Lecture des documents par le modèle...")
                    # Open the stream route and get the tokens
                    management_workflow_sans_api.stream_workflow(workflow_id, progress_callback)
                    generated = True
                # Or if there are defined status
                elif status is not None and status != "Finished":
                    # Display them in the UI (label)
                    try:
                        self.signal_label_update.emit(self.label_freeText, status)
                    except RuntimeError:
                        # Widget already deleted → ignore
                        return
                # Or if Output Interface has been reached
                elif status == "Finished":
                    # Get the data in Output Interface (source table with "path", "name", "page") and exit the loop
                    data = convert.convert_json_implicite_to_data_table(response["_result"])
                    break
                # Else, do nothing while waiting for infos
                else:
                    pass

        if self.folder_is_selected:
            # Check if data is definedS
            if not data:
                self.error("Could not display sources, no table was retrieved from Output Interface.")
                return
            # Check if the sources data table contains the required columns
            required_columns = ["path", "name", "page"]
            if not all(col in data.domain for col in required_columns):
                self.error('Could not display sources, the following columns are needed in the result: "path", "name", "page".')
                return
            # Display sources from Output Interface, as HTML links
            pdf_data = []
            for row in data:
                path = pathlib.Path(row["path"].value)
                name = row["name"].value
                page = row["page"].value
                pdf_data.append({"path": path, "name": name, "page": int(page)})
            # Envoi à la carte
            progress_callback(("source", pdf_data))
        self.signal_label_update.emit(self.label_freeText, "Réponse terminée !")

    ### Folder button
    def load_folder(self):
        # Prepare the input json
        workflow_id = id_folder
        num_input = num_folder
        data_json = data_to_json_str(workflow_id=workflow_id,
                                     num_input=num_input,
                                     col_names=["trigger"],
                                     col_types=["str"],
                                     values=[["Trigger"]])

        # POST Input
        management_workflow_sans_api.input_workflow(data_json=data_json)

        # GET Status / Output
        while True:
            # response = hlit_python_api.call_output_workflow_unique_2(ip_port=ip_port, workflow_id=workflow_id)
            response = management_workflow_sans_api.output_workflow(workflow_id=workflow_id)
            if response:
                status = response["_statut"]
                # If Output Interface has been reached
                if status == "Finished":
                    # Get the data in Output Interface (folder table with "path") and exit the loop
                    data = convert.convert_json_implicite_to_data_table(response["_result"])
                    break
                # Or if there are defined status
                elif status is not None:
                    # Display them in the UI (label)
                    self.signal_label_update.emit(self.label_freeText, status)
                # Else, do nothing while waiting for infos
                else:
                    pass

        # Check if data is defined
        if not data:
            self.error("Cannot display the selected folder, no table was retrieved from Output Interface.")
            self.folder_is_selected = False
            self.signal_label_update.emit(self.label_folder, "Nom du dossier")
            return
        # Check if the data table contains the required column
        required_columns = ["path"]
        if not all(col in data.domain for col in required_columns):
            self.error('Cannot display the selected folder, the following column is needed in the result: "path".')
            self.folder_is_selected = False
            self.signal_label_update.emit(self.label_folder, "Nom du dossier")
            return
        # Display folder to its label
        path = data[0]["path"].value
        path = path.rstrip("/")
        folder_name = os.path.basename(path)
        self.signal_label_update.emit(self.label_folder, folder_name)
        self.signal_label_update.emit(self.label_freeText, "Préparation terminé !")
        self.folder_is_selected = True

    ### Model button
    def open_model_menu(self, parent=None):
        if not isinstance(parent, QWidget):
            parent = None

        menu = QMenu(parent)

        act_browse = QAction("parcourir mon ordinateur", menu)
        act_local_store = QAction("depuis local store", menu)

        menu.addAction(act_browse)
        menu.addAction(act_local_store)

        lmstudio_dir = os.path.join(os.path.expanduser("~"), ".lmstudio", "models")

        act_lm_studio = None
        if os.path.isdir(lmstudio_dir):
            act_lm_studio = QAction("depuis lm studio", menu)
            menu.addAction(act_lm_studio)

        action = menu.exec(QCursor.pos())

        if action == act_browse:
            self.run(self.select_model)
            return

        if action == act_local_store:
            gguf_path = self.select_gguf_from_local_store()
            if gguf_path:
                self.pending_model_path = gguf_path
                self.run(self.select_model_from_pending_path)
            return

        if act_lm_studio is not None and action == act_lm_studio:
            gguf_path = self.select_gguf_from_lm_studio()
            if gguf_path:
                self.pending_model_path = gguf_path
                self.run(self.select_model_from_pending_path)
            return

    def select_model_from_pending_path(self):
        if not self.pending_model_path:
            return
        self.select_model(self.pending_model_path)

    def select_gguf_from_local_store(self):
        base_dir = os.path.join(
            get_local_store_path(),
            "Models",
            "NLP"
        )

        gguf_files = []

        if os.path.isdir(base_dir):
            for name in os.listdir(base_dir):
                path = os.path.join(base_dir, name)
                if os.path.isfile(path) and name.lower().endswith(".gguf") and "mmproj" not in name.lower():
                    gguf_files.append(os.path.abspath(path))

            for name in os.listdir(base_dir):
                subdir = os.path.join(base_dir, name)
                if os.path.isdir(subdir):
                    for sub_name in os.listdir(subdir):
                        path = os.path.join(subdir, sub_name)
                        if os.path.isfile(path) and sub_name.lower().endswith(".gguf") and "mmproj" not in sub_name.lower():
                            gguf_files.append(os.path.abspath(path))

        return self.show_gguf_list_menu(gguf_files)

    def select_gguf_from_lm_studio(self):
        base_dir = os.path.join(os.path.expanduser("~"), ".lmstudio", "models")

        gguf_files = []

        if os.path.isdir(base_dir):
            for root, dirs, files in os.walk(base_dir):
                for name in files:
                    if name.lower().endswith(".gguf") and "mmproj" not in name.lower():
                        gguf_files.append(os.path.abspath(os.path.join(root, name)))

        return self.show_gguf_list_menu(gguf_files)

    def show_gguf_list_menu(self, gguf_files):
        menu = QMenu(self)

        act_cancel = QAction("cancel", menu)
        menu.addAction(act_cancel)

        actions = {}

        for path in sorted(gguf_files):
            act = QAction(path, menu)
            menu.addAction(act)
            actions[act] = path

        action = menu.exec(QCursor.pos())

        if action is None or action == act_cancel:
            return None

        return actions.get(action)

    def select_model(self, model_path=None):
        # Prepare the input json
        workflow_id = id_model
        num_input = num_model
        if model_path:
            data_json = data_to_json_str(workflow_id=workflow_id,
                                         num_input=num_input,
                                         col_names=["trigger"],
                                         col_types=["str"],
                                         values=[[str(os.path.abspath(model_path))]])
        else:
            data_json = data_to_json_str(workflow_id=workflow_id,
                                         num_input=num_input,
                                         col_names=["trigger"],
                                         col_types=["str"],
                                         values=[["Trigger"]])

        # POST Input
        management_workflow_sans_api.input_workflow(data_json=data_json)

        # GET Status / Output
        while True:
            # response = hlit_python_api.call_output_workflow_unique_2(ip_port=ip_port, workflow_id=workflow_id)
            response = management_workflow_sans_api.output_workflow(workflow_id=workflow_id)
            if response:
                status = response["_statut"]
                # If Output Interface has been reached
                if status == "Finished":
                    # Get the data in Output Interface (folder table with "path") and exit the loop
                    data = convert.convert_json_implicite_to_data_table(response["_result"])
                    break
                # Or if there are defined status
                elif status is not None:
                    # Display them in the UI (label)
                    self.signal_label_update.emit(self.label_freeText, status)
                # Else, do nothing while waiting for infos
                else:
                    pass

        # Check if data is defined
        if not data:
            self.error("Cannot display the selected model, no table was retrieved from Output Interface.")
            self.signal_label_update.emit(self.label_model, "Modèle")
            return
        # Check if the data table contains the required column
        required_columns = ["path"]
        if not all(col in data.domain for col in required_columns):
            self.error('Cannot display the selected folder, the following column is needed in the result: "path".')
            self.signal_label_update.emit(self.label_model, "Modèle")
            return
        # Display folder to its label
        path = data[0]["path"].value
        path = path.rstrip("/")
        model_name = os.path.basename(path)
        if not model_name.lower().endswith(".gguf"):
            self.signal_label_update.emit(self.label_model, "Modèle")
            self.signal_label_update.emit(self.label_freeText, "Wrong file selected : please select a .gguf file")
            return
        self.used_model_path = path
        self.signal_label_update.emit(self.label_model, model_name)
        self.signal_label_update.emit(self.label_freeText, "Modèle chargé !")

    ### Conversation button (click on ID)
    def load_conversation(self, progress_callback):
        # Clear textBrowser history
        progress_callback(("clear", 0))
        # Find selected item
        item = self.list_conversations.currentItem()
        # Get full stored path
        conv_path = item.data(Qt.ItemDataRole.UserRole)
        # Safety check
        if not conv_path or not os.path.exists(conv_path):
            self.error(f"Conversation could not be loaded: {conv_path}")
            return
        try:
            data = Table.from_file(conv_path)
            # Display the conversation
            self.display_conversation(data, progress_callback)
            self.conversation_path = conv_path
            self.conv_is_selected = True

            if self.attach_is_selected:
                # Reset attachments
                self.reset_attachments()
        except Exception as e:
            print(e)
            print("erreur au chargement de la conversation je la supprime")
            self.delete_conversation()
            self.conv_is_selected = False


    ### Attachment button
    def load_attachment(self, paths=None):
        # Clear labels
        self.signal_label_update.emit(self.label_attachment, "")

        workflow_id = id_attach
        num_input = num_attach

        # Case 1: no files → simple trigger
        if not paths:
            data_json = data_to_json_str(
                workflow_id=workflow_id,
                num_input=num_input,
                col_names=["path"],
                col_types=["str"],
                values=[["Trigger"]]
            )

        # Case 2: files dropped → send paths
        else:
            data_json = data_to_json_str(
                workflow_id=workflow_id,
                num_input=num_input,
                col_names=["path"],
                col_types=["str"],
                values=[[p] for p in paths]
            )

        # POST Input
        # hlit_python_api.post_input_to_workflow(ip_port=ip_port, data=data_json)
        management_workflow_sans_api.input_workflow(data_json=data_json)

        # GET Status / Output
        while True:
            # response = hlit_python_api.call_output_workflow_unique_2(ip_port=ip_port, workflow_id=workflow_id)
            response = management_workflow_sans_api.output_workflow(workflow_id=workflow_id)
            if response:
                status = response["_statut"]
                # If Output Interface has been reached
                if status == "Finished":
                    # Get the data in Output Interface (table with "Message") and exit the loop
                    data = convert.convert_json_implicite_to_data_table(response["_result"])
                    break
                # Or if there are defined status
                elif status is not None:
                    # Display them in the UI (label)
                    self.signal_label_update.emit(self.label_freeText, status)
                # Else, do nothing while waiting for infos
                else:
                    pass

        # Check if data is defined
        if not data:
            self.error("Cannot display the selected attachment, no table was retrieved from Output Interface.")
            self.signal_label_update.emit(self.label_attachment, "")
            self.signal_label_update.emit(self.label_freeText, "Une erreur s'est produite.")
            return
        # Check if the data table contains the required column
        required_columns = ["message"]
        if not all(col in data.domain for col in required_columns):
            self.error('Cannot display the selected attachment, the following column is needed in the result: "Message".')
            self.signal_label_update.emit(self.label_attachment, "")
            return
        # Display attachment to its label
        if len(data) == 1:
            attach_name = data[0]["message"].value
            attach_name = os.path.basename(attach_name)
            self.signal_label_update.emit(self.label_attachment, attach_name)
            self.signal_label_update.emit(self.label_freeText, "Document chargé en pièce jointe !")
        else:
            self.signal_label_update.emit(self.label_attachment, f"{len(data)} documents chargés")
            self.signal_label_update.emit(self.label_freeText, "Documents chargés en pièce jointe !")
        self.attach_is_selected = True

    ### Delete button
    def delete_conversation(self):
        self.error("")  # clear previous errors

        # Return early if list is empty or no item selected
        item = self.list_conversations.currentItem()
        if item is None:
            self.error("No conversation selected to delete")
            return

        # Retrieve the hidden full path (or ID)
        path = item.data(Qt.ItemDataRole.UserRole)

        if not os.path.exists(path):
            self.error(f"This conversation does not exist: {path}")
            return

        try:
            reset_files([path])
            self.update_conversations_list()
        except Exception as e:
            self.error(f"Failed to delete file: {e}")

        if self.attach_is_selected:
            # Reset attachments
            self.reset_attachments()
        self.conversation_path = ""
        self.clear_chat_display()
        self.list_conversations.clearSelection()
        return
        # Load the most recent conversation
        if self.list_conversations.count() == 0:
            self.conversation_path = ""
            self.clear_chat_display()
        else:
            # Safe to select the first item
            item = self.list_conversations.item(0)
            self.list_conversations.setCurrentItem(item)
            item.setSelected(True)
            self.list_conversations.setFocus()
            self.conversation_path = item.data(Qt.ItemDataRole.UserRole)
            self.run(self.load_conversation)
            self.conv_is_selected = True

    ### New button
    def create_new_conversation(self, progress_callback):
        # Clear textBrowser history & request field
        progress_callback(("clear", 0))

        # Clear conversation
        self.conversation_path = ""
        self.list_conversations.clearSelection()

        if self.attach_is_selected:
            # Reset attachments
            self.reset_attachments()

    def reset_attachments(self):
        self.signal_label_update.emit(self.label_freeText, "Nettoyage du workflow...")

        # Reset attachments
        workflow_id = id_attach
        num_input = num_attach

        # Case 1: no files → simple trigger
        data_json = data_to_json_str(
            workflow_id=workflow_id,
            num_input=num_input,
            col_names=["path"],
            col_types=["str"],
            values=[["error nothing selected"]]
        )

        # POST Input
        management_workflow_sans_api.input_workflow(data_json=data_json)

        # GET Status / Output
        while True:
            # response = hlit_python_api.call_output_workflow_unique_2(ip_port=ip_port, workflow_id=workflow_id)
            response = management_workflow_sans_api.output_workflow(workflow_id=workflow_id)
            if response:
                status = response["_statut"]
                # If Output Interface has been reached
                if status == "Finished":
                    # Get the data in Output Interface (table with "Message") and exit the loop
                    data = convert.convert_json_implicite_to_data_table(response["_result"])
                    break
                # Or if there are defined status
                elif status is not None:
                    # Display them in the UI (label)
                    self.signal_label_update.emit(self.label_freeText, "")
                # Else, do nothing while waiting for infos
                else:
                    pass

        # Check if data is defined
        if not data:
            self.error("Une erreur s'est produite")
            self.signal_label_update.emit(self.label_attachment, "")
            self.signal_label_update.emit(self.label_freeText, "Une erreur s'est produite.")
            return
        # Display attachment to its label
        self.signal_label_update.emit(self.label_attachment, "")
        self.signal_label_update.emit(self.label_freeText, "")
        self.attach_is_selected = False

    def handle_progress(self, value) -> None:
        tag, content = value[0], value[1]
        end_think_tags = ["</think>", "<channel|>"]

        if tag == "user":
            user_card = UserMessageCard(content)
            self.add_message_card(user_card)
            QApplication.processEvents()

        elif tag == "assistant":
            # Thinking
            if "<think>" in content:
                self.current_thinking_card = ThinkingMessageCard()
                self.add_message_card(self.current_thinking_card)
                parts = content.split("<think>", 1)
                after_think = parts[1].lstrip()
                if after_think:
                    self.current_thinking_card.addText(after_think)
                return
            for end_think_tag in end_think_tags:
                if end_think_tag in content:
                    self.in_think = False
                    parts = content.split(end_think_tag, 1)
                    before_end = parts[0]  # Ce qui restait de la pensée
                    after_end = parts[1].lstrip()  # Le début de la vraie réponse (ex: "Hello!")
                    # On finit de remplir la pensée si besoin
                    if before_end and self.current_thinking_card:
                        self.current_thinking_card.setText(self.current_thinking_card.content_label.text().strip("\n") + before_end.strip())
                    # On ferme la pensée
                    self.current_thinking_card.toggle_btn.click()
                    self.current_thinking_card = None
                    # On crée immédiatement la carte assistant pour la suite
                    self.current_assistant_card = AssistantMessageCard(after_end)
                    self.add_message_card(self.current_assistant_card)
                    # self.clear_thinking_messages()
                    return
            if self.current_thinking_card is not None:
                self.current_thinking_card.addText(content)
                return
            # Answer
            if self.current_assistant_card is None:
                self.current_assistant_card = AssistantMessageCard(content)
                self.add_message_card(self.current_assistant_card)
            else:
                self.current_assistant_card.addText(content)

        elif tag == "source":
            self.current_source_card = SourceMessageCard(content)
            self.current_source_card.source_clicked.connect(self.handle_source_link_click)
            self.add_message_card(self.current_source_card)

        elif tag == "clear":
            self.clear_chat_display()
            self.textEdit_request.clear()
            self.folder_is_selected = False
            self.signal_label_update.emit(self.label_folder, "Nom du dossier")

        elif tag == "clear_request":
            self.textEdit_request.clear()

        elif tag == "new_assistant":
            self.current_assistant_card = None

        self.scroll_to_bottom()

    def handle_result(self, result):
        pass

    def handle_finish(self):
        for button in self.findChildren(QPushButton):
            button.setEnabled(True)
        self.list_conversations.setEnabled(True)

        if self.current_task == "send_request":
            if not self.conv_is_selected:
                self.update_conversations_list()
                if self.list_conversations.count() > 0:
                    item = self.list_conversations.item(0)
                    self.list_conversations.setCurrentItem(item)
                    item.setSelected(True)
                    self.list_conversations.setFocus()
                    self.conv_is_selected = True

        elif self.current_task == "load_folder":
            pass
        elif self.current_task == "load_conversation":
            pass
        elif self.current_task == "load_attachment":
            pass
        elif self.current_task == "create_new_conversation":
            pass

        self.current_thinking_card = None
        self.current_assistant_card = None
        self.current_source_card = None
        self.in_think = True
        self.rotator.stop()

        # si (pas assez de vram ou que l'on force l eco) et que l'on ne force pas sur GPU
        if (has_gpu_with_min_vram(self.minimum_vram) == False or self.model_mode == "1") and self.model_mode != "2":
            self.btn_folder.setEnabled(False)
            self.btn_attachment.setEnabled(False)

    def post_initialized(self):
        pass

    def update_conversations_list(self):
        self.list_conversations.clear()
        convs_path = os.path.join(self.store_path, "conversations")
        if not os.path.exists(convs_path):
            return

        # 🔥 build full paths instead of filenames
        files = [os.path.join(convs_path, f) for f in os.listdir(convs_path) if os.path.isfile(os.path.join(convs_path, f))]
        # sort by modification time
        files.sort(key=os.path.getmtime, reverse=True)

        for file_path in files:
            # filename only (no directory)
            filename = os.path.basename(file_path)
            # remove extension
            name_no_ext, _ = os.path.splitext(filename)
            # remove __id__ part
            display_name = name_no_ext.split("__id__")[0].strip()
            # truncate for UI
            display_name = display_name[:name_conv_length] + "..." if len(display_name) >= name_conv_length else display_name
            item = QListWidgetItem(display_name.replace("_", " "))
            # 🔥 store FULL PATH
            item.setData(Qt.ItemDataRole.UserRole, file_path)
            self.list_conversations.addItem(item)

    def display_conversation(self, data, progress_callback):
        # Iterate over rows
        for row in data:
            # "request" is the user input
            if row["role"].value == "user":
                progress_callback(("user", row["content"].value))
            elif row["role"].value == "assistant":
                progress_callback(("assistant", row["content"].value))
                progress_callback(("new_assistant", None))

    def update_label(self, label, text):
        label.setText(text)

    # UI
    def add_message_card(self, message_card):
        self.vLayout_display.insertWidget(self.vLayout_display.count() - 1, message_card)

    # UI
    def clear_chat_display(self):
        """Supprime les messages et reset les pointeurs de streaming."""
        # 1. Nettoyage de l'UI
        for i in reversed(range(self.vLayout_display.count())):
            item = self.vLayout_display.itemAt(i)
            widget = item.widget()

            if isinstance(widget, (UserMessageCard, AssistantMessageCard, ThinkingMessageCard, SourceMessageCard)):
                widget.setParent(None)  # Détache du layout
                widget.deleteLater()  # Supprime de la mémoire

        # 2. Reset pour le prochain streaming
        self.current_assistant_card = None
        self.current_thinking_card = None
        self.current_source_card = None

    # UI
    def clear_thinking_messages(self):
        """Supprime uniquement les cartes de réflexion et reset le pointeur."""
        # 1. On parcourt le layout
        for i in reversed(range(self.vLayout_display.count())):
            item = self.vLayout_display.itemAt(i)
            widget = item.widget()

            if isinstance(widget, ThinkingMessageCard):
                # Pas besoin de setParent(None) si on fait deleteLater()
                # deleteLater() informe le layout que le widget va mourir
                widget.deleteLater()

        # 2. Reset pour le streaming
        self.current_thinking_card = None

        # 3. Optionnel : Rafraîchir l'affichage
        self.vLayout_display.update()

    # UI
    def scroll_to_bottom(self):
        QTimer.singleShot(0, lambda:
        self.scrollArea_display.verticalScrollBar().setValue(
            self.scrollArea_display.verticalScrollBar().maximum()
        )
                          )

    # PDF Viewer
    def handle_source_link_click(self, link_data):
        if not self.pdf_window:
            self.pdf_window = PdfViewerWindow()
        self.pdf_window.load_pdf(link_data)
        self.pdf_window.show()
        self.pdf_window.activateWindow()


# UI - User message card
class UserMessageCard(QWidget):
    def __init__(self, text=""):
        super().__init__()

        # Main horizontal layout to align the whole bubble to the right
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.addStretch()  # Pushes the bubble to the right

        # --- The Container ---
        # This widget holds the label and the button together
        self.container = QWidget()
        self.container_layout = QGridLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(0)

        # 1. The Label (The Message Bubble)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(250)
        self.label.setMaximumWidth(250)
        self.label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.label.setStyleSheet("""
            QLabel {
                background-color: #1e4358;
                color: white;
                border-radius: 8px;
                padding: 10px;
                padding-bottom: 25px; /* Space for the button */
                font-size: 13px;
            }
        """)

        # 2. The Copy Button
        self.copy_button = QPushButton("Copy")
        self.copy_button.setFixedWidth(45)
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self.copy_to_clipboard)

        self.copy_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.15);
                border: none;
                color: #b0c4de;
                border-radius: 4px;
                font-size: 9px;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.3);
                color: white;
            }
        """)

        # Add both to the container's grid (overlap)
        self.container_layout.addWidget(self.label, 0, 0)
        self.container_layout.addWidget(self.copy_button, 0, 0,
                                        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        # Add the container to the main horizontal layout
        self.main_layout.addWidget(self.container)

    def copy_to_clipboard(self):
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.label.text())

        # Flashy feedback
        self.copy_button.setText("Copied!")
        # Revert text after 2 seconds (optional, requires QTimer)

    def setText(self, text):
        self.label.setText(text)

    def addText(self, new_text):
        self.label.setText(self.label.text() + new_text)


def sanitize_filename(name, max_length=100):
    # Normalize unicode (é → e, etc. optional but useful)
    name = unicodedata.normalize("NFKD", name)
    # Remove illegal characters (Windows + Linux safe set)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '', name)
    # Replace spaces with underscores (optional but recommended)
    name = name.replace(" ", "_")
    # Remove leading/trailing dots and spaces
    name = name.strip(" .")
    # Limit length
    name = name[:max_length]
    # Avoid empty filename
    if not name:
        name = "file"
    return name


# UI - Assistant message card
class AssistantMessageCard(QWidget):
    def __init__(self, text=""):
        super().__init__()

        # Use a Grid Layout to control positioning precisely
        self.main_layout = QGridLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)

        # 1. The Message Label
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.MarkdownText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.label.setStyleSheet("""
            background-color: #4b839f;
            color: white;
            border-radius: 8px;
            padding: 8px;
            padding-bottom: 25px; /* Extra padding at bottom for the button */
        """)

        # 2. The Copy Button
        self.copy_button = QPushButton("Copy")
        self.copy_button.setFixedWidth(50)
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self.copy_to_clipboard)

        # Style the button to look subtle
        self.copy_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.2);
                border: none;
                color: white;
                border-radius: 4px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.4);
            }
        """)

        # Add to Grid: Label spans the whole area, Button sits on top in the bottom right
        self.main_layout.addWidget(self.label, 0, 0)
        self.main_layout.addWidget(self.copy_button, 0, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

    def copy_to_clipboard(self):
        clipboard = QGuiApplication.clipboard()
        # Note: self.label.text() will include Markdown tags.
        # For plain text, you might want a separate variable.
        clipboard.setText(self.label.text())
        self.copy_button.setText("Saved!")  # Quick visual feedback

    def setText(self, text):
        self.label.setText(text)

    def addText(self, new_text):
        self.label.setText(self.label.text() + new_text)


# UI - Source message card
class SourceMessageCard(QWidget):
    source_clicked = pyqtSignal(dict)

    def __init__(self, sources=None):
        super().__init__()

        # Force Qt to actually paint the background
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(3)
        self.main_layout.setContentsMargins(5, 5, 5, 5)

        # Base card style — applies directly to this widget
        self.setStyleSheet("""
            background-color: #4b839f;
            border-radius: 14px;
            border: 2px solid #5a8ba3;
        """)

        if sources:
            for item in sources:
                display_text = f"{item['name']} - Page {item['page']}"
                link_label = SourceLink(display_text, item)
                link_label.clicked_with_data.connect(self.source_clicked.emit)
                self.main_layout.addWidget(link_label)


class SourceLink(QLabel):
    clicked_with_data = pyqtSignal(dict)

    def __init__(self, text, pdf_data):
        super().__init__(text)
        self.pdf_data = pdf_data
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Only text styling — **do not set background transparent**
        self.setStyleSheet("""
            color: #e0f2f1;
            text-decoration: underline;
            border: none;
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked_with_data.emit(self.pdf_data)
        super().mousePressEvent(event)


# Minimal Thinking card with just a button
class ThinkingMessageCard(QWidget):
    def __init__(self, text=""):
        super().__init__()

        # --- Main layout for the card ---
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 0, 5, 0)
        main_layout.setSpacing(0)

        # --- Card container ---
        self.container = QFrame()
        self.container.setStyleSheet("""
            QFrame {
                background-color: #262626;
                border-radius: 8px;
                border-left: 3px solid #505050;
            }
        """)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(5, 0, 5, 0)
        self.container_layout.setSpacing(0)

        # --- Header: button + "Réflexion" ---
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self.toggle_btn = QPushButton("▼")
        self.toggle_btn.setFixedSize(28, 28)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                color: #90a4ae;
                background-color: transparent;
                border: none;
                font-weight: bold;
                font-size: 16px;
            }
        """)
        self.toggle_btn.clicked.connect(self.toggle_text)

        self.label_reflexion = QLabel("Réflexion")
        self.label_reflexion.setStyleSheet("color: #607d8b; font-style: italic;")

        header_layout.addWidget(self.toggle_btn)
        header_layout.addWidget(self.label_reflexion)
        header_layout.addStretch()

        self.container_layout.addLayout(header_layout)

        # --- Content text ---
        self.content_label = QLabel(text)
        self.content_label.setWordWrap(True)
        self.content_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.content_label.setStyleSheet("color: #90a4ae; font-style: italic;")
        self.content_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.container_layout.addWidget(self.content_label)

        main_layout.addWidget(self.container)

        # --- Card state ---
        self.is_collapsed = False  # start expanded

    def toggle_text(self):
        """Collapse/expand the content label"""
        self.is_collapsed = not self.is_collapsed
        if self.is_collapsed:
            self.content_label.hide()
            self.toggle_btn.setText("▶")
        else:
            self.content_label.show()
            self.toggle_btn.setText("▼")

    def setText(self, html_text):
        """Met à jour les sources d'un coup."""
        self.content_label.setText(html_text)

    def addText(self, new_text):
        """Ajoute du texte à la suite (utile pour le streaming)."""
        self.content_label.setText(self.content_label.text() + new_text)


############################
##### Additional stuff #####
############################
from PyQt6.QtWidgets import QTabWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import QUrl


class PdfViewerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Document Workspace")
        self.resize(800, 600)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.tabs.removeTab)

        self.setCentralWidget(self.tabs)

    def load_pdf(self, pdf_data):
        """Open a single PDF in a new tab (or focus it if already open)."""

        path = pdf_data["path"]
        name = pdf_data["name"]
        page = pdf_data["page"]

        abs_path = os.path.abspath(path)

        if not abs_path.lower().endswith(".pdf"):
            return

        # Check if already open → just switch to it
        for i in range(self.tabs.count()):
            existing_view = self.tabs.widget(i)
            if existing_view.property("pdf_path") == abs_path:
                # Same PDF already open → jump to requested page
                url = QUrl.fromLocalFile(abs_path)
                url.setFragment(f"page={page}")
                existing_view.load(url)
                self.tabs.setCurrentIndex(i)
                return

        view = QWebEngineView()

        settings = view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)

        # Store path in widget (used to detect duplicates)
        view.setProperty("pdf_path", abs_path)

        url = QUrl.fromLocalFile(abs_path)
        url.setFragment(f"page={page}")

        view.load(url)

        self.tabs.addTab(view, name)
        self.tabs.setCurrentWidget(view)


from PyQt6.QtGui import QTransform, QIcon


class ButtonIconRotator:
    def __init__(self, button):
        self.button = button
        self.original_icon = button.icon()
        # store the pixmap for rotation
        self.original_pixmap = self.original_icon.pixmap(button.iconSize())
        self.angle = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.rotate)

    def rotate(self):
        if self.original_pixmap is None:
            return

        if self.button is None:
            return

        try:
            self.angle = (self.angle + 10) % 360
            transform = QTransform().rotate(self.angle)
            rotated_pix = self.original_pixmap.transformed(
                transform,
                Qt.TransformationMode.SmoothTransformation
            )
            self.button.setIcon(QIcon(rotated_pix))
        except RuntimeError:
            return

    def start(self):
        self.angle = 0
        self.timer.start(50)

    def stop(self):
        self.timer.stop()
        self.button.setIcon(self.original_icon)
        self.angle = 0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWLeTigre()
    my_widget.show()

    # my_widget.label_folder.setText(r"C:\Users\lucas\Documents\Projets\IFIA\RAG\Dataset\Helico - Embeddings & Keywords")
    # my_widget.label_folder.setText("Dossier")
    # --- Create test cards ---
    user_card = UserMessageCard("Hello, can you explain how helicopters work?")
    thinking_card = ThinkingMessageCard("Just a reflexion to share some ideas.")
    assistant_card = AssistantMessageCard(
        "Sure! Helicopters generate lift using rotating blades called rotors..."
    )

    user_card2 = UserMessageCard("Hello, can you explain how helicopters work?")
    thinking_card2 = ThinkingMessageCard("Just a reflexion to share some ideas.")
    assistant_card2 = AssistantMessageCard(
        "### Sure! Helicopters generate lift using rotating blades called rotors..."
    )

    pdf_data = [
        {
            "name": "PDF_1Helicopters generate lift using rotating blades called rotorsHelicopters generate lift using rotating blades called rotors",
            "path": r"C:\Users\lucas\Desktop\Datasets\Base Hélico - Embeddings & Keywords\manuel_volFamaKiss.pdf",
            "page": 3
        },
        {
            "name": "PDF_2",
            "path": r"C:\Users\lucas\Desktop\Datasets\Base Hélico - Embeddings & Keywords\4. MANUEL SGS HELICLUB FAMA.pdf",
            "page": 2
        }
    ]

    source_card = SourceMessageCard(sources=pdf_data)
    source_card.source_clicked.connect(my_widget.handle_source_link_click)

    # --- THIS IS WHAT'S MISSING ---
    # We need a place to store the window reference so it doesn't get garbage collected
    my_widget.pdf_window = None

    # --- Add them to the chat display ---
    my_widget.add_message_card(user_card)
    my_widget.add_message_card(thinking_card)
    my_widget.add_message_card(assistant_card)
    my_widget.add_message_card(user_card2)
    my_widget.add_message_card(thinking_card2)
    my_widget.add_message_card(assistant_card2)
    my_widget.add_message_card(source_card)

    # Optional: scroll to bottom if you have that method
    if hasattr(my_widget, "scroll_to_bottom"):
        my_widget.scroll_to_bottom()

    # --- Run app ---
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
