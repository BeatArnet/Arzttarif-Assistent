from synonyms.models import SynonymCatalog, SynonymEntry
from synonyms.storage import compare_catalogues


def test_compare_catalogues():
    old = SynonymCatalog(entries={
        "foo": SynonymEntry("foo", ["bar"], lkn="1"),
        "baz": SynonymEntry("baz", ["qux"], lkn="2"),
    })
    new = SynonymCatalog(entries={
        "foo": SynonymEntry("foo", ["bar", "baz"], lkn="1"),
        "new": SynonymEntry("new", ["syn"], lkn="3"),
    })
    status = compare_catalogues(old, new)
    assert status["foo"] == "changed"
    assert status["baz"] == "removed"
    assert status["new"] == "added"
