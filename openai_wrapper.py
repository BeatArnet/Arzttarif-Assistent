# -*- coding: utf-8 -*-
"""
Robuster OpenAI-Chat-Wrapper:
- Entfernt 'temperature' automatisch für Modelle, die sie nicht unterstützen
- Wiederholt den Request einmal ohne 'temperature', wenn der Server mit
  'unsupported_value' für param='temperature' antwortet.
- Lässt alle anderen Optionen unverändert durch.
- Merkt sich fehlende 'temperature'-Unterstützung dauerhaft in ``config.runtime.ini``.
"""
from __future__ import annotations

import json
import logging
import os
import configparser
from typing import Any, Dict, List, Optional, TYPE_CHECKING
import threading
import time
from runtime_config import (
    CONFIG_MAIN_PATH,
    load_merged_config,
    update_runtime_section,
)

if TYPE_CHECKING:  # pragma: no cover - type hinting only
    from openai import OpenAI
    from openai.types.chat import ChatCompletionMessageParam
else:  # pragma: no cover - optional dependency not installed
    ChatCompletionMessageParam = Dict[str, Any]  # type: ignore[misc]

# Modelle mit fest verdrahteter/erzwungener Sampling-Temp (nachweislich: gpt-5-nano)
FIXED_SAMPLING_MODELS = {"gpt-5-nano"}

try:
    _CONFIG = load_merged_config()
except Exception:
    logging.exception("Konfiguration konnte nicht vollständig geladen werden, nutze Fallback")
    _CONFIG = configparser.ConfigParser()
    try:
        _CONFIG.read(CONFIG_MAIN_PATH, encoding="utf-8-sig")
    except Exception:
        logging.exception("Fallback: config.ini konnte nicht gelesen werden")

_UNSUPPORTED_TEMPERATURE_MODELS = set()
if _CONFIG.has_section("LLM_CAPABILITIES"):
    for key, value in _CONFIG.items("LLM_CAPABILITIES"):
        if key.endswith("_supports_temperature") and value.strip() == "0":
            _UNSUPPORTED_TEMPERATURE_MODELS.add(
                key[: -len("_supports_temperature")]
            )


_APP_VERSION = _CONFIG.get("APP", "version", fallback="dev")
_UA_PRODUCT = os.getenv("APP_USER_AGENT_PRODUCT") or _CONFIG.get("APP", "user_agent_product", fallback="ArzttarifAssistent")
_USER_AGENT = f"{_UA_PRODUCT}/{_APP_VERSION}"

def _persist_temperature_flag(model: str, supported: bool) -> None:
    try:
        if "LLM_CAPABILITIES" not in _CONFIG:
            _CONFIG["LLM_CAPABILITIES"] = {}
        _CONFIG["LLM_CAPABILITIES"][
            f"{model}_supports_temperature"
        ] = "1" if supported else "0"
        update_runtime_section(
            "LLM_CAPABILITIES",
            {f"{model}_supports_temperature": "1" if supported else "0"},
        )
    except Exception:
        logging.exception(
            "Konnte Temperatur-Fähigkeit nicht in config.runtime.ini speichern"
        )

_client_singleton: Optional["OpenAI"] = None


# Globale LLM-Call-Drossel gemäss config.ini
def _read_llm_min_interval() -> float:
    try:
        if _CONFIG.has_section("LLM"):
            val = int(_CONFIG.get("LLM", "min_call_interval_seconds", fallback="0") or 0)
            # Begrenze auf 0..1000 Sekunden
            val = max(0, min(1000, val))
            return float(val)
    except Exception:
        pass
    return 0.0

_THROTTLE_LOCK = threading.Lock()
_LAST_CALL_TS: float = 0.0

def enforce_llm_min_interval() -> None:
    """Erzwingt den konfigurierten Mindestabstand zwischen zwei LLM-Aufrufen.

    Liest den Wert aus [LLM] min_call_interval_seconds (0..1000).
    Thread-sicher, prozesslokal.
    """
    interval = _read_llm_min_interval()
    if interval <= 0:
        return
    now = time.monotonic()
    with _THROTTLE_LOCK:
        global _LAST_CALL_TS
        elapsed = now - _LAST_CALL_TS if _LAST_CALL_TS else interval
        if elapsed < interval:
            wait = interval - elapsed
            try:
                logging.info("LLM_THROTTLE_WAIT: Warte %.2fs (min %.2fs) bis zum nächsten Aufruf.", wait, interval)
            except Exception:
                pass
            time.sleep(wait)
        _LAST_CALL_TS = time.monotonic()


def get_client() -> "OpenAI":
    """Return a lazily constructed global OpenAI client instance."""
    global _client_singleton
    if _client_singleton is None:
        from openai import OpenAI  # type: ignore  # pragma: no cover - optional dependency
        _client_singleton = OpenAI(default_headers={"User-Agent": _USER_AGENT})
    return _client_singleton


def _extract_error_payload(exc: Exception) -> Dict[str, Any]:
    """
    Versucht, den JSON-Body aus typischen OpenAI/HTTPX-Exceptions zu ziehen.
    Gibt {} zurück, wenn nichts brauchbares gefunden wird.
    """
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            return resp.json() or {}
        except Exception:  # pragma: no cover - fallback path
            try:
                txt = getattr(resp, "text", None)
                if isinstance(txt, str) and txt.strip().startswith("{"):
                    return json.loads(txt)
            except Exception:
                pass
    msg = getattr(exc, "message", None) or str(exc)
    if isinstance(msg, str) and msg.strip().startswith("{"):
        try:
            return json.loads(msg)
        except Exception:
            pass
    return {}


def _is_unsupported_temperature_error(exc: Exception) -> bool:
    """
    Erkennt die typische 400-Fehlermeldung der API:
      {'error': {'code': 'unsupported_value', 'param': 'temperature', ...}}
    """
    payload = _extract_error_payload(exc)
    err = payload.get("error") or {}
    if err.get("code") == "unsupported_value" and err.get("param") == "temperature":
        return True
    msg = (err.get("message") or "") + " " + str(getattr(exc, "message", "")) + " " + str(exc)
    msg = msg.lower()
    return ("temperature" in msg) and ("unsupported" in msg or "only the default" in msg)


def _is_unsupported_param_error(exc: Exception, param_name: str) -> bool:
    """Detects typical unsupported parameter errors in OpenAI-compatible APIs."""
    payload = _extract_error_payload(exc)
    err = payload.get("error") or {}
    if err.get("code") in {"unsupported_value", "invalid_request_error"} and err.get("param") == param_name:
        return True
    # Fallback by message substring
    msg = (err.get("message") or "") + " " + str(getattr(exc, "message", "")) + " " + str(exc)
    msg = msg.lower()
    return (param_name.lower() in msg) and ("unsupported" in msg or "invalid" in msg)


def chat_completion_safe(
    *,
    model: str,
    messages: List[ChatCompletionMessageParam],
    client: Optional["OpenAI"] = None,
    **kwargs: Any,
):
    """Wrapper around ``client.chat.completions.create`` with temperature handling."""
    client = client or get_client()
    if model in FIXED_SAMPLING_MODELS and "temperature" in kwargs:
        logging.debug(
            "Model %s erzwingt feste Temperatur – entferne 'temperature' proaktiv.", model
        )
        kwargs.pop("temperature", None)
    if model in _UNSUPPORTED_TEMPERATURE_MODELS and "temperature" in kwargs:
        logging.debug(
            "Model %s unterstützt 'temperature' nicht – entferne 'temperature'.",
            model,
        )
        kwargs.pop("temperature", None)
    try:
        # Drossel vor dem eigentlichen Request
        enforce_llm_min_interval()
        return client.chat.completions.create(model=model, messages=messages, **kwargs)
    except Exception as e:
        # 1) Fallback: 'max_tokens' → 'max_completion_tokens' (neue OpenAI-Modelle)
        if (
            ("max_tokens" in kwargs)
            and _is_unsupported_param_error(e, "max_tokens")
        ):
            logging.warning(
                "'%s' verlangt 'max_completion_tokens' statt 'max_tokens' – wiederhole mit umbenanntem Parameter.",
                model,
            )
            clean_kwargs = dict(kwargs)
            value = clean_kwargs.pop("max_tokens", None)
            if value is not None:
                clean_kwargs["max_completion_tokens"] = value
            # Kein zusätzlicher Wait bei unmittelbarem Retry aufgrund von Parametern
            return client.chat.completions.create(
                model=model, messages=messages, **clean_kwargs
            )
        if _is_unsupported_temperature_error(e) and "temperature" in kwargs:
            logging.warning(
                "'%s' unterstützt 'temperature' nicht – speichere in config und wiederhole ohne 'temperature'.",
                model,
            )
            _UNSUPPORTED_TEMPERATURE_MODELS.add(model)
            _persist_temperature_flag(model, False)
            clean_kwargs = dict(kwargs)
            clean_kwargs.pop("temperature", None)
            # Kein zusätzlicher Wait bei unmittelbarem Retry aufgrund von Parametern
            return client.chat.completions.create(
                model=model, messages=messages, **clean_kwargs
            )
        # Gracefully drop unsupported response_format (often not implemented by clones)
        try:
            extra_body = dict(kwargs.get("extra_body") or {})
        except Exception:
            extra_body = {}
        has_resp_fmt = ("response_format" in kwargs) or ("response_format" in extra_body)
        if has_resp_fmt and _is_unsupported_param_error(e, "response_format"):
            logging.warning(
                "'%s' unterstützt 'response_format' nicht – entferne und wiederhole.",
                model,
            )
            clean_kwargs = dict(kwargs)
            clean_kwargs.pop("response_format", None)
            if "extra_body" in clean_kwargs:
                eb = dict(clean_kwargs["extra_body"] or {})
                eb.pop("response_format", None)
                clean_kwargs["extra_body"] = eb
            # Kein zusätzlicher Wait bei unmittelbarem Retry aufgrund von Parametern
            return client.chat.completions.create(
                model=model, messages=messages, **clean_kwargs
            )
        raise
