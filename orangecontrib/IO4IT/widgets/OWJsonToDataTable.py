import os
import sys
import json
import numpy as np
import Orange
from Orange.widgets.widget import Input, Output
from AnyQt.QtWidgets import QApplication
from Orange.widgets.settings import Setting
from AnyQt.QtWidgets import QCheckBox
from Orange.data import Table, Domain, StringVariable, ContinuousVariable, DiscreteVariable
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.HLIT.remote_server_smb import convert
    from Orange.widgets.orangecontrib.AAIT.utils import base_widget
else:
    from orangecontrib.HLIT.remote_server_smb import convert
    from orangecontrib.AAIT.utils import base_widget


class OWJsonToDataTable(base_widget.BaseListWidget):
    name = "JsonToDataTable"
    description = "Convert Json to Orange data table. You need to pass a content in input."
    icon = "icons/json-file.png"
    if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
        icon = "icons_dev/json-file.png"
    priority = 3000
    gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "designer/ow_json_to_data_table.ui")
    want_control_area = False
    category = "AAIT - TOOLBOX"
    selected_column_name = Setting("content")
    data_table_to_json = Setting("False")
    deep_json = Setting("False")  # JSON profond / variable, decoche par defaut

    class Inputs:
        data = Input("Data", Orange.data.Table)
        path = Input("Path to json", Orange.data.Table)

    @Inputs.data
    def set_data(self, in_data):
        if in_data is None:
            return
        self.data = in_data
        if self.data:
            self.var_selector.add_variables(self.data.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        self.run()

    @Inputs.path
    def set_path(self, in_data):
        if in_data is None:
            return
        if self.data_table_to_json == "True":
            self.warning("")
            return
        self.path = in_data  # in_data est le chemin pas l entree in_data
        if self.path:
            self.var_selector.add_variables(self.path.domain)
            self.var_selector.select_variable_by_name(self.selected_column_name)
        self.run()

    class Outputs:
        data = Output("Data", Orange.data.Table)

    def __init__(self):
        super().__init__()
        # Qt Management
        self.setFixedWidth(500)
        self.setFixedHeight(450)
        self.data = None
        self.path = None

        self.check_box_data_table_to_json = self.findChild(QCheckBox, "checkBox")
        if self.data_table_to_json == "True":
            self.check_box_data_table_to_json.setChecked(True)
        else:
            self.check_box_data_table_to_json.setChecked(False)
        self.check_box_data_table_to_json.stateChanged.connect(self.on_checkbox_toggled)

        self.check_box_deep_json = self.findChild(QCheckBox, "checkBox_deep_json")
        if self.deep_json == "True":
            self.check_box_deep_json.setChecked(True)
        else:
            self.check_box_deep_json.setChecked(False)
        self.check_box_deep_json.stateChanged.connect(self.on_deep_json_toggled)

    def on_checkbox_toggled(self):
        if self.check_box_data_table_to_json.isChecked():
            self.data_table_to_json = "True"
        else:
            self.data_table_to_json = "False"

    def on_deep_json_toggled(self):
        if self.check_box_deep_json.isChecked():
            self.deep_json = "True"
        else:
            self.deep_json = "False"

    # ------------------------------------------------------------------
    # Lecture tolerante du JSON
    # ------------------------------------------------------------------
    @staticmethod
    def parse_json_text(text):
        """Retourne la liste des documents JSON contenus dans text.
        Gere : BOM, un seul document, plusieurs documents concatenes
        (JSON Lines / "Extra data"), et un JSON encode deux fois dans une chaine."""
        text = text.lstrip("\ufeff").strip()
        decoder = json.JSONDecoder()
        docs = []
        pos = 0
        n = len(text)
        while pos < n:
            doc, end = decoder.raw_decode(text, pos)
            if isinstance(doc, str):
                stripped = doc.strip()
                if stripped[:1] in ("{", "["):
                    doc = json.loads(stripped)
            docs.append(doc)
            pos = end
            # sauter espaces, retours ligne et virgules entre documents
            while pos < n and text[pos] in " \t\r\n,":
                pos += 1
        return docs

    @staticmethod
    def error_excerpt(text, pos, width=30):
        start = max(0, pos - width)
        return repr(text[start:pos + width])

    # ------------------------------------------------------------------
    # Mode JSON profond / variable
    # ------------------------------------------------------------------
    @staticmethod
    def _is_scalar(value):
        return value is None or isinstance(value, (str, int, float, bool))

    @staticmethod
    def _is_record_list(value):
        """Liste non vide dont les elements sont des objets JSON."""
        return isinstance(value, list) and len(value) > 0 and all(isinstance(v, dict) for v in value)

    def _flatten(self, value, prefix, out):
        """Aplatit les objets imbriques en cles pointees (a.b.c).
        Les listes ne creent jamais de colonnes indexees : elles restent en texte JSON
        dans une seule cellule."""
        if isinstance(value, dict):
            if not value and prefix:
                out[prefix] = None
            for key, sub in value.items():
                new_key = f"{prefix}.{key}" if prefix else str(key)
                self._flatten(sub, new_key, out)
        elif isinstance(value, list):
            out[prefix or "value"] = json.dumps(value, ensure_ascii=False) if value else None
        else:
            out[prefix or "value"] = value

    def _extract_records(self, document):
        """Retourne une liste de (contexte, enregistrement).
        - liste racine : chaque element est un enregistrement ;
        - objet racine contenant une liste d'objets (ex. "issues") : chaque element de
          cette liste devient une ligne, les autres champs de la racine (total, startAt...)
          sont repetes sur chaque ligne ;
        - sinon l'objet racine est un seul enregistrement."""
        if isinstance(document, list):
            return [({}, item) for item in document]
        if isinstance(document, dict):
            record_keys = [k for k, v in document.items() if self._is_record_list(v)]
            if record_keys:
                # la plus grande liste d'objets = les enregistrements
                main_key = max(record_keys, key=lambda k: len(document[k]))
                context = {}
                for key, value in document.items():
                    if key != main_key:
                        self._flatten(value, str(key), context)
                return [(context, item) for item in document[main_key]]
            return [({}, document)]
        return [({}, document)]

    def convert_deep_json_to_data_table(self, documents):
        pairs = []
        for document in documents:
            pairs.extend(self._extract_records(document))

        flat_records = []
        record_columns, record_seen = [], set()
        for context, record in pairs:
            flat = {}
            if isinstance(record, dict):
                self._flatten(record, "", flat)
            else:
                flat["value"] = record if self._is_scalar(record) else json.dumps(record, ensure_ascii=False)
            flat_records.append((context, flat))
            for key in flat:
                if key not in record_seen:
                    record_seen.add(key)
                    record_columns.append(key)

        # Champs du contexte (racine) : renommes en root.xxx s'ils existent aussi dans les enregistrements
        context_columns, context_seen = [], set()
        rows = []
        for context, flat in flat_records:
            row = dict(flat)
            for key, value in context.items():
                name = f"root.{key}" if key in record_seen else key
                row[name] = value
                if name not in context_seen:
                    context_seen.add(name)
                    context_columns.append(name)
            rows.append(row)

        columns = record_columns + [c for c in context_columns if c not in record_seen]
        # supprimer les colonnes entierement vides (ex. "assignee": null alors que
        # d'autres lignes ont deja assignee.displayName)
        columns = [c for c in columns if any(r.get(c) is not None for r in rows)]

        if not rows or not columns:
            return None

        attributes, metas = [], []
        attr_cols, meta_cols = [], []
        for col in columns:
            present = [r[col] for r in rows if r.get(col) is not None]
            if present and all(isinstance(v, bool) for v in present):
                attributes.append(DiscreteVariable(col, values=("False", "True")))
                attr_cols.append([np.nan if r.get(col) is None else float(bool(r[col])) for r in rows])
            elif present and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
                attributes.append(ContinuousVariable(col))
                attr_cols.append([np.nan if r.get(col) is None else float(r[col]) for r in rows])
            else:
                values = []
                for r in rows:
                    v = r.get(col)
                    if v is None:
                        values.append("")  # "" = valeur manquante (?) pour StringVariable
                    elif isinstance(v, str):
                        values.append(v)
                    else:
                        values.append(json.dumps(v, ensure_ascii=False))
                metas.append(StringVariable(col))
                meta_cols.append(values)

        n = len(rows)
        X = np.array(attr_cols, dtype=float).T if attr_cols else np.empty((n, 0))
        M = np.array(meta_cols, dtype=object).T if meta_cols else np.empty((n, 0), dtype=object)
        domain = Domain(attributes, metas=metas)
        return Table.from_numpy(domain, X, metas=M)

    # ------------------------------------------------------------------

    def run(self):
        self.error("")
        self.warning("")
        if self.data_table_to_json == "True":
            try:
                json_data = convert.convert_data_table_to_json(self.data)

                if json_data is None:
                    content = ""
                else:
                    content = json.dumps(json_data, ensure_ascii=False, indent=4)

                domain = Domain([], metas=[StringVariable("content")])

                out_data = Table.from_list(
                    domain,
                    [[content]]
                )

                self.Outputs.data.send(out_data)
                return
            except Exception as e:
                self.error(f"Error: {e}")
                self.Outputs.data.send(None)
                self.data = None
                self.path = None
                return

        try:
            obj = None
            documents = []  # documents JSON bruts, utilises par le mode deep
            if self.data:
                obj = []
                values = self.data.get_column(self.selected_column_name)
                texts = []
                non_str = []
                for raw in values:
                    if isinstance(raw, str):
                        if raw.strip() != "":
                            texts.append(raw)
                    elif raw is not None:
                        non_str.append(raw)

                row_errors = []
                for row_index, raw in enumerate(texts):
                    try:
                        parsed = self.parse_json_text(raw)
                        documents.extend(parsed)
                        for current_obj in parsed:
                            if isinstance(current_obj, list):
                                obj.extend(current_obj)
                            else:
                                obj.append(current_obj)
                    except json.JSONDecodeError as e:
                        row_errors.append((row_index, e, raw))

                if row_errors:
                    # Cas frequent : le JSON a ete decoupe sur plusieurs lignes de la table
                    # (une ligne du fichier = une ligne Orange). On recolle tout.
                    try:
                        obj = []
                        documents = self.parse_json_text("\n".join(texts))
                        for current_obj in documents:
                            if isinstance(current_obj, list):
                                obj.extend(current_obj)
                            else:
                                obj.append(current_obj)
                    except json.JSONDecodeError:
                        row_index, e, raw = row_errors[0]
                        self.error(f"Row {row_index}: {e.msg} (line {e.lineno}, column {e.colno}) "
                                   f"near: {self.error_excerpt(raw, e.pos)}")
                        self.Outputs.data.send(None)
                        self.data = None
                        self.path = None
                        return
                obj.extend(non_str)
                documents.extend(non_str)

            if self.path:
                raw = self.path.get_column(self.selected_column_name)[0]
                # utf-8-sig : gere le BOM ajoute par certains editeurs Windows
                with open(raw, "r", encoding="utf-8-sig") as f:
                    text = f.read()
                try:
                    docs = self.parse_json_text(text)
                except json.JSONDecodeError as e:
                    self.error(f"{os.path.basename(str(raw))}: {e.msg} (line {e.lineno}, column {e.colno}) "
                               f"near: {self.error_excerpt(text, e.pos)}")
                    self.Outputs.data.send(None)
                    self.data = None
                    self.path = None
                    return
                obj = docs[0] if len(docs) == 1 else docs
                documents = docs

            if self.deep_json == "True":
                data = self.convert_deep_json_to_data_table(documents)
                if data is None:
                    self.warning("Empty JSON: no data to convert.")
            else:
                # Convertir les valeurs de type liste en texte JSON pour qu'elles
                # deviennent des StringVariable dans la table Orange.
                if isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, dict):
                            for key, value in item.items():
                                if isinstance(value, list):
                                    item[key] = json.dumps(value, ensure_ascii=False)
                elif isinstance(obj, dict):
                    for key, value in obj.items():
                        if isinstance(value, list):
                            obj[key] = json.dumps(value, ensure_ascii=False)

                data = convert.convert_json_implicite_to_data_table(obj)

            self.Outputs.data.send(data)
            self.data = None
            self.path = None
        except Exception as e:
            self.error(f"Error: {e}")
            self.Outputs.data.send(None)
            self.data = None
            self.path = None

    def post_initialized(self):
        pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    my_widget = OWJsonToDataTable()
    my_widget.show()

    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())
