from typing import List, Dict
import sys
import types
import importlib
from synonyms.models import SynonymCatalog, SynonymEntry
from synonyms import generator
from synonyms.generator import _clean_variants, _extract_json

def test_clean_variants_filters_noise():
    raw = [" foo ", "A", "", "This is a very long sentence that should be removed", "bar"]
    cleaned = _clean_variants(raw)
    assert cleaned == ["foo", "bar"]


def test_clean_variants_replaces_eszett():
    raw = ["groß", "fuß"]
    cleaned = _clean_variants(raw)
    assert "gross" in cleaned
    assert "fuss" in cleaned


def test_clean_variants_prefers_umlauts():
    raw = ["arzt", "aerzt", "ärzt"]
    cleaned = _clean_variants(raw)
    assert "ärzt" in cleaned
    assert "arzt" in cleaned
    # 'ae' variant should be removed when umlaut present
    assert all("ae" not in c for c in cleaned)


def test_incremental_returns_entry_with_lkn_and_by_lang(tmp_path, monkeypatch):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[SYNONYMS]\nllm_provider = ollama\nllm_model = x\n")
    monkeypatch.chdir(tmp_path)
    mod = importlib.reload(generator)

    def fake_query(data: Dict[str, str]):
        assert mod.LLM_PROVIDER == "ollama"
        term = data["de"]
        return {
            "de": {term: [f"{term}-de"]},
            "fr": {term: [f"{term}-fr"]},
            "it": {term: [f"{term}-it"]},
        }

    monkeypatch.setattr(mod, "_query_llm", fake_query)
    base_terms = [{"de": "Foo", "fr": "Foo", "it": "Foo", "lkn": "L1"}]

    entries = list(mod.propose_synonyms_incremental(base_terms))
    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, SynonymEntry)
    assert entry.lkn == "L1"
    assert entry.by_lang == {"de": ["Foo-de"], "fr": ["Foo-fr"], "it": ["Foo-it"]}
    assert set(entry.synonyms) == {"Foo-de", "Foo-fr", "Foo-it"}
    assert entry.components == {
        "de": {"Foo": ["Foo-de"]},
        "fr": {"Foo": ["Foo-fr"]},
        "it": {"Foo": ["Foo-it"]},
    }


def test_propose_synonyms_filters_german(tmp_path, monkeypatch):
    cfg = tmp_path / "config.ini"
    cfg.write_text("[SYNONYMS]\nllm_provider = ollama\nllm_model = x\n")
    monkeypatch.chdir(tmp_path)
    mod = importlib.reload(generator)

    def fake_query(data: Dict[str, str]):
        return {
            "de": {"Arzt": ["arzt"]},
            "fr": {"Médecin": ["arzt", "médecin"]},
            "it": {"Medico": ["arzt", "medico"]},
        }

    monkeypatch.setattr(mod, "_query_llm", fake_query)
    base_terms = [{"de": "Arzt", "fr": "Médecin", "it": "Medico"}]
    entry = next(mod.propose_synonyms_incremental(base_terms))
    assert "arzt" not in entry.by_lang["fr"]
    assert "arzt" not in entry.by_lang["it"]
    assert entry.components["fr"] == {"Médecin": ["médecin"]}
    assert entry.components["it"] == {"Medico": ["medico"]}


def test_extract_json_handles_fenced_block():
    text = "Here\nis:\n```json\n{\"canonical\": \"foo\", \"synonyms\": [\"bar\"]}\n```"
    data = _extract_json(text)
    assert data == {"canonical": "foo", "synonyms": ["bar"]}


def test_extract_json_single_quotes():
    text = "{'canonical': 'foo', 'synonyms': ['bar']}"
    data = _extract_json(text)
    assert data == {"canonical": "foo", "synonyms": ["bar"]}


def test_extract_json_merges_multiple_blocks():
    text = (
        "Intro\n"
        "```json\n{\"de\": [\"a\"], \"fr\": [\"b\"]}\n```\n"
        "Zwischen\n"
        "```json\n{\"de\": [\"c\"], \"it\": [\"d\"]}\n```"
    )
    data = _extract_json(text)
    assert data == {"de": ["a", "c"], "fr": ["b"], "it": ["d"]}


