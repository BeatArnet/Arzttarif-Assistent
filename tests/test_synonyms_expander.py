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


def test_expand_query_language_filtering():
    entry = SynonymEntry(
        "foo",
        ["bar", "baz", "qux"],
        by_lang={"de": ["bar"], "fr": ["baz"], "it": ["qux"]},
    )
    catalog = SynonymCatalog(entries={"foo": entry})
    set_synonyms_enabled(True)

    fr_variants = expand_query("foo", catalog, lang="fr")
    assert set(fr_variants) == {"foo", "baz"}
    assert "bar" not in fr_variants
    assert "qux" not in fr_variants

    it_variants = expand_query("foo", catalog, lang="it")
    assert set(it_variants) == {"foo", "qux"}
    assert "bar" not in it_variants
    assert "baz" not in it_variants
