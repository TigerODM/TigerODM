import argparse
import gc
import os

import Orange


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import (MetManagement, shared_variables)
else:
    from orangecontrib.AAIT.utils import (MetManagement, shared_variables)


def get_ow_file_widget():
    """
    This function retrieves the Orange Canvas file widget associated with the main window.
    It iterates through the objects in the garbage collector and identifies the main window,
    then prints information about the associated widgets.
    """
    le_self = None  # Variable to store the main window instance

    # Iterate through the objects in the garbage collector
    for obj in gc.get_objects():
        try:
            if isinstance(obj, Orange.canvas.mainwindow.MainWindow):
                le_self = obj
        except Exception as e:
            print(e)
    return le_self


def get_duplicate_names(only_aait=False):
    """
    This function collects and compares widget names for every Orange Widget Scheme (OWS) in the Orange Canvas.
    It prints information about the widgets and their associations with OWS.
    It identifies duplicate widget names across different OWS and returns a list of tuples containing OWS names
    and sets of duplicate widget names.

    Parameters:
    - only_aait: If True, targets only widgets with category starting with "aait". If False, includes all widgets.

    Returns:
    A list of tuples containing OWS names and sets of duplicate widget names.
    """
    ows_list = []  # List to store OWS names
    widgets_lists = []  # List to store lists of widgets for each OWS

    print("Collecting all widgets for every OWS")
    try:
        for obj in gc.get_objects():
            if isinstance(obj, Orange.canvas.mainwindow.MainWindow):
                ows_name = obj.current_document().path().split("/")[-1]
                ows_list.append(ows_name)
                widgets_list = []

                # Extract information about widgets for the current OWS
                item_dict = obj.scheme_widget._SchemeEditWidget__scheme.widget_manager._OWWidgetManager__item_for_node
                for item in item_dict.items():
                    #widget = item[1].widget  # The widget is the 2nd element of the Tuple
                    widget_name = item[0].title
                    # print("  OWS :", ows_name, "ID :", id(obj))
                    # print("  Widget :", widget)
                    # print("  Widget ID:", id(widget))
                    # print("  Widget name:", widget_name)
                    category = item[0].description.category

                    # Targets only aait widgets or includes all widgets based on the 'only_aait' parameter
                    if category[0:9] == "dev_workflow" or not only_aait:
                        widgets_list.append(widget_name)

                widgets_lists.append(widgets_list)
    except Exception as e:
        print(e)
    all_duplicates = []  # List to store tuples of OWS names and sets of duplicate widget names
    n_ows = len(ows_list)

    # Compare the lists of widgets to find duplicates
    for i in range(n_ows):
        for j in range(i + 1, n_ows):
            ows_1 = ows_list[i]
            ows_2 = ows_list[j]
            widgets_list_1 = widgets_lists[i]
            widgets_list_2 = widgets_lists[j]
            duplicates = set(widgets_list_1) & set(widgets_list_2)

            if duplicates:
                all_duplicates.append((ows_1, ows_2, duplicates))

    return all_duplicates


def get_current_ows_gui(arg_self):
    """
    Returns the Orange Widget Scheme (OWS) object containing the specified widget.

    If the OWS hasn't been named and saved, it forces a save-as operation.

    Parameters:
    - arg_self: The widget for which the OWS is to be retrieved.

    Returns:
    The OWS object containing the widget, or None if not found.
    """
    # print("sys argv0", sys.argv[0])
    # print("arg_self current ows", arg_self)
    widget_id = id(arg_self)
    # print("----> Created Widget ID :", widget_id)

    # Loop over ALL instantiated objects
    try:
        for obj in gc.get_objects():
            # Stop whenever a MainWindow is found (OWS)
            if isinstance(obj, Orange.canvas.mainwindow.MainWindow):
                # Dictionary containing all the existing widgets (inside Tuples)
                item_dict = obj.scheme_widget._SchemeEditWidget__scheme.widget_manager._OWWidgetManager__item_for_node

                for item in item_dict.items():
                    # The widget (object) is the 2nd element of Tuple
                    widget = item[1].widget

                    if id(widget) == widget_id:
                        ows_path = obj.current_document().path()

                        # If the OWS hasn't been named / saved, force save-as
                        if not ows_path:
                            MetManagement.force_save_as(arg_self, target_canvas_id=id(obj))

                        return obj
    except Exception as e:
        print(e)

    return None


def get_current_ows_name_no_gui(arg_self):
    """
    Returns the name of the Orange Widget Scheme (OWS) associated with the specified argument namespace.

    Parameters:
    - arg_self: The argument namespace for which the OWS name is to be retrieved.

    Returns:
    The name of the associated OWS or an empty string if not found.
    """
    try:
        for obj in gc.get_objects():
            if isinstance(obj, argparse.Namespace):
                ows_path = obj.file
                return ows_path
    except Exception as e:
        print(e)

    return ""


def setup_shared_variables(arg_self):
    """
    Setup for shared variables. Should be put at the beginning of __init__ of every aait widget.

    Parameters:
    - arg_self: The instance of the widget where shared variables are being set up.
    """
    # Case where coding a widget outside Orange
    if hasattr(Orange, "canvas") == False:
        arg_self.current_ows = shared_variables.current_ows
        shared_variables.ptr_current_canvas_main = 0
        return

    if hasattr(Orange.canvas, "mainwindow"):
        ows = get_current_ows_gui(arg_self)

        # Retrieve the path of the current Orange Widget Scheme (OWS)
        try:
            ows_path = ows.current_document().path()
        except:
            ows_path = None

        arg_self.current_ows = ows_path
        shared_variables.current_ows = ows_path
        shared_variables.ptr_current_canvas_main = id(ows)
        # Add the [ows_path, id(ows)] pair to the list if not already present
        if [ows_path, id(ows)] not in shared_variables.vect_doc_ptr:
            shared_variables.vect_doc_ptr.append([ows_path, id(ows)])

        # print("all ows", shared_variables.vect_doc_ptr)
        # print("/!\\ shared_variables current doc", shared_variables.current_ows)
    else:
        # Retrieve the path of the current Orange Widget Scheme (OWS) in the absence of GUI
        ows_path = get_current_ows_name_no_gui(arg_self)

        arg_self.current_ows = ows_path
        shared_variables.current_ows = ows_path
        shared_variables.ptr_current_canvas_main = 0
