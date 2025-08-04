"""Tools for generating new synonyms from the tariff data and LLM suggestions."""

from __future__ import annotations

__all__ = ["extract_base_terms_from_tariff", "propose_synonyms_incremental"]

import logging
import os

import json
from pathlib import Path
from typing import Dict, Iterable, List, TypedDict, cast
import unicodedata
import re
from .models import SynonymCatalog, SynonymEntry


class MultilingualResponse(TypedDict):
    """Typed response for multilingual LLM requests."""

    canonical: Dict[str, str]
    synonyms: Dict[str, List[str]]


def extract_base_terms_from_tariff() -> List[Dict[str, str]]:
    """Return canonical descriptions for all languages from the tariff data."""
    # This simplified implementation only looks at the main tariff catalogue if
    # it is available.  The file contains a list of dictionaries with
    # ``Beschreibung`` fields for German, French and Italian.
    path = Path("data") / "LKAAT_Leistungskatalog.json"
    if not path.exists():
        return []

    try:
        records: List[Dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    terms: List[Dict[str, str]] = []
    for rec in records:
        de = rec.get("Beschreibung")
        fr = rec.get("Beschreibung_f")
        it = rec.get("Beschreibung_i")
        lkn = rec.get("LKN")
        if isinstance(de, str):
            item = {"de": de.strip()}
            if isinstance(fr, str):
                item["fr"] = fr.strip()
            if isinstance(it, str):
                item["it"] = it.strip()
            if isinstance(lkn, str):
                item["lkn"] = lkn
            terms.append(item)
    return terms


def _clean_variants(variants: Iterable[str]) -> List[str]:
    """Return ``variants`` stripped of obviously invalid entries."""

    cleaned: List[str] = []
    for var in variants:
        if not isinstance(var, str):
            continue
        item = var.strip()
        # replace German Eszett with Swiss 'ss'
        item = item.replace("ß", "ss")
        if not item:
            continue
        # discard single characters and long sentences
        if len(item) <= 1:
            continue
        if len(item) > 50 or len(item.split()) > 5:
            continue
        cleaned.append(item)

    # de-duplicate while preserving order
    deduped: List[str] = []
    seen: set[str] = set()
    for c in cleaned:
        if c not in seen:
            seen.add(c)
            deduped.append(c)

    return _dedup_umlaut_variants(deduped)


def _dedup_umlaut_variants(variants: Iterable[str]) -> List[str]:
    """Prefer variants with umlauts over ASCII replacements."""

    mapping = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
    }

    chosen: Dict[str, str] = {}
    for item in variants:
        key = item
        for uml, repl in mapping.items():
            key = key.replace(uml, repl)
        norm = key.lower()
        existing = chosen.get(norm)
        if existing:
            if any(ch in item for ch in "äöüÄÖÜ") and not any(ch in existing for ch in "äöüÄÖÜ"):
                chosen[norm] = item
        else:
            chosen[norm] = item
    return list(chosen.values())


def _filter_cross_language_synonyms(by_lang: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Remove obviously German terms from French and Italian lists."""

    german_set = set(by_lang.get("de", []))
    filtered: Dict[str, List[str]] = {}
    for lang, items in by_lang.items():
        if lang in ("fr", "it"):
            tmp: List[str] = []
            for val in items:
                if val in german_set:
                    continue
                if any(ch in val.lower() for ch in "äöüß"):
                    continue
                tmp.append(val)
            filtered[lang] = tmp
        else:
            filtered[lang] = items
    return filtered


def _extract_json(text: str) -> Dict[str, object]:
    """Return JSON data from ``text`` by scanning for the first JSON object."""

    try:
        return json.loads(text)
    except Exception:
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
        if fence:
            snippet = fence.group(1)
        else:
            match = re.search(r"\{.*?\}", text, re.S)
            if match:
                snippet = match.group(0)
            else:
                raise

    for candidate in (snippet, snippet.replace("'", '"')):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    raise


def _call_gemini_for_language(
    term: str, lang: str, translation: str | None
) -> tuple[str | None, List[str]]:
    """Return translation and synonyms for ``term`` in a single ``lang``."""

    try:
        import google.generativeai as genai  # type: ignore
    except Exception as e:  # pragma: no cover - optional dependency
        raise RuntimeError("google.generativeai package not available") from e

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    genai.configure(api_key=api_key)  # type: ignore[attr-defined]
    model_cls = getattr(genai, "GenerativeModel")  # type: ignore[attr-defined]
    model = model_cls(os.getenv("GEMINI_MODEL_SYNONYM", "gemini-2.5-pro"))

    extra = f" Übersetzung: '{translation}'." if translation else ""

    prompt = (
        "Arzttarif Schweiz. "
        "Leistungsbezeichnung: '"
        f"{term}'.\n"
        f"Zielsprache für Synonyme: {lang.upper()} (DE=deutsch, FR=français, IT=italiano).{extra}\n"
        "Gib funktionale, kontextbezogene Synonyme für die Begriffe innerhalb der Leistungsbezeichnung an. "
        "Ziel ist es, die Suchbarkeit in Alltagssprache und medizinischer Umgangssprache zu verbessern.\n"
        "WICHTIG:\n"
        "- Keine abstrakten oder rein adjektivischen Begriffe wie 'medizinisch', 'heilkundlich', 'ärztlich', 'therapeutisch' ohne Bezug zur Leistung.\n"
        "- Synonyme müssen *eine erbringbare Leistung* oder *eine übliche sprachliche Umschreibung* bezeichnen.\n"
        "- Wenn die Leistungsbezeichnung Zeitangaben enthält, gib keine Synonyme für die Zeitkomponente.\n"
        "- Vermeide generische Begriffe wie 'Kontrolle' oder 'Prüfung', falls sie zu unspezifisch sind.\n"
        "- Gib **ausschliesslich** Begriffe an, die in der jeweiligen Sprache verwendet werden.\n"
        '- Format: {"canonical": "<normierter Begriff>", "synonyms": ["syn1", "syn2", "..."]}\n'
        "- Synonyme mit Umlauten (ä, ö, ü, é, è, à usw.) und 'ss' statt 'ß' im Deutschen.\n"
    )

    logging.debug("Gemini prompt for '%s' [%s]: %s", term, lang, prompt)

    resp = model.generate_content(prompt, generation_config={"temperature": 0.05})
    try:
        content = resp.text
    except Exception as e:  # pragma: no cover - network failures
        raise RuntimeError("Unexpected Gemini response") from e

    logging.info("LLM raw response [%s]: %s", lang, content)

    try:
        data = _extract_json(content)
        canon_val = data.get("canonical")
        canonical = str(canon_val).strip() if isinstance(canon_val, str) else None
        syns = cast(List[str], data.get("synonyms") or [])
        variants = [s.strip() for s in syns if isinstance(s, str)]
        logging.debug(
            "Gemini response for '%s' [%s]: canonical=%s synonyms=%s",
            term,
            lang,
            canonical,
            variants,
        )
        return canonical, variants
    except Exception as e:  # pragma: no cover - parsing errors
        raise RuntimeError("Failed to parse Gemini response") from e


def propose_synonyms_incremental(
    base_terms: Iterable[dict] | Iterable[str],
    *,
    start: int = 0,
) -> Iterable[SynonymEntry]:
    """Yield ``SynonymEntry`` objects one by one.

    ``base_terms`` may be a list of dictionaries with language variants or
    simple strings containing only the German term.  The function automatically
    handles both cases.  When translations are available, the respective
    language variant is used as ``term`` so that the LLM generates synonyms in
    the correct language.  The German term is still provided as translation
    context.
    """

    languages = ["de", "fr", "it"]
    for idx, item in enumerate(base_terms):
        if idx < start:
            continue
        lkn = None
        if isinstance(item, dict):
            term_de = str(item.get("de", "")).strip()
            trans: Dict[str, str] = {}
            fr = item.get("fr")
            if isinstance(fr, str):
                trans["fr"] = fr.strip()
            it = item.get("it")
            if isinstance(it, str):
                trans["it"] = it.strip()
            lkn_val = item.get("lkn") or item.get("LKN")
            if isinstance(lkn_val, str):
                lkn = lkn_val
            translations = trans or None
        else:
            term_de = str(item)
            translations = None

        by_lang: Dict[str, List[str]] = {}
        try:
            for lang in languages:
                if lang == "de":
                    lang_term = term_de
                    tr = None
                else:
                    lang_term = translations.get(lang) if translations else None
                    if lang_term:
                        tr = term_de
                    else:
                        lang_term = term_de
                        tr = None
                canonical_val, syns = _call_gemini_for_language(
                    lang_term, lang, tr
                )
                lang_list: List[str] = []
                if lang != "de" and canonical_val:
                    lang_list.append(canonical_val)
                lang_list.extend(syns)
                by_lang[lang] = _clean_variants(lang_list)
        except Exception as e:  # pragma: no cover - network failures
            logging.warning("LLM lookup failed for '%s': %s", term_de, e)
            for lang in languages:
                by_lang.setdefault(lang, [])

        by_lang = _filter_cross_language_synonyms(by_lang)

        # aggregate all language lists for the synonyms field
        synonyms: List[str] = []
        for lang in languages:
            vals = _clean_variants(by_lang.get(lang, []))
            by_lang[lang] = vals
            synonyms.extend(vals)

        synonyms = _clean_variants(synonyms)

        yield SynonymEntry(base_term=term_de, synonyms=synonyms, lkn=lkn, by_lang=by_lang)
