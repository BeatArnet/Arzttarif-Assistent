"""Logic for scoring synonym suggestions."""

from __future__ import annotations

from difflib import SequenceMatcher

from .normalizer import normalize_term


def score_synonym(candidate: str, base: str) -> float:
    """Return a score indicating how well ``candidate`` matches ``base``."""

    cand_norm = normalize_term(candidate)
    base_norm = normalize_term(base)
    if not cand_norm or not base_norm:
        return 0.0

    if cand_norm == base_norm:
        return 1.0

    return SequenceMatcher(None, cand_norm, base_norm).ratio()
