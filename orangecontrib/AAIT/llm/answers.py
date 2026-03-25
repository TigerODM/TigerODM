import copy
import os
try:
    import GPUtil #sometimes errors occurs on gpu testing
except:
    pass
import psutil
import ntpath
import platform

from gpt4all import GPT4All
from Orange.data import Domain, StringVariable, Table


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import prompt_management
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
else:
    from orangecontrib.AAIT.llm import prompt_management
    from orangecontrib.AAIT.utils import MetManagement


def check_gpu(model_path, argself):
    """
    Checks if the GPU has enough VRAM to load a model.

    Args:
        model_path (str): Path to the model file.
        argself (OWWidget): OWQueryLLM object.

    Returns:
        bool: True if the model can be loaded on the GPU, False otherwise.
    """
    argself.error("")
    argself.warning("")
    argself.information("")
    argself.can_run = True
    token_weight = 0.13
    if model_path is None:
        argself.use_gpu = False
        return
    if platform.system() != "Windows":
        argself.use_gpu = False
        return
    if not model_path.endswith(".gguf"):
        argself.use_gpu = False
        argself.can_run = False
        argself.error("Model is not compatible. It must be a .gguf format.")
        return
    #  sometimes errors occurs on gpu testing
    try:
        # Calculate the model size in MB with a 1500 MB buffer
        model_size = os.path.getsize(model_path) / (1024 ** 3) * 1000
        model_size += token_weight * int(argself.n_ctx)
        print(f"Required memory: {model_size/1000:.2f}GB")
        # If there is no GPU, set use_gpu to False
        if len(GPUtil.getGPUs()) == 0:
            argself.use_gpu = False
            argself.information("Running on CPU. No GPU detected.")
            return
        # Else
        else:
            # Get the available VRAM on the first GPU
            gpu = GPUtil.getGPUs()[0]
            free_vram = gpu.memoryFree
        # If there is not enough VRAM on GPU
        if free_vram < model_size:
            # Set use_gpu to False
            argself.use_gpu = False
            # Check for available RAM
            available_ram = psutil.virtual_memory().available / 1024 / 1024
            if available_ram < model_size:
                argself.can_run = False
                argself.error(f"Cannot run. Both GPU and CPU are too small for this model (required: {model_size/1000:.2f}GB).")
                return
            else:
                argself.warning(f"Running on CPU. GPU seems to be too small for this model (available: {free_vram/1000:.2f}GB || required: {model_size/1000:.2f}GB).")
                return
        # If there is enough space on GPU
        else:
            try:
                # Load the model and test it
                # model = GPT4All(model_name=model_path, model_path=model_path, n_ctx=int(argself.n_ctx),
                #                 allow_download=False, device="cuda")
                # answer = model.generate("What if ?", max_tokens=3)
                # # If it works, set use_gpu to True
                argself.use_gpu = True
                argself.information("Running on GPU.")
                return
            # If importing Llama and reading the model doesn't work
            except Exception as e:
                # Set use_gpu to False
                argself.use_gpu = False
                argself.warning(f"GPU cannot be used. (detail: {e})")
                return
    except:
        argself.use_gpu = False
        argself.warning("GPU cannot be used.")
        return


def load_model(model_path, use_gpu, n_ctx=10000):
    if os.path.exists(model_path):
        # Load model on CUDA for windows
        if use_gpu and platform.system() == "Windows":
            model = GPT4All(model_name=model_path, model_path=model_path, n_ctx=n_ctx,
                            allow_download=False, device="cuda")
        # Load model on Metal for MacOS
        elif platform.system() == "Darwin":
            model = GPT4All(model_name=model_path, model_path=model_path, n_ctx=n_ctx,
                            allow_download=False)
        # Load model on CPU for others
        else:
            model = GPT4All(model_name=model_path, model_path=model_path, n_ctx=n_ctx,
                            allow_download=False)
        return model

    else:
        print(f"Model could not be found: {model_path} does not exist")
        return


def generate_answers(table, model_path, use_gpu=False, n_ctx=4096, query_parameters=None, workflow_id="", progress_callback=None, argself=None):
    """
    Generates answers using a local LLM for each row in a data table with a "prompt" column.

    This function loads a local LLM model (compatible with GPT4All), applies a prompt template using
    columns "prompt", "system prompt", and "assistant prompt" (if present), and appends the generated
    response as a new meta column to the output table.

    Parameters:
        table (Orange.data.Table): The input data table with at least a "prompt" column.
        model_path (str): Path to the local model file.
        use_gpu (bool): Whether to use GPU (CUDA/Metal) acceleration if available. Default is False.
        n_ctx (int): Context window size for the model. Default is 4096.
        query_parameters (dict): Dictionary containing the generation parameters, such as temperature, top p...
        workflow_id (str): ID for streaming the answer.
        progress_callback (callable, optional): Function to report progress updates.
        argself (object, optional): An object with a `.stop` attribute to support early termination.

    Returns:
        Orange.data.Table or None: A new data table with the generated answers appended to metas,
        or None if an error occurs or the model file doesn't exist.
    """
    # Copy of input data
    data = copy.deepcopy(table)
    attr_dom = list(data.domain.attributes)
    metas_dom = list(data.domain.metas)
    class_dom = list(data.domain.class_vars)

    # Load model
    model = load_model(model_path=model_path, use_gpu=use_gpu, n_ctx=n_ctx)

    # Generation parameters
    if query_parameters is None:
        query_parameters = {"max_tokens": 4096, "temperature": 0.4, "top_p": 0.4, "top_k": 40, "repeat_penalty": 1.15}

    # Generate answers on column named "prompt"
    try:
        rows = []
        for i, row in enumerate(data):
            features = list(data[i])
            metas = list(data.metas[i])
            prompt = row["prompt"].value

            system_prompt = row["system prompt"].value if "system prompt" in data.domain else ""
            assistant_prompt = row["assistant prompt"].value if "assistant prompt" in data.domain else ""

            prompt = prompt_management.apply_prompt_template(model_path, user_prompt=prompt, assistant_prompt=assistant_prompt, system_prompt=system_prompt)
            answer = run_query(prompt, model=model,
                               max_tokens=query_parameters["max_tokens"],
                               temperature=query_parameters["temperature"],
                               top_p=query_parameters["top_p"],
                               top_k=query_parameters["top_k"],
                               repeat_penalty=query_parameters["repeat_penalty"],
                               workflow_id=workflow_id, argself=argself, progress_callback=progress_callback)
            if answer == "":
                answer = f"Error: The answer could not be generated. The model architecture you tried to use it most likely not supported yet.\n\nModel name: {ntpath.basename(model_path)}"
            metas += [answer]
            rows.append(features + metas)
            if progress_callback is not None:
                progress_value = float(100 * (i + 1) / len(data))
                progress_callback((progress_value, "\n\n\n\n"))
            if argself is not None:
                if argself.stop:
                    break
    except ValueError as e:
        print("An error occurred when trying to generate an answer:", e)
        return

    # Generate new Domain to add to data
    answer_dom = [StringVariable("Answer")]

    # Create and return table
    domain = Domain(attributes=attr_dom, metas=metas_dom + answer_dom, class_vars=class_dom)
    out_data = Table.from_list(domain=domain, rows=rows)
    return out_data


class StopCallback:
    def __init__(self, stop_sequences, widget_thread=None):
        self.stop_sequences = stop_sequences
        self.recent_tokens = ""
        self.returning = True  # Store the last valid token before stopping
        self.widget_thread = widget_thread

    def __call__(self, token_id, token):
        # Stop in case thread is stopped
        if self.widget_thread:
            if self.widget_thread.stop:
                return False

        # Stop in case stop word has been met
        if not self.returning:
            return False
        self.recent_tokens += token

        # Check if any stop sequence appears
        for stop_seq in self.stop_sequences:
            if stop_seq in self.recent_tokens:
                self.returning = False  # Stop the generation, but allow the last token

        return True  # Continue generation


def write_tokens_to_file(token: str, workflow_id=""):
    chemin_dossier = MetManagement.get_api_local_folder(workflow_id=workflow_id)
    if os.path.exists(chemin_dossier):
        MetManagement.write_file_time(chemin_dossier + "time.txt")
        filepath = os.path.join(chemin_dossier, "chat_output.txt")
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(token)
            f.flush()


def run_query(prompt, model, max_tokens=4096, temperature=0.4, top_p=0.4, top_k=40, repeat_penalty=1.15,
              workflow_id="", argself=None, progress_callback=None):
    """
    Generates a response from a local LLM model using the given prompt, with support for streaming output
    and optional early stopping.

    The function streams tokens from the model and accumulates them into a full response. It also filters
    out predefined stop sequences from the final answer.

    Parameters:
        prompt (str): The user prompt to send to the model.
        model (GPT4All): The loaded LLM model with a `.generate()` method supporting streaming.
        max_tokens (int): Maximum number of tokens to generate. Default is 4096.
        temperature (float): Sampling temperature for randomness. Lower is more deterministic. Default is 0.
        top_p (float): Top-p (nucleus) sampling value. Default is 0 (disabled).
        top_k (int): Top-k sampling value. Default is 40.
        repeat_penalty (float): Penalty for repeating tokens. Default is 1.15.
        argself (object, optional): Object with a `.stop` attribute to allow interruption during generation.
        progress_callback (callable, optional): Callback function for receiving token-level updates.
            Should accept a tuple like `(None, token)`.

    Returns:
        str: The generated response with stop sequences removed.
    """
    stop_sequences = ["<|endoftext|>", "### User", "<|im_end|>", "<|im_start|>", "<|im_end>", "<im_end|>", "<im_end>"]
    callback_instance = StopCallback(stop_sequences, argself)

    answer = ""
    for token in model.generate(prompt=prompt, max_tokens=max_tokens, temp=temperature, top_p=top_p, top_k=top_k,
                                repeat_penalty=repeat_penalty, streaming=True, callback=callback_instance):
        answer += token
        write_tokens_to_file(token, workflow_id)
        if progress_callback is not None:
            progress_callback((None, token))
        if argself is not None and argself.stop:
            return answer

    # Remove stop sequences from the final answer
    for stop in stop_sequences:
        answer = answer.replace(stop, "")

    return answer


def generate_conversation(table, model, model_path, conversation="", progress_callback=None, argself=None):
    """
    Generates a response using a language model and appends it to a conversation.

    Parameters:
    ----------
    table (Orange.data.Table) Input data table. The first row should contain at least a "prompt" column, and optionally
        "system prompt" and "assistant prompt" columns for context.

    model (GPT4All) : Loaded language model instance, compatible with GPT4All or llama.cpp-style interfaces.

    model_path (str) : Path or name of the model, used for selecting the appropriate prompt template.

    conversation (str, optional) : Existing conversation string to append the new response to. Defaults to an empty string.

    progress_callback (callable, optional) : Callback function for UI updates during generation. Called with progress percentage and message.

    argself (object, optional) : Extra argument passed to `run_query`, typically the widget instance (used for context or settings).

    Returns:
    -------
    Orange.data.Table
        A new Orange Table containing the original input row with two new meta columns:
        - "Answer": the model's generated response.
        - "Conversation": the updated full conversation string.
    """
    if table is None:
        return

    # Copy of input data
    data = copy.deepcopy(table)
    attr_dom = list(data.domain.attributes)
    metas_dom = list(data.domain.metas)
    class_dom = list(data.domain.class_vars)

    features = list(data[0])
    metas = list(data.metas[0])

    # Get data from the first row of the Data Table
    system_prompt = data[0]["system prompt"].value if "system prompt" in data.domain else ""
    assistant_prompt = data[0]["assistant prompt"].value if "assistant prompt" in data.domain else ""
    user_prompt = data[0]["prompt"].value

    # Build prompt based on the model name
    prompt = prompt_management.apply_prompt_template(model_path, user_prompt=user_prompt, assistant_prompt=assistant_prompt, system_prompt=system_prompt)
    answer = run_query(prompt, model=model, argself=argself, progress_callback=progress_callback)
    conversation += "### Assistant :\n\n" + answer + "\n\n\n\n"

    # Add spaces to the widget for following answers
    progress_callback((100, "\n\n\n\n"))

    # Generate new Domain to add to data
    metas += [answer, conversation]
    row = [features + metas]
    answer_dom = [StringVariable("Answer"), StringVariable("Conversation")]

    # Create and return table
    domain = Domain(attributes=attr_dom, metas=metas_dom + answer_dom, class_vars=class_dom)
    out_data = Table.from_list(domain=domain, rows=row)
    return out_data
