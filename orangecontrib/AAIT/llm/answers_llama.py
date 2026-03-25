import copy
import os
import re
try:
    import GPUtil #sometimes errors occurs on gpu testing
except:
    pass
import psutil
import base64
import ntpath
import platform
from llama_cpp import Llama
try:
    from llama_cpp.llama_chat_format import Qwen3VLChatHandler
except Exception as e:
    print("Missing installs for Qwen3-VL:", e)
    pass
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
    argself.use_gpu = True

    # attention bien faire la suite dans un try exept car gputil peut etre capricieux
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


def count_tokens(model: Llama, text: str) -> int:
    """
    Count the number of tokens in a text, for a chosen model.
    """
    tokens = model.tokenize(text.encode("utf-8"))
    return len(tokens)


def load_model(model_path, use_gpu, n_ctx=10000, k_cache=0, v_cache=0):
    """
    Charge un modèle GGUF avec llama_cpp.Llama.

    - use_gpu=True : tente d'utiliser l'accélération (Metal/CUDA/Vulkan selon build)
      en mettant n_gpu_layers à -1 (= toutes les couches si possible).
    - use_gpu=False : CPU only (n_gpu_layers=0).
    """
    if not os.path.exists(model_path):
        print(f"Model could not be found: {model_path} does not exist")
        return

    try:
        # n_gpu_layers : -1 = toutes les couches si le binaire a un backend GPU (Metal/CUDA/Vulkan)
        n_gpu_layers = -1 if use_gpu else 0

        # n_threads : par défaut tous les cœurs logiques dispo moins 1 (pour avoir l'interface graphique qui ne freeze pas)
        n_threads = max(1, (os.cpu_count()-1 or 1))

        # NOTE : llama_cpp utilise n_ctx pour la taille de contexte
        model = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            # Quelques réglages sûrs
            use_mmap=True,
            use_mlock=False,
            embedding=False,
            verbose=True, #hahahahahaha remettre a False
            type_k=k_cache,
            type_v=v_cache
        )
        return model
    except Exception as e:
        print("Failed to load model with llama_cpp:", e)
        return


def generate_answers(table, model_path, use_gpu=False, n_ctx=4096, query_parameters=None, workflow_id="", progress_callback=None, argself=None):
    """
    Identique en signature/comportement, mais utilise llama_cpp sous le capot.
    """
    # Copie des données d'entrée
    data = copy.deepcopy(table)
    attr_dom = list(data.domain.attributes)
    metas_dom = list(data.domain.metas)
    class_dom = list(data.domain.class_vars)

    # Chargement modèle (llama_cpp)
    if not "Qwen3-VL-8B-Instruct" in model_path:
        model = load_model(model_path=model_path,
                           use_gpu=use_gpu,
                           n_ctx=n_ctx,
                           k_cache=query_parameters["k_cache"],
                           v_cache=query_parameters["v_cache"])
    else:
        model = load_Qwen3VL(model_path=model_path, n_ctx=n_ctx)
    if model is None:
        return None
    # Paramètres de génération par défaut
    if query_parameters is None:
        query_parameters = {"max_tokens": 4096, "temperature": 0.4, "top_p": 0.4, "top_k": 40, "repeat_penalty": 1.15}

    # Génération sur la colonne "prompt"
    try:
        rows = []
        for i, row in enumerate(data):
            features = list(data[i])
            metas = list(data.metas[i])
            prompt = row["prompt"].value

            system_prompt = row["system prompt"].value if "system prompt" in data.domain else ""
            assistant_prompt = row["assistant prompt"].value if "assistant prompt" in data.domain else ""

            # Appliquer ton template existant (inchangé)
            if not "Qwen3-VL-8B-Instruct" in model_path:
                prompt = prompt_management.apply_prompt_template(
                    model_path,
                    user_prompt=prompt,
                    assistant_prompt=assistant_prompt,
                    system_prompt=system_prompt
                )

                prompt = handle_context_length(prompt, model, n_ctx, method="truncate", margin=query_parameters["max_tokens"], progress_callback=progress_callback)

                answer = run_query(
                    prompt,
                    model=model,
                    max_tokens=query_parameters["max_tokens"],
                    temperature=query_parameters["temperature"],
                    top_p=query_parameters["top_p"],
                    top_k=query_parameters["top_k"],
                    repeat_penalty=query_parameters["repeat_penalty"],
                    workflow_id=workflow_id,
                    argself=argself,
                    progress_callback=progress_callback
                )
            else:
                image_paths = [p.strip() for p in row["image paths"].value.split(";")] if "image paths" in data.domain else []
                answer = run_Qwen3VL_query(query=prompt,
                                           image_paths=image_paths,
                                           model=model,
                                           progress_callback=progress_callback)

            if answer == "":
                answer = (
                    "Error: The answer could not be generated. Your prompt might be too long, or the model architecture you tried to use is possibly "
                    f"not supported yet.\n\nModel name: {ntpath.basename(model_path)}"
                )

            thinking = ""
            matches = re.findall(r"<think>[\s\S]*?</think>", answer)
            if matches:
                thinking = matches[0]
                answer = answer.replace(thinking, "").strip()
            metas += [answer, thinking]
            rows.append(features + metas)

            if progress_callback is not None:
                progress_value = float(100 * (i + 1) / len(data))
                progress_callback(("progressBar", progress_value))

            if argself is not None and getattr(argself, "stop", False):
                break
    except Exception as e:
        print("An error occurred when trying to generate an answer:", e)
        return

    # Ajouter la colonne "Answer" en metas
    answer_dom = [StringVariable("Answer"), StringVariable("Thinking")]

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


def run_query(prompt, model, max_tokens=4096, temperature=0, top_p=0, top_k=40, repeat_penalty=1.15,
              workflow_id="", argself=None, progress_callback=None):
    """
    Version llama_cpp avec streaming.
    On garde la même signature et le même contrat de retour.
    """


    # Séquences d'arrêt à filtrer du résultat final
    stop_sequences = ["<|endoftext|>", "### User", "<|im_end|>", "<|im_start|>", "<|im_end>", "<im_end|>", "<im_end>"]
    callback_instance = StopCallback(stop_sequences, argself)

    # Paramètres de sampling mappés vers llama_cpp
    gen_kwargs = dict(
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p if top_p else 1.0,   # top_p=0 désactive → on met 1.0
        top_k=top_k if top_k else 0,     # top_k=0 désactive
        repeat_penalty=repeat_penalty,
        stream=True,
    )

    answer = ""

    # IMPORTANT :
    # - On utilise create_completion (prompt-style) pour rester compatible avec ton templating actuel.
    # - Le générateur renvoie des chunks contenant choices[0].text.
    try:
        stream = model(prompt=prompt, **gen_kwargs)

        for chunk in stream:
            # Récupérer le texte incrémental
            token = chunk["choices"][0].get("text", "")
            if not token:
                continue

            # Callback d'arrêt custom (on simule token_id=None)
            if not callback_instance(None, token):
                # On stoppe proprement le flux (consommation du générateur non nécessaire)
                answer += token  # on peut inclure le dernier token si souhaité
                break

            answer += token
            write_tokens_to_file(token, workflow_id)

            if progress_callback is not None:
                progress_callback(("assistant", token))

            if argself is not None and getattr(argself, "stop", False):
                # Arrêt demandé de l'extérieur
                return answer

    except Exception as e:
        # En cas d'erreur pendant la génération, on retourne ce qu'on a + log
        print("Generation error (llama_cpp):", e)

    # Nettoyage des séquences d'arrêt
    for stop in stop_sequences:
        if stop:
            answer = answer.replace(stop, "")

    return answer


def generate_conversation(table, model, conversation=None, n_ctx=32768, query_parameters=None, workflow_id="", progress_callback=None, argself=None):
    """
    Generates a response using a language model and appends it to a conversation.

    Parameters:
    ----------
    table (Orange.data.Table) Input data table. The first row should contain at least a "prompt" column, and optionally
        "system prompt" and "assistant prompt" columns for context.
    model (Llama) : Loaded language model instance, compatible with GPT4All or llama.cpp-style interfaces.
    widget (OWConverseLLM) : The widget in which to display the conversation.
    conversation (list, optional) : Existing conversation string to append the new response to. Defaults to an empty string.
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

    # Copy the input data
    data = copy.deepcopy(table)
    L = len(data)

    # Get data from the first row of the Data Table
    system_prompt = data[0]["system prompt"].value if "system prompt" in data.domain else ""
    user_prompt = data[0]["prompt"].value
    assistant_prompt = data[0]["assistant prompt"].value if "assistant prompt" in data.domain else ""

    # Get model path to determine prompt template
    model_path = model.model_path

    prompt = ""
    # If the conversation has not started, add a default system prompt
    if not conversation:
        conversation = [{"role": "system", "content": system_prompt}]

    # If the conversation has started, build the complete context
    for message in conversation:
        if message["role"] == "system":
            prompt += prompt_management.apply_system_template(model_path, message["content"])
        elif message["role"] == "user":
            prompt += prompt_management.apply_user_template(model_path, message["content"])
        elif message["role"] == "assistant":
            prompt += prompt_management.apply_assistant_template(model_path, message["content"])

    # Add the current user prompt & assistant prompt
    prompt += prompt_management.apply_user_template(model_path, user_prompt)
    prompt += prompt_management.apply_assistant_template(model_path, assistant_prompt)

    prompt = handle_context_length(prompt, model, n_ctx, method="truncate", margin=query_parameters["max_tokens"], progress_callback=progress_callback)

    # Return progression to fill the user & assistant cards
    progress_callback(("user", user_prompt))
    progress_callback(("assistant", assistant_prompt))

    # Append the user message to the conversation
    conversation.append({"role": "user", "content": user_prompt})

    # Generate the answer
    answer = run_query(prompt,
                       model=model,
                       max_tokens=query_parameters["max_tokens"],
                       temperature=query_parameters["temperature"],
                       top_p=query_parameters["top_p"],
                       top_k=query_parameters["top_k"],
                       repeat_penalty=query_parameters["repeat_penalty"],
                       workflow_id=workflow_id,
                       argself=argself,
                       progress_callback=progress_callback)

    # Split the thinking block and remove it from the answer
    think_text, final_answer = split_think(answer=answer)

    # Append the answer to the conversation
    conversation.append({"role": "assistant", "content": assistant_prompt + final_answer})

    # End of the progress bar
    progress_callback(("progressBar", 100))

    # Padding to add columns to the table, TEMPORARY # TODO : process the entire table for conversation
    rows_answer = [final_answer]
    rows_answer += [""] * (L - len(rows_answer))
    rows_think = [think_text]
    rows_think += [""] * (L - len(rows_think))
    conv_text = ""
    for message in conversation:
        if message["role"] == "system":
            conv_text += f"# System:\n{message['content']}\n\n"
        elif message["role"] == "user":  # Changé en elif
            conv_text += f"# User:\n{message['content']}\n\n"
        elif message["role"] == "assistant":
            conv_text += f"# Assistant:\n{message['content']}\n\n"
    rows_conv = [conv_text]
    rows_conv += [""] * (L - len(rows_conv))

    # Generate new Domain to add to data
    var_answer = StringVariable("Answer")
    var_conversation = StringVariable("Conversation")
    var_think = StringVariable("Think")

    # Add columns to the table
    data = data.add_column(var_answer, rows_answer, to_metas=True)
    data = data.add_column(var_conversation, rows_conv, to_metas=True)
    data = data.add_column(var_think, rows_think, to_metas=True)

    return data, conversation


def split_think(answer: str):
    # Extract think content (if any)
    think_match = re.search(r"<think>(.*?)</think>", answer, flags=re.DOTALL)
    think_text = think_match.group(1).strip() if think_match else ""
    # Remove think block from the final answer
    final_answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
    return think_text, final_answer


def handle_context_length(prompt, model, n_ctx, method="truncate", margin=0, progress_callback=None):
    """
    Truncate a prompt to fit within n_ctx tokens, leaving margin for generation.
    Safely handles edge cases where limit <= 0.
    """
    # Keep a margin for generated tokens
    limit = max(n_ctx - margin, 0)  # clamp to at least 0

    if method == "truncate":
        tokens = model.tokenize(prompt.encode("utf-8"))  # pass string, not bytes
        initial_length = len(tokens)
        if initial_length > limit:
            # take last `limit` tokens safely
            tokens = tokens[-limit:] if limit > 0 else []
            truncated_length = len(tokens)
            prompt = model.detokenize(tokens).decode("utf-8") if tokens else ""
            if progress_callback:
                warning = (
                    f"Complete prompt contains {initial_length} tokens - context limit is {limit} (Context length - Max tokens). "
                    f"The {truncated_length} last tokens have been kept in the prompt."
                )
                progress_callback(("warning", warning))
        return prompt
    elif method == "summarize":
        pass
    else:
        return prompt



# For pure display
def conversation_to_text(conversation):
    if not conversation:
        return ""
    else:
        pass #TODO



def load_Qwen3VL(model_path, n_ctx=32768):
    folder = os.path.dirname(model_path)
    mmproj_path = os.path.join(folder, "mmproj-Qwen3-VL-8B-Instruct-F16.gguf")
    if not os.path.exists(mmproj_path):
        print("Something is wrong with your model : couldn't find mmproj-Qwen3-VL-8B-Instruct-F16.gguf")
        return None
    chat_handler = Qwen3VLChatHandler(clip_model_path=mmproj_path)
    model = Llama(model_path=model_path,
                  chat_handler=chat_handler,
                  n_ctx=n_ctx,
                  n_gpu_layers=-1)
    return model


def run_Qwen3VL_query(query, image_paths, model, system_prompt=" ", progress_callback=None):
    image_messages = []
    for image_path in image_paths:
        data_uri = convert_to_uri(image_path)
        if not data_uri.startswith("data"):
            progress_callback(("error", data_uri))
            return "The image could not be processed"
        image_messages.append({"type": "image_url", "image_url": {"url": data_uri}})
    image_messages.append({"type": "text", "text": query})

    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": image_messages}]
    generator = model.create_chat_completion(messages=messages, stream=True)

    full_response = ""
    for chunk in generator:
        # chunk is a dict, often with a 'choices' list
        for choice in chunk.get("choices", []):
            # Each choice may have a 'delta' dict with 'content'
            delta = choice.get("delta", {})
            token = delta.get("content")
            if token:
                full_response += token
                if progress_callback is not None:
                    progress_callback(("assistant", token))
    return full_response



_IMAGE_MIME_TYPES = {
    # Most common formats
    '.png':  'image/png',
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif':  'image/gif',
    '.webp': 'image/webp',
    '.svg':  'image/svg+xml',
    '.svgz': 'image/svg+xml',

    # Next-generation formats
    '.avif': 'image/avif',
    '.heic': 'image/heic',
    '.heif': 'image/heif',
    '.heics': 'image/heic-sequence',
    '.heifs': 'image/heif-sequence',

    # Legacy / Windows formats
    '.bmp':  'image/bmp',
    '.dib':  'image/bmp',
    '.ico':  'image/x-icon',
    '.cur':  'image/x-icon',

    # Professional imaging
    '.tif':  'image/tiff',
    '.tiff': 'image/tiff',
}

def convert_to_uri(
    file_path: str,
    fallback_mime: str = "image/png" #"application/octet-stream"
) -> str:
    """
    Convert a local image file to a base64-encoded data URI with the correct MIME type.

    Supports 20+ image formats (PNG, JPEG, WebP, AVIF, HEIC, SVG, BMP, ICO, TIFF, etc.).

    Args:
        file_path: Path to the image file on disk.
        fallback_mime: MIME type used when the file extension is unknown.

    Returns:
        A valid data URI string (e.g., data:image/webp;base64,...).

    Raises:
        FileNotFoundError: If the file does not exist.
        OSError: If reading the file fails.
    """
    if not os.path.isfile(file_path):
        return f"Image file not found: {file_path}"

    extension = os.path.splitext(file_path)[1].lower()
    mime_type = _IMAGE_MIME_TYPES.get(extension, fallback_mime)

    if mime_type == fallback_mime:
        print(f"Warning: Unknown extension '{extension}' for '{file_path}'. "
              f"Using fallback MIME type: {fallback_mime}")

    try:
        with open(file_path, "rb") as img_file:
            encoded_data = base64.b64encode(img_file.read()).decode("utf-8")
    except Exception as e:
        return f"Failed to read image file '{file_path}': {e}"

    return f"data:{mime_type};base64,{encoded_data}"


