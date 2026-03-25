import json
import time
import os

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import server_uvicorn, hlit_workflow_management
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert
else:
    from orangecontrib.AAIT.utils import MetManagement
    from orangecontrib.HLIT_dev.remote_server_smb import server_uvicorn, hlit_workflow_management
    from orangecontrib.HLIT_dev.remote_server_smb import convert

def reset_workflow(workflow_id:str=""):
    if workflow_id == "":
        chemin_dossier = MetManagement.get_api_local_folder()
    else:
        chemin_dossier = MetManagement.get_api_local_folder(workflow_id=workflow_id)
    # on purge bien touts les elements c est normal de ne pa mettre de workflow id ici
    if os.path.exists(chemin_dossier):
        MetManagement.reset_folder(chemin_dossier, recreate=False)
    # on purge bien touts les elements dans adm
    chemin_dossier_adm = MetManagement.get_api_local_folder_admin()
    if workflow_id == "":
        if os.path.exists(chemin_dossier_adm):
            MetManagement.reset_folder(chemin_dossier_adm, recreate=False)


def is_valid_json_response(response, data=None):
    if data is None:
        data = {}
    try:
        if response is None:
            return 1
        body = getattr(response, "body", None)
        if body is None:
            return 1
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="strict")
        elif not isinstance(body, str):
            return 1
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            return 1
        data.clear()
        data.update(parsed)
        return 0
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return 1

def expected_input_for_workflow(key_name: str, out_tab_input=[]) -> int:
    del out_tab_input[:]
    expected_input_output = server_uvicorn.get_worklow_expected_input_output(key_name)
    try:
        data = json.loads(expected_input_output.body.decode("utf-8"))
        out_tab_input.append(data["expected_input"][0])
        return 0
    except json.JSONDecodeError:
        return 1

def input_workflow(data_json):
    data_json = json.loads(data_json)
    result = server_uvicorn.receive_data(data_json)
    return result

def output_workflow(workflow_id):
    time.sleep(0.2)
    try:
        result = server_uvicorn.read_root(workflow_id)
    except Exception:
        time.sleep(0.2)
        return output_workflow(workflow_id)

    data = {}

    try:
        if is_valid_json_response(result, data) != 0:
            print("error reading json, retry")
            time.sleep(0.2)
            return output_workflow(workflow_id)
    except Exception:
        time.sleep(0.2)
        return output_workflow(workflow_id)

    if "_result" in data:
        return data
    else:
        time.sleep(0.2)
        return output_workflow(workflow_id)

def stream_workflow(workflow_id, progress_callback):
    full_text = ""
    chemin_dossier = MetManagement.get_api_local_folder(workflow_id=workflow_id)
    filepath = chemin_dossier + "chat_output.txt"
    if os.path.exists(filepath):
        os.remove(filepath)
    generator = hlit_workflow_management.stream_tokens_from_file(chemin_dossier)
    for token in generator:
        if token == "[DONE]":
            break
        progress_callback(("assistant", token))
        full_text += token
    return full_text

def expected_output_for_workflow(key_name: str, out_tab_output=[]) -> int:
    del out_tab_output[:]
    expected_input_output = server_uvicorn.get_worklow_expected_input_output(key_name)
    try:
        data = json.loads(expected_input_output.body.decode("utf-8"))
        out_tab_output.append(data["expected_output"][0])
        return 0
    except json.JSONDecodeError:
        return 1


def call_workflow_without_api(input_data=[], key_name: str="", out_tab_output=[]):
    del out_tab_output[:]
    #reset_all()
    all_config = server_uvicorn.read_config_file_ows_html()
    config = {}
    for item in all_config["message"]:
        if item["name"] == key_name:
            config = item
            break
    if not isinstance(input_data, dict) or "workflow_id" not in input_data:
        out_tab_input = []
        if 0 != expected_input_for_workflow(key_name, out_tab_input=out_tab_input):
            print("Erreur lors de l'appel de l'input")
            return 1
        if input_data != []:
            input_json = convert.convert_data_table_to_json_explicite(input_data, 0)
            input_json = {"workflow_id": out_tab_input[0]["workflow_id"], "data": [input_json], "timeout": config["timeout_daemon"]}
        else:
            input_json = {"workflow_id": out_tab_input[0]["workflow_id"], "data": out_tab_input[0]["data"],
                          "timeout": config["timeout_daemon"]}
    else:
        input_json = input_data
        input_json["timeout"] = config["timeout_daemon"]
    server_uvicorn.receive_data(input_json)
    server_uvicorn.start_workflow(key_name)
    time.sleep(10)
    while True:
        res = server_uvicorn.read_root(input_json["workflow_id"])
        data = {}
        if 0 != is_valid_json_response(res, data):
            print("error reading json")
            return 1
        if "_result" in data:
            if data["_result"] is not None:
                data_table = convert.convert_json_implicite_to_data_table(data["_result"])
                out_tab_output.append(data_table)
                break
        time.sleep(0.1)
    server_uvicorn.kill_process(key_name)
    return 0

if __name__ == "__main__":
    key_name = "export_md"
    out_tab_input = []
    if 0 != expected_input_for_workflow(key_name, out_tab_input=out_tab_input):
        print("Erreur lors de l'appel de l'input")
    out_tab_output = []
    if 0 != call_workflow_without_api(out_tab_input[0], key_name, out_tab_output=out_tab_output):
        print("Erreur lors de l'appel call workflow")