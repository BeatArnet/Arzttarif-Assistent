import json
from synonyms.models import SynonymCatalog, SynonymEntry
from synonyms.storage import load_synonyms
from synonyms.expander import (
    expand_terms,
    expand_query,
    set_synonyms_enabled,
    _synonyms,
)

def test_expand_terms_respects_flag():
    catalog = SynonymCatalog(entries={"foo": SynonymEntry("foo", ["bar"])})
    set_synonyms_enabled(False)
    assert expand_terms(["foo"], catalog) == ["foo"]
    set_synonyms_enabled(True)
    expanded = expand_terms(["foo"], catalog)
    assert set(expanded) == {"foo", "bar"}


def test_expand_query_input_limits(monkeypatch):
    monkeypatch.setitem(_synonyms, "foo", ["a", "b", "c"])
    set_synonyms_enabled(True)
    variants = expand_query("foo")
    # original plus each synonym, no duplicates
    assert len(variants) == 4
    assert "foo" in variants
    for syn in ["a", "b", "c"]:
        assert syn in variants

    assert expand_query("") == [""]
    assert expand_query(123) == [123]


def test_expand_query_reverse_lookup(tmp_path):
    data = {
        "Ärztliche Konsultation": {"synonyms": {"de": ["Arztbesuch"]}}
    }
    path = tmp_path / "syn.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    catalog = load_synonyms(path)
    set_synonyms_enabled(True)
    variants = expand_query("Arztbesuch", catalog)
    assert "Ärztliche Konsultation" in variants
    assert "Arztbesuch" in variants
