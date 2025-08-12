"""Tools for generating new synonyms from the tariff data and LLM suggestions."""

from __future__ import annotations

__all__ = ["extract_base_terms_from_tariff", "propose_synonyms_incremental"]

import logging
import os
import json
import subprocess
import threading
from pathlib import Path
from typing import Dict, Iterable, List, TypedDict, cast
import unicodedata
import re
import configparser
from .models import SynonymCatalog, SynonymEntry
from openai_wrapper import chat_completion_safe


_CONFIG = configparser.ConfigParser()
_CONFIG.read("config.ini")
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


def _build_prompt(term_data: Dict[str, str]) -> str:
    term = term_data.get("de", "")
    fr = term_data.get("fr")
    it = term_data.get("it")
    prompt = (
        "Arzttarif Schweiz. "
        "Leistungsbezeichnung: '"
        f"{term}'.\n"
        "Gib funktionale, kontextbezogene Synonyme für die wichtigsten medizinischen und alltagssprachlichen Begriffe in den Sprachen DE, FR und IT zurück.\n"
        'Format: {"de": ["..."], "fr": ["..."], "it": ["..."]}\n'
        "Synonyme mit Umlauten (ä, ö, ü, é, è, à usw.) und 'ss' statt 'ß' im Deutschen.\n"
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



def _query_llm(term_data: Dict[str, str]) -> Dict[str, List[str]]:
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
        resp = model.generate_content(prompt, generation_config={"temperature": 0.05})
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
        client = OpenAI(api_key=api_key, base_url=base_url)
        try:
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
                    )
            else:
                resp = chat_completion_safe(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "Du bist ein hilfreicher Assistent."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=1,
                    timeout=60,
                    client=client,
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
    result: Dict[str, List[str]] = {}
    for lang in ("de", "fr", "it"):
        vals = data.get(lang) or []
        if isinstance(vals, list):
            result[lang] = [str(v).strip() for v in vals if isinstance(v, str)]
        else:
            result[lang] = []
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
            if isinstance(lkn_val, (str, int)):
                lkn = str(lkn_val)
            translations = trans or None
        else:
            term_de = str(item)
            translations = None

        logging.info("LLM request for %s (%s)", term_de, lkn or "-")
        by_lang: Dict[str, List[str]] = {}
        term_data = {"de": term_de}
        if translations:
            term_data.update(translations)
        try:
            by_lang = _query_llm(term_data)
        except Exception as e:  # pragma: no cover - network failures
            logging.warning("LLM lookup failed for '%s': %s", term_de, e)
            by_lang = {lang: [] for lang in languages}

        by_lang = _filter_cross_language_synonyms(by_lang)

        # aggregate all language lists for the synonyms field
        synonyms: List[str] = []
        for lang in languages:
            vals = _clean_variants(by_lang.get(lang, []))
            by_lang[lang] = vals
            synonyms.extend(vals)

        synonyms = _clean_variants(synonyms)

        yield SynonymEntry(base_term=term_de, synonyms=synonyms, lkn=lkn, by_lang=by_lang)
