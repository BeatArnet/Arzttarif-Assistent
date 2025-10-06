"""Werkzeuge zur Erzeugung neuer Synonyme aus Tarifdaten und LLM-Vorschlägen.

Der Generator liest den offiziellen Tarifkatalog, holt Übersetzungen und
Varianten vom konfigurierten LLM-Anbieter und speichert Ergänzungen im
Synonymspeicher. Sperr-Mechanismen schützen lokale Ollama-Instanzen, und die
Hilfsfunktionen dienen der Tkinter-GUI als Bausteine für interaktive
Kurationssitzungen.
"""

from __future__ import annotations

__all__ = ["extract_base_terms_from_tariff", "propose_synonyms_incremental"]

import logging
import os
import json
import subprocess
import threading
from pathlib import Path
from typing import Dict, Iterable, List, Optional, TypedDict, cast
import unicodedata
import re
import configparser
from .models import SynonymCatalog, SynonymEntry
from openai_wrapper import chat_completion_safe, enforce_llm_min_interval


_CONFIG = configparser.ConfigParser()
try:
    # Use utf-8-sig to handle potential BOM at start of file
    _CONFIG.read("config.ini", encoding="utf-8-sig")
except Exception:
    logging.exception("CONFIG lesen fehlgeschlagen")
LLM_PROVIDER = (
    os.getenv("SYNONYM_LLM_PROVIDER")
    or _CONFIG.get("SYNONYMS", "llm_provider", fallback="ollama")
).lower()

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-pro",
    "openai": "gpt-4o-mini",
    "ollama": "gpt-oss-20b",
}

LLM_MODEL = (
    os.getenv("SYNONYM_LLM_MODEL")
    or _CONFIG.get(
        "SYNONYMS",
        "llm_model",
        fallback=DEFAULT_MODELS.get(LLM_PROVIDER, "gpt-oss-20b"),
    )
)

MODEL_TEMPERATURE_SECTION = "MODEL_TEMPERATURES"


def _get_float_option(section: str, option: str) -> Optional[float]:
    if _CONFIG.has_option(section, option):
        try:
            return _CONFIG.getfloat(section, option)
        except ValueError:
            raw_value = _CONFIG.get(section, option, fallback="").strip()
            logging.warning(
                "Ignoriere ungueltigen Temperaturwert fuer %s.%s: %s",
                section,
                option,
                raw_value,
            )
    return None


def _synonym_default_temperature(stage: str) -> Optional[float]:
    if stage == "completion":
        return 1.0 if LLM_PROVIDER != "ollama" else None
    if stage == "generation":
        return 0.05
    return None


def _resolve_synonym_temperature(stage: str) -> Optional[float]:
    option = f"{stage}_temperature"
    explicit = _get_float_option("SYNONYMS", option)
    if explicit is not None:
        return explicit

    if _CONFIG.has_section(MODEL_TEMPERATURE_SECTION):
        stage_specific = f"{LLM_MODEL}@synonyms_{stage}"
        value = _get_float_option(MODEL_TEMPERATURE_SECTION, stage_specific)
        if value is not None:
            return value
        value = _get_float_option(MODEL_TEMPERATURE_SECTION, LLM_MODEL)
        if value is not None:
            return value

    return _synonym_default_temperature(stage)


SYNONYMS_GENERATION_TEMPERATURE = _resolve_synonym_temperature("generation")
SYNONYMS_COMPLETION_TEMPERATURE = _resolve_synonym_temperature("completion")

APP_VERSION = _CONFIG.get("APP", "version", fallback="dev")
USER_AGENT_PRODUCT = os.getenv("APP_USER_AGENT_PRODUCT") or _CONFIG.get("APP", "user_agent_product", fallback="ArzttarifAssistent")
USER_AGENT = f"{USER_AGENT_PRODUCT}/{APP_VERSION}"

_OLLAMA_LOCK = threading.Lock()
_OLLAMA_STOPPED = False


def _env_name(provider: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", provider.upper())


def _get_api_key(provider: str) -> str | None:
    return os.getenv("SYNONYM_LLM_API_KEY") or os.getenv(f"{_env_name(provider)}_API_KEY")


def _get_base_url(provider: str) -> str | None:
    return os.getenv("SYNONYM_LLM_BASE_URL") or os.getenv(f"{_env_name(provider)}_BASE_URL")


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
            if isinstance(lkn, (str, int)):
                item["lkn"] = str(lkn)
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


# _split_components was unused; removed to simplify module


def _extract_json(text: str) -> Dict[str, object]:
    """Return JSON data from ``text``.

    The language model occasionally wraps multiple JSON objects into a
    longer answer.  This helper scans the text for *all* JSON snippets and
    merges them into a single dictionary.  When no JSON object can be
    extracted a :class:`ValueError` is raised.
    """

    def _parse(snippet: str) -> Dict[str, object] | None:
        for candidate in (snippet, snippet.replace("'", '"')):
            try:
                obj = json.loads(candidate)
            except Exception:
                continue
            if isinstance(obj, dict):
                return obj
        return None

    result = _parse(text)
    if result is not None:
        return result

    objects: List[Dict[str, object]] = []
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S):
        obj = _parse(match.group(1))
        if obj is not None:
            objects.append(obj)

    if not objects:
        for match in re.finditer(r"\{.*?\}", text, re.S):
            obj = _parse(match.group(0))
            if obj is not None:
                objects.append(obj)

    if not objects:
        raise ValueError("No JSON object found")

    if len(objects) == 1:
        return objects[0]

    merged: Dict[str, object] = {}
    for obj in objects:
        for key, val in obj.items():
            if isinstance(val, list):
                existing = merged.get(key)
                if isinstance(existing, list):
                    existing.extend(val)
                else:
                    # start a new list to preserve type information for linters
                    merged[key] = list(val)
            elif key not in merged:
                merged[key] = val
    return merged


def _build_prompt(term_data: Dict[str, str]) -> str:
    term = term_data.get("de", "")
    fr = term_data.get("fr")
    it = term_data.get("it")
    prompt = (
        "Arzttarif Schweiz. "
        "Leistungsbezeichnung: '"
        f"{term}'.\n"
        "Gib funktionale, kontextbezogene Synonyme für die wichtigsten medizinischen und alltagssprachlichen Begriffe getrennt nach einzelnen Komponenten in den Sprachen DE, FR und IT zurück.\n"
        'Format: {"de": {"<Begriff1>": ["..."], "<Begriff2>": ["..."]}, "fr": {...}, "it": {...}}\n'
        "Synonyme mit Umlauten (ä, ö, ü, é, è, à usw.) und 'ss' statt 'ß' im Deutschen.\n"
        "Antworte ausschließlich im JSON-Format ohne weitere Erläuterungen.\n"
    )
    if fr:
        prompt += f"Französisch: '{fr}'.\n"
    if it:
        prompt += f"Italienisch: '{it}'.\n"
    return prompt

def _stop_ollama_model_once() -> None:
    """Stop any running Ollama instance of the configured model once."""
    global _OLLAMA_STOPPED
    if _OLLAMA_STOPPED:
        return
    if LLM_PROVIDER == "ollama":
        try:
            subprocess.run(
                ["ollama", "stop", LLM_MODEL],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            pass
    _OLLAMA_STOPPED = True



def _query_llm(term_data: Dict[str, str]) -> Dict[str, Dict[str, List[str]]]:
    provider = LLM_PROVIDER
    prompt = _build_prompt(term_data)
    content: str
    if provider == "gemini":
        try:
            import google.generativeai as genai  # type: ignore
        except Exception as e:  # pragma: no cover - optional dependency
            raise RuntimeError("google.generativeai package not available") from e
        api_key = _get_api_key(provider)
        if not api_key:
            raise RuntimeError("API key not configured")
        genai.configure(api_key=api_key)  # type: ignore[attr-defined]
        model_cls = getattr(genai, "GenerativeModel")  # type: ignore[attr-defined]
        model = model_cls(LLM_MODEL)
        # Respektiere konfigurierten Mindestabstand zwischen LLM-Requests
        enforce_llm_min_interval()
        generation_config = {}
        if SYNONYMS_GENERATION_TEMPERATURE is not None:
            generation_config["temperature"] = SYNONYMS_GENERATION_TEMPERATURE
        resp = model.generate_content(
            prompt,
            generation_config=generation_config or None,
        )
        try:
            resp_text = resp.text
            if not isinstance(resp_text, str):
                raise RuntimeError("Unexpected Gemini response")
            content = resp_text
        except Exception as e:  # pragma: no cover - network failures
            raise RuntimeError("Unexpected Gemini response") from e
    else:
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:  # pragma: no cover - optional dependency
            raise RuntimeError("openai package not available") from e
        api_key = _get_api_key(provider)
        base_url = _get_base_url(provider)
        if provider == "ollama":
            _stop_ollama_model_once()
            if not api_key:
                api_key = os.getenv("OLLAMA_API_KEY", "ollama")
            base_url = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
        else:
            if not api_key:
                raise RuntimeError("API key not configured")
        base_url = base_url or "https://api.openai.com/v1"
        if not base_url.rstrip("/").endswith("/v1"):
            base_url = f"{base_url.rstrip('/')}/v1"
        # Deaktiviert SDK-interne Retries, damit unsere eigene Drossel/Retry greift
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            default_headers={
                "User-Agent": USER_AGENT,
            },
        )
        try:
            temp_kwargs: Dict[str, float] = {}
            if SYNONYMS_COMPLETION_TEMPERATURE is not None:
                temp_kwargs["temperature"] = SYNONYMS_COMPLETION_TEMPERATURE

            if provider == "ollama":
                with _OLLAMA_LOCK:
                    resp = chat_completion_safe(
                        model=LLM_MODEL,
                        messages=[
                            {"role": "system", "content": "Du bist ein hilfreicher Assistent."},
                            {"role": "user", "content": prompt},
                        ],
                        timeout=60,
                        client=client,
                        **temp_kwargs,
                    )
            else:
                resp = chat_completion_safe(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "Du bist ein hilfreicher Assistent."},
                        {"role": "user", "content": prompt},
                    ],
                    timeout=60,
                    client=client,
                    **temp_kwargs,
                )
            resp_content = resp.choices[0].message.content
            if isinstance(resp_content, list):
                content = "".join(
                    part.get("text", "") for part in resp_content if isinstance(part, dict)
                )
            elif isinstance(resp_content, str):
                content = resp_content
            else:
                raise RuntimeError("Unexpected response")
        except Exception as e:  # pragma: no cover - network failures
            raise RuntimeError(f"{provider} error: {e}") from e
    logging.info("LLM raw response: %s", content)
    data = _extract_json(content)
    result: Dict[str, Dict[str, List[str]]] = {}
    for lang in ("de", "fr", "it"):
        vals = data.get(lang) or {}
        if isinstance(vals, dict):
            inner: Dict[str, List[str]] = {}
            for comp, syns in vals.items():
                if not isinstance(comp, str) or not isinstance(syns, list):
                    continue
                inner[comp] = [str(v).strip() for v in syns if isinstance(v, str)]
            result[lang] = inner
        else:
            result[lang] = {}
    return result


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
        lkns: List[str] = []
        if isinstance(item, dict):
            term_de = str(item.get("de", "")).strip()
            trans: Dict[str, str] = {}
            fr = item.get("fr")
            if isinstance(fr, str):
                trans["fr"] = fr.strip()
            it = item.get("it")
            if isinstance(it, str):
                trans["it"] = it.strip()
            lkns_value = item.get("lkns")
            if isinstance(lkns_value, (list, tuple, set)):
                for code in lkns_value:
                    code_norm = str(code).strip().upper()
                    if code_norm and code_norm not in lkns:
                        lkns.append(code_norm)
            lkn_val = item.get("lkn") or item.get("LKN")
            if isinstance(lkn_val, (str, int)):
                code_norm = str(lkn_val).strip().upper()
                if code_norm and code_norm not in lkns:
                    lkns.append(code_norm)
            translations = trans or None
        else:
            term_de = str(item)
            translations = None

        primary_lkn = lkns[0] if lkns else "-"
        logging.info("LLM request for %s (%s)", term_de, primary_lkn)
        term_data = {"de": term_de}
        if translations:
            term_data.update(translations)
        try:
            raw_components = _query_llm(term_data)
        except Exception as e:  # pragma: no cover - network failures
            logging.warning("LLM lookup failed for '%s': %s", term_de, e)
            raw_components = {lang: {} for lang in languages}

        # aggregate per-language synonyms before filtering
        by_lang_unfiltered: Dict[str, List[str]] = {}
        for lang in languages:
            comps = raw_components.get(lang, {})
            flat: List[str] = []
            for syns in comps.values():
                flat.extend(syns)
            by_lang_unfiltered[lang] = _clean_variants(flat)

        by_lang = _filter_cross_language_synonyms(by_lang_unfiltered)

        # filter components to match cleaned language lists
        components: Dict[str, Dict[str, List[str]]] = {}
        for lang in languages:
            comps = raw_components.get(lang, {})
            cleaned: Dict[str, List[str]] = {}
            allowed = set(by_lang.get(lang, []))
            for comp, syns in comps.items():
                vals = [s for s in _clean_variants(syns) if s in allowed]
                if vals:
                    cleaned[comp] = vals
            components[lang] = cleaned

        # aggregate all language lists for the synonyms field
        synonyms = _clean_variants(
            [syn for items in by_lang.values() for syn in items]
        )

        yield SynonymEntry(
            base_term=term_de,
            synonyms=synonyms,
            lkns=lkns,
            by_lang=by_lang,
            components=components,
        )
