import sys
import json
import os
import psutil
import time
import subprocess
import shutil
import re

from pathlib import Path
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement,subprocess_management
    from Orange.widgets.orangecontrib.HLIT_dev.utils import extract_property_ows
else:
    from orangecontrib.AAIT.utils import MetManagement,subprocess_management
    from orangecontrib.HLIT_dev.utils import extract_property_ows

def to_bool(value):
    """Convertit diverses représentations en booléen."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ["true", "1", "yes"]
    if isinstance(value, int):
        return value != 0
    return True  # Valeur par défaut si inconnue

def load_json_and_check_json_agregate(fichier_json, montab=[]):
    try:
        with open(fichier_json, 'r', encoding='utf-8') as file:
            data = json.load(file)

        required_fields = {"name", "ows_file", "html_file", "description"}

        for item in data:
            if not required_fields.issubset(item.keys()):
                return 1  # Erreur si un champ requis manque

            # Traitement des champs optionnels
            item["with_gui"] = to_bool(item.get("with_gui", True))
            item["with_terminal"] = to_bool(item.get("with_terminal", True))
            item["daemonizable"] = to_bool(item.get("daemonizable", False))
            item["timeout_daemon"] = item.get("timeout_daemon", 1000000)
            item["fichier_json"] = str(fichier_json).split("\\")[-1]
            montab.append(item)

        return 0  # Tout est bon

    except (json.JSONDecodeError, FileNotFoundError, IOError) as e:
        print(f"Erreur: {e}")
        return 1

def read_config_ows_html_file_as_dict(out_put_tab=[]):
    del out_put_tab[:]
    folder_path = Path(MetManagement.get_path_linkHTMLWorkflow())
    le_tab=[]
    for file_path in folder_path.glob('*.json'):
        if 0!=load_json_and_check_json_agregate(file_path,le_tab):
            print("error reading ",file_path)
            return 1
    if len(le_tab)==0:
        print("error no json loaded from", folder_path)
        return 1
    # crate absolute path
    for idx,_ in enumerate(le_tab):
        le_tab[idx]['html_file']=MetManagement.TransfromStorePathToPath(le_tab[idx]['html_file'])
        le_tab[idx]['ows_file']=MetManagement.TransfromStorePathToPath(le_tab[idx]['ows_file'])

    # on verifie que l on a pas deux fois le meme nom
    seen_names = set()
    for item in le_tab:
        if item["name"] in seen_names:
            print("error in json several use of :"+str(item["name"]))
            return 1
        seen_names.add(item["name"])
    for element in le_tab:
        out_put_tab.append(element)
    return 0

def open_local_html(list_config_html_ows,name):
    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    a_lancer=""
    try:
        for element in list_config_html_ows:
            print(element)
            if element["name"]==name:
                print(os.name)
                if os.name == "posix":
                    a_lancer=f'file://{element["html_file"]}'
                    print(a_lancer)
                else:
                    a_lancer='"'+edge_path+'" "'+element['html_file']+'"'


    except Exception as e:
        print(e)
        return 1
    if a_lancer=="":
        print("aucun html trouvé")
        return 1
    if os.name == "posix":
        import webbrowser
        webbrowser.open(a_lancer)
        print("Gérer les exceptions correctement sur Mac ici!!!!")
        return 0
    else:
        result,PID=subprocess_management.execute_command(a_lancer,hidden=True)
    return result


def is_process_running(pid):
    return psutil.pid_exists(pid)

def get_process_name(pid):
    try:
        p = psutil.Process(pid)
        return p.name()
    except psutil.NoSuchProcess:
        return None

def write_PID_to_file(name: str, number: int,extention="txt") -> int:
    """
    Writes an integer to a file named "name.txt" inside a folder named "name".
    Handles exceptions related to file operations.
    Returns 0 if successful, 1 if an error occurs.
    """
    try:
        # Create directory if it does not exist

        dirname=MetManagement.get_api_local_folder_admin()
        os.makedirs(dirname, exist_ok=True)
        # Define file path
        file_path = os.path.join(dirname, f"{name}.{extention}")

        # Write the integer to the file
        with open(file_path, 'w') as file:
            file.write(str(number))

        return 0  # Success
    except Exception as e:
        print(f"Error: {e}")
        return 1  # Error

def is_defunct_or_not_used_only_posix(pid: int) -> bool:
    if os.name !="posix":
        return False
    try:
        # Appel de ps pour obtenir l'état du processus
        result = subprocess.run(
            ['ps', '-o', 'stat=', '-p', str(pid)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True
        )
        state = result.stdout.strip()
        if not state:
            print(f"PID {pid} not found.")
            return True
        if 'Z' in state:
            print(f"PID {pid} is defunct (zombie).")
            return True
        else:
            print(f"PID {pid} is not defunct.")
            return False
    except Exception as e:
        print(f"Error checking PID {pid}: {e}")
        return False


def check_file_and_process(name: str,extention="txt") -> int:
    """
    Checks if "name.extention" exists in the "name" directory.
    If it exists, reads its content as an integer.
    If a process with that integer as PID exists, returns 2.
    If not, deletes the file and returns the integer.
    If the file does not exist return 0
    If an error occurs, returns 1.
    """

    try:
        dirname=MetManagement.get_api_local_folder_admin()
        # Define file path
        file_path = os.path.join(dirname, f"{name}.{extention}")

        # Check if file exists
        if not os.path.isfile(file_path):
            return 0
        # Read the integer from the file
        with open(file_path, 'r') as file:
            content = file.read().strip()

        if not content.isdigit():
            return 1

        process_id = int(content)
        # processus zombie de mac
        if is_defunct_or_not_used_only_posix(process_id):
            os.remove(file_path)
            return 0
        # Check if a process with this PID exists
        if process_id in [p.pid for p in psutil.process_iter()]:
            print("process deja en existant")
            return 2

        # If no such process exists, delete the file
        os.remove(file_path)

        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def start_workflow(list_config_html_ows,name):
    """Launch a workflow using the command line and store the process information.
    retun 1 -> erro
    return 0 ->> ok
    retrun 2 -> workflow alrwready used"""
    workflow_path=""
    with_terminal = True
    gui = True
    try:
        for element in list_config_html_ows:
            if element["name"]==name:
                workflow_path=element['ows_file']
                with_terminal=element['with_terminal']
                gui=element['with_gui']

    except Exception as e:
        print(e)
        return 1
    if workflow_path=="":
        print("no ows file found in json config")
        return 1
    if not os.path.isfile(workflow_path):
        print(workflow_path+" doesn t existe")
        return 1
    # est ce que le workflow est deja ouvert?
    res=check_file_and_process(name,"txt")
    if res==1:
        return 1
    if res==2:
        return 2



    # create lock file to wait orange finished loading
    liste_a_lock=extract_property_ows.get_list_workflow_id_input_id_uuid(workflow_path)
    if liste_a_lock is None:
        return 1
    folder_path = MetManagement.get_api_local_folder_admin_locker()
    os.makedirs(folder_path, exist_ok=True)
    # creation du fichier de lock
    #folder_path/uuid.lk
    for element in liste_a_lock:
        if str(element[2])=="":
            continue
        file_to_write = folder_path + "/" + str(element[2]) + ".lk"
        try:
            with open(file_to_write, "w", encoding="utf-8"):
                pass
        except Exception as e:
            print(e)
            return 1
    # creation des dossier pour faire le lien avec le workflow id
    #folder_path/workflow_id/inpid_id/uuid.info et dans uuid.info il y a la valeur de uuid.lk
    for element in liste_a_lock:
        if str(element[2])=="":
            continue
        wor_id=str(element[0])
        if len(wor_id) > 4:
            wor_id=wor_id[:-4]
            wor_id+"/"
        if len(wor_id)==0:
            continue
        os.makedirs(folder_path+"/"+wor_id, exist_ok=True)
        os.makedirs(folder_path + "/" + wor_id+"/"+str(element[1]), exist_ok=True)
        try:
            with open(folder_path + "/" + wor_id+"/"+str(element[1])+"/uuid.info", "w", encoding="utf-8") as f:
                f.write(str(element[2]) + ".lk")
        except Exception as e:
            print(f"Erreur lors de l'écriture dans le fichier : {e}")
            return 1

    workflow_directory=Path(os.path.dirname(workflow_path))
    # clean file to aviod erreor
    for file in workflow_directory.glob("*.ows.swp.*"):
        file.unlink()
    env = dict(os.environ)
    if not gui:
        if sys.platform.startswith("Darwin") or sys.platform.startswith("darwin"):
            # Sur Mac, offscreen peut poser problème si pas dans une session graphique
            # Donc on peut soit afficher un warning soit ne pas forcer offscreen
            print("Attention: 'offscreen' forcé sur Mac peut être instable.")
        else:
            env['QT_QPA_PLATFORM'] = 'offscreen'
    # 2. Construct the command to run the workflow
    python_path = Path(sys.executable)
    workflow_path=str(workflow_path)
    if os.name == "nt":
        workflow_path=workflow_path.replace('/','\\')
    str_python_path=str(python_path)
    str_python_path=f'{str_python_path}'
    str_workflow_path = f'{workflow_path}'
    command = [
        str_python_path,
        "-m",
        "Orange.canvas",
        str_workflow_path
    ]
    print(command)

    PID=None
    try:
        if with_terminal:
            PID = subprocess_management.open_terminal(command, with_qt=gui, env=env)
        else:
            PID = subprocess_management.open_hide_terminal(command, with_qt=gui, env=env)
    except Exception as e:
        print(e)
        return 1

    return write_PID_to_file(name,PID,"txt")


def start_daemon(list_config_html_ows,name):
    """Launch a workflow using the command line and store the process information.
    retun 1 -> erro
    return 0 ->> ok
    retrun 2 -> workflow alrwready used
    return 3 -> daemon already used
    return 4 -> workflow not daemonizable"""
    workflow_path=""
    daemonizable=False
    with_terminal_daemon = True
    try:
        for element in list_config_html_ows:
            if element["name"]==name:
                workflow_path=element['ows_file']
                daemonizable = element['daemonizable']
    except Exception as e:
        print(e)
        return 1
    if not daemonizable:
        print("workflow not daemonizable")
        return 4
    if workflow_path=="":
        print("no ows file found in json config")
        return 1
    if not os.path.isfile(workflow_path):
        print(workflow_path+" doesn t existe")
        return 1
    # est ce que le workflow est deja ouvert?
    res=check_file_and_process(name,"txt")
    if res==1:
        return 1
    if res==2:
        return 2
    # est ce que le demon est deja ouvert?
    res=check_file_and_process(name,"dmn")
    if res==1:
        return 1
    if res==2:
        return 3

    env = dict(os.environ)
    # 2. Construct the command to run the workflow
    python_path = Path(sys.executable)
    workflow_path=str(workflow_path)
    if os.name == "nt":
        workflow_path=workflow_path.replace('/','\\')



    command = [str(python_path) ,
               ' print("coucou")']
    PID=None
    try:
        if with_terminal_daemon:
            PID = subprocess_management.open_terminal(command, env=env)
        else:
            PID = subprocess_management.open_hide_terminal(command, env=env)
    except Exception as e:
        print(e)
        return 1

    return write_PID_to_file(name,PID,"dmn")



def check_if_timout_is_reached(chemin_dossier):
    if os.path.exists(chemin_dossier + "config.json"):
        with open(chemin_dossier + "config.json", "r", encoding="utf-8") as file:
            config_json = json.load(file)
        timeout = config_json["timeout"]
        if os.path.exists(chemin_dossier + "time.txt"):
            second_file = MetManagement.read_file_time(chemin_dossier + "time.txt")
            second_now = MetManagement.get_second_from_1970()
            second_since_workflow_launch = second_now - second_file
            if second_since_workflow_launch > timeout:
                MetManagement.reset_folder(chemin_dossier, recreate=False)
                return 1
    return 0

def stream_tokens_from_file(chemin_dossier: str, timeout: float = 5.0):
    filepath = chemin_dossier + "chat_output.txt"
    while not os.path.exists(filepath):
        time.sleep(0.01)
        if 1== check_if_timout_is_reached(chemin_dossier):
            print("timeout reached")
            return

    last_position = 0
    last_activity = time.time()
    buffer = ""

    while True:
        with open(filepath, 'r', encoding='utf-8') as f:
            f.seek(last_position)
            chunk = f.read()
            if chunk:
                buffer += chunk
                last_position = f.tell()
                last_activity = time.time()

                # On attend un espace ou une ponctuation avant d'envoyer
                while True:
                    # Chercher un point de coupure sûr
                    match = None
                    for i in range(len(buffer)-1, -1, -1):
                        if buffer[i] in " \n.,;!?":
                            match = i + 1
                            break

                    if match:
                        to_send = buffer[:match]
                        buffer = buffer[match:]
                        yield f"{to_send}"
                    else:
                        break
            else:
                time.sleep(0.05)

        if time.time() - last_activity > timeout:
            if buffer.strip():
                yield f"{buffer}"
            yield "[DONE]"
            break
    MetManagement.write_file_time(chemin_dossier + "time.txt")


def kill_process(file, type="cmd.exe"):
    if not os.path.exists(file):
        print("your file does not exist")
        return "your file does not exist"
    with open(file,"r") as f:
        pid = f.read()
    pid = int(pid)
    if not is_process_running(pid):
        print("process not running")
        return "process not running"
    name = get_process_name(pid)
    if os.name =="posix":
        subprocess_management.kill_process_tree(pid)
        return "Process kill"
    if name == type:
        subprocess_management.kill_process_tree(pid)
    else:
        print("process type unexpected")
    time.sleep(1) # not necessayr?
    # kill process take time -> bug
    # if psutil.pid_exists(pid):
    #     p = psutil.Process(pid)
    #     print(f"Nom: {p.name()}")
    #     print(f"Status: {p.status()}")
    #     print(f"Executable: {p.exe()}")
    #     print(f"Parent PID: {p.ppid()}")
    # else:
    #     print("Le processus n'existe pas.")
    return "Process kill"

def workflow_id_is_loaded(workflow_id,list_input_id):
    # return 0 if w id loaded
    # return 1 f nok
    # return 2 if error
    wor_id=workflow_id
    folder_path = MetManagement.get_api_local_folder_admin_locker()
    if len(wor_id) > 4:
        wor_id = wor_id[:-4]
        wor_id + "/"
    dir_to_delete=[]
    for element in list_input_id:
        file_to_check=folder_path+"/"+wor_id+"/"+str(element)+"/uuid.info"
        path_to_check=""
        dir_to_delete.append(folder_path+"/"+wor_id+"/"+str(element))
        if not os.path.exists(file_to_check):
            continue
        try:
            with open(file_to_check, "r", encoding="utf-8") as fichier:
                path_to_read = fichier.readline().strip()
        except Exception as e:
            print(e)
            return 2
        path_to_check=folder_path+"/"+path_to_read
        if os.path.exists(path_to_check):
            return 1
    for element in dir_to_delete:
        MetManagement.reset_folder(element, recreate=False)
    return 0

def lire_config_serveur(chemin_fichier):
    # renvoie le contenu de json à mettre dans le dossier aait_store\keys\SERVEUR_CONFIG
    # json de la forme:
    # {
    #     "api_keys": ["ma_clef_api_super_secrete"],
    #     "secured_paths": ["/kill-all"],
    #     "auth_required": true #false si pas de auth required
    # }
    try:
        folder_path = MetManagement.get_secret_content_dir()
        chemin_fichier = folder_path+ "SERVEUR_CONFIG/" +chemin_fichier
        # Lecture du fichier JSON
        with open(chemin_fichier, "r", encoding="utf-8") as f:
            contenu = json.load(f)
        return contenu
    except Exception as e:
        print(e)
        return None

def purge_worklow_input_id_list_from_keyname(key_name):
    # 0 ok
    # 1 error
    # put results in workflow_input_id_list
    json_result=""
    workflow_input_id_list=[]
    list_config_html_ows = []
    if 0 != read_config_ows_html_file_as_dict(list_config_html_ows):
        return 1
    workflow_path=""
    try:
        for element in list_config_html_ows:
            if element["name"]==key_name:
                workflow_path=element['ows_file']
    except Exception as e:
        print(e)
        return 1
    if workflow_path=="":
        return 1

    try:
        print(f"workflow_path : {workflow_path}")
        # Simule ici une extraction typique (à adapter selon ton contexte réel)
        json_result = extract_property_ows.extract_property_for_hlit(workflow_path)


        if json_result is None:
            return 1
        if json_result=="":
            return 1
    except Exception as e:
        print(f"error {e}")
        return 1

    for element in json_result:
        try :
            workflow_input_id_list.append(element['workflow_id'])
        except Exception as e:
            print(f"error {e}")
            return 1
    if len(workflow_input_id_list)==0:
        print("no workflow id in your file !!")
        return 1
    for element in workflow_input_id_list:
        dir_to_delete=MetManagement.get_api_local_folder(element)
        MetManagement.reset_folder(dir_to_delete,recreate=False)
    return 0


def sauvegarder_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def dupplicate_linkHTMLWorkflow(data, id):
    linkHTMLWorkflow = MetManagement.get_path_linkHTMLWorkflow()
    new_linkHTMLWorkflow = linkHTMLWorkflow + "temp_" + str(id) + ".json"
    if not os.path.exists(new_linkHTMLWorkflow):
        sauvegarder_json(new_linkHTMLWorkflow, data)
    else:
        time.sleep(0.1)
        id = MetManagement.get_second_from_1970()
        dupplicate_linkHTMLWorkflow(data, id)
    return

def dupplicate_workflow(data, id=None):
    print(id)
    aait_store_path = MetManagement.get_local_store_path()
    if id is None:
        id = MetManagement.get_second_from_1970()
    path = data[0]["ows_file"]
    new_path = path
    if len(path)>4:
        if path[-4:]==".ows":
            new_path=path[:-4]
    new_workflow = new_path + "_temp_" + str(id) + ".ows"
    data[0]["name"] = data[0]["name"] + "_temp_" + str(id)
    data[0]["ows_file"] = new_workflow
    if aait_store_path not in new_workflow:
        new_workflow = aait_store_path + new_workflow
        path = aait_store_path + path
    if os.path.exists(new_workflow):
        print("Workflow already exist")
        return
    shutil.copyfile(path, new_workflow)
    dupplicate_linkHTMLWorkflow(data, str(id))
    if 0 != change_workflow_id(new_workflow, id):
        print("Error while changing the workflow ID")
        return
    return data[0]["name"], id

def delete_temp(id):
    aait_store_path = MetManagement.get_local_store_path()
    linkHTMLWorkflow = MetManagement.get_path_linkHTMLWorkflow()
    new_linkHTMLWorkflow = linkHTMLWorkflow + "temp_" + str(id) + ".json"
    if os.path.exists(new_linkHTMLWorkflow):
        with open(new_linkHTMLWorkflow, "r", encoding="utf-8") as f:
            data = json.load(f)
        ows_file = data[0]["ows_file"]
        if aait_store_path not in ows_file:
            ows_file = aait_store_path + ows_file
        if os.path.exists(ows_file):
            os.remove(ows_file)
        os.remove(new_linkHTMLWorkflow)
        return 0
    else:
        return 1

def change_workflow_id(fichier, time):
    with open(fichier, "r", encoding="cp1252") as f:
        contenu = f.read()
    contenu = re.sub(r"[^\x20-\x7E]", "", contenu)
    pattern = r"('workflow_id'\s*:\s*')([^']*)(')"

    def remplacer(match):
        valeur = match.group(2)
        return match.group(1) + valeur + "_" + str(time) + match.group(3)

    contenu_modifie = re.sub(pattern, remplacer, contenu)

    with open(fichier, "w", encoding="utf-8") as f:
        f.write(contenu_modifie)
    return 0

if __name__ == "__main__":
    workflow_input_id_list = []
    key_name="nom simpathique2"
    print(workflow_input_id_list)