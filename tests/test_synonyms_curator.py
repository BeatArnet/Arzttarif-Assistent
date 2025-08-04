from synonyms.models import SynonymCatalog, SynonymEntry
from synonyms.curator import curate_catalog


def test_curate_catalog_passthrough():
    catalog = SynonymCatalog(entries={"foo": SynonymEntry("foo", ["bar"])})
    curated = curate_catalog(catalog)
    assert curated is catalog
    assert curated.entries["foo"].synonyms == ["bar"]
