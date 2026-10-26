import os
import re
import json
import copy
import numpy as np

import requests

from Orange.data import StringVariable, Table


if "site-packages/Orange/widgets" in os.path.dirname(os.path.abspath(__file__)).replace("\\", "/"):
    from Orange.widgets.orangecontrib.AAIT.llm.answers_llama import write_tokens_to_file, prompt_to_messages, conv_to_messages
else:
    from orangecontrib.AAIT.llm.answers_llama import write_tokens_to_file, prompt_to_messages, conv_to_messages


def build_headers(header_name, auth_scheme, api_key):
    header_name = (header_name or "Authorization").strip()
    auth_scheme = (auth_scheme or "").strip()
    value = f"{auth_scheme} {api_key}".strip() if auth_scheme else str(api_key)
    return {"Content-Type": "application/json", header_name: value}


def list_models(config):
    """
    GET Base URL + /models and return the list of model ids exposed by an
    OpenAI-compatible endpoint (llama-server, vLLM, OpenAI, ...).

    Expects Base URL to already include the API version prefix if the
    server uses one, e.g. "http://127.0.0.1:8080/v1".

    config keys: base_url, header_name, auth_scheme, api_key, cert_path,
                 cert_is_ca, use_proxy, proxy_url
    """
    url = config["base_url"].rstrip("/") + "/models"
    api_key = config.get("api_key")
    if api_key:
        headers = build_headers(config["header_name"], config["auth_scheme"], api_key)
    else:
        headers = {"Content-Type": "application/json"}

    kwargs = {"timeout": 30}
    cert_path = config.get("cert_path")
    if cert_path:
        if config.get("cert_is_ca"):
            kwargs["verify"] = cert_path
        else:
            kwargs["cert"] = cert_path

    if config.get("use_proxy"):
        proxy_url = config.get("proxy_url") or ""
        kwargs["proxies"] = {"http": proxy_url, "https": proxy_url}

    response = requests.get(url, headers=headers, **kwargs)
    response.raise_for_status()
    data = response.json()
    return [m.get("id", "?") for m in data.get("data", [])]


def search_for_streamed_token(decoded_line):
    r"""
    /!\ This function is meant to be updated whenever a new response format is identified /!\

    Parse a decoded stream response "line" and return (kind, token), where
    kind is "content" for actual answer text, "reasoning" for a model's
    internal thinking trace (some reasoning models, e.g. Qwen3 through
    llama-server, stream it in a separate delta field: "reasoning" or
    "reasoning_content" depending on server version), or None if the line
    carries no usable token.
    """
    reasoning_keys = ("reasoning", "reasoning_content")
    dict_regex = r"\{[\s\S]*\}"
    match = re.search(dict_regex, decoded_line)
    if not match:
        return None, ""

    json_data = json.loads(match.group())
    # "choices" can be an empty list on the last chunk of a stream, e.g.
    # llama-server sends {"choices": [], "usage": {...}, ...} right before
    # [DONE] once "usage" reporting is involved.
    choices = json_data.get("choices") or []
    if not choices:
        return None, ""
    delta = choices[0].get("delta", {})
    # .get(key) (not "key in delta") also skips a key whose value is
    # JSON null, e.g. {"delta": {"role": "assistant", "content": null}},
    # which some OpenAI-compatible servers (llama-server included) send.
    if delta.get("content"):
        return "content", delta["content"]
    for key in reasoning_keys:
        if delta.get(key):
            return "reasoning", delta[key]
    # Diagnostic: if the delta carries something we don't recognize (e.g. a
    # model's thinking trace under a key that isn't "reasoning" or
    # "reasoning_content" on this particular server), log it so the actual
    # key name shows up in the console instead of silently dropping it.
    ignored_keys = {"role", "tool_calls", "function_call", "refusal"}
    unknown = {k: v for k, v in delta.items() if k not in ignored_keys and v}
    if unknown:
        print("search_for_streamed_token: unrecognized delta keys, please report ->", unknown)
    return None, ""


_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


def strip_thinking(text):
    """
    Some reasoning models (e.g. Qwen3 served through llama-server) emit
    their internal <think>...</think> trace as regular streamed content,
    since it isn't split into a separate delta field. Strip it out so it
    doesn't end up in the final answer.
    """
    return _THINK_BLOCK_RE.sub("", text).strip()


def call_chat_completion(messages, config, stream=False, workflow_id="Request_RAG"):
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

    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": config["temperature"],
        "max_tokens": config["max_tokens"],
        "stream": stream,
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

    response = requests.post(url, headers=headers, json=payload, stream=stream, **kwargs)
    response.raise_for_status()

    if not stream:
        data = response.json()
        return strip_thinking(data["choices"][0]["message"]["content"])
    else:
        answer = ""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode("utf-8")
                try:
                    kind, token = search_for_streamed_token(decoded_line)
                except Exception as e:
                    kind, token = None, ""
                    print("An error occured when trying to get token from stream response:", e)
                # Only actual answer content goes into the final answer;
                # a model's reasoning/thinking trace is deliberately dropped.
                if kind == "content":
                    answer += token
                write_tokens_to_file(token, workflow_id=workflow_id)
        return strip_thinking(answer)


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
        messages = prompt_to_messages(prompt, system_prompt, image_paths)
        try:
            answer = call_chat_completion(messages, config, stream=True, workflow_id=config.get("workflow_id") or "")
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



def continue_conversation(table, config, progress_callback=None):
    """
    Runs call_chat_completion considering the table as a conversation (list of messages).
    """
    data = copy.deepcopy(table)
    messages = conv_to_messages(data)
    if not messages:
        return data

    try:
        answer = call_chat_completion(messages, config, stream=True, workflow_id=config.get("workflow_id") or "")
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else str(e)
        answer = f"[ERROR] HTTP {e.response.status_code if e.response is not None else '?'}: {body}"
    except Exception as e:
        answer = f"[ERROR] {e}"

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
