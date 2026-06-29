import os

prompt_templates = {
    "llama": {
        "system": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n{system_prompt}<|eot_id|>",
        "user": "<|start_header_id|>user<|end_header_id|>\n{user_prompt}<|eot_id|>",
        "assistant": "<|start_header_id|>assistant<|end_header_id|>\n{assistant_prompt}"
    },

    "mistral": {
        "system": "{system_prompt}\n",
        "user": "<s>[INST] {user_prompt} [/INST]</s>\n",
        "assistant": "{assistant_prompt}"
    },

    "solar": {
        "system": "{system_prompt}\n",
        "user": "### User: {user_prompt}\n",
        "assistant": "### Assistant: {assistant_prompt}"
    },

    "deepseek": {
        "system": "{system_prompt}\n",
        "user": "### Instruction: {user_prompt}\n",
        "assistant": "### Response: {assistant_prompt}"
    },

    "qwen": {
        "system": "<|im_start|>system\n{system_prompt}<|im_end|>\n",
        "user": "<|im_start|>user\n{user_prompt}<|im_end|>\n",
        "assistant": "<|im_start|>assistant\n{assistant_prompt}"
    },

    "gemma": {
        "system": "{system_prompt}\n",
        "user": "<start_of_turn>user\n{user_prompt}<end_of_turn>\n",
        "assistant": "<start_of_turn>model\n{assistant_prompt}\n"
    },

    "granite": {
        "system": "<|system|>\n{system_prompt}\n",
        "user": "<|user|>\n{user_prompt}\n",
        "assistant": "<|assistant|>\n{assistant_prompt}"
    },

    "phi": {
        "system": "<|im_start|>system<|im_sep|>\n{system_prompt}<|im_end|>\n",
        "user": "<|im_start|>user<|im_sep|>\n{user_prompt}<|im_end|>\n",
        "assistant": "<|im_start|>assistant<|im_sep|>\n{assistant_prompt}"
    },

    "default": {
        "system": "{system_prompt}",
        "user": "{user_prompt}",
        "assistant": "{assistant_prompt}"
    }
}



stop_tokens = {
    "llama": "<|eot_id|>",
    "mistral": "</s>",
    "qwen": "<|im_end|>",
    "gemma": "<end_of_turn>",
    "granite": "<|endoftext|>",
    "phi": "<|im_end|>",
    "solar": "</s>",  #chattyboy
    "deepseek": "<|EOT|>", # chattyboy
}


model_types = {

    # Qwen
    "qwen2.5.1-coder": "qwen",
    "qwen2.5-coder": "qwen",
    "qwen2.5": "qwen",
    "qwen2": "qwen",
    "qwen3": "qwen",
    "qwen": "qwen",

    # Mistral
    "mistral": "mistral",
    "mixtral": "mistral",

    # Solar
    "solar": "solar",

    # DeepSeek
    "deepseek": "deepseek",

    # Llama
    "llama-4": "llama",
    "llama-3": "llama",
    "llama3": "llama",
    "llama": "llama",

    # Gemma
    "gemma-3": "gemma",
    "gemma-2": "gemma",
    "gemma": "gemma",

    # Granite
    "granite": "granite",

    # Phi
    "phi-4": "phi",
    "phi-3.5": "phi",
    "phi-3": "phi",
    "phi3": "phi",
    "phi": "phi",
}


def get_model_type(model_path):
    """
    Détecte le type du modèle à partir du nom du GGUF.
    """
    model_name = os.path.basename(model_path).lower()
    # Recherche tolérante
    for keyword, model_type in model_types.items():
        if keyword in model_name:
            return model_type

    # Fallback
    return "qwen"


def apply_prompt_template(model_path, user_prompt, assistant_prompt="", system_prompt="", force_non_thinking=False):
    """
    Apply a prompt template based on the given model name and user input.

    Parameters:
        model_path (str): The name of the model used to determine its type.
        user_prompt (str): The user input or request to embed into the prompt.
        assistant_prompt (str, optional): The assistant's beginning of response, if any. Defaults to an empty string.
        system_prompt (str, optional): A system-level instruction or context to include in the prompt. Defaults to an empty string.

    Returns:
        str: The formatted prompt that is ready to be passed to the model.
    """
    # Try to identify the model's type
    model_type = get_model_type(model_path)
    # Retrieve the template
    template = prompt_templates.get(model_type, prompt_templates["default"])  # Default template if none found
    # Apply the template
    prompt = ""
    if system_prompt is not None:
        prompt += template["system"].format(system_prompt=system_prompt)
    prompt += template["user"].format(user_prompt=user_prompt)
    prompt += template["assistant"].format(assistant_prompt=assistant_prompt)
    if force_non_thinking:
        prompt += "<think>\n\n</think>"
    return prompt


def apply_system_template(model_path, system_prompt):
    model_type = get_model_type(model_path)
    template = prompt_templates.get(model_type, prompt_templates["default"])
    return template["system"].format(system_prompt=system_prompt)

def apply_user_template(model_path, user_prompt):
    model_type = get_model_type(model_path)
    template = prompt_templates.get(model_type, prompt_templates["default"])
    return template["user"].format(user_prompt=user_prompt)

def apply_assistant_template(model_path, assistant_prompt, is_last=True):
    model_type = get_model_type(model_path)
    template = prompt_templates.get(model_type, prompt_templates["default"])
    text = template["assistant"].format(assistant_prompt=assistant_prompt)
    # Append <|im_end|> for all but the last assistant message
    if not is_last:
        text += "<|im_end|>\n"
    return text

def apply_template_to_conversation(model_path, conversation):
    prompt = ""
    for i, message in enumerate(conversation):
        is_last = (i == len(conversation) - 1)
        if message["role"] == "system":
            prompt += apply_system_template(model_path, message["content"])
        elif message["role"] == "user":
            prompt += apply_user_template(model_path, message["content"])
        elif message["role"] == "assistant":
            prompt += apply_assistant_template(model_path, message["content"], is_last=is_last)
    prompt += apply_assistant_template(model_path, "")
    return prompt


def apply_template_to_conversation_2(model_path, conversation):
    prompt = ""
    for i, message in enumerate(conversation):
        is_last = (i == len(conversation) - 1)
        role = message["role"]
        content = message["content"]

        # Normalize content → always iterable list of strings
        if isinstance(content, str):
            contents = [content]
        elif isinstance(content, list):
            contents = [
                entry.get("text", "")
                for entry in content
                if "text" in entry
            ]
        else:
            contents = [""]

        if role == "system":
            prompt += apply_system_template(model_path, contents[0])
        elif role == "user":
            for text in contents:
                prompt += apply_user_template(model_path, text)
        elif role == "assistant":
            for j, text in enumerate(contents):
                # Only last chunk of last assistant message gets is_last=True
                last_chunk = is_last and (j == len(contents) - 1)
                prompt += apply_assistant_template(model_path, text, is_last=last_chunk)

    # Ensure generation prompt if last message isn't assistant
    if conversation[-1]["role"] != "assistant":
        prompt += apply_assistant_template(model_path, "")
    return prompt


def get_stop_token(model_name):
    """
    Get the stop token according to the model name / type.

    Parameters:
        model_name (str): The name of the model used to determine its type.
    """
    # If there is a stop token
    try:
        # Get the model type
        model_type = get_model_type(model_name)
        # Get the template for the model type
        stop_token = stop_tokens[model_type]
    except KeyError as e:
        print(f"Your model {model_name} has no stop token defined. See prompt_management.py. (detail: {e})")
        return None
    return stop_token





