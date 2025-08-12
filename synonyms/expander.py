
from __future__ import annotations

import logging
from typing import Iterable, List, Set, Dict, Any

from .models import SynonymCatalog

logger = logging.getLogger(__name__)

# Indicates whether expansion is active.  This mirrors the helper in
# ``utils.py`` but lives here so that the synonym subsystem can be used
# independently of the rest of the application.
_enabled: bool = True

# Simple in-memory mapping used by :func:`expand_query`. Tests patch this
# dictionary directly to provide canned synonyms.
_synonyms: Dict[str, List[str]] = {}

def set_synonyms_enabled(enabled: bool) -> None:
    """Globally enable or disable synonym expansion."""

    global _enabled
    _enabled = enabled


def synonyms_enabled() -> bool:
    """Return ``True`` if expansion is currently enabled."""

    return _enabled


def expand_terms(terms: Iterable[str], catalog: SynonymCatalog) -> List[str]:
    """Return ``terms`` plus any synonyms found in ``catalog``."""

    seen: Set[str] = set(terms)
    if not _enabled:
        return list(seen)

    for term in list(seen):
        entry = catalog.entries.get(term)
        if entry:
            seen.update(entry.synonyms)
    return list(seen)


def expand_query(
    query: Any,
    catalog: SynonymCatalog | None = None,
    *,
    lang: str | None = None,
) -> List[str]:
    """Return ``query`` plus any synonyms from ``catalog`` or :data:`_synonyms`.

    If ``query`` itself matches a known synonym, the canonical base term is
    included in the result as well.  When ``lang`` is provided, only synonyms
    for that language are considered, falling back to German if no entries are
    found.
    """

    if not synonyms_enabled() or not isinstance(query, str):
        return [query]

    variants: List[str] = [query]
    variants.extend(_synonyms.get(query, []))

    if catalog:
        entry = catalog.entries.get(query)
        if not entry:
            base = catalog.index.get(query.lower())
            if base:
                variants.append(base)
                entry = catalog.entries.get(base)
        if entry:
            if lang:
                syns = entry.by_lang.get(lang, [])
                if not syns:
                    syns = entry.by_lang.get("de", [])
                variants.extend(syns)
            else:
                variants.extend(entry.synonyms)

    seen: Set[str] = set()
    deduped: List[str] = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            deduped.append(v)
    return deduped
