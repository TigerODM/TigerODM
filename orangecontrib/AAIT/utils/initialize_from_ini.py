import importlib.util
import os
import pickle
from pathlib import Path

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
else:
    from orangecontrib.AAIT.utils import MetManagement


def delete_widget_cache(widget_name=None):
    """WINDOWS COMPATIBLE ONLY.
    This function deletes the cache of a widget, to force it to reload.
    It loads cache as pickle object, and deletes all lines containing the widget name.
    Be careful to put the widget name correctly, as it is case-sensitive. The widgetName is the name of file containing the widget.
    if widgetName is None, it will delete all cache.
    Args:
        widget_name(str): Name of the widget to delete cache of."""
    if os.name != "nt":
        print("only implemented on windows")
        return
    
    appdata_path = Path(os.getenv('LOCALAPPDATA', '')) / "Orange"
    registry_cache_files = []
    for file in appdata_path.rglob("*.pck"):
        if "registry-cache.pck" == file.name:
            registry_cache_files.append(file)
    
    if not registry_cache_files:
        print("No cache files found. Exiting the function.")
        return
            
    print("registry_cache_files: ", registry_cache_files)

    # Comment: Instead of deleting the line of the widget, you can delete the whole cache file.
    # registry_cache_file.unlink()
    for registry_cache_file in registry_cache_files:
        if widget_name is None:
            widget_name = "AAIT\\widgets"
        try:
            with open(registry_cache_file, "rb") as file:
                registry_cache = pickle.load(file)
        except Exception as e:
            print("Error loading registry cache:", e)

        new_dict ={key: registry_cache[key] for key in registry_cache.keys() if widget_name not in key}
        with open(registry_cache_file, "wb") as file:
            pickle.dump(new_dict, file)



def apply_modification_from_python_file(filepath_original_widget):
    """This decorator applies modifications to the class, reading from an external python file.
    This allows user to override or add new methods to the class, without modifying AAIT package.
    Args:
        filepath_original_widget (str): Path of the file where the original widget is defined
    """
    def decorator(cls):
        original_widget_name=filepath_original_widget.replace("\\","/")
        original_widget_name=os.path.basename(original_widget_name)
        # cases without modification
        if len(original_widget_name)<7:
            return cls
        file_to_load=MetManagement.get_widget_extension_path()
        # case dev
        if original_widget_name[:7]=="__dev__":
            original_widget_name=original_widget_name[5:]
        # cases without modification
        if original_widget_name[:2]!="__":
            if original_widget_name[:3]!="POW":
                return cls
            the_dir_the_file = original_widget_name.split("__")
            if len(the_dir_the_file)!=3 and len(the_dir_the_file)!=4:
                return cls
            file_to_load+=the_dir_the_file[-2]+"/"+the_dir_the_file[0]+".py"
        if file_to_load==MetManagement.get_widget_extension_path():# not POW
            original_widget_name=original_widget_name[2:]
            the_dir_the_file=original_widget_name.split("__")
            if len(the_dir_the_file)!=2:
                return cls
            file_to_load+=the_dir_the_file[0]+"/"+the_dir_the_file[1]
        if os.path.isfile(file_to_load)==False:
            return cls
        user_modifications_path=file_to_load
        #print(f"\n - Modification of |{cls.__name__}| based on |{user_modifications_path}|")
        # Load the module dynamically
        try:
            spec = importlib.util.spec_from_file_location("user_modifications", user_modifications_path)
            if spec is not None and spec.loader is not None:
                user_mods = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(user_mods)
            else:
                print("Error loading user modifications from file:", user_modifications_path)
        except Exception as e:
            print("Error loading user modifications from file:", user_modifications_path, e)
            return cls

        try:
            white_list = getattr(user_mods, "white_list")
        except Exception as e:
            print("Error getting white list from user modifications:", e)
            print("attributes:", dir(user_mods))
            raise e
        # after there is changes before nothing
        white_list += ["__init__"]
        #print("white list: ", white_list)
        for attribute in dir(user_mods):
            if attribute in white_list:
                #print("Replacing attribute:", attribute, "with value:", getattr(user_mods, attribute))
                attr_value = getattr(user_mods, attribute)

                if callable(attr_value):
                    # If overriding or adding new methods, use `MethodType` to bind them
                    # Assuming no need to differentiate between new and existing methods
                    # This works for `__init__`, or any other instance method
                    setattr(cls, attribute, attr_value)
                else:
                    # Directly set new class attribute values
                    setattr(cls, attribute, attr_value)

        return cls
    return decorator



