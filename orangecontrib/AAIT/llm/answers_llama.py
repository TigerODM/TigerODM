import ast
import copy
import os
import re
import numpy as np
try:
    import GPUtil #sometimes errors occurs on gpu testing
except:
    pass
import psutil
import base64
import ntpath
import platform
from llama_cpp import Llama
from jinja2 import Template

from Orange.data import Domain, StringVariable, Table


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm import prompt_management,handler_llama
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement
else:
    from orangecontrib.AAIT.llm import prompt_management,handler_llama
    from orangecontrib.AAIT.utils import MetManagement



supported_VLM = {
    "Qwen3-VL-8B-Instruct-Q4_K_M.gguf": "mmproj-F16.gguf",
    "Qwen3.5-9B-Q6_K.gguf": "mmproj-F16.gguf",
    "Qwen3.5-4B-Q4_K_M.gguf": "mmproj-F16.gguf"
}# manque Qwen3-VL



# Information (useless in the code)
format_for_messages = [
    {"role": "system", "content": str},

    {
        "role": "user",
        "content": [
            {"type": "text", "text": str},
            {"type": "image_url", "image_url": {"url": str}}
        ]
    },

    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": str},
            {"type": "image_url", "image_url": {"url": str}}
        ]
    }
]



def check_gpu(model_path, argself, mmproj_path=None, n_ctx=0):
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

    # Resolve effective context size
    if not n_ctx:
        n_ctx = getattr(argself, "n_ctx", 4096)

    try:
        n_ctx = int(n_ctx)
    except Exception:
        n_ctx = 4096

    # attention bien faire la suite dans un try exept car gputil peut etre capricieux
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
    # Calculate the model size in MB, including mmproj if provided with a 1500 MB buffer
    model_size = os.path.getsize(model_path) / (1024 ** 3) * 1000
    if mmproj_path and os.path.isfile(mmproj_path):
        mmproj_size = os.path.getsize(mmproj_path) / (1024 ** 3) * 1000
        print(f"mmproj size: {mmproj_size/1000:.2f}GB")
        model_size += mmproj_size

    kv_cache_mb = (n_ctx * 150_000) / (1024 ** 2)
    model_size += kv_cache_mb

    print(f"KV cache estimate: {kv_cache_mb/1000:.2f}GB")
    print(f"Required memory total: {model_size/1000:.2f}GB")
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
        print(f"Free VRAM: {free_vram/1000:.2f}GB")

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


def count_tokens(model, message, image_token_cost=1968, overhead_size=4):
    """
    Estimate token count for a single message.
    """
    # CASE 1: pure string
    if isinstance(message, str):
        return len(model.tokenize(message.encode("utf-8"))) + overhead_size

    total_tokens = 0
    # CASE 2: list (multimodal)
    if isinstance(message, list):
        for item in message:
            if not isinstance(item, dict):
                continue
            # TEXT
            if "text" in item:
                text = item["text"]
                total_tokens += len(model.tokenize(text.encode("utf-8"))) + overhead_size
            # IMAGE
            elif "image_url" in item:
                total_tokens += image_token_cost + overhead_size
            # Else, weird
            else:
                print("Wrong message format !")
    else:
        print("Wrong message format !")
    return total_tokens


def load_model(model_path, use_gpu, n_ctx=10000, k_cache=0, v_cache=0, verbose=False):
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
            verbose=verbose,
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
    model = load_model_with_handler(model_path=model_path, use_gpu=use_gpu, n_ctx=n_ctx, verbose=True)
    with_handler = True
    if model is None:
        model = load_model(model_path=model_path,
                           use_gpu=use_gpu,
                           n_ctx=n_ctx,
                           k_cache=query_parameters["k_cache"],
                           v_cache=query_parameters["v_cache"],
                           verbose=True)
        with_handler = False
    if model is None:
        return None

    # Paramètres de génération par défaut
    if query_parameters is None:
        query_parameters = {"max_tokens": 4096, "temperature": 0.4, "top_p": 0.4, "top_k": 40, "repeat_penalty": 1.15}

    # Génération sur la colonne "prompt", fonctionnement ligne à ligne

    rows = []
    for i, row in enumerate(data):
        features = list(data[i])
        metas = list(data.metas[i])
        prompt = row["prompt"].value

        system_prompt = row["system prompt"].value if "system prompt" in data.domain else ""
        assistant_prompt = row["assistant prompt"].value if "assistant prompt" in data.domain else ""

        # Si ce n'est pas un VLM:
        if not with_handler:
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
            # Parsing et regroupement des prompts / image path
            image_paths = [p.strip() for p in row["image paths"].value.split(";")] if "image paths" in data.domain else []
            message_rows = [["user", "text", prompt]]
            for image_path in image_paths:
                message_rows.append(["user", "image", image_path])
            if assistant_prompt:
                message_rows.append(["assistant", "text", assistant_prompt])

            # Création d'une table pour utiliser la helper function table_to_messages
            v1 = StringVariable("role")
            v2 = StringVariable("type")
            v3 = StringVariable("content")
            temp_domain = Domain([], metas=[v1, v2, v3])
            temp_table = Table.from_list(temp_domain, rows=message_rows)
            messages = table_to_messages(temp_table)

            answer = chat_completion_with_handler(messages=messages,
                                                  model=model,
                                                  parameters=query_parameters,
                                                  workflow_id=workflow_id,
                                                  progress_callback=progress_callback,
                                                  argself=argself)

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


def run_query(prompt, model, max_tokens=4096, temperature=0.4, top_p=0.8, top_k=50, repeat_penalty=1.15,
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
            print(token, end="")

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


def split_think(answer: str):
    # Extract think content (if any)
    think_match = re.search(r"(.*?)</think>", answer, flags=re.DOTALL)
    think_text = think_match.group(1).strip() if think_match else ""
    # Remove think block from the final answer
    final_answer = re.sub(r".*?</think>", "", answer, flags=re.DOTALL).strip()
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


def handle_long_messages(messages, model, n_ctx, method="truncate", margin=0, progress_callback=None):
    limit = max(n_ctx - margin, 0)

    if method == "truncate":
        return _handle_truncate(messages, model, limit, progress_callback)
    elif method == "summarize":
        # Placeholder for future implementation
        raise NotImplementedError("Summarization method is not yet implemented.")
    else:
        raise ValueError(f"Unknown method: {method}")


def _handle_truncate(messages, model, limit, progress_callback):
    kept_messages = []
    total_tokens = 0
    system_msg = None

    # 1. Separate and count the system message first
    if messages and messages[0]["role"] == "system":
        system_msg = messages[0]
        text = messages[0]["content"]
        total_tokens += count_tokens(model=model, message=text)

        # If the system message itself exceeds the limit, we're in trouble
        if total_tokens > limit:
            if progress_callback:
                progress_callback(("error", "System message exceeds context limit."))
            return [system_msg]

    # 2. Iterate through the rest of the messages (newest to oldest)
    # We skip index 0 if it's the system message
    chat_history = messages[1:] if system_msg else messages

    for msg in reversed(chat_history):
        content = msg["content"]
        tokens = count_tokens(model=model, message=content)

        if total_tokens + tokens > limit:
            if progress_callback:
                warning = (
                    f"Context limit reached ({limit} tokens). "
                    f"Keeping {len(kept_messages)} recent messages plus system prompt."
                    f"Remember that an image ≈ 2000 tokens."
                )
                progress_callback(("warning", warning))
            break

        kept_messages.append(msg)
        total_tokens += tokens

    # 3. Restore chronological order
    kept_messages.reverse()

    # 4. Re-attach the system message at the very top
    if system_msg:
        kept_messages.insert(0, system_msg)

    return kept_messages



# For pure display
def conversation_to_text(conversation):
    rendered_conversation = ""
    for messages in conversation:
        rendered_conversation += f"# {messages['role']}\n"
        if isinstance(messages["content"], str):
            rendered_conversation += messages["content"]
        else:
            for message in messages["content"]:
                if message["type"] == "text":
                    rendered_conversation += message["text"]
                elif message["type"] == "image_url":
                    rendered_conversation += "[IMAGE]"
        rendered_conversation += "\n"
    return rendered_conversation


def continue_conversation(table, model_path, use_gpu=False, n_ctx=32768, query_parameters=None, workflow_id="", progress_callback=None, argself=None):
    """
    Continues a multimodal conversation from an Orange data table using a local language model.

    This function converts a structured table into chat messages, loads the appropriate model
    (standard LLM or vision-language model), applies token/context handling, and generates a
    response using either a dedicated chat handler or a generic prompt-based pipeline. The
    generated assistant reply is then appended back into the original Orange Table format.

    Parameters:
    ----------
    table : Orange.data.Table
        Input conversation table containing rows with role/type/content metadata.
    model_path : str
        Path to the local model file or directory.
    use_gpu : bool, optional
        Whether to enable GPU acceleration for model inference.
    n_ctx : int, optional
        Maximum context window size for the model.
    query_parameters : dict, optional
        Generation parameters such as:
        - max_tokens
        - temperature
        - top_p
        - top_k
        - repeat_penalty
        Also may include cache settings (k_cache, v_cache).
    workflow_id : str, optional
        Identifier used for tracking or logging the generation workflow.
    progress_callback : callable, optional
        Callback function for reporting generation progress (UI updates, logs, etc.).
    argself : object, optional
        Optional reference to a widget or external context for callbacks.

    Returns:
    -------
    Orange.data.Table
        A new table containing the original conversation plus one additional row
        representing the assistant's generated response.

    Returns None if model loading or message conversion fails.
    """
    # Copie des données d'entrée
    data = copy.deepcopy(table)

    # Chargement modèle (llama_cpp)
    model_name = os.path.basename(model_path)

    if handler_llama.find_mmproj_path(model_path) is not None:
        model = load_model_with_handler(model_path, n_ctx=n_ctx, use_gpu=use_gpu, verbose=True)
        with_handler = True
    else:
        model = load_model(model_path=model_path,
                           use_gpu=use_gpu,
                           n_ctx=n_ctx,
                           k_cache=query_parameters["k_cache"],
                           v_cache=query_parameters["v_cache"])
        with_handler = False
    if model is None:
        return None

    # Default generation parameters
    if query_parameters is None:
        query_parameters = {"max_tokens": 0, "temperature": 0.4, "top_p": 0.4, "top_k": 40, "repeat_penalty": 1.15}

    # Build the conversation from table
    messages = table_to_messages(data)
    if not messages:
        return
    messages = handle_long_messages(messages, model, n_ctx, method="truncate", margin=query_parameters["max_tokens"], progress_callback=progress_callback)

    ### GENERATE ANSWER
    if with_handler:
        answer = chat_completion_with_handler(messages=messages,
                                              model=model,
                                              parameters=query_parameters,
                                              workflow_id=workflow_id,
                                              progress_callback=progress_callback,
                                              argself=argself)
    else:
        try:
            print("Trying native prompt formating...")
            chat_template = model.metadata["tokenizer.chat_template"]
            if not is_multimodal_template(chat_template):
                messages = flatten_multimodal_messages(messages, drop_images=True)
            template = Template(chat_template)
            prompt = template.render(messages=messages, tools=None, add_generation_prompt=True)
            print("Successfully generated prompt.")
        except Exception as e:
            print(f"An error happened: {e}. Falling back to generic prompt formating...")
            prompt = prompt_management.apply_template_to_conversation_2(model.model_path, conversation=messages)
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
    thinking, answer = split_think(answer)

    # Create output table
    meta = data.metas[-1].copy()
    meta_names = [m.name for m in data.domain.metas]
    meta[meta_names.index("role")] = "assistant"
    meta[meta_names.index("type")] = "text"
    meta[meta_names.index("content")] = answer
    empty_x = np.zeros((1, len(data.domain.attributes)))

    new_row = Table.from_numpy(
        data.domain,
        X=empty_x,
        metas=np.array([meta], dtype=object)
    )
    out_data = Table.concatenate([data, new_row])
    return out_data


# Should replace load_Qwen3VL (more generic)
def load_model_with_handler(model_path, n_ctx=32768, use_gpu=True, verbose=True):
    """
    Loads a multimodal (vision-language) model using a dedicated chat handler and GGUF backend.

    This function initializes a model with optional GPU acceleration and attaches the
    appropriate multimodal projector (mmproj) required for vision capabilities. It currently
    supports specific VLM architectures (e.g., Qwen3-VL) by selecting the correct chat handler
    and configuring the Llama backend accordingly.

    Parameters:
    ----------
    model_path : str
        Path to the GGUF model file.
    n_ctx : int, optional
        Context window size for the model (default is 32768).
    use_gpu : bool, optional
        If True, enables GPU acceleration by offloading layers.
    verbose : bool, optional
        If True, enables detailed logging during model loading and inference.

    Returns:
    -------
    Llama or None
        A configured Llama model instance with an attached multimodal chat handler,
        or None if required projector files are missing or the model is unsupported.
    """
    model_name = os.path.basename(model_path)
    mmproj_path = handler_llama.find_mmproj_path(model_path)

    if mmproj_path is None or not os.path.exists(mmproj_path) :
        print(f"Couldn't find the projector for this model: {mmproj_path}")
        return None

    n_gpu_layers = -1 if use_gpu else 0
    model = None
    chat_handler = handler_llama.get_chat_handler(model_path, mmproj_path, verbose=verbose, use_gpu=use_gpu)
    model = Llama(model_path=model_path,
                  chat_handler=chat_handler,
                  n_ctx=n_ctx,
                  n_gpu_layers=n_gpu_layers,
                  verbose=verbose)

    return model


def run_Qwen3VL_query(query, image_paths, image_prompts, model, system_prompt=" ", workflow_id="", progress_callback=None):
    image_messages = []
    for i, image_path in enumerate(image_paths):
        if os.path.exists(image_path):
            data_uri = convert_to_uri(image_path)
            if not data_uri.startswith("data"):
                progress_callback(("error", data_uri))
                return "The image could not be processed"
            # Add prompt first, if available
            if image_prompts and i < len(image_prompts):
                image_messages.append({
                    "type": "text",
                    "text": image_prompts[i]
                })
            # Then add the image
            image_messages.append({
                "type": "image_url",
                "image_url": {"url": data_uri}
            })
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
                write_tokens_to_file(token, workflow_id)
                if progress_callback is not None:
                    progress_callback(("assistant", token))
    return full_response


# Should replace run_Qwen3VL_query (more generic)
def chat_completion_with_handler(messages, model, parameters, workflow_id="", progress_callback=None, argself=None):
    """
    Generates a streaming chat completion using a multimodal-capable Llama model handler.

    This function sends a list of chat messages to the model and streams the response token
    by token. It aggregates the generated tokens into a full response while optionally
    reporting progress in real time via callbacks and persisting tokens to disk.

    The generation can be interrupted externally via the `argself.stop` flag.

    Parameters:
    ----------
    messages : list
        List of chat messages in OpenAI-style format, including role and multimodal content.
    model : Llama
        Loaded Llama model instance with an attached chat handler.
    parameters : dict
        Generation parameters including:
        - temperature
        - top_p
        - top_k
        - repeat_penalty
        - max_tokens
    workflow_id : str, optional
        Identifier used for logging or tracking streamed tokens.
    progress_callback : callable, optional
        Callback function receiving streamed tokens for UI or live display.
    argself : object, optional
        External controller object that may contain a `.stop` flag to interrupt generation.

    Returns:
    -------
    str
        The full generated assistant response as a single concatenated string.
    """
    thinks = handler_llama.is_a_thinking_model(model)
    think_token_added = False
    generator = model.create_chat_completion(messages=messages,
                                             temperature=parameters["temperature"],
                                             top_p=parameters["top_p"],
                                             top_k=parameters["top_k"],
                                             repeat_penalty=parameters["repeat_penalty"],
                                             max_tokens=parameters["max_tokens"],
                                             stream=True)
    full_response = ""
    for chunk in generator:
        # chunk is a dict, often with a 'choices' list
        for choice in chunk.get("choices", []):
            # Each choice may have a 'delta' dict with 'content'
            delta = choice.get("delta", {})
            token = delta.get("content")

            if thinks and not think_token_added:
                thinking_token = "<think>\n"
                full_response += thinking_token
                write_tokens_to_file(thinking_token, workflow_id)
                if progress_callback is not None:
                    progress_callback(("assistant", thinking_token))
                think_token_added = True

            if token:
                full_response += token
                write_tokens_to_file(token, workflow_id)
                if progress_callback is not None:
                    progress_callback(("assistant", token))
                if argself is not None and getattr(argself, "stop", False):
                    return full_response
    return full_response



def table_to_messages(data):
    """
    Converts a structured table of role/type/content rows into a chat-formatted message list.

    This function groups consecutive USER and ASSISTANT rows into single messages with multimodal
    content (text and images), while keeping SYSTEM messages as standalone entries. It also converts
    image paths into data URIs when valid, enabling multimodal compatibility.

    Parameters:
    ----------
    data : Orange.data.Table
        Iterable of rows where each row contains:
        - "role": role enum (system, user, assistant)
        - "type": content type enum (text or image)
        - "content": actual content value (string path or text)

    Returns:
    -------
    list
        A list of message dictionaries in chat format:
        - {"role": "system", "content": str}
        - {"role": "user"/"assistant", "content": [{"type": "text", ...}, {"type": "image_url", ...}]}

    Returns None if an image conversion error occurs.
    """
    messages = []
    current_message = None
    for row in data:
        role = row["role"].value
        typ = row["type"].value
        content = row["content"].value

        # SYSTEM → always standalone
        if role == "system":
            messages.append({"role": "system", "content": content})
            current_message = None
            continue

        # USER / ASSISTANT → group into one message
        if current_message is None or current_message["role"] != role:
            current_message = {"role": role, "content": []}
            messages.append(current_message)

        # Add content item
        if typ == "text":
            current_message["content"].append({"type": "text", "text": content})
        elif typ == "image":
            content = content.strip("'").strip('"')
            if os.path.exists(content):
                data_uri = convert_to_uri(content)
                if not data_uri.startswith("data"):
                    current_message["content"].append({"type": "text", "text": "Error: image could not be loaded !"})
                else:
                    current_message["content"].append({"type": "image_url", "image_url": {"url": data_uri}})
            else:
                current_message["content"].append({"type": "text", "text": "PathError: the image doesn't exist !"})
    return messages

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

    extension = os.path.splitext(file_path)[1].strip().lower()
    mime_type = _IMAGE_MIME_TYPES.get(extension, fallback_mime)

    if mime_type == fallback_mime and extension != ".png":
        print(f"Warning: Unknown extension '{extension}' for '{file_path}'. "
              f"Using fallback MIME type: {fallback_mime}")

    try:
        with open(file_path, "rb") as img_file:
            encoded_data = base64.b64encode(img_file.read()).decode("utf-8")
    except Exception as e:
        return f"Failed to read image file '{file_path}': {e}"

    return f"data:{mime_type};base64,{encoded_data}"






# 2 functions to assure compatibility between LLM and VLM
def is_multimodal_template(chat_template: str) -> bool:
    """
    Heuristically detect if a Jinja chat template supports multimodal input.
    """

    multimodal_markers = [
        "vision_start",
        "vision_end",
        "image_pad",
        "video_pad",
        "image_url",
        "image",
        "video",
        "<|vision_start|>",
        "<|image_pad|>",
        "<|video_pad|>",
    ]

    template_lower = chat_template.lower()

    return any(marker.lower() in template_lower for marker in multimodal_markers)

def flatten_multimodal_messages(messages, drop_images=True):
    """
    Converts structured messages into pure text format.
    Only works safely if messages contain no real multimodal content.
    """

    flat_messages = []

    for msg in messages:
        content = msg.get("content")

        # CASE 1: already string → keep
        if isinstance(content, str):
            flat_messages.append({
                "role": msg["role"],
                "content": content
            })
            continue

        # CASE 2: list of content blocks
        if isinstance(content, list):
            text_parts = []

            for item in content:
                if not isinstance(item, dict):
                    continue

                # TEXT
                if "text" in item:
                    text_parts.append(item["text"])

                # IMAGE (decide behavior)
                elif any(k in item for k in ["image", "image_url"]):
                    if not drop_images:
                        raise ValueError("Multimodal content found (image). Cannot flatten safely.")
                    # otherwise ignore images silently or mark them
                    text_parts.append("[IMAGE]")

            flat_messages.append({
                "role": msg["role"],
                "content": "\n".join(text_parts)
            })
            continue

        # CASE 3: dict-style content (your older format)
        if isinstance(content, dict):
            if "text" in content:
                flat_messages.append({
                    "role": msg["role"],
                    "content": content["text"]
                })
            elif "image_url" in content:
                if drop_images:
                    flat_messages.append({
                        "role": msg["role"],
                        "content": "[IMAGE]"
                    })
                else:
                    raise ValueError("Image found in dict content")

    return flat_messages
