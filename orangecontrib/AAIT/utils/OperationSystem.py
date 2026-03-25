import os
from pathlib import Path
from typing import List
import shutil
import time
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
else:
    from orangecontrib.AAIT.utils import MetManagement



def DeleteFolderlistOrFilelist(paths: list[str]):
    """
    supprime des fichier et des dossier dans la liste
    """
    for p in paths:
        if os.path.exists(p):
            if os.path.isfile(p):
                MetManagement.reset_files([p], attempts=10, delay=0.05)
            elif os.path.isdir(p):
                MetManagement.reset_folder(p, attempts=10, delay=0.05, recreate=False)

def ensure_dirs(paths: List[str]):
    """
    Crée récursivement tous les dossiers donnés dans la liste.
    Ne lève pas d'erreur si le dossier existe déjà.
    Compatible Windows, macOS, Linux.
    """
    for p in paths:
        path = Path(p).expanduser()
        if path.exists() and not path.is_dir():
            continue  # un fichier existe déjà ici, on ne touche pas
        os.makedirs(path, exist_ok=True)

def move_or_rename(src_list: List[str], dst_list: List[str]):
    """
    Déplace ou renomme des fichiers / dossiers.
    - src_list et dst_list doivent avoir la même longueur.
    - Crée les dossiers parents de destination si besoin.
    - Ne produit aucune sortie (fonction silencieuse).
    - Compatible Windows, macOS, Linux.
    """
    if len(src_list) != len(dst_list):
        raise ValueError("Les listes source et destination doivent avoir la même longueur.")

    for src, dst in zip(src_list, dst_list):
        src_path = Path(src).expanduser()
        dst_path = Path(dst).expanduser()

        if not src_path.exists():
            continue  # ignore si le fichier/dossier source n'existe pas

        dst_path.parent.mkdir(parents=True, exist_ok=True)  # crée le dossier parent si besoin
        os.replace(src_path, dst_path)  # déplace ou renomme (remplace si existe)

def copy_and_overwrite(src_list: List[str], dst_list: List[str]):
    """
    Copie des fichiers ou dossiers (récursivement pour les dossiers).
    - src_list et dst_list doivent avoir la même longueur.
    - Crée automatiquement les dossiers parents de destination.
    - Écrase les fichiers existants sans erreur.
    - Fonction silencieuse (aucune sortie console).
    - Compatible Windows, macOS, Linux.
    """
    if len(src_list) != len(dst_list):
        raise ValueError("Les listes source et destination doivent avoir la même longueur.")

    for src, dst in zip(src_list, dst_list):
        src_path = Path(src).expanduser()
        dst_path = Path(dst).expanduser()

        if not src_path.exists():
            continue  # ignore les sources inexistantes

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_dir():
            # Copie récursive du dossier (remplace si déjà présent)
            if dst_path.exists():
                shutil.rmtree(dst_path)
            shutil.copytree(src_path, dst_path)
        else:
            # Copie simple de fichier
            shutil.copy2(src_path, dst_path)

def sleep_seconds(seconds: float):
    """
    Suspend l'exécution pendant 'seconds' secondes.
    Compatible Windows, macOS, Linux.
    """
    if seconds <= 0:
        return
    time.sleep(seconds)

def set_proxy(proxy: str):
    os.environ["http_proxy"] = proxy
    os.environ["https_proxy"] = proxy