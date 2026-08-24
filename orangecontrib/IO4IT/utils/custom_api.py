import base64
import mimetypes
import os

import requests

import Orange.data
from Orange.data import StringVariable


def build_headers(header_name, auth_scheme, api_key):
    header_name = (header_name or "Authorization").strip()
    auth_scheme = (auth_scheme or "").strip()
    value = f"{auth_scheme} {api_key}".strip() if auth_scheme else str(api_key)
    return {"Content-Type": "application/json", header_name: value}


def image_to_data_uri(file_path):
    """Encode a local image file as a base64 data URI."""
    mime_type, _ = mimetypes.guess_type(file_path)
    mime_type = mime_type or "application/octet-stream"
    with open(file_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def build_user_content(prompt, image_paths):
    """Build the 'content' field of a user message, attaching images when provided."""
    if not image_paths:
        return str(prompt)

    content = []
    for image_path in image_paths:
        image_path = image_path.strip().strip("'").strip('"')
        if not image_path:
            continue
        if not os.path.exists(image_path):
            content.append({"type": "text", "text": f"[ERROR] Image not found: {image_path}"})
            continue
        try:
            content.append({"type": "image_url", "image_url": {"url": image_to_data_uri(image_path)}})
        except Exception as e:
            content.append({"type": "text", "text": f"[ERROR] Unable to read image {image_path}: {e}"})
    content.append({"type": "text", "text": str(prompt)})
    return content


def call_chat_completion(prompt, system_prompt, config, image_paths=None):
    """
    Call a /chat/completions endpoint using the widely adopted chat-completions
    message format. Vision-capable models can be reached by passing image_paths,
    which are embedded in the user message as base64 data URIs.

    config keys: base_url, route, header_name, auth_scheme, api_key,
                 model, max_tokens, temperature, cert_path, cert_is_ca,
                 proxy_url
    """
    url = config["base_url"].rstrip("/") + config["route"]
    headers = build_headers(config["header_name"], config["auth_scheme"], config["api_key"])

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": str(system_prompt)})
    messages.append({"role": "user", "content": build_user_content(prompt, image_paths)})

    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": config["temperature"],
        "max_tokens": config["max_tokens"],
    }

    kwargs = {"timeout": 600}
    cert_path = config.get("cert_path")
    if cert_path:
        if config.get("cert_is_ca"):
            kwargs["verify"] = cert_path
        else:
            kwargs["cert"] = cert_path

    if config.get("use_proxy"):
        # Explicitly set, even when empty: an empty value forces a direct
        # connection and bypasses any http_proxy/https_proxy environment
        # variable (e.g. the one Orange itself sets from its preferences),
        # instead of silently inheriting it.
        proxy_url = config.get("proxy_url") or ""
        kwargs["proxies"] = {"http": proxy_url, "https": proxy_url}

    response = requests.post(url, headers=headers, json=payload, **kwargs)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def generate_answers(data, config, progress_callback=None):
    """
    Runs call_chat_completion for every row of `data` (needs a 'prompt' column,
    optionally a 'system_prompt' column and an 'image paths' column for
    vision-capable models) and returns a new Table with an added 'Answer'
    string column.

    The 'image paths' column, when present, holds one or more image file
    paths separated by ';' for that row.
    """
    domain = data.domain
    has_system_prompt = "system_prompt" in domain
    has_images = "image paths" in domain

    prompts = data.get_column("prompt")
    system_prompts = data.get_column("system_prompt") if has_system_prompt else None
    image_paths_column = data.get_column("image paths") if has_images else None

    answers = []
    n_rows = len(data)
    for i in range(n_rows):
        prompt = prompts[i]
        system_prompt = system_prompts[i] if system_prompts is not None else None
        image_paths = image_paths_column[i].split(";") if image_paths_column is not None else None
        try:
            answer = call_chat_completion(prompt, system_prompt, config, image_paths)
        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else str(e)
            answer = f"[ERROR] HTTP {e.response.status_code if e.response is not None else '?'}: {body}"
        except Exception as e:
            answer = f"[ERROR] {e}"

        answers.append(answer)
        if progress_callback is not None:
            progress_callback((int(100 * (i + 1) / max(n_rows, 1)), f"Row {i + 1}/{n_rows} done\n"))

    answer_var = StringVariable("Answer")
    return data.add_column(answer_var, answers)
