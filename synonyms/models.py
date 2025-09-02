"""Dataclasses representing synonym catalog structures."""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SynonymEntry:
    """Single synonym entry.

    Attributes:
        base_term: Canonical term from the tariff catalog.
        synonyms: Alternative spellings or phrasings aggregated over all languages.
        lkn: Optional tariff code (Leistungs­kennnummer).
        by_lang: Mapping of language code to synonyms in that language.
        components: Per-language mapping of base term components to their synonyms.
    """

    base_term: str
    synonyms: List[str] = field(default_factory=list)
    lkn: str | None = None
    by_lang: Dict[str, List[str]] = field(default_factory=dict)
    components: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)

@dataclass
class SynonymCatalog:
    """Collection of synonym entries keyed by the base term.

    The ``index`` attribute maps every known synonym to its canonical
    ``base_term`` for quick reverse lookups.
    """

    entries: Dict[str, SynonymEntry] = field(default_factory=dict)
    index: Dict[str, str] = field(default_factory=dict)
