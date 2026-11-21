"""
Loads three TigerODM modules WITHOUT Orange, llama_cpp, gguf or a model:
the heavy third-party imports are replaced by empty stubs in sys.modules,
and the modules are loaded from their file path.
Only `pytest` is needed to run the tests.
"""
import importlib.util
import os
import sys
import types
from unittest import mock

import pytest

LLM_DIR = os.path.join(os.path.dirname(__file__), "..", "orangecontrib", "AAIT", "llm")


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(LLM_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def modules():
    # sys.modules is restored when the session ends: real installed modules are
    # never shadowed outside these tests.
    with mock.patch.dict(sys.modules):
        yield _build()


def _build():
    # third-party stubs
    _stub("gguf", GGUFReader=object)
    _stub("llama_cpp", Llama=object)
    _stub("llama_cpp.llama_multimodal", GenericMTMDChatHandler=object)
    _stub("jinja2", Template=object)
    _stub("GPUtil")
    _stub("numpy")
    _stub("psutil")
    _stub("Orange")
    _stub("Orange.data", Domain=object, StringVariable=object, Table=object)

    prompt_management = _load("prompt_management", "prompt_management.py")
    handler_llama = _load("handler_llama", "handler_llama.py")

    # package layout expected by `from orangecontrib.AAIT.llm import ...`
    _stub("orangecontrib")
    _stub("orangecontrib.AAIT")
    _stub("orangecontrib.AAIT.llm", prompt_management=prompt_management, handler_llama=handler_llama)
    _stub("orangecontrib.AAIT.utils", MetManagement=object)

    answers_llama = _load("answers_llama", "answers_llama.py")
    return types.SimpleNamespace(prompt_management=prompt_management,
                                 handler_llama=handler_llama,
                                 answers_llama=answers_llama)
