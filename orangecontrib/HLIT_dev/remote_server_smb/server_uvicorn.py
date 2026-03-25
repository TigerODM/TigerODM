import uvicorn
import time
from fastapi import FastAPI, Depends, HTTPException, Security, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import os
import json
import socket
import signal
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from fastapi.security.api_key import APIKeyHeader
from fastapi.routing import compile_path
from typing import Optional
import argparse
import platform
import subprocess
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert, hlit_workflow_management
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
    from Orange.widgets.orangecontrib.HLIT_dev.utils import extract_property_ows
else:
    from orangecontrib.HLIT_dev.remote_server_smb import convert, hlit_workflow_management
    from orangecontrib.AAIT.utils import MetManagement
    from orangecontrib.HLIT_dev.utils import extract_property_ows

app = FastAPI(docs_url=None)
# app = FastAPI() # call external ressource for the swagger
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change "*" par une liste de domaines autorisés si besoin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY_NAME = "HLIT-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
API_KEYS = set()
SECURED_PATHS = set()

def is_auth_enabled() -> bool:
    return os.getenv("REQUIRE_AUTH", "true").lower() == "true"

# obligatoire de regarder les routes composées par exemple de /{key_name}
def matches_secured_path(request_path: str, secured_paths: list[str]) -> bool:
    for secured_path in secured_paths:
        try:
            regex = compile_path(secured_path)[0]
            if regex.match(request_path):
                return True
        except Exception as e:
            print("Erreur compile_path:", e)
            continue
    return False


def get_api_key(request: Request, api_key: str = Security(api_key_header)):
    if is_auth_enabled() and (api_key not in API_KEYS or api_key is None):
        if request.url.path in SECURED_PATHS or matches_secured_path(request.url.path, SECURED_PATHS) or SECURED_PATHS == "*" or SECURED_PATHS == []:
            raise HTTPException(status_code=403, detail="Clé API invalide")
    return api_key

# === Swagger UI personnalisé ===
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title="HLIT API",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
        swagger_favicon_url="/static/favicon.png",
    )

# Fichiers Swagger statiques
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "swagger")),
    name="static"
)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="HLIT API",
        version="1.0",
        description="API HLIT",
        routes=app.routes,
    )

    if is_auth_enabled():
        # Ajout du header X-API-Key seulement si auth activée
        openapi_schema["components"]["securitySchemes"] = {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": API_KEY_NAME
            }
        }
        #Securisation des routes uniquement sur celle configurées si définis
        # Ajoute le cadenas
        for path_name, path in openapi_schema["paths"].items():
            if SECURED_PATHS != [] or SECURED_PATHS == "*":
                if path_name in SECURED_PATHS or SECURED_PATHS == "*":
                    for method in path.values():
                        method["security"] = [{"ApiKeyAuth": []}]
                else:
                    for method in path.values():
                        method.pop("security", None)
            else:
                for method in path.values():
                    method["security"] = [{"ApiKeyAuth": []}]
    else:
        # Supprime tout ce qui concerne la sécurité
        if "securitySchemes" in openapi_schema.get("components", {}):
            del openapi_schema["components"]["securitySchemes"]
        for path in openapi_schema["paths"].values():
            for method in path.values():
                method.pop("security", None)

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

class InputWorkflowJson(BaseModel):
    workflow_id: str = Field(..., json_schema_extra={"example":"toto.ows"})
    timeout: int = Field(default=100000000, json_schema_extra={"example": 60})
    data: list = Field(..., json_schema_extra={
        "example": [{
            "num_input": 0,
            "values": [["col1", "col2"], ["float", "str"], [[3, "test"], [3, "test"]]]
        }]
    })


def check_if_uvicorn_is_running():
    port = 8000
    # Verification of port
    if est_port_occupe(port):
        print(f"Le port {port} est déjà utilisé par un autre workflow.")
        return
    else:
        # Start server
        launch_uvicorn()

def est_port_occupe(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0  # Retourne True si le port est occupé


def is_port_in_use(host, port, timeout=1):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            return s.connect_ex((host, port)) == 0
        except Exception:
            return False

def launch_uvicorn():
    if is_port_in_use(host="127.0.0.1", port=8000):
        print("port already used")
        return
    chemin_dossier =MetManagement.get_api_local_folder()
    # on purge bien touts les elements c est normal de ne pa mettre de workflow id ici
    if os.path.exists(chemin_dossier):
        MetManagement.reset_folder(chemin_dossier, recreate=False)
    # on purge bien touts les elements dans adm
    chemin_dossier_adm = MetManagement.get_api_local_folder_admin()
    if os.path.exists(chemin_dossier_adm):
        MetManagement.reset_folder(chemin_dossier_adm, recreate=False)
    uvicorn.run(app, host="127.0.0.1", port=8000)

@app.get("/read-config-file-ows-html", summary="Récupération du fichier de configuration", description="L'appel a cette route permet la récupération des informations nécéssaires afin de configurer la connexion front-end du ou des workflows avec comme paramètre le workflow id, la description, le timeout ... \n\nLe chemin vers le dossier de configuration est "+MetManagement.get_path_linkHTMLWorkflow())
def read_config_file_ows_html(api_key: str = Depends(get_api_key)):
    list_config_html_ows=[]
    if 0!= hlit_workflow_management.read_config_ows_html_file_as_dict(list_config_html_ows):
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs"}
        )
    return {"message" : list_config_html_ows}

@app.get("/open-local-html/{key_name}", summary="Lancement d'un html", description="L'appel a cette route permet de lancer un html local en passant comme paramètre le 'key_name' correspondant au process")
def open_local_html(key_name, api_key: str = Depends(get_api_key)):
    list_config_html_ows = []
    if 0!= hlit_workflow_management.read_config_ows_html_file_as_dict(list_config_html_ows):
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs"}
        )
    if 0!= hlit_workflow_management.open_local_html(list_config_html_ows, key_name):
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs to open local html"}
        )
    return {"message" : "Open local html ok"}


@app.get("/get-worklow-id-list/{key_name}", summary="Workflow information", description="L'appel a cette route permet de récupérer les inputs et outputs nécéssaires au fonctionnement du process correspond au 'key_name' passé en paramètre.")
def get_worklow_id_list(key_name, api_key: str = Depends(get_api_key)):
    list_config_html_ows = []
    if 0 != hlit_workflow_management.read_config_ows_html_file_as_dict(list_config_html_ows):
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs to get json aait store file"}
        )
    workflow_path=""
    try:
        for element in list_config_html_ows:
            if element["name"]==key_name:
                workflow_path=element['ows_file']
    except Exception as e:
        print(e)
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs when I read ows file path"}
        )
    if workflow_path=="":
        return JSONResponse(
            status_code=404,
            content={"message": "workflow path not found"}
        )

    try:
        print(f"workflow_path : {workflow_path}")
        # Simule ici une extraction typique (à adapter selon ton contexte réel)
        json_result = extract_property_ows.extract_property_for_hlit(workflow_path)


        if json_result is None:
            return JSONResponse(
                status_code=500,
                content={"error": "error nodes reading"}
            )

        return JSONResponse(
            status_code=200,
            content=json_result
        )

    except Exception as e:
        print(f"[API ERROR] : {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Servor error"}
        )

@app.get("/get-worklow-expected-input-output/{key_name}", summary="Workflow input output", description="L'appel a cette route permet de récupérer les inputs et outputs nécéssaires au fonctionnement du process correspond au 'key_name' passé en paramètre.")
def get_worklow_expected_input_output(key_name, api_key: str = Depends(get_api_key)):
    list_config_html_ows = []
    if 0 != hlit_workflow_management.read_config_ows_html_file_as_dict(list_config_html_ows):
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs to get json aait store file"}
        )
    workflow_path=""
    try:
        for element in list_config_html_ows:
            if element["name"]==key_name:
                workflow_path=element['ows_file']
    except Exception as e:
        print(e)
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs when I read ows file path"}
        )
    if workflow_path=="":
        return JSONResponse(
            status_code=404,
            content={"message": "workflow path not found"}
        )

    try:
        print(f"workflow_path : {workflow_path}")
        # Simule ici une extraction typique (à adapter selon ton contexte réel)
        json_result = extract_property_ows.get_workflow_input_output_from_ows_file(workflow_path)


        if json_result is None:
            return JSONResponse(
                status_code=500,
                content={"error": "error nodes reading"}
            )

        return JSONResponse(
            status_code=200,
            content=json_result
        )

    except Exception as e:
        print(f"[API ERROR] : {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "Servor error"}
        )

@app.get("/start-workflow/{key_name}", summary="Lance un workflow", description="Cette route permet de lancer le workflow correspondant au 'key_name' passé en paramètre.")
def start_workflow(key_name, api_key: str = Depends(get_api_key)):
    list_config_html_ows = []
    if 0!= hlit_workflow_management.read_config_ows_html_file_as_dict(list_config_html_ows):
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs to get json aait store file"}
        )
    res= hlit_workflow_management.start_workflow(list_config_html_ows, key_name)
    if res==1:
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs to start workflow"}
        )
    if res == 2:
        return JSONResponse(
            status_code=404,
            content={"message": "workflow is already running"}
        )
    return {"_message" : "Start workflow ok", "_statut": "Started", "_result": None}

@app.get("/start-daemon/{key_name}",include_in_schema=False, summary="Lance un daemon", description="Cette route permet de lancer le daemon correspondant au 'key_name' passé en paramètre. Pour kill le dameon 'key_name' devient key_name_D par exemple /start-daemon/{toto} peut etre arreter utiliser par process")
def start_daemon(key_name, api_key: str = Depends(get_api_key)):
    list_config_html_ows = []
    if 0 != hlit_workflow_management.read_config_ows_html_file_as_dict(list_config_html_ows):
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs to get json aait store file"}
        )


    res = hlit_workflow_management.start_daemon(list_config_html_ows, key_name)
    print(res)


@app.get("/reset-data-folder-workflow", summary="Suppression du dossier API", description="On appelle cette route pour supprimer le dossier 'exchangeApi' présent dans l'IA store et ainsi réinitialiser les données pour relancer le process. Nota si la route /chat est appelé et que le stream n'est pas terminé il ne sera pas possible de reset le dossier")
def reset_data_folder_workflow(api_key: str = Depends(get_api_key)):
    chemin_dossier = MetManagement.get_api_local_folder()
    if os.path.exists(chemin_dossier):
        MetManagement.reset_folder(chemin_dossier, recreate=False)
        return {"message": "Reset data folder workflow ok"}
    else:
        return {"message": "Error no folder found"}

@app.post("/input-workflow", summary="Envoie de donner au process", description="On appelle cette route pour initialiser le process. Lorsqu'elle est appelée le process commence son exécution. Il n'est pas possible de rappeler cette route pour relancer le même process tant que celui ci n'est pas terminé. Pour le rappeler alors qu'il n'a pas fini il faut utiliser la route /reset-data-folder-workflow et ensuite rappeler cette route pour exécuter de nouveau le process. Si le timeout n est pas definit il sera de base de 3,1 ans.")
def receive_data(input_data: InputWorkflowJson, api_key: str = Depends(get_api_key)):
    input_data = input_data.model_dump() if hasattr(input_data, "model_dump") else input_data
    chemin_dossier =""
    data_config = []
    # check if ODM finidhed to load
    if input_data["workflow_id"] is None:
        return JSONResponse(
            status_code=404,
            content={"_message": "The input data is not at good format"}
        )
    if input_data["data"] is None:
        return JSONResponse(
            status_code=404,
            content={"_message": "The input data is not at good format"}
        )
    liste_input_num_input=[]
    for data in input_data["data"] :
        if data["num_input"] is None:
            return JSONResponse(
                status_code=404,
                content={"_message": "The input data is not at good format"}
            )
        liste_input_num_input.append(data["num_input"])

    res=hlit_workflow_management.workflow_id_is_loaded(input_data["workflow_id"],liste_input_num_input)
    if res==2:
        return JSONResponse(
            status_code=404,
            content={"_message": "Internal Error"}
        )
    if res!=0:
        return JSONResponse(
            status_code=202,
            content={"_message": "The workflow is starting"}
        )

    chemin_dossier = MetManagement.get_api_local_folder(workflow_id=input_data["workflow_id"])
    if not os.path.exists(chemin_dossier):
        os.makedirs(chemin_dossier)
    else:
        print(f"Dossier '{chemin_dossier}' existe déjà.")
        return JSONResponse(
            status_code=202,
            content={"_message": "The workflow is already running"}
        )
    for key, data in enumerate(input_data["data"]):
        table = convert.convert_json_to_orange_data_table(data)
        if table == 1:
            MetManagement.reset_folder(chemin_dossier, recreate=False)
            return JSONResponse(
                status_code=404,
                content={"_message": "The input data table is not a dict"}
            )

        if table is None or table == []:
            MetManagement.reset_folder(chemin_dossier, recreate=False)
            return JSONResponse(
                status_code=404,
                content={"_message": "The input data table is empty"}
            )
        table.save(chemin_dossier + "input_data_" + str(data["num_input"]) + ".tab")
        data_config.append({"num_input": data["num_input"], "path": "input_data_" + str(data["num_input"]) + ".tab"})

    with open(chemin_dossier + "config.json", "w") as fichier:
        json.dump({"workflow_id": input_data["workflow_id"], "timeout": input_data["timeout"], "data_config": data_config}, fichier, indent=4)
    with open(chemin_dossier + ".ok", "w") as fichier:
        pass
    MetManagement.write_file_time(chemin_dossier+"time.txt")
    return {"_message" : "the input file has been created", "_statut": "Started", "_result": None}



@app.get("/output-workflow/{workflow_id}", summary="Récupération de la sortie d'un process", description="On appelle cette route tant que le process n'a pas fini de générer sa sortie. On lui passe le workflow id d'un process en paramètre. Tant que le process n'a pas fini de générer sa sortie et que le timout n'est pas atteint (définition du timeout optionnel) le process s'éxécute. Lorsque c'est fini il renvoie la table de sortie au format JSON classique de type : {'_message': f'Your workflow is finished.', '_statut': 'Finished', '_result': data} ou data est la table de sortie du workflow formaté aussi au format JSON. Lorsque le process est fini, il supprime le sous dossier dans 'exchangeApi' et on peut donc rappeler le process avec la route /input-workflow .")
def read_root(workflow_id, api_key: str = Depends(get_api_key)):
    chemin_dossier = MetManagement.get_api_local_folder(workflow_id=workflow_id)
    if not os.path.exists(chemin_dossier):
        return JSONResponse(
            status_code=404,
            content={"_message": "Error no folder found"}
        )
    ## on check si le timeout est défini et s'il est atteint
    if 0 != hlit_workflow_management.check_if_timout_is_reached(chemin_dossier):
        return JSONResponse(
            status_code=404,
            content={"_message": "Timeout has been reached.", "_statut":"Timeout",
                     "_result": None}
        )
    if not os.path.exists(chemin_dossier + ".out_ok") and not os.path.exists(chemin_dossier + "output.json"):
        if os.path.exists(chemin_dossier + ".statut_ok"):
            with open(chemin_dossier + "statut.json", "r", encoding="utf-8") as file:
                data = json.load(file)
                return JSONResponse(
                    status_code=202,
                    content={"_message": "Your data are still being processed.", "_statut": data["value"], "_result": None}
                )
        else:
            return JSONResponse(
                status_code=202,
                content={"_message": "Your data are still being processed.", "_statut": None, "_result": None}
            )

    output_path = os.path.join(chemin_dossier, "output.json")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        data = {}
    else:
        with open(output_path, "r", encoding="utf-8") as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                data = {}
    MetManagement.reset_folder(chemin_dossier, recreate=False)
    return JSONResponse(
                status_code=200,
                content={"_message": "Your workflow is finished.", "_statut": "Finished", "_result": data}
            )

@app.get("/chat/{workflow_id}",  summary="Stream pour LLM", description="On passe workflow id d'un process. Cela écoute si le workflow écrit un fichier chat_output.txt. Si oui le retour est stream par cette route. Elle reste ouverte tant que le chat n'a pas fini de générer des tokens.")
def chat(workflow_id, api_key: str = Depends(get_api_key)):
    chemin_dossier = MetManagement.get_api_local_folder(workflow_id=workflow_id)
    if os.path.exists(chemin_dossier + "chat_output.txt"):
        os.remove(chemin_dossier + "chat_output.txt")
    return StreamingResponse(hlit_workflow_management.stream_tokens_from_file(chemin_dossier), media_type="text/event-stream")

@app.get("/kill-process/{key_name}", summary="Kill process", description="On passe la key name pour savoir si un process est en cours, si c'est le cas on le kill")
def kill_process(key_name, api_key: str = Depends(get_api_key)):
    chemin_dossier = MetManagement.get_api_local_folder_admin()
    chemin_dossier = chemin_dossier + key_name + ".txt"
    message = hlit_workflow_management.kill_process(chemin_dossier,
                 "python.exe")
    MetManagement.reset_files([chemin_dossier])
    # si erreur pas grave
    if 0!=hlit_workflow_management.purge_worklow_input_id_list_from_keyname(key_name):
        pass

    return JSONResponse(
        status_code=200,
        content={"_statut": message}
    )
@app.get("/kill-daemon/{key_name}", include_in_schema=False,summary="Kill daemon and associated process", description="On passe la key name pour savoir si un process est en cours, si c'est le cas on le kill")
def kill_daemon(key_name, api_key: str = Depends(get_api_key)):
    chemin_dossier = MetManagement.get_api_local_folder_admin()
    chemin_dossier = chemin_dossier + key_name + ".dmn"
    hlit_workflow_management.kill_process(chemin_dossier,
                 "python.exe")
    MetManagement.reset_files([chemin_dossier])
    return kill_process(key_name)

@app.get("/kill-all", summary="Kill all daemon and process", description="On  kill tous les daemon et process de types cmd.exe")
def kill_all_process_and_daemon(api_key: str = Depends(get_api_key)):
    chemin_dossier = MetManagement.get_api_local_folder_admin()
    fichiers = [f for f in os.listdir(chemin_dossier) if os.path.isfile(os.path.join(chemin_dossier, f))]
    for f in fichiers:
        if len(f)>4:
            if f[-4:]==".dmn":
                hlit_workflow_management.kill_process(chemin_dossier + f,"python.exe")
                time.sleep(1)
                MetManagement.reset_files([chemin_dossier + f])
    for f in fichiers:
        if len(f) > 4:
            if f[-4:] == ".txt":
                hlit_workflow_management.kill_process(chemin_dossier + f, "python.exe")
                time.sleep(1)
                MetManagement.reset_files([chemin_dossier + f])

    chemin_dossier_api =MetManagement.get_api_local_folder()
    # reset le dossier exchangeApi
    if os.path.exists(chemin_dossier_api):
        MetManagement.reset_folder(chemin_dossier_api, recreate=False)

    # reset le dossier exchangeApiadm
    if os.path.exists(chemin_dossier):
        MetManagement.reset_folder(chemin_dossier, recreate=False)

    return JSONResponse(
        status_code=200,
        content={"files deleted ": fichiers}
    )

@app.get("/duplicate/{key_name}", summary="Duplicate a workflow", description="On dupplique un workflow pour éviter tout problème de conflit avec un workflow en cours ou lancé")
def dupplicate(key_name, id: Optional[str] = None, api_key: str = Depends(get_api_key)):
    all_config = read_config_file_ows_html()
    config = {}
    for item in all_config["message"]:
        if item["name"] == key_name:
            config = item
            break
    key_name, id =hlit_workflow_management.dupplicate_workflow([config], id)
    return JSONResponse(
        status_code=200,
        content={"key_name": key_name, "id": id}
    )


@app.get("/delete-duplicate/{id}", summary="Delete a duplicate a workflow", description="On supprime un workflow qui a été duppliqué")
def delete_dupplicate(id, api_key: str = Depends(get_api_key)):
    if 0 != hlit_workflow_management.delete_temp(id):
        return JSONResponse(
            status_code=404,
            content={"message": "Error occurs to delete workflow"}
        )
    return JSONResponse(
        status_code=200,
        content={"message": "Workflow deleted"}
    )


@app.get("/exit-srv", include_in_schema=False,summary="Quit the server instance", description="On  quitte l instance actuelle")
def exit_srv(api_key: str = Depends(get_api_key)):
    prod=False # aller lire un fichier quelque part
    if not prod:
        try:
            os.kill(os.getpid(), signal.SIGINT)# peut echouer sur --reload
        except Exception:
            os._exit(0) # butal quit
    return JSONResponse(
        status_code=403,
        content={"acces refusé"}
    )

def load_config_serveur(config_file="uvicorn.json"):
    global API_KEYS, SECURED_PATHS
    auth_required = True  # Mets False ici si tu veux désactiver la clé API

    # on va lire le fichier config serveur
    data = hlit_workflow_management.lire_config_serveur(config_file)

    if data:
        auth_required = data.get("auth_required", False)
        API_KEYS = data.get("api_keys", [])
        SECURED_PATHS = data.get("secured_paths", [])
    else:
        API_KEYS = []
        SECURED_PATHS = []
    # Variable d’environnement pour la logique
    os.environ["REQUIRE_AUTH"] = "true" if auth_required else "false"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--autoquit_terminal_if_already_started", action="store_true", help="Quitte le terminal si le port est déjà utilisé.")
    args = parser.parse_args()

    #utile pour configurer l'auth par cle api
    #load_config_serveur()

    launch_uvicorn()
    if args.autoquit_terminal_if_already_started:
        system = platform.system()

        if system == "Windows":
            # Ferme la fenêtre du terminal (cmd.exe) en tuant le processus parent
            parent_pid = os.getppid()
            subprocess.Popen(f"taskkill /PID {parent_pid} /F", shell=True)


        elif system == "Darwin":
            # AppleScript pour fermer la fenêtre Terminal
            script = '''
            tell application "Terminal"
                if (count of window) > 0 then
                    close (last window)
                end if
            end tell
            '''
            subprocess.Popen(["osascript", "-e", script])