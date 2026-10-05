import copy
import gc
import os
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



# =============================================================================
# Dimensionnement memoire
# =============================================================================

# Type GGML du cache KV. 0 = F32, 1 = F16, 8 = Q8_0.
# ATTENTION : ne jamais passer 0 a llama_cpp en croyant "valeur par defaut",
# cela force un cache KV en F32, soit le double de la F16.
GGML_TYPE_F16 = 1
GGML_TYPE_Q8_0 = 8

# Reserve fixe (Mo) pour les buffers de calcul, le projecteur multimodal
# et la VRAM deja prise par le canvas Orange.
RUNTIME_VRAM_OVERHEAD_MB = 1800

# Cout du cache KV en octets par token, par famille d'architecture.
# Mesure sur les logs llama.cpp (K + V, couches non-glissantes, KV en F16).
# Gemma 4 12B a des tetes d'attention en 512, d'ou un cout tres superieur
# a la moyenne : c'est lui qui dimensionne le pire cas.
KV_BYTES_PER_TOKEN = {
    "gemma-4-12b": 16384,
    "gemma4-12b": 16384,
    "gemma-4-e4b": 4096,
    "gemma-4-e2b": 2048,
    "qwen3.5-9b": 3072,
    "qwen3.5": 3072,
    "qwen3-vl": 4096,
}

# Valeur par defaut, volontairement pessimiste, pour un modele inconnu.
KV_BYTES_PER_TOKEN_DEFAULT = 16384

# Balises de raisonnement, par famille de modeles.
# La detection se fait sur la balise de FERMETURE : c'est la seule fiable.
# llama.cpp consomme frequemment la balise d'ouverture via le chat template,
# et chat_completion_with_handler() en reinjecte une artificiellement pour
# l'affichage. Chercher l'ouverture donnerait donc de faux negatifs.
THINK_CLOSE_TAGS = [
    "<channel|>",      # Gemma 4  (ouverture : <|channel>thought)
    "</think>",        # Qwen 3.x, DeepSeek-R1
    "<|/think|>",
    "</thought>",
]

# Balises d'ouverture a retirer du bloc de raisonnement extrait.
THINK_OPEN_TAGS = [
    "<|channel>thought",
    "<|channel>",
    "<think>",
    "<|think|>",
    "<thought>",
]

def kv_bytes_per_token_from_gguf(model_path, bytes_per_elem=2):
    """Coût KV par token (K + V, F16) lu dans les métadonnées GGUF. None si illisible."""
    try:
        from gguf import GGUFReader
        reader = GGUFReader(model_path)

        def val(key):
            field = reader.get_field(key)
            return None if field is None else field.contents()

        arch = val("general.architecture")
        n_layer = val(f"{arch}.block_count")
        n_head = val(f"{arch}.attention.head_count")
        n_head_kv = val(f"{arch}.attention.head_count_kv") or n_head
        n_embd = val(f"{arch}.embedding_length")
        if not (arch and n_layer and n_head and n_embd):
            return None

        head_max = max(n_head) if isinstance(n_head, list) else n_head
        k_len = val(f"{arch}.attention.key_length") or n_embd // head_max
        v_len = val(f"{arch}.attention.value_length") or n_embd // head_max

        # head_count_kv peut être une valeur unique ou une liste par couche
        kv_heads_total = sum(n_head_kv) if isinstance(n_head_kv, list) else n_layer * n_head_kv
        return int(kv_heads_total * (k_len + v_len) * bytes_per_elem)
    except Exception as e:
        print(f"Could not read KV size from GGUF: {e}")
        return None

def estimate_kv_bytes_per_token(model_path):
    """
    Estime le cout du cache KV en octets par token a partir du nom du fichier.

    C'est une heuristique : le cout reel depend de n_embd_head_k, du nombre de
    tetes KV et du nombre de couches, qui ne sont lisibles qu'apres chargement
    du GGUF. Elle sert uniquement a decider CPU/GPU en amont ; le vrai garde-fou
    est la degradation progressive de load_model_with_handler().
    """
    if not model_path:
        return KV_BYTES_PER_TOKEN_DEFAULT
    name = os.path.basename(str(model_path)).lower()
    for key, value in KV_BYTES_PER_TOKEN.items():
        if key in name:
            return value
    return kv_bytes_per_token_from_gguf(model_path) or KV_BYTES_PER_TOKEN_DEFAULT


def get_free_vram_mb():
    """VRAM libre du premier GPU en Mo, ou None si indisponible."""
    try:
        gpus = GPUtil.getGPUs()
        if not gpus:
            return None
        return float(gpus[0].memoryFree)
    except Exception as e:
        print(f"Could not read free VRAM: {e}")
        return None


def fit_n_ctx_to_vram(model_path, n_ctx, use_gpu, min_n_ctx=4096):
    """
    Reduit n_ctx pour que poids + cache KV + marge tiennent dans la VRAM libre.

    Retourne le n_ctx retenu. Ne descend jamais sous min_n_ctx : si meme cette
    valeur ne tient pas, on renvoie min_n_ctx et c'est la degradation de
    load_model_with_handler() qui basculera sur CPU.
    """
    if not use_gpu:
        return n_ctx

    free_vram = get_free_vram_mb()
    if free_vram is None:
        return n_ctx

    try:
        weights_mb = os.path.getsize(model_path) / (1024 ** 2)
    except Exception:
        weights_mb = 0.0

    budget_mb = free_vram - weights_mb - RUNTIME_VRAM_OVERHEAD_MB
    if budget_mb <= 0:
        print(f"KV budget exhausted (free={free_vram:.0f}MB, weights={weights_mb:.0f}MB)")
        return min_n_ctx

    per_token = estimate_kv_bytes_per_token(model_path)
    max_n_ctx = int((budget_mb * (1024 ** 2)) / per_token)
    # Aligne sur 1024 pour rester propre vis-a-vis du batching.
    max_n_ctx = max(min_n_ctx, (max_n_ctx // 1024) * 1024)

    if max_n_ctx < n_ctx:
        print(f"n_ctx reduced {n_ctx} -> {max_n_ctx} "
              f"(free VRAM {free_vram:.0f}MB, weights {weights_mb:.0f}MB, "
              f"{per_token} B/token)")
        return max_n_ctx

    return n_ctx


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

    kv_cache_mb = (n_ctx * estimate_kv_bytes_per_token(model_path)) / (1024 ** 2)
    model_size += kv_cache_mb

    # Marge pour les buffers de calcul, le projecteur multimodal et la VRAM
    # deja consommee par le canvas Orange (Qt6 + WebEngine + widgets charges).
    model_size += RUNTIME_VRAM_OVERHEAD_MB

    print(f"KV cache estimate: {kv_cache_mb/1000:.2f}GB")
    print(f"Runtime overhead reserve: {RUNTIME_VRAM_OVERHEAD_MB/1000:.2f}GB")
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


def load_model(model_path, use_gpu, n_ctx=10000, k_cache=None, v_cache=None, verbose=False, error_callback=None):
    """
    Charge un modèle GGUF avec llama_cpp.Llama.

    - use_gpu=True : tente d'utiliser l'accélération (Metal/CUDA/Vulkan selon build)
      en mettant n_gpu_layers à -1 (= toutes les couches si possible).
    - use_gpu=False : CPU only (n_gpu_layers=0).
    - error_callback : optionnel, callable(("error", message)) - permet de remonter
      la vraie cause de l'échec jusqu'au widget (au lieu du message générique
      "unable to load model"). N'est utilisé ici que pour ça, jamais pour du
      streaming/progression - contrairement au progress_callback des fonctions
      de génération (run_query, chat_completion_with_handler, ...).
    """
    if not os.path.exists(model_path):
        message = f"Model could not be found: {model_path} does not exist"
        print(message)
        if error_callback is not None:
            error_callback(("error", message))
        return

    try:
        # n_gpu_layers : -1 = toutes les couches si le binaire a un backend GPU (Metal/CUDA/Vulkan)
        n_gpu_layers = -1 if use_gpu else 0

        # n_threads : par défaut tous les cœurs logiques dispo moins 1 (pour avoir l'interface graphique qui ne freeze pas)
        n_threads = max(1, (os.cpu_count()-1 or 1))

        # Ajuste le contexte a la VRAM reellement disponible avant de charger.
        n_ctx = fit_n_ctx_to_vram(model_path, n_ctx, use_gpu)

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
            # Cache glissant dimensionne a la fenetre reelle et non a n_ctx.
            # Indispensable pour Gemma 4 (fenetre 1024 sur 40 de ses 48 couches),
            # sans effet sur les architectures sans attention glissante.
            swa_full=False,
            type_k=k_cache,
            type_v=v_cache
        )
        return model
    except Exception as e:
        print("Failed to load model with llama_cpp:", e)
        if error_callback is not None:
            error_callback(("error", f"Failed to load model: {e}"))
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
    # Note: `progress_callback` est le canal multi-usage (tokens, %, warnings, erreurs).
    # load_model/load_model_with_handler ne l'utilisent que pour signaler un échec,
    # d'où le nom `error_callback` côté de leur signature.
    model = load_model_with_handler(model_path=model_path, use_gpu=use_gpu, n_ctx=n_ctx, verbose=True, error_callback=progress_callback)
    with_handler = True
    if model is None:
        model = load_model(model_path=model_path,
                           use_gpu=use_gpu,
                           n_ctx=n_ctx,
                           k_cache=query_parameters["k_cache"],
                           v_cache=query_parameters["v_cache"],
                           error_callback=progress_callback,
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
        model.reset()
        _ctx = model._ctx
        if hasattr(_ctx, "memory_clear"):
            _ctx.memory_clear(True)
        elif hasattr(_ctx, "kv_cache_clear"):
            _ctx.kv_cache_clear()
        else:
            import llama_cpp
            llama_cpp.llama_memory_clear(llama_cpp.llama_get_memory(_ctx.ctx), True)
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

        thinking, answer = split_think(answer)
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
    stop_sequences = ["<|endoftext|>", "### User", "<|im_end|>", "<|im_start|>", "<|im_end>", "<im_end|>", "<im_end>", "<turn|>", "<|turn>"]
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

    # Le générateur renvoie des chunks contenant choices[0].text.
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
                answer += token
                break

            answer += token
            write_tokens_to_file(token, workflow_id)
            # print(token, end="")

            if progress_callback is not None:
                # Renvoie des tokens vers l'interface PyQt
                progress_callback(("assistant", token))

            if argself is not None and getattr(argself, "stop", False):
                # Arrêt demandé de l'extérieur
                return answer

    except Exception as e:
        # En cas d'erreur pendant la génération (contexte dépassé, allocation
        # mémoire, ...), on retourne ce qu'on a + on remonte l'erreur au widget
        print("Generation error (llama_cpp):", e)
        if progress_callback is not None:
            progress_callback(("error", f"Generation failed: {e}"))

    # Nettoyage des séquences d'arrêt
    for stop in stop_sequences:
        if stop:
            answer = answer.replace(stop, "")

    return answer




def strip_think_open_tags(text: str) -> str:
    """Retire les balises d'ouverture de raisonnement d'un fragment de texte."""
    for tag in THINK_OPEN_TAGS:
        text = text.replace(tag, "")
    return text


def find_think_close(text: str):
    """
    Localise la premiere balise de fermeture de raisonnement presente.

    Retourne (position, balise) ou (-1, None) si aucune n'est trouvee.
    """
    best_index = -1
    best_tag = None
    for tag in THINK_CLOSE_TAGS:
        idx = text.find(tag)
        if idx != -1 and (best_index == -1 or idx < best_index):
            best_index = idx
            best_tag = tag
    return best_index, best_tag


def split_think(answer: str):
    """
    Separe le raisonnement de la reponse finale.

    Gere indifferemment les conventions Gemma 4 (<|channel>thought ... <channel|>)
    et Qwen / DeepSeek (<think> ... </think>), y compris quand la balise
    d'ouverture est absente ou orpheline.

    Retourne (raisonnement, reponse). Le raisonnement est une chaine vide si le
    modele n'en a pas produit.
    """
    if not answer:
        return "", ""

    idx, tag = find_think_close(answer)

    if idx == -1:
        # Aucune fermeture : soit le modele ne raisonne pas, soit la generation
        # a ete coupee en plein raisonnement (max_tokens atteint, arret manuel).
        # Dans les deux cas on ne peut pas isoler de reponse fiable, donc on
        # renvoie le texte nettoye de ses balises d'ouverture orphelines.
        return "", strip_think_open_tags(answer).strip()

    think_text = strip_think_open_tags(answer[:idx]).strip()
    final_answer = answer[idx + len(tag):]
    final_answer = strip_think_open_tags(final_answer).strip()

    return think_text, final_answer


def handle_context_length(prompt, model, n_ctx, method="truncate", margin=0, progress_callback=None):
    """
    Truncate a prompt to fit within n_ctx tokens, leaving margin for generation.
    Safely handles edge cases where limit <= 0.
    """
    # Keep a margin for generated tokens
    limit = max(n_ctx - margin, 0)  # clamp to at least 0
    if method == "truncate":
        tokens = model.tokenize(prompt.encode("utf-8"))
        initial_length = len(tokens)
        if initial_length > limit:
            tokens = tokens[-limit:] if limit > 0 else []
            truncated_length = len(tokens)
            prompt = model.detokenize(tokens).decode("utf-8") if tokens else ""
            if progress_callback:
                if limit <= 0:
                    warning = (
                        f"Max tokens ({margin}) >= Context Length ({n_ctx}) : aucune place pour l'entrée, "
                        f"elle a été entièrement coupée ({initial_length} tokens perdus).\n"
                        f"-> Baissez Max tokens ou augmentez Context Length."
                    )
                else:
                    warning = (
                        f"Entrée trop longue : {initial_length} tokens pour une place utilisable de {limit} "
                        f"(Context Length {n_ctx} - Max tokens {margin}). "
                        f"Les {initial_length - truncated_length} premiers tokens ont été coupés, "
                        f"les {truncated_length} derniers conservés.\n"
                        f"-> Augmentez Context Length (plus de VRAM) ou baissez Max tokens "
                        f"pour ne pas tronquer l'entrée."
                    )
                progress_callback(("warning", warning))
        return prompt
    elif method == "summarize":
        pass
    else:
        return prompt


def handle_long_messages(messages, model, n_ctx, method="truncate", margin=0, progress_callback=None, mode="chat"):
    limit = max(n_ctx - margin, 0)

    if method == "truncate":
        return _handle_truncate(messages, model, limit, progress_callback,
                                context_length=n_ctx, max_tokens=margin, mode=mode)
    elif method == "summarize":
        raise NotImplementedError("La méthode de résumé n'est pas encore implémentée.")
    else:
        raise ValueError(f"Méthode inconnue : {method}")


def _handle_truncate(messages, model, limit, progress_callback, context_length=None, max_tokens=0, mode="chat"):
    kept_messages = []
    total_tokens = 0
    system_msg = None

    if messages and messages[0]["role"] == "system":
        system_msg = messages[0]
        text = messages[0]["content"]
        total_tokens += count_tokens(model=model, message=text)

        if total_tokens > limit:
            if progress_callback:
                if limit <= 0:
                    progress_callback(("error",
                        f"Max tokens ({max_tokens}) >= Context Length ({context_length}) : il ne reste "
                        f"aucune place pour l'entrée, pas même le prompt système.\n"
                        f"-> Baissez Max tokens ou augmentez Context Length."))
                else:
                    progress_callback(("error",
                        f"Le prompt système seul (~{total_tokens} tokens) dépasse la place utilisable "
                        f"({limit} = Context Length {context_length} - Max tokens {max_tokens}).\n"
                        f"-> Raccourcissez le prompt système, baissez Max tokens, ou augmentez Context Length."))
            return [system_msg]

    chat_history = messages[1:] if system_msg else messages

    for msg in reversed(chat_history):
        content = msg["content"]
        tokens = count_tokens(model=model, message=content)

        if total_tokens + tokens > limit:
            if progress_callback:
                if mode == "single":
                    # Question unique : pas d'historique, on coupe DANS l'entrée
                    progress_callback(("warning",
                        f"L'entrée (prompt + image) dépasse la place utilisable "
                        f"({limit} = Context Length {context_length} - Max tokens {max_tokens} ; "
                        f"une image ~= 2000 tokens, estimé). Une partie de l'entrée sera coupée.\n"
                        f"-> Augmentez Context Length (plus de VRAM) ou baissez Max tokens "
                        f"pour ne pas tronquer l'entrée."))
                else:
                    # Conversation : on jette les tours les plus anciens
                    dropped = len(chat_history) - len(kept_messages)
                    progress_callback(("warning",
                        f"Limite de contexte atteinte : {len(kept_messages)} message(s) récent(s) conservé(s) "
                        f"+ prompt système, {dropped} ancien(s) écarté(s) "
                        f"(place utilisable {limit} = Context Length {context_length} - Max tokens {max_tokens} ; "
                        f"une image ~= 2000 tokens, estimé).\n"
                        f"-> Augmentez Context Length (plus de VRAM) ou baissez Max tokens "
                        f"pour garder plus de conversation."))
            break

        kept_messages.append(msg)
        total_tokens += tokens

    kept_messages.reverse()
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

    if handler_llama.find_mmproj_path(model_path) is not None:
        model = load_model_with_handler(model_path, n_ctx=n_ctx, use_gpu=use_gpu, verbose=True, error_callback=progress_callback)
        with_handler = True
    else:
        model = load_model(model_path=model_path,
                           use_gpu=use_gpu,
                           n_ctx=n_ctx,
                           k_cache=query_parameters["k_cache"],
                           v_cache=query_parameters["v_cache"],
                           error_callback=progress_callback)
        with_handler = False
    if model is None:
        return None

    # Default generation parameters
    if query_parameters is None:
        query_parameters = {"max_tokens": 0, "temperature": 0.4, "top_p": 0.4, "top_k": 40, "repeat_penalty": 1.15}

    # Build the conversation from table
    messages = table_to_messages(data)
    if not messages:
        if progress_callback is not None:
            progress_callback(("error", "Could not build a conversation from the input data (empty or invalid role/type/content rows)."))
        return data
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

    if answer == "":
        answer = (
            "Error: The answer could not be generated. Your prompt might be too long, or the model architecture you tried to use is possibly "
            f"not supported yet.\n\nModel name: {ntpath.basename(model_path)}"
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


def load_model_with_handler(model_path, n_ctx=32768, use_gpu=True, verbose=True, min_n_ctx=4096, error_callback=None):
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
    error_callback : callable, optional
        callable(("warning", message)) - used only to report why this failed
        (not a fatal error here since callers typically fall back to load_model()).

    Returns:
    -------
    Llama or None
        A configured Llama model instance with an attached multimodal chat handler,
        or None if required projector files are missing or the model is unsupported.
    """
    mmproj_path = handler_llama.find_mmproj_path(model_path)

    if mmproj_path is None or not os.path.exists(mmproj_path) :
        print(f"Couldn't find the projector for this model: {mmproj_path}")
        return None

    n_threads = max(1, (os.cpu_count() - 1 or 1))

    # Le contexte demande est d'abord ramene a ce que la VRAM libre peut tenir.
    # C'est une estimation ; la boucle de dégradation ci-dessous rattrape les cas
    # ou elle est trop optimiste (VRAM prise entre-temps, architecture inconnue).
    requested_n_ctx = int(n_ctx)
    n_ctx = fit_n_ctx_to_vram(model_path, requested_n_ctx, use_gpu, min_n_ctx=min_n_ctx)

    # Echelle de repli, de la configuration la plus confortable a la plus sobre.
    # Chaque etape est (n_ctx, sur_gpu, type_cache_kv).
    attempts = []
    seen = set()

    def add_attempt(ctx, on_gpu, kv_type):
        ctx = max(int(ctx), min_n_ctx)
        key = (ctx, on_gpu, kv_type)
        if key not in seen:
            seen.add(key)
            attempts.append(key)

    if use_gpu:
        add_attempt(n_ctx, True, GGML_TYPE_F16)
        add_attempt(n_ctx, True, GGML_TYPE_Q8_0)
        add_attempt(n_ctx // 2, True, GGML_TYPE_Q8_0)
        add_attempt(n_ctx // 4, True, GGML_TYPE_Q8_0)
        add_attempt(min_n_ctx, True, GGML_TYPE_Q8_0)
    # Dernier recours : CPU, ou la contrainte n'est plus la VRAM mais la RAM.
    add_attempt(requested_n_ctx, False, GGML_TYPE_F16)

    last_error = None

    for attempt_n_ctx, on_gpu, kv_type in attempts:
        chat_handler = None
        try:
            # Le handler charge le projecteur multimodal, et le charge sur le GPU
            # quand use_gpu est vrai : il consomme de la VRAM avant meme que
            # Llama() n'alloue son cache KV. Il est donc recree a chaque essai,
            # et libere explicitement en cas d'echec.
            chat_handler = handler_llama.get_chat_handler(
                model_path, mmproj_path, verbose=verbose, use_gpu=on_gpu
            )

            print(f"Loading model (n_ctx={attempt_n_ctx}, gpu={on_gpu}, "
                  f"kv_type={'Q8_0' if kv_type == GGML_TYPE_Q8_0 else 'F16'})")

            model = Llama(model_path=model_path,
                          chat_handler=chat_handler,
                          n_ctx=attempt_n_ctx,
                          n_gpu_layers=-1 if on_gpu else 0,
                          n_threads=n_threads,
                          # Cache glissant dimensionne a la fenetre reelle du
                          # modele et non a n_ctx. Sur Gemma 4 12B a 128k, cela
                          # fait passer le cache glissant de ~40 Go a ~0,5 Go.
                          # Sans effet sur les modeles sans attention glissante.
                          swa_full=False,
                          type_k=kv_type,
                          type_v=kv_type,
                          verbose=verbose)

            if attempt_n_ctx < requested_n_ctx:
                print(f"WARNING: context reduced from {requested_n_ctx} to "
                      f"{attempt_n_ctx} to fit available memory")
            if not on_gpu and use_gpu:
                print("WARNING: fell back to CPU, generation will be slow")

            return model

        except Exception as e:
            last_error = e
            print(f"Load failed (n_ctx={attempt_n_ctx}, gpu={on_gpu}): {e}")
            # Libere le projecteur avant l'essai suivant, sinon sa VRAM reste
            # prise et chaque tentative demarre avec moins de marge que la
            # precedente.
            handler_llama.close_chat_handler(chat_handler)
            del chat_handler
            gc.collect()

    print(f"Could not load model after {len(attempts)} attempts. "
          f"Last error: {last_error}")
    # Non bloquant : l'appelant se replie sur load_model(), d'où un simple warning.
    if error_callback is not None:
        error_callback(("warning", f"Multimodal loading failed, falling back to standard mode: {last_error}"))
    return None


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

    # --- Ajuste la conversation à la fenêtre de contexte --------------------
    # Empêche "prompt + image + réponse > n_ctx" de lever une erreur bloquante :
    # l'entrée est tronquée si nécessaire, et max_tokens est borné à la place
    # réellement disponible.
    messages, effective_max_tokens = fit_messages_to_context(
        messages,
        model,
        requested_max_tokens=parameters.get("max_tokens", 0),
        progress_callback=progress_callback,
    )

    full_response = ""

    # Une balise de fermeture peut etre coupee en deux tokens ("<chan" puis
    # "nel|>"). On retient donc en tampon la fin du flux tant qu'elle pourrait
    # constituer le debut d'une balise, et on n'emet que ce qui est certain.
    max_tag_len = max(len(t) for t in THINK_CLOSE_TAGS)
    pending = ""
    close_seen = False

    def emit(text):
        """Ecrit un fragment vers le fichier de log et l'UI."""
        if not text:
            return
        write_tokens_to_file(text, workflow_id)
        if progress_callback is not None:
            progress_callback(("assistant", text))

    try:
        generator = model.create_chat_completion(
            messages=messages,
            temperature=parameters["temperature"],
            top_p=parameters["top_p"],
            top_k=parameters["top_k"],
            repeat_penalty=parameters["repeat_penalty"],
            max_tokens=effective_max_tokens,
            stop=["<turn|>", "<|turn>"],
            stream=True,
        )
        for chunk in generator:
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})

                # Certaines versions de llama_cpp exposent deja le raisonnement
                # separement. Quand c'est le cas, il n'y a rien a parser.
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    if not think_token_added:
                        full_response += "<think>\n"
                        emit("<think>\n")
                        think_token_added = True
                    full_response += reasoning
                    emit(reasoning)

                token = delta.get("content")

                if thinks and not think_token_added:
                    thinking_token = "<think>\n"
                    full_response += thinking_token
                    emit(thinking_token)
                    think_token_added = True

                if token:
                    full_response += token

                    if close_seen:
                        # Raisonnement termine : plus rien a surveiller.
                        emit(token)
                    else:
                        pending += token
                        idx, tag = find_think_close(pending)
                        if idx != -1:
                            # Balise complete reconstituee : on emet tout jusqu'a la
                            # fin de la balise incluse, puis on passe en mode direct.
                            cut = idx + len(tag)
                            emit(pending[:cut])
                            pending = pending[cut:]
                            emit(pending)
                            pending = ""
                            close_seen = True
                        else:
                            # On garde en tampon de quoi reconstituer une balise a
                            # cheval sur deux tokens, et on emet le reste.
                            keep = max_tag_len - 1
                            if len(pending) > keep:
                                emit(pending[:-keep])
                                pending = pending[-keep:]

                    if argself is not None and getattr(argself, "stop", False):
                        emit(pending)
                        return full_response

    except Exception as e:
        # Filet défensif : si le vrai coût en tokens de l'image dépasse notre
        # estimation et que le contexte déborde en cours de génération, on
        # retourne ce qu'on a au lieu de faire planter tout le batch.
        print("Generation error (chat handler):", e)
        if progress_callback is not None:
            progress_callback(("warning", f"Génération interrompue tôt : {e}"))

    # Fin de generation : vider le tampon residuel.
    emit(pending)
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

        if role not in ["system", "user", "assistant"]:
            continue

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


def count_messages_tokens(model, messages, image_token_cost=1968, overhead_size=4):
    """Somme des tokens estimés sur toute une liste de messages VLM (texte + images)."""
    total = 0
    for msg in messages:
        total += count_tokens(model=model, message=msg["content"],
                              image_token_cost=image_token_cost, overhead_size=overhead_size)
    return total


def fit_messages_to_context(messages, model, requested_max_tokens,
                            n_ctx=None, min_generation=64, safety=16,
                            progress_callback=None):
    """
    Garantit que (prompt + images) laisse de la place pour la génération dans n_ctx.

    Retourne (messages, effective_max_tokens) :
      - messages : tronqués si besoin (system prompt + messages récents conservés)
      - effective_max_tokens : borné pour que prompt_tokens + max_tokens <= n_ctx - safety,
        ce qui empêche llama_cpp de lever une erreur de dépassement de contexte.

    requested_max_tokens == 0 est traité comme "utilise tout le contexte restant".
    """
    if n_ctx is None:
        try:
            n_ctx = model.n_ctx()
        except Exception:
            n_ctx = 4096

    # Marge qu'on réserve pour la réponse pendant qu'on tronque l'entrée
    margin = requested_max_tokens if requested_max_tokens and requested_max_tokens > 0 else min_generation

    # 1) Tronque les vieux messages si l'entrée seule est déjà trop grosse
    messages = handle_long_messages(messages, model, n_ctx, method="truncate",
                                    margin=margin, progress_callback=progress_callback,
                                    mode="single")

    # 2) Borne max_tokens à ce qui reste réellement après le prompt (tronqué)
    prompt_tokens = count_messages_tokens(model, messages)
    available = max(1, n_ctx - prompt_tokens - safety)

    if requested_max_tokens and requested_max_tokens > 0:
        effective_max_tokens = min(requested_max_tokens, available)
    else:
        effective_max_tokens = available  # illimité demandé -> tout ce qui rentre

    if progress_callback is not None and requested_max_tokens and effective_max_tokens < requested_max_tokens:
        progress_callback(("warning",
            f"Réponse limitée à {effective_max_tokens} tokens (au lieu de {requested_max_tokens}) "
            f"pour tenir dans le contexte : Context Length {n_ctx}, entrée ~= {prompt_tokens} tokens "
            f"(images estimées).\n"
            f"-> Augmentez Context Length ou baissez Max tokens pour une réponse plus longue."))
    return messages, effective_max_tokens


def identify_table_type(table):
    domain = table.domain

    # Vérifie uniquement les StringVariable
    string_vars = [
        var.name
        for var in list(domain.attributes) + list(domain.class_vars) + list(domain.metas)
        if isinstance(var, StringVariable)
    ]

    has_role = "role" in string_vars
    has_type = "type" in string_vars
    has_content = "content" in string_vars
    has_prompt = "prompt" in string_vars

    # Cas erreur : les 4 colonnes présentes
    if has_role and has_type and has_content and has_prompt:
        return "multiple"

    # Mode conversation
    elif has_role and has_type and has_content:
        return "conversation"

    # Mode prompt
    elif has_prompt:
        return "batch"

    return "error"



def prompt_to_messages(prompt, system_prompt="You are a helpful assistant.", image_paths=None):
    """
    Converts a prompt and optional images into a chat-formatted message list.

    Includes a system message when provided and supports multimodal user content with
    text and image attachments.

    Parameters:
    ----------
    prompt : str
        The user's prompt.
    system_prompt : str, optional
        The system instruction.
    image_paths : list[str], optional
        Image paths to attach to the user message.

    Returns:
    -------
    list
        Chat-formatted message dictionaries.
    """
    messages = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if image_paths:
        content = []
        for image_path in image_paths:
            image_path = image_path.strip().strip("'").strip('"')

            if not image_path:
                continue

            if not os.path.exists(image_path):
                content.append({"type": "text", "text": f"[ERROR] Image not found: {image_path}"})
                continue

            try:
                content.append({"type": "image_url", "image_url": {"url": convert_to_uri(image_path)}})
            except Exception as e:
                content.append({"type": "text", "text": f"[ERROR] Unable to read image {image_path}: {e}"})

        content.append({"type": "text","text": str(prompt)})
    else:
        content = str(prompt)

    messages.append({"role": "user", "content": content})
    return messages


def conv_to_messages(table):
    return table_to_messages(table)