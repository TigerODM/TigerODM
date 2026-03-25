import os
from datetime import datetime
import MetManagement as MetManagement
import pandas as pd
# Liste des dossiers à ignorer
ignored_dirs = {".git", ".bin", "lfs", "__pycache__", ".svn", ".hg", "node_modules"}

# Fonction pour récupérer les informations des dossiers spécifiques
def get_dir_info(directory, allowed_dirs, source_label):
    """
    Récupère les informations des dossiers uniquement dans les dossiers spécifiques.

    :param directory: Chemin du dossier à analyser.
    :param allowed_dirs: Liste des sous-dossiers autorisés à analyser.
    :param source_label: Label pour indiquer la source (local ou remote).
    :return: Un dictionnaire contenant les chemins relatifs des dossiers avec leur taille totale et leur date de modification.
    """
    dir_info = {}
    print(f"\nAnalyse des dossiers dans '{source_label}': {directory}")
    print(f"{'Dossier':<70} {'Date modification':<25} {'Taille totale (bytes)':<20}")
    print("-" * 120)

    for root, dirs, files in os.walk(directory):
        # Filtrer les dossiers à ignorer
        dirs[:] = [d for d in dirs if d not in ignored_dirs]

        # Vérifier si le chemin contient l'un des sous-dossiers autorisés
        relative_path = os.path.relpath(root, directory).replace("\\", "/")
        if any(relative_path.startswith(d) for d in allowed_dirs) or relative_path in allowed_dirs:
            # Calculer la taille totale des fichiers dans le dossier
            total_size = sum(os.path.getsize(os.path.join(root, file)) for file in files)
            dir_stats = os.stat(root)

            dir_info[relative_path] = {
                'size': total_size,
                'modified': datetime.fromtimestamp(dir_stats.st_mtime).isoformat()
            }

            print(f"{relative_path:<70} {dir_info[relative_path]['modified']:<25} {dir_info[relative_path]['size']:<20}")

    return dir_info

# Fonction pour comparer les dossiers
def compare_directories(local_dir, shared_dir, allowed_dirs):
    """
    Compare les dossiers en se basant uniquement sur les informations des dossiers.

    :param local_dir: Chemin du dossier local.
    :param shared_dir: Chemin du dossier partagé (remote).
    :param allowed_dirs: Liste des sous-dossiers autorisés à comparer.
    :return: Tuple contenant un booléen (True si différences, False sinon) et un tableau de dossiers avec différences.
    """
    # Récupérer les informations des dossiers pour les deux répertoires
    shared_dirs = get_dir_info(shared_dir, allowed_dirs, "remote")
    local_dirs = get_dir_info(local_dir, allowed_dirs, "local")

    deltas = []

    # Comparer les dossiers partagés avec ceux en local
    print("\nComparaison des dossiers entre remote et local :")
    print(f"{'Dossier':<70} {'Date modif remote':<25} {'Taille remote':<20} {'Date modif locale':<25} {'Taille locale':<20}")
    print("-" * 150)

    for dir_path, shared_info in shared_dirs.items():
        if dir_path in local_dirs:
            local_info = local_dirs[dir_path]
            date_diff = shared_info['modified'] != local_info['modified']
            size_diff = shared_info['size'] != local_info['size']

            # Afficher les détails du dossier
            print(f"{dir_path:<70} {shared_info['modified']:<25} {shared_info['size']:<20} {local_info['modified']:<25} {local_info['size']:<20}")

            # Ajouter à la liste des différences si nécessaire
            if date_diff or size_diff:
                deltas.append(dir_path)
        else:
            # Dossier présent dans le remote mais absent en local
            print(f"{dir_path:<70} {shared_info['modified']:<25} {shared_info['size']:<20} {'Absent':<25} {'Absent':<20}")
            deltas.append(dir_path)

    return (len(deltas) > 0, deltas)

# Sous-dossiers spécifiques à analyser
allowed_dirs = ["AddOn", "Models", "Parameters", "Workflows"]

# Chemins des dossiers local et distant
local_dir = MetManagement.get_local_store_path()
shared_dir = MetManagement.get_aait_store_remote_ressources_path()

# Comparaison des dossiers
has_differences, differences = compare_directories(local_dir, shared_dir, allowed_dirs)

# Afficher le résultat final
print("\nRésultat de la comparaison :")
if not has_differences:
    print("Dossier à jour !")
else:
    print("Les dossiers avec des différences sont :", differences)

# Exporter le résultat vers un fichier Excel si des différences existent
if has_differences:
    print("\nCréation d'un DataFrame pour les dossiers avec des différences...")
    df = pd.DataFrame({'Dossier': differences})
    output_file = "comparison_differences_directories.xlsx"
    print(f"Exportation des résultats dans le fichier Excel : {output_file}...")
    df.to_excel(output_file, index=False)
    print(f"Les résultats de la comparaison ont été enregistrés dans {output_file}.")
