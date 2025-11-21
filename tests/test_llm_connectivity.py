"""
Kompakter Konnektivitätstest für OpenAI‑kompatible Provider.

- Lädt Provider/Modell/Base‑URL aus config.ini/Umgebung
- GET <base_url>/models → listet verfügbare Modell‑IDs
- POST <base_url>/chat/completions → Minimal‑Konversation (doc‑konformes Schema)

Ausführung:
  python test_llm_connectivity.py

Relevante Umgebungsvariablen:
  STAGE1_LLM_PROVIDER, STAGE1_LLM_MODEL
  APERTUS_API_KEY, APERTUS_BASE_URL
  OPENAI_API_KEY, OPENAI_BASE_URL
  OLLAMA_API_KEY, OLLAMA_BASE_URL, OLLAMA_URL
  HTTPS_PROXY / HTTP_PROXY
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import configparser
from pathlib import Path
from typing import Iterable, Optional, Tuple, Dict, Any, List

import requests
import pytest
from dotenv import load_dotenv


DEFAULT_MODELS: Dict[str, str] = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    # Für Apertus gilt: Modell-IDs sind account-/cluster-spezifisch -> /models nutzen
    "apertus": "swiss-ai/apertus-70b-instruct",
}


def _env_name(provider: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in provider.upper())


def _get_api_key(cfg: configparser.ConfigParser, provider: str) -> Optional[str]:
    env_key = os.getenv(f"{_env_name(provider)}_API_KEY")
    if env_key:
        return env_key
    if cfg.has_section("API_KEYS"):
        try:
            return cfg.get("API_KEYS", f"{provider}_api_key")
        except Exception:
            pass
    return None


def _get_base_url(cfg: configparser.ConfigParser, provider: str) -> Optional[str]:
    env_url = os.getenv(f"{_env_name(provider)}_BASE_URL")
    if env_url:
        return env_url
    if cfg.has_section("API_ENDPOINTS"):
        try:
            return cfg.get("API_ENDPOINTS", f"{provider}_base_url")
        except Exception:
            pass
    # Defaults
    if provider == "openai":
        return "https://api.openai.com/v1"
    if provider == "apertus":
        # Discovery ergab: https://api.publicai.co/v1 ist funktional (/models liefert JSON)
        return "https://api.publicai.co/v1"
    if provider == "ollama":
        return os.getenv("OLLAMA_BASE_URL") or (os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/v1")
    return None


def _get_stage(cfg: configparser.ConfigParser, stage: str) -> Tuple[str, str]:
    p = os.getenv(f"{stage.upper()}_LLM_PROVIDER") or cfg.get("LLM1UND2", f"{stage}_provider", fallback="gemini")
    p = p.lower()
    m = (
        os.getenv(f"{stage.upper()}_LLM_MODEL")
        or cfg.get("LLM1UND2", f"{stage}_model", fallback=DEFAULT_MODELS.get(p, ""))
        or DEFAULT_MODELS.get(p, "")
    )
    return p, m


def _canonical_model_name(model_id: str) -> str:
    """Normalisiert eine Modell-ID (z. B. entfernt "models/"-Prefix)."""
    mid = (model_id or "").strip()
    if mid.startswith("models/"):
        mid = mid[len("models/"):]
    return mid


_FAMILY_SUFFIXES = (
    "-latest",
    "-beta",
    "-preview",
)


def _model_family(model_id: str) -> str:
    """Leitet aus einer Modell-ID die zugehörige Modellfamilie ab."""
    base = _canonical_model_name(model_id)
    if not base:
        return ""
    lowered = base.lower()
    for suffix in _FAMILY_SUFFIXES:
        if lowered.endswith(suffix):
            return base[: -len(suffix)]
    numeric_match = re.search(r"-(\d{2,3})$", lowered)
    if numeric_match:
        return base[: -len(numeric_match.group(0))]
    return base


def _family_matches(model_id: str, candidates: Iterable[str]) -> Tuple[str, List[str]]:
    """Filtert Kandidaten, die zur Modellfamilie der Referenz-ID gehören."""
    family = _model_family(model_id)
    if not family:
        return "", []
    family_lower = family.lower()
    matches: List[str] = []
    for candidate in candidates:
        canonical_candidate = _canonical_model_name(candidate)
        if canonical_candidate.lower().startswith(family_lower):
            matches.append(candidate)
    return family, matches




def _load_configuration() -> Tuple[configparser.ConfigParser, Optional[Path]]:
    load_dotenv()
    cfg = configparser.ConfigParser()
    # Konfigurationsdatei robust finden (ENV, CWD, Repo-Root, Paket-Ordner)
    cfg_path_env = os.getenv('CONFIG_PATH')
    candidates = [
        Path(cfg_path_env) if cfg_path_env else None,
        Path.cwd() / 'config.ini',
        Path(__file__).resolve().parent.parent / 'config.ini',
        Path(__file__).resolve().parent / 'config.ini',
    ]
    used_cfg: Optional[Path] = None
    for candidate in candidates:
        if candidate and candidate.exists():
            try:
                cfg.read(candidate, encoding='utf-8-sig')
                used_cfg = candidate
                break
            except Exception:
                pass
    return cfg, used_cfg


@pytest.fixture(scope='session')
def configuration() -> Tuple[configparser.ConfigParser, Optional[Path]]:
    return _load_configuration()


@pytest.fixture(scope='session')
def provider(configuration: Tuple[configparser.ConfigParser, Optional[Path]]) -> str:
    cfg, _ = configuration
    resolved_provider, _ = _get_stage(cfg, 'stage1')
    return resolved_provider


@pytest.fixture(scope='session')
def model(configuration: Tuple[configparser.ConfigParser, Optional[Path]]) -> str:
    cfg, _ = configuration
    _, resolved_model = _get_stage(cfg, 'stage1')
    return resolved_model


@pytest.fixture(scope='session')
def base_url(
    configuration: Tuple[configparser.ConfigParser, Optional[Path]],
    provider: str,
) -> Optional[str]:
    cfg, _ = configuration
    return _get_base_url(cfg, provider)


@pytest.fixture(scope='session')
def api_key(
    configuration: Tuple[configparser.ConfigParser, Optional[Path]],
    provider: str,
) -> Optional[str]:
    cfg, _ = configuration
    return _get_api_key(cfg, provider)


@pytest.fixture(scope='session')
def app_version(configuration: Tuple[configparser.ConfigParser, Optional[Path]]) -> str:
    cfg, _ = configuration
    return cfg.get('APP', 'version', fallback='dev')


def is_openai_compatible(provider: str) -> bool:
    return provider in {"openai", "apertus", "ollama"}


def _print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def _detect_html_block(txt: str) -> Optional[str]:
    t = txt.lower()
    if "cloudflare" in t or "<html" in t:
        return "Server lieferte HTML (mögliche WAF/Blockierung)."
    return None


def test_openai_compatible(provider: str, model: str, base_url: Optional[str], api_key: Optional[str], app_version: str) -> None:
    if not is_openai_compatible(provider):
        pytest.skip('Stage1 provider is not OpenAI-compatible.')
    if not base_url:
        pytest.skip(f'Base URL for {provider} is not configured.')
    if provider in {'openai', 'apertus'} and not api_key:
        pytest.skip(f'API key for {provider} is not configured.')
    assert base_url is not None
    print(f"Provider: {provider}")
    print(f"Model:    {model}")
    print(f"Base URL: {base_url}")
    print(f"API-Key:  {'gesetzt' if api_key else 'FEHLT'}")
    print(f"Proxy:    HTTPS_PROXY={os.getenv('HTTPS_PROXY') or ''}")

    headers = {
        "Authorization": f"Bearer {api_key}" if api_key else "",
        "Accept": "application/json",
        "User-Agent": f"Arzttarif-Assistent/{app_version}",
        "Content-Type": "application/json",
    }

    # 1) GET /models
    models_url = base_url.rstrip("/") + "/models"
    available_models: List[str] = []
    models_payload: List[Dict[str, Any]] = []
    try:
        r = requests.get(models_url, headers=headers, timeout=15)
        print(f"GET /models -> {r.status_code}")
        ctype = r.headers.get("content-type", "")
        if "application/json" in ctype:
            data = r.json()
            # Print summarized info
            if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                models_payload = [
                    {k: v for k, v in it.items() if k in {"id", "object", "created", "owned_by"}}
                    for it in data["data"] if isinstance(it, dict)
                ]
                available_models = [str(it.get("id")) for it in models_payload if it.get("id")]
                print(f"  Modelle: {len(models_payload)} Einträge")
                # Hervorhebung: alle swiss-ai Modelle (falls vorhanden)
                swiss_models = [m for m in available_models if m.lower().startswith("swiss-ai/")]
                if swiss_models:
                    print(f"  swiss-ai: {len(swiss_models)} Modelle")
                print("  Model-IDs:")
                for mid in available_models:
                    print(f"   - {mid}")
                family, fam_matches = _family_matches(model, available_models)
                if family:
                    if fam_matches:
                        print(f"  Modellfamilie '{family}*' ({len(fam_matches)} Treffer):")
                        for fam in fam_matches:
                            print(f"    - {fam}")
                    else:
                        print(f"  Hinweis: Kein Modell mit Präfix '{family}' gefunden.")
            else:
                print(f"  JSON: {list(data)[:5] if isinstance(data, dict) else type(data)}")
        else:
            hint = _detect_html_block(r.text)
            print(f"  content-type={ctype}")
            if hint:
                print(f"  Hinweis: {hint}")
            print(f"  Body (200 chars): {r.text[:200]!r}")
    except Exception as e:
        print(f"GET /models Fehler: {e}")

    # 2) POST /chat/completions (Minimal-Prompt)
    chat_url = base_url.rstrip("/") + "/chat/completions"
    # Modell wählen: konfiguriertes falls verfügbar, sonst erste chat-fähige ID
    chosen_model = model
    if available_models and model not in available_models:
        def _is_chat_capable(m: str) -> bool:
            ml = m.lower()
            return ("instruct" in ml or "chat" in ml) and ("embed" not in ml and "rerank" not in ml)
        candidates = [m for m in available_models if _is_chat_capable(m)] or available_models
        chosen_model = candidates[0]
        print(f"Hinweis: Konfiguriertes Modell nicht gefunden. Verwende: {chosen_model}")
    # Build a minimal, model‑compatible body
    if provider == "openai":
        # OpenAI gpt‑5 family: use string messages, no temperature override, use max_completion_tokens
        body = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'pong' if you are online."},
            ],
            "max_completion_tokens": 32,
            "user": f"arzttarif-assistent/{app_version}",
        }
    else:
        # Many OpenAI‑compatible vendors accept parts format and classic params
        body = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": [{"type": "text", "text": "You are a helpful assistant."}]},
                {"role": "user", "content": [{"type": "text", "text": "Say 'pong' if you are online."}]},
            ],
            "temperature": 0,
            "top_p": 1,
            "n": 1,
            "stream": False,
            "stop": [],
            "max_tokens": 32,
            "presence_penalty": 0,
            "frequency_penalty": 0,
            "logit_bias": {},
            "user": f"arzttarif-assistent/{app_version}",
        }
    def _print_response(label: str, resp: requests.Response) -> Tuple[int, Optional[Dict[str, Any]]]:
        print(f"{label} -> {resp.status_code}")
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                data = resp.json()
            except Exception:
                print("  JSON-Parse-Fehler")
                print(f"  Body (200 chars): {resp.text[:200]!r}")
                return resp.status_code, None
            # summarize
            reply = None
            try:
                reply = data["choices"][0]["message"]["content"]
            except Exception:
                pass
            if resp.status_code == 200:
                print(f"  OK: JSON erhalten. Antwort: {repr((reply or '')[:80])}")
            else:
                print(f"  Fehler-JSON: {json.dumps(data, ensure_ascii=False)[:400]}")
            return resp.status_code, data if isinstance(data, dict) else None
        else:
            hint = _detect_html_block(resp.text)
            print(f"  content-type={ctype}")
            if hint:
                print(f"  Hinweis: {hint}")
            print(f"  Body (200 chars): {resp.text[:200]!r}")
            return resp.status_code, None

    # Versuch 1: Standard-OpenAI-Body
    invalid_model = False
    try:
        r = requests.post(chat_url, headers=headers, json=body, timeout=30)
        status, data = _print_response("POST /chat/completions", r)
        if status == 200:
            return
        # Fallback: neue OpenAI-Modelle erwarten 'max_completion_tokens' statt 'max_tokens'
        try:
            err = (data or {}).get("error") if isinstance(data, dict) else None
            if isinstance(err, dict) and (err.get("param") == "max_tokens"):
                print("Hinweis: Erneuter Versuch mit 'max_completion_tokens'...")
                body2 = dict(body)
                body2.pop("max_tokens", None)
                body2["max_completion_tokens"] = 32
                r2 = requests.post(chat_url, headers=headers, json=body2, timeout=30)
                status2, _ = _print_response("POST /chat/completions (retry)", r2)
                if status2 == 200:
                    return
            # Fallback: einige Modelle erlauben keine explizite temperature → entferne sie
            if isinstance(err, dict) and (err.get("param") == "temperature"):
                print("Hinweis: Erneuter Versuch ohne 'temperature'...")
                body3 = dict(body)
                body3.pop("temperature", None)
                r3 = requests.post(chat_url, headers=headers, json=body3, timeout=30)
                status3, _ = _print_response("POST /chat/completions (retry2)", r3)
                if status3 == 200:
                    return
        except Exception:
            pass
        # Detect invalid model hints
        msg = ""
        try:
            if data and isinstance(data.get("error"), dict):
                msg = str(data["error"].get("message") or "")
        except Exception:
            pass
        invalid_model = ("Invalid model name" in msg) or ("/v1/models" in msg)
    except Exception as e:
        print(f"POST /chat/completions Fehler: {e}")

    # Bei ungültiger Modell-ID: Liste ausgeben und Hinweis
    if invalid_model and available_models:
        print("\nUngültige Modell-ID. Verfügbare Modelle:")
        for mid in available_models:
            print(f"  - {mid}")
        print("Bitte in config.ini unter [LLM1UND2] anpassen.")


def _list_gemini_models(model: str, api_key: Optional[str]) -> None:
    if not api_key:
        print("Gemini: GEMINI_API_KEY fehlt oder ist leer. Kann /models nicht abrufen.")
        return

    models_url = "https://generativelanguage.googleapis.com/v1beta/models"
    all_models: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    try:
        while True:
            params: Dict[str, Any] = {"key": api_key, "pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            resp = requests.get(models_url, params=params, timeout=20)
            print(f"GET /v1beta/models (pageToken={page_token or '∅'}) -> {resp.status_code}")
            if resp.status_code != 200:
                print(f"  Fehler: {resp.text[:400]!r}")
                return
            payload = resp.json()
            page_models = payload.get("models") or []
            all_models.extend(page_models)
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        print(f"Gemini /models Fehler: {exc}")
        return

    if not all_models:
        print("Gemini: API lieferte keine Modelle zurück.")
        return

    canonical_map: Dict[str, Dict[str, Any]] = {}
    for item in all_models:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("name", "")
        canonical_name = _canonical_model_name(raw_name)
        if canonical_name:
            canonical_map[canonical_name] = item

    print(f"Gemini: {len(canonical_map)} Modelle erkannt.")
    family, family_models = _family_matches(model, canonical_map.keys())
    if family:
        if family_models:
            print(f"  Modellfamilie '{family}*' ({len(family_models)} Treffer):")
            for fam in sorted(family_models):
                meta = canonical_map.get(_canonical_model_name(fam), {})
                display = meta.get("displayName") or fam
                methods = ", ".join(meta.get("supportedGenerationMethods") or []) or "-"
                prompt_limit = meta.get("inputTokenLimit") or meta.get("promptTokenLimit")
                prompt_info = f", Prompt-Limit: {prompt_limit}" if prompt_limit else ""
                print(f"    - {fam} ({display}; Methoden: {methods}{prompt_info})")
        else:
            print(f"  Hinweis: Kein Gemini-Modell mit Präfix '{family}' gefunden.")
    else:
        print("  Hinweis: Modellfamilie konnte nicht bestimmt werden (Stage1-Modell fehlt?).")


def test_gemini(model: str, provider: str, api_key: Optional[str]) -> None:
    if provider != 'gemini':
        pytest.skip('Stage1 provider is not Gemini.')
    if not api_key:
        pytest.skip('Gemini API key is not configured.')
    _list_gemini_models(model, api_key)



def main() -> int:
    cfg, used_cfg = _load_configuration()
    if not used_cfg:
        # Fallback: leere Config (Defaults/ENV werden genutzt)
        print("Warnung: config.ini nicht gefunden. Verwende Umgebungsvariablen/Defaults.")
    else:
        print(f"Verwende Konfiguration: {used_cfg}")
    app_version = cfg.get("APP", "version", fallback="dev")

    _print_header("Konnektivitätstest (einmalig)")
    p1, m1 = _get_stage(cfg, "stage1")
    b1 = _get_base_url(cfg, p1)
    k1 = _get_api_key(cfg, p1)
    if is_openai_compatible(p1) and b1:
        test_openai_compatible(p1, m1, b1, k1, app_version)
    elif p1 == "gemini":
        _list_gemini_models(m1, k1)
    else:
        print(f"Unbekannter Provider: {p1}")

    print("\nHinweis: Falls HTML/Cloudflare gemeldet wird, blockiert eine WAF den Zugriff.\n"
          "Bitte Anbieter kontaktieren (Ray ID), anderen egress/Proxy nutzen oder Base-URL prüfen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
