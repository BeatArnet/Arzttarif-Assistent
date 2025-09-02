"""Logic for scoring synonym suggestions and normalization helpers."""

from __future__ import annotations

from difflib import SequenceMatcher


def normalize_term(term: str) -> str:
    """Return a standardized representation of ``term`` for matching."""

    if not isinstance(term, str):
        return ""

    # Lowercase and strip whitespace.  More elaborate logic such as accent
    # removal could be added here in the future.
    return term.lower().strip()


def score_synonym(candidate: str, base: str) -> float:
    """Return a score indicating how well ``candidate`` matches ``base``."""

    cand_norm = normalize_term(candidate)
    base_norm = normalize_term(base)
    if not cand_norm or not base_norm:
        return 0.0

    if cand_norm == base_norm:
        return 1.0

    return SequenceMatcher(None, cand_norm, base_norm).ratio()
