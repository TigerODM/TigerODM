import os
import win32com.client
from pathlib import Path
import pathlib
import shutil
import time
import pythoncom
import fitz

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import get_local_store_path,reset_folder
else:
    from orangecontrib.AAIT.utils.MetManagement import get_local_store_path,reset_folder

def enable_long_path(path):
    """Simplifie la gestion des chemins longs sous Windows."""
    return pathlib.Path(r"\\?\\" + str(path))

def convert_pdf_structure(input_dir: str, output_dir: str,ignore_exsting_out_put=False,forceBasicConvertion=False,progress_callback=None):
    """
    return a string with log in  case of error
    Recursively lists all .pdf and .PDF files in the input directory,
    replicates the folder structure in the output directory, and
    creates empty .docx files with the same names.

    Parameters:
    input_dir (str): Path to the input directory containing PDF files.
    output_dir (str): Path to the output directory where DOCX files will be created.
    """
    error_log=""
    if os.name != 'nt':
        error_log="version developped for windows computer "
        return error_log

    nbre_file = 0
    for i, data in enumerate(input_dir):
        input_path = Path(str(input_dir[i]))
        for pdf_file in input_path.rglob("*.pdf"):
            nbre_file += 1

    k = 1
    for i, data in enumerate(input_dir):
        input_path = Path(str(input_dir[i]))
        output_path = Path(str(output_dir[i]))

        if not input_path.exists() or not input_path.is_dir():
            print(f"Error: The input directory '{input_dir}' does not exist or is not a directory.")
            return f"Error: The input directory '{input_dir}' does not exist or is not a directory. "

        for pdf_file in input_path.rglob("*.pdf"):  # Recursively search for .pdf and .PDF files
            print("traitement de ",str(pdf_file))
            relative_path = pdf_file.relative_to(input_path)  # Get relative path from input root
            new_file_path = output_path / relative_path.with_suffix(".docx")  # Change extension to .docx



            if ignore_exsting_out_put:
                if os.path.exists(enable_long_path(str(new_file_path))):
                    print("ignoring",enable_long_path(str(new_file_path)))
                    continue


            if 0!= convert_pdf_with_temp(str(pdf_file),str(new_file_path),forceBasicConvertion):#convert_pdf_with_temp #convert_pdf_to_docx
                if error_log!="":
                    error_log+="\n"
                error_log+="error -> "+str(pdf_file)
                return error_log # a supprimer
            if progress_callback is not None:
                progress_value = float(100 * (k) / nbre_file)
                k += 1
                progress_callback(progress_value)
    # purge temp dir if everithing is ok
    if error_log=="":
        reset_folder(get_local_store_path() + "temp_word_conversion/", attempts=10, delay=0.05, recreate=False)
    return error_log




def convert_pdf_to_docx(pdf_path, docx_path):
    """
    Convertit un fichier PDF en DOCX en utilisant Microsoft Word.

    Args:
        pdf_path (str): Chemin du fichier PDF source.
        docx_path (str): Chemin du fichier DOCX de destination.

    Returns:
        int: 0 si la conversion a réussi, 1 en cas d'échec.
    """
    if not os.path.exists(pdf_path):
        print(f"Erreur : Le fichier {pdf_path} n'existe pas.")
        return 1

    try:
        # Initialiser COM
        pythoncom.CoInitialize()

        # Lancer Word
        word = win32com.client.Dispatch("Word.Application")
        word.DisplayAlerts = 0  # Désactiver les alertes
        word.Visible = True  # Mettre à True pour voir Word en action
        print(f"Conversion de {pdf_path} en {docx_path}...")

        # Ouvrir le PDF en lecture seule
        doc = word.Documents.Open(pdf_path, ReadOnly=True, ConfirmConversions=False)

        # Sauvegarder en DOCX
        doc.SaveAs(docx_path, FileFormat=16)  # 16 = wdFormatDocumentDefault
        doc.Close(False)

        print(f"Conversion réussie : {docx_path}")
        return 0

    except Exception as e:
        print(f"Erreur lors de la conversion : {e}")
        return 1

    finally:
        if 'word' in locals():
            word.Quit()

        # Libérer COM
        pythoncom.CoUninitialize()


def wait_for_file_access(file_path, timeout=10, interval=0.5):
    """
    Attendre que le fichier soit accessible en lecture/écriture.

    Args:
        file_path (str): Chemin du fichier à vérifier.
        timeout (int): Temps max en secondes avant d'abandonner.
        interval (float): Temps d'attente entre chaque vérification.

    Returns:
        bool: True si le fichier est accessible, False sinon.
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        if os.path.exists(file_path) and os.access(file_path, os.R_OK | os.W_OK):
            try:
                with open(file_path, "a"):
                    pass  # Test d'ouverture en écriture
                return True
            except IOError:
                pass

        time.sleep(interval)  # Attendre avant de réessayer

    print(f"Erreur : Le fichier {file_path} est verrouillé ou inaccessible.")
    return False




def is_pdf_a4(pdf_path: str) -> bool:
    """
    Vérifie si toutes les pages du PDF sont au format A4.
    Retourne True si toutes les pages sont en A4, False sinon.
    """
    A4_WIDTH_PTS = 595  # Largeur A4 en points (approx. 210mm)
    A4_HEIGHT_PTS = 842  # Hauteur A4 en points (approx. 297mm)
    TOLERANCE = 5  # Marge de tolérance en points

    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return False

        for page in doc:
            width, height = page.rect.width, page.rect.height
            if not (
                    (abs(width - A4_WIDTH_PTS) <= TOLERANCE and abs(height - A4_HEIGHT_PTS) <= TOLERANCE) or
                    (abs(width - A4_HEIGHT_PTS) <= TOLERANCE and abs(height - A4_WIDTH_PTS) <= TOLERANCE)
            ):
                return False
    except Exception as e:
        print("is A4?",e)
        return False
    return True

def convert_pdf_to_a4(input_pdf, output_pdf):
    try:
        # Dimensions A4 en points
        a4_width, a4_height = fitz.paper_size("a4")
        a3_width, a3_height = fitz.paper_size("a3")
        doc = fitz.open(input_pdf)
        new_doc = fitz.open()

        for page in doc:
            page_w, page_h = page.rect.width, page.rect.height

            # Si la page est déjà en A4 (tolérance de 1 point)
            if abs(page_w - a4_width) < 1 and abs(page_h - a4_height) < 1:
                new_doc.insert_pdf(doc, from_page=page.number, to_page=page.number)
                continue

            # Si la page est déjà en A3 (tolérance de 1 point)
            if abs(page_w - a3_width) < 1 and abs(page_h - a3_height) < 1:
                new_doc.insert_pdf(doc, from_page=page.number, to_page=page.number)
                continue

            # Définition de la transformation selon l'orientation de la page
            if page_w > page_h:  # Paysage
                # Après rotation, les dimensions seront inversées (largeur <-> hauteur)
                effective_scale = min(a4_width / page_h, a4_height / page_w)
                matrix = fitz.Matrix(effective_scale, effective_scale)
                # Rotation de 90° et translation pour repositionner le contenu
                matrix = matrix.prerotate(90).pretranslate(page_h * effective_scale, 0)
            else:  # Portrait
                effective_scale = min(a4_width / page_w, a4_height / page_h)
                matrix = fitz.Matrix(effective_scale, effective_scale)

            # Générer le pixmap à la résolution finale souhaitée
            pix = page.get_pixmap(matrix=matrix)

            # Calcul du centrage sur la page A4
            new_img_w, new_img_h = pix.width, pix.height
            x_offset = (a4_width - new_img_w) / 2
            y_offset = (a4_height - new_img_h) / 2

            # Créer la nouvelle page et y insérer l'image
            new_page = new_doc.new_page(width=a4_width, height=a4_height)
            new_page.insert_image(
                fitz.Rect(x_offset, y_offset, x_offset + new_img_w, y_offset + new_img_h),
                pixmap=pix
            )
        new_doc.save(output_pdf)
        new_doc.close()
        doc.close()
        return 0
    except:
        return 1


def write_two_strings_to_file(file_path: str,string1: str, string2: str):
    """
    Writes two strings to a file, one per line, handling errors gracefully.

    :param string1: The first string to write.
    :param string2: The second string to write.
    :param file_path: The path where the file should be saved.
    """
    try:
        file = open(file_path, 'w', encoding='utf-8')
        file.write(string1 + "\n")
        file.write(string2 )
        print(f"Successfully written to {file_path}")
    except IOError as e:
        print(f"Error writing to file: {e}")
        return 1
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return 1
    finally:
        file.close()
    return 0


def convert_pdf_with_temp(temp_pdf, output_path,forceBasicConvertion=False):
    """
    Copie le PDF source dans un dossier temporaire, le convertit en DOCX,
    puis copie le fichier résultant vers le chemin de sortie spécifié,
    en gérant les chemins longs.
    """
    pdf_path = enable_long_path(os.path.abspath(temp_pdf))
    output_path = enable_long_path(os.path.abspath(output_path))
    output_dir = output_path.parent

    if not pdf_path.exists():
        print(f"Le fichier {pdf_path} n'existe pas.")
        return 1

    # Créer le dossier de sortie s'il n'existe pas
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    try:
        dest_dir = get_local_store_path() + "temp_word_conversion/"
        if 0 != reset_folder(dest_dir, attempts=10, delay=0.05):
            print("impossible to reset " + dest_dir)
            return 1
        # Création du dossier temporaire
        temp_pdf = os.path.join(dest_dir, "input_toto.pdf")
        temp_docx = os.path.join(dest_dir, "input_toto.docx")

        print(dest_dir+"conversion_en_cours.txt")
        print("######################################")
        if 0!=write_two_strings_to_file(dest_dir+"conversion_en_cours.txt",str(pdf_path),str(output_path)):
            print("error writing ",dest_dir+"conversion_en_cours.txt")
            return 1
        # Copie du fichier source vers le dossier temporaire
        shutil.copy2(pdf_path, temp_pdf)
        wait_for_file_access(temp_pdf)
        if forceBasicConvertion==False:
            if is_pdf_a4(temp_pdf)==False:
                temp_pdf2 = os.path.join(dest_dir, "input_totoA4.pdf")
                if 0!=convert_pdf_to_a4(temp_pdf,temp_pdf2):
                    print("erreur au resize du pdf")
                    return 1
                temp_pdf=temp_pdf2
                wait_for_file_access(temp_pdf)
                time.sleep(1)
        result=0
        # Conversion du PDF en DOCX
        for _ in range(4):
            time.sleep(1)
            result = convert_pdf_to_docx(str(temp_pdf), str(temp_docx))
            if result==0:
                break
        if result == 0:
            # Copie du fichier converti vers la destination finale
            shutil.copy2(temp_docx, output_path)
            print(f"recopie réussie : {output_path}")

            # Supprimer les fichiers temporaires après le déplacement
            # if temp_docx.exists():
            #     temp_docx.unlink()
            # if temp_pdf.exists():
            #     temp_pdf.unlink()
            return 0
        else:
            print("Erreur lors de la conversion.")
            return 1

    except Exception as e:
        print(f"Erreur : {e}")
        return 1



