from typing import List, Dict
import sys
import types
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


def test_incremental_returns_entry_with_lkn_and_by_lang(monkeypatch):
    def fake_call(term: str, lang: str, translation: str | None):
        return None, [f"{term}-{lang}"]

    monkeypatch.setattr(generator, "_call_gemini_for_language", fake_call)
    base_terms = [{"de": "Foo", "fr": "Foo", "it": "Foo", "lkn": "L1"}]

    entries = list(generator.propose_synonyms_incremental(base_terms))
    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, SynonymEntry)
    assert entry.lkn == "L1"
    assert entry.by_lang == {"de": ["Foo-de"], "fr": ["Foo-fr"], "it": ["Foo-it"]}
    assert set(entry.synonyms) == {"Foo-de", "Foo-fr", "Foo-it"}


def test_propose_synonyms_filters_german(monkeypatch):
    def fake_call(term: str, lang: str, translation: str | None):
        if lang == "de":
            return None, ["arzt"]
        if lang == "fr":
            return None, ["arzt", "médecin"]
        return None, ["arzt", "medico"]

    monkeypatch.setattr(generator, "_call_gemini_for_language", fake_call)
    base_terms = [{"de": "Arzt", "fr": "Médecin", "it": "Medico"}]
    entry = next(generator.propose_synonyms_incremental(base_terms))
    assert "arzt" not in entry.by_lang["fr"]
    assert "arzt" not in entry.by_lang["it"]


def test_extract_json_handles_fenced_block():
    text = "Here\nis:\n```json\n{\"canonical\": \"foo\", \"synonyms\": [\"bar\"]}\n```"
    data = _extract_json(text)
    assert data == {"canonical": "foo", "synonyms": ["bar"]}


def test_extract_json_single_quotes():
    text = "{'canonical': 'foo', 'synonyms': ['bar']}"
    data = _extract_json(text)
    assert data == {"canonical": "foo", "synonyms": ["bar"]}


def test_call_gemini_includes_translation(monkeypatch):
    captured = {}

    class DummyModel:
        def generate_content(self, prompt, generation_config=None):
            captured["prompt"] = prompt

            class Resp:
                text = '{"canonical": "foo", "synonyms": ["bar"]}'

            return Resp()

    dummy_module = types.SimpleNamespace(
        configure=lambda **kw: None,
        GenerativeModel=lambda name: DummyModel(),
    )
    google_pkg = types.SimpleNamespace(generativeai=dummy_module)
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.generativeai", dummy_module)
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    canonical, syns = generator._call_gemini_for_language("Foo", "fr", "Foo fr")

    assert canonical == "foo"
    assert syns == ["bar"]
    assert "Foo fr" in captured["prompt"]
