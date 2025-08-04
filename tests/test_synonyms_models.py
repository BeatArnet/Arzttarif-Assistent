from synonyms.models import SynonymEntry, SynonymCatalog


def test_entry_default_list_is_unique():
    e1 = SynonymEntry("foo")
    e2 = SynonymEntry("bar")
    e1.synonyms.append("a")
    assert e2.synonyms == []


def test_catalog_add_entry():
    catalog = SynonymCatalog()
    entry = SynonymEntry("foo", ["bar"])
    catalog.entries[entry.base_term] = entry
    assert "foo" in catalog.entries
    assert catalog.entries["foo"].synonyms == ["bar"]
