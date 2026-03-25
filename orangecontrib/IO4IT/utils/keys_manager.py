import os
import re
import json
import hashlib
import getpass
from pathlib import Path
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
    from Orange.widgets.orangecontrib.IO4IT.utils import secret_manager
else:
    from orangecontrib.AAIT.utils import MetManagement
    from orangecontrib.IO4IT.utils import secret_manager



def _normalize_single_quotes_json(s: str) -> str:
    """
    Convertit un pseudo-JSON avec quotes simples
    en JSON valide, de manière contrôlée.
    """
    # ⚠️ On ne touche qu'aux clés et valeurs simples
    # 'key': 'value'  →  "key": "value"
    s = re.sub(r"'([^']*)'\s*:", r'"\1":', s)
    s = re.sub(r":\s*'([^']*)'", r': "\1"', s)
    s = re.sub(r'(?<!\\)\\(?!\\)', r'\\\\', s)
    return s



def ask_secure():
    while True:
        resp = input("Secure? (Y/N) : ").strip().lower()
        if resp in ("y", "yes"):
            return True
        if resp in ("n", "no"):
            return False
        print("Please enter Y or N.")
#  FONCTIOSN D'OBFUSCATION GÉNÉRALES & CHEMIN
# Fonction pour générer une clé simple à partir du nom d'utilisateur
def get_user_key():
    try:
        username = getpass.getuser()
        #try:
        #username = os.getlogin()

        #except OSError:
        #username = getpass.getuser()

        if not username:
            raise ValueError("Nom d'utilisateur introuvable")

        # On dérive une clé simple (1 octet) depuis le hash du nom d'utilisateur
        digest = hashlib.sha256(username.encode("utf-8")).digest()
        key = digest[0]  # 1 octet pour XOR
        return key

    except Exception as e:
        raise RuntimeError(f"Erreur de génération de clé : {e}")


# Fonction simple de chiffrement/déchiffrement par XOR (non sécurisé mais obscurcissant)
def xor_crypt(data: str, key: int) -> str:
    return ''.join(chr(ord(c) ^ (key & 0xFF)) for c in data)


# Renvoie le chemin absolu vers le sous-dossier « aait_store/keys »
def get_keys_dir(type_key: str = "MICROSOFT_EXCHANGE_OAUTH2") -> str:
    """
    Retourne …/aait_store/keys/<type_key> sans // ni slash final,
    créé au besoin.  type_key ∈ {"IMAP4_SSL", "API", "NXP"}.
    """
    try:
        # normalise le chemin racine
        base = os.path.normpath(MetManagement.get_secret_content_dir())
        if os.path.basename(base) != "keys":
            base = os.path.join(base, "keys")
        dossier = os.path.normpath(os.path.join(base, type_key))
        os.makedirs(dossier, exist_ok=True)
        return dossier
    except Exception as e:
        raise RuntimeError(f"Erreur création/récupération dossier : {e}")





# GSTION IMAP
#je n'ai pas compris à quoi ça sert et ce n'est pas utilisé: à supprimer
""" 
def save_config(str_type,list_str=[]):
    # str_type==IMAP4_SSL -> list_str=[name,server_imap,mail]
    if str_type=="IMAP4_SSL":
        write_imap_config(list_str)
    return
"""


## va lire le fichier de white_list et black_list
## ce fichier et un json du type {"white_list":[], "black_list":[]}
## si pas de fichier ou juste white_liste ou black list il retourne uniquement celui présent
def lire_list_email(chemin_fichier):
    try:
        chemin_fichier = MetManagement.get_secret_content_dir() + chemin_fichier
        if not os.path.exists(chemin_fichier):
            return [[], []]
        # Lecture du fichier JSON
        with open(chemin_fichier, "r", encoding="utf-8") as f:
            contenu = json.load(f)
        return [
            contenu.get("white_list", []),
            contenu.get("black_list", [])
        ]
    except Exception as e:
        print(f"❌ Erreur lors de la lecture : {e}")
        return None


def enregistrer_config_imap4_ssl(agent, my_domain, password, interval_second, alias=""):
    try:
        dossier = get_keys_dir("IMAP4_SSL")
        # Crée le dossier s'il n'existe pas
        if not os.path.exists(dossier):
            os.makedirs(dossier)

        # Récupère l'adresse MAC et chiffre le mot de passe
        key = get_user_key()
        mdp_chiffre = xor_crypt(password, key)

        # Nom du fichier (remplace @ par _at_ pour éviter les problèmes)
        nom_fichier = os.path.join(dossier, f"{agent}{my_domain.replace('@', '_at_')}.json")
        if alias == "''" or alias == "\"\"":
            alias = ""

        # Contenu à écrire dans le fichier
        contenu = {
            "agent": agent,
            "domain": my_domain,
            "interval_second": interval_second,
            "password_encrypted": mdp_chiffre,
            "alias": alias
        }

        # Écriture du fichier
        with open(nom_fichier, "w", encoding="utf-8") as f:
            json.dump(contenu, f, indent=4)

        print(f"✅ Fichier enregistré : {nom_fichier}")
        return 0

    except Exception as e:
        print(f"❌ Erreur lors de l'enregistrement : {e}")
        return 1

def enregistrer_config_imap4_ssl_secure(agent, my_domain, password, interval_second, alias=""):
    try:
        dossier = get_keys_dir("IMAP4_SSL")
        # Crée le dossier s'il n'existe pas
        if not os.path.exists(dossier):
            os.makedirs(dossier)


        # Nom du fichier (remplace @ par _at_ pour éviter les problèmes)
        nom_fichier = os.path.join(dossier, f"{agent}{my_domain.replace('@', '_at_')}.sec")
        service_name = f"IMAP4_SSL__{agent}{my_domain.replace('@', '_at_')}"
        if alias == "''" or alias == "\"\"":
            alias = ""

        # Contenu à écrire dans le fichier
        contenu = {
            "agent": agent,
            "domain": my_domain,
            "interval_second": interval_second,
            "password": password,
            "alias": alias
        }
        sm = secret_manager.SecretManager(service_name)
        sm.store(contenu,overwrite=True)
        # Écriture du fichier
        open(nom_fichier, "w", encoding="utf-8").close()

        print(f"✅ Fichier enregistré : {nom_fichier}")
        return 0

    except Exception as e:
        print(f"❌ Erreur lors de l'enregistrement : {e}")
        return 1
def enregistrer_config_owa(mail, alias, server, username, password, interval):
    try:
        dossier = get_keys_dir("MICROSOFT_EXCHANGE_OWA")
        # Crée le dossier s'il n'existe pas
        if not os.path.exists(dossier):
            os.makedirs(dossier)

        # Récupère l'adresse MAC et chiffre le mot de passe
        key = get_user_key()
        mdp_chiffre = xor_crypt(password, key)

        # Nom du fichier (remplace @ par _at_ pour éviter les problèmes)
        nom_fichier = os.path.join(dossier, f"{alias.replace('@', '_at_')}.json")

        # Contenu à écrire dans le fichier
        contenu = {
            "mail": mail,
            "alias": alias,
            "server": server,
            "username": username,
            "password_encrypted": mdp_chiffre,
            "interval_second": interval
        }

        # Écriture du fichier
        with open(nom_fichier, "w", encoding="utf-8") as f:
            json.dump(contenu, f, indent=4)

        print(f"✅ Fichier enregistré : {nom_fichier}")
        return 0

    except Exception as e:
        print(f"❌ Erreur lors de l'enregistrement : {e}")
        return 1

def enregistrer_config_owa_secure(mail, alias, server, username, password, interval):
    try:
        dossier = get_keys_dir("MICROSOFT_EXCHANGE_OWA")
        # Crée le dossier s'il n'existe pas
        if not os.path.exists(dossier):
            os.makedirs(dossier)

        # Nom du fichier (remplace @ par _at_ pour éviter les problèmes)
        nom_fichier = os.path.join(dossier, f"{alias.replace('@', '_at_')}.sec")
        service_name=f"MICROSOFT_EXCHANGE_OWA__{alias.replace('@', '_at_')}"


        # Contenu à écrire dans le fichier
        contenu = {
            "mail": mail,
            "alias": alias,
            "server": server,
            "username": username,
            "password_encrypted": password,
            "interval_second": interval
        }
        sm = secret_manager.SecretManager(service_name)
        sm.store(contenu,overwrite=True)
        # Écriture du fichier
        open(nom_fichier, "w", encoding="utf-8").close()

        print(f"✅ Fichier enregistré : {nom_fichier}")
        return 0

    except Exception as e:
        print(f"❌ Erreur lors de l'enregistrement : {e}")
        return 1



def parse_json_and_save_owa(config_str: str) -> None:
    raw = config_str.strip()

    # 1️⃣ Parsing JSON direct
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 2️⃣ Tentative de normalisation contrôlée
        try:
            normalized = _normalize_single_quotes_json(raw)
            data = json.loads(normalized)
        except json.JSONDecodeError:
            raise ValueError(
                "Invalid JSON format. "
                "Use double quotes or valid key/value pairs "
                '(example: {"mail": "nom@domain.com"})'
            ) from None

    # 3️⃣ Type attendu
    if not isinstance(data, dict):
        raise TypeError("JSON root must be an object")

    # 4️⃣ Champs obligatoires
    required_keys = ("mail", "alias", "server", "username", "password_encrypted", "interval_second")
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(f"Missing required key(s): {', '.join(missing)}")

    # 5️⃣ Validation strings
    for key in ("mail", "alias", "server", "username", "password_encrypted"):
        if not isinstance(data[key], str):
            raise TypeError(f"'{key}' must be a string")
        if not data[key].strip():
            raise ValueError(f"'{key}' must be a non-empty string")

    # 6️⃣ interval_second
    interval = data["interval_second"]
    if not isinstance(interval, int):
        raise TypeError("'interval_second' must be an integer")
    if interval <= 0:
        raise ValueError("'interval_second' must be > 0")

    # 7️⃣ Appel sécurisé
    enregistrer_config_owa_secure(
        mail=data["mail"],
        alias=data["alias"],
        server=data["server"],
        username=data["username"],
        password=data["password_encrypted"],
        interval=interval,
    )

def lire_config_imap4_ssl_dict_sec(chemin_fichier):
    if len(chemin_fichier)<5:
        print(f"❌ Error path not correct{chemin_fichier}")
        return None
    if not chemin_fichier.endswith(".sec"):
        chemin_fichier += ".sec"
    try:
        service = "IMAP4_SSL__" + chemin_fichier[:-4]
        sm = secret_manager.SecretManager(service)
        contenu = sm.load_all()
        return contenu


    except Exception as e:
        print(f"❌ Erreur lors de la lecture : {e}")
        return None


# Fonction pour lire le fichier de configuration et déchiffrer le mot de passe
def lire_config_imap4_ssl(chemin_fichier):
    # renvoie une liste =["agent","domain",mdp,"interval_second"]
    if len(chemin_fichier)<5:
        print(f"❌ Error path not correct {chemin_fichier}")
        return None
    if chemin_fichier.endswith(".sec"):
        try:
            service = "IMAP4_SSL__" + chemin_fichier[:-4]
            sm = secret_manager.SecretManager(service)
            contenu = sm.load_all()
            print(contenu)
            return [
                contenu["agent"],
                contenu["domain"],
                contenu["password"],
                int(contenu["interval_second"]),
                contenu.get("alias", "")
            ]

        except Exception as e:
            print(f"❌ Erreur lors de la lecture : {e}")
            return None
    try:
        chemin_fichier = os.path.join(get_keys_dir("IMAP4_SSL"), chemin_fichier)
        # Lecture du fichier JSON
        with open(chemin_fichier, "r", encoding="utf-8") as f:
            contenu = json.load(f)

        # Récupère l'adresse MAC
        key = get_user_key()

        # Déchiffre le mot de passe
        mdp_dechiffre = xor_crypt(contenu["password_encrypted"], key)
        return [
            contenu["agent"],
            contenu["domain"],
            mdp_dechiffre,
            int(contenu["interval_second"]),
            contenu.get("alias", "")
        ]
    except Exception as e:
        print(f"❌ Erreur lors de la lecture : {e}")
        return None

def parse_json_and_save_oauth2(config_str: str) -> None:
    raw = config_str.strip()

    # 1️⃣ Parsing JSON (avec normalisation si quotes simples)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        if "double quotes" in e.msg.lower():
            try:
                normalized = _normalize_single_quotes_json(raw)
                data = json.loads(normalized)
            except json.JSONDecodeError:
                raise ValueError(
                    "Invalid JSON: use double quotes "
                    '(example: {"client_id": "xxx"})'
                ) from None
        else:
            raise ValueError(f"Invalid JSON syntax: {e.msg}") from None

    # 2️⃣ Type attendu
    if not isinstance(data, dict):
        raise TypeError("JSON root must be an object")

    # 3️⃣ Champs obligatoires
    required_keys = ("client_id", "client_secret", "tenant_id", "user_email")
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(f"Missing required key(s): {', '.join(missing)}")

    # 4️⃣ Validation des champs string obligatoires
    for key in required_keys:
        if not isinstance(data[key], str):
            raise TypeError(f"'{key}' must be a string")
        if not data[key].strip():
            raise ValueError(f"'{key}' must be a non-empty string")

    # 5️⃣ Champ optionnel : type
    cfg_type = data.get("type", "MICROSOFT_EXCHANGE_OAUTH2")
    if not isinstance(cfg_type, str):
        raise TypeError("'type' must be a string")
    if not cfg_type.strip():
        raise ValueError("'type' must be a non-empty string")

    # 6️⃣ Appel sécurisé
    enregistrer_config_oauth2_secure(
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        tenant_id=data["tenant_id"],
        user_email=data["user_email"],
        type=cfg_type,
    )

def lire_config_oauth2_dict_sec(chemin_fichier, type="MICROSOFT_EXCHANGE_OAUTH2"):
    # renvoie une liste =["agent","domain",mdp,"interval_second"]
    if len(chemin_fichier) < 5:
        print(f"❌ Error path not correct {chemin_fichier}")
        return None
    if not chemin_fichier.endswith(".sec"):
        chemin_fichier+=".sec"
        try:
            service = type + "__" + chemin_fichier[:-4]
            sm = secret_manager.SecretManager(service)
            contenu = sm.load_all()
            return contenu
        except Exception as e:
            print(f"❌ Erreur lors de la lecture : {e}")
            return None

def lire_config_oauth2(chemin_fichier, type="MICROSOFT_EXCHANGE_OAUTH2"):
    # renvoie une liste =["agent","domain",mdp,"interval_second"]
    if len(chemin_fichier) < 5:
        print(f"❌ Error path not correct {chemin_fichier}")
        return None
    if chemin_fichier.endswith(".sec"):
        try:
            service = type + "__" + chemin_fichier[:-4]
            sm = secret_manager.SecretManager(service)
            contenu = sm.load_all()
            return [
                contenu["client_id"],
                contenu["client_secret"],
                contenu["tenant_id"],
                contenu["user_email"]
            ]

        except Exception as e:
            print(f"❌ Erreur lors de la lecture : {e}")
            return None
    try:
        chemin_fichier = os.path.join(get_keys_dir(type), chemin_fichier)
        # Lecture du fichier JSON
        with open(chemin_fichier, "r", encoding="utf-8") as f:
            contenu = json.load(f)

        # Récupère l'adresse MAC
        key = get_user_key()

        # Déchiffre le mot de passe
        client_id = xor_crypt(contenu["client_id_chiffre"], key)
        client_secret = xor_crypt(contenu["client_secret_chiffre"], key)
        tenant_id = xor_crypt(contenu["tenant_id_chiffre"], key)
        return [
            client_id,
            client_secret,
            tenant_id,
            contenu["user_email"]
        ]
    except Exception as e:
        print(f"❌ Erreur lors de la lecture : {e}")
        return None

def lire_config_owa_dict_sec(chemin_fichier):
    if len(chemin_fichier)<5:
        print(f"❌ Error path not correct {chemin_fichier}")
        return None
    if not chemin_fichier.endswith(".sec"):
        chemin_fichier += ".sec"
        try:
            service="MICROSOFT_EXCHANGE_OWA__"+chemin_fichier[:-4]
            sm = secret_manager.SecretManager(service)
            contenu = sm.load_all()
            return contenu

        except Exception as e:
            print(f"❌ Erreur lors de la lecture : {e}")
            return None


def lire_config_owa(chemin_fichier):
    if len(chemin_fichier)<5:
        print(f"❌ Error path not correct {chemin_fichier}")
        return None
    if chemin_fichier.endswith(".sec"):
        try:
            service="MICROSOFT_EXCHANGE_OWA__"+chemin_fichier[:-4]
            sm = secret_manager.SecretManager(service)
            contenu = sm.load_all()
            return [
                contenu["mail"],
                contenu["alias"],
                contenu["server"],
                contenu["username"],
                contenu["password_encrypted"],
                int(contenu["interval_second"])
            ]

        except Exception as e:
            print(f"❌ Erreur lors de la lecture : {e}")
            return None

    try:
        chemin_fichier = os.path.join(get_keys_dir("MICROSOFT_EXCHANGE_OWA"), chemin_fichier)
        print("chemin fichier", chemin_fichier)
        # Lecture du fichier JSON
        with open(chemin_fichier, "r", encoding="utf-8") as f:
            contenu = json.load(f)

        # Récupère l'adresse MAC
        key = get_user_key()

        # Déchiffre le mot de passe
        mdp_dechiffre = xor_crypt(contenu["password_encrypted"], key)
        return [
            contenu["mail"],
            contenu["alias"],
            contenu["server"],
            contenu["username"],
            mdp_dechiffre,
            int(contenu["interval_second"])
        ]

    except Exception as e:
        print(f"❌ Erreur lors de la lecture : {e}")
        return None


def enregistrer_config_cli_imap4_ssl():
    print("\n📝 Écriture d’un fichier de configuration :")
    agent = input("🤖 Nom de l’agent : ").strip()
    domaine = input("📨 @domain.com? : ").strip()
    mdp = input("📨mot de passe? : ").strip()
    interval = int(input("⏱️ Intervalle en secondes : ").strip())
    alias = input("Nom de l'alias : ").strip()
    store = ask_secure()
    if not store:
        if 0 != enregistrer_config_imap4_ssl(agent, domaine, mdp, interval, alias):
            print("erreur!")
            return
    if 0 != enregistrer_config_imap4_ssl_secure(agent, domaine, mdp, interval, alias):
        print("erreur!")
        return

def enregistrer_config_cli_owa():
    print("\n📝 Écriture d’un fichier de configuration owa :")
    mail = input("🤖 mail (nom@domain.com) : ").strip()
    alias = input("📨 alias (=mail apparant :(nom2@domain2.com) ").strip()
    server = input("server ? toto.titi.tata: ").strip()
    username = input("usernamme (domaine\\username): ").strip()
    mdp = input("password?: ").strip()
    interval = int(input("⏱️ Intervalle en secondes : ").strip())
    store = ask_secure()

    if alias == "''" or alias == "\"\"" or alias == "":
        alias = mail
    if not store:
        if 0 != enregistrer_config_owa(mail, alias, server, username, mdp, interval):
            print("erreur!")
        return
    if 0 != enregistrer_config_owa_secure(mail, alias, server, username, mdp, interval):
        print("erreur!")

def enregistrer_config_oauth2_secure(client_id, client_secret, tenant_id, user_email, type="MICROSOFT_EXCHANGE_OAUTH2"):
    dossier = get_keys_dir(type)
    # Crée le dossier s'il n'existe pas
    if not os.path.exists(dossier):
        os.makedirs(dossier)

    # Nom du fichier (remplace @ par _at_ pour éviter les problèmes)
    nom_fichier = os.path.join(dossier, f"{user_email.replace('@', '_at_')}.sec")
    service_name = f"{type}__{user_email.replace('@', '_at_')}"


    contenu = {
        "client_id": client_id,
        "client_secret": client_secret,
        "tenant_id": tenant_id,
        "user_email": user_email
    }

    sm = secret_manager.SecretManager(service_name)
    sm.store(contenu,overwrite=True)
    # Écriture du fichier
    open(nom_fichier, "w", encoding="utf-8").close()


    print(f"✅ Fichier enregistré : {nom_fichier}")
    return 0


def enregistrer_config_oauth2(client_id, client_secret, tenant_id, user_email, type="MICROSOFT_EXCHANGE_OAUTH2"):
    dossier = get_keys_dir(type)
    # Crée le dossier s'il n'existe pas
    if not os.path.exists(dossier):
        os.makedirs(dossier)

    # Récupère l'adresse MAC et chiffre le mot de passe
    key = get_user_key()
    client_id_chiffre = xor_crypt(client_id, key)
    client_secret_chiffre = xor_crypt(client_secret, key)
    tenant_id_chiffre = xor_crypt(tenant_id, key)

    contenu = {
        "client_id_chiffre": client_id_chiffre,
        "client_secret_chiffre": client_secret_chiffre,
        "tenant_id_chiffre": tenant_id_chiffre,
        "user_email": user_email
    }


    # Nom du fichier (remplace @ par _at_ pour éviter les problèmes)
    nom_fichier = os.path.join(dossier, f"{user_email.replace('@', '_at_')}.json")

    # Écriture du fichier
    with open(nom_fichier, "w", encoding="utf-8") as f:
        json.dump(contenu, f, indent=4)

    print(f"✅ Fichier enregistré : {nom_fichier}")
    return 0

def enregistrer_config_cli_oauth2():
    print("\n📝 Écriture d’un fichier de configuration OAuth2 :")
    type = input(
        "📄 Nom du service à choisir entre MICROSOFT_EXCHANGE_OAUTH2 et MICROSOFT_EXCHANGE_OAUTH2_MICROSOFT_GRAPH  : ").strip()
    client_id = input("🆔 Client ID : ").strip()
    client_secret = input("🔑 Client Secret : ").strip()
    tenant_id = input("🏢 Tenant ID (GUID Azure) : ").strip()
    user_email = input("📨 Adresse email de l'utilisateur Exchange : ").strip()
    store = ask_secure()
    if not store:
        if 0 != enregistrer_config_oauth2(client_id, client_secret, tenant_id, user_email, type):
            print("erreur!")
        return
    if 0 != enregistrer_config_oauth2_secure(client_id, client_secret, tenant_id, user_email, type):
        print("erreur!")




def lire_config_cli_oauth2(type=""):
    if type == "":
        type = input("📄 Nom du service à choisir entre MICROSOFT_EXCHANGE_OAUTH2 et MICROSOFT_EXCHANGE_OAUTH2_MICROSOFT_GRAPH  : ").strip()
    chemin_fichier = input("📄 nom fichier json (pas le chemin!) JSON : ").strip()
    print("oeoeo ", chemin_fichier, type)
    config = lire_config_oauth2(chemin_fichier, type)
    if config == None:
        print("erreur")




def lecture_config_cli_owa():
    chemin_fichier = input("📄 nom fichier json ou sec (pas le chemin!) JSON / sec : ").strip()
    config = lire_config_owa(chemin_fichier)

    if config == None:
        print("erreur")
    print(config)


def lire_config_cli_imap4_ssl():
    chemin_fichier = input("📄 nom fichier json ou sec (pas le chemin!) JSON / SEC: ").strip()
    config = lire_config_imap4_ssl(chemin_fichier)

    if config == None:
        print("erreur")
    print(config)


# Gestion clés API          (HARD dossier aait_store/keys)
# Enregistre un fichier JSON {service, api_key_encrypted, description}
def enregistrer_config_api(service_name, api_key, description=""):
    try:
        # Clé « personnelle » (1 octet) et chiffrement XOR
        key = get_user_key()
        api_key_enc = xor_crypt(api_key, key)

        contenu = {
            "service": service_name,
            "api_key_encrypted": api_key_enc,
            "description": description
        }

        chemin_fic = os.path.join(get_keys_dir("API"), f"{service_name}.json")
        with open(chemin_fic, "w", encoding="utf-8") as fp:
            json.dump(contenu, fp, indent=4)

        #print(f"✅ Fichier enregistré : {chemin_fic}")
        #print(get_user_key())
        return 0
    except Exception as e:
        print(f"❌ Erreur d’enregistrement : {e}")
        return 1


def parse_json_and_save_api(config_str: str) -> None:
    raw = config_str.strip()

    # 1️⃣ Parsing initial
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        # 2️⃣ Cas très courant : quotes simples
        if "double quotes" in e.msg.lower():
            try:
                normalized = _normalize_single_quotes_json(raw)
                data = json.loads(normalized)
            except json.JSONDecodeError:
                raise ValueError(
                    "Invalid JSON: use double quotes "
                    '(example: {"service": "xxx"})'
                ) from None
        else:
            raise ValueError(f"Invalid JSON syntax: {e.msg}") from None

    # 3️⃣ Type attendu
    if not isinstance(data, dict):
        raise TypeError("JSON root must be an object")

    # 4️⃣ Champs obligatoires
    required_keys = ("service", "api_key")
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(f"Missing required key(s): {', '.join(missing)}")

    # 5️⃣ Validation stricte
    for key in required_keys:
        if not isinstance(data[key], str):
            raise TypeError(f"'{key}' must be a string")
        if not data[key].strip():
            raise ValueError(f"'{key}' must be a non-empty string")

    # 6️⃣ Champ optionnel
    desc = data.get("description", "")
    if not isinstance(desc, str):
        raise TypeError("'description' must be a string")

    # 7️⃣ Appel sécurisé
    enregistrer_config_api_secure(
        data["service"],
        data["api_key"],
        desc
    )



def parse_json_and_save_ssl(config_str: str) -> None:
    raw = config_str.strip()

    # 1️⃣ Parsing JSON (avec normalisation si quotes simples)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        if "double quotes" in e.msg.lower():
            try:
                normalized = _normalize_single_quotes_json(raw)
                data = json.loads(normalized)
            except json.JSONDecodeError:
                raise ValueError(
                    "Invalid JSON: use double quotes "
                    '(example: {"agent": "xxx"})'
                ) from None
        else:
            raise ValueError(f"Invalid JSON syntax: {e.msg}") from None

    # 2️⃣ Type attendu
    if not isinstance(data, dict):
        raise TypeError("JSON root must be an object")

    # 3️⃣ Champs obligatoires
    required_keys = ("agent", "domain", "password", "interval_second")
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(f"Missing required key(s): {', '.join(missing)}")

    # 4️⃣ Validation des champs string
    for key in ("agent", "domain", "password"):
        if not isinstance(data[key], str):
            raise TypeError(f"'{key}' must be a string")
        if not data[key].strip():
            raise ValueError(f"'{key}' must be a non-empty string")

    # 5️⃣ Validation interval_second
    interval = data["interval_second"]
    if not isinstance(interval, int):
        raise TypeError("'interval_second' must be an integer")
    if interval <= 0:
        raise ValueError("'interval_second' must be > 0")

    # 6️⃣ Champ optionnel
    alias = data.get("alias", "")
    if not isinstance(alias, str):
        raise TypeError("'alias' must be a string")

    # 7️⃣ Appel sécurisé
    enregistrer_config_imap4_ssl_secure(
        agent=data["agent"],
        my_domain=data["domain"],
        password=data["password"],
        interval_second=interval,
        alias=alias,
    )

def parse_json_and_save_nxp(config_str: str) -> int:
    raw = config_str.strip()

    # 1️⃣ Parsing JSON (avec normalisation si quotes simples)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        if "double quotes" in e.msg.lower():
            try:
                normalized = _normalize_single_quotes_json(raw)
                data = json.loads(normalized)
            except json.JSONDecodeError:
                raise ValueError(
                    "Invalid JSON: use double quotes "
                    '(example: {"dossier_node_id": "xxx"})'
                ) from None
        else:
            raise ValueError(f"Invalid JSON syntax: {e.msg}") from None

    # 2️⃣ Type attendu
    if not isinstance(data, dict):
        raise TypeError("JSON root must be an object")

    # 3️⃣ Champs obligatoires
    required_keys = ("dossier_node_id", "serveur", "username", "password")
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(f"Missing required key(s): {', '.join(missing)}")

    # 4️⃣ Validation des champs string obligatoires
    for key in required_keys:
        if not isinstance(data[key], str):
            raise TypeError(f"'{key}' must be a string")
        if not data[key].strip():
            raise ValueError(f"'{key}' must be a non-empty string")

    # 5️⃣ Champ optionnel : description
    description = data.get("description", "")
    if not isinstance(description, str):
        raise TypeError("'description' must be a string")

    # 6️⃣ Appel sécurisé
    return enregistrer_config_nxp_secure(
        dossier_node_id=data["dossier_node_id"],
        serveur=data["serveur"],
        username=data["username"],
        password=data["password"],
        description=description,
    )
# Gestion clés API          (HARD dossier aait_store/keys)
# Enregistre un fichier JSON {service, api_key_encrypted, description}
def enregistrer_config_api_secure(service_name, api_key, description=""):
    try:
        dossier = get_keys_dir("API")
        # Crée le dossier s'il n'existe pas
        if not os.path.exists(dossier):
            os.makedirs(dossier)
        service_name_windows=f"API__{service_name}"


        contenu = {
            "service": service_name,
            "api_key": api_key,
            "description": description
        }
        sm = secret_manager.SecretManager(service_name_windows)
        sm.store(contenu,overwrite=True)
        chemin_fic = os.path.join(get_keys_dir("API"), f"{service_name}.sec")
        open(chemin_fic, "w", encoding="utf-8").close()

        #print(f"✅ Fichier enregistré : {chemin_fic}")
        #print(get_user_key())
        return 0
    except Exception as e:
        print(f"❌ Erreur d’enregistrement : {e}")
        return 1

# Lecture + déchiffrement → dict {"service", "api_key", "description"}
def lire_config_api(service_name):
    chemin_sec = os.path.join(get_keys_dir("API"), f"{service_name}")
    if not service_name.endswith(".sec"):
        chemin_sec += ".sec"
    if os.path.exists(chemin_sec):
        try:
            if service_name.endswith(".sec"):
                service_name=service_name[:-4]
            service=f"API__{service_name}"
            sm = secret_manager.SecretManager(service)
            contenu=sm.load_all()
            return {
                "service": contenu["service"],
                "api_key": contenu["api_key"],
                "description": contenu.get("description", "")
            }


        except Exception as e:
            print(f"❌ Erreur lors de la lecture : {e}")
            return None

    try:
        chemin_fic = os.path.join(get_keys_dir("API"), f"{service_name}")
        if not service_name.endswith(".json"):
            chemin_fic += ".json"
        with open(chemin_fic, "r", encoding="utf-8") as fp:
            contenu = json.load(fp)

        key = get_user_key()
        api_key_plain = xor_crypt(contenu["api_key_encrypted"], key)
        #print(api_key_plain)
        #print(get_user_key())

        return {
            "service": contenu["service"],
            "api_key": api_key_plain,
            "description": contenu.get("description", "")
        }
    except FileNotFoundError:
        print("❌ Fichier introuvable.")
        return None
    except Exception as e:
        print(f"❌ Erreur lors de la lecture : {e}")
        return None


def enregistrer_config_cli_api():
    print("\n📝 Écriture d’une clé API :")
    service = input("🔖 Nom du service : ").strip()
    api_key = input("🔑 Clé API         : ").strip()
    desc = input("✏️  Description      : ").strip()
    store = ask_secure()
    if not store:
        if 0 != enregistrer_config_api(service, api_key, desc):
            print("erreur!")
        return
    if 0 != enregistrer_config_api_secure(service, api_key, desc):
        print("erreur!")


def lire_config_cli_api(service=""):
    if service == "":
        service = input("🔖 Nom du service (ou nom du fichier .sec/.json): ").strip()
    try:
        cfg = lire_config_api(service)
        if cfg is None:
            print("erreur")
            return
        print(f"\n📄 service     : {cfg['service']}")
        print(f"🔑 clé API     : {cfg['api_key']}")
        if cfg['description']:
            print(f"📝 description : {cfg['description']}")
        return cfg['api_key']
    except Exception as e:
        print(f"❌ Erreur lors de la lecture : {e}")
        return None


# Gestion d’éléments de nxp (DOSSIER_NODE_ID, SERVEUR, USERNAME, PASSWORD)  (HARD dossier aait_store/keys)

def enregistrer_config_nxp(
        dossier_node_id: str,
        serveur: str,
        username: str,
        password: str,
        description: str = ""
) -> int:
    try:
        key = get_user_key()
        password_enc = xor_crypt(password, key)

        contenu = {
            "dossier_node_id": dossier_node_id,
            "serveur": serveur,
            "username": username,
            "password_encrypted": password_enc,
            "description": description
        }

        # ⬅️  Ici : plus de "conn_", juste {serveur}.json
        chemin = os.path.join(get_keys_dir("NXP"), f"{serveur}.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(contenu, f, indent=4)

        print(f"✅ Fichier enregistré : {chemin}")
        return 0
    except Exception as e:
        print(f"❌ Erreur d’enregistrement : {e}")
        return 1

def enregistrer_config_nxp_secure(
        dossier_node_id: str,
        serveur: str,
        username: str,
        password: str,
        description: str = ""
) -> int:
    try:
        service_name = f"NXP__{serveur}"
        dossier = get_keys_dir("NXP")
        # Crée le dossier s'il n'existe pas
        if not os.path.exists(dossier):
            os.makedirs(dossier)
        contenu = {
            "dossier_node_id": dossier_node_id,
            "serveur": serveur,
            "username": username,
            "password": password,
            "description": description
        }
        sm = secret_manager.SecretManager(service_name)
        sm.store(contenu,overwrite=True)
        # ⬅️  Ici : plus de "conn_", juste {serveur}.json
        chemin = os.path.join(get_keys_dir("NXP"), f"{serveur}.sec")
        open(chemin, "w", encoding="utf-8").close()

        print(f"✅ Fichier enregistré : {chemin}")
        return 0
    except Exception as e:
        print(f"❌ Erreur d’enregistrement : {e}")
        return 1


def lire_config_nxp(serveur: str) -> dict | None:
    chemin_sec = os.path.join(get_keys_dir("NXP"), f"{serveur}")
    if not serveur.endswith(".sec"):
        chemin_sec += ".sec"
    if os.path.exists(chemin_sec):
        try:
            if serveur.endswith(".sec"):
                serveur=serveur[:-4]
            service=f"NXP__{serveur}"
            sm = secret_manager.SecretManager(service)
            contenu=sm.load_all()
            return {
            "dossier_node_id": contenu["dossier_node_id"],
            "serveur": contenu["serveur"],
            "username": contenu["username"],
            "password": contenu["password"],
            "description": contenu["description"]
        }

        except Exception as e:
            print(f"❌ Erreur lors de la lecture : {e}")
            return None

    try:
        chemin = os.path.join(get_keys_dir("NXP"), f"{serveur}")  # ⬅️ même logique
        if not serveur.endswith(".json"):
            chemin += ".json"
        with open(chemin, "r", encoding="utf-8") as f:
            contenu = json.load(f)

        key = get_user_key()
        password_plain = xor_crypt(contenu["password_encrypted"], key)

        return {
            "dossier_node_id": contenu["dossier_node_id"],
            "serveur": contenu["serveur"],
            "username": contenu["username"],
            "password": password_plain,
            "description": contenu.get("description", "")
        }
    except FileNotFoundError:
        print("❌ Fichier introuvable.")
        return None
    except Exception as e:
        print(f"❌ Erreur de lecture : {e}")
        return None


def enregistrer_config_cli_nxp():
    print("\n📝 Écriture d’une connexion nxp :")
    dossier_node_id = input("📦 DOSSIER_NODE_ID : ").strip()
    serveur = input("🌐 SERVEUR         : ").strip()
    username = input("👤 USERNAME        : ").strip()
    password = getpass.getpass("🔑 PASSWORD        : ").strip()
    description = input("✏️  Description     : ").strip()
    store = ask_secure()
    if not store:
        enregistrer_config_nxp(
            dossier_node_id,
            serveur,
            username,
            password,
            description
        )
        return
    enregistrer_config_nxp_secure(
        dossier_node_id,
        serveur,
        username,
        password,
        description
    )
def delete_secret(type, key):
    base = MetManagement.get_secret_content_dir()
    filename = base+str(type)+"/"+key+".sec"
    file_path = Path(filename)

    if file_path.exists():
        file_path.unlink()
    key_secret=type+"__"+key
    sm = secret_manager.SecretManager(key_secret)
    deleted=sm.clear()
    print("deleted :",deleted)


def lire_config_cli_nxp():
    serveur = input("🌐 SERVEUR : ").strip()  # ⬅️ on demande le serveur
    cfg = lire_config_nxp(serveur)
    if cfg is None:
        print("erreur")
        return
    print(f"\n📄 dossier_node_id : {cfg['dossier_node_id']}")
    print(f"🌐 serveur         : {cfg['serveur']}")
    print(f"👤 username        : {cfg['username']}")
    print(f"🔑 password        : {cfg['password']}")
    if cfg["description"]:
        print(f"📝 description     : {cfg['description']}")

def recreate_all_sec_file():
    base = MetManagement.get_secret_content_dir()
    listing_file=secret_manager.SecretManager.list_services()
    for element in listing_file:
        list_el= element.split("__")
        if len(list_el) != 2:
            continue
        le_type= list_el[0]
        le_key= list_el[1]
        path = Path(base+le_type)
        path.mkdir(parents=True, exist_ok=True)
        file_name=base+le_type+"/"+le_key+".sec"
        if os.path.exists(file_name):
            continue

        open(file_name, "w", encoding="utf-8").close()

        print(f"✅ Fichier enregistré : {file_name}")

if __name__ == "__main__":
    print("add --no-log-tigger")
    print("1) ecrire fichier IMAP4_SSL")
    print("2) dechiffer fichier IMAP4_SSL")
    print("3) Écrire fichier CLÉ API")
    print("4) Déchiffrer fichier CLÉ API")
    print("5) Écrire fichier NXP")
    print("6) Déchiffrer fichier NXP")
    print("7) Écrire fichier Microsoft Exchange (OWA)")
    print("8) Déchiffrer fichier Microsoft Exchange (OWA)")
    print("9) Écrire fichier Microsoft Exchange (OAuth2)")
    print("10) Déchiffrer fichier Microsoft Exchange (OAuth2)")



    choix = input("👉 Que faire ? [1-10] : ").strip()

    if choix == "1":
        enregistrer_config_cli_imap4_ssl()
    elif choix == "2":
        lire_config_cli_imap4_ssl()
    elif choix == "3":
        enregistrer_config_cli_api()
    elif choix == "4":
        lire_config_cli_api()
    elif choix == "5":
        enregistrer_config_cli_nxp()
    elif choix == "6":
        lire_config_cli_nxp()
    elif choix == "7":
        enregistrer_config_cli_owa()
    elif choix == "8":
        lecture_config_cli_owa()
    elif choix == "9":
        enregistrer_config_cli_oauth2()
    elif choix == "10":
        lire_config_cli_oauth2()



    else:
        print("❌ Choix invalide. Réessayez.\n")
