from pathlib import Path
import json
import pytest

from synonyms.models import SynonymCatalog, SynonymEntry
from synonyms.storage import load_synonyms, save_synonyms, validate_catalog


def test_load_missing_returns_empty(tmp_path):
    path = tmp_path / "missing.json"
    catalog = load_synonyms(path)
    assert catalog.entries == {}


def test_save_roundtrip(tmp_path):
    entry = SynonymEntry("foo", ["bar"], lkn="L1", by_lang={"de": ["bar"]})
    catalog = SynonymCatalog(entries={"foo": entry})
    path = tmp_path / "syn.json"
    save_synonyms(catalog, path)
    loaded = load_synonyms(path)
    assert loaded.entries["foo"].synonyms == ["bar"]
    assert loaded.entries["foo"].by_lang == {"de": ["bar"]}
    assert loaded.entries["foo"].lkn == "L1"


def test_load_utf16_file(tmp_path):
    catalog = {"foo": ["bar"]}
    path = tmp_path / "syn.json"
    path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-16")
    loaded = load_synonyms(path)
    assert loaded.entries["foo"].synonyms == ["bar"]

def test_load_new_format(tmp_path):
    data = {"foo": {"lkn": "L2", "synonyms": {"de": ["bar"], "fr": ["baz"]}}}
    path = tmp_path / "syn.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_synonyms(path)
    assert set(loaded.entries["foo"].synonyms) == {"bar", "baz"}
    assert loaded.entries["foo"].by_lang == {"de": ["bar"], "fr": ["baz"]}
    assert loaded.entries["foo"].lkn == "L2"

def test_load_with_control_chars(tmp_path):
    path = tmp_path / "syn.json"
    path.write_bytes(b'{"foo": ["bar"]}\x00')
    loaded = load_synonyms(path)
    assert loaded.entries["foo"].synonyms == ["bar"]

def test_load_utf8_bom(tmp_path):
    catalog = {"foo": ["bar"]}
    path = tmp_path / "syn.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(catalog).encode("utf-8"))
    loaded = load_synonyms(path)
    assert loaded.entries["foo"].synonyms == ["bar"]

def test_validate_catalog_success():
    catalog = SynonymCatalog(entries={"foo": SynonymEntry("foo", ["bar"], by_lang={"de": ["bar"]})})
    validate_catalog(catalog)


def test_validate_catalog_invalid():
    catalog = SynonymCatalog(entries={"foo": SynonymEntry("foo", [])})
    catalog.entries["foo"].synonyms = "bad"  # type: ignore
    catalog.entries["foo"].by_lang = []  # type: ignore
    with pytest.raises(ValueError):
        validate_catalog(catalog)
