import time
import os


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.HLIT_dev.utils import hlit_python_api
else:
    from orangecontrib.HLIT_dev.utils import hlit_python_api

# a supprimer ou a ameliorer grandement!!
def boucle_workflow():
    """
    Exécute une boucle de requêtes POST/GET vers un serveur, en attendant que le workflow soit terminé.

    Conditions de sortie de la boucle GET :
    - Code HTTP 200
    - Champ "_statut" == "Finished" dans le JSON retourné

    Paramètres :
    - ip_port (str) : IP et port du serveur (ex : "127.0.0.1:8000")
    - workflow_id (str) : nom du fichier workflow (ex : "untitled.ows")
    - temporisation (float) : délai entre chaque tentative (en secondes)
    """
    key_name="chatbot basique"
    ip_port = "127.0.0.1:8000"
    # timeout_daemon=20 # requeter
    temporisation = 0.3
    temporisation_demarrage_fermeture=20 # seconde
    order_liste_of_request_post=[]
    order_workflow_id=[]
    workflow_id = "chatbot_1_mini.ows"
    post_command = [
        "curl", "--silent", "--show-error", "--location",
        f"{ip_port}/input-workflow",
        "--header", "Content-Type: application/json",
        "--data", f'''{{
            "workflow_id": "{workflow_id}",
            "front_id": "11OO1O1O1",
            "data": [
                {{
                    "num_input": 0,
                    "values": [
                        ["prompt"],
                        ["str"],
                        [["coucou qui es tu?"]]
                    ]
                }}
            ]
        }}'''
    ]
    order_liste_of_request_post.append(post_command)
    order_workflow_id.append(workflow_id)
    while True:# cycle de demmmarage fermeture d orange
        if 0!=hlit_python_api.call_start_workflow(ip_port,key_name):
            print("error running workflow")
            break
        print("start workflow -> ok")
        time.sleep(temporisation_demarrage_fermeture)

        if 0!=hlit_python_api.call_kill_process(ip_port,key_name):
            print("error stopping workflow")
            break
        print("kill workflow -> ok")
        time.sleep(temporisation)
        # end while True cycle de demmmarage fermeture d orange

    #ip_port = "127.0.0.1:8000", workflow_id = "untitled.ows", temporisation = 0.3
    # null_file = "NUL" if platform.system() == "Windows" else "/dev/null"

    # while True:
    #     try:
    #         # 1. Envoi de la requête POST
    #         post_command = [
    #             "curl", "--silent", "--show-error", "--location",
    #             f"{ip_port}/input-workflow",
    #             "--header", "Content-Type: application/json",
    #             "--data", f'''{{
    #                 "workflow_id": "{workflow_id}",
    #                 "front_id": "11OO1O1O1",
    #                 "data": [
    #                     {{
    #                         "num_input": 0,
    #                         "values": [
    #                             ["col1"],
    #                             ["float"],
    #                             [[3]]
    #                         ]
    #                     }}
    #                 ]
    #             }}'''
    #         ]
    #
    #         print(f"[POST] → {ip_port}/input-workflow (workflow : {workflow_id})")
    #         result = subprocess.run(post_command, capture_output=True, text=True)
    #
    #         if result.returncode != 0:
    #             print("❌ Erreur POST :", result.stderr)
    #             break
    #
    #         # 2. Attente de la complétion du workflow via GET
    #         while True:
    #             get_command = [
    #                 "curl", "--silent", "--show-error",
    #                 "-X", "GET",
    #                 f"http://{ip_port}/output-workflow/{workflow_id}",
    #                 "-H", "accept: application/json"
    #             ]
    #
    #             get_result = subprocess.run(get_command, capture_output=True, text=True)
    #
    #             if get_result.returncode != 0:
    #                 print("❌ Erreur GET :", get_result.stderr)
    #                 return
    #
    #             try:
    #                 response_json = json.loads(get_result.stdout)
    #             except json.JSONDecodeError:
    #                 print("❌ Réponse non JSON. Attente...")
    #                 time.sleep(temporisation)
    #                 continue
    #
    #             statut = response_json.get("_statut", "")
    #             print(f"[GET] _statut = {statut}")
    #
    #             if statut == "Finished":
    #                 print("✅ Workflow terminé avec succès.")
    #                 break
    #
    #             time.sleep(temporisation)
    #
    #         # Pause avant de recommencer un nouveau cycle
    #         time.sleep(temporisation)
    #
    #     except Exception as e:
    #         print("❌ Erreur inattendue :", e)
    #         break

if __name__ == "__main__":
    boucle_workflow()