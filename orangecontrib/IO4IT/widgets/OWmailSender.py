import os
import sys
# from Orange.data import Domain, StringVariable, Table
import Orange.data
from AnyQt.QtWidgets import QApplication
from Orange.widgets import widget
from Orange.widgets.utils.signals import Input, Output

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.import_uic import uic
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils.import_uic import uic
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWMailSender(widget.OWWidget):
    name = "OWMailSender"
    description = "Send a mail from AAIT format"
    icon = ""
    icon = "icons/mail_writer.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
       icon = "icons_dev/mail_writer.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owmailsender.ui")
    want_control_area = False
    priority = 9999
    category = "AAIT - API"

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        self.data = in_data
        if self.autorun:
            self.run()


    def __init__(self):
        super().__init__()
        # Qt Management
        self.valid_folders=[]
        self.can_run = True
        self.setFixedWidth(700)
        self.setFixedHeight(500)
        uic.loadUi(self.gui, self)

        # # Data Management
        self.data = None
        self.thread = None
        self.autorun = True

        # Custom updates
        self.post_initialized()

    def run(self):
        self.error("")
        if self.data is None:
            return

        # TODO : Rajouter le content du mail original ?
        domain_requirements = ["Sender", "Receiver", "Copy", "Priority", "Title", "Answer"]
        for name in domain_requirements:
            if not name in self.data.domain:
                self.error(f'You need a column "{name}" in your input data.')
                return

        for row in self.data:
            mail_path = row["Mail path"].value
            # TODO : que faire si out_dir_path existe déjà ? pour le moment ça le remplacera juste, est-ce qu'on veut un warning ?
            out_dir_path = os.path.dirname(mail_path)
            out_mail_path = os.path.join(out_dir_path, "mail.txt")
            out_mail_path_ok = os.path.join(out_dir_path, "mail.ok")
            os.makedirs(out_dir_path, exist_ok=True)
            response_content = self.format_response(row)
            with open(out_mail_path, "w", encoding="utf-8") as f:
                f.write(response_content)
            with open(out_mail_path_ok, "w", encoding="utf-8") as f:
                f.write(response_content)
        self.Outputs.data.send(self.data)


    def format_response(self, row):
        """
        Formats metadata from an Orange Data Table row into a structured text block.

        Extracts specific fields (Receiver, Sender, Copy, Priority, Title, Answer) from the given row,
        maps them to standardized tags (eme, des, cop, pri, tit, txt), and returns a string formatted
        in the style of metadata headers (e.g., "#$eme : value").

        Parameters:
            row (Orange.data.Instance): A single row from an Orange Data Table.

        Returns:
            str: A formatted string representing the metadata of the row, ready to be saved or processed.
        """
        # Gather the metadata from the row instance
        sender = self.safe_get(row, "Sender")
        receiver = self.safe_get(row, "Receiver")
        copy = self.safe_get(row, "Copy")
        priority = self.safe_get(row, "Priority")
        title = self.safe_get(row, "Title")
        answer = self.safe_get(row, "Answer")

        # Format the metadata with proper prefixes
        # TODO : ajouter la gestion du content original !
        metadata = {
            "eme": sender,
            "des": receiver,
            "cop": copy,
            "pri": priority,
            "tit": title,
            "txt": answer
        }

        # Build the text content as a string
        txt_content = ""
        for key, value in metadata.items():
            line = f"#${key} : {value if value is not None else ''}\n"
            txt_content += line
        return txt_content


    def safe_get(self, row, name):
        """
        Safely retrieves the value of a given column from a row in an Orange Data Table.

        Parameters:
            row (Orange.data.Instance): A single row from an Orange Table.
            name (str): The name of the column to retrieve.

        Returns:
            The value of the column if it exists in the table domain, otherwise "Empty".
        """
        return row[name].value if name in self.data.domain else "Empty"


    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # data = Orange.data.Table("C:/toto_ta_ta_titi/input.tab")
    my_widget = OWMailSender()
    my_widget.show()
    # my_widget.set_data(data)

    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
