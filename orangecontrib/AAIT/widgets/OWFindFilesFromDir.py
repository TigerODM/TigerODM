import os
import sys
import Orange.data
from AnyQt.QtWidgets import QApplication, QLineEdit, QCheckBox,QSpinBox, QPushButton
from Orange.data import StringVariable, Table, Domain
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.settings import Setting
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
from AnyQt.QtCore import QTimer

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import base_widget, help_management
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import base_widget, help_management
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWFileFromDir(base_widget.BaseListWidget):
    name = "Find Files From Dir"
    description = ("Search files by extension or no for all files in a directory or subdirectories.")
    category = "AAIT - TOOLBOX"
    icon = "icons/owfilesfromdir.svg"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/owfilesfromdir.svg"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/owfindfilesfromdir.ui")
    want_control_area = False
    priority = 1060
    selected_column_name = Setting("input_dir")
    extension = Setting("")
    recursive = Setting("False")
    ignore_orphan=Setting("False")
    filter_per_date = Setting("False")
    extra_column = Setting("False")
    time_filter= Setting("0-0-0-1")

    class Inputs:
        data = Input("Data", Orange.data.Table)

    class Outputs:
        data = Output("Data", Orange.data.Table)


    @Inputs.data
    def set_path_table(self, in_data):
        self.data = in_data
        if in_data is None:
            self.Outputs.data.send(None)
            return
        if self.data:
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        self.run()


    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(500)
        self.setFixedHeight(620)
        if self.is_dash_int_castable(self.time_filter)!=0:
            self.time_filter = "0-0-0-1"

        self.edit_extension = self.findChild(QLineEdit, 'lineEdit')
        self.edit_extension.setPlaceholderText("Extension (.docx, .pdf, .xslx, .csv, .json ...)")
        self.edit_extension.setText(self.extension)
        self.edit_extension.editingFinished.connect(self.update_parameters)
        self.comboBox = self.findChild(QCheckBox, 'checkBox')
        self.checkBox_2 = self.findChild(QCheckBox, 'checkBox_2')
        self.checkBox_3 = self.findChild(QCheckBox, 'checkBox_3')

        self.spinBox_day = self.findChild(QSpinBox, 'spinBox_day')
        self.spinBox_hour = self.findChild(QSpinBox, 'spinBox_hour')
        self.spinBox_minute = self.findChild(QSpinBox, 'spinBox_minute')
        self.spinBox_second= self.findChild(QSpinBox, 'spinBox_second')
        self.checkBox_extra_column = self.findChild(QCheckBox, 'checkBox_extra_column')

        DD,JJ,SS,MM=self._parse_delta_4_numbers(self.time_filter)
        self.spinBox_day.setValue(int(DD))
        self.spinBox_hour.setValue(int(JJ))
        self.spinBox_minute.setValue(int(SS))
        self.spinBox_second.setValue(int(MM))
        # Data Management
        self.folderpath = None
        self.data = None
        self.autorun = True
        self.post_initialized()

        if self.filter_per_date=="False":
            self.checkBox_2.setChecked(False)
            self.spinBox_day.setVisible(False)
            self.spinBox_hour.setVisible(False)
            self.spinBox_minute.setVisible(False)
            self.spinBox_second.setVisible(False)
        else:
            self.checkBox_2.setChecked(True)
            self.spinBox_day.setVisible(True)
            self.spinBox_hour.setVisible(True)
            self.spinBox_minute.setVisible(True)
            self.spinBox_second.setVisible(True)

        if self.recursive == "True":
            self.comboBox.setChecked(True)

        if self.ignore_orphan=="False":
            self.checkBox_3.setChecked(False)
        else:
            self.checkBox_3.setChecked(True)

        if self.extra_column=="True":
            self.checkBox_extra_column.setChecked(True)
        else:
            self.checkBox_extra_column.setChecked(False)

        self.comboBox.stateChanged.connect(self.on_checkbox_toggled)
        self.checkBox_2.stateChanged.connect(self.on_checkBox_2_toggled)
        self.checkBox_3.stateChanged.connect(self.on_checkBox_3_toggled)


        self.checkBox_extra_column.stateChanged.connect(self.checkBox_extra_column_toggled)
        self.spinBox_day.valueChanged.connect(self.on_value_changed)
        self.spinBox_hour.valueChanged.connect(self.on_value_changed)
        self.spinBox_minute.valueChanged.connect(self.on_value_changed)
        self.spinBox_second.valueChanged.connect(self.on_value_changed)

        self.pushButton_run =self.findChild(QPushButton, 'pushButton_send')
        self.pushButton_run.clicked.connect(self.run)
        QTimer.singleShot(0, lambda: help_management.override_help_action(self))


    def on_value_changed(self):
        self.time_filter = str(self.spinBox_day.value())+"-"+str(self.spinBox_hour.value())+"-"+str(self.spinBox_minute.value())+"-"+str(self.spinBox_second.value())
    def update_parameters(self):
        self.extension = (self.edit_extension.text() or "").strip() #a jout de la gestion d'une zone vide
        if self.folderpath is not None:
            self.run()

    def on_checkbox_toggled(self,state):
        self.recursive = "True"
        if state==0:
            self.recursive = "False"
        if self.folderpath is not None:
            self.run()
    def on_checkBox_2_toggled(self,state):
        self.filter_per_date = "True"
        if state==0:
            self.filter_per_date = "False"

        if self.filter_per_date == "False":
            self.spinBox_day.setVisible(False)
            self.spinBox_hour.setVisible(False)
            self.spinBox_minute.setVisible(False)
            self.spinBox_second.setVisible(False)
        else:
            self.spinBox_day.setVisible(True)
            self.spinBox_hour.setVisible(True)
            self.spinBox_minute.setVisible(True)
            self.spinBox_second.setVisible(True)

        if self.folderpath is not None:
            self.run()

    def on_checkBox_3_toggled(self,state):
        self.ignore_orphan = "True"
        if state==0:
            self.ignore_orphan = "False"


    def checkBox_extra_column_toggled(self,state):
        self.extra_column = "True"
        if state==0:
            self.extra_column = "False"



    def residual_path(self,parent_dir: str, child_path: str) -> str:
        """
        Renvoie la partie résiduelle de child_path par rapport à parent_dir.
        Ex: parent=C:/data, child=C:/data/a/b/file.txt => "a/b/file.txt"
        Indépendant des back slash et slash (Windows/Linux/mac).
        """
        parent = Path(parent_dir).expanduser().resolve()
        child = Path(child_path).expanduser().resolve()

        # Cas normal: child est dans parent
        try:
            rel = child.relative_to(parent)
            return rel.as_posix()  # format stable ("/")
        except ValueError:
            # Fallback: compare en "samefile" / normalisation, puis calcule un relpath
            # (utile si resolve() n’aligne pas tout comme prévu)
            import os
            rel2 = os.path.relpath(str(child), start=str(parent))
            return Path(rel2).as_posix()

    def find_files(self):
        files_data = []
        roots_data=[]
        files_data_rel=[]
        suffixes = self.parse_extensions()  # si pas de d'extensions, elles apparaitront toutes

        for i in range(len(self.folderpath)):
            base = self.folderpath[i]
            if self.recursive == "True":
                traversal = os.walk(base)
            else:
                try:
                    traversal = [(base, [], os.listdir(base))]
                except Exception:
                    continue

            for root, _, files in traversal:
                for file in files:
                    # on ignore les liens symboliques et et les dossiers
                    full_path = os.path.join(root, file)
                    if not os.path.isfile(full_path) or os.path.islink(full_path):
                        continue

                    if self.ignore_orphan == "True":
                        if file.startswith("~$") : # or file.startswith(".~") peut etre a ajouter
                            continue
                    name = file.lower()
                    if suffixes is None or name.endswith(suffixes):
                        files_data.append([os.path.join(root, file).replace("\\", "/")])
                        roots_data.append(base)
                        files_data_rel.append(self.residual_path(base,os.path.join(root, file).replace("\\", "/")))

        return [files_data,roots_data,files_data_rel]

    def parse_extensions(self):
        """
        Convertit la saisie utilisateur en tuple de suffixes normalisés pour endswith.
        Exemples d'entrées valides :
          - ".pdf, .docx"
          - "pdf docx"
          - "csv"
          - "" (vide => aucune filtration, donc toutes extensions)
        """
        raw = (self.extension or "").strip().lower()
        if not raw:
            return None  # pas de filtre => tout passe

        # accepte virgules ou espaces multiples comme séparateurs
        parts = [p.strip() for chunk in raw.split(",") for p in chunk.split()]
        # normalise en ajoutant le point s'il manque, ignore les vides
        cleaned = []
        for p in parts:
            if not p:
                continue
            if not p.startswith("."):
                p = "." + p
            cleaned.append(p)

        if not cleaned:
            return None
        return tuple(set(cleaned))  # tuple unique pour endswith(...)

    def is_dash_int_castable(self,value: str) -> int:
        """
        Retourne 0 si tous les morceaux séparés par '-' sont castables en int, 1 sinon.
        Exemple :
          "1-0-0-1" -> 0
          "10-5-3-2" -> 0
          "1-a-0-1" -> 1
        """
        try:
            parts = value.split("-")
            if len(parts)!=4:
                return 1

            for p in parts:
                int(p)  # essaie de caster chaque partie
            return 0
        except (ValueError, TypeError):
            return 1

    def _parse_delta_4_numbers(self,delta_str):
        return(delta_str.split("-"))



    def _parse_delta(self,delta_str):
        """
        Accepte soit:
          - 'AA-MM-JJ-HH-mm-SS' (années, mois, jours, heures, minutes, secondes)
          - 'JJJJJ-HH-mm-SS'   (jours, heures, minutes, secondes)
        Les valeurs peuvent être non paddées (ex: '1-0-0-1').
        """
        parts = delta_str.split("-")
        try:
            nums = [int(p) for p in parts]
        except Exception as e:
            raise ValueError(
                "Delta invalide '{}'. Parties non entières.".format(delta_str)
            ) from e

        if len(nums) == 6:
            aa, mm, jj, hh, mi, ss = nums
            days = aa * 365 + mm * 30 + jj  # approximation mois=30j, année=365j
            return timedelta(days=days, hours=hh, minutes=mi, seconds=ss)
        elif len(nums) == 4:
            jj, hh, mi, ss = nums
            return timedelta(days=jj, hours=hh, minutes=mi, seconds=ss)
        else:
            raise ValueError(
                "Delta invalide '{}'. Formats acceptés: "
                "AA-MM-JJ-HH-mm-SS OU JJJJJ-HH-mm-SS.".format(delta_str)
            )

    def _created_or_modified_time(self,path):
        """
        Retourne l'instant (UTC) le plus récent entre création (si dispo) et modification.
        - Windows: st_ctime ~ création
        - Unix: st_ctime = change time; on utilise st_birthtime si disponible.
        """
        st = os.stat(path)
        mtime = st.st_mtime
        birth = getattr(st, "st_birthtime", None)
        best_epoch = max(mtime, birth) if birth is not None else mtime
        return datetime.utcfromtimestamp(best_epoch)

    def filter_files_newer_than_delta(
            self,
            files_data,
            roots_data,
            files_data_rel,
            delta_str,
            now=None,
            skip_missing=True,
    ):
        """
        Filtre files_data, roots_data et files_data_rel en conservant
        uniquement les entrées dont le fichier est plus récent que le delta.

        :param files_data: liste ex. [[abs_path], [abs_path2], ...]
        :param roots_data: liste parallèle
        :param files_data_rel: liste parallèle
        :param delta_str: 'AA-MM-JJ-HH-mm-SS' OU 'JJJJJ-HH-mm-SS'
        :param now: datetime de référence UTC
        :param skip_missing: True -> ignore fichiers manquants
        :return: (files_data_filtres, roots_data_filtres, files_data_rel_filtres)
        """
        delta = self._parse_delta(delta_str)
        ref = now or datetime.utcnow()
        threshold = ref - delta

        filtered_files_data = []
        filtered_roots_data = []
        filtered_files_data_rel = []

        for file_item, root_item, rel_item in zip(files_data, roots_data, files_data_rel):
            p = file_item[0]

            if not os.path.isabs(p):
                pass

            if not os.path.exists(p):
                if skip_missing:
                    continue
                raise FileNotFoundError(p)

            try:
                t = self._created_or_modified_time(p)
            except Exception:
                if not skip_missing:
                    raise
                continue

            if t >= threshold:
                filtered_files_data.append(file_item)
                filtered_roots_data.append(root_item)
                filtered_files_data_rel.append(rel_item)

        return filtered_files_data, filtered_roots_data, filtered_files_data_rel

    def run(self):
        self.error("")
        self.warning("")

        if self.data is None:
            self.Outputs.data.send(None)
            return

        if not self.selected_column_name in self.data.domain:
            self.warning(f'Previously selected column "{self.selected_column_name}" does not exist in your data.')
            self.Outputs.data.send(None)
            return
        if self.extra_column=="True":
            if "root_dir" in  self.data.domain:
                self.error("The input column must not contain root_dir.")
                return
            if "relative_path" in  self.data.domain:
                self.error("The input column must not contain relative_path.")
                return

        self.folderpath = self.data.get_column(self.selected_column_name)

        try:
            files_data,roots_data,files_data_rel = self.find_files()
            if self.filter_per_date !="False":
                files_data, roots_data, files_data_rel = self.filter_files_newer_than_delta(
                    files_data,
                    roots_data,
                    files_data_rel,
                    self.time_filter
                )

            if len(files_data) == 0:
                self.Outputs.data.send(None)
                return

            if self.extra_column!="True":
                X = [[] for _ in files_data]
                domain = Domain([], metas=[StringVariable("path")])
                table = Table.from_numpy(domain, X, metas=files_data)
            else:
                def _scalar_str(v):
                    # Transforme v en string scalaire (si v est un tableau/list 1-élément, prend v[0])
                    if isinstance(v, (list, tuple, np.ndarray)):
                        if len(v) == 1:
                            v = v[0]
                    return "" if v is None else str(v)

                X = [[] for _ in range(len(files_data))]

                domain = Domain(
                    [],
                    metas=[
                        StringVariable("path"),
                        StringVariable("root_dir"),
                        StringVariable("relative_path"),
                    ],
                )

                metas = [
                    [_scalar_str(p), r, rel]
                    for p, r, rel in zip(files_data, roots_data, files_data_rel)
                ]

                table = Table.from_numpy(domain, X, metas=metas)
            self.Outputs.data.send(table)
        except Exception as e:
            self.error(f"An error occurred: the provided file path may not be supported ({e})")
            return

    def post_initialized(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWFileFromDir()
    my_widget.show()

    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()
