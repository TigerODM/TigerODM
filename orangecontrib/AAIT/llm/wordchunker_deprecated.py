# wordchunker_deprecated.py
# -----------------------------------------------------------------------------
# Compatibility shim reproducing chonkie==0.4.1 WordChunker behavior (including
# historical quirks/bugs), while being usable inside chonkie>=1.x pipelines.
#
# What you get:
# - A local WordChunker class with the same logic as chonkie 0.4.1 word chunker.
# - Preserves newlines: words are spans like r"(\s*\S+)" joined with "".
# - chunk_size / chunk_overlap are TOKEN budgets (not "word" counts), measured
#   via the provided tokenizer backend.
# - Reproduces 0.4.1 overlap-loop quirk: iterates range(previous_chunk_length)
#   where previous_chunk_length is a TOKEN count (not word count).
# - Reproduces 0.4.1 final-chunk quirk: _create_chunk called without current_index
#   (defaults to 0), which can yield start_index via .find from the start.
#
# Added for practicality in your AAIT / chonkie>=1.5.2 integration:
# - WordChunker is callable: chunker(text) == chunker.chunk(text)
# - Accepts tokenizer="character" (character-count pseudo tokenizer)
# - Accepts a SentenceTransformer instance as tokenizer (uses .tokenizer underneath)
#
# NOTE (important bugfix vs earlier draft):
# Many HuggingFace tokenizers are *callable* (tokenizer(text) -> BatchEncoding).
# We must NOT mis-detect them as a generic callable token counter. We detect
# transformers/tokenizers backends *first* by attributes, then fall back to callable.
# -----------------------------------------------------------------------------

from __future__ import annotations

import importlib
import inspect
import re
from dataclasses import dataclass
from typing import Any, Callable, List, Union


@dataclass(frozen=True)
class Chunk:
    text: str
    start_index: int
    end_index: int
    token_count: int


# -----------------------------
# Helpers for robust tokenizers
# -----------------------------

def _unwrap_possible_sentence_transformer(obj: Any) -> Any:
    """
    If `obj` looks like a SentenceTransformer, return its underlying HF tokenizer
    when available. SentenceTransformer usually has `.tokenizer`.
    """
    if obj is None:
        return obj
    try:
        if hasattr(obj, "tokenizer") and "SentenceTransformer" in type(obj).__name__:
            tok = getattr(obj, "tokenizer", None)
            if tok is not None:
                return tok
    except Exception:
        pass
    return obj


def _make_character_tokenizer() -> Any:
    """
    Special compatibility: when user passes tokenizer="character", count tokens
    as characters, and support batch encoding.
    """
    class _CharTokenizer:
        def encode(self, text: str):
            return list(range(len(text)))

        def encode_batch(self, texts: List[str]):
            return [self.encode(t) for t in texts]

    return _CharTokenizer()


# -----------------------------
# Minimal BaseChunker (0.4.1-ish)
# -----------------------------

class BaseChunker:
    """
    Minimal subset of chonkie.chunker.base.BaseChunker needed by WordChunker 0.4.1
    """

    def __init__(self, tokenizer_or_token_counter: Union[str, Any, Callable[[str], int]]):
        tokenizer_or_token_counter = _unwrap_possible_sentence_transformer(tokenizer_or_token_counter)

        if tokenizer_or_token_counter == "character":
            tokenizer_or_token_counter = _make_character_tokenizer()

        if isinstance(tokenizer_or_token_counter, str):
            self.tokenizer = self._load_tokenizer(tokenizer_or_token_counter)
        else:
            self.tokenizer = tokenizer_or_token_counter

        self._tokenizer_backend = self._get_tokenizer_backend()
        self.token_counter = self._get_tokenizer_counter()

    def _get_tokenizer_backend(self) -> str:
        t = self.tokenizer
        tname = type(t).__name__
        ttype = str(type(t))

        # 1) transformers-style tokenizer (callable, returns BatchEncoding, has encode, often batch_encode_plus)
        if hasattr(t, "batch_encode_plus") or "transformers" in ttype or "PreTrainedTokenizer" in tname:
            return "transformers"

        # 2) tokenizers rust-style (has encode_batch with add_special_tokens)
        if "tokenizers" in ttype:
            return "tokenizers"

        # 3) tiktoken encodings
        if "tiktoken" in ttype:
            return "tiktoken"

        # 4) our custom / other encoders that implement encode_batch
        if hasattr(t, "encode_batch"):
            return "encode_batch"

        # 5) basic encode-only objects
        if hasattr(t, "encode"):
            return "encode_only"

        # 6) finally: a callable token *counter* function: f(text)->int
        # (must be LAST so we don't mis-detect HF tokenizers as callable counters)
        if callable(t) or inspect.isfunction(t) or inspect.ismethod(t):
            return "callable_counter"

        raise ValueError(f"Tokenizer backend {ttype} not supported")

    def _load_tokenizer(self, tokenizer_name: str):
        # Same overall strategy as 0.4.1: try tiktoken -> autotiktokenizer -> tokenizers -> transformers
        try:
            if importlib.util.find_spec("tiktoken") is not None:
                from tiktoken import get_encoding
                return get_encoding(tokenizer_name)
            raise RuntimeError("tiktoken not available")
        except Exception:
            try:
                if importlib.util.find_spec("autotiktokenizer") is not None:
                    from autotiktokenizer import AutoTikTokenizer
                    return AutoTikTokenizer.from_pretrained(tokenizer_name)
                raise RuntimeError("autotiktokenizer not available")
            except Exception:
                try:
                    if importlib.util.find_spec("tokenizers") is not None:
                        from tokenizers import Tokenizer
                        return Tokenizer.from_pretrained(tokenizer_name)
                    raise RuntimeError("tokenizers not available")
                except Exception:
                    if importlib.util.find_spec("transformers") is not None:
                        from transformers import AutoTokenizer
                        return AutoTokenizer.from_pretrained(tokenizer_name)
                    raise ValueError(
                        "Tokenizer not found in: transformers, tokenizers, autotiktokenizer, tiktoken. "
                        "Install one of these."
                    )

    def _get_tokenizer_counter(self) -> Callable[[str], int]:
        t = self.tokenizer
        if self._tokenizer_backend == "transformers":
            return lambda text: len(t.encode(text, add_special_tokens=False))
        if self._tokenizer_backend == "tokenizers":
            return lambda text: len(t.encode(text, add_special_tokens=False).ids)
        if self._tokenizer_backend == "tiktoken":
            return lambda text: len(t.encode(text))
        if self._tokenizer_backend == "encode_batch":
            if hasattr(t, "encode"):
                return lambda text: len(t.encode(text))
            return lambda text: len(t.encode_batch([text])[0])
        if self._tokenizer_backend == "encode_only":
            return lambda text: len(t.encode(text))
        if self._tokenizer_backend == "callable_counter":
            return t  # type: ignore[return-value]
        raise ValueError("Tokenizer backend not supported for token counting")

    def _encode_batch(self, texts: List[str]) -> List[List[int]]:
        """
        Return list of token-id lists. Only lengths are used by WordChunker.
        """
        t = self.tokenizer
        if self._tokenizer_backend == "transformers":
            # batch_encode_plus exists on most HF tokenizers; if not, fall back to __call__
            if hasattr(t, "batch_encode_plus"):
                return t.batch_encode_plus(texts, add_special_tokens=False)["input_ids"]
            # Fallback: tokenizer(texts, add_special_tokens=False) -> BatchEncoding with input_ids
            enc = t(texts, add_special_tokens=False)
            return enc["input_ids"]
        if self._tokenizer_backend == "tokenizers":
            return [e.ids for e in t.encode_batch(texts, add_special_tokens=False)]
        if self._tokenizer_backend == "tiktoken":
            return t.encode_batch(texts)
        if self._tokenizer_backend == "encode_batch":
            return t.encode_batch(texts)
        if self._tokenizer_backend == "encode_only":
            return [t.encode(x) for x in texts]
        if self._tokenizer_backend == "callable_counter":
            # emulate "ids" with dummy list of length == token_count
            out: List[List[int]] = []
            for x in texts:
                n = int(t(x))
                out.append(list(range(n)))
            return out
        raise ValueError(f"Tokenizer backend {self._tokenizer_backend} not supported.")


# -----------------------------
# WordChunker (exact 0.4.1 logic)
# -----------------------------

class WordChunker(BaseChunker):
    """
    Exact port of chonkie==0.4.1 WordChunker (chunker/word.py), with identical behavior/quirks.
    """

    def __init__(
        self,
        tokenizer: Union[str, Any] = "gpt2",
        chunk_size: int = 512,
        chunk_overlap: int = 128,
    ):
        super().__init__(tokenizer)

        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _split_into_words(self, text: str) -> List[str]:
        split_points = [match.end() for match in re.finditer(r"(\s*\S+)", text)]
        words: List[str] = []
        prev = 0

        for point in split_points:
            words.append(text[prev:point])
            prev = point

        if prev < len(text):
            words.append(text[prev:])

        return words

    def _create_chunk(
        self,
        words: List[str],
        text: str,
        token_count: int,
        current_index: int = 0,
    ) -> Chunk:
        chunk_text = "".join(words)
        start_index = text.find(chunk_text, current_index)
        return Chunk(
            text=chunk_text,
            start_index=start_index,
            end_index=start_index + len(chunk_text),
            token_count=token_count,
        )

    def _get_word_list_token_counts(self, words: List[str]) -> List[int]:
        words = [word for word in words if word != ""]
        encodings = self._encode_batch(words)
        return [len(encoding) for encoding in encodings]

    def chunk(self, text: str) -> List[Chunk]:
        if not text or not text.strip():
            return []

        words = self._split_into_words(text)
        lengths = self._get_word_list_token_counts(words)
        chunks: List[Chunk] = []

        current_chunk: List[str] = []
        current_chunk_length = 0
        current_index = 0

        for i, (word, length) in enumerate(zip(words, lengths)):
            if current_chunk_length + length <= self.chunk_size:
                current_chunk.append(word)
                current_chunk_length += length
            else:
                chunk = self._create_chunk(current_chunk, text, current_chunk_length, current_index)
                chunks.append(chunk)

                previous_chunk_length = current_chunk_length
                current_index = chunk.end_index

                overlap: List[str] = []
                overlap_length = 0

                # Quirk/bug-compatible loop: previous_chunk_length is token count
                for j in range(0, previous_chunk_length):
                    cwi = i - 1 - j
                    if cwi < 0:
                        break
                    oword = words[cwi]
                    olength = lengths[cwi]
                    if overlap_length + olength <= self.chunk_overlap:
                        overlap.append(oword)
                        overlap_length += olength
                    else:
                        break

                current_chunk = [w for w in reversed(overlap)]
                current_chunk_length = overlap_length

                current_chunk.append(word)
                current_chunk_length += length

        if current_chunk:
            # Quirk/bug-compatible: current_index not passed (defaults to 0)
            chunk = self._create_chunk(current_chunk, text, current_chunk_length)
            chunks.append(chunk)

        return chunks

    def __call__(self, text: str) -> List[Chunk]:
        return self.chunk(text)

    def __repr__(self) -> str:
        return f"WordChunker(chunk_size={self.chunk_size}, chunk_overlap={self.chunk_overlap})"


def chunk_words(content: str, tokenizer: Any, chunk_size: int = 300, chunk_overlap: int = 100):
    chunker = WordChunker(tokenizer=tokenizer, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = chunker.chunk(content)
    return [c.text for c in chunks], []
