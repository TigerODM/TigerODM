import os

if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.utils import SimpleDialogQt
    from Orange.widgets.orangecontrib.AAIT.utils.MetManagement import (
        GetFromRemote,
        get_local_store_path,
        ensure_file_exists_recursive,
    )
else:
    from orangecontrib.AAIT.utils import SimpleDialogQt
    from orangecontrib.AAIT.utils.MetManagement import (
        GetFromRemote,
        get_local_store_path,
        ensure_file_exists_recursive,
    )

# Mapping between AAIT remote keys and local resources.
# Value can be:
# Cas 1
# "Model": "Models/NLP/model.gguf"
# dans ce cas ca renverra le chemin
# # Cas 2
# "Spacy FR": (
#     "Models/NLP/fr_core_news_md",
#     "fr_core_news_md-3.7.0"
# )
#dans ce cas ca renverra #     "Models/NLP/fr_core_news_md/fr_core_news_md-3.7.0"
# mais on sais que ca a besoin du dossier "Models/NLP/fr_core_news_md" pour une fonction de generation de json
# # Cas 3
# "Qwen3 VL 8B": (
#     [
#         "Qwen3-VL-8B-Instruct-Q4_K_M.gguf",
#         "mmproj-Qwen3-VL-8B-Instruct.gguf"
#     ],
#     os.path.join("Models", "NLP", "Qwen3-VL-8B")
# )
#ca renvoie le dernier chemin mais on sait que l on a besoin d une liste de fichier pour une fonction de generation de json
file_mapping = {
    "Qwen Model Coder": os.path.join("Models", "NLP", "Qwen2.5.1-Coder-7B-Instruct-Q6_K.gguf"),
    "MPNET BASE V2": os.path.join("Models", "NLP", "all-mpnet-base-v2"),
    "Cross encoder MiniLM L6": os.path.join("Models", "NLP", "cross-encoder_MiniLM-L6"),
    "Falcon 7B Model": os.path.join("Models", "NLP", "falcon3-7b-instruct-q6_k.gguf"),
    "Helsinki EN FR": os.path.join("Models", "NLP", "helsinki_en_fr"),
    "Helsinki FR EN": os.path.join("Models", "NLP", "helsinki_fr_en"),
    "Qwen Model 1.5B Q6": os.path.join("Models", "NLP", "qwen2.5-1.5b-instruct-q6_k.gguf"),
    "Mistral Model": os.path.join("Models", "NLP", "Mistral-7B-Instruct-v0.3.Q6_K.gguf"),
    "Qwen Model 32B Q4": os.path.join("Models", "NLP", "qwen2.5-32b-instruct-q4_k_m.gguf"),
    "Qwen Model 7B Q4": os.path.join("Models", "NLP", "Qwen2.5-Dyanka-7B-Preview.Q4_K_M.gguf"),
    "Qwen Model 3B Q4": os.path.join("Models", "NLP", "qwen2.5-3b-instruct-q4_k_m.gguf"),
    "Qwen Model 7B Q6": os.path.join("Models", "NLP", "Qwen2.5-Dyanka-7B-Preview.Q6_K.gguf"),
    "Solar Model Uncensored": os.path.join("Models", "NLP", "solar-10.7b-instruct-v1.0-uncensored.Q6_K.gguf"),
    "Solar Model": os.path.join("Models", "NLP", "solar-10.7b-instruct-v1.0.Q6_K.gguf"),
    "Spacy MD EN":(os.path.join("Models", "NLP", "en_core_web_md"),"en_core_web_md-3.7.1"),
    "Spacy MD FR":(os.path.join("Models", "NLP", "fr_core_news_md"), "fr_core_news_md-3.7.0"),
    "Tokenizer - Qwen3 8B": os.path.join("Models", "NLP", "Tokenizer_Qwen3-8B"),
    "DinoV2":os.path.join("Models", "ComputerVision", "dinov2-base"),
    "ResNet50":os.path.join("Models","ComputerVision","resnet50","resnet50-0676ba61.pth"),
    "Paddle OCR": ([os.path.join("Models", "ComputerVision", "PaddleOCR", "PP-OCRv5_server_det"), os.path.join("Models", "ComputerVision", "PaddleOCR", "latin_PP-OCRv5_mobile_rec")], os.path.join("Models", "ComputerVision", "PaddleOCR", "PP-OCRv5_server_det", "inference.yml")),
    "Qwen3.5 9B Q6": ([os.path.join("Models","NLP","Qwen3.5-9B-GGUF","Qwen3.5-9B-Q6_K.gguf"),os.path.join("Models","NLP","Qwen3.5-9B-GGUF","mmproj-F16.gguf")],os.path.join("Models","NLP","Qwen3.5-9B-GGUF","Qwen3.5-9B-Q6_K.gguf")),
    # a verifier
    "Qwen3.5 4B Q4": ([os.path.join("Models","NLP","Qwen3.5-4B-GGUF","Qwen3.5-4B-Q4_K_M.gguf"),os.path.join("Models","NLP","Qwen3.5-4B-GGUF","mmproj-F16.gguf")],os.path.join("Models","NLP","Qwen3.5-4B-GGUF","Qwen3.5-4B-Q4_K_M.gguf")),
    "Qwen3 1.7B (Q2)": os.path.join("Models", "NLP","Qwen3-1.7B-Q2_K_L.gguf"),
    "Qwen3 1.7B": os.path.join("Models", "NLP","Qwen3-1.7B-Q6_K.gguf"),
    "Qwen3 4B": os.path.join("Models", "NLP","Qwen3-4B-Q4_K_M.gguf"),
    "Qwen3 VL 8B": ([os.path.join("Models","NLP","qwen3VL","mmproj-Qwen3-VL-8B-Instruct-F16.gguf"),os.path.join("Models","NLP","qwen3VL","Qwen3-VL-8B-Instruct-Q4_K_M.gguf")],os.path.join("Models","NLP","qwen3VL","Qwen3-VL-8B-Instruct-Q4_K_M.gguf")),
    "Qwen3 8B": os.path.join("Models", "NLP","Qwen3-8B-Q4_K_M.gguf"),
    "Qwen3 14B": os.path.join("Models", "NLP","Qwen3-14B-Q4_K_M.gguf"),
    "Granite4 7B": os.path.join("Models", "NLP","granite-4.0-h-tiny-Q4_K_M.gguf"),
    "Phi4 4B": os.path.join("Models", "NLP","Phi-4-mini-reasoning-Q4_K_M.gguf"),
    "Gemma3 270m": os.path.join("Models", "NLP","gemma-3-270m-Q8_0.gguf"),
    "Gemma3 12B": os.path.join("Models", "NLP", "gemma-3-12b-it-Q4_K_M.gguf",),
    "Deepseek 8B": os.path.join("Models", "NLP", "DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf"),
    "Gemma 4 E2B Q4":([os.path.join("Models","NLP","gemma-4-E2B-qat-Q4-GGUF","mmproj-F16.gguf"),os.path.join("Models","NLP","gemma-4-E2B-qat-Q4-GGUF","gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf")],os.path.join("Models","NLP","gemma-4-E2B-qat-Q4-GGUF","gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf")),

}
# pour etre independant de la casse
file_mapping_lower = {
    key.lower(): key
    for key in file_mapping
}


def get_path_or_retrieve(aait_remote_key: str, download_if_necessary: bool = True) -> str:
    """
    Returns the local path corresponding to a remote key.

    Supported file_mapping formats:

        "key": "relative/path"

        "key": (
            "relative/path",
            "optional/sub/path"
        )

        "key": (
            ["file1", "file2", ...],
            "relative/path"
        ) # attention la liste n'est qu'indicative et n'est pas utilisée

    if download_if_necessary==False and resource not found, returns "".

    Raises
    ------
    ValueError
        If the key is unknown.
    """
    try:
        real_key = file_mapping_lower[aait_remote_key.lower()]
        mapping_value = file_mapping[real_key]

        optional_value = None

        if isinstance(mapping_value, tuple):

            # New format:
            # (["file1","file2"], "relative/path")
            if (
                len(mapping_value) == 2
                and isinstance(mapping_value[0], list)
            ):
                relative_path=mapping_value[1]
            # Existing format:
            # ("relative/path", "optional/sub/path")
            else:
                relative_path = mapping_value[0]
                optional_value = mapping_value[1]

        else:
            relative_path = mapping_value

    except KeyError:
        raise ValueError(
            f"Unknown aait_remote_key: '{aait_remote_key}'"
        )

    local_path = os.path.join(
        get_local_store_path(),
        relative_path
    ).replace("\\", "/")

    list_tr = [local_path]

    if ensure_file_exists_recursive(list_tr):
        if optional_value is None:
            return list_tr[0]

        return str(
            os.path.normpath(
                os.path.join(
                    list_tr[0],
                    str(optional_value)
                )
            ).replace("\\", "/")
        )
    if not download_if_necessary:
        return ""# modele non trouvé
    if not SimpleDialogQt.BoxYesNo(
        "Model isn't in your computer. Do you want to download it from AAIT store?"
    ):
        raise ValueError(
            f"User don't want to download: '{real_key}' : '{relative_path}'"
        )

    try:
        ret = GetFromRemote(real_key)
    except Exception:
        SimpleDialogQt.BoxError("Unable to get the Model.")
        raise ValueError(
            f"Error can not download: '{real_key}' : '{relative_path}'"
        )

    if ret != 0:
        SimpleDialogQt.BoxError("Unable to get the Model.")
        raise ValueError(
            f"Error can not download: '{real_key}' : '{relative_path}'"
        )

    if ensure_file_exists_recursive(list_tr):
        if optional_value is None:
            return list_tr[0]

        return str(
            os.path.normpath(
                os.path.join(
                    list_tr[0],
                    str(optional_value)
                )
            ).replace("\\", "/")
        )

    raise ValueError(
        f"Error can not get: '{real_key}' : '{relative_path}'"
    )


def export_file_mapping_to_json(file_mapping, output_json_path, keys_to_export=None):
    """
    Export file_mapping to a JSON file.

    Returns
    -------
    int
        0 if success, 1 if error.
    """
    try:
        if keys_to_export is None:
            keys_to_export = list(file_mapping.keys())

        lines = ["["]

        for index, key in enumerate(keys_to_export):

            if key not in file_mapping:
                raise KeyError(f"Key not found in file_mapping: {key}")

            value = file_mapping[key]

            # Cas 1 : str
            if isinstance(value, str):
                extra_datas = [value]

            # Cas 2 ou Cas 3
            elif isinstance(value, tuple) and len(value) == 2:

                # Cas 2 : (str, option)
                if isinstance(value[0], str):
                    extra_datas = [value[0]]

                # Cas 3 : ([paths...], main_path)
                elif isinstance(value[0], list):
                    extra_datas = value[0]

                else:
                    raise TypeError(f"Unsupported tuple format for key: {key}")

            else:
                raise TypeError(f"Unsupported value format for key: {key}")

            extra_datas = [
                os.path.normpath(str(path)).replace("\\", "/")
                for path in extra_datas
            ]

            lines.append("    {")

            lines.append(f'        "name": "{key}",')
            lines.append('        "workflows": [ "" ],')

            extra_data_str = ", ".join(
                f'"{path}"'
                for path in extra_datas
            )
            lines.append(f'        "extra_datas": [ {extra_data_str} ],')

            lines.append('        "metdir_datas": [ "" ],')
            lines.append(f'        "description": [ "{key}" ]')

            if index < len(keys_to_export) - 1:
                lines.append("    },")
            else:
                lines.append("    }")

        lines.append("]")

        output_dir = os.path.dirname(os.path.abspath(output_json_path))
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(output_json_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return 0

    except Exception as e:
        print(f"Error while exporting file_mapping to JSON: {e}")
        return 1

if __name__ == "__main__":
    import sys
    from AnyQt.QtWidgets import QApplication
    app = QApplication(sys.argv)
    # try:
    #     path = get_path_or_retrieve("Qwen3.5 9B Q6",True)
    #     print("--->",path)
    # except Exception as e:
    #     print(e)
    export_file_mapping_to_json(file_mapping,"C:/pas_probleme/toto.json")
    # regarder orangecontrib\AAIT\utils\aait_repo_file.py