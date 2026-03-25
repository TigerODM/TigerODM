import os
import time


def get_unique_identifier():
    """Returns a unique identifier for the computer (HWID)."""
    try:
        import random
        return str(random.randint(100000,1000000000))
        #return str(uuid.getnode())  # Retrieves the hardware address as a unique ID
    except Exception as e:
        raise RuntimeError(f"Failed to get unique identifier: {e}")




# 0 ok
# 1 deja une instruction dans la queue
def create_waiting_file(enqueue_dir, exchange_dir,json_data,hwid,retries=20):
    """
    Creates a file in the enqueue directory with the unique identifier of the machine.
    If the file exists, it retries for up to 20 times before raising an error.
    Then, it waits for a file with the same identifier in the exchange directory.
    """

    enqueue_dir=enqueue_dir.replace("\\","/")
    exchange_dir = exchange_dir.replace("\\", "/")
    if enqueue_dir[-1]!="/":
        enqueue_dir+="/"

    if exchange_dir[-1]!="/":
        exchange_dir+="/"
    if not os.path.isdir(enqueue_dir) or not os.path.isdir(exchange_dir):
        raise ValueError("One or both provided paths are not valid directories.")

    waiting_file_path = os.path.join(enqueue_dir,f"{hwid}.txt")
    exchange_file_path=exchange_dir+hwid+"/ready_to_get_instruction.txt"
    # Try to create the waiting file
    retries = 20
    for _ in range(retries):
        if os.path.exists(waiting_file_path):
            time.sleep(0.2)
        else:
            break
    else:
        raise TimeoutError("Failed to create waiting file: Another instance is already waiting.")

    try:
        with open(waiting_file_path, "w") as f:
            f.write(hwid)
    except Exception as e:
        raise IOError(f"Failed to write waiting file: {e}")
    # Wait for the exchange file (max 10 seconds)
    timeout = 10  # seconds
    start_time = time.time()
    while not os.path.exists(exchange_file_path):
        if time.time() - start_time > timeout:
            raise TimeoutError("Exchange file was not created within the time limit.")
        time.sleep(0.2)



if __name__ == "__main__":

    hwid="coucou"#get_unique_identifier()
    json_data = '[{"ows_path": "toto.ows", "data": [{"num_input": 0, "values": [["col1", "col2"], ["float", "str"], [3, "test"]]}]}]'
    create_waiting_file("C:/toto_titi/in/","C:/toto_titi/out/",json_data,hwid)
