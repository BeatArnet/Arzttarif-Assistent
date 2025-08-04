"""Manual approval utilities for synonyms."""

from __future__ import annotations

from .models import SynonymCatalog


def curate_catalog(catalog: SynonymCatalog) -> SynonymCatalog:
    """Return a curated version of ``catalog`` after manual review."""

    # The reference implementation of the curator simply returns the provided
    # catalogue unchanged.  In a production system this function would present
    # the suggestions to a human operator and incorporate their feedback.
    return catalog
