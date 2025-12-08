"""Renderer and formatting utilities for Pauschalen explanations."""

from __future__ import annotations

import html
import logging
from functools import wraps
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from utils import (
    activate_table_content_cache,
    deactivate_table_content_cache,
    escape,
    get_lang_field,
    get_table_content,
    translate,
)

logger = logging.getLogger(__name__)

__all__ = [
    "with_table_content_cache",
    "render_condition_results_html",
    "generate_condition_detail_html",
    "get_beschreibung_fuer_lkn_im_backend",
    "get_beschreibung_fuer_icd_im_backend",
]


def with_table_content_cache(func):
    """Ensure table lookups reuse a request-scoped cache while the function runs."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        token = activate_table_content_cache()
        try:
            return func(*args, **kwargs)
        finally:
            deactivate_table_content_cache(token)

    return wrapper


def get_beschreibung_fuer_lkn_im_backend(
    lkn_code: str,
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    lang: str = "de",
) -> str:
    """Return the localized description for a service catalogue code."""
    details = leistungskatalog_dict.get(str(lkn_code).upper())
    if not details:
        return lkn_code
    return get_lang_field(details, "Beschreibung", lang) or lkn_code


@with_table_content_cache
def get_beschreibung_fuer_icd_im_backend(
    icd_code: str,
    tabellen_dict_by_table: Mapping[str, Sequence[Dict[str, Any]]],
    spezifische_icd_tabelle: Optional[str] = None,
    lang: str = "de",
) -> str:
    """Return the localized description for an ICD code."""
    if spezifische_icd_tabelle:
        icd_entries_specific = get_table_content(
            spezifische_icd_tabelle,
            "icd",
            tabellen_dict_by_table,
            lang,
        )
        for entry in icd_entries_specific:
            if entry.get("Code", "").upper() == icd_code.upper():
                return entry.get("Code_Text", icd_code)

    haupt_icd_tabelle_name = "icd_hauptkatalog"
    icd_entries_main = get_table_content(
        haupt_icd_tabelle_name,
        "icd",
        tabellen_dict_by_table,
        lang,
    )
    for entry in icd_entries_main:
        if entry.get("Code", "").upper() == icd_code.upper():
            return entry.get("Code_Text", icd_code)

    for entries in tabellen_dict_by_table.values():
        for entry in entries:
            if (
                entry.get("Tabelle_Typ") == "icd"
                and entry.get("Code", "").upper() == icd_code.upper()
            ):
                return entry.get("Code_Text", icd_code)

    return icd_code


def render_condition_results_html(
    results: List[Dict[str, Any]],
    lang: str = "de",
) -> str:
    """Render legacy condition results."""
    logger.warning(
        "render_condition_results_html wird aufgerufen, ist aber für die neue HTML-Struktur veraltet."
    )
    html_parts = ["<ul class='legacy-condition-list'>"]
    for item in results:
        icon_text = "&#10003;" if item.get("erfuellt") else "&#10007;"
        typ_text = escape(str(item.get("Bedingungstyp", "")))
        wert_text = escape(str(item.get("Werte", "")))
        html_parts.append(f"<li>{icon_text} {typ_text}: {wert_text}</li>")
    html_parts.append("</ul>")
    return "".join(html_parts)


@with_table_content_cache
def generate_condition_detail_html(
    condition_tuple: Tuple[Any, Any],
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    tabellen_dict_by_table: Mapping[str, Sequence[Dict[str, Any]]],
    lang: str = "de",
) -> str:
    """Generate HTML for a simplified condition tuple."""
    cond_type_comp, cond_value_comp = condition_tuple
    condition_html = "<li>"

    try:
        if cond_type_comp == "LKN_LIST":
            condition_html += translate("require_lkn_list", lang)
            if not cond_value_comp:
                condition_html += f"<i>{translate('no_lkns_spec', lang)}</i>"
            else:
                lkn_details_html_parts = []
                for lkn_code in cond_value_comp:
                    beschreibung = get_beschreibung_fuer_lkn_im_backend(
                        lkn_code,
                        leistungskatalog_dict,
                        lang,
                    )
                    lkn_details_html_parts.append(
                        f"<b>{html.escape(lkn_code)}</b> ({html.escape(beschreibung)})"
                    )
                condition_html += ", ".join(lkn_details_html_parts)

        elif cond_type_comp == "LKN_TABLE":
            condition_html += translate("require_lkn_table", lang)
            if not cond_value_comp:
                condition_html += f"<i>{translate('no_table_name', lang)}</i>"
            else:
                table_links_html_parts = []
                for table_name_norm in cond_value_comp:
                    table_content_entries = get_table_content(
                        table_name_norm,
                        "service_catalog",
                        tabellen_dict_by_table,
                        lang,
                    )
                    entry_count = len(table_content_entries)
                    details_content_html = ""
                    if table_content_entries:
                        details_content_html = (
                            "<ul style='margin-top: 5px; font-size: 0.9em; "
                            "max-height: 150px; overflow-y: auto; border-top: 1px solid #eee; "
                            "padding-top: 5px; padding-left: 15px; list-style-position: inside;'>"
                        )
                        for item in sorted(
                            table_content_entries,
                            key=lambda x: x.get("Code", ""),
                        ):
                            item_code = item.get("Code", "N/A")
                            item_text = get_beschreibung_fuer_lkn_im_backend(
                                item_code,
                                leistungskatalog_dict,
                                lang,
                            )
                            details_content_html += (
                                f"<li><b>{html.escape(item_code)}</b>: "
                                f"{html.escape(item_text)}</li>"
                            )
                        details_content_html += "</ul>"
                    entries_label = translate("entries_label", lang)
                    table_detail_html = (
                        "<details class='inline-table-details-comparison'>"
                        f"<summary>{html.escape(table_name_norm.upper())}</summary> "
                        f"({entry_count} {entries_label}){details_content_html}</details>"
                    )
                    table_links_html_parts.append(table_detail_html)
                condition_html += ", ".join(table_links_html_parts)

        elif cond_type_comp == "ICD_TABLE":
            condition_html += translate("require_icd_table", lang)
            if not cond_value_comp:
                condition_html += f"<i>{translate('no_table_name', lang)}</i>"
            else:
                table_links_html_parts = []
                for table_name_norm in cond_value_comp:
                    table_content_entries = get_table_content(
                        table_name_norm,
                        "icd",
                        tabellen_dict_by_table,
                        lang,
                    )
                    entry_count = len(table_content_entries)
                    details_content_html = ""
                    if table_content_entries:
                        details_content_html = "<ul>"
                        for item in sorted(
                            table_content_entries,
                            key=lambda x: x.get("Code", ""),
                        ):
                            item_code = item.get("Code", "N/A")
                            item_text = item.get("Code_Text", "N/A")
                            details_content_html += (
                                f"<li><b>{html.escape(item_code)}</b>: "
                                f"{html.escape(item_text)}</li>"
                            )
                        details_content_html += "</ul>"
                    entries_label = translate("entries_label", lang)
                    table_detail_html = (
                        "<details class='inline-table-details-comparison'>"
                        f"<summary>{html.escape(table_name_norm.upper())}</summary> "
                        f"({entry_count} {entries_label}){details_content_html}</details>"
                    )
                    table_links_html_parts.append(table_detail_html)
                condition_html += ", ".join(table_links_html_parts)

        elif cond_type_comp == "ICD_LIST":
            condition_html += translate("require_icd_list", lang)
            if not cond_value_comp:
                condition_html += f"<i>{translate('no_icds_spec', lang)}</i>"
            else:
                icd_details_html_parts = []
                for icd_code in cond_value_comp:
                    beschreibung = get_beschreibung_fuer_icd_im_backend(
                        icd_code,
                        tabellen_dict_by_table,
                        lang=lang,
                    )
                    icd_details_html_parts.append(
                        f"<b>{html.escape(icd_code)}</b> ({html.escape(beschreibung)})"
                    )
                condition_html += ", ".join(icd_details_html_parts)

        elif cond_type_comp == "MEDICATION_LIST":
            condition_html += translate("require_medication_list", lang)
            if not cond_value_comp:
                condition_html += f"<i>{translate('no_medications_spec', lang)}</i>"
            else:
                condition_html += html.escape(", ".join(cond_value_comp))

        elif cond_type_comp.startswith("PATIENT_"):
            feld_name_raw = cond_type_comp.split("_", 1)[1]
            feld_name = feld_name_raw.replace("_", " ").capitalize()
            condition_html += translate(
                "patient_condition",
                lang,
                field=html.escape(feld_name),
                value=html.escape(str(cond_value_comp)),
            )

        elif cond_type_comp == "ANZAHL_CHECK":
            condition_html += translate(
                "anzahl_condition",
                lang,
                value=html.escape(str(cond_value_comp)),
            )

        elif cond_type_comp == "SEITIGKEIT_CHECK":
            condition_html += translate(
                "seitigkeit_condition",
                lang,
                value=html.escape(str(cond_value_comp)),
            )

        elif cond_type_comp == "GESCHLECHT_LIST_CHECK":
            condition_html += translate("geschlecht_list", lang)
            if not cond_value_comp:
                condition_html += f"<i>{translate('no_gender_spec', lang)}</i>"
            else:
                condition_html += html.escape(", ".join(cond_value_comp))

        else:
            condition_html += (
                f"{html.escape(cond_type_comp)}: {html.escape(str(cond_value_comp))}"
            )

    except Exception as exc:
        logger.error(
            "FEHLER beim Erstellen der Detailansicht für Vergleichs-Bedingung '%s': %s",
            condition_tuple,
            exc,
        )
        condition_html += (
            f"<i>Fehler bei Detailgenerierung: {html.escape(str(exc))}</i>"
        )

    condition_html += "</li>"
    return condition_html
