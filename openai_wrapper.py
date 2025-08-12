# -*- coding: utf-8 -*-
"""
Robuster OpenAI-Chat-Wrapper:
- Entfernt 'temperature' automatisch für Modelle, die sie nicht unterstützen
- Wiederholt den Request einmal ohne 'temperature', wenn der Server mit
  'unsupported_value' für param='temperature' antwortet.
- Lässt alle anderen Optionen unverändert durch.
- Merkt sich fehlende 'temperature'-Unterstützung dauerhaft in ``config.ini``.
"""
from __future__ import annotations

import json
import logging
import configparser
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type hinting only
    from openai import OpenAI
    from openai.types.chat import ChatCompletionMessageParam
else:  # pragma: no cover - optional dependency not installed
    ChatCompletionMessageParam = Dict[str, Any]  # type: ignore[misc]

# Modelle mit fest verdrahteter/erzwungener Sampling-Temp (nachweislich: gpt-5-nano)
FIXED_SAMPLING_MODELS = {"gpt-5-nano"}

_CONFIG = configparser.ConfigParser()
_CONFIG_FILE = Path(__file__).with_name("config.ini")
_CONFIG.read(_CONFIG_FILE, encoding="utf-8")

_UNSUPPORTED_TEMPERATURE_MODELS = set()
if _CONFIG.has_section("LLM_CAPABILITIES"):
    for key, value in _CONFIG.items("LLM_CAPABILITIES"):
        if key.endswith("_supports_temperature") and value.strip() == "0":
            _UNSUPPORTED_TEMPERATURE_MODELS.add(
                key[: -len("_supports_temperature")]
            )


def _persist_temperature_flag(model: str, supported: bool) -> None:
    try:
        _CONFIG.read(_CONFIG_FILE, encoding="utf-8")
        if "LLM_CAPABILITIES" not in _CONFIG:
            _CONFIG["LLM_CAPABILITIES"] = {}
        _CONFIG["LLM_CAPABILITIES"][
            f"{model}_supports_temperature"
        ] = "1" if supported else "0"
        with _CONFIG_FILE.open("w", encoding="utf-8") as cfg:
            _CONFIG.write(cfg)
    except Exception:
        logging.exception(
            "Konnte Temperatur-Fähigkeit nicht in config.ini schreiben"
        )

_client_singleton: Optional["OpenAI"] = None


def get_client() -> "OpenAI":
    """Return a lazily constructed global OpenAI client instance."""
    global _client_singleton
    if _client_singleton is None:
        from openai import OpenAI  # type: ignore  # pragma: no cover - optional dependency
        _client_singleton = OpenAI()
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
        return client.chat.completions.create(model=model, messages=messages, **kwargs)
    except Exception as e:
        if _is_unsupported_temperature_error(e) and "temperature" in kwargs:
            logging.warning(
                "'%s' unterstützt 'temperature' nicht – speichere in config und wiederhole ohne 'temperature'.",
                model,
            )
            _UNSUPPORTED_TEMPERATURE_MODELS.add(model)
            _persist_temperature_flag(model, False)
            clean_kwargs = dict(kwargs)
            clean_kwargs.pop("temperature", None)
            return client.chat.completions.create(
                model=model, messages=messages, **clean_kwargs
            )
        raise
