"""Helpers to normalize terms before comparison."""

from __future__ import annotations


def normalize_term(term: str) -> str:
    """Return a standardized representation of ``term`` for matching."""

    if not isinstance(term, str):
        return ""

    # Lowercase and strip whitespace.  More elaborate logic such as accent
    # removal could be added here in the future.
    return term.lower().strip()
