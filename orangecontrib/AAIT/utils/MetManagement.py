import ctypes  # to call id
import json
import os
import shlex  # pour faire des split qui respectent les ""
import shutil
import subprocess
import sys
from urllib.parse import urlparse
import urllib.parse
from os.path import expanduser
from pathlib import Path
import time
import tempfile
import uuid
import base64
from Orange.data import Table, StringVariable, Domain
import platform



if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import (SimpleDialogQt, aait_repo_file, shared_variables,
                     windows_utils,mac_utils)
else:
    from orangecontrib.AAIT.utils import (SimpleDialogQt, aait_repo_file, shared_variables,
                     windows_utils,mac_utils)


def force_save(self_instance):
    """
    This function forces the save of the currently opened Orange document.
    It utilizes the ctypes library to invoke the save_scheme function of the document.
    It checks if the save is successful and displays an error message if it fails.
    """

    # Initialize the canvas ID to a default value
    canvas_id = -666

    # Iterate through the shared variables to find the document's canvas ID
    for shared_variable in shared_variables.vect_doc_ptr:
        if self_instance.current_ows == shared_variable[0]:
            canvas_id = shared_variable[1]

    # Check if the canvas ID is still the default value, indicating failure to find the document
    if canvas_id == -666:
        print("Unable to save. Document not found.")
        return

    # Use ctypes to invoke the save_scheme function of the document
    save_result = ctypes.cast(canvas_id, ctypes.py_object).value.save_scheme()

    # Check the result of the save operation
    if save_result != 1:
        self_instance.error("Error: You need to save your document.")
        return

    # Clear any previous error messages
    self_instance.error("")


def force_save_as(self_instance, target_canvas_id=None):
    """
    This function forces the save of the currently opened Orange document with a new name. It loops until the save is successful.
    """
    save_result = 0

    # Loop until the save operation is successful
    while save_result != 1:
        self_instance.error("You need to save your document to use AAIT widgets")
        print("You need to save your document to use AAIT widgets")

        # Use ctypes to invoke the save_scheme function of the document
        save_result = ctypes.cast(target_canvas_id, ctypes.py_object).value.save_scheme()

    # Clear any previous error messages
    self_instance.error("")


def replaceAll(file_path, search_exp, replace_exp):
    """
    This function searches and replaces all occurrences of search_exp with replace_exp in a specified file.
    """
    try:
        modified_lines = []  # Create an empty list to store modified lines
        with open(file_path, "r") as file:
            lines = file.readlines()  # Read all lines from the file

        for line in lines:
            if search_exp in line:  # Check if the search expression is present in the line
                line = line.replace(search_exp,
                                    replace_exp)  # Replace the search expression with the replacement expression
            modified_lines.append(line)  # Append the modified line to the list

        print(modified_lines)  # Print the modified lines to the console

        with open(file_path, 'w') as file:
            file.writelines(modified_lines)  # Write the modified lines back to the file

    except Exception as e:
        print(e, file=sys.stderr)  # Print the exception details to standard error
        print("Error in modifying file:", file_path, file=sys.stderr)  # Print an error message to standard error
        return ""  # Return an empty string if there is an error


def current_met_directory(argself):
    """
    This function returns the current save directory for the current Orange document.
    It ensures that the document has been saved and that a save directory exists.
    """
    # Check if the current document is not saved or has an empty name
    if argself.current_ows == "toto" or argself.current_ows == "":
        print("Error: OWS file needs to be saved before using AAIT modules!", file=sys.stderr)

        # Force save the document with a new name
        force_save_as(argself)

        # Update the current document variable
        argself.current_ows = shared_variables.get_current_ows()

        # Recursive call to ensure a valid met directory is obtained
        return current_met_directory(argself)

    # Build the met directory path based on the current document path
    met_dir = argself.current_ows[:-3] + "metdir"

    # Check if the directory already exists
    if os.path.isdir(met_dir):
        return met_dir

    # Try creating the directory
    try:
        os.mkdir(met_dir)
    except Exception as e:
        print(e, file=sys.stderr)
        print("Error in creating directory:", met_dir, file=sys.stderr)
        return ""

    return met_dir


def write_met_file(self_arg, extra_arg_title=[], extra_arg_value=[]):
    """
    This function writes a file in "met" format (configuration) with specified titles and values.
    It checks for consistency between the lists of titles and values.
    """
    # Check for inconsistency in the length of title and value lists
    if len(extra_arg_title) != len(extra_arg_value):
        print("Error: Mismatch in length of arguments [title][value]", file=sys.stderr)
        return 1  # Return 1 to indicate an error

    # Get the current met directory
    met_dir = current_met_directory(self_arg)

    # Check if the met directory is not available
    if met_dir == "":
        # Show a save file window and call the function again
        print("Here, display a save file window and recall the function")
        return 1  # Return 1 to indicate an error

    # Construct the file name using the met directory and the caption title of self_arg
    file_name = met_dir + "/" + self_arg.captionTitle + ".met"

    try:
        with open(file_name, 'w') as file:
            # Write caption, name, and id to the file
            file.write("Caption ")
            file.write('"' + str(self_arg.captionTitle) + '"\n')
            file.write("Name ")
            file.write('"' + str(self_arg.name) + '"\n')
            file.write("Id ")
            file.write('"' + str(id(self_arg)) + '"')

            # Write additional titles and values to the file
            for i in range(len(extra_arg_title)):
                file.write("\n")
                file.write('"' + str(extra_arg_title[i]) + '" "')
                file.write(str(extra_arg_value[i]) + '"')

    except Exception as e:
        print(e, file=sys.stderr)
        print("Error in writing file:", file_name, file=sys.stderr)
        return 1  # Return 1 to indicate an error

    return 0  # Return 0 to indicate success


# 0 ok 1 erreur
def read_met_file_from_caption(self_instance, caption, out_title_list, out_value_list):
    """
    This function reads a "met" file based on a specified caption, extracts titles and values,
    and then stores them in the lists out_title_list and out_value_list.
    """
    # Get the current met directory
    met_directory = current_met_directory(self_instance)

    # Check if the met directory is not valid
    if met_directory == "":
        force_save_as(self_instance)
        # print("End of the attempt")

        # Update the current document variable
        self_instance.current_ows = shared_variables.get_current_ows()

        # Recursive call to ensure a valid met directory is obtained
        return read_met_file_from_caption(self_instance, caption, out_title_list, out_value_list)

    # Build the absolute path to the met file based on the caption
    absolute_path = met_directory + "/" + caption + ".met"

    # Call the function to read the met file from the absolute path
    return read_met_file_from_absolute_path(absolute_path, out_title_list, out_value_list)


def read_met_file_from_absolute_path(file_path, title_list, value_list):
    """
    This function reads a "met" file from its absolute path (file_path), extracts titles and values,
    and then stores them in the lists title_list and value_list.
    """
    lines_to_process = []
    del title_list[:]
    del value_list[:]

    try:
        with open(file_path, 'r') as file:
            lines_to_process = file.readlines()
    except Exception as e:
        print("Error in reading:", file_path, file=sys.stderr)
        print(e)
        return 1

    for i in range(0, len(lines_to_process)):
        cleaned_line = lines_to_process[i].strip()
        split_line = shlex.split(cleaned_line)

        if len(split_line) != 2:
            print("Line not expected:", lines_to_process[i], file=sys.stderr)
            return 1

        title_list.append(split_line[0])

        if len(split_line[1]) > 2:
            if (split_line[1][0] == '"' and split_line[1][-1] == '"'):
                split_line[1] = split_line[1][1:]
                split_line[1] = split_line[1][:-1]

        value_list.append(split_line[1])

    if len(title_list) != len(value_list):
        print("Error: Met file truncated size")
        return 1

    if len(title_list) < 3:
        print("Error: Met file truncated, less than 3 elements")
        return 1

    if title_list[0] != "Caption":
        print("Error: Caption not found in Met file at index 0")
        return 1

    if title_list[1] != "Name":
        print("Error: Name not found in Met file at index 1")
        return 1

    if title_list[2] != "Id":
        print("Error: Id not found in Met file at index 2")
        return 1

    return 0


def get_all_captions(self_instance, include_dict_variable=False):
    """
    This function returns the list of all caption names for "met" files in the current save directory.
    It allows including or excluding "dict_variable" files based on the include_dict_variable parameter.
    """
    # Get the current metm directory
    met_directory = current_met_directory(self_instance)

    # Check if the met directory is not valid
    if met_directory == "":
        print("Put a save file window here and call the function again")
        return 1

    # List to store file captions
    captions_list = []

    # Iterate through the directory
    for file_name in os.listdir(met_directory):
        # Check if the file is a "met" file
        if file_name.endswith('.met'):
            # Check if excluding "dict_variable" files and skip if necessary
            if not include_dict_variable and file_name[:-4] == "dict_variable":
                continue

            # Append the caption name to the list
            captions_list.append(file_name[:-4])

    return captions_list


def get_all_captions_with_specific_class(self_instance, class_name):
    """
    This function returns a list of caption names for "met" files that have a specified class (class_name).
    """
    # Get the list of all captions
    captions_to_study = get_all_captions(self_instance)

    # Check for an error in getting the list of captions
    if type(captions_to_study) is int:
        return []

    result_list = []

    # Check if the list of captions is empty
    if len(captions_to_study) == 0:
        return result_list

    # Iterate through the list of captions
    for caption_element in captions_to_study:
        title_list = []
        value_list = []

        # Read the "met" file and check for errors
        if 0 != read_met_file_from_caption(self_instance, caption_element, title_list, value_list):
            print("Error reading ", caption_element, file=sys.stderr)
            return []

        # Check if the class of the file matches the specified class_name
        if value_list[1] == class_name:
            result_list.append(caption_element)

    return result_list


def get_all_captions_from_specific_ows(ows_path, include_dict_variable=False):
    """
    This function returns the list of all caption names for "met" files in the save directory associated with a specified OWS document.
    """
    # Build the met directory path based on the OWS document path
    met_directory = ows_path[:-3] + "metdir"

    # List to store file captions
    captions_list = []

    # Iterate through the directory
    for file_name in os.listdir(met_directory):
        # Check if the file is a "met" file
        if file_name.endswith('.met'):
            # Check if excluding "dict_variable" files and skip if necessary
            if not include_dict_variable and file_name[:-4] == "dict_variable":
                continue

            # Append the caption name to the list
            captions_list.append(file_name[:-4])

    return captions_list


def get_all_captions_with_specific_class_from_specific_ows(class_name, ows_path):
    """
    This function returns a list of caption names for "met" files that have a specified class (class_name) in the save directory associated with a specified OWS document.
    """
    # Get the list of all captions for the specific OWS document
    captions_to_study = get_all_captions_from_specific_ows(ows_path)

    # Check for an error in getting the list of captions
    if type(captions_to_study) is int:
        return []

    result_list = []

    # Check if the list of captions is empty
    if len(captions_to_study) == 0:
        return result_list

    # Build the met directory path based on the OWS document path
    met_directory = ows_path[:-3] + "metdir"

    # Iterate through the list of captions
    for caption_element in captions_to_study:
        title_list = []
        value_list = []

        # Build the absolute path to the "met" file
        absolute_path = met_directory + "/" + caption_element + ".met"

        # Read the "met" file and check for errors
        if 0 != read_met_file_from_absolute_path(absolute_path, title_list, value_list):
            print("Error reading ", absolute_path, file=sys.stderr)
            return []

        # Check if the class of the file matches the specified class_name
        if value_list[1] == class_name:
            result_list.append(caption_element)

    return result_list


def is_caption_file_exist(self_arg, caption):
    """
    This function checks if a "met" file with a specific caption exists in the current save directory.
    """
    met_dir = current_met_directory(self_arg)

    # Check if the met_dir directory is not available
    if met_dir == "":
        # print("Here, display a save file window and recall the function")
        return 1  # Return 1 to indicate an error

    # Construct the absolute path using the met directory and the caption
    absolute_path = met_dir + "/" + caption + ".met"

    # Check if the file exists at the constructed absolute path
    return os.path.isfile(absolute_path)


def write_local_current_version():
    """"
    This function write local current version
    """
    version="0.0.0.0"# to be changed at each new version
    store_ia_path = expanduser("~")
    store_ia_path=store_ia_path.replace("\\","/")
    store_ia_path+="/aait_store/Parameters"
    # test for none standard path
    none_standard_path = sys.executable.replace("\\", "/")
    none_standard_path = os.path.dirname(none_standard_path)
    none_standard_path = os.path.dirname(none_standard_path)+"/aait_store/"
    if os.path.isfile(none_standard_path+"remote_ressources_path.txt"):
        store_ia_path=none_standard_path+"Parameters"


    version_file=store_ia_path+"/Store_IA.txt"
    try:
        os.makedirs(store_ia_path, exist_ok=True)
        with open(version_file, 'w') as f:
            f.write(version)
            pass
    except:
        SimpleDialogQt.BoxError("error impossible to write file :"+ version_file)
        raise Exception("error impossible to write file :"+ version_file)





def get_local_store_path():
    """
    This function return the IA Store path stocked locally on user computer
    create folder if not exist
    """
    store_ia_path = expanduser("~")
    store_ia_path = store_ia_path.replace("\\", "/")
    store_ia_path += "/aait_store/"

    # test for none standard path
    none_standard_path = sys.executable.replace("\\", "/")
    none_standard_path = os.path.dirname(none_standard_path)
    none_standard_path = os.path.dirname(none_standard_path)+"/aait_store/"




    if os.path.isfile(none_standard_path+"remote_ressources_path.txt"):
        store_ia_path=none_standard_path
    elif  os.path.isdir(none_standard_path):
        try:
            with open(none_standard_path + '/remote_ressources_path.txt', 'w'):
                pass
            store_ia_path=none_standard_path
        except:
            SimpleDialogQt.BoxError("error impossible to write file :" + none_standard_path)
            raise Exception("error impossible to write file :" + none_standard_path)

    if not os.path.exists(store_ia_path):
        # Create a new directory because it does not exist
        os.makedirs(store_ia_path,exist_ok=True)
        # create blanck file with future remote path
        try:
            with open(store_ia_path + '/remote_ressources_path.txt', 'w'):
                pass
        except:
            SimpleDialogQt.BoxError("error impossible to write file :"+ store_ia_path)
            raise Exception("error impossible to write file :"+ store_ia_path)
    return store_ia_path


def get_widget_extension_path():
    local_store_ia = get_local_store_path()
    result=""
    if os.path.exists(local_store_ia+"widget_extention_path.txt"):
        with open(local_store_ia+"widget_extention_path.txt", 'r', encoding='utf-8') as f:
            result=f.readline().strip()
            result.replace("\\", "/")
            if len(result)>1:
                if result[-1]!="/":
                    result=result+"/"
            return result
    if result=="":
        return local_store_ia+"AddOn/PythonExtension/"

def get_category_extension_to_load():
    the_widget_extention_path=get_widget_extension_path()
    if not os.path.isdir(the_widget_extention_path):
        return []
    widget_extention_to_check = [f for f in os.listdir(the_widget_extention_path) if os.path.isdir(os.path.join(the_widget_extention_path, f))]
    result=[]
    for element in widget_extention_to_check:
        path_to_check=the_widget_extention_path+element+"/__init__.py"
        if os.path.isfile(path_to_check):
            result.append(element)
    return result

def set_aait_store_remote_ressources_path(ressource_path):
    """
    Set up remote ressources path of store IA
    """
    if len(ressource_path) == 0:
        return
    ressource_path.replace("\\", "/")
    if is_url(ressource_path):
        path = urlparse(ressource_path).path
        if bool (os.path.splitext(path)[1])==False:
            if os.path.isfile(ressource_path)==False:
                if ressource_path[-1] != "/":
                    ressource_path += "/"

        else:
            if ressource_path.endswith('.aait'):
                temp_url = ressource_path.split("/")[:-1]
                ressource_path = "/".join(temp_url)+"/"

    else :
        if os.path.isfile(ressource_path) == False:
            if ressource_path[-1] != "/":
                ressource_path += "/"
    # check if proposed directory is valid
    try:
        version = get_aait_store_remote_version(ressource_path)
        print("current remote version", version)
    except:
        SimpleDialogQt.BoxError(ressource_path+ " is not a valid remote ressource path")
        print(ressource_path+ " is not a valid remote ressource path")
        return
    store_ia_path = get_local_store_path()
    # writinf local file with directory path
    try:
        with open(store_ia_path + '/remote_ressources_path.txt', 'w') as fp:
            fp.write(ressource_path)
            pass
    except:
        SimpleDialogQt.BoxError("error impossible to write file :"+ store_ia_path + '/remote_ressources_path.txt')
        raise Exception("error impossible to write file :"+ store_ia_path + '/remote_ressources_path.txt')


def get_aait_store_remote_version(ressource_path):
    """
    Return current remote version of store IA
    """
    if is_url(ressource_path):
        version_file = ressource_path + "/Parameters/Store_IA.txt"
    else:
        version_file = os.path.join(ressource_path, "Parameters/Store_IA.txt")

    version = ""
    try:
        if is_url(ressource_path):
            # Télécharger le contenu du fichier à distance
            curl_command = f"curl -s {version_file}"
            process = subprocess.run(curl_command, shell=True, capture_output=True, text=True)

            if process.returncode == 0:  # Vérifie si curl a réussi
                line = process.stdout.splitlines()[0]  # Lire la première ligne
                version = line.split(" ")[-1]
            else:
                raise Exception(f"Error: Unable to fetch file using curl: {version_file}")
        else:
            # Lire le fichier local
            with open(version_file, 'r') as f:
                line = f.readline()
                version = line.split(" ")[-1]
    except Exception as e:
        SimpleDialogQt.BoxError(f"Error: Impossible to read file: {version_file}\n{str(e)}")
        raise Exception(f"Error: Impossible to read file: {version_file}\n{str(e)}")

    print("Version:", version)
    return version


def get_aait_store_remote_ressources_path():
    """
    Get remote ressources path of store IA
    """
    try:
        local_aait_store_path = get_local_store_path()
    except Exception:
        SimpleDialogQt.BoxError("Impossible to open local ia store path")
        raise Exception("Impossible to open local ia store path")

    path_to_read = local_aait_store_path + "remote_ressources_path.txt"
    output_path = ""
    try:
        with open(path_to_read, 'r') as f:
            output_path = f.readline().strip()
            pass
    except:
        SimpleDialogQt.BoxError("error impossible to read file :"+ path_to_read)
        raise Exception("error impossible to read file :"+ path_to_read)
    return output_path



def evolved_json_load(json_data_str):
    """IMPORTANT: This feature is still in progress. If used, be aware that some bugs could happen."""
    print("Using evolved_json_load function. Feature still in progress")
    subcategories = {}
    resolved_data = []
    json_data = json.loads(json_data_str)

    print("json_data_type:", type(json_data))

    # Parse subcategories and create a mapping
    for entry in json_data:
        if "sous_category_name" in entry:
            subcategories[entry["sous_category_name"]] = {
                "workflows": entry.get("workflows", []),
                "extra_datas": entry.get("extra_datas", []),
            }

    # Resolve each entry that references subcategories
    for entry in json_data:
        if "use_sous_category" in entry:
            merged_workflows = entry.get("workflows", [])
            merged_extra_datas = entry.get("extra_datas", [])

            for subcat_name in entry["use_sous_category"]:
                if subcat_name in subcategories:
                    subcat = subcategories[subcat_name]
                    merged_workflows.extend(subcat["workflows"])
                    merged_extra_datas.extend(subcat["extra_datas"])

            # Remove duplicates
            entry["workflows"] = list(set(merged_workflows))
            entry["extra_datas"] = list(set(merged_extra_datas))

        # Append the resolved entry to the resolved_data list
        if "sous_category_name" not in entry:
            if isinstance(entry, str):
                print("WTF: ", entry)
            entry.pop("use_sous_category", None)
            resolved_data.append(entry)
    
    return resolved_data


def IsLocalStoreCompressed(aait_store_path):
    """
    Return the dictionnary of requierment
    """
    return not Path(aait_store_path).is_dir()

def is_url(path_str: str) -> bool:
    """Retourne True si la chaîne ressemble à une URL (http ou https)."""
    parsed = urllib.parse.urlparse(path_str)
    return parsed.scheme in ("http", "https")




def has_listing_signature(url):
    """
    Does a quick GET on 'url' and checks if the body contains
    'Index of' or 'Contenu de'.
    Returns True if it likely is a directory listing,
    otherwise False.
    """
    process_get = subprocess.run(
        ["curl", "-s", "-L", url],
        capture_output=True
    )
    if process_get.returncode != 0:
        return False
    body = process_get.stdout.decode("utf-8", errors="replace").lower()
    return ("index of" in body) or ("contenu de" in body)

def get_aait_store_requirements_json(repo_path=None):
    """
    Return the dictionary of requirements
    :param repo_path: Optional repository path to use instead of the one from the file
    """
    try:
        if repo_path is None:
            aait_store_remote = get_aait_store_remote_ressources_path()
        else:
            aait_store_remote = repo_path
    except:
        SimpleDialogQt.BoxError("no access to ia store resource path")
        raise Exception("no access to ia store resource path")

    if not is_url(aait_store_remote):
        if IsLocalStoreCompressed(aait_store_remote):
            output = aait_repo_file.decode(aait_store_remote, "Parameters/requirements.json")
            if output == None:
                return
            data = evolved_json_load(output)
            return data
    # Cas distant (URL)
    json_path = aait_store_remote + "Parameters/requirements.json"
    if is_url(json_path):
        json_path = aait_store_remote + "/Parameters/requirements.json"
        # Utiliser curl pour récupérer le contenu du fichier distant
        curl_command = f"curl -s {json_path}"
        process = subprocess.run(curl_command, shell=True, capture_output=True, text=True)

        if process.returncode == 0:  # Vérifie si curl a réussi
            try:
                data = evolved_json_load(process.stdout)  # Utiliser stdout pour récupérer la sortie
                print("Données chargées depuis l'URL :", data)
                return data
            except Exception as e:
                SimpleDialogQt.BoxError(f"Error parsing JSON from URL: {json_path}")
                raise Exception(f"Error parsing JSON from URL: {json_path}") from e
        else:
            raise Exception(f"Error: Unable to fetch file using curl: {json_path}")
    else:
        if not Path(json_path).is_file():
            return {}
        try:
            with open(json_path, 'r', encoding='utf-8') as file:
                data = evolved_json_load(file.read())
                return data
        except:
            SimpleDialogQt.BoxError("unable to read"+ json_path)
            raise Exception("unable to read"+ json_path)


def download_aait_store_file_or_directory(server_path: str = "", target: str = "", repo_path: str = None) -> None:
    """
    copy a file/directory from remote to local
    :param server_path: Path to the server directory
    :param target: Target file or directory to download
    :param repo_path: Optional repository path to use instead of the one from the file
    """

    if server_path == "":
        return

    if server_path[-1] == "/":
        server_path = server_path[:-1]

    file_or_directory = server_path +"/"+ target


    try:
        if repo_path is None:
            aait_store_remote = get_aait_store_remote_ressources_path()
        else:
            aait_store_remote = repo_path
    except Exception as e:
        SimpleDialogQt.BoxError("no acces to ia store ressource path")
        print(e)
        raise Exception("no acces to ia store ressource path")

    compressed = False

    # Helper function to check if a string is a URL
    def is_url(path_str):
        parsed = urllib.parse.urlparse(path_str)
        return parsed.scheme in ("http", "https")

    if not compressed:
        if not is_url(aait_store_remote):
            source =  file_or_directory
            output = get_local_store_path() + target

            if already_downloaded(source, output):
                return

            os.makedirs(os.path.dirname(output), exist_ok=True)

            if os.name == 'nt':
                # correction buf sinon on copie C:\toto\titi\ dans C:\tatat\titi\ on obtient C:\tatat\titi\titi ...
                if os.path.isdir(server_path):
                    output=str(Path(output).resolve().parent).replace('\\','/')+"/"
                windows_utils.win32_shellcopy(source, output)
            elif platform.system() == "Darwin":
                if os.path.isdir(server_path):
                    output=str(Path(output).resolve().parent).replace('\\','/')+"/"
                mac_utils.mac_copy_with_anyqt_progress(source, output)

            else:
                #try:
                #    windows_utils.mac_shellcopy(source, output)
                #except Exception as e:
                    #print(e)
                try:
                    dialog_progress = SimpleDialogQt.ProgressDialog(
                        title="Synchronsation please wait",
                        content=f"synchronization of the file {source}\nthis operation may take a few minutes"
                    )
                    dialog_progress.show()
                    if os.path.isfile(source):
                        shutil.copyfile(source, output)
                    else:
                        shutil.copytree(source, output,dirs_exist_ok=True)
                except Exception as e:
                    print(e)
                    raise Exception(f"erreur then copy{source}")

        else:
            # ----- REMOTE URL (non-compressed) -----


            try:
                aait_repo_file.download_from_folder_server(
                    base_url=aait_store_remote,
                    target_subfolder=target,
                    local_dir=get_local_store_path()
                )
            except Exception as e:
                print(e)
                SimpleDialogQt.BoxError(f"Error downloading file from URL: {aait_store_remote}")
                raise Exception(f"Error downloading file from URL: {aait_store_remote}")

        return

def get_size(path):
    """
    Returns the size of the specified file or directory in bytes.

    :param path: Path to the file or directory.
    :return: Size in bytes.
    """
    if os.path.isfile(path):
        return os.path.getsize(path)
    elif os.path.isdir(path):
        return get_dir_size(path)
    else:
        SimpleDialogQt.BoxError("The specified path is neither a file nor a directory"+path)
        raise Exception("The specified path is neither a file nor a directory"+path)

def get_dir_size(directory):
    """
    Returns the total size of all files in a directory in bytes.

    :param directory: Path to the directory.
    :return: Size in bytes.
    """
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(directory):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # Ignore symbolic links
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
    return total_size

def delete_path(path):
    """
    Deletes the specified file or directory.

    :param path: Path to the file or directory to be deleted.
    """
    try:
        if os.path.isfile(path):
            os.remove(path)  # Remove the file
            print(f"File '{path}' has been deleted.")
        elif os.path.isdir(path):
            shutil.rmtree(path)  # Remove the directory and all its contents
            print(f"Directory '{path}' and all its contents have been deleted.")
        else:
            print(f"The path '{path}' does not exist.")
    except Exception as e:
        SimpleDialogQt.BoxError("An error occurred while deleting "+path+"\""+str(e))
        raise("An error occurred while deleting "+path+"\""+str(e))

def already_downloaded(source,output):
    """
    Check if a file need to be downloaded or downloaded again
    based on file size
    remove file if necessary
    """
    # file or directory doesn't exist -> we need to download it

    if not os.path.exists(output):
        return False
    if get_size(source)==get_size(output):
        return True
    # remove output
    print("remove")
    delete_path(output)
    return False

def already_downloaded_compressed(repo_file,file_or_directory,output):
    """
    Check if a file need to be downloaded or downloaded again
    based on file size
    remove file if necessary
    """

    if not os.path.exists(output):
        return False
    output_size=get_size(output)
    input_size=0

    data = json.loads(aait_repo_file.decode(repo_file, "files_info.json"))
    if file_or_directory in data:
        input_size=int(data[file_or_directory])
    else:
        list_of_file = [cle for cle in data if cle.startswith(file_or_directory)]
        for element in list_of_file:
            input_size+=data[element]
    if input_size==output_size:
        return True
    print("remove")
    delete_path(output)
    return False


def already_downloaded_compressed_server(server_repo_url: str, file_or_directory: str, output: str) -> bool:

    """
    Checks whether the file or directory 'file_or_directory', listed on the server
    (described in the JSON file files_info.json), has already been downloaded locally to 'output',
    and if the local size matches the size declared in files_info.json.
    This is done using curl commands (via subprocess).

    :param server_repo_url: Base URL of the server directory,
                            e.g. "http://88.172.137.71:40386/share/ma0UJQ8-jqb9uqiM/"
    :param file_or_directory: Path (or key) representing the file or directory to check,
                              as referenced in the JSON.
    :param output: Local path to the file/directory where it was (or should be) downloaded.
    :return: True if the file/directory is already downloaded and up to date (same size),
             False otherwise.
    """

    # --- 1. Check if 'output' already exists locally
    if not Path(output).exists():
        #print(f"the path {output} doesn't exist locally")
        return False
    # --- 2. Get the local size
    output_size = get_size(output)

    # --- 3. Retrieve the expected size (input_size) from "files_info.json" on the server
    # Build the URL to the JSON file
    json_url = server_repo_url.rstrip('/') + '/files_info.json'

    # Download files_info.json using curl
    # -s : silent mode, -L : follow redirects
    process = subprocess.run(
        ["curl", "-s", "-L", json_url],
        capture_output=True
    )
    if process.returncode != 0:
        # If curl failed (bad URL, DNS error, etc.), display the error and exit
        err_msg = process.stderr.decode('utf-8', errors='replace')
        print(f"Failed to download {json_url}: {err_msg}")
        return False

    data_str = process.stdout.decode('utf-8', errors='replace')
    if not data_str.strip():
        # If the JSON file is empty or inaccessible
        print(f"The content of {json_url} is empty or inaccessible.")
        return False

    # Attempt to parse the JSON
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f"The file {json_url} is not valid JSON: {e}")
        return False

    # --- 4. Compute input_size based on 'file_or_directory'
    input_size = 0
    if file_or_directory in data:
        # Exact key
        input_size = int(data[file_or_directory])
    else:
        # Assume file_or_directory is a directory: sum the sizes of all matching keys
        matching_keys = [k for k in data if k.startswith(file_or_directory)]
        for key in matching_keys:
            input_size += int(data[key])

    # --- 5. Compare
    if input_size == output_size:
        return True
    else:
        # If sizes do not match, remove the local folder to force a new download
        print(f"Local size ({output_size}) does not match the expected size ({input_size}).")
        print("remove")
        delete_path(output)
        return False


def exectute_python_post_install(script_path):
    """
    execute a one time scipt
    """
    try:
        local_aait_store_path = get_local_store_path()
    except Exception:
        SimpleDialogQt.BoxError("Impossible to open local ia store path")
        raise Exception("Impossible to open local ia store path")


    path_to_execute= local_aait_store_path +script_path
    if os.path.isfile(path_to_execute)==False:
        SimpleDialogQt.BoxError(path_to_execute+" not exist")
        raise Exception(path_to_execute+" not exist")

    sys.path.append(os.path.dirname(path_to_execute))
    le_module=__import__(Path(path_to_execute).stem)
    le_module.python_post_install()




def GetFromRemote(name_to_download, repo_if_necessary = None):
    """
    Get files form store ia
    return 0 if ok
    1 if not ok
    """
    if not repo_if_necessary:
        write_local_current_version()

        # Get all repositories from the file
        local_store_path = get_local_store_path()
        path_file = os.path.join(local_store_path, "remote_ressources_path.txt")
        repositories = []

        if os.path.exists(path_file):
            with open(path_file, 'r') as f:
                repositories = [line.strip() for line in f if line.strip()]
        if not repositories:
            SimpleDialogQt.BoxError("No repositories found!")
            return 1

        # Try each repository until we find the package
        for repo in repositories:
            remote_version = get_aait_store_remote_version(repo)
            local_version = get_aait_store_remote_version(get_local_store_path())

            if remote_version != local_version:
                SimpleDialogQt.BoxWarning("you need to update your ia store add on!")
                raise Exception("you need to update your ia store add on!")

            try:
                requirements = get_aait_store_requirements_json(repo_path=repo)

                ia_store_path = repo  # Use repo directly instead of getting it from the file
                delete_temporary_files = False
                downloaded = False

                for element in requirements:
                    if element['name'] != name_to_download:
                        continue


                    downloaded = True

                    for key in ("workflows", "extra_datas", "temporary_files"):
                        if key in element:
                            if key == "temporary_files":
                                delete_temporary_files = True
                            for subpath in element[key]:
                                if not subpath:
                                    continue
                                if not is_url(ia_store_path + "/" + subpath):
                                    download_aait_store_file_or_directory(server_path=ia_store_path, target=subpath, repo_path=repo)
                                else:
                                    download_aait_store_file_or_directory(server_path=ia_store_path, target=subpath, repo_path=repo)

                    if "python_post_install" in element:
                        for script in element["python_post_install"]:
                            if script:
                                exectute_python_post_install(script)

                    if downloaded:
                        if delete_temporary_files:
                            delete_path(get_local_store_path()+"temporary_files")
                        SimpleDialogQt.BoxInfo("Finished!")
                        return 0

            except Exception as e:
                print(e)
                continue
    else:
        write_local_current_version()

        # Get all repositories from the file
        local_store_path = get_local_store_path()
        path_file = os.path.join(local_store_path, "remote_ressources_path.txt")
        repositories = []

        if os.path.exists(path_file):
            with open(path_file, 'r') as f:
                repositories = [line.strip() for line in f if line.strip()]
        if not repositories:
            SimpleDialogQt.BoxError("No repositories found!")
            return 1

        # Try each repository until we find the package
        for repo in repositories:
            remote_version = get_aait_store_remote_version(repo)
            local_version = get_aait_store_remote_version(get_local_store_path())


            if remote_version != local_version:
                SimpleDialogQt.BoxWarning("you need to update your ia store add on!")
                raise Exception("you need to update your ia store add on!")

            try:
                requirements = get_aait_store_requirements_json(repo_path=repo)

                ia_store_path = repo  # Use repo directly instead of getting it from the file
                delete_temporary_files = False
                downloaded = False
                for element in requirements:
                    if element['name'] != name_to_download:
                        continue

                    downloaded = True

                    for key in ("workflows", "extra_datas", "temporary_files"):
                        if key in element:
                            if key == "temporary_files":
                                delete_temporary_files = True
                            for subpath in element[key]:
                                if not subpath:
                                    continue
                                if not is_url(ia_store_path + "/" + subpath):
                                    download_aait_store_file_or_directory(server_path=ia_store_path, target=subpath,
                                                                          repo_path=repo)
                                else:
                                    download_aait_store_file_or_directory(server_path=ia_store_path, target=subpath,
                                                                          repo_path=repo)

                    if "python_post_install" in element:
                        for script in element["python_post_install"]:
                            if script:
                                exectute_python_post_install(script)

                    if downloaded:
                        if delete_temporary_files:
                            delete_path(get_local_store_path() + "temporary_files")
                        SimpleDialogQt.BoxInfo("Finished!")
                        return 0

            except Exception as e:
                print(e)
                continue
            
    SimpleDialogQt.BoxError(f"Package {name_to_download} doesn't exist in any of your stores!")
    return 1

def TransfromPathToStorePath(path_in):
    """
    transform if possible an absolute path to a path relative in the store
    """
    path_in=path_in.replace("\\","/")
    local_store=get_local_store_path()
    if len(local_store)<2:
        return path_in
    if len(path_in)<len(local_store):
        return path_in
    if len(path_in)==len(local_store):
        return path_in
    if path_in[:len(local_store)]==local_store:
        return path_in[len(local_store):]
    return path_in


def TransfromStorePathToPath(path_in):
    """
    transform if possible a path relative in the store to an absolute path to
    """
    path_in=path_in.replace("\\","/")
    if len(path_in)<2:
        return get_local_store_path()+path_in
    if path_in[1]==":":# exemple c:
        return path_in
    if path_in[0]=="/": # exemple /dev or //serveur_name
        return path_in
    return get_local_store_path()+path_in

def getTempDir():
    """
    get temporary dir (available on nt, macosx and gnu/linux
    """
    temp_dir =os.getenv('TMPDIR') or os.getenv('TEMP') or  tempfile
    if temp_dir is None:
        raise "temp dir check not implementing in your OS"
    return str(temp_dir)


def reset_folder(folder_path, attempts=10, delay=0.05,recreate=True):
    """
    Attempts to delete a folder and its contents up to a specified number of times.
    If the folder is successfully deleted, it is then recreated.
    Returns 0 if successful, 1 if deletion fails after all attempts or if recreation fails.
    """
    for _ in range(attempts):
        if os.path.exists(folder_path):
            try:
                shutil.rmtree(folder_path)
                break  # Exit loop if deletion succeeds
            except Exception as e:
                print(f"Failed to delete folder: {e}")
                time.sleep(delay)

    if os.path.exists(folder_path):
        print(f"Failed to delete folder after {attempts} attempts.")
        return 1  # Failure if the folder still exists
    if recreate==False:
        return 0
    try:
        os.makedirs(folder_path, exist_ok=True)
        return 0  # Success
    except Exception as e:
        print(f"Failed to create folder: {e}")
        return 1  # Failure

def reset_files(files, attempts=10, delay=0.05):
    # files [file1,file2,file3]???
    for file in files:
        for _ in range(attempts):
            if os.path.exists(file):
                try:
                    os.remove(file)
                    break  # Exit loop if deletion succeeds
                except Exception as e:
                    print(f"Failed to delete folder: {e}")
                    time.sleep(delay)
        if os.path.exists(file):
            print(f"Failed to delete {file} after {attempts} attempts.")
            return 1  # Failure if the folder still exists
    return 0

def get_api_local_folder(workflow_id=""):
    aait_path = get_local_store_path()
    result=aait_path + "exchangeApi/"
    if workflow_id=="":
        return result
    if len(workflow_id)>4:
        if workflow_id[-4:]==".ows":
            workflow_id=workflow_id[:-4]
    result+=workflow_id+"/"
    return result

def get_api_local_folder_admin():
    return get_api_local_folder()[:-1]+"_adm/"

def get_api_local_folder_admin_locker():
    return get_api_local_folder()[:-1]+"_adm/locker/"

def get_path_linkHTMLWorkflow():
    aait_path = get_local_store_path()
    return aait_path + "Parameters/linkHTMLWorkflow/"

def get_jobs_path():
    aait_path = get_local_store_path()
    return aait_path + "Parameters/jsonJobs/"

def get_path_mailFolder():
    aait_path = get_local_store_path()
    the_path= aait_path + "exchangeMail/"
    if not os.path.exists(the_path):
        os.makedirs(the_path)
    return the_path

def get_secret_content_dir():
    aait_path = get_local_store_path()
    the_path=aait_path+"keys/"
    if not os.path.exists(the_path):
        os.makedirs(the_path)
    return the_path

def get_second_from_1970():
    return int(time.time())

def write_file_time(path):
    time= get_second_from_1970()
    time_ok=path[:-4]+".ok"
    reset_files([time_ok])
    with open(path, "w") as f:
        f.write(str(time))
        f.flush()
    try:
        with open(time_ok, "w"):
            pass
    except Exception as e:
        print(f"Error creating .ok file: {e}")
    return
def write_file_arbitrary_time(path,time):
    time= int(time)
    time_ok=path[:-4]+".ok"
    reset_files([time_ok])
    with open(path, "w") as f:
        f.write(str(time))
        f.flush()
    try:
        with open(time_ok, "w"):
            pass
    except Exception as e:
        print(f"Error creating .ok file: {e}")
    return

def read_file_time(path):
    time_ok = path[:-4] + ".ok"
    for _ in range(100):
        if not os.path.exists(time_ok):
                time.sleep(0.5)
    if  not os.path.exists(time_ok):
        return 0 # time out
    with open(path, "r") as f:
        content = f.read()
    if content.isdigit()==False:
        return int(get_second_from_1970()) # en cas d'erreur on renvoie le temps actuel
    return int(content)

def generate_unique_id_from_mac_timestamp():
    # Récupère l'adresse MAC de la machine (ou un fallback stable si MAC inaccessible)
    mac = uuid.getnode()
    # Temps Unix à la centieme de seconde (précision 0.01s)
    timestamp = int(time.time() * 100)
    # Conversion en octets
    mac_bytes = mac.to_bytes(6, byteorder='big')  # 6 octets = 48 bits
    ts_bytes = timestamp.to_bytes(8, byteorder='big')  # 6 octet je suis large
    # Concaténation binaire + encodage en base64 URL-safe sans padding
    raw_bytes = mac_bytes + ts_bytes
    out= str(base64.b32encode(raw_bytes).decode().rstrip('=').lower())
    return out

def describe_orange_table(data_table):
    """
    Décrit une Orange.data.Table.
    Retour:
      - None en cas d'erreur (mauvais type, exception, etc.)
      - (n_rows, columns) sinon, où:
          n_rows: int, nombre de lignes
          columns: liste de dicts {name, kind, var_type}
                   - kind ∈ {"feature","target","meta"}
                   - var_type ∈ {"StringVariable","ContinuousVariable","Categorical","TimeVariable", ...}
    """
    try:
        if not isinstance(data_table, Table):
            return None

        def var_type_name(var):
            return type(var).__name__         # fallback propre

        n_rows = len(data_table)
        dom = data_table.domain

        cols = []
        # Features
        for v in dom.attributes:
            cols.append({"name": v.name, "kind": "feature", "var_type": var_type_name(v)})
        # Targets (peut être 0, 1 ou plusieurs class_vars)
        for v in dom.class_vars:
            cols.append({"name": v.name, "kind": "target", "var_type": var_type_name(v)})
        # Metas
        for v in dom.metas:
            cols.append({"name": v.name, "kind": "meta", "var_type": var_type_name(v)})

        return n_rows, cols

    except Exception as e:
        print(e)
        return None


def create_trigger_table():
    var = StringVariable("Trigger")
    dom = Domain([], metas=[var])
    table = Table.from_list(domain=dom, rows=[["Trigger"]])
    return table


def ensure_file_exists_recursive(path_holder: list[str]) -> bool:
    """
    Vérifie l'existence d'un fichier.

    - Si le chemin absolu existe → True
    - Sinon, cherche récursivement le fichier dans le dossier parent
      - Si trouvé → met à jour path_holder[0] avec le nouveau chemin absolu → True
      - Sinon → False (sans modifier path_holder)

    Args:
        path_holder (list[str]): liste mutable contenant le chemin absolu du fichier

    Returns:
        bool
    """
    if not path_holder or not path_holder[0]:
        return False

    original_path = Path(path_holder[0])

    # 1️⃣ Cas simple : le fichier existe déjà
    if original_path.is_file():
        return True

    parent_dir = original_path.parent
    filename = original_path.name

    # 2️⃣ Sécurité minimale
    if not parent_dir.is_dir():
        return False

    # 3️⃣ Recherche récursive dans les sous-dossiers
    for found in parent_dir.rglob(filename):
        if found.is_file():
            path_holder[0] = str(found.resolve())
            return True

    # 4️⃣ Rien trouvé → ne pas modifier le chemin
    return False



if __name__ == "__main__":
    # avant faire un bouton
    # set_aait_store_remote_ressources_path(ressource_path)
    # get_aait_store_remote_version("http://88.172.137.71:40386/share/ma0UJQ8-jqb9uqiM/AAIT_v240916")
    #
    # #download_aait_store_file_or_directory("http://88.172.137.71:40386/share/ma0UJQ8-jqb9uqiM/AAIT_v240916")
    # aait_store_remote = get_aait_store_remote_ressources_path()
    # print(aait_store_remote)
    # aait_store_local = get_local_store_path()
    # get_aait_store_requirements_json()
    # aait_store_content = get_aait_store_requirements_json()
    #print(already_downloaded_compressed_server("http://88.172.137.71:40386/share/ma0UJQ8-jqb9uqiM/AAIT_v240916","Models/NLP/all-mpnet-base-v2/config.json",r"C:\Users\timot\aait_store\Models\NLP\all-mpnet-base-v2\config.json"))
    #GetFromRemote("All AI Store")
    #IsStoreCompressed("http://88.172.137.71:40386/share/ma0UJQ8-jqb9uqiM/IFIA_models/repository.aait")
    #set_aait_store_remote_ressources_path("http://88.172.137.71:40386/share/ma0UJQ8-jqb9uqiM/IFIA_models/repository.aait")
    aaa = get_second_from_1970()
    print(aaa)

