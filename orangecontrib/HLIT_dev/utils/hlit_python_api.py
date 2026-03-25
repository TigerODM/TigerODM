import time
import json
import subprocess
import urllib.parse
import sys
import os
if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import subprocess_management
    from Orange.widgets.orangecontrib.HLIT_dev.remote_server_smb import convert
else:
    from orangecontrib.AAIT.utils import subprocess_management
    from orangecontrib.HLIT_dev.remote_server_smb import convert



def start_api_in_new_terminal():
    str_python_path=str(sys.executable.replace("\\","/"))
    if len(str_python_path)>10:
        if str_python_path[-11:].lower()=="pythonw.exe":
            str_python_path=str_python_path[:-11]+"python.exe"


    python_path=f'{str_python_path}'
    # je cherche le chemin en relatif par rapport
    str_path_server_uvicorn=str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"))+"/remote_server_smb/server_uvicorn.py")
    path_server_uvicorn=f'{str_path_server_uvicorn}'
    command=[python_path,path_server_uvicorn,"--autoquit_terminal_if_already_started"]

    try:
        subprocess_management.open_terminal(command, with_qt=True, env=None)
    except Exception as e:
        print(e)
        return 1
    return 0


def call_start_workflow(ip_port: str, key_name: str) -> int:
    """
    Calls a REST API endpoint using curl to start a workflow identified by key_name on the server at ip_port.

    This function is cross-platform (macOS/Windows) and uses subprocess to invoke curl safely.
    It URL-encodes the workflow key, handles various system and network errors,
    and returns 0 if everything went well, or 1 if any error occurred.

    Parameters:
    - ip_port (str): The IP address and port of the target server (e.g. "127.0.0.1:8000")
    - key_name (str): The workflow name to start (e.g. "chatbot basique")

    Returns:
    - int: 0 if success (HTTP 200), 1 otherwise (any failure or non-200 response)
    """

    try:
        # Validate input IP:port format
        if not ip_port or ':' not in ip_port:
            print(f"Error: Invalid IP:port format: {ip_port}", file=sys.stderr)
            return 1

        # URL-encode the workflow key
        encoded_key = urllib.parse.quote(key_name, safe='')

        # Construct the full URL
        url = f"http://{ip_port}/start-workflow/{encoded_key}"

        # Prepare the curl command with safe options
        curl_cmd = [
            "curl","--noproxy", '*', "-X", "GET",
            url,
            "-H", "accept: application/json",
            "--fail",  # return non-zero if HTTP code >= 400
            "--silent",  # suppress output
            "--show-error",  # still show errors if any
            "--write-out", "%{http_code}",  # write only the HTTP status code
            "--output", "-"  # output response body to stdout
        ]

        # Run the curl command and capture output
        result = subprocess.run(curl_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)

        # Check curl execution status
        if result.returncode != 0:
            print(f"Error: curl execution failed: {result.stderr.strip()}", file=sys.stderr)
            return 1

        # Extract HTTP status code from the last 3 characters of output
        http_code = result.stdout[-3:]
        if http_code != "200":
            print(f"Error: Unexpected HTTP response code: {http_code}", file=sys.stderr)
            return 1

        print("Request succeeded with HTTP 200")
        return 0

    except FileNotFoundError:
        # Curl is not installed
        print("Error: curl is not installed on this system.", file=sys.stderr)
    except Exception as e:
        # Any other unexpected error
        print(f"Error: Unexpected exception: {str(e)}", file=sys.stderr)

    return 1




def call_kill_process(ip_port: str, key_name: str) -> int:
    """
    Calls a REST API endpoint using curl to kill a running process identified by key_name on the server at ip_port.

    This function is cross-platform (macOS/Windows) and uses subprocess to invoke curl safely.
    It URL-encodes the process key, handles various system and network errors,
    and returns 0 if everything went well, or 1 if any error occurred.

    Parameters:
    - ip_port (str): The IP address and port of the target server (e.g. "127.0.0.1:8000")
    - key_name (str): The name of the process to kill (e.g. "chatbot basique")

    Returns:
    - int: 0 if success (HTTP 200), 1 otherwise (any failure or non-200 response)
    """

    try:
        # Validate input IP:port format
        if not ip_port or ':' not in ip_port:
            print(f"Error: Invalid IP:port format: {ip_port}", file=sys.stderr)
            return 1

        # URL-encode the process name
        encoded_key = urllib.parse.quote(key_name, safe='')

        # Construct the full URL
        url = f"http://{ip_port}/kill-process/{encoded_key}"

        # Prepare the curl command with safe options
        curl_cmd = [
            "curl","--noproxy", '*', "-X", "GET",
            url,
            "-H", "accept: application/json",
            "--fail",
            "--silent",
            "--show-error",
            "--write-out", "%{http_code}",
            "--output", "-"
        ]
        # Run the curl command and capture output
        result = subprocess.run(curl_cmd, capture_output=True, text=True)

        # Check curl execution status
        if result.returncode != 0:
            print(f"Error: curl execution failed: {result.stderr.strip()}", file=sys.stderr)
            return 1

        # Extract HTTP status code from the last 3 characters of output
        http_code = result.stdout[-3:]
        if http_code != "200":
            print(f"Error: Unexpected HTTP response code: {http_code}", file=sys.stderr)
            return 1

        print("Kill request succeeded with HTTP 200")
        return 0

    except FileNotFoundError:
        print("Error: curl is not installed on this system.", file=sys.stderr)
    except Exception as e:
        print(f"Error: Unexpected exception: {str(e)}", file=sys.stderr)

    return 1


def call_output_workflow(ip_port: str, workflow_id: str,temporisation:float=0.3, out_tab_output=[]) -> int:
    while True:
        res=call_output_workflow_unique(ip_port, workflow_id, out_tab_output)
        if res==1:
            return 1
        if res==0:
            return 0
        #autre cas res == 2 on continue
        time.sleep(temporisation)

def call_output_workflow_unique(ip_port: str, workflow_id: str, out_tab_output=[]) -> int:
    """
    Calls a REST API endpoint using curl to retrieve the output of a workflow identified by key_name
    on the server at ip_port.

    This function is cross-platform (macOS/Windows) and uses subprocess to invoke curl safely.
    It URL-encodes the workflow key, handles various system and network errors,
    and returns 0 if everything went well, or 1 if any error occurred.

    Parameters:
    - ip_port (str): The IP address and port of the target server (e.g. "127.0.0.1:8000")
    - key_name (str): The workflow name to retrieve output for (e.g. "chatbot basique")

    Returns:
    - int: 0 if success (HTTP 200), 2 if servor is wroking, 1 otherwise (any failure or non-200 or 204 response)
    """
    del out_tab_output[:]
    try:
        # Validate input IP:port format
        if not ip_port or ':' not in ip_port:
            print(f"Error: Invalid IP:port format: {ip_port}", file=sys.stderr)
            return 1

        # URL-encode the workflow key
        encoded_key = urllib.parse.quote(workflow_id, safe='')

        # Construct the full URL
        url = f"http://{ip_port}/output-workflow/{encoded_key}"

        # Prepare the curl command with safe options
        curl_cmd = [
            "curl","--noproxy", '*', "-X", "GET",
            url,
            "-H", "accept: application/json",
            "--fail",
            "--silent",
            "--show-error",
            "--write-out", "%{http_code}",
            "--output", "-"
        ]

        # Run the curl command and capture output
        result = subprocess.run(curl_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, encoding="utf-8")
        # Check curl execution status
        if result.returncode != 0:
            print(f"Error: curl execution failed: {result.stderr.strip()}", file=sys.stderr)
            return 1

        # Extract HTTP status code from the last 3 characters of output
        http_code = result.stdout[-3:]
        if http_code == "200":
            print("Output request succeeded with HTTP 200")
            # Parse the JSON response
            try:
                data = json.loads(result.stdout[:-3])
                data_table = convert.convert_json_implicite_to_data_table(data["_result"])
                out_tab_output.append(data_table)
            except json.JSONDecodeError as e:
                print(f"Error: Failed to parse JSON: {str(e)}", file=sys.stderr)
                return 1
            return 0

        if 200 < int(http_code) <= 230:
            #print("server busy try again")
            return 2
        return 1
    except FileNotFoundError:
        print("Error: curl is not installed on this system.", file=sys.stderr)
    except Exception as e:
        print(f"Error: Unexpected exception: {str(e)}", file=sys.stderr)

    return 1




### CUSTOM
def call_output_workflow_unique_2(ip_port: str, workflow_id: str):
    """
    Calls a REST API endpoint using curl to retrieve the output of a workflow identified by key_name
    on the server at ip_port.

    This function is cross-platform (macOS/Windows) and uses subprocess to invoke curl safely.
    It URL-encodes the workflow key, handles various system and network errors,
    and returns 0 if everything went well, or 1 if any error occurred.

    Parameters:
    - ip_port (str): The IP address and port of the target server (e.g. "127.0.0.1:8000")
    - key_name (str): The workflow name to retrieve output for (e.g. "chatbot basique")
    """
    # Validate input IP:port format
    if not ip_port or ':' not in ip_port:
        print(f"Error: Invalid IP:port format: {ip_port}", file=sys.stderr)
        return

    # URL-encode the workflow key
    encoded_key = urllib.parse.quote(workflow_id, safe='')

    # Construct the full URL
    url = f"http://{ip_port}/output-workflow/{encoded_key}"

    # Prepare the curl command with safe options
    curl_cmd = [
        "curl","--noproxy", '*', "-X", "GET",
        url,
        "-H", "accept: application/json",
        "--fail",
        "--silent",
        "--show-error",
        "--write-out", "%{http_code}",
        "--output", "-"
    ]

    # Run the curl command and capture output
    result = subprocess.run(curl_cmd, capture_output=True, text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
    # Check curl execution status
    if result.returncode != 0:
        print(f"Error: curl execution failed: {result.stderr.strip()}", file=sys.stderr)
        return

    # Extract HTTP status code from the last 3 characters of output
    if result:
        json_string = result.stdout[:-3]
        try:
            data = json.loads(json_string)
            return data
        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse JSON: {str(e)}", file=sys.stderr)
            return












def get_timeout_for_workflow(ip_port: str, key_name: str,out_tab_time_out=[]) -> int:
    """
    Calls a REST API endpoint using curl to retrieve the timeout configuration for a specific workflow.

    This function is cross-platform (macOS/Windows) and uses subprocess to invoke curl safely.
    It parses the JSON response, searches for the workflow named key_name,
    and prints the corresponding timeout_daemon value.

    Parameters:
    - ip_port (str): The IP address and port of the target server (e.g. "127.0.0.1:8000")
    - key_name (str): The name of the workflow to search for
    - out_tab_time_out content time out if return =0
    Returns:
    - int:
        0 if success (workflow found and timeout printed),
        2 if workflow name not found,
        1 for any other error (network, parsing, command failure)
    """
    del out_tab_time_out[:]
    try:
        # Validate IP:port format
        if not ip_port or ':' not in ip_port:
            print(f"Error: Invalid IP:port format: {ip_port}", file=sys.stderr)
            return 1

        # Construct the full URL
        url = f"http://{ip_port}/read-config-file-ows-html"

        # Prepare the curl command
        curl_cmd = [
            "curl","--noproxy", '*', "-X", "GET",
            url,
            "-H", "accept: application/json",
            "--fail",
            "--silent",
            "--show-error"
        ]

        # Execute the curl command
        result = subprocess.run(curl_cmd, capture_output=True, text=True)

        # Check curl execution status
        if result.returncode != 0:
            print(f"Error: curl execution failed: {result.stderr.strip()}", file=sys.stderr)
            return 1

        # Parse the JSON response
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse JSON: {str(e)}", file=sys.stderr)
            return 1

        # Ensure 'message' is in response and is a list
        if "message" not in data or not isinstance(data["message"], list):
            print("Error: Invalid response format (missing 'message')", file=sys.stderr)
            return 1

        # Search for the entry matching key_name
        for item in data["message"]:
            if item.get("name") == key_name:
                timeout = item.get("timeout_daemon")
                if not isinstance(timeout, int):
                    print(f"Error: 'timeout_daemon' is not an integer (value: {timeout})", file=sys.stderr)
                    return 1
                out_tab_time_out.append(timeout)
                print(f"timeout_daemon for '{key_name}': {timeout}")
                return 0

        # If key_name not found
        print(f"Error: Workflow with name '{key_name}' not found.", file=sys.stderr)
        return 2

    except FileNotFoundError:
        print("Error: curl is not installed on this system.", file=sys.stderr)
    except Exception as e:
        print(f"Error: Unexpected exception: {str(e)}", file=sys.stderr)

    return 1

def expected_input_for_workflow(ip_port: str, key_name: str,out_tab_input=[]) -> int:
    """
    Calls a REST API endpoint using curl to retrieve the expected input structure for a workflow.

    This function is cross-platform (macOS/Windows) and uses subprocess to invoke curl safely.
    It parses the JSON response, prints the 'expected_input' field, and returns an appropriate status code.

    Parameters:
    - ip_port (str): The IP address and port of the target server (e.g. "127.0.0.1:8000")
    - key_name (str): The name of the workflow (e.g. "chatbot basique")

    Returns:
    - int:
        0 if success and 'expected_input' is printed,
        1 in case of any error (network, parsing, missing field)
    """
    del out_tab_input[:]
    try:
        # Validate IP:port format
        if not ip_port or ':' not in ip_port:
            print(f"Error: Invalid IP:port format: {ip_port}", file=sys.stderr)
            return 1

        # URL encode the key name
        encoded_key = urllib.parse.quote(key_name, safe='')

        # Construct the URL
        url = f"http://{ip_port}/get-worklow-expected-input-output/{encoded_key}"

        # Prepare the curl command
        curl_cmd = [
            "curl","--noproxy", '*', "-X", "GET",
            url,
            "-H", "accept: application/json",
            "--fail",
            "--silent",
            "--show-error"
        ]

        # Run curl
        result = subprocess.run(curl_cmd, capture_output=True, text=True)

        # Check curl execution
        if result.returncode != 0:
            print(f"Error: curl execution failed: {result.stderr.strip()}", file=sys.stderr)
            return 1

        # Parse JSON
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse JSON: {str(e)}", file=sys.stderr)
            return 1

        # Validate presence of expected_input
        if "expected_input" not in data:
            print("Error: 'expected_input' not found in response", file=sys.stderr)
            return 1

        # Print the expected_input content
        out_tab_input.append(json.dumps(data["expected_input"], indent=2))
        return 0

    except FileNotFoundError:
        print("Error: curl is not installed on this system.", file=sys.stderr)
    except Exception as e:
        print(f"Error: Unexpected exception: {str(e)}", file=sys.stderr)

    return 1

def expected_output_for_workflow(ip_port: str, key_name: str,out_tab_output=[]) -> int:
    """
    Calls a REST API endpoint using curl to retrieve the expected output structure for a workflow.

    This function is cross-platform (macOS/Windows) and uses subprocess to invoke curl safely.
    It parses the JSON response, prints the 'expected_input' field, and returns an appropriate status code.

    Parameters:
    - ip_port (str): The IP address and port of the target server (e.g. "127.0.0.1:8000")
    - key_name (str): The name of the workflow (e.g. "chatbot basique")

    Returns:
    - int:
        0 if success and 'expected_input' is printed,
        1 in case of any error (network, parsing, missing field)
    """
    del out_tab_output[:]
    try:
        # Validate IP:port format
        if not ip_port or ':' not in ip_port:
            print(f"Error: Invalid IP:port format: {ip_port}", file=sys.stderr)
            return 1

        # URL encode the key name
        encoded_key = urllib.parse.quote(key_name, safe='')

        # Construct the URL
        url = f"http://{ip_port}/get-worklow-expected-input-output/{encoded_key}"

        # Prepare the curl command
        curl_cmd = [
            "curl","--noproxy", '*', "-X", "GET",
            url,
            "-H", "accept: application/json",
            "--fail",
            "--silent",
            "--show-error"
        ]

        # Run curl
        result = subprocess.run(curl_cmd, capture_output=True, text=True)

        # Check curl execution
        if result.returncode != 0:
            print(f"Error: curl execution failed: {result.stderr.strip()}", file=sys.stderr)
            return 1

        # Parse JSON
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse JSON: {str(e)}", file=sys.stderr)
            return 1

        # Validate presence of expected_input
        if "expected_input" not in data:
            print("Error: 'expected_input' not found in response", file=sys.stderr)
            return 1

        # Print the expected_input content
        out_tab_output.append(json.dumps(data["expected_output"], indent=2))
        return 0

    except FileNotFoundError:
        print("Error: curl is not installed on this system.", file=sys.stderr)
    except Exception as e:
        print(f"Error: Unexpected exception: {str(e)}", file=sys.stderr)

    return 1


def post_input_to_workflow(ip_port: str, data: str) -> int:
    """
    Sends input data to a specific workflow using a POST request with curl.

    This function is cross-platform (macOS/Windows), and uses subprocess to invoke curl safely.
    It expects JSON-formatted string for the 'data' parameter and constructs the body accordingly.

    Parameters:
    - ip_port (str): The IP address and port of the target server (e.g. "127.0.0.1:8000")
    - data (str): A JSON string representing the 'data' block of the request body

    Returns:
    - int:
        0 if the HTTP response code is 200,
        2 if the HTTP response code is 202, and worklow is starting
        1 for any other error or non-expected code
    """

    try:
        # Validate inputs
        if not ip_port or ':' not in ip_port:
            print(f"Error: Invalid IP:port format: {ip_port}", file=sys.stderr)
            return 1

        # Validate and normalize the JSON input
        try:
            # Handle double-encoded strings if needed
            parsed = json.loads(data)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON input: {str(e)}", file=sys.stderr)
            return 1

        # Serialize it back to clean JSON (compact and properly formatted)
        json_payload = json.dumps(parsed)

        url = f"http://{ip_port}/input-workflow"

        curl_cmd = [
            "curl","--noproxy", '*', "-X", "POST",
            url,
            "-H", "accept: application/json",
            "-H", "Content-Type: application/json",
            "--fail",
            "--silent",
            "--show-error",
            "--write-out", "%{http_code}",
            "--output", "-",
            "-d", json_payload
        ]

        # print("###############################")
        # print(curl_cmd)
        # print("###########################")
        # Execute the command
        result = subprocess.run(curl_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)

        # Check for curl execution error
        if result.returncode != 0:
            print(f"Error: curl execution failed: {result.stderr.strip()}", file=sys.stderr)
            return 1

        # Extract HTTP status code
        http_code = result.stdout[-3:]

        if http_code == "200":
            print("POST succeeded with HTTP 200")
            return 0
        elif http_code == "202":
            json_part = result.stdout[:-3]  # Retirer les 3 derniers caractères (le code HTTP)
            response_json = json.loads(json_part)
            message = response_json.get("_message", "")
            if message == "The workflow is already running":
                print("error POST Workflow already running")
                return 1
            #print("POST succeeded with HTTP 202 (accepted)")
            return 2
        else:
            print(f"Error: Unexpected HTTP code: {http_code}", file=sys.stderr)
            return 1

    except FileNotFoundError:
        print("Error: curl is not installed on this system.", file=sys.stderr)
    except Exception as e:
        print(f"Error: Unexpected exception: {str(e)}", file=sys.stderr)

    return 1

def expected_from_max_output(ip_port: str, key_name: str):
    out_tab_input=[]
    exit_code = expected_input_for_workflow(ip_port, key_name, out_tab_input)
    if 0!=exit_code:
        print("error reading expected input")
        return 1
    raw_str = out_tab_input[0]
    raw_str = json.loads(raw_str)
    print(raw_str[0])
    data_input = convert.convert_json_to_orange_data_table(raw_str[0]["data"][0])
    return data_input


def post_and_get_all_routes(ip_port: str, key_name: str,temporisation:float=0.3):
    out_tab_input=[]
    exit_code = expected_input_for_workflow(ip_port, key_name, out_tab_input)
    if 0!=exit_code:
        print("error reading expected input")
        return 1
    raw_str =out_tab_input[0]
    out_tab_time_out=[]
    if 0!=get_timeout_for_workflow(ip_port, key_name,out_tab_time_out):
        print("error reading time out")
        return 1
    time_out=int(out_tab_time_out[0])

    try:
        parsed = json.loads(raw_str)

        for item in parsed:
            workflow_id = item.get("workflow_id")
            if not workflow_id:
                print("Error: 'workflow_id' missing in item.", file=sys.stderr)
                return 1
            item["timeout"] = time_out  # insertion du timeout

            payload=str(json.dumps(item, indent=2, ensure_ascii=False))
            while True:
                error_value=post_input_to_workflow(ip_port, payload)
                if error_value==1:
                    print("erreur during post request -> ",payload)
                    return 1
                time.sleep(temporisation)
                if error_value==2:
                    continue
                if error_value!=0:
                    print("unexpected error then",payload)
                    return 1
                if 0!=call_output_workflow(ip_port, workflow_id,temporisation):
                    print("erreur getting output",workflow_id)
                    return 1
                break

        return 0
    except Exception as e:
        print(f"Erreur : {e}")
        return 1

def daemonizer_with_input_output(input_data, ip_port: str, key_name: str,temporisation:float=0.3, out_tab_output=[]):
    if input_data is None or len(input_data) == 0:
        return
    print("demarrage d orange")
    result=0
    out_tab_input=[]
    exit_code = expected_input_for_workflow(ip_port, key_name, out_tab_input)
    if 0!=exit_code:
        print("error reading expected input")
        return 1
    data = json.loads(out_tab_input[0])
    workflow_id = data[0]["workflow_id"]
    if 0!=call_start_workflow(ip_port,key_name):
        print("error starting workflow key =",key_name)
        return 1

    out_tab_time_out=[]
    if 0!=get_timeout_for_workflow(ip_port, key_name,out_tab_time_out):
        print("error reading time out")
        return 1
    time_out=int(out_tab_time_out[0])
    time.sleep(temporisation)
    input_json = convert.convert_data_table_to_json_explicite(input_data, 0)
    input_json = {"workflow_id": workflow_id, "data": [input_json],"timeout":time_out}
    payload = str(json.dumps(input_json, indent=2, ensure_ascii=False))
    while True:
        error_value = post_input_to_workflow(ip_port, payload)
        if error_value == 1:
            print("erreur during post request -> ", payload)
            return 1
        time.sleep(temporisation)
        if error_value == 2:
            continue
        if error_value != 0:
            print("unexpected error then", payload)
            return 1
        if 0 != call_output_workflow(ip_port, workflow_id, temporisation, out_tab_output):
            print("erreur getting output", key_name)
            return 1
        break
    if 0!=call_kill_process(ip_port,key_name):
        print("error quitting orange",key_name)
        result=1
    return result


def daemonizer_no_input_output(ip_port: str, key_name: str,temporisation:float=0.3):
    print("demarrage d orange")
    result=0
    if 0!=call_start_workflow(ip_port,key_name):
        print("error starting workflow key =",key_name)
        return 1
    time.sleep(temporisation)
    if 0!=post_and_get_all_routes(ip_port,key_name,temporisation):
        print("error post_and_get_all_routes =",key_name)
        result=1
    time.sleep(temporisation)
    if 0!=call_kill_process(ip_port,key_name):
        print("error quitting orange",key_name)
        result=1
    time.sleep(temporisation)
    return result


def exit_server(ip_port: str) -> int:
    """
    Calls the /exit-srv endpoint to request the server to shut down.

    Uses curl via subprocess, compatible with macOS and Windows.
    Returns 0 if HTTP 200, 1 otherwise.

    Parameters:
    - ip_port (str): The IP address and port of the server (e.g. "127.0.0.1:8000")

    Returns:
    - int: 0 if successful (HTTP 200), 1 otherwise
    """

    try:
        if not ip_port or ':' not in ip_port:
            print(f"Error: Invalid IP:port format: {ip_port}", file=sys.stderr)
            return 1

        url = f"http://{ip_port}/exit-srv"

        curl_cmd = [
            "curl","--noproxy", '*', "-X", "GET",
            url,
            "-H", "accept: application/json",
            "--fail",
            "--silent",
            "--show-error",
            "--write-out", "%{http_code}",
            "--output", "-"
        ]

        result = subprocess.run(curl_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            stderr_text = result.stderr.strip()
            # Treat curl (56) as OK (expected if connection is reset after shutdown)
            if "curl: (56) Recv failure: Connection was reset" in stderr_text:
                print("Info: Connection reset (curl 56) — treating as successful shutdown.")
                return 0

            print(f"Error: curl execution failed: {stderr_text}", file=sys.stderr)
            return 1

        http_code = result.stdout[-3:]
        if http_code == "200":
            print("Server shutdown requested successfully (HTTP 200)")
            return 0
        else:
            print(f"Error: Unexpected HTTP code: {http_code}", file=sys.stderr)
            return 1

    except FileNotFoundError:
        print("Error: curl is not installed on this system.", file=sys.stderr)
    except Exception as e:
        print(f"Error: Unexpected exception: {str(e)}", file=sys.stderr)

    return 1

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script_name.py <name>")
        exit(0)
    while True:
        for i in range(len(sys.argv)):
            if i == 0:
                continue
            exit_code = daemonizer_no_input_output("127.0.0.1:8000", sys.argv[i])
            time.sleep(10)

