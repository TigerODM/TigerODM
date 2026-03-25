import schedule
from datetime import datetime
import time
import os
import json
import sys

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import server_uvicorn, management_workflow_sans_api
    from Orange.widgets.orangecontrib.AAIT.utils import thread_management, MetManagement
else:
    from orangecontrib.HLIT_dev.remote_server_smb import server_uvicorn, management_workflow_sans_api
    from orangecontrib.AAIT.utils import thread_management, MetManagement


VALID_UNITS = {
    "seconds": lambda n: schedule.every(n).seconds,
    "minutes": lambda n: schedule.every(n).minutes,
    "hours": lambda n: schedule.every(n).hours,
    "days": lambda n: schedule.every(n).days,
}

WEEKDAYS = {
    "monday": schedule.every().monday,
    "tuesday": schedule.every().tuesday,
    "wednesday": schedule.every().wednesday,
    "thursday": schedule.every().thursday,
    "friday": schedule.every().friday,
    "saturday": schedule.every().saturday,
    "sunday": schedule.every().sunday,
}

AVAILABLE_UNITS_EVERY = ["seconds", "minutes", "hours", "days"]

AVAILABLE_UNITS_AT = ["day", "hour", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]



class SchedulerApp:
    def __init__(self):
        self.threads = []

    def run_script(self, job: dict):
        now_dt = datetime.now()
        now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        name = job["name"]

        # Optionnel : exécuter seulement un certain jour du mois
        dom = job.get("day_of_month")
        if dom is not None and now_dt.day != int(dom):
            print(f"[{now}] Skip job={name} (day {now_dt.day} != {dom})")
            return

        print(f"[{now}] Appel API... job={name}")

        try:
            management_workflow_sans_api.call_workflow_without_api(key_name=name)
        except Exception as e:
            print(f"[{now}] Erreur job={name}: {e}")

    def run_script_async(self, job: dict):
        thread = thread_management.Thread(self.run_script, job)

        self.threads.append(thread)
        thread.finish.connect(lambda: self.threads.remove(thread))

        thread.start()

    def register_job(self, job: dict):
        name = job["name"]
        unit = job["unit"].lower()

        # Cas 1 : every X seconds/minutes/hours/days
        if "every" in job:
            every = job["every"]

            if unit not in VALID_UNITS:
                raise ValueError(f"Invalid unit: {unit}")

            VALID_UNITS[unit](every).do(self.run_script_async, job).tag(name)
            return

        # Cas 2 : at HH:MM (daily ou weekday)
        if "at" in job:
            at_time = job["at"]

            if unit in WEEKDAYS:
                WEEKDAYS[unit].at(at_time).do(self.run_script_async, job).tag(name)
                return

            if unit in ["day", "daily"]:
                schedule.every().day.at(at_time).do(self.run_script_async, job).tag(name)
                return

        raise ValueError(f"Invalid job configuration: {job}")

    def main(self, jobs=None):
        if jobs is None:
            config = server_uvicorn.read_config_file_ows_html()
            jobs = config["message"]
        if not jobs:
            print("No jobs configured.")
            return

        for job in jobs:
            if "unit" in job:
                self.register_job(job)

        print("Scheduler started")

        while True:
            schedule.run_pending()
            time.sleep(1)

def charger_json(path):
    if not os.path.exists(path):
        print(f"{path} n'existe pas, création du fichier.")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4)
        return []

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sauvegarder_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def afficher_jobs(data):
    print("\nJobs existants :")

    if not data:
        print("Aucun job")
        return 1

    for i, job in enumerate(data, 1):
        name = job.get("name", "<sans nom>")
        unit = job.get("unit", "<sans unit>")

        if "every" in job:
            desc = f"toutes les {job['every']} {unit}"

        elif "at" in job:
            if unit == "hour":
                desc = f"toutes les heures à {job['at']}"
            elif unit in ["day", "daily"]:
                desc = f"tous les jours à {job['at']}"
            else:
                desc = f"tous les {unit} à {job['at']}"

            if "day_of_month" in job:
                desc += f" (jour du mois: {job['day_of_month']})"

        else:
            desc = "configuration inconnue"

        print(f"{i} - {name} ({desc})")

def modifier_job(data):
    if 1 == afficher_jobs(data):
        return

    try:
        index = int(input("\nNuméro du job à modifier : ").strip()) - 1
    except ValueError:
        print("Index invalide")
        return

    if index < 0 or index >= len(data):
        print("Index invalide")
        return

    job = data[index]

    print(f"\nModification de {job['name']}")
    print("Laisser vide pour conserver la valeur actuelle.\n")

    print("Type de planification actuel :")
    if "every" in job:
        print(f"- every={job['every']} unit={job['unit']}")
    elif "at" in job:
        msg = f"- unit={job['unit']} at={job['at']}"
        if "day_of_month" in job:
            msg += f" day_of_month={job['day_of_month']}"
        print(msg)
    else:
        print("- configuration non reconnue")

    print("\nNouveau type de planification :")
    print("1 - Toutes les X unités (every + unit)")
    print("2 - À une heure/minute précise (at + unit)")
    print("Entrée vide = garder le mode actuel")

    mode = input("Choix (1/2) : ").strip()

    if mode == "1" or (mode == "" and "every" in job):
        current_every = job.get("every", "")
        current_unit = job.get("unit", "")

        every_raw = input(f"every ({current_every}) : ").strip()
        unit_raw = input(f"unit {AVAILABLE_UNITS_EVERY} ({current_unit}) : ").strip().lower()

        if every_raw:
            try:
                job["every"] = int(every_raw)
            except ValueError:
                print("every doit être un entier")
                return

        if unit_raw:
            if unit_raw not in AVAILABLE_UNITS_EVERY:
                print(f"Unit invalide. Valeurs autorisées : {AVAILABLE_UNITS_EVERY}")
                return
            job["unit"] = unit_raw

        # Nettoyage des clés incompatibles
        job.pop("at", None)
        job.pop("day_of_month", None)

        print("Job modifié :")
        print(job)
        return

    if mode == "2" or (mode == "" and "at" in job):
        current_unit = job.get("unit", "")
        current_at = job.get("at", "")

        unit_raw = input(f"unit {AVAILABLE_UNITS_AT} ({current_unit}) : ").strip().lower()
        if not unit_raw:
            unit_raw = current_unit

        if unit_raw not in AVAILABLE_UNITS_AT:
            print(f"Unit invalide. Valeurs autorisées : {AVAILABLE_UNITS_AT}")
            return

        if unit_raw == "hour":
            at_prompt = f'at format ":MM" ({current_at}) : '
            at_raw = input(at_prompt).strip()

            if not at_raw:
                at_raw = current_at

            if not at_raw.startswith(":") or len(at_raw) != 3 or not at_raw[1:].isdigit():
                print('Format invalide pour hour. Exemple attendu : ":30"')
                return
        else:
            at_prompt = f'at format "HH:MM" ({current_at}) : '
            at_raw = input(at_prompt).strip()

            if not at_raw:
                at_raw = current_at

            parts = at_raw.split(":")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                print('Format invalide. Exemple attendu : "09:00"')
                return

            hh, mm = map(int, parts)
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                print("Heure invalide")
                return

        job["unit"] = unit_raw
        job["at"] = at_raw

        # Nettoyage des clés incompatibles
        job.pop("every", None)

        # Gestion optionnelle du jour du mois
        current_dom = job.get("day_of_month", "")
        dom_raw = input(f"day_of_month ({current_dom}) [vide = inchangé, 0 = supprimer] : ").strip()

        if dom_raw:
            try:
                dom = int(dom_raw)
            except ValueError:
                print("day_of_month doit être un entier")
                return

            if dom == 0:
                job.pop("day_of_month", None)
            else:
                if not (1 <= dom <= 31):
                    print("day_of_month doit être entre 1 et 31")
                    return

                if unit_raw not in ["day", "daily"]:
                    print('day_of_month ne peut être utilisé qu’avec unit="day" ou "daily"')
                    return

                job["day_of_month"] = dom

        print("Job modifié :")
        print(job)
        return

    if mode == "":
        print("Aucune modification appliquée")
        return

    print("Choix invalide")

def ajouter_job(data):
    existing = [j["name"] for j in data]

    config = server_uvicorn.read_config_file_ows_html()
    available_names = [job["name"] for job in config["message"]]

    print("\nJobs disponibles à ajouter :")
    for name in available_names:
        if name not in existing:
            print("-", name)

    name = input("\nNom du job : ").strip()

    if not name:
        print("Nom vide")
        return

    if name in existing:
        print("Ce job existe déjà")
        return

    print("\nType de planification :")
    print("1 - Toutes les X unités de temps (every + unit) ex: toutes 5 minutes depuis le lancement de l'application")
    print("2 - À une heure/minute précise (at + unit)")

    mode = input("Choix (1/2) : \n").strip()

    job = {"name": name}

    if mode == "1":
        try:
            every = int(input("every : ").strip())
        except ValueError:
            print("every doit être un entier")
            return

        unit = input(f"unit {AVAILABLE_UNITS_EVERY} : ").strip().lower()

        if unit not in AVAILABLE_UNITS_EVERY:
            print(f"Unit invalide. Valeurs autorisées : {AVAILABLE_UNITS_EVERY}")
            return

        job["every"] = every
        job["unit"] = unit

    elif mode == "2":
        unit = input(f"unit {AVAILABLE_UNITS_AT} : ").strip().lower()

        if unit not in AVAILABLE_UNITS_AT:
            print(f"Unit invalide. Valeurs autorisées : {AVAILABLE_UNITS_AT}")
            return

        if unit == "hour":
            print('Pour "hour", utilise un format du type ":30"')
            at_value = input('at (ex: ":30") : ').strip()
            if not at_value.startswith(":") or len(at_value) != 3 or not at_value[1:].isdigit():
                print('Format invalide pour hour. Exemple attendu : ":30"')
                return
        else:
            print('Utilise un format "HH:MM"')
            at_value = input('at (ex: "09:00") : ').strip()
            parts = at_value.split(":")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                print('Format invalide. Exemple attendu : "09:00"')
                return

            hh, mm = map(int, parts)
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                print("Heure invalide")
                return

        job["unit"] = unit
        job["at"] = at_value

        # Option mensuelle
        add_dom = input("Jour du mois spécifique ? (laisser vide sinon) : \n").strip()
        if add_dom:
            try:
                dom = int(add_dom)
            except ValueError:
                print("day_of_month doit être un entier")
                return

            if not (1 <= dom <= 31):
                print("day_of_month doit être entre 1 et 31")
                return

            if unit != "day":
                print('day_of_month ne peut être utilisé qu’avec unit="day"')
                return

            job["day_of_month"] = dom

    else:
        print("Choix invalide")
        return

    data.append(job)
    print("Job ajouté :")
    print(job)

def supprimer_job(data):
    afficher_jobs(data)

    if not data:
        return

    try:
        index = int(input("\nNuméro du job à supprimer : ").strip()) - 1
    except ValueError:
        print("Index invalide")
        return

    if index < 0 or index >= len(data):
        print("Index invalide")
        return

    job = data[index]

    confirm = input(f"Supprimer le job '{job['name']}' ? (y/n) : ").strip().lower()

    if confirm != "y":
        print("Suppression annulée")
        return

    data.pop(index)

    print(f"Job '{job['name']}' supprimé")

def get_folder_path():
    folder_path = MetManagement.get_jobs_path()
    if not os.path.exists(folder_path):
        try:
            os.makedirs(folder_path, exist_ok=True)
        except Exception as e:
            print(f"Failed to create folder: {e}")
    return folder_path + "jobs.json"

def scheduler_manager(path, data):
    afficher_jobs(data)
    print("\n1 - Lancer")
    print("2 - Modifier")
    print("3 - Ajouter")
    print("4 - Supprimer")
    print("5 - Exit")

    choix = input("\nChoix : \n")
    if choix == "1":
        management_workflow_sans_api.reset_workflow()
        SchedulerApp().main(data)

    if choix == "2":
        modifier_job(data)

    elif choix == "3":
        ajouter_job(data)

    elif choix == "4":
        supprimer_job(data)

    elif choix == "5":
        return
    sauvegarder_json(path, data)

    if choix == "2" or choix == "3" or choix == "4":
        print("\nJSON mis à jour.")
    scheduler_manager(path, data)


if __name__ == "__main__":
    path = get_folder_path()
    data = charger_json(path)

    #lancer scheduler directement depuis un script
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "scheduler":
            management_workflow_sans_api.reset_workflow()
            SchedulerApp().main(data)

    #choix de l'action par l'utilisateur entre lancement, modification et ajout
    else:
        scheduler_manager(path, data)
