import os
import shutil
import sys
import time
import zipfile

# traget path
# input path of first_dependancy
# number of package



def get_list_file_to_copy_past(input_path_of_first_dependancy,number_of_sub_package):
    result=[]
    result.append(input_path_of_first_dependancy)
    for i in range(number_of_sub_package):
        if i==0:
            continue
        str_i=str(i+1)
        file_to_use=input_path_of_first_dependancy[:-len(str_i)]+str_i
        parts = file_to_use.split('/')
        segment = parts[-3]
        segment_modif = segment[:-len(str_i)]+str_i
        parts[-3] = segment_modif
        file_to_use = '/'.join(parts)
        result.append(file_to_use)
    result.sort()
    return result

def does_dependancy_need_to_be_installed(target_path_to_check,input_path_of_first_dependancy):
    if os.path.isfile(target_path_to_check):
        return False
    # python_path = sys.executable.replace("\\","/")
    if os.path.isfile(input_path_of_first_dependancy)==False:
        print(input_path_of_first_dependancy)
        return False
    return True
def copier_fichier(source, destination):
    with open(source, 'rb') as fsrc:
        with open(destination, 'wb') as fdst:
            fdst.write(fsrc.read())
# fonction_a_coder pour les copier coller
def copier_dossier(source, destination):

    # Créer le dossier de destination s'il n'existe pas
    os.makedirs(destination, exist_ok=True)
    destination_path = os.path.join(destination, os.path.basename(source))
    # print("1", source)
    # print("2", destination)
    # print(destination_path)

    if os.path.isdir(source):
        print("copy directory not implemented")
        return
    else:
        copier_fichier(source, destination_path)




def unzip_dependancy_if_needed(target_dir,target_path_to_check,input_path_of_first_dependancy,number_of_sub_package=0):
    # print(target_dir)
    # print(target_path_to_check)
    # print(input_path_of_first_dependancy)
    # print(number_of_sub_package)

    if False==does_dependancy_need_to_be_installed(target_path_to_check,input_path_of_first_dependancy):
        return


    if os.name!='nt':
        print("only for windows")
        return

    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
        time.sleep(0.5)
    # print(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    if number_of_sub_package==0:
        file_to_read=os.path.dirname(input_path_of_first_dependancy).replace("\\","/")+"/resum.txt"
        try:
            with open(file_to_read, 'r') as fichier:
                lignes = fichier.readlines()
                if len(lignes) >= 2:
                    number_of_sub_package=int(lignes[1].strip())
                else:
                    return #not enough line
        except FileNotFoundError:
            return # file not found

    list_file = get_list_file_to_copy_past(input_path_of_first_dependancy,number_of_sub_package)
    if len(list_file)!=number_of_sub_package:
        print("number if sub package doesn 't match")
        return
    if os.path.isdir(target_dir)==False:
        print(target_dir)
        print("output dir not exist")
        return False
    if list_file != []:
        for elem in list_file:
            copier_dossier(elem, target_dir)

    list_path_to_unzip=[]
    for filename in list_file:
        list_path_to_unzip.append(target_dir +"/"+ os.path.basename(filename))
    list_path_to_unzip.sort()
    with open(target_dir + '/result.zip', 'ab') as outfile:  # append in binary mode
        for fname in list_path_to_unzip:
            with open(fname, 'rb') as infile:  # open in binary mode also
                outfile.write(infile.read())
                time.sleep(1)

    with zipfile.ZipFile(target_dir + '/result.zip', 'r') as zip_ref:
        zip_ref.extractall(os.path.dirname(target_dir))
    # faire un nu=ouveau liste file avec basemane liste file et target dir
    # Clear useless .zip files
    for filename in list_file:
        file_to_remove=target_dir +"/"+ os.path.basename(filename)
        if os.path.exists(file_to_remove):
            os.remove(file_to_remove)
    if os.path.exists(target_dir + "/result.zip"):
        os.remove(target_dir + "/result.zip")
def get_site_package_path():
    python_path = sys.executable.replace("\\", "/")
    dir_path = os.path.dirname(python_path)
    dir_path = dir_path + "/Lib/site-packages/"
    return dir_path

def get_path_of_OrangeDir():
    python_path = sys.executable.replace("\\","/")
    dir_path = os.path.dirname(python_path)
    return dir_path