import os
import re
from pathlib import Path



def is_a_thinking_model(model):
    """
    Detect if a GGUF model is likely a reasoning/thinking model.

    Returns:
        True  -> thinking model probable
        False -> non-thinking model probable
    """

    # =========================
    # HARDCODED KNOWN MODELS
    # =========================

    # Models KNOWN to use reasoning/thinking
    known_thinking_models = [
        "deepseek-r1",
        "deepseek-r1-distill",
        # "qwq",
        "qwen3-thinking",
        "qwen-3-thinking",
        "qwen3-instruct-thinking",
        # "magistral",
        # "reflection",
        # "r1",
        # "o1",
        # "o3",
        "phi-4-reasoning",
        "kimi-k2-thinking",
    ]

    # Models KNOWN to be NON-thinking
    known_non_thinking_models = [
        # "llama-2",
        # "llama-3",
        # "llama-3.1",
        # "llama-3.2",
        "mistral-7b-instruct",
        # "mixtral",
        # "gemma",
        # "gemma-2",
        "phi-3",
        "phi-4",
        "qwen2.5",
        "qwen2.5-instruct",
        # "qwen3",
        # "qwen3-instruct",
        "yi",
        "command-r",
        "tinyllama",
        "openchat",
        "gemma-4-e2b",
        # "solar",
    ]

    # =========================
    # MODEL NAME
    # =========================

    model_name = os.path.basename(
        getattr(model, "model_path", "")
    ).lower()

    # Remove extension
    model_name = model_name.replace(".gguf", "")

    # =========================
    # DIRECT NAME CHECK
    # =========================

    for name in known_thinking_models:
        if name in model_name:
            return True

    for name in known_non_thinking_models:
        if name in model_name:
            return False

    # =========================
    # METADATA EXTRACTION
    # =========================

    metadata = getattr(model, "metadata", {}) or {}

    # Safe extraction
    prompt_template = str(
        metadata.get("tokenizer.chat_template", "")
    ).lower()

    metadata_text = "\n".join(
        f"{k}: {v}" for k, v in metadata.items()
    ).lower()

    # =========================
    # STRONG THINKING SIGNALS
    # =========================

    strong_signals = [
        "<think>",
        "</think>",
        "enable_thinking",
        "reasoning_parser",
        "reasoning format",
        "reasoning_format",
        "chain_of_thought",
    ]

    for signal in strong_signals:
        if signal in metadata_text:
            return True

    # =========================
    # WEAK SIGNALS
    # =========================

    weak_signals = [
        "thinking",
        "reasoning",
        "thought",
        "cot",
    ]

    weak_score = 0

    for signal in weak_signals:
        if signal in metadata_text:
            weak_score += 1

    # Require several weak signals
    if weak_score >= 2:
        return True

    # =========================
    # FINAL TEMPLATE CHECK
    # =========================

    if "<think>" in prompt_template:
        return True

    return False


#-----------------------------------------------



def find_mmproj_path(model_path):
    """
    =====================================================================================
    find_mmproj_path
    =====================================================================================

    But :
    -----
    Trouver automatiquement le fichier mmproj associé à un modèle GGUF.

    IMPORTANT :
    ----------
    - Recherche UNIQUEMENT dans le même dossier que le modèle.
    - Aucun accès Internet.
    - Aucun scan de sous-dossiers.
    - Aucun téléchargement.
    - Aucun appel externe.

    Paramètre :
    -----------
    model_path : str | Path
        Chemin du modèle GGUF principal.

    Retour :
    --------
    str | None

        - chemin complet du mmproj trouvé
        - None si aucun mmproj crédible trouvé

    Exemples de fichiers supportés :
    --------------------------------
    mmproj-Qwen2-VL-7B-Instruct-f32.gguf
    mmproj-model-f16.gguf
    llava-mmproj-f16.gguf
    Phi-3.5-vision-instruct-mmproj-f16.gguf

    =====================================================================================
    """

    # =============================================================================
    # Conversion du chemin vers un objet Path robuste
    # =============================================================================

    # expanduser() :
    #   transforme ~ en dossier utilisateur
    #
    # resolve() :
    #   transforme en chemin absolu propre
    #
    # Exemple :
    #   ~/models/test.gguf
    # devient :
    #   C:/Users/lucas/models/test.gguf
    #
    model_path = Path(model_path).expanduser().resolve()

    # =============================================================================
    # Vérification que le modèle existe réellement
    # =============================================================================

    # Si le fichier n'existe pas :
    # -> inutile d'aller plus loin
    #
    if not model_path.exists():
        return None

    # =============================================================================
    # Récupération du dossier contenant le modèle
    # =============================================================================

    # Exemple :
    #   C:/models/qwen.gguf
    #
    # model_dir devient :
    #   C:/models
    #
    model_dir = model_path.parent

    # =============================================================================
    # Nom du fichier complet en minuscules
    # =============================================================================

    # Exemple :
    #   Qwen2-VL-Q4_K_M.gguf
    #
    # devient :
    #   qwen2-vl-q4_k_m.gguf
    #

    # =============================================================================
    # Nom sans extension
    # =============================================================================

    # Exemple :
    #   qwen2-vl-q4_k_m
    #
    model_stem = model_path.stem.lower()

    # =============================================================================
    # Fonction de normalisation de nom
    # =============================================================================

    def normalize_name(s):
        """
        Nettoie fortement un nom de modèle afin de comparer
        intelligemment deux fichiers.

        Exemple :

        Avant :
            Qwen2-VL-7B-Instruct-Q4_K_M.gguf

        Après :
            qwen2 vl 7b instruct

        Cela permet de détecter qu'un mmproj
        appartient probablement au même modèle.
        """

        # Tout en minuscules
        s = s.lower()

        # Supprime l'extension gguf si présente
        s = re.sub(r"\.gguf$", "", s)

        # =========================================================================
        # Suppression des quantizations
        # =========================================================================

        # Ces suffixes décrivent UNIQUEMENT la quantization,
        # PAS le modèle lui-même.
        #
        # On les retire pour comparer proprement.
        #
        # Exemples supprimés :
        #   q4_k_m
        #   q5_k_s
        #   q8_0
        #   iq4
        #
        s = re.sub(
            r"(q2_k_s|q2_k|q3_k_s|q3_k_m|q3_k_l|q4_k_s|q4_k_m|q5_k_s|q5_k_m|q6_k|q8_0|iq1|iq2|iq3|iq4|iq5)",
            " ",
            s
        )

        # =========================================================================
        # Suppression des précisions flottantes
        # =========================================================================

        # Exemples :
        #   f16
        #   f32
        #   fp16
        #   bf16
        #
        # Ce ne sont pas des informations utiles
        # pour identifier le modèle.
        #
        s = re.sub(r"(f16|f32|fp16|fp32|bf16)", " ", s)

        # =========================================================================
        # Remplacement des séparateurs par des espaces
        # =========================================================================

        # Tout ce qui n'est PAS :
        #   a-z
        #   0-9
        #
        # devient un espace.
        #
        s = re.sub(r"[^a-z0-9]+", " ", s)

        # =========================================================================
        # Nettoyage des espaces multiples
        # =========================================================================

        return " ".join(s.split())

    # =============================================================================
    # Création d'un ensemble de tokens du modèle principal
    # =============================================================================

    # Exemple :
    #
    # "qwen2 vl 7b instruct"
    #
    # devient :
    #
    # {
    #   "qwen2",
    #   "vl",
    #   "7b",
    #   "instruct"
    # }
    #
    model_tokens = set(normalize_name(model_stem).split())

    # =============================================================================
    # Vérification que le fichier est un vrai GGUF
    # =============================================================================

    def is_real_gguf(path):
        """
        Vérifie rapidement si le fichier commence
        bien par la signature GGUF.

        Cela évite :
        - faux fichiers
        - renommages incorrects
        - fichiers corrompus
        """

        try:

            # Ouverture binaire
            with open(path, "rb") as f:

                # Lecture des 4 premiers octets
                #
                # Un GGUF commence par :
                #   b"GGUF"
                #
                return f.read(4) == b"GGUF"

        except Exception:

            # Si erreur lecture :
            # -> considéré invalide
            #
            return False

    # =============================================================================
    # Fonction de scoring des candidats mmproj
    # =============================================================================

    def score_candidate(path):
        """
        Donne un score de probabilité qu'un fichier
        soit un mmproj valide pour le modèle principal.

        Plus le score est élevé :
        -> plus le candidat est crédible.
        """

        # Nom complet du fichier
        name = path.name.lower()

        # Nom sans extension
        stem = path.stem.lower()

        # =========================================================================
        # Évite de sélectionner le modèle lui-même
        # =========================================================================

        if path.resolve() == model_path:
            return -9999

        # =========================================================================
        # On ne veut QUE des fichiers gguf
        # =========================================================================

        if path.suffix.lower() != ".gguf":
            return -9999

        # =========================================================================
        # Initialisation du score
        # =========================================================================

        score = 0

        # =========================================================================
        # Très forts signaux mmproj
        # =========================================================================

        # Exemple :
        #   mmproj-model.gguf
        #
        if name.startswith("mmproj"):
            score += 120

        # Exemple :
        #   qwen-mmproj-f16.gguf
        #
        if "mmproj" in name:
            score += 100

        # Exemple :
        #   projector.gguf
        #
        if "projector" in name:
            score += 80

        # Exemple :
        #   mm_projector.gguf
        #
        if "mm_projector" in name:
            score += 80

        # =========================================================================
        # Signaux vision / multimodal
        # =========================================================================

        # Ces mots apparaissent souvent
        # dans les modèles VLM.
        #
        if "vision" in name:
            score += 30

        if "visual" in name:
            score += 20

        if "clip" in name:
            score += 20

        # =========================================================================
        # Similarité avec le modèle principal
        # =========================================================================

        # On transforme aussi le candidat
        # en ensemble de tokens.
        #
        candidate_tokens = set(normalize_name(stem).split())

        # Intersection des tokens
        #
        # Exemple :
        #
        # modèle :
        #   qwen2 vl 7b instruct
        #
        # candidat :
        #   mmproj qwen2 vl
        #
        # intersection :
        #   qwen2 vl
        #
        common = model_tokens & candidate_tokens

        # Bonus selon le nombre de mots communs
        #
        score += min(len(common) * 5, 40)

        # =========================================================================
        # Bonus pour formats fréquents
        # =========================================================================

        # Les mmproj sont souvent en :
        #   f16
        #   fp16
        #   bf16
        #
        if "f16" in name or "fp16" in name or "bf16" in name:
            score += 10

        if "f32" in name or "fp32" in name:
            score += 8

        # =========================================================================
        # Évite de prendre un modèle quantifié classique
        # =========================================================================

        quant_keywords = [
            "q2_k", "q3_k", "q4_k", "q5_k",
            "q6_k", "q8_0", "iq1", "iq2",
            "iq3", "iq4", "iq5"
        ]

        # Si le fichier contient :
        #   q4_k_m
        #
        # MAIS PAS :
        #   mmproj
        #
        # alors c'est probablement juste
        # un modèle texte normal.
        #
        if (
                any(q in name for q in quant_keywords)
                and "mmproj" not in name
                and "projector" not in name
        ):
            score -= 100

        # =========================================================================
        # Vérification signature GGUF
        # =========================================================================

        if is_real_gguf(path):

            # Bonus si vrai GGUF
            score += 20

        else:

            # Très forte pénalité sinon
            score -= 200

        # Retour du score final
        return score

    # =============================================================================
    # Liste des candidats potentiels
    # =============================================================================

    candidates = []

    # =============================================================================
    # Scan du dossier du modèle UNIQUEMENT
    # =============================================================================

    for file in model_dir.iterdir():

        # Ignore les dossiers
        if not file.is_file():
            continue

        # Ignore les fichiers non gguf
        if file.suffix.lower() != ".gguf":
            continue

        # Calcul du score
        score = score_candidate(file)

        # On garde uniquement les scores positifs
        if score > 0:
            candidates.append((score, file))

    # =============================================================================
    # Aucun candidat trouvé
    # =============================================================================

    if not candidates:
        return None

    # =============================================================================
    # Tri décroissant par score
    # =============================================================================

    candidates.sort(reverse=True, key=lambda x: x[0])

    # =============================================================================
    # Meilleur candidat
    # =============================================================================

    best_score, best_file = candidates[0]

    # =============================================================================
    # Vérification finale
    # =============================================================================

    if best_score <= 0:
        return None

    # =============================================================================
    # Succès
    # =============================================================================

    return str(best_file)

def get_chat_handler(model_path, mmproj_path, verbose=False, use_gpu=True):

    model_name = os.path.basename(model_path).lower()

    # =============================================================================
    # Qwen3-VL
    # =============================================================================
    if "qwen3-vl" in model_name or "qwen3_vl" in model_name:

        try:
            from llama_cpp.llama_chat_format import Qwen3VLChatHandler

            return Qwen3VLChatHandler(
                clip_model_path=mmproj_path,
                force_reasoning=False,
                verbose=verbose
            )

        except Exception as e:
            print("Unable to load Qwen3VLChatHandler:", e)
            return None

    # =============================================================================
    # Qwen 3.5
    # =============================================================================
    elif (
        "qwen3.5" in model_name
        or "qwen35" in model_name
        or "qwen-3.5" in model_name
    ):

        try:
            from llama_cpp.llama_chat_format import Qwen35ChatHandler

            return Qwen35ChatHandler(
                clip_model_path=mmproj_path,
                verbose=verbose,
                use_gpu=use_gpu
            )

        except Exception as e:
            print("Unable to load Qwen35ChatHandler:", e)
            return None

    return None