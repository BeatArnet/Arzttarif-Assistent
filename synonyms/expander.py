"""Synonymerweiterung für Backend und GUI.

Das Modul verwaltet den Laufzeitzustand (Aktiv-Flag, Lookup-Caches) der
Synonym-Komponente und stellt Helfer bereit, die eine Anfrage in semantisch
ähnliche Suchbegriffe überführen. ``server.py`` erweitert damit den
Retriever-Kontext vor dem LLM-Aufruf, während Unit-Tests die In-Memory-Tabellen
für Szenarien manipulieren können.
"""

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


def _lookup_base_terms(term: str, catalog: SynonymCatalog) -> List[str]:
    """Return all base terms matching ``term`` via direct or reverse lookup."""
    bases: List[str] = []
    if term in catalog.entries:
        bases.append(term)
    norm = " ".join(term.lower().split())
    for base in catalog.index.get(norm, []):
        if base not in bases:
            bases.append(base)
    return bases

def set_synonyms_enabled(enabled: bool) -> None:
    """Aktiviert oder deaktiviert die Synonymerweiterung global."""

    global _enabled
    _enabled = enabled


def synonyms_enabled() -> bool:
    """Gibt ``True`` zurück, wenn die Erweiterung derzeit aktiv ist."""

    return _enabled


def expand_terms(terms: Iterable[str], catalog: SynonymCatalog) -> List[str]:
    """Erweitert ``terms`` um alle im ``catalog`` hinterlegten Synonyme."""

    seen: Set[str] = set(terms)
    if not _enabled:
        return list(seen)

    for term in list(seen):
        for base in _lookup_base_terms(term, catalog):
            entry = catalog.entries.get(base)
            if not entry:
                continue
            seen.add(base)
            seen.update(entry.synonyms)
            for lang_syns in entry.by_lang.values():
                seen.update(lang_syns)
    return list(seen)


def expand_query(
    query: Any,
    catalog: SynonymCatalog | None = None,
    *,
    lang: str | None = None,
) -> List[str]:
    """Gibt ``query`` samt Synonymen aus ``catalog`` oder :data:`_synonyms` zurück.

    Deckt sich ``query`` mit einem bekannten Synonym, wird auch der kanonische
    Basisterm ergänzt. Bei gesetztem ``lang`` werden nur Synonyme dieser Sprache
    berücksichtigt; fehlt dort ein Eintrag, fällt die Funktion auf Deutsch
    zurück.
    """

    if not synonyms_enabled() or not isinstance(query, str):
        return [query]

    variants: List[str] = [query]
    variants.extend(_synonyms.get(query, []))

    if catalog is not None:
        bases = _lookup_base_terms(query, catalog)
        for base in bases:
            if base not in variants:
                variants.append(base)
            entry = catalog.entries.get(base)
            if not entry:
                continue
            if lang:
                candidates = entry.by_lang.get(lang, [])
                if not candidates:
                    candidates = entry.by_lang.get("de", [])
            else:
                candidates = entry.synonyms
            variants.extend(candidates)

    seen: Set[str] = set()
    deduped: List[str] = []
    for value in variants:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
