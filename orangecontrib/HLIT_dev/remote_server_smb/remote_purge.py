import os
import shutil
import time



if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import remote_script_launcher

else:
    from orangecontrib.HLIT_dev.remote_server_smb import remote_script_launcher



def delete_folder(folder_path, retries=20, delay=0.2):
    """
    Deletes a folder if it exists, with retries in case of failure.

    :param folder_path: Path of the folder to delete.
    :param retries: Number of times to retry deletion in case of failure.
    :param delay: Delay in seconds between retries.
    """
    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
        print(f"Folder does not exist: {folder_path}")
        return

    for attempt in range(retries):
        try:
            shutil.rmtree(folder_path)  # Recursively deletes the folder
            print(f"Folder deleted: {folder_path}")
            return
        except PermissionError:
            print(f"Attempt {attempt + 1}/{retries}: Permission denied for folder '{folder_path}', retrying...")
        except Exception as e:
            print(f"Attempt {attempt + 1}/{retries}: Error deleting folder '{folder_path}': {e}")

        time.sleep(delay)

    raise RuntimeError(f"Failed to delete folder '{folder_path}' after {retries} attempts.")


def delete_file(file_path, retries=20, delay=0.2):
    """
    Deletes a file if it exists, with retries in case of failure.

    :param file_path: Path of the file to delete.
    :param retries: Number of times to retry deletion in case of failure.
    :param delay: Delay in seconds between retries.
    """
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        print(f"File does not exist: {file_path}")
        return

    for attempt in range(retries):
        try:
            os.remove(file_path)  # Deletes the file
            print(f"File deleted: {file_path}")
            return
        except PermissionError:
            print(f"Attempt {attempt + 1}/{retries}: Permission denied for file '{file_path}', retrying...")
        except Exception as e:
            print(f"Attempt {attempt + 1}/{retries}: Error deleting file '{file_path}': {e}")

        time.sleep(delay)

    raise RuntimeError(f"Failed to delete file '{file_path}' after {retries} attempts.")



def purge_my_instance(enqueue_dir, exchange_dir):
    enqueue_dir=enqueue_dir.replace("\\","/")
    exchange_dir = exchange_dir.replace("\\", "/")
    if enqueue_dir[-1]!="/":
        enqueue_dir+="/"

    if exchange_dir[-1]!="/":
        exchange_dir+="/"
    hwid = remote_script_launcher.get_unique_identifier()

    waiting_file_path = os.path.join(enqueue_dir, f"{hwid}.txt")
    exchange_dir_path=exchange_dir+hwid
    try:
        delete_file(waiting_file_path)
        delete_folder(exchange_dir_path)
    except Exception as e:
        raise e
if __name__ == "__main__":
    purge_my_instance(   "C:/toto_titi/in/","C:/toto_titi/out/")