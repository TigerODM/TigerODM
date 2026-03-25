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
    "phi": "<|im_end|>"
}


model_types = {
    "solar-10.7b-instruct-v1.0.Q6_K.gguf": "solar",
    "solar-10.7b-instruct-v1.0-uncensored.Q6_K.gguf": "solar",
    "Mistral-7B-Instruct-v0.3.Q6_K.gguf": "mistral",
    "Qwen2.5.1-Coder-7B-Instruct-Q6_K.gguf": "qwen",
    "qwen2.5-3b-instruct-q4_k_m.gguf": "qwen",
    "deepseek-coder-6.7b-instruct.Q6_K.gguf": "deepseek"
}

model_keywords = ["qwen", "solar", "mistral", "llama", "deepseek", "gemma", "granite", "phi"]



def get_model_type(model_path):
    model_name = os.path.basename(model_path)
    model_type = model_types.get(model_name)
    if model_type is None:
        model_type = next((keyword for keyword in model_keywords if keyword in model_name.lower()), None)
    if model_type is None:
        model_type = "default"
    return model_type


def apply_prompt_template(model_path, user_prompt, assistant_prompt="", system_prompt=""):
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
    return prompt


def apply_system_template(model_path, system_prompt):
    model_type = get_model_type(model_path)
    template = prompt_templates.get(model_type, prompt_templates["default"])
    return template["system"].format(system_prompt=system_prompt)

def apply_user_template(model_path, user_prompt):
    model_type = get_model_type(model_path)
    template = prompt_templates.get(model_type, prompt_templates["default"])
    return template["user"].format(user_prompt=user_prompt)

def apply_assistant_template(model_path, assistant_prompt):
    model_type = get_model_type(model_path)
    template = prompt_templates.get(model_type, prompt_templates["default"])
    return template["assistant"].format(assistant_prompt=assistant_prompt)


def get_stop_token(model_name):
    """
    Get the stop token according to the model name / type.

    Parameters:
        model_name (str): The name of the model used to determine its type.
    """
    # If there is a stop token
    try:
        # Get the model type
        model_type = model_types[model_name]
        # Get the template for the model type
        stop_token = stop_tokens[model_type]
    except KeyError as e:
        print(f"Your model {model_name} has no stop token defined. See prompt_management.py. (detail: {e})")
        return None
    return stop_token





