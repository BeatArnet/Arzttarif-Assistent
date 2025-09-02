from synonyms.models import SynonymEntry, SynonymCatalog


def test_entry_default_list_is_unique():
    e1 = SynonymEntry("foo")
    e2 = SynonymEntry("bar")
    e1.synonyms.append("a")
    assert e2.synonyms == []


def test_entry_default_components_is_unique():
    e1 = SynonymEntry("foo")
    e2 = SynonymEntry("bar")
    e1.components["de"] = {"foo": ["bar"]}
    assert e2.components == {}


def test_catalog_add_entry():
    catalog = SynonymCatalog()
    entry = SynonymEntry("foo", ["bar"])
    catalog.entries[entry.base_term] = entry
    assert "foo" in catalog.entries
    assert catalog.entries["foo"].synonyms == ["bar"]
