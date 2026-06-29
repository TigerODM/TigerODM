import os
import sys
import docx
import pandas as pd
from docx.oxml.ns import qn
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QApplication, QPushButton, QLineEdit, QCheckBox

from Orange.widgets.utils.signals import Input, Output
from Orange.data import Domain, StringVariable, Table, DiscreteVariable

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import base_widget
    from Orange.widgets.orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file
else:
    from orangecontrib.AAIT.utils import base_widget
    from orangecontrib.AAIT.utils.initialize_from_ini import apply_modification_from_python_file


@apply_modification_from_python_file(filepath_original_widget=__file__)
class OWExtractTablesDocxToXlsx(base_widget.BaseListWidget):
    """
    Orange Widget qui extrait les tableaux de documents Word (.docx) et les sauvegarde
    en fichiers XLSX distincts (une table Word = un fichier XLSX).
    """
    name = "Docx to XLSX"
    description = "Extract tables from Word documents and save them as XLSX, with an optional split feature."
    category = "AAIT - TOOLBOX"
    icon = "icons/extract_table.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/extract_table.png"
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_extract_tables_docx_to_xlsx.ui")
    want_control_area = False
    priority = 1005

    selected_column_name = Setting("path")
    checkBox_alpha_headers: str = Setting("True")
    lineEdit_trigger_text: str = Setting("Routing item")

    class Inputs:
        data = Input("Files Table", Table)

    class Outputs:
        data = Output("Processed Files Table", Table)
        status_data = Output("Status Table", Table)

    @Inputs.data
    def set_data(self, in_data: Table | None):
        self.data = in_data
        if in_data:
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
            if self.autorun:
                self.run()
        else:
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(470)
        self.setFixedHeight(580)

        self.checkbox_headers = self.findChild(QCheckBox, "checkBox_headers")
        self.pushButton_run = self.findChild(QPushButton, "pushButton_run")
        self.lineEdit_trigger_ui = self.findChild(QLineEdit, "trigger_text")

        # Application des réglages sauvegardés aux widgets UI
        if self.checkbox_headers:
            self.checkbox_headers.setChecked(self.checkBox_alpha_headers == "True")
            self.checkbox_headers.stateChanged.connect(self._update_alpha_headers_state)

        if self.lineEdit_trigger_ui:
            self.lineEdit_trigger_ui.setText(self.lineEdit_trigger_text)
            self.lineEdit_trigger_ui.textChanged.connect(self._update_trigger_text)

        if self.pushButton_run:
            self.pushButton_run.clicked.connect(self.run)

        self.trigger_text = self.lineEdit_trigger_text
        self.use_alpha_headers = (self.checkBox_alpha_headers == "True")

        self.data = None
        self.autorun = True
        self.processed_statuses = []

        self.post_initialized()

    def _update_alpha_headers_state(self, state):
        """Met à jour le Setting et la variable de travail."""
        self.checkBox_alpha_headers = "True" if state else "False"
        self.use_alpha_headers = bool(state)

    def _update_trigger_text(self, text):
        """Met à jour le Setting et la variable de travail."""
        self.lineEdit_trigger_text = text.strip()
        self.trigger_text = text.strip()

    def run(self):
        if self.data is None:
            self.Outputs.data.send(None)
            self.Outputs.status_data.send(None)
            return

        self.error("")
        # Vérification de la présence de la colonne sélectionnée
        if self.selected_column_name not in self.data.domain:
            self.error(f"La colonne '{self.selected_column_name}' est manquante.")
            return

        self.progressBarInit()
        self.processed_statuses = []
        self.Outputs.status_data.send(None)

        if self.trigger_text:
            self.information(f"Utilisation du trigger de split : '{self.trigger_text}'")
        else:
            self.information("Aucun trigger de split défini. Export standard.")

        result_rows = self._process_files(self.data)

        output_domain = Domain([], metas=[
            StringVariable("src_path"),
            StringVariable("output_dir_path"),
            StringVariable("status")
        ])
        result_table = Table.from_list(output_domain, result_rows)
        self.Outputs.data.send(result_table)
        self.progressBarFinished()

    def _process_files(self, in_data: Table) -> list:
        result_rows = []
        # Utilisation dynamique de la colonne choisie par l'utilisateur
        file_paths = [str(x) for x in in_data.get_column(self.selected_column_name)]
        total_files = len(file_paths)

        if not file_paths:
            return []

        for i, full_path in enumerate(file_paths):
            self.progressBarSet((i + 1) / total_files * 100)

            status_short = "ko"
            details = "traitement échoué"
            output_dir_path = ""

            if not full_path.lower().endswith('.docx'):
                status_short = "skipped"
                details = "Fichier ignoré : n'est pas un fichier .docx."
                output_dir_path = "N/A"
                self.processed_statuses.append([full_path, status_short, details])
                self._send_status_table()
                result_rows.append([full_path, output_dir_path, f"{status_short}: {details}"])
                QApplication.processEvents()
                continue

            try:
                tables_found, output_dir_path = self._extraire_et_convertir(full_path)

                if tables_found > 0:
                    status_short = "ok"
                    details_suffix = "séparée(s)" if self.trigger_text else "standard(s)"
                    details = f"{tables_found} table(s) {details_suffix} extraite(s) et convertie(s) en XLSX."
                else:
                    status_short = "ko"
                    details = "Aucune table valide trouvée."

            except FileNotFoundError:
                details = "Fichier non trouvé."
            except Exception as e:
                details = f"Une erreur inattendue est survenue : {e}"

            self.processed_statuses.append([full_path, status_short, details])
            self._send_status_table()
            result_rows.append([full_path, output_dir_path, f"{status_short}: {details}"])
            QApplication.processEvents()

        return result_rows

    # ------------------------------------------------------------------ #
    # Extraction du texte des cellules — gère les champs (REF, STYLEREF…) #
    # ------------------------------------------------------------------ #

    def _extract_text_from_paragraphs(self, paragraphs) -> str:
        """
        Extrait le texte d'une liste de paragraphes, en capturant à la fois les
        runs statiques et les résultats mis en cache des champs (séquence
        w:fldChar begin/separate/end et w:fldSimple). Se rabat sur le nom du
        signet de instrText lorsque la zone de résultat en cache est vide.
        """
        all_parts = []

        for para in paragraphs:
            para_parts = []
            field_depth = 0
            in_instr = False
            current_instr = []
            current_result = []

            def _flush_field():
                result = " ".join(current_result).strip()
                instr = " ".join(current_instr).strip()
                if result:
                    para_parts.append(result)
                else:
                    # Résultat en cache vide : on se rabat sur le nom du signet de instrText
                    tokens = instr.split()
                    if len(tokens) >= 2:
                        para_parts.append(f"[{tokens[1]}]")
                    elif tokens:
                        para_parts.append(f"[{instr}]")
                    else:
                        para_parts.append("[EMPTY_FIELD]")
                current_instr.clear()
                current_result.clear()

            for child in para._element.iter():
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

                if tag == "fldSimple":
                    # Champ autonome : <w:fldSimple w:instr="REF ..."><w:r><w:t>valeur</w:t></w:r></w:fldSimple>
                    instr = child.get(qn("w:instr"), "")
                    result_texts = [
                        t.text for t in child.findall(".//" + qn("w:t"))
                        if t.text and t.text.strip()
                    ]
                    if result_texts:
                        para_parts.append(" ".join(result_texts))
                    else:
                        tokens = instr.split()
                        if len(tokens) >= 2:
                            para_parts.append(f"[{tokens[1]}]")
                        elif tokens:
                            para_parts.append(f"[{instr}]")

                elif tag == "fldChar":
                    fld_type = child.get(qn("w:fldCharType"))
                    if fld_type == "begin":
                        field_depth += 1
                        in_instr = True
                    elif fld_type == "separate":
                        in_instr = False
                    elif fld_type == "end":
                        field_depth = max(0, field_depth - 1)
                        _flush_field()
                        in_instr = False

                elif tag == "instrText":
                    if child.text:
                        current_instr.append(child.text)

                elif tag == "t":
                    text = child.text or ""
                    if text.strip():
                        if in_instr:
                            pass  # on ignore le texte d'instruction
                        elif field_depth > 0:
                            current_result.append(text)
                        else:
                            para_parts.append(text)

            if para_parts:
                all_parts.append(" ".join(para_parts))

        return "\n".join(all_parts)

    def _extract_cell_text_from_xml(self, tc_element) -> str:
        """
        Extrait le texte d'un élément XML w:tc brut, en itérant directement sur
        les enfants w:p pour éviter les problèmes de déduplication des cellules
        fusionnées de python-docx. Récurse également dans les tables imbriquées
        de la cellule.
        """
        all_parts = []

        # Paragraphes directs de cette cellule
        paragraphs_xml = tc_element.findall(".//" + qn("w:p"))

        # On a besoin d'objets paragraphes — on construit des wrappers minimaux
        # par itération sur les éléments.
        # Mais _extract_text_from_paragraphs attend des objets exposant ._element,
        # on enveloppe donc chaque w:p dans un proxy léger.
        class _ParaProxy:
            def __init__(self, el):
                self._element = el

        para_proxies = [_ParaProxy(p) for p in paragraphs_xml]
        text = self._extract_text_from_paragraphs(para_proxies)
        if text.strip():
            all_parts.append(text.strip())

        return "\n".join(all_parts)

    # ------------------------------------------------------------------ #
    # Extraction principale                                                #
    # ------------------------------------------------------------------ #

    def _extraire_et_convertir(self, docx_path):
        """
        Extrait les tableaux d'un document Word.
        Sauvegarde les tables (splittées ou non) dans '..._tables_data'.
        """
        dir_name, file_name = os.path.split(docx_path)
        base_name, _ = os.path.splitext(file_name)

        output_dir_main = os.path.join(dir_name, base_name + '_tables_data')
        os.makedirs(output_dir_main, exist_ok=True)

        doc = docx.Document(docx_path)
        total_tables_main_found = 0

        # Récupère le trigger et le met en minuscule (ou None)
        trigger_text_lower = self.trigger_text.lower() if self.trigger_text else None

        for i, table in enumerate(doc.tables):
            try:
                raw_data = []

                # Fallback table : accès sécurisé aux lignes (structure potentiellement corrompue)
                try:
                    rows_xml = table._element.findall(".//" + qn("w:tr"))
                except Exception as e:
                    self.warning(
                        f"Table {i + 1} ignorée (accès aux lignes impossible) "
                        f"dans '{docx_path}': {e}"
                    )
                    continue

                for row_idx, row_xml in enumerate(rows_xml):
                    # Fallback ligne : on skippe les lignes défectueuses sans bloquer la table
                    try:
                        # Récupère chaque w:tc directement depuis le XML de la ligne —
                        # évite totalement la duplication des cellules fusionnées de python-docx
                        cell_elements = row_xml.findall(qn("w:tc"))
                        row_data = []
                        for cell_idx, tc in enumerate(cell_elements):
                            cell_text = self._extract_cell_text_from_xml(tc)
                            row_data.append(cell_text)

                        raw_data.append(row_data)
                    except Exception as e:
                        self.warning(
                            f"Table {i + 1}, ligne {row_idx + 1} ignorée "
                            f"dans '{docx_path}': {e}"
                        )
                        continue

                if not raw_data or not any(row for row in raw_data):
                    continue

                table_index = i + 1

                if trigger_text_lower:
                    # Cas A : Un trigger est fourni, on split
                    sub_tables_data = self._split_table_data(raw_data, trigger_text_lower)
                    for j, sub_table_data in enumerate(sub_tables_data):
                        table_name = f"table_{table_index}_{chr(ord('a') + j)}"
                        df_split = self._create_dataframe(sub_table_data)
                        if df_split is not None and not df_split.empty:
                            self._save_sub_table(df_split, output_dir_main, table_name)
                            total_tables_main_found += 1
                else:
                    # Cas B : Pas de trigger, comportement original
                    table_name = f"table_{table_index}_a"  # Garde le suffixe _a pour cohérence
                    df_main = self._create_dataframe(raw_data)
                    if df_main is not None and not df_main.empty:
                        self._save_sub_table(df_main, output_dir_main, table_name)
                        total_tables_main_found += 1

            except Exception as e:
                self.warning(f"Table {i + 1} ignorée (erreur inattendue) : {e}")
                continue

        return total_tables_main_found, output_dir_main

    def _split_table_data(self, raw_data: list, trigger_text: str) -> list:
        data = [row for row in raw_data if row and any(cell.strip() for cell in row)]
        if not data:
            return []

        if self.use_alpha_headers:
            sub_tables = []
            current_table = [data[0]]
            for row in data[1:]:
                if any(trigger_text in str(cell).lower() for cell in row):
                    # Déclencheur détecté (mode alpha-headers). Division.
                    if current_table:
                        sub_tables.append(current_table)
                    current_table = [row]
                else:
                    current_table.append(row)
            if current_table:
                sub_tables.append(current_table)
            return sub_tables
        else:
            if len(data) <= 1:
                return [data]

            headers = data[0]
            data_rows = data[1:]
            final_tables = []
            current_data_segment = []

            if data_rows:
                current_data_segment.append(data_rows[0])  # La ligne n+1 ne splite jamais

            for row in data_rows[1:]:  # Commence à n+2
                if any(trigger_text in str(cell).lower() for cell in row):
                    # Déclencheur détecté (mode 1ère-ligne-header). Division.
                    if current_data_segment:
                        final_tables.append([headers] + current_data_segment)
                    current_data_segment = [row]
                else:
                    current_data_segment.append(row)

            if current_data_segment:
                final_tables.append([headers] + current_data_segment)

            return final_tables

    def _create_dataframe(self, data):
        data = [row for row in data if row and any(cell.strip() for cell in row)]
        if not data:
            return None

        max_cols = max(len(row) for row in data)
        data = [row + [''] * (max_cols - len(row)) for row in data]

        if self.use_alpha_headers:
            headers = [chr(ord('A') + j) for j in range(max_cols)]
            df = pd.DataFrame(data, columns=headers)
        else:
            # Cas B : Première ligne comme en-tête.
            if len(data) == 1:
                # Si le segment n'a qu'une seule ligne, on utilise des en-têtes alphabétiques.
                headers = [chr(ord('A') + j) for j in range(max_cols)]
                df = pd.DataFrame(data, columns=headers)
            else:
                # Cas standard : première ligne = en-tête, reste = données.
                headers = data[0]
                data_rows = data[1:]
                min_cols = min(len(headers), max_cols)

                if not data_rows:
                    df = pd.DataFrame(columns=headers[:min_cols])
                else:
                    data_rows_adjusted = [row[:min_cols] for row in data_rows]
                    df = pd.DataFrame(data_rows_adjusted, columns=headers[:min_cols])

            df.columns = df.columns.astype(str)

        return df

    def _save_sub_table(self, df, output_dir, table_full_name):
        output_xlsx_path = os.path.join(output_dir, f"{table_full_name}.xlsx")
        try:
            df.to_excel(output_xlsx_path, index=False, engine='openpyxl')
        except Exception as e:
            self.warning(f"Impossible de sauvegarder la table '{table_full_name}' en format XLSX : {e}")

    def _send_status_table(self):
        domain = Domain([], metas=[
            StringVariable("src_path"),
            DiscreteVariable("status", values=["ok", "ko", "skipped"]),
            StringVariable("details")
        ])
        status_table = Table.from_list(domain, self.processed_statuses)
        self.Outputs.status_data.send(status_table)

    def post_initialized(self):
        pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWExtractTablesDocxToXlsx()
    my_widget.show()
    if hasattr(app, "exec"):
        app.exec()
    else:
        app.exec_()