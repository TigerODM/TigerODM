# import os
#
# if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\","/"):
#     from Orange.widgets.orangecontrib.AAIT.utils.tools import change_owcorpus
# else:
#     from orangecontrib.AAIT.utils.tools import change_owcorpus
#
# # if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\","/"):
# #     from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
# #     from Orange.widgets.orangecontrib.AAIT.utils.tools import (
# #         change_owcorpus, concat_splitted_pypi)
# # else:
# #     from orangecontrib.AAIT.utils import MetManagement
# #     from orangecontrib.AAIT.utils.tools import (change_owcorpus,
# #                                                 concat_splitted_pypi)
#
# #concat_splitted_pypi.unzip_dependancy_if_needed(concat_splitted_pypi.get_path_of_OrangeDir()+"/../aait_store",concat_splitted_pypi.get_path_of_OrangeDir()+"/../aait_store/Parameters/requirements.json",concat_splitted_pypi.get_site_package_path()+"aait_store_cut-part_001/input/aait_store.zip.001",16)
# #concat_splitted_pypi.unzip_dependancy_if_needed(MetManagement.get_local_store_path()+"Models/NLP/all-mpnet-base-v2",MetManagement.get_local_store_path()+"Models/NLP/all-mpnet-base-v2/model.safetensors",concat_splitted_pypi.get_site_package_path()+"all-mpnet-base-v2-pypi-part_001/input/all-mpnet-base-v2.zip.001",5)
# #concat_splitted_pypi.unzip_dependancy_if_needed(concat_splitted_pypi.get_path_of_OrangeDir()+"/Lib/site-packages/forall/gpt4all",concat_splitted_pypi.get_path_of_OrangeDir()+"/Lib/site-packages/forall/gpt4all/bin/chat.exe",concat_splitted_pypi.get_site_package_path()+"gpt4all-pypi-part_001/input/gpt4all.zip.001",0)
# change_owcorpus.replace_owcorpus_file()