# Currently active OWS
current_ows = "toto"

def get_current_ows():
    return current_ows
# Currently active OWS id
ptr_current_canvas_main = 0
# List of all OWS
vect_doc_ptr = []  # [path, id, first opening time]

# Vector containing the master external in the order of invocation
# Value is "cmd_line" if it's from the command line, otherwise it's the ID
ptr_master_external_orange = []
