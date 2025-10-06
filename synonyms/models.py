"""Dataclasses representing synonym catalog structures."""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SynonymEntry:
    """Single synonym entry.

    Attributes:
        base_term: Canonical term from the tariff catalog.
        synonyms: Alternative spellings or phrasings aggregated over all languages.
        lkns: Tariff codes (Leistungskennnummern) associated with the concept.
        by_lang: Mapping of language code to synonyms in that language.
        components: Per-language mapping of base term components to their synonyms.
    """

    base_term: str
    synonyms: List[str] = field(default_factory=list)
    lkns: List[str] = field(default_factory=list)
    by_lang: Dict[str, List[str]] = field(default_factory=dict)
    components: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)


@dataclass
class SynonymCatalog:
    """Collection of synonym entries keyed by the base term.

    The ``index`` attribute maps known synonyms (normalized) to all
    canonical ``base_term`` values that reference them. ``lkn_index``
    provides the same lookup for tariff codes.
    """

    entries: Dict[str, SynonymEntry] = field(default_factory=dict)
    index: Dict[str, List[str]] = field(default_factory=dict)
    lkn_index: Dict[str, List[str]] = field(default_factory=dict)

