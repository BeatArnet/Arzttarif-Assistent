"""
Kompakter Konnektivitätstest für OpenAI‑kompatible Provider (Fokus: Apertus).

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
import sys
import time
import configparser
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

import requests
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


def test_openai_compatible(provider: str, model: str, base_url: str, api_key: Optional[str], app_version: str) -> None:
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


def test_gemini(model: str) -> None:
    print("Gemini‑Test übersprungen (Fokus: OpenAI‑kompatibel/Apertus)")


def main() -> int:
    load_dotenv()
    cfg = configparser.ConfigParser()
    # Konfigurationsdatei robust finden (ENV, CWD, Repo-Root, Paket-Ordner)
    cfg_path_env = os.getenv("CONFIG_PATH")
    candidates = [
        Path(cfg_path_env) if cfg_path_env else None,
        Path.cwd() / "config.ini",
        Path(__file__).resolve().parent.parent / "config.ini",
        Path(__file__).resolve().parent / "config.ini",
    ]
    used_cfg = None
    for p in candidates:
        if p and p.exists():
            try:
                cfg.read(p, encoding="utf-8-sig")
                used_cfg = p
                break
            except Exception:
                pass
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
        test_gemini(m1)
    else:
        print(f"Unbekannter Provider: {p1}")

    print("\nHinweis: Falls HTML/Cloudflare gemeldet wird, blockiert eine WAF den Zugriff.\n"
          "Bitte Anbieter kontaktieren (Ray ID), anderen egress/Proxy nutzen oder Base-URL prüfen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
