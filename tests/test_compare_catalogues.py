from synonyms.models import SynonymCatalog, SynonymEntry
from synonyms.storage import compare_catalogues


def test_compare_catalogues():
    old = SynonymCatalog(entries={
        "foo": SynonymEntry("foo", ["bar"], lkns=["1"]),
        "baz": SynonymEntry("baz", ["qux"], lkns=["2"]),
    })
    new = SynonymCatalog(entries={
        "foo": SynonymEntry("foo", ["bar", "baz"], lkns=["1", "1A"]),
        "new": SynonymEntry("new", ["syn"], lkns=["3"]),
    })
    status = compare_catalogues(old, new)
    assert status["foo"] == "changed"
    assert status["baz"] == "removed"
    assert status["new"] == "added"
