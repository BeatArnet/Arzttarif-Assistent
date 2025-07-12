"""Wrapper module for HTML generation."""
from regelpruefer_pauschale import (
    check_pauschale_conditions,
    get_simplified_conditions,
    generate_condition_detail_html,
    get_beschreibung_fuer_lkn_im_backend,
    get_beschreibung_fuer_icd_im_backend,
)

__all__ = [
    "check_pauschale_conditions",
    "get_simplified_conditions",
    "generate_condition_detail_html",
    "get_beschreibung_fuer_lkn_im_backend",
    "get_beschreibung_fuer_icd_im_backend",
]
