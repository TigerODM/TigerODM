import json
import Orange
from Orange.data import Table, Domain, StringVariable, ContinuousVariable
import math


def is_valid_json_string(data):
    try:
        json_str = json.dumps(data)
        json.loads(json_str)
        return 0
    except json.JSONDecodeError:
        return 1

def convert_json_to_orange_data_table(json_data):
    """
        Convertit une liste de dictionnaires JSON en un objet de données de type data table sous Orange data Mining (.tab)
        Exemple de json_data qui peut etre utilisé pour cette fonction :
        {"ows_path": "toto.ows", "front_id": "11OO1O1O1", "data": [{"num_input": 0, "values": [["col1", "col2", "col3"], ["float", "str", "float"], [[3, "test", 6], [4, "oui", 5]]]}]}

        :param json_data: Chaine json au format d'exemple
        :return: Data Table.
    """
    if is_valid_json_string(json_data) == 1:
        print("La data n'est pas au format json")
        return 1
    json_str = json.dumps(json_data)
    data = json.loads(json_str)
    domain = []
    data_continous = []
    data_metas = []
    table = []
    attributes = []
    metas = []
    for i, d in enumerate(data["values"][1]):
        if d == "str":
            metas.append(StringVariable(data["values"][0][i]))
        if d == "float":
            attributes.append(ContinuousVariable(data["values"][0][i]))
    for elem in data["values"][2]:
        if len(elem) != len(data["values"][1]):
            print("Il manque des données par rapport au nombre de colonnes")
            return 1
        d_metas = []
        d_continous = []
        for i, d in enumerate(data["values"][1]):
            if d == "str":
                d_metas.append(elem[i])
            if d == "float":
                d_continous.append(elem[i])
        data_metas.append(d_metas)
        data_continous.append(d_continous)
    domain = Domain(attributes, metas=metas)
    table = Table.from_numpy(domain, data_continous, metas=data_metas)
    return table

def safe_val(val):
    return "" if isinstance(val, float) and math.isnan(val) else val

def convert_data_table_to_json(data):
    """
        Convertit un objet de données de type data table sous Orange data Mining (.tab) en une liste de dictionnaires JSON.

        :param data: Objet contenant les données avec ses attributs et métadonnées.
        :return: Chaîne JSON formatée. None si erreur
    """

    if data == None or data == []:
        print("Pas de data en entree")
        return None
    feature_names = [var.name for var in data.domain.attributes]
    meta_names = [var.name for var in data.domain.metas]
    json_data = []
    for row in data:
        row_dict = {}
        for i, col in enumerate(feature_names):
            row_dict[col] = safe_val(row[i].value)
        for i, col in enumerate(meta_names):
            row_dict[col] = safe_val(row.metas[i])
        # Vérifier si la ligne contient uniquement des types (ex: "continuous", "discrete")
        if all(isinstance(value, str) and value in ["continuous", "discrete"] for value in row_dict.values()):
            continue  # Ignorer cette ligne
        json_data.append(row_dict)
    return json_data


def json_explicite_to_implicite(json_data):
    # json data du type {'num_input': 0, 'values': [['col1', 'col2', 'col3'], ['float', 'str', 'float'], [[3, 'test', 6], [4, 'oui', 5]]]}
    table = convert_json_to_orange_data_table(json_data)
    if table == 1:
        print("erreur dans convert_json_to_orange_data_table")
        return None
    json = convert_data_table_to_json(table)
    if json == None:
        print("erreur dans convert_data_table_to_json")
        return None
    return json

def json_implicite_to_explicite(json_data):
    print("a faire")

def is_explicite(json_data):
    if is_valid_json_string(json_data) == 1:
        print("La data n'est pas au format json")
        return 1
    if 'values' in json_data and isinstance(json_data['values'], list) and len(json_data['values']) == 3:
        if isinstance(json_data['values'][0], list) and isinstance(json_data['values'][1], list) and isinstance(json_data['values'][2], list):
            return 0
    return 1

def is_implicite(json_data):
    if is_valid_json_string(json_data) == 1:
        print("La data n'est pas au format json")
        return 1
    if not isinstance(json_data, list):
        return 1
    for i, element in enumerate(json_data):
        if not isinstance(element, dict):
            return f"L'élément à l'index {i} n'est pas un dictionnaire."
    cles_reference = set(json_data[0].keys())
    for i, d in enumerate(json_data[1:], start=2):
        cles_actuelles = set(d.keys())
        if cles_actuelles != cles_reference:
            print(
                f"Le dictionnaire #{i} n'a pas les mêmes clés. Clés attendues : {cles_reference}, trouvées : {cles_actuelles}")
            return 1
    return 0

def is_implicite_or_explicite(json_data):
    if is_implicite(json_data) == 0:
        print("implicite")
        return
    if is_explicite(json_data) == 0:
        print("explicite")
        return

# Fonction pour traduire Orange types en types Python
def orange_var_type_to_python(var):
    if var.is_string:
        return "str"
    if var.is_continuous:
        return "float"

def convert_data_table_to_json_explicite(data, num_input=None):
    if data == None or data == []:
        print("Pas de data en entree")
        return None

    feature_names = [var.name for var in data.domain.attributes]
    meta_names = [var.name for var in data.domain.metas]

    feature_types = [orange_var_type_to_python(var) for var in data.domain.attributes]
    meta_types = [orange_var_type_to_python(var) for var in data.domain.metas]

    if len(feature_names) != len(feature_types) or len(meta_names) != len(meta_types):
        print("Il manque des données par rapport au nombre de colonnes")
        return None

    new_data = []
    for i in range(len(data)):
        d = []
        for j in range(len(feature_names)):
            if data[i][j] is None or (isinstance(data[i][j].value, float) and math.isnan(data[i][j].value)):
                d.append(None)
            else:
                d.append(data[i][j].value)
        for j in range(len(data[i].metas)):
            if data[i].metas[j] is None:
                d.append("")
            else:
                d.append(str(data[i].metas[j]))
        new_data.append(d)
    json_data = {'num_input': num_input, 'values': [feature_names + meta_names, feature_types+meta_types, new_data]}
    return json_data

def convert_json_implicite_to_data_table(json_data):
    if is_implicite(json_data) == 1:
        print("La data n'est pas au format implicite")
        return None
    attributes = []
    metas = []
    for item in json_data:
        for key, value in item.items():
            if isinstance(value, str):
                metas.append(key)
            elif isinstance(value, float) or isinstance(value, int):
                attributes.append(key)
        break
    domain_attributes = []
    domain_metas = []
    data_continous = []
    data_metas = []
    for item in json_data:
        d = []
        m = []
        for key, value in item.items():
            if key in metas:
                m.append(value)
            elif key in attributes:
                if value is None or isinstance(value, str):
                    d.append(None)
                else:
                    if hasattr(value, "value"):
                        value = value.value
                    if value is None or isinstance(value, int):
                        d.append(int(value))
                    elif value is None or isinstance(value, float):
                        d.append(float(value))
        data_continous.append(d)
        data_metas.append(m)
    for i in range(len(attributes)):
        domain_attributes.append(ContinuousVariable(attributes[i]))
    for i in range(len(metas)):
        domain_metas.append(StringVariable(metas[i]))
    domain = Domain(domain_attributes, metas=domain_metas)
    table = Table.from_numpy(domain, data_continous, metas=data_metas)
    return table


if __name__ == "__main__":
    #json_data = {'num_input': 0, 'values': [['col1', 'col2', 'col3'],['float', 'str', 'float'], [[3, 'test', 6], [4, 'oui', 5]]]} # explicite
    json_data =  [{'nom': 'Alice', 'age': 30}, {'nom': 'Bob', 'age': 25},  {'nom': 'Bob', 'age': 25}] # implicite
    #is_implicite_or_explicite(json_data)
    table = convert_json_implicite_to_data_table(json_data)
    print(table)
    #table = convert_json_to_orange_data_table(json_data)
    exit(0)
    data = Orange.data.Table("table_data.tab")
    print("data table entrée : ",data)
    json_ex = convert_data_table_to_json_explicite(data)
    print("json explicite : ",json_ex)


