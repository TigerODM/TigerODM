import os
import sys
from pathlib import Path


def replace_owcorpus_file():
    if os.name == "nt":
        python_path = sys.executable.replace("\\","/")
        dir_path = os.path.dirname(python_path)
        owcorpus_file_path =dir_path+"/lib/site-packages/orangecontrib/text/widgets/owcorpus.py"
        file_py = Path(owcorpus_file_path)
        file_txt = Path(os.path.dirname(os.path.abspath(__file__)).replace("\\", "/") + "/owcorpus_ok.txt")
        if os.path.exists(dir_path+"/lib/site-packages/orangecontrib/text/widgets")==False:
            return
        size = os.stat(owcorpus_file_path).st_size
        if size != 14559:
            return
        os.remove(owcorpus_file_path)
        contenu = file_txt.read_text()
        file_py.write_text(contenu)
        print(f"{owcorpus_file_path} a été remplacé.")



if __name__ == "__main__":
    replace_owcorpus_file()