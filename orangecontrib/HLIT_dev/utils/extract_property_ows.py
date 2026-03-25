import xml.etree.ElementTree as ET
import ast




def extract_node_properties_by_name(ows_path, target_name):
    """🔍 Extraction des propriétés pour un seul type de widget."""
    return extract_node_properties_by_names(ows_path, [target_name])

def get_list_workflow_id_input_id_uuid(ows_path):
    # retrun a list
    #[[workflow_id,input_id,widget_input_uuid]] all in str
    data_list=extract_property_for_hlit(ows_path)
    if data_list==None:
        return None
    try:
        if not isinstance(data_list, list):
            return None

        result = []
        for node in data_list:
            if not isinstance(node, dict):
                continue
            if node.get("node_name") == "Input Interface":
                workflow_id = node.get("workflow_id")
                input_id = node.get("input_id")
                if workflow_id is None or input_id is None:
                    continue
                # si None on donne la valeur ""
                widget_input_uuid = node.get("widget_input_uuid") or ""
                result.append([workflow_id, input_id, widget_input_uuid])

        return result

    except Exception as e:
        print(e)
        return None

def decode_properties(prop_text):
    # attention dans certain cas on lit un json et pas un literral,je fais en sorte de ne pas tomber dans ce cas mais nous ne sommes pas robuste!!
    # if prop_text[0]=="{" and prop_text[-1]=="}":
    try:
        return ast.literal_eval(prop_text)
    except Exception as e:
        print(f"error of text parsing : {e}")
        return None
    # else:
    #     try:
    #         decoded = base64.b64decode(prop_text)
    #         obj = pickle.loads(decoded)
    #         return obj
    #     except Exception as e:
    #         print(f"❌ Erreur de désérialisation pickle : {e}")
    #         return None

def extract_node_properties_by_names(ows_path, target_names):
    """🔍 Extraction des propriétés pour plusieurs types de widgets."""
    #print(f"🔍 Lecture du fichier OWS : {ows_path}")
    tree = ET.parse(ows_path)
    root = tree.getroot()

    # Créer un mapping node_id -> name
    #print("📦 Construction du mapping node_id -> node_name...")
    node_id_to_name = {
        node.attrib['id']: node.attrib.get('name', '')
        for node in root.find('nodes')
        if node.tag == 'node'
    }
    #print(node_id_to_name)
    #print(f"✅ {len(node_id_to_name)} nœuds détectés dans la section <nodes>.")

    results = []
    found = 0

    #print(f"\n🔎 Recherche des propriétés pour les widgets : {target_names}")
    for prop in root.find('node_properties'):
        node_id = prop.attrib['node_id']
        node_name = node_id_to_name.get(node_id, '')
        if node_name in target_names:
            found += 1
            prop_text = prop.text.strip()
            #print(f"\n📍 Propriétés trouvées pour node_id={node_id} ({node_name})")
            try:
                parsed_dict = decode_properties(prop_text)#ast.literal_eval(prop_text)
                if parsed_dict is None:
                    return None
                results.append({
                    "node_id": node_id,
                    "node_name": node_name,
                    "properties": parsed_dict
                })
                #print(f"✅ Contenu extrait (clé(s) : {list(parsed_dict.keys())}):\n{parsed_dict}")
            except Exception as e:
                print(f"❌ Erreur de parsing pour node_id={node_id}: {e}")
                print(f"Texte brut:\n{prop_text}")
                return None

    #print(f"\n🎯 Total de nœuds correspondants : {found}")
    return results



def extract_property_for_hlit(ows_path):
    results=extract_node_properties_by_names(ows_path,["Input Interface","Output Interface"])
    if results is None:
        return None
    if len(results)==0:
        return None
    """
        Extrait les 'Input Interface' et 'Output Interface' dans l'ordre,
        et formate un JSON plat (liste de dictionnaires) avec les champs utiles.

        Args:
            results (list): Liste de nœuds du workflow (type list[dict])

        Returns:
            list or None: Liste ordonnée de dictionnaires JSON, ou None en cas d'erreur.
        """
    try:
        processed = []

        for node in results:
            if not isinstance(node, dict):
                continue  # sécurité : on ignore les objets non conformes

            node_name = node.get("node_name")
            props = node.get("properties", {})

            if node_name == "Input Interface":
                processed.append({
                    "node_name": node_name,
                    "workflow_id": props.get("workflow_id"),
                    "input_id": props.get("input_id"),
                    "help_description": props.get("help_description"),
                    "widget_input_uuid": props.get("widget_input_uuid"),# null if dosn t existe
                    "expected_input": props.get("expected_input")
                })

        for node in results:
            if not isinstance(node, dict):
                continue

            node_name = node.get("node_name")
            props = node.get("properties", {})

            if node_name == "Output Interface":
                processed.append({
                    "node_name": node_name,
                    "workflow_id": props.get("workflow_id"),
                    "help_description": props.get("help_description"),
                    "expected_output": props.get("expected_output")
                })

        return processed

    except Exception as e:
        print(f"[ERREUR] Impossible de traiter les nœuds : {e}")
        return None

def get_workflow_input_output_from_ows_file(ows_path):
    results=extract_property_for_hlit(ows_path)
    input_workflow_id = []
    output_workflow_id = []
    for i in range(len(results)):
        if results[i]["node_name"] == "Input Interface" and results[i]["workflow_id"] not in input_workflow_id:
            input_workflow_id.append(results[i]["workflow_id"])
        if results[i]["node_name"] == "Output Interface":
            output_workflow_id.append(results[i]["workflow_id"])
    input_data = []
    for i in range(len(input_workflow_id)):
        data = []

        for j in range(len(results)):
            if results[j]["node_name"] == "Input Interface" and results[j]["workflow_id"] == input_workflow_id[i]:
                if isinstance(results[j]["expected_input"], dict):
                    data.append(results[j]["expected_input"].get("data", [""])[0])
                    #data.append(results[j]["expected_input"].get("data", [""])[0])# case no data input add ""
                else:
                    data.append("")
        input_data.append({"workflow_id": input_workflow_id[i], "data": data})
    output_data = []
    for i in range(len(output_workflow_id)):
        data = []
        for j in range(len(results)):
            if results[j]["node_name"] == "Output Interface" and results[j]["workflow_id"] == output_workflow_id[i]:
                data = results[j]["expected_output"]
        output_data.append({"workflow_id": output_workflow_id[i], "data": data})
    return {"expected_input": input_data, "expected_output": output_data}


# Exemple d'utilisation
if __name__ == "__main__":
    #file = r"C:\test_bug_orange\aait_store\workloawfs_test1\ows\chatbot_1_mini.ows"
    # Pour un seul widget
    file = "C:/Users/max83/Desktop/Orange_4All_AAIT/Orange_4All_AAIT/aait_store/untitled.ows"
