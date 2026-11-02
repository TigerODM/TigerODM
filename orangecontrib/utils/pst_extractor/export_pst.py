import ctypes
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(str(BASE_DIR))

dll = ctypes.WinDLL(str(BASE_DIR / "TigerODMPST.dll"))

dll.pst_reader_version.restype = ctypes.c_char_p

dll.pst_export_to_txt_w.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
dll.pst_export_to_txt_w.restype = ctypes.c_int


def export_pst(pst_file, output_dir):
    pst_file = Path(pst_file).resolve()

    if not pst_file.exists():
        raise FileNotFoundError(f"Fichier introuvable : {pst_file}")


    rc = dll.pst_export_to_txt_w(str(pst_file), str(output_dir))

    if rc < 0:
        raise RuntimeError(f"Erreur export PST, code={rc}")

    print("Nombre de mails exportes ou code erreur:", rc)
    return 

def export_pst_folder(pst_folder):
    pst_folder = Path(pst_folder).resolve()

    if not pst_folder.exists() or not pst_folder.is_dir():
        raise FileNotFoundError(f"Dossier invalide : {pst_folder}")

    pst_files = list(pst_folder.glob("*.pst"))

    if not pst_files:
        raise FileNotFoundError(f"Aucun fichier PST dans : {pst_folder}")

    output_dir = pst_folder / "output_dir"
    output_dir.mkdir(exist_ok=True)

    for pst_file in pst_files:
        try:
            export_pst(pst_file, output_dir)
        except Exception as e:
            print(f"Erreur sur {pst_file} : {e}")

    return output_dir
