import copy
import types

import pytest


# --- generate_answers: query_parameters=None --------------------------------
class _Domain(list):
    attributes = []
    metas = []
    class_vars = []


class _Table:
    def __init__(self):
        self.domain = _Domain()


def test_generate_answers_without_query_parameters_reaches_model_loading(modules, monkeypatch):
    """Before the fix, query_parameters=None raised TypeError at the first
    query_parameters["k_cache"], before the fallback dict was ever built."""
    al = modules.answers_llama
    seen = {}

    def fake_load_model(**kwargs):
        seen.update(kwargs)
        return None  # generate_answers then returns None

    monkeypatch.setattr(al, "load_model", fake_load_model)
    assert al.generate_answers(_Table(), "m.gguf", use_gpu=False, query_parameters=None) is None
    assert seen["k_cache"] == 1 and seen["v_cache"] == 1


def test_generate_answers_explicit_query_parameters_untouched(modules, monkeypatch):
    # negative control for "the fallback only applies when None"
    al = modules.answers_llama
    seen = {}
    monkeypatch.setattr(al, "load_model", lambda **kw: seen.update(kw))
    qp = {"max_tokens": 5, "k_cache": 8, "v_cache": 8, "reasoning": False}
    al.generate_answers(_Table(), "m.gguf", use_gpu=False, query_parameters=qp)
    assert seen["k_cache"] == 8 and seen["v_cache"] == 8
    assert qp == {"max_tokens": 5, "k_cache": 8, "v_cache": 8, "reasoning": False}


# --- reasoning default on the image path ---------------------------------------
class _ImageTable(_Table):
    def __init__(self):
        super().__init__()
        self.domain.append("image paths")


def _record_handler(al, monkeypatch):
    seen = {}
    monkeypatch.setattr(al, "load_model_with_handler", lambda *a, **kw: seen.update(kw))
    return seen


def test_generate_answers_default_reasoning_is_true_on_image_path(modules, monkeypatch):
    al = modules.answers_llama
    seen = _record_handler(al, monkeypatch)
    al.generate_answers(_ImageTable(), "m.gguf", use_gpu=False, query_parameters=None)
    assert seen["reasoning"] is True  # thinking stays on by default


def test_generate_answers_explicit_reasoning_false_is_kept(modules, monkeypatch):
    al = modules.answers_llama
    seen = _record_handler(al, monkeypatch)
    qp = {"max_tokens": 5, "k_cache": 1, "v_cache": 1, "reasoning": False}
    al.generate_answers(_ImageTable(), "m.gguf", use_gpu=False, query_parameters=qp)
    assert seen["reasoning"] is False


# --- continue_conversation: query_parameters=None ---------------------------
def test_continue_conversation_without_query_parameters_text_model(modules, monkeypatch):
    al = modules.answers_llama
    seen = {}
    monkeypatch.setattr(al.handler_llama, "find_mmproj_path", lambda p: None, raising=False)
    monkeypatch.setattr(al, "load_model", lambda **kw: seen.update(kw))
    assert al.continue_conversation(_Table(), "m.gguf", use_gpu=False, query_parameters=None) is None
    assert seen["k_cache"] == 1 and seen["v_cache"] == 1


def test_continue_conversation_without_query_parameters_handler(modules, monkeypatch):
    al = modules.answers_llama
    seen = _record_handler(al, monkeypatch)
    monkeypatch.setattr(al.handler_llama, "find_mmproj_path", lambda p: "mm.gguf", raising=False)
    al.continue_conversation(_Table(), "m.gguf", use_gpu=False, query_parameters=None)
    assert seen["reasoning"] is True


# --- split_think -------------------------------------------------------------
def test_split_think_qwen_and_gemma4(modules):
    st = modules.answers_llama.split_think
    assert st("<think>because</think>Yes") == ("because", "Yes")
    assert st("<|channel>thought\nhmm<channel|>No") == ("hmm", "No")


def test_split_think_no_close_tag_is_not_reasoning(modules):
    # refuse: without a closing tag nothing is split off
    st = modules.answers_llama.split_think
    assert st("plain answer") == ("", "plain answer")
    assert st("<think>cut by max_tokens") == ("", "cut by max_tokens")
    assert st("") == ("", "")


# --- handle_context_length ---------------------------------------------------
class _FakeModel:
    def tokenize(self, b):
        return list(b.decode().split())

    def detokenize(self, tokens):
        return " ".join(tokens).encode()


def test_handle_context_length_truncates_keeping_the_end(modules):
    f = modules.answers_llama.handle_context_length
    msgs = []
    out = f("a b c d e", _FakeModel(), n_ctx=4, margin=1, progress_callback=msgs.append)
    assert out == "c d e"
    assert msgs and msgs[0][0] == "warning"


def test_handle_context_length_short_prompt_untouched(modules):
    f = modules.answers_llama.handle_context_length
    msgs = []
    assert f("a b", _FakeModel(), n_ctx=4, margin=1, progress_callback=msgs.append) == "a b"
    assert msgs == []


# --- prompt_management ------------------------------------------------------
def test_get_model_type(modules):
    g = modules.prompt_management.get_model_type
    assert g("/x/gemma-4-E2B-it.gguf") == "gemma"
    assert g("Qwen3-4B.gguf") == "qwen"
    assert g("something-unknown.gguf") == "qwen"  # documented fallback


def test_apply_prompt_template_and_force_non_thinking(modules):
    a = modules.prompt_management.apply_prompt_template
    p = a("qwen3.gguf", user_prompt="hi", system_prompt="sys")
    assert p == "<|im_start|>system\nsys<|im_end|>\n<|im_start|>user\nhi<|im_end|>\n<|im_start|>assistant\n"
    # allow / refuse: the empty think block is added only on request
    assert a("qwen3.gguf", user_prompt="hi", force_non_thinking=True).endswith("<think>\n\n</think>")
    assert "<think>" not in p


def test_get_stop_token(modules):
    g = modules.prompt_management.get_stop_token
    assert g("gemma-4.gguf") == "<end_of_turn>"
    assert g("granite.gguf") == "<|endoftext|>"


# --- handler_llama.is_a_thinking_model -------------------------------------
def _m(path, **metadata):
    return types.SimpleNamespace(model_path=path, metadata=metadata)


def test_thinking_model_known_names(modules):
    f = modules.handler_llama.is_a_thinking_model
    assert f(_m("/m/DeepSeek-R1-Distill-7B.gguf")) is True
    assert f(_m("/m/gemma-4-12b-it.gguf")) is True


def test_non_thinking_model_known_names(modules):
    f = modules.handler_llama.is_a_thinking_model
    assert f(_m("/m/gemma-4-E2B-it.gguf")) is False
    assert f(_m("/m/phi-4-mini.gguf")) is False  # not "phi-4-reasoning"


def test_thinking_model_from_metadata(modules):
    f = modules.handler_llama.is_a_thinking_model
    assert f(_m("/m/unknown.gguf", **{"tokenizer.chat_template": "{% if enable_thinking %}x{% endif %}"})) is True
    assert f(_m("/m/unknown.gguf", **{"general.name": "plain"})) is False


def test_known_non_thinking_name_wins_over_metadata(modules):
    f = modules.handler_llama.is_a_thinking_model
    meta = {"tokenizer.chat_template": "{% if enable_thinking %}x{% endif %}"}
    assert f(_m("/m/gemma-4-E2B-it.gguf", **meta)) is False
