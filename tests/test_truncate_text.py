import math
import sys
from pathlib import Path

# sicherstellen, dass Projektwurzel auf dem Importpfad liegt
sys.path.append(str(Path(__file__).resolve().parents[1]))

from generate_embeddings import truncate_text


class DummyTokenizer:
    model_max_length = 128

    def encode(self, text, add_special_tokens=False):
        # simple whitespace tokenization
        return list(range(len(text.split())))

    def decode(self, tokens, clean_up_tokenization_spaces=True):
        return " ".join(f"t{t}" for t in range(len(tokens)))

    def num_special_tokens_to_add(self, pair=False):
        return 2


def test_truncate_text_respects_limit():
    tokenizer = DummyTokenizer()
    text = "w " * 130  # 130 tokens
    result = truncate_text(text.strip(), tokenizer, max_tokens=128)
    tokens = tokenizer.encode(result, add_special_tokens=False)
    assert len(tokens) + tokenizer.num_special_tokens_to_add(False) <= 128


def test_truncate_text_uses_tokenizer_default():
    tokenizer = DummyTokenizer()
    text = "w " * 200
    result = truncate_text(text.strip(), tokenizer)
    tokens = tokenizer.encode(result, add_special_tokens=False)
    assert len(tokens) + tokenizer.num_special_tokens_to_add(False) <= tokenizer.model_max_length
