"""Flask-Anwendung zur Koordination des zweistufigen LLM-Workflows.

Der Server führt Katalogdaten, Synonymerweiterung, Retrieval-Hilfen sowie die
Regelprüfer für Einzelleistungen und Pauschalen zusammen. Eingehende Anfragen
durchlaufen eine Pipeline: Stufe 1 extrahiert potenzielle Tarifcodes über ein
LLM, das Python-Backend prüft Mengen und Regeln, und Stufe 2 ordnet oder
korrigiert die Vorschläge bei Bedarf. Zusätzlich stellt das Modul
Qualitätssicherungs-Endpunkte, das Ausliefern der Weboberfläche sowie
umfangreiche Logging- und Telemetrie-Hooks bereit. Viele Importe bringen
Fallback-Stubs mit, damit Testläufe auch ohne Flask oder externe HTTP-Abhängigkeiten
funktionieren.
"""

import os
import re
import json
import math
import time # für Zeitmessung
import traceback # für detaillierte Fehlermeldungen
from pathlib import Path
# Use explicit module alias to avoid any name shadowing or analysis confusion
import datetime as dt
from functools import lru_cache
from importlib import import_module
from typing import Any, TYPE_CHECKING, Optional, Dict, List, Set, Union, cast, TypedDict, Tuple, Mapping, Protocol, Callable, DefaultDict

# Always initialize optional third-party helpers to a known value so static analyzers
# see a bound name even if the optional dependency is missing.
Compress: Optional[Any] = None
USING_FLASK_STUB = False


def _load_stub_module():
    """Lädt die Stub-Implementierung (tests.mocks bevorzugt, sonst mocks im Root)."""
    for module_name in ("tests.mocks", "mocks"):
        try:
            return import_module(module_name)
        except ModuleNotFoundError:
            continue
    raise ModuleNotFoundError("Kein mocks-Modul gefunden. Flask installieren oder Stubs bereitstellen.")

if TYPE_CHECKING:
    from flask import (
        Blueprint as FlaskBlueprint,
        Flask as FlaskType,
        Request as FlaskRequest,
        abort,
        jsonify,
        request,
        send_from_directory,
    )
else:
    try:
        from flask import (
            Blueprint as FlaskBlueprint,
            Flask as FlaskType,
            Request as FlaskRequest,
            abort,
            jsonify,
            request,
            send_from_directory,
        )
    except ModuleNotFoundError:
        USING_FLASK_STUB = True
        _stub_mod = _load_stub_module()
        FlaskBlueprint = _stub_mod.FlaskBlueprint
        FlaskType = _stub_mod.FlaskType
        FlaskRequest = _stub_mod.FlaskRequest
        abort = _stub_mod.abort
        jsonify = _stub_mod.jsonify
        request = _stub_mod.request
        send_from_directory = _stub_mod.send_from_directory

try:
    from flask_compress import Compress
except ModuleNotFoundError:
    Compress = None

Request = FlaskRequest

# Ensure a module-like ``flask`` object is always defined so that static analyzers
# (and code relying on ``flask`` namespace attributes) do not report undefined
# names even when the real dependency is missing during local development. When
# Flask is available we expose the real module; otherwise we create a lightweight
# namespace that mimics the relevant attributes provided by our fallbacks above.
if TYPE_CHECKING:
    import flask as _flask_module  # pragma: no cover - import only for typing
else:
    try:  # pragma: no cover - executed only when Flask is installed
        import flask as _flask_module
    except ModuleNotFoundError:  # pragma: no cover - matches fallback stub usage
        _stub_mod = _load_stub_module()
        _flask_module = _stub_mod.flask_namespace()

flask = cast(Any, _flask_module)

# Typing alias for chat message param to satisfy static analyzers
from typing import TypeAlias

_MsgParam: TypeAlias = Dict[str, Any]
try:
    import requests
    RequestsHTTPError = requests.exceptions.HTTPError
    RequestsRequestException = requests.exceptions.RequestException
except ModuleNotFoundError:
    _stub_mod = _load_stub_module()
    RequestsHTTPError = _stub_mod.RequestsHTTPError
    RequestsRequestException = _stub_mod.RequestsRequestException
    requests: Any = _stub_mod._DummyRequests()

HTTPError = RequestsHTTPError
RequestException = RequestsRequestException
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*a, **k) -> bool:
        """Fallback für python-dotenv: tut nichts und liefert False."""
        return False
from utils import (
    get_table_content,
    translate_rule_error_message,
    expand_compound_words,
    extract_keywords,
    extract_lkn_codes_from_text,
    extract_patient_demographics,
    rank_embeddings_entries,
    STOPWORDS,
    PatientDemographics,
    activate_table_content_cache,
    deactivate_table_content_cache,
)
from utils import (
    translate,
    translate_condition_type,
    create_html_info_link,
    get_lang_field,
    escape as html_escape,
)
import html
try:
    import bleach  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    bleach = None  # type: ignore
from prompts import get_stage1_prompt, get_stage2_mapping_prompt, get_stage2_ranking_prompt
from utils import (
    compute_token_doc_freq,
    rank_leistungskatalog_entries,
    count_tokens)
from synonyms.expander import expand_query, set_synonyms_enabled
from synonyms import storage
from synonyms.models import SynonymCatalog
from runtime_config import load_merged_config
from openai_wrapper import chat_completion_safe, enforce_llm_min_interval, ChatCompletionMessageParam
import configparser

import logging
from collections import defaultdict
from logging.handlers import RotatingFileHandler
import sys
import shutil

# Configure logging
lkn_to_tables_index: DefaultDict[str, List[str]] = defaultdict(list)
# Custom StreamHandler to handle encoding errors
class SafeEncodingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        """Schreibt Logzeilen robust unter Erhalt nicht-ASCII-Zeichen."""
        try:
            msg = self.format(record)
            stream = self.stream
            # Encode to UTF-8 with replacement for unencodable characters
            stream.write(msg.encode('utf-8', errors='replace').decode('utf-8', errors='ignore') + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

class SafeRotatingFileHandler(RotatingFileHandler):
    """Rotating handler that tolerates Windows file locks (e.g. OneDrive/AV)."""

    def rotate(self, source: str, dest: str) -> None:
        try:
            super().rotate(source, dest)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) != 32:
                raise
        # Fallback: copy current log and truncate instead of renaming
        try:
            if os.path.exists(source):
                shutil.copy2(source, dest)
            with open(source, "w", encoding=self.encoding or "utf-8") as fh:
                fh.truncate(0)
        except Exception:
            # If the fallback also fails, continue without rotating to avoid log spam
            return

# Get the root logger
root_logger = logging.getLogger()

# Remove any existing handlers
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
    try:
        handler.close()
    except Exception:
        pass

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Handler for standard logs
safe_handler = SafeEncodingStreamHandler(sys.stdout)
safe_handler.setFormatter(formatter)
root_logger.addHandler(safe_handler)

logger = logging.getLogger(__name__)  # Module-level logger

# Separate logger and handler for optional detailed output
detail_logger = logging.getLogger("detail")
for handler in detail_logger.handlers[:]:
    detail_logger.removeHandler(handler)
    try:
        handler.close()
    except Exception:
        pass
detail_handler = SafeEncodingStreamHandler(sys.stdout)
detail_handler.setFormatter(formatter)
detail_logger.addHandler(detail_handler)
detail_logger.propagate = False

# --- Konfiguration ---
load_dotenv()

# Default models per provider; can be extended as new providers are added
DEFAULT_MODELS: Dict[str, str] = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
}

# Zusätzliche Umgebungsvariablen-Aliase pro Provider (graceful fallback)
API_KEY_ENV_FALLBACKS: Dict[str, tuple[str, ...]] = {
    "gemini": ("GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY", "GEMINI_KEY"),
    "openai": ("OPENAI_KEY",),
    "apertus": ("APERTUS_API_KEY",),
    "ollama": ("OLLAMA_API_KEY",),
}

def _env_name(provider: str) -> str:
    """Return an environment variable prefix for ``provider``."""
    return re.sub(r"[^A-Z0-9]", "_", provider.upper())


# Helper to fetch API credentials generically (e.g. GEMINI_API_KEY)
def _get_api_key(provider: str) -> Optional[str]:
    """Liest einen API-Key aus Umgebungsvariablen oder config.ini für den Provider."""
    provider_env_key = _env_name(provider)
    env_candidates = [f"{provider_env_key}_API_KEY"]
    env_candidates.extend(API_KEY_ENV_FALLBACKS.get(provider.lower(), ()))
    for env_name in env_candidates:
        value = os.getenv(env_name)
        if value and value.strip():
            return value.strip()

    cfg = globals().get("config")
    if isinstance(cfg, configparser.ConfigParser):
        section = provider.upper()
        if cfg.has_section(section) and cfg.has_option(section, "api_key"):
            candidate = cfg.get(section, "api_key", fallback="")
            candidate = (candidate or "").strip()
            if candidate:
                return candidate

    return None


def _get_base_url(provider: str) -> Optional[str]:
    """Liest eine optionale Basis-URL für OpenAI-kompatible Provider."""
    return os.getenv(f"{_env_name(provider)}_BASE_URL")


# Lese optionale Einstellungen aus config.ini (ggf. mit Laufzeit-Overrides)
try:
    config = load_merged_config()
except Exception:
    logging.exception("Konfiguration konnte nicht vollständig geladen werden, nutze Fallback")
    config = configparser.ConfigParser()
    # Nutze utf-8-sig, um ein evtl. vorhandenes BOM (\ufeff) robust zu behandeln
    config.read(Path(__file__).with_name("config.ini"), encoding="utf-8-sig")


def _get_stage_settings(stage: str) -> tuple[str, str]:
    """Ermittelt Provider- und Modellnamen für Stage 1 oder 2 aus der Konfiguration."""
    provider_raw = config.get("LLM1UND2", f"{stage}_provider", fallback="gemini")
    provider = (provider_raw or "gemini").strip().lower() or "gemini"

    model_raw = config.get("LLM1UND2", f"{stage}_model", fallback=DEFAULT_MODELS.get(provider, ""))
    model = (model_raw or "").strip()
    if not model:
        model = DEFAULT_MODELS.get(provider, "")

    return provider, model

STAGE1_PROVIDER, STAGE1_MODEL = _get_stage_settings("stage1")
STAGE2_PROVIDER, STAGE2_MODEL = _get_stage_settings("stage2")
MODEL_TEMPERATURE_SECTION = "MODEL_TEMPERATURES"

def _get_float_option(section: str, option: str) -> Optional[float]:
    """Liest einen Float aus der Konfiguration und liefert None bei ungültigem Wert."""
    if config.has_option(section, option):
        try:
            return config.getfloat(section, option)
        except ValueError:
            raw_value = config.get(section, option, fallback="").strip()
            logger.warning(
                "Ignoriere ungueltigen Temperaturwert fuer %s.%s: %s",
                section,
                option,
                raw_value,
            )
    return None

def _default_temperature(stage_key: str, provider: str) -> Optional[float]:
    """Fallback-Temperatur pro Stage/Provider, falls keine Konfiguration vorhanden ist."""
    if provider == "openai":
        return None
    if provider == "apertus" and stage_key == "stage1":
        return 0.0
    if stage_key == "stage2_ranking":
        return 0.1
    return 0.05

def _resolve_temperature(stage_key: str, provider: str, model: str) -> Optional[float]:
    """Leitet die Temperatur aus Konfiguration oder Default-Regeln ab."""
    option = f"{stage_key}_temperature"
    explicit = _get_float_option("LLM1UND2", option)
    if explicit is not None:
        return explicit

    if config.has_section(MODEL_TEMPERATURE_SECTION):
        stage_specific = f"{model}@{stage_key}"
        value = _get_float_option(MODEL_TEMPERATURE_SECTION, stage_specific)
        if value is not None:
            return value
        value = _get_float_option(MODEL_TEMPERATURE_SECTION, model)
        if value is not None:
            return value

    return _default_temperature(stage_key, provider)

def _temperature_kwargs(temperature: Optional[float]) -> Dict[str, float]:
    """Konvertiert Temperaturwert in Keyword-Args für den Modellaufruf."""
    if temperature is None:
        return {}
    return {"temperature": float(temperature)}

STAGE1_TEMPERATURE = _resolve_temperature("stage1", STAGE1_PROVIDER, STAGE1_MODEL)
STAGE2_MAPPING_TEMPERATURE = _resolve_temperature("stage2_mapping", STAGE2_PROVIDER, STAGE2_MODEL)
STAGE2_RANKING_TEMPERATURE = _resolve_temperature("stage2_ranking", STAGE2_PROVIDER, STAGE2_MODEL)


# Fallback: if OpenAI is configured but no API key is available, use Gemini so
# that tests can run without external credentials.
if STAGE1_PROVIDER == "openai" and not os.getenv("OPENAI_API_KEY"):
    STAGE1_PROVIDER, STAGE1_MODEL = "gemini", DEFAULT_MODELS.get("gemini", "")
    STAGE1_TEMPERATURE = _resolve_temperature("stage1", STAGE1_PROVIDER, STAGE1_MODEL)

# Logging settings from config.ini
CONSOLE_LOG_LEVEL_NAME = config.get('LOGGING', 'console_level', fallback='INFO').upper()
CONSOLE_LOG_LEVEL = logging._nameToLevel.get(CONSOLE_LOG_LEVEL_NAME, logging.INFO)

# Set console handler level
safe_handler.setLevel(CONSOLE_LOG_LEVEL)
root_logger.setLevel(CONSOLE_LOG_LEVEL) # Root logger should be at the most permissive level

# Detaillierte Debug-Schalter
LOG_LLM_INPUT = config.getint('LOGGING', 'log_llm_input', fallback=0) == 1
if config.has_option('LOGGING', 'log_input_text'):
    LOG_INPUT_TEXT = config.getint('LOGGING', 'log_input_text', fallback=0) == 1
else:
    LOG_INPUT_TEXT = LOG_LLM_INPUT
if config.has_option('LOGGING', 'log_llm_prompt'):
    LOG_LLM_PROMPT = config.getint('LOGGING', 'log_llm_prompt', fallback=0) == 1
else:
    LOG_LLM_PROMPT = LOG_LLM_INPUT
LOG_LLM_OUTPUT = config.getint('LOGGING', 'log_llm_output', fallback=0) == 1
LOG_TOKENS = config.getint('LOGGING', 'log_tokens', fallback=0) == 1
LOG_S1_PARSED_JSON = config.getint('LOGGING', 'log_s1_parsed_json', fallback=0) == 1
LOG_HTML_OUTPUT = config.getint('LOGGING', 'log_html_output', fallback=0) == 1

# Determine if any detailed logging is enabled to set the detail_logger level
detail_logging_enabled = any([
    LOG_LLM_INPUT,
    LOG_INPUT_TEXT,
    LOG_LLM_PROMPT,
    LOG_LLM_OUTPUT,
    LOG_TOKENS,
    LOG_S1_PARSED_JSON,
    LOG_HTML_OUTPUT,
])

# The detail_logger is used for verbose, optional outputs.
# If any detailed flag is on, this logger must be set to INFO or DEBUG to capture the messages.
# The root logger's level is already set, so we only need to manage the detail_handler.
if detail_logging_enabled:
    detail_logger.setLevel(logging.INFO) # Or DEBUG if you have finer-grained levels
    detail_handler.setLevel(logging.INFO)
else:
    # If no detailed logging is active, set the level high to ignore all info messages.
    detail_logger.setLevel(logging.WARNING)
    detail_handler.setLevel(logging.WARNING)

# Optional: Dateibasiertes Logging (RotatingFileHandler) per config.ini
try:
    LOG_FILE_ENABLED = config.getint('LOGGING', 'file_enabled', fallback=0) == 1
except Exception:
    LOG_FILE_ENABLED = False
LOG_FILE_PATH = config.get('LOGGING', 'file_path', fallback='')
try:
    LOG_FILE_MAX_BYTES = max(0, config.getint('LOGGING', 'file_max_bytes', fallback=1048576))
except Exception:
    LOG_FILE_MAX_BYTES = 1048576
try:
    LOG_FILE_BACKUP_COUNT = max(0, config.getint('LOGGING', 'file_backup_count', fallback=5))
except Exception:
    LOG_FILE_BACKUP_COUNT = 5
LOG_FILE_LEVEL_NAME = config.get('LOGGING', 'file_level', fallback=CONSOLE_LOG_LEVEL_NAME).upper()
LOG_FILE_LEVEL = logging._nameToLevel.get(LOG_FILE_LEVEL_NAME, CONSOLE_LOG_LEVEL)

file_handler: Optional[SafeRotatingFileHandler] = None

if LOG_FILE_ENABLED and LOG_FILE_PATH:
    try:
        log_path = Path(LOG_FILE_PATH)
        if log_path.parent and not log_path.parent.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = SafeRotatingFileHandler(
            LOG_FILE_PATH,
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding='utf-8',
            delay=True,
        )
        file_handler.setLevel(LOG_FILE_LEVEL)
        file_handler.setFormatter(formatter)
        # An Root-Logger anhängen
        root_logger.addHandler(file_handler)
        # Auch Detail-Logger schreibt in Datei
        detail_logger.addHandler(file_handler)
    except Exception as _file_log_exc:
        try:
            logger.warning("Dateilogs konnten nicht initialisiert werden: %s", _file_log_exc)
        except Exception:
            pass

# Ensure that Werkzeug's startup messages (including the server URLs) are
# always visible so users know where to access the HTML GUI. We attach a
# dedicated handler and disable propagation to prevent these logs from being
# filtered by the root logger or appearing twice.
werkzeug_logger = logging.getLogger('werkzeug')
for handler in werkzeug_logger.handlers[:]:
    werkzeug_logger.removeHandler(handler)
    try:
        handler.close()
    except Exception:
        pass
desired_werkzeug_level = max(CONSOLE_LOG_LEVEL, logging.INFO)
werkzeug_logger.setLevel(desired_werkzeug_level)
werkzeug_handler = SafeEncodingStreamHandler(sys.stdout)
werkzeug_handler.setFormatter(formatter)
werkzeug_handler.setLevel(desired_werkzeug_level)
werkzeug_logger.addHandler(werkzeug_handler)
werkzeug_logger.propagate = False

# Falls Dateilogs aktiv sind, auch Werkzeug-Logs in Datei schreiben
if file_handler is not None:
    try:
        werkzeug_logger.addHandler(file_handler)
    except Exception:
        pass

# --- HTML Sanitization (server-side) ---
ALLOWED_HTML_TAGS: list[str] = [
    # text / structure
    'div', 'span', 'p', 'ul', 'ol', 'li', 'br', 'b', 'i', 'em', 'strong', 'code', 'hr',
    # interactive summaries used by explanations
    'details', 'summary',
    # links used by frontend handlers (info-link, pauschale-exp-link)
    'a',
    # optional: icons created by condition lists
    'svg', 'use',
]

ALLOWED_HTML_ATTRS: dict[str, list[str]] = {
    '*': ['class'],
    'a': ['href', 'target', 'rel', 'data-code', 'data-type', 'data-content'],
    'svg': ['viewBox'],
    'use': ['xlink:href', 'href'],
    'details': ['open', 'class'],
    'summary': ['class'],
}

def sanitize_html_fragment(html_text: str) -> str:
    """Sanitize an HTML fragment while preserving required data-* attributes and links.

    Falls bleach nicht installiert ist, wird der Text unverändert zurückgegeben.
    """
    if not isinstance(html_text, str):
        return ''
    if bleach is None:
        # Best-effort: return as-is to avoid breaking output in test environments
        return html_text
    try:
        cleaned = bleach.clean(
            html_text,
            tags=ALLOWED_HTML_TAGS,
            attributes=ALLOWED_HTML_ATTRS,
            strip=True,
            protocols=['http', 'https', 'mailto'],
        )
        # Ensure external links are safe
        cleaned = cleaned.replace('target="_blank"', 'target="_blank" rel="noopener noreferrer"')
        return cleaned
    except Exception as _san_exc:  # pragma: no cover - robust fallback
        try:
            logger.warning("Sanitize failed, returning original HTML: %s", _san_exc)
        except Exception:
            pass
        return html_text

def _sanitize_abrechnung_payload(abrechnung: dict[str, Any] | None) -> dict[str, Any] | None:
    """Sanitize known HTML fields within the 'abrechnung' object returned to clients.

    - abrechnung['bedingungs_pruef_html']
    - abrechnung['details']['pauschale_erklaerung_html']
    - abrechnung['evaluated_pauschalen'][i]['bedingungs_pruef_html']
    """
    if not isinstance(abrechnung, dict):
        return abrechnung
    try:
        if 'bedingungs_pruef_html' in abrechnung:
            abrechnung['bedingungs_pruef_html'] = sanitize_html_fragment(abrechnung.get('bedingungs_pruef_html') or '')
        details = abrechnung.get('details')
        if isinstance(details, dict) and 'pauschale_erklaerung_html' in details:
            details['pauschale_erklaerung_html'] = sanitize_html_fragment(details.get('pauschale_erklaerung_html') or '')
        eval_list = abrechnung.get('evaluated_pauschalen')
        if isinstance(eval_list, list):
            for item in eval_list:
                if isinstance(item, dict) and 'bedingungs_pruef_html' in item:
                    item['bedingungs_pruef_html'] = sanitize_html_fragment(item.get('bedingungs_pruef_html') or '')
    except Exception as _:
        # Keep payload intact even if sanitization fails for some element
        pass
    return abrechnung


def _normalize_gender(value: Any) -> str:
    """Normalize various gender inputs to 'm' or 'w' used by rule engine.

    Accepts German/French/Italian/English synonyms and single letters.
    Returns 'unbekannt' if not recognized.
    """
    if value is None:
        return 'unbekannt'
    s = str(value).strip().lower()
    if not s:
        return 'unbekannt'
    female = {
        'w', 'f', 'weiblich', 'frau', 'feminin', 'féminin', 'femminile', 'female', 'woman', 'donna', 'femme'
    }
    male = {
        'm', 'männlich', 'mann', 'masculin', 'maschio', 'male', 'homme', 'uomo'
    }
    if s in female:
        return 'w'
    if s in male:
        return 'm'
    return s  # passt ggf. schon ('w'/'m') oder bleibt als freier Wert


class CombinedDemographics(TypedDict, total=False):
    age_value: Optional[int]
    age_operator: Optional[str]
    age_source: Optional[str]
    gender_value: Optional[str]
    gender_source: Optional[str]


def _merge_patient_demographics(
    alter_user: Optional[int],
    geschlecht_user: Optional[str],
    extracted_info: Dict[str, Any],
    heuristic_demo: PatientDemographics | None,
) -> CombinedDemographics:
    """Combine user, LLM and heuristics to derive age/gender context."""

    if heuristic_demo is None:
        heuristic_demo = cast(PatientDemographics, {})

    def _clean_operator(value: Any) -> Optional[str]:
        """Validiert Alters-Vergleichsoperatoren und gibt nur erlaubte zurück."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped in {"<", "<=", "=", ">=", ">"}:
                return stripped
        return None

    age_value: Optional[int] = None
    age_operator: Optional[str] = None
    age_source: Optional[str] = None
    if isinstance(alter_user, int):
        age_value = alter_user
        age_operator = "="
        age_source = "user"
    else:
        extracted_age = extracted_info.get("alter")
        if isinstance(extracted_age, int):
            age_value = extracted_age
            age_operator = _clean_operator(extracted_info.get("alter_operator")) or "="
            age_source = "llm"
        else:
            heur_age = heuristic_demo.get("age_value")
            if isinstance(heur_age, int):
                age_value = heur_age
                age_operator = _clean_operator(heuristic_demo.get("age_operator"))
                if not age_operator:
                    age_operator = "=" if heuristic_demo.get("age_source") == "text" else "<="
                age_source = str(heuristic_demo.get("age_source") or "heuristic")

    if age_value is not None and not age_operator:
        age_operator = "="

    gender_value: Optional[str] = None
    gender_source: Optional[str] = None
    if geschlecht_user:
        normalized = _normalize_gender(geschlecht_user)
        if normalized != 'unbekannt':
            gender_value = normalized
            gender_source = "user"
    if not gender_value or gender_value == 'unbekannt':
        extracted_gender = extracted_info.get("geschlecht")
        if isinstance(extracted_gender, str) and extracted_gender.strip():
            normalized = _normalize_gender(extracted_gender)
            if normalized != 'unbekannt':
                gender_value = normalized
                gender_source = "llm"
    if not gender_value or gender_value == 'unbekannt':
        heur_gender = heuristic_demo.get("gender")
        if isinstance(heur_gender, str) and heur_gender.strip():
            normalized = _normalize_gender(heur_gender)
            if normalized != 'unbekannt':
                gender_value = normalized
                gender_source = str(heuristic_demo.get("gender_source") or "heuristic")
    if not gender_value:
        gender_value = 'unbekannt'

    return cast(
        CombinedDemographics,
        {
            "age_value": age_value,
            "age_operator": age_operator,
            "age_source": age_source,
            "gender_value": gender_value,
            "gender_source": gender_source,
        },
    )


def _coerce_age_value(value: Any) -> Optional[float]:
    """Convert raw TARDOC min/max age values to float."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _extract_tardoc_demographics(info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return normalized demographic constraints from a TARDOC record."""

    min_age = _coerce_age_value(info.get("MinAlter"))
    max_age = _coerce_age_value(info.get("MaxAlter"))
    unit_texts = {
        "de": info.get("Einheit_Text_d"),
        "fr": info.get("Einheit_Text_f"),
        "it": info.get("Einheit_Text_i"),
    }
    unit_texts = {lang: text for lang, text in unit_texts.items() if isinstance(text, str) and text.strip()}

    gender_raw = info.get("Geschlecht")
    gender_map = {"0": "m", "1": "w", "M": "m", "W": "w"}
    gender_norm = None
    if isinstance(gender_raw, str):
        gender_norm = gender_map.get(gender_raw.strip())
    elif isinstance(gender_raw, (int, float)):
        gender_norm = gender_map.get(str(int(gender_raw)))

    result: Dict[str, Any] = {}
    if min_age is not None:
        result["min_age"] = min_age
    if max_age is not None:
        result["max_age"] = max_age
    if unit_texts:
        result["unit_texts"] = unit_texts
    if gender_norm:
        result["gender"] = gender_norm

    if 'Kapitel' in info:
        kapitel_text = str(info.get("Kapitel", "")).lower()
    else:
        kapitel_text = ""
    bezeichnung_text = str(info.get("Bezeichnung", "")).lower()
    is_surcharge = "zuschlag" in kapitel_text or "zuschlag" in bezeichnung_text

    kapitel_nummer = str(info.get("KapitelNummer", "")).strip()
    if kapitel_nummer:
        result["kapitel_nummer"] = kapitel_nummer
    kapitel_name = str(info.get("Kapitel", "")).strip()
    if kapitel_name:
        result["kapitel"] = kapitel_name

    if result and is_surcharge:
        result["is_surcharge"] = True

    return result or None


_GENDER_LABELS = {
    "m": {"de": "nur männlich", "fr": "masculin uniquement", "it": "solo maschile"},
    "w": {"de": "nur weiblich", "fr": "féminin uniquement", "it": "solo femminile"},
}

_GENDER_TOKEN_HINTS = {
    "m": ["männlich", "maennlich", "male", "homme", "maschio", "uomo", "mann", "garcon", "boy"],
    "w": ["weiblich", "female", "femme", "frau", "donna", "fille", "ragazza", "girl"],
}

_AGE_UNIT_FALLBACK = {"de": "Jahre", "fr": "ans", "it": "anni", "en": "years"}


def _format_tardoc_demographics(code: str, lang: str) -> Optional[str]:
    """Generate a localized demographic string for the given LKN."""

    info = tardoc_demographic_cache.get(code)
    if not info:
        return None

    parts: List[str] = []
    unit_texts: Dict[str, str] = info.get("unit_texts", {}) if isinstance(info.get("unit_texts"), dict) else {}
    unit_text = unit_texts.get(lang) or unit_texts.get("de") or _AGE_UNIT_FALLBACK["de"]

    def _fmt(value: float | None) -> Optional[str]:
        """Formatiert Alterswerte kompakt ohne Nachkommastellen, falls Integer."""
        if value is None:
            return None
        if float(value).is_integer():
            return str(int(value))
        return f"{value:g}"

    min_age = info.get("min_age")
    max_age = info.get("max_age")
    min_str = _fmt(min_age) if isinstance(min_age, (int, float)) else None
    max_str = _fmt(max_age) if isinstance(max_age, (int, float)) else None

    if min_str:
        parts.append(f"ab {min_str} {unit_text}")
    if max_str:
        parts.append(f"bis {max_str} {unit_text}")

    gender = info.get("gender")
    if isinstance(gender, str) and gender in _GENDER_LABELS:
        label = _GENDER_LABELS[gender].get(lang) or _GENDER_LABELS[gender]["de"]
        parts.append(label)

    return "; ".join(parts) if parts else None


def _format_age_value_for_tokens(value: float) -> str:
    """Formatiert Alterswerte für Token-Listen (Integer ohne Dezimalpunkt)."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _build_demographic_seed_terms(demo: PatientDemographics) -> List[str]:
    """Generate multilingual tokens that describe inferred demographics."""

    tokens: List[str] = []
    age_value = demo.get("age_value")
    operator = demo.get("age_operator")
    age_num = None
    if isinstance(age_value, (int, float)):
        age_num = float(age_value)
        age_str = _format_age_value_for_tokens(age_num)
        tokens.extend([
            f"{age_str} {_AGE_UNIT_FALLBACK['de']}",
            f"{age_str} {_AGE_UNIT_FALLBACK['fr']}",
            f"{age_str} {_AGE_UNIT_FALLBACK['it']}",
            f"{age_str} {_AGE_UNIT_FALLBACK['en']}",
            f"Alter {age_str}",
            f"age {age_str}",
        ])
        if operator in {"<", "<="}:
            tokens.extend([
                f"bis {age_str} {_AGE_UNIT_FALLBACK['de']}",
                f"moins de {age_str} {_AGE_UNIT_FALLBACK['fr']}",
                f"fino a {age_str} {_AGE_UNIT_FALLBACK['it']}",
                f"under {age_str} {_AGE_UNIT_FALLBACK['en']}",
                f"<={age_str}",
            ])
        elif operator in {">", ">="}:
            tokens.extend([
                f"ab {age_str} {_AGE_UNIT_FALLBACK['de']}",
                f"au moins {age_str} {_AGE_UNIT_FALLBACK['fr']}",
                f"almeno {age_str} {_AGE_UNIT_FALLBACK['it']}",
                f"over {age_str} {_AGE_UNIT_FALLBACK['en']}",
                f">={age_str}",
            ])
        elif operator == "=":
            tokens.extend([
                f"genau {age_str} {_AGE_UNIT_FALLBACK['de']}",
                f"exactement {age_str} {_AGE_UNIT_FALLBACK['fr']}",
                f"esattamente {age_str} {_AGE_UNIT_FALLBACK['it']}",
                f"exactly {age_str} {_AGE_UNIT_FALLBACK['en']}",
            ])

        if age_num <= 12:
            tokens.extend(["Kind", "Kinder", "Kindern", "child", "children", "enfant", "enfants", "pediatrie", "pédiatrie", "bambino", "bambini", "pediatric"])
        if age_num >= 65:
            tokens.extend(["Senioren", "Senior", "geriatrie", "gériatrie", "anziani", "elderly", "aged", "personnes âgées"])

    gender_value = demo.get("gender") or demo.get("gender_value")
    if isinstance(gender_value, str):
        gender_tokens = _GENDER_TOKEN_HINTS.get(gender_value.lower())
        if gender_tokens:
            tokens.extend(gender_tokens)

    # Deduplicate while preserving order
    deduped = list(dict.fromkeys(token for token in tokens if isinstance(token, str) and token.strip()))
    return deduped


def _match_codes_for_demographics(demo: PatientDemographics) -> Set[str]:
    """Return TARDOC codes whose demographic constraints match the inferred patient info."""

    matches: Set[str] = set()
    if not tardoc_demographic_cache or not isinstance(demo, dict):
        return matches

    age_value = demo.get("age_value")
    age_operator = demo.get("age_operator")
    age_known = isinstance(age_value, (int, float))

    user_min = -math.inf
    user_max = math.inf
    if age_known:
        val = float(age_value)  # type: ignore[arg-type]
        if age_operator in (None, "="):
            user_min = user_max = val
        elif age_operator == ">=":
            user_min = val
        elif age_operator == ">":
            user_min = val + 1e-6
        elif age_operator == "<=":
            user_max = val
        elif age_operator == "<":
            user_max = val - 1e-6
        else:
            user_min = user_max = val

    raw_gender = demo.get("gender") or demo.get("gender_value")
    gender_norm = None
    if isinstance(raw_gender, str) and raw_gender:
        gender_norm = raw_gender.lower()[0]

    for code, info in tardoc_demographic_cache.items():
        if not info.get("is_surcharge"):
            continue
        chapter = str(
            info.get("kapitel_nummer")
            or info.get("KapitelNummer")
            or ""
        ).strip()
        if chapter and not chapter.startswith("CG.15"):
            continue
        code_min = info.get("min_age")
        code_max = info.get("max_age")
        if (code_min is not None or code_max is not None) and not age_known:
            continue
        if isinstance(code_min, (int, float)) and user_max < float(code_min):
            continue
        if isinstance(code_max, (int, float)) and user_min > float(code_max):
            continue
        code_gender = info.get("gender")
        if code_gender:
            if not gender_norm:
                continue
            if gender_norm != code_gender:
                continue
        matches.add(code)

    return matches


# --- Rendering helpers for structured Pauschale conditions ---
def render_condition_groups_html(structured: dict[str, Any], lang: str = 'de') -> str:
    """Render HTML for structured condition groups.

    This function expects the structure returned by
    regelpruefer_pauschale.check_pauschale_conditions_structured.
    """
    try:
        groups = structured.get('groups') or []
        inter_ops = structured.get('inter_group_ops') or []

        def _normalize_identifier(value: Any) -> Any:
            """Normalisiert Gruppen-IDs auf int oder bereinigte Strings."""
            if value is None:
                return None
            try:
                return int(str(value).strip())
            except Exception:
                return str(value).strip()

        raw_children = structured.get('group_children') or {}
        normalized_children: dict[Any, list[tuple[Any, str]]] = {}
        for parent_key, entries in raw_children.items():
            parent_norm = _normalize_identifier(parent_key)
            if parent_norm is None:
                continue
            normalized_entries: list[tuple[Any, str]] = []
            for entry in entries or []:
                child_norm = _normalize_identifier(entry.get('child'))
                op_norm = str(entry.get('operator') or '').upper()
                normalized_entries.append((child_norm, op_norm))
            normalized_children[parent_norm] = normalized_entries

        group_index_map: dict[Any, int] = {}
        for idx, group in enumerate(groups):
            gid_norm = _normalize_identifier(group.get('normalized_id', group.get('id')))
            group['normalized_id'] = gid_norm
            if gid_norm is not None:
                group_index_map[gid_norm] = idx

        parent_link: dict[Any, tuple[Any, str]] = {}
        for parent_gid, children in normalized_children.items():
            for child_gid, op_val in children:
                if child_gid is None:
                    continue
                parent_link[child_gid] = (parent_gid, op_val)

        @lru_cache(maxsize=None)
        def _cluster_end_for(group_id: Any) -> int:
            """Berechnet das Ende eines UND-Clusters, um Klammerung korrekt zu rendern."""
            idx = group_index_map.get(group_id)
            if idx is None:
                return -1
            max_idx = idx
            for child_gid, op_val in normalized_children.get(group_id, []):
                if op_val != 'UND':
                    continue
                child_end = _cluster_end_for(child_gid)
                if child_end > max_idx:
                    max_idx = child_end
            return max_idx

        cluster_starts: dict[int, list[dict[str, Any]]] = {}
        for parent_gid, children in normalized_children.items():
            und_children = [child_gid for child_gid, op_val in children if op_val == 'UND']
            if not und_children:
                continue
            parent_idx = group_index_map.get(parent_gid)
            if parent_idx is None:
                continue
            parent_parent = parent_link.get(parent_gid)
            if parent_parent and parent_parent[1] == 'UND':
                continue  # Teil einer bestehenden UND-Kette, Cluster startet weiter oben
            max_idx = parent_idx
            for child_gid in und_children:
                child_end_idx = _cluster_end_for(child_gid)
                if child_end_idx > max_idx:
                    max_idx = child_end_idx
            if max_idx > parent_idx:
                cluster_starts.setdefault(parent_idx, []).append({
                    'end_index': max_idx,
                    'parent_id': parent_gid,
                })

        connector_index = 0
        prueflogik_expr = structured.get('prueflogik_expr')
        prueflogik_pretty = structured.get('prueflogik_pretty')
        group_logic_terms = structured.get('group_logic_terms') or []
        prueflogik_header = ""
        expr_trimmed = prueflogik_expr.strip() if isinstance(prueflogik_expr, str) else ""
        pretty_trimmed = str(prueflogik_pretty).strip() if isinstance(prueflogik_pretty, str) else ""
        if expr_trimmed or pretty_trimmed:
            label_text = translate('prueflogik_header', lang)
            prueflogik_header = (
                f"<div class=\"condition-prueflogik\"><strong>{html_escape(label_text)}</strong></div>"
            )
        if not groups:
            empty_parts: list[str] = []
            if prueflogik_header:
                empty_parts.append(prueflogik_header)
            empty_parts.append(f"<p><i>{html_escape(translate('no_conditions_for_pauschale', lang))}</i></p>")
            return "".join(empty_parts)

        html_parts: list[str] = [prueflogik_header] if prueflogik_header else []
        active_clusters: list[dict[str, Any]] = []

        for gi, group in enumerate(groups):
            gid = group.get('id')
            gid_norm = group.get('normalized_id', gid)
            group_negated = bool(group.get('negated'))
            while active_clusters and active_clusters[-1]['end_index'] < gi:
                html_parts.append("</div>")
                active_clusters.pop()

            current_op_raw = ""
            if gi > 0 and connector_index < len(inter_ops):
                current_op_raw = str(inter_ops[connector_index] or "").upper()
            if gi > 0:
                connector_index += 1
                if current_op_raw in ("UND", "ODER"):
                    op_label = translate('AND' if current_op_raw == 'UND' else 'OR', lang)
                    if active_clusters:
                        html_parts.append(
                            f"<div class=\"condition-separator cluster-operator\">{html_escape(op_label)}</div>"
                        )
                    else:
                        html_parts.append(
                            f"<div class=\"condition-separator inter-group-operator\">{html_escape(op_label)}</div>"
                        )

            for cluster_info in cluster_starts.get(gi, []):
                html_parts.append("<div class=\"condition-group-cluster\">")
                active_clusters.append(cluster_info)

            title = f"{translate('condition_group', lang)} {html_escape(str(gid))}"
            group_class = "condition-group condition-group-negated" if group_negated else "condition-group"
            html_parts.append(f"<div class=\"{group_class}\"><div class=\"condition-group-title\">{title}</div>")

            conditions = group.get('conditions') or []
            intra_ops = group.get('intra_ops') or []
            for ci, cond in enumerate(conditions):
                if ci > 0 and (ci - 1) < len(intra_ops):
                    link_op = (intra_ops[ci - 1] or '').upper()
                    if link_op in ('UND', 'ODER'):
                        if group_negated and link_op == 'UND':
                            op_label = translate('AND_NOT', lang)
                        elif group_negated and link_op == 'ODER':
                            op_label = translate('OR_NOT', lang)
                        else:
                            op_label = translate('AND' if link_op == 'UND' else 'OR', lang)
                        html_parts.append(
                            f"<div class=\"condition-separator intra-group-operator\">{html_escape(op_label)}</div>"
                        )

                matched = bool(cond.get('matched'))
                display_matched = (not matched) if group_negated else matched
                icon_svg_path = "#icon-check" if display_matched else "#icon-cross"
                icon_class = "condition-icon-fulfilled" if display_matched else "condition-icon-not-fulfilled"
                cond_type = str(cond.get('type', 'N/A'))
                cond_type_display = translate_condition_type(cond_type, lang)
                value_html = _render_condition_value_html(cond, lang)

                html_parts.append(
                    """
                    <div class="condition-item">
                        <span class="condition-status-icon {icon_class}">
                            <svg viewBox="0 0 24 24"><use xlink:href="{icon_svg_path}"></use></svg>
                        </span>
                        <span class="condition-type-display">{cond_type_display}:</span>
                        <span class="condition-text-wrapper">{value_html}</span>
                    </div>
                    """.format(
                        icon_class=icon_class,
                        icon_svg_path=icon_svg_path,
                        cond_type_display=html_escape(cond_type_display),
                        value_html=value_html,
                    )
                )

            html_parts.append("</div>")

        while active_clusters:
            html_parts.append("</div>")
            active_clusters.pop()

        return "".join(html_parts)
    except Exception as _render_exc:
        try:
            logger.error("render_condition_groups_html failed: %s", _render_exc)
        except Exception:
            pass
        return "<p><i>Rendering error</i></p>"


def _render_condition_value_html(cond: dict[str, Any], lang: str = 'de') -> str:
    """Render the display value of a condition (links, values)."""
    ctype = str(cond.get('type', '')).upper()
    raw_values = str(cond.get('werte') or '').strip()
    if not raw_values:
        return f"<i>{html_escape(translate('not_specified', lang))}</i>"

    try:
        if ctype in ("GESCHLECHT IN LISTE",):
            # Display rule's allowed genders using abbreviations (W/M)
            tokens = [v.strip() for v in raw_values.split(',') if v.strip()]
            if not tokens:
                return f"<i>{html_escape(translate('no_gender_spec', lang))}</i>"
            abbrev: list[str] = []
            for t in tokens:
                canon = _normalize_gender(t)
                if canon == 'w':
                    abbrev.append('W')
                elif canon == 'm':
                    abbrev.append('M')
                else:
                    abbrev.append(str(t).strip().upper())
            return f"{html_escape(translate('geschlecht_list', lang))}{', '.join(html_escape(x) for x in abbrev)}"

        if ctype in ("ALTER IN JAHREN BEI EINTRITT",):
            op = str(cond.get('vergleich') or '').strip()
            val = raw_values
            # Show only the comparator and value; the type label is rendered separately
            return f"{html_escape(op)} {html_escape(val)}" if op else html_escape(val)

        if ctype in ("ANZAHL",):
            op = str(cond.get('vergleich') or '').strip()
            val = raw_values
            return html_escape(translate('anzahl_condition', lang, value=f"{op} {val}".strip()))

        if ctype in ("SEITIGKEIT",):
            # Normalize quoted tokens like '\'B\'' to B
            token = raw_values.replace("'", "").strip().lower()
            label_key = None
            if token == 'b':
                label_key = 'bilateral'
            elif token == 'e':
                label_key = 'unilateral'
            elif token == 'l':
                label_key = 'left'
            elif token == 'r':
                label_key = 'right'
            display = translate(label_key, lang) if label_key else token.upper()
            op = str(cond.get('vergleich') or '=').strip() or '='
            # Render like "= beidseits" localized
            return html_escape(translate('seitigkeit_condition', lang, value=f"{display}"))

        if ctype in ("LEISTUNGSPOSITIONEN IN LISTE", "LKN", "LKN IN LISTE"):
            codes = [v.strip().upper() for v in raw_values.split(',') if v.strip()]
            parts: list[str] = []
            for code in codes:
                desc = get_lang_field(leistungskatalog_dict.get(code, {}), 'Beschreibung', lang) or code
                parts.append(create_html_info_link(code, 'lkn', html_escape(f"{code} ({desc})")))
            return translate('condition_text_lkn_list', lang, linked_codes=", ".join(parts)) if parts else f"<i>{html_escape(translate('no_lkns_spec', lang))}</i>"

        if ctype in ("LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE", "LKN IN TABELLE"):
            tokens = [v.strip() for v in raw_values.split(',') if v.strip()]
            if len(tokens) == 1 and tokens[0].upper() in ("ODER", "OR", "UND", "AND"):
                table_names = tokens  # Treat as literal table name (e.g., "OR")
            else:
                table_names = [t for t in tokens if t.upper() not in ("ODER", "OR", "UND", "AND")]
            parts: list[str] = []
            for tn in table_names:
                entries = get_table_content(tn, 'service_catalog', tabellen_dict_by_table, lang)
                parts.append(create_html_info_link(tn, 'lkn_table', html_escape(tn), data_content=json.dumps(entries)))
            if parts:
                return translate('condition_text_lkn_table', lang, table_names=", ".join(parts))
            return ""

        if ctype in ("HAUPTDIAGNOSE IN TABELLE", "ICD IN TABELLE"):
            tokens = [v.strip() for v in raw_values.split(',') if v.strip()]
            if len(tokens) == 1 and tokens[0].upper() in ("ODER", "OR", "UND", "AND"):
                table_names = tokens
            else:
                table_names = [t for t in tokens if t.upper() not in ("ODER", "OR", "UND", "AND")]
            parts: list[str] = []
            for tn in table_names:
                entries = get_table_content(tn, 'icd', tabellen_dict_by_table, lang)
                parts.append(create_html_info_link(tn, 'icd_table', html_escape(tn), data_content=json.dumps(entries)))
            if parts:
                return translate('condition_text_icd_table', lang, table_names=", ".join(parts))
            return ""

        if ctype in ("ICD", "HAUPTDIAGNOSE IN LISTE", "ICD IN LISTE"):
            codes = [v.strip().upper() for v in raw_values.split(',') if v.strip()]
            parts: list[str] = []
            for code in codes:
                # Use a diagnosis link; frontend knows how to render it
                link = f'<a href="#" class="info-link" data-type="diagnosis" data-code="{html_escape(code)}">{html_escape(code)}</a>'
                parts.append(link)
            return ", ".join(parts) if parts else f"<i>{html_escape(translate('no_icds_spec', lang))}</i>"

        if ctype in ("MEDIKAMENTE IN LISTE",):
            codes = [v.strip().upper() for v in raw_values.split(',') if v.strip()]
            parts: list[str] = []
            for code in codes:
                display_text = html_escape(code)
                parts.append(create_html_info_link(code, 'medication', display_text))
            return translate('condition_text_medication_list', lang, linked_codes=", ".join(parts)) if parts else f"<i>{html_escape(translate('no_medications_spec', lang))}</i>"

        # Fallback: show the value as plain text
        return html_escape(raw_values)
    except Exception as _:
        return html_escape(raw_values)


def render_pauschale_explanation_html(selected: dict[str, Any] | None,
                                      evaluated: list[dict[str, Any]] | None,
                                      lang: str = 'de') -> str:
    """Render a compact explanation list for evaluated Pauschalen.

    - Shows a bullet list of all evaluated candidates with status
    - If a selection is given, adds a short header line
    """
    try:
        html_parts: list[str] = []
        if selected and selected.get('details'):
            sel_code = str(selected.get('code') or selected.get('details', {}).get('Pauschale') or '')
            sel_text = get_lang_field(selected.get('details', {}), 'Pauschale_Text', lang) or ''
            if sel_code:
                sel_code_disp = html_escape(sel_code)
                sel_link = (
                    f"<a href='#' class='pauschale-exp-link info-link tag-code' "
                    f"data-code='{sel_code_disp}'>{sel_code_disp}</a>"
                )
                html_parts.append(
                    f"<p><b>{sel_link}</b> {html_escape(sel_text)}</p>"
                )
        if evaluated:
            html_parts.append("<ul>")
            for cand in evaluated:
                code = str(cand.get('code') or '')
                details = cand.get('details') or {}
                text = get_lang_field(details, 'Pauschale_Text', lang) or ''
                valid = bool(cand.get('is_valid_structured'))
                status = translate('conditions_met' if valid else 'conditions_not_met', lang)
                status_class = "condition-status condition-status-positive" if valid else "condition-status condition-status-negative"
                status_html = f"<span class=\"{status_class}\">{html_escape(status)}</span>"
                code_disp = html_escape(code)
                link = (
                    f"<a href='#' class='pauschale-exp-link info-link tag-code' "
                    f"data-code='{code_disp}'>{code_disp}</a>"
                )
                html_parts.append(
                    f"<li><b>{link}</b> {html_escape(text)} {status_html}</li>"
                )
            html_parts.append("</ul>")
        return "".join(html_parts) if html_parts else ""
    except Exception as _exc:
        try:
            logger.error("render_pauschale_explanation_html failed: %s", _exc)
        except Exception:
            pass
        return ""

USE_RAG = config.getint('RAG', 'enabled', fallback=0) == 1
APP_VERSION = config.get('APP', 'version', fallback='unknown')
TARIF_VERSION = config.get('APP', 'tarif_version', fallback='')
BRICK_QUIZ_ENABLED = config.getint('FEATURES', 'brick_quiz_enabled', fallback=1) == 1
# Base data directory
DATA_DIR = Path("data")
BRICK_QUIZ_STATIC_DIR = Path(__file__).with_name("brick_quiz")
# Rendering feature flag: prefer server-side rendering for conditions HTML from structured data
try:
    RENDER_SERVER_SIDE_CONDITIONS = config.getint('RENDER', 'server_side_conditions', fallback=0) == 1
except Exception:
    RENDER_SERVER_SIDE_CONDITIONS = False
# Configure synonym support
SYNONYMS_ENABLED = config.getint('SYNONYMS', 'enabled', fallback=0) == 1

# Determine path to the synonym catalogue. Prefer explicit catalog_path for
# backwards compatibility, otherwise build the path from the configured
# filename inside DATA_DIR.
if config.has_option('SYNONYMS', 'catalog_path'):
    SYNONYMS_CATALOG_PATH = Path(config.get('SYNONYMS', 'catalog_path'))
else:
    _fname = config.get('SYNONYMS', 'catalog_filename', fallback='synonyms.json')
    SYNONYMS_CATALOG_PATH = DATA_DIR / _fname
set_synonyms_enabled(SYNONYMS_ENABLED)

# Load synonym catalog if enabled
synonym_catalog: SynonymCatalog = SynonymCatalog()
if SYNONYMS_ENABLED and SYNONYMS_CATALOG_PATH:
    try:
        synonym_catalog = storage.load_synonyms(SYNONYMS_CATALOG_PATH)
        logger.info(
            " ✓ Synonymkatalog geladen (%s Einträge).",
            len(synonym_catalog.entries),
        )
    except Exception as exc:  # pragma: no cover - optional file
        logger.error("Failed to load synonym catalog: %s", exc)
        synonym_catalog = SynonymCatalog()

# ... (andere Imports)
FAISS_INDEX_FILE = DATA_DIR / "vektor_index.faiss"
FAISS_CODES_FILE = DATA_DIR / "vektor_index_codes.json"
EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

try:  # optional dependency
    from sentence_transformers import SentenceTransformer
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    SentenceTransformer = None  # type: ignore
try:
    import faiss
except ModuleNotFoundError:
    faiss = None

embedding_model = None
faiss_index = None
embedding_codes: List[str] = []
if USE_RAG and SentenceTransformer and faiss:
    try:
        faiss_index = faiss.read_index(str(FAISS_INDEX_FILE))
        with FAISS_CODES_FILE.open("r", encoding="utf-8") as f:
            embedding_codes = json.load(f)
        embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        logger.info(" ✓ FAISS index, embedding model and codes geladen.")
    except Exception as e:  # pragma: no cover - ignore on missing file
        logger.warning(f"Konnte FAISS-Index oder Embeddings nicht laden: {e}")

LEISTUNGSKATALOG_PATH = DATA_DIR / "LKAAT_Leistungskatalog.json"
TARDOC_TARIF_PATH = DATA_DIR / "TARDOC_Tarifpositionen.json"
TARDOC_INTERP_PATH = DATA_DIR / "TARDOC_Interpretationen.json"
PAUSCHALE_LP_PATH = DATA_DIR / "PAUSCHALEN_Leistungspositionen.json"
PAUSCHALEN_PATH = DATA_DIR / "PAUSCHALEN_Pauschalen.json"
PAUSCHALE_BED_PATH = DATA_DIR / "PAUSCHALEN_Bedingungen.json"
TABELLEN_PATH = DATA_DIR / "PAUSCHALEN_Tabellen.json"
BASELINE_RESULTS_PATH = DATA_DIR / "baseline_results.json"
BEISPIELE_PATH = DATA_DIR / "beispiele.json"
CHOP_PATH = DATA_DIR / "CHOP_Katalog.json"

# OpenAI-kompatible API-Settings (Apertus, OpenAI, Ollama-OAI)
try:
    OPENAI_TIMEOUT = config.getint('OPENAI', 'timeout', fallback=120)
except Exception:
    OPENAI_TIMEOUT = 120
try:
    OPENAI_MAX_OUTPUT_TOKENS = config.getint('OPENAI', 'max_output_tokens', fallback=800)
except Exception:
    OPENAI_MAX_OUTPUT_TOKENS = 2000
try:
    OPENAI_MAX_OUTPUT_TOKENS_APERTUS = config.getint('OPENAI', 'max_output_tokens_apertus', fallback=OPENAI_MAX_OUTPUT_TOKENS)
except Exception:
    OPENAI_MAX_OUTPUT_TOKENS_APERTUS = OPENAI_MAX_OUTPUT_TOKENS

# Anzahl Wiederholungsversuche bei Serverfehlern (HTTP 5xx) für OpenAI-kompatible Aufrufe
try:
    OPENAI_SERVER_ERROR_MAX_RETRIES = max(0, config.getint('OPENAI', 'server_error_max_retries', fallback=1))
except Exception:
    OPENAI_SERVER_ERROR_MAX_RETRIES = 1
try:
    OPENAI_SERVER_ERROR_RETRY_DELAY_SECONDS = max(0.0, config.getfloat('OPENAI', 'server_error_retry_delay_seconds', fallback=1.0))
except Exception:
    OPENAI_SERVER_ERROR_RETRY_DELAY_SECONDS = 1.0

# Kontext-Steuerung zur Reduktion des Eingabekontextes
CONTEXT_INCLUDE_MED_INTERPRETATION = config.getint('CONTEXT', 'include_med_interpretation', fallback=1) == 1
CONTEXT_INCLUDE_TYP = config.getint('CONTEXT', 'include_typ', fallback=1) == 1
CONTEXT_INCLUDE_BESCHREIBUNG = config.getint('CONTEXT', 'include_beschreibung', fallback=1) == 1
try:
    CONTEXT_MAX_ITEMS = max(0, config.getint('CONTEXT', 'max_context_items', fallback=0))
except Exception:
    CONTEXT_MAX_ITEMS = 0
_force_codes_raw = config.get('CONTEXT', 'force_include_codes', fallback='')
CONTEXT_FORCE_INCLUDE_CODES: List[str] = [c.strip().upper() for c in _force_codes_raw.split(',') if c.strip()] if _force_codes_raw else []

# Retry configuration for Gemini API calls
# Bei HTTP 429 (Rate Limit) wird nach dem Exponential-Backoff-Schema erneut
# versucht. Die Wartezeit berechnet sich als GEMINI_BACKOFF_SECONDS * (2**Versuch).
try:
    GEMINI_MAX_RETRIES = max(1, config.getint('GEMINI', 'server_error_max_retries', fallback=3))
except Exception:
    GEMINI_MAX_RETRIES = 3
try:
    GEMINI_BACKOFF_SECONDS = max(0.0, config.getfloat('GEMINI', 'server_error_backoff_seconds', fallback=1.0))
except Exception:
    GEMINI_BACKOFF_SECONDS = 1.0
# Einheitlicher Timeout für Gemini-API-Aufrufe (in Sekunden)
GEMINI_TIMEOUT = 120

# --- Typ-Aliase für Klarheit ---
# Optionales Prompt-Trimmen für Gemini konfigurierbar machen
try:
    GEMINI_TRIM_ENABLED = config.getint('GEMINI', 'trim_enabled', fallback=0) == 1
except Exception:
    GEMINI_TRIM_ENABLED = False
try:
    GEMINI_TOKEN_BUDGET = config.getint('GEMINI', 'token_budget', fallback=8000)
except Exception:
    GEMINI_TOKEN_BUDGET = 8000
try:
    GEMINI_TRIM_MIN_CONTEXT_CHARS = config.getint('GEMINI', 'trim_min_context_chars', fallback=1000)
except Exception:
    GEMINI_TRIM_MIN_CONTEXT_CHARS = 1000

# --- Stage-1 Kontextaufbau: Feintuning-Konstanten ---
# Anzahl alternativer Query-Varianten (z.B. Synonyme), die wir bei der Kontexterstellung berücksichtigen.
MAX_QUERY_VARIANTS = 80
# Höchstzahl zusätzlicher Tokens, die Varianten pro Suchlauf beitragen dürfen (begrenzt Streuung).
MAX_TOKEN_VARIANT_ADDITIONS = 24
# Maximale Zeichenlänge einzelner Variantenbeschreibungen, um ausufernde Texte zu vermeiden.
MAX_VARIANT_LENGTH = 120
# Mindestanzahl an Keyword-basierten Treffern, bevor Zusatzvarianten gesucht werden.
MIN_KEYWORD_RESULTS = 40
# Zielgröße für eindeutig gerankte LKN-Kodes im Kontextblock.
MIN_RANKED_CODE_TARGET = 80
# Wie viele Varianten wir bei Bedarf für zusätzliche Suchläufe heranziehen.
EXTRA_VARIANT_SEARCH_LIMIT = 6
# Maximale Anzahl Katalogtreffer, die pro Zusatzvariante übernommen werden.
EXTRA_VARIANT_RESULT_LIMIT = 40
# Untere Token-Schwelle des Kontextblocks; fällt der Wert darunter, hängen wir medizinische Interpretationen an.
MIN_CONTEXT_TOKEN_THRESHOLD = 6000
# Maximalzahl an Fallback-Zeilen mit medizinischer Interpretation, die ergänzt werden dürfen.
MAX_FALLBACK_MED_LINES = 40
# Anzahl Seed-Ergebnisse aus der initialen Keyword-Suche für Variantenbildung.
SEED_KEYWORD_RESULT_LIMIT = 10
# Anzahl Top-Keyword-Treffer, die bevorzugt (mit Score) in die Rangliste eingehen.
KEYWORD_PRIORITY_LIMIT = 3
# Wie viele Katalogbeschreibungen als zusätzliche Variantenformulierungen genutzt werden.
KEYWORD_VARIANT_DESCRIPTION_LIMIT = 3
# Zahl direkter Synonym-Kodes, die wir als Rangierhinweise einschieben.
MAX_DIRECT_SYNONYM_RANK_HINTS = 4
# Limit für explizit in den Prompt aufgenommenen Synonymbezeichnungen.
MAX_PROMPT_SYNONYMS = 12

EvaluateStructuredConditionsType = Callable[[str, Dict[Any, Any], List[Dict[Any, Any]], Dict[str, List[Dict[Any, Any]]]], bool]
CheckPauschaleConditionsType = Callable[
    [
        str,
        Dict[Any, Any],
        List[Dict[Any, Any]],
        Dict[str, List[Dict[Any, Any]]],
        Dict[str, Dict[str, Any]],
        str,
        Optional[Dict[str, Dict[str, Any]]],
        Optional[Dict[str, Any]],
        bool,
    ],
    Dict[str, Any]
]
GetSimplifiedConditionsType = Callable[[str, List[Dict[Any, Any]]], Set[Any]]
GenerateConditionDetailHtmlType = Callable[
    [Tuple[Any, ...], Dict[Any, Any], Dict[Any, Any], str],
    str,
]
class DetermineApplicablePauschaleType(Protocol):
    def __call__(
        self,
        user_input: str,
        rule_checked_leistungen: List[Dict[str, Any]],
        context: Mapping[str, Any],
        pauschale_lp_data: List[Dict[str, Any]],
        pauschale_bedingungen_data: List[Dict[str, Any]],
        pauschalen_dict: Dict[str, Dict[str, Any]],
        leistungskatalog_dict: Dict[str, Dict[str, Any]],
        tabellen_dict_by_table: Dict[str, List[Dict[str, Any]]],
        pauschale_lp_index: Mapping[str, Set[str]],
        pauschale_cond_lkn_index: Mapping[str, Set[str]],
        pauschale_cond_table_index: Mapping[str, Set[str]],
        lkn_to_tables_index: Mapping[str, List[str]],
        potential_pauschale_codes_set: Optional[Set[str]] = ...,
        lang: str = ...,
        prepared_structures: Optional[Dict[str, Any]] = ...,
    ) -> Dict[str, Any]:
        """Signatur für Pauschalen-Auswahlfunktionen."""
        ...
PrepareTardocAbrechnungType = Callable[[List[Dict[Any,Any]], Dict[str, Dict[Any,Any]], str], Dict[str,Any]]

# --- Standard-Fallbacks für Funktionen aus regelpruefer_pauschale ---
def default_evaluate_fallback( # Matches: evaluate_structured_conditions(pauschale_code: str, context: Dict, pauschale_bedingungen_data: List[Dict], tabellen_dict_by_table: Dict[str, List[Dict]]) -> bool
    pauschale_code: str,
    context: Dict[Any, Any],
    pauschale_bedingungen_data: List[Dict[Any, Any]],
    tabellen_dict_by_table: Dict[str, List[Dict[Any, Any]]]
) -> bool:
    """Fallback, falls der Pauschalen-Regelprüfer nicht geladen werden konnte."""
    logger.warning("Fallback für 'evaluate_structured_conditions' aktiv.")
    return False

def default_check_html_fallback(
    pauschale_code: str,
    context: Dict[Any, Any],
    pauschale_bedingungen_data: List[Dict[Any, Any]],
    tabellen_dict_by_table: Dict[str, List[Dict[Any, Any]]],
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    lang: str = "de",
    pauschalen_dict: Optional[Dict[str, Dict[str, Any]]] = None,
    prepared_structures: Optional[Dict[str, Any]] = None,
    tolerant: bool = False,
) -> Dict[str, Any]:
    """Fallback für HTML-Detailprüfung, falls Modulimport fehlschlägt."""
    logger.warning("Fallback für 'check_pauschale_conditions' aktiv.")
    message = translate('detail_html_not_generated', lang)
    return {
        "html": f"<p><i>{html_escape(message)}</i></p>",
        "errors": ["Fallback aktiv"],
        "trigger_lkn_condition_met": False,
        "prueflogik_expr": None,
        "prueflogik_pretty": "",
    }

def default_get_simplified_conditions_fallback( # Matches: get_simplified_conditions(pauschale_code: str, bedingungen_data: list[dict]) -> set
    pauschale_code: str,
    bedingungen_data: List[Dict[Any, Any]]
) -> Set[Any]:
    """Fallback für vereinfachte Bedingungsliste, wenn Regelprüfer fehlt."""
    logger.warning("Fallback für 'get_simplified_conditions' aktiv.")
    return set()

def default_generate_condition_detail_html_fallback(
    condition_tuple: Tuple[Any, ...],
    leistungskatalog_dict: Dict[Any, Any],
    tabellen_dict_by_table: Dict[Any, Any],
    lang: str = 'de',
) -> str:
    """Fallback für Detail-HTML einer Bedingung, wenn Generator fehlt."""
    logger.warning("Fallback für 'generate_condition_detail_html' aktiv.")
    return "<li>Detail-Generierung fehlgeschlagen (Fallback)</li>"

def default_determine_applicable_pauschale_fallback(
    user_input: str,
    rule_checked_leistungen: List[Dict[str, Any]],
    context: Mapping[str, Any],
    pauschale_lp_data: List[Dict[str, Any]],
    pauschale_bedingungen_data: List[Dict[str, Any]],
    pauschalen_dict: Dict[str, Dict[str, Any]],
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    tabellen_dict_by_table: Dict[str, List[Dict[str, Any]]],
    pauschale_lp_index: Mapping[str, Set[str]],
    pauschale_cond_lkn_index: Mapping[str, Set[str]],
    pauschale_cond_table_index: Mapping[str, Set[str]],
    lkn_to_tables_index: Mapping[str, List[str]],
    potential_pauschale_codes_set: Optional[Set[str]] = None,
    lang: str = 'de',
    prepared_structures: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fallback für Hauptprüfung der Pauschalen-Logik."""
    logger.warning("Fallback für 'determine_applicable_pauschale' aktiv.")
    return {"type": "Error", "message": "Pauschalen-Hauptprüfung nicht verfügbar (Fallback)"}

def prepare_tardoc_abrechnung_fallback(
    regel_ergebnisse_details_list: List[Dict[Any, Any]],
    leistungskatalog_dict_arg: Dict[str, Dict[Any, Any]],
    lang: str = "de",
) -> Dict[str, Any]:
    """Fallback für prepare_tardoc_abrechnung, falls Regelprüfer-Modul fehlt."""
    logger.warning("Fallback für 'prepare_tardoc_abrechnung' aktiv.")
    return {"type": "Error", "message": "TARDOC-Abrechnungsaufbereitung nicht verfügbar (Fallback)"}

# --- Initialisiere Funktionsvariablen mit Fallbacks ---
evaluate_structured_conditions: EvaluateStructuredConditionsType = default_evaluate_fallback
check_pauschale_conditions: CheckPauschaleConditionsType = default_check_html_fallback
get_simplified_conditions: GetSimplifiedConditionsType = default_get_simplified_conditions_fallback
generate_condition_detail_html: GenerateConditionDetailHtmlType = default_generate_condition_detail_html_fallback
determine_applicable_pauschale_func: DetermineApplicablePauschaleType = default_determine_applicable_pauschale_fallback
prepare_tardoc_abrechnung_func: PrepareTardocAbrechnungType = prepare_tardoc_abrechnung_fallback

# --- Importiere Regelprüfer-Module und überschreibe Fallbacks bei Erfolg ---
try:
    # Für regelpruefer_einzelleistungen.py (LKN-Regeln)
    rp_lkn_module = None
    import regelpruefer_einzelleistungen as rp_lkn_module
    logger.info("✓ Regelprüfer LKN (regelpruefer_einzelleistungen.py) Modul geladen.")
    if hasattr(rp_lkn_module, 'prepare_tardoc_abrechnung'):
        prepare_tardoc_abrechnung_func = rp_lkn_module.prepare_tardoc_abrechnung
        logger.debug("DEBUG: 'prepare_tardoc_abrechnung' aus regelpruefer_einzelleistungen.py zugewiesen.")
    else:
        logger.error("FEHLER: 'prepare_tardoc_abrechnung' NICHT in regelpruefer_einzelleistungen.py gefunden! Verwende Fallback.")
        def prepare_tardoc_lkn_fb(r: List[Dict[Any,Any]], l: Dict[str, Dict[Any,Any]], lang_param: str = 'de') -> Dict[str,Any]:
            """Fallback für prepare_tardoc_abrechnung, falls Funktion fehlt."""
            return {"type":"Error", "message":"TARDOC Prep Fallback (LKN Funktion fehlt)"}
        prepare_tardoc_abrechnung_func = prepare_tardoc_lkn_fb
except ImportError:
    logger.error("FEHLER: regelpruefer_einzelleistungen.py nicht gefunden! Verwende Fallbacks für LKN-Regelprüfung.")
    def prepare_tardoc_lkn_import_fb(r: List[Dict[Any,Any]], l: Dict[str, Dict[Any,Any]], lang_param: str = 'de') -> Dict[str,Any]:
        """Fallback für prepare_tardoc_abrechnung bei Importfehlern."""
        return {"type":"Error", "message":"TARDOC Prep Fallback (LKN Modulimportfehler)"}
    prepare_tardoc_abrechnung_func = prepare_tardoc_lkn_import_fb

try:
    # Für regelpruefer_pauschale.py
    logger.info("INFO: Versuche, regelpruefer_pauschale.py zu importieren...")
    import regelpruefer_pauschale as rpp_module
    logger.debug("DEBUG: Importversuch abgeschlossen. rpp_module ist: %s", rpp_module)
    logger.debug("DEBUG: Inhalt von rpp_module: %s", dir(rpp_module))
    logger.info("✓ Regelprüfer Pauschalen (regelpruefer_pauschale.py) Modul geladen.")

    # if rpp_module and hasattr(rpp_module, 'evaluate_structured_conditions'):
    #    evaluate_structured_conditions = rpp_module.evaluate_structured_conditions
    # else:
    #    logger.error("FEHLER: 'evaluate_structured_conditions' nicht in regelpruefer_pauschale.py (oder Modul nicht geladen)! Fallback aktiv.")

    if rpp_module and hasattr(rpp_module, 'check_pauschale_conditions'):
        check_pauschale_conditions = rpp_module.check_pauschale_conditions  # type: ignore[attr-defined]
    else:
        logger.error(
            "FEHLER: 'check_pauschale_conditions' nicht in regelpruefer_pauschale.py (oder Modul nicht geladen)! Fallback aktiv."
        )

    if rpp_module and hasattr(rpp_module, 'get_simplified_conditions'):
        get_simplified_conditions = rpp_module.get_simplified_conditions  # type: ignore[attr-defined]
    else:
        logger.error(
            "FEHLER: 'get_simplified_conditions' nicht in regelpruefer_pauschale.py (oder Modul nicht geladen)! Fallback aktiv."
        )

    if rpp_module and hasattr(rpp_module, 'generate_condition_detail_html'):
        generate_condition_detail_html = rpp_module.generate_condition_detail_html  # type: ignore[attr-defined]
    else:
        logger.error(
            "FEHLER: 'generate_condition_detail_html' nicht in regelpruefer_pauschale.py (oder Modul nicht geladen)! Fallback aktiv."
        )

    if rpp_module and hasattr(rpp_module, 'determine_applicable_pauschale'):
        determine_applicable_pauschale_func = rpp_module.determine_applicable_pauschale  # type: ignore[attr-defined]
        logger.debug("DEBUG: 'determine_applicable_pauschale' aus regelpruefer_pauschale.py zugewiesen.")
    else:
        logger.error(
            "FEHLER: 'determine_applicable_pauschale' nicht in regelpruefer_pauschale.py (oder Modul nicht geladen)! Fallback aktiv."
        )

except ImportError as e_imp:
    logger.error(
        "FEHLER (ImportError): regelpruefer_pauschale.py konnte nicht importiert werden: %s! Standard-Fallbacks bleiben aktiv.",
        e_imp,
    )
    traceback.print_exc()
except Exception as e_gen: # Fängt auch andere Fehler während des Imports
    logger.error(
        "FEHLER (Allgemein beim Import): Ein Fehler trat beim Laden von regelpruefer_pauschale.py auf: %s! Standard-Fallbacks bleiben aktiv.",
        e_gen,
    )
    traceback.print_exc()

# --- Globale Datencontainer ---
leistungskatalog_data: list[dict] = []
leistungskatalog_dict: dict[str, dict] = {}
regelwerk_dict: dict[str, list] = {} # Annahme: lade_regelwerk gibt List[RegelDict] pro LKN
tardoc_tarif_dict: dict[str, dict] = {}
tardoc_interp_dict: dict[str, dict] = {}
tardoc_demographic_cache: dict[str, Dict[str, Any]] = {}
pauschale_lp_data: list[dict] = []
pauschale_lp_index: DefaultDict[str, Set[str]] = defaultdict(set)  # Pauschale -> LKNs (LP-Zuordnung)
pauschale_lp_index_by_lkn: DefaultDict[str, Set[str]] = defaultdict(set)  # LKN -> Pauschalen (abgeleitet)
pauschalen_data: list[dict] = []
pauschalen_dict: dict[str, dict] = {}
pauschale_bedingungen_data: list[dict] = []
pauschale_cond_lkn_index: DefaultDict[str, Set[str]] = defaultdict(set)  # Pauschale -> LKN-Bedingungen
pauschale_cond_lkn_index_by_lkn: DefaultDict[str, Set[str]] = defaultdict(set)  # LKN -> Pauschalen (Bedingungen)
pauschale_cond_table_index: DefaultDict[str, Set[str]] = defaultdict(set)  # Pauschale -> Tabellen-Bedingungen
pauschale_cond_table_index_by_table: DefaultDict[str, Set[str]] = defaultdict(set)  # Tabelle -> Pauschalen
tabellen_data: list[dict] = []
tabellen_dict_by_table: dict[str, list[dict]] = {}
medication_entries: list[dict[str, Any]] = []
medication_lookup_by_token: dict[str, Set[str]] = {}
pauschale_bedingungen_indexed: Dict[str, List[Dict[str, Any]]] = {}
daten_geladen: bool = False
baseline_results: dict[str, dict] = {}
examples_data: list[dict] = []
token_doc_freq: dict[str, int] = {}
chop_data: list[dict] = []
full_catalog_token_count: int = 0
catalog_description_lookup: Set[str] = set()
prepared_structures: Dict[str, Any] = {}

def create_app() -> FlaskType:
    """
    Erstellt die Flask-Instanz.  
    Render (bzw. Gunicorn) ruft diese Factory einmal pro Worker auf
    und bekommt das WSGI-Objekt zurück.
    """
    if USING_FLASK_STUB and not os.getenv("ALLOW_FLASK_STUBS"):
        raise RuntimeError("Flask ist nicht installiert. Bitte 'pip install flask flask-compress' ausführen oder ALLOW_FLASK_STUBS=1 setzen (nur für Tests).")
    app = FlaskType(__name__, static_folder='.', static_url_path='')
    # Stelle sicher, dass alle JSON-Antworten UTF-8 liefern und nicht auf ASCII
    # zurückfallen. Ohne dieses Flag werden Umlaute in Kombination mit bestimmten
    # Browsern als "Prüflogik" dargestellt.
    app.config.update(
        JSON_AS_ASCII=False,
        JSONIFY_MIMETYPE="application/json; charset=utf-8",
    )

    @app.before_request
    def _activate_table_cache_per_request() -> None:
        """Aktiviert den Tabellencache pro Request und merkt sich das Token im Environ."""
        token = activate_table_content_cache()
        if token is not None:
            environ = getattr(request, "environ", None)
            if isinstance(environ, dict):
                environ['_table_cache_token'] = token
            else:
                request.environ = {'_table_cache_token': token}  # type: ignore[attr-defined]

    @app.teardown_request
    def _cleanup_table_cache_per_request(_exc: Optional[BaseException]) -> None:
        """Deaktiviert den Tabellencache nach jedem Request, falls Token gesetzt."""
        environ = getattr(request, "environ", None)
        token = None
        if isinstance(environ, dict):
            token = environ.pop('_table_cache_token', None)
        deactivate_table_content_cache(token)

    # Daten nur einmal laden – egal ob lokal oder Render-Worker
    global daten_geladen
    if not daten_geladen:
        logger.info("Initialer Daten-Load beim App-Start …")
        if not load_data():
            raise RuntimeError("Kritische Daten konnten nicht geladen werden.")

    if SYNONYMS_ENABLED:
        try:
            from synonyms.api import bp as synonyms_bp
            app.register_blueprint(cast(FlaskBlueprint, synonyms_bp))
        except Exception as exc:
            logger.error("Failed to register synonyms API: %s", exc)

    @app.after_request
    def _ensure_utf8_charset(response):
        """Stelle sicher, dass textbasierte Antworten explizit UTF-8 senden."""
        content_type = response.headers.get("Content-Type")
        if content_type:
            lowered = content_type.lower()
            needs_charset = "charset=" not in lowered and (
                lowered.startswith("text/")
                or lowered.startswith("application/json")
                or lowered.startswith("application/javascript")
            )
            if needs_charset:
                response.headers["Content-Type"] = f"{content_type}; charset=utf-8"
        return response

    # Ab hier bleiben alle @app.route-Dekorationen unverändert
    # Initialize Flask-Compress
    if Compress:
        try:
            Compress(app)
        except Exception as e:
            logger.warning(f"Could not initialize Flask-Compress: {e}")
    else:
        logger.info("Flask-Compress module not found; compression disabled.")

    return app

MEDICATION_KEY_CLEAN_RE = re.compile(r'[^0-9A-Z]+')


def _normalize_medication_key(value: str) -> str:
    """Return an uppercase, whitespace-normalized token for medication matching."""
    if not isinstance(value, str):
        value = str(value or '')
    normalized = MEDICATION_KEY_CLEAN_RE.sub(' ', value.upper())
    normalized = re.sub(r"\s+", ' ', normalized).strip()
    return normalized


def _build_medication_lookup(tabellen_rows: List[Dict[str, Any]]) -> None:
    """Prepare lookup structures for medication resolution using ATC codes."""
    medication_entries.clear()
    medication_lookup_by_token.clear()
    if not tabellen_rows:
        return
    for item in tabellen_rows:
        if not isinstance(item, dict):
            continue
        tab_typ = str(item.get('Tabelle_Typ', '')).strip()
        if tab_typ != '402':
            continue
        atc = str(item.get('Tabelle', '')).strip().upper()
        if not atc:
            continue
        code = str(item.get('Code', '')).strip()
        name = str(item.get('Code_Text', '')).strip()
        entry_normalized_name = _normalize_medication_key(name) if name else ''
        medication_entries.append({
            'atc': atc,
            'code': code,
            'code_upper': code.upper() if code else '',
            'name': name,
            'name_normalized': entry_normalized_name,
        })
        tokens = {atc}
        if code:
            tokens.add(code.upper())
            tokens.add(_normalize_medication_key(code))
        if name:
            tokens.add(name.upper())
            tokens.add(entry_normalized_name)
        for token in {t for t in tokens if t}:
            medication_lookup_by_token.setdefault(token, set()).add(atc)


def resolve_medication_inputs(raw_inputs: List[str]) -> tuple[List[str], List[str]]:
    """Resolve user provided medication tokens (GTIN, name, ATC) into ATC codes."""
    resolved: Set[str] = set()
    unresolved: List[str] = []
    for raw in raw_inputs:
        token = str(raw).strip() if raw is not None else ''
        if not token:
            continue
        token_upper = token.upper()
        token_normalized = _normalize_medication_key(token)
        candidate_atcs: Set[str] = set()
        for key in {token_upper, token_normalized}:
            if key and key in medication_lookup_by_token:
                candidate_atcs.update(medication_lookup_by_token[key])
        if not candidate_atcs and token_normalized:
            for entry in medication_entries:
                name_norm = entry.get('name_normalized')
                if name_norm and token_normalized in name_norm:
                    candidate_atcs.add(entry['atc'])
        if candidate_atcs:
            resolved.update(candidate_atcs)
        else:
            unresolved.append(token)
    return sorted(resolved), unresolved


_QUANTITY_TIME_UNITS_RE = re.compile(
    r"\b(min|minute|minuten|minuti|minutes|minutos|heures|heure|ore|ora|stunden|stunde|std|h)\b",
    re.IGNORECASE,
)
_QUANTITY_WORD_MAP = {
    # German
    "eins": 1, "eine": 1, "einen": 1, "ein": 1, "zwei": 2, "drei": 3, "vier": 4, "fuenf": 5, "fünf": 5,
    # French
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    # Italian
    "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
}
_QUANTITY_VAGUE_WORDS = {
    "mehrere", "verschiedene", "einige", "paar", "plusieurs", "divers", "quelques", "alcuni", "diversi", "parecchi", "qualche"
}
def _extract_quantity_hint(text: str) -> Optional[int]:
    """Heuristisch Mengenhinweise aus Freitext ziehen (mehrsprachig, ohne Zeitangaben)."""
    if not isinstance(text, str):
        return None
    cleaned = text
    for code in extract_lkn_codes_from_text(text):
        cleaned = cleaned.replace(code, " ")
    lowered = cleaned.lower()
    # Explizite Ziffern (ohne Minuten/Stunden-Bezug)
    for match in re.finditer(r"\b(\d{1,2})\b", lowered):
        value = int(match.group(1))
        window = lowered[max(0, match.start() - 12): match.end() + 12]
        if _QUANTITY_TIME_UNITS_RE.search(window):
            continue
        if value > 0:
            return value
    # Zahlwörter
    for word, value in _QUANTITY_WORD_MAP.items():
        pattern = rf"\b{re.escape(word)}\b"
        for match in re.finditer(pattern, lowered):
            window = lowered[max(0, match.start() - 12): match.end() + 12]
            if _QUANTITY_TIME_UNITS_RE.search(window):
                continue
            return value
    # Vage Pluralhinweise -> mind. 2
    for word in _QUANTITY_VAGUE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return 2
    return None


# --- Daten laden Hilfsfunktionen ---
def _reset_data_containers() -> None:
    leistungskatalog_data.clear(); leistungskatalog_dict.clear(); regelwerk_dict.clear(); tardoc_tarif_dict.clear(); tardoc_interp_dict.clear()
    pauschale_lp_data.clear(); pauschalen_data.clear(); pauschalen_dict.clear(); pauschale_bedingungen_data.clear(); pauschale_bedingungen_indexed.clear(); tabellen_data.clear()
    tabellen_dict_by_table.clear()
    lkn_to_tables_index.clear()
    pauschale_lp_index.clear()
    pauschale_lp_index_by_lkn.clear()
    pauschale_cond_lkn_index.clear()
    pauschale_cond_lkn_index_by_lkn.clear()
    pauschale_cond_table_index.clear()
    pauschale_cond_table_index_by_table.clear()
    token_doc_freq.clear()
    chop_data.clear()


def _load_catalogs() -> bool:
    """Lädt Kern-JSONs (Kataloge, Tabellen etc.) und baut Grund-Lookups."""
    all_ok = True
    files_to_load = {
        "Leistungskatalog": (LEISTUNGSKATALOG_PATH, leistungskatalog_data, 'LKN', leistungskatalog_dict),
        "PauschaleLP": (PAUSCHALE_LP_PATH, pauschale_lp_data, None, None),
        "Pauschalen": (PAUSCHALEN_PATH, pauschalen_data, 'Pauschale', pauschalen_dict),
        "PauschaleBedingungen": (PAUSCHALE_BED_PATH, pauschale_bedingungen_data, None, None),
        "TARDOC_TARIF": (TARDOC_TARIF_PATH, [], 'LKN', tardoc_tarif_dict),
        "TARDOC_INTERP": (TARDOC_INTERP_PATH, [], 'LKN', tardoc_interp_dict),
        "Tabellen": (TABELLEN_PATH, tabellen_data, None, None),
        "CHOP": (CHOP_PATH, chop_data, None, None)
    }

    for name, (path, target_list_ref, key_field, target_dict_ref) in files_to_load.items():
        try:
            logger.info("  Versuche %s von %s zu laden...", name, path)
            if path.is_file():
                with open(path, 'r', encoding='utf-8') as f:
                    data_from_file = json.load(f)

                if name == "TARDOC_INTERP" and isinstance(data_from_file, dict):
                    logger.info("  Spezialbehandlung für TARDOC_INTERP: Extrahiere Listen aus dem Wörterbuch.")
                    combined_list = []
                    for key, value in data_from_file.items():
                        if isinstance(value, list):
                            combined_list.extend(value)
                    data_from_file = combined_list
                    logger.info("  Kombinierte Liste für TARDOC_INTERP enthält %d Einträge.", len(data_from_file))

                if isinstance(data_from_file, list):
                     target_list_ref.clear()
                     target_list_ref.extend(data_from_file)
                     
                     if key_field and target_dict_ref is not None:
                         target_dict_ref.clear()
                         for item in data_from_file:
                             if isinstance(item, dict):
                                 key_val = item.get(key_field)
                                 if key_val:
                                     target_dict_ref[str(key_val)] = item
                         logger.info("  ✓ %s-Daten '%s' geladen (%s Einträge in Liste, %s in Dict).", name, path, len(target_list_ref), len(target_dict_ref))
                     elif target_dict_ref is None:
                          logger.info("  ✓ %s-Daten '%s' geladen (%s Einträge in Liste).", name, path, len(target_list_ref))

                if name == "Tabellen":
                    TAB_KEY = "Tabelle"
                    tabellen_dict_by_table.clear()
                    for item in data_from_file:
                        if isinstance(item, dict):
                            table_name = item.get(TAB_KEY)
                            if table_name:
                                normalized_key = str(table_name).lower()
                                if normalized_key not in tabellen_dict_by_table:
                                    tabellen_dict_by_table[normalized_key] = []
                                tabellen_dict_by_table[normalized_key].append(item)
                            
                            code_val = item.get("Code")
                            if code_val and table_name:
                                code_key = str(code_val).strip().upper()
                                table_key = str(table_name).strip().lower()
                                if code_key and table_key and table_key not in lkn_to_tables_index[code_key]:
                                    lkn_to_tables_index[code_key].append(table_key)

                    logger.info("  Tabellen-Daten gruppiert nach Tabelle (%s Tabellen).", len(tabellen_dict_by_table))
                    _build_medication_lookup(data_from_file)
                    logger.info("  Medikamenten-Lookup aufgebaut (%s Eintraege).", len(medication_entries))
                    missing_keys_check = ['cap13', 'cap14', 'or', 'nonor', 'nonelt', 'ambp.pz', 'anast', 'c08.50']
                    not_found_keys_check = {k for k in missing_keys_check if k not in tabellen_dict_by_table}
                    if not_found_keys_check:
                         logger.error("  FEHLER: Kritische Tabellenschlüssel fehlen in tabellen_dict_by_table: %s!", not_found_keys_check)
                         all_ok = False
            else:
                logger.error("  FEHLER: %s-Datei nicht gefunden: %s", name, path)
                if name in ["Leistungskatalog", "Pauschalen", "TARDOC_TARIF", "TARDOC_INTERP", "PauschaleBedingungen", "Tabellen"]:
                    all_ok = False
        except (json.JSONDecodeError, IOError, Exception) as e:
            logger.error("  FEHLER beim Laden/Verarbeiten von %s (%s): %s", name, path, e)
            all_ok = False
            traceback.print_exc()

    try:
        tardoc_demographic_cache.clear()
        for lkn, info in tardoc_tarif_dict.items():
            if not isinstance(info, dict):
                continue
            demo = _extract_tardoc_demographics(info)
            if demo:
                tardoc_demographic_cache[lkn] = demo
        if tardoc_demographic_cache:
            logger.info("  Demografische Metadaten aus TARDOC geladen (%s LKNs).", len(tardoc_demographic_cache))
    except Exception as e:
        logger.warning("  WARNUNG: Konnte demografische Metadaten aus TARDOC nicht extrahieren: %s", e)
        tardoc_demographic_cache.clear()

    return all_ok


def _load_optional_datasets() -> None:
    """Lädt optionale Dateien (Baseline, Beispiele) ohne die Erfolgslage zu beeinflussen."""
    try:
        global baseline_results
        with open(BASELINE_RESULTS_PATH, 'r', encoding='utf-8') as f:
            baseline_results = json.load(f)
        logger.info("  Baseline-Ergebnisse geladen (%s Beispiele.)", len(baseline_results))
    except Exception as e:
        logger.warning("  WARNUNG: Baseline-Resultate konnten nicht geladen werden: %s", e)
        baseline_results = {}
    try:
        global examples_data
        with open(BEISPIELE_PATH, 'r', encoding='utf-8') as f:
            examples_data = json.load(f)
        logger.info("  Beispiel-Daten geladen (%s Einträge.)", len(examples_data))
    except Exception as e:
        logger.warning("  WARNUNG: Beispiel-Daten konnten nicht geladen werden: %s", e)
        examples_data = []


def _load_rules() -> bool:
    """Extrahiert Regelwerke aus geladenen Katalogen."""
    try:
        regelwerk_dict.clear()
        for lkn, info in tardoc_tarif_dict.items():
            rules = info.get("Regeln")
            if rules:
                regelwerk_dict[lkn] = rules
        logger.info("  Regelwerk aus TARDOC geladen (%s LKNs mit Regeln).", len(regelwerk_dict))
        return True
    except Exception as e:
        logger.error("  FEHLER beim Extrahieren des Regelwerks aus TARDOC: %s", e)
        traceback.print_exc()
        regelwerk_dict.clear()
        return False


def _build_indices(all_loaded_successfully: bool) -> bool:
    """Baut Token-, Beschreibung- und Pauschalen-Indizes basierend auf geladenen Daten."""
    try:
        compute_token_doc_freq(leistungskatalog_dict, token_doc_freq)
        logger.info("  Token-Dokumentfrequenzen berechnet (%s Tokens).", len(token_doc_freq))
    except Exception as e:
        logger.error("  FEHLER bei compute_token_doc_freq: %s", e)
        all_loaded_successfully = False

    catalog_description_lookup.clear()
    for details in leistungskatalog_dict.values():
        if not isinstance(details, dict):
            continue
        for field in ("Beschreibung", "Beschreibung_f", "Beschreibung_i"):
            value = details.get(field)
            if not isinstance(value, str):
                continue
            normalized_desc = " ".join(value.split()).lower()
            if normalized_desc:
                catalog_description_lookup.add(normalized_desc)

    global full_catalog_token_count
    if not USE_RAG:
        total_tokens = 0
        for lkn_code, details in leistungskatalog_dict.items():
            desc_texts = []
            for base in ["Beschreibung", "Beschreibung_f", "Beschreibung_i"]:
                val = details.get(base)
                if val:
                    desc_texts.append(str(val))
            mi_texts = []
            for base in [
                "MedizinischeInterpretation",
                "MedizinischeInterpretation_f",
                "MedizinischeInterpretation_i",
            ]:
                val = details.get(base)
                if val:
                    mi_texts.append(str(val))
            mi_joined = " ".join(mi_texts)
            context_line = f"LKN: {lkn_code}, Typ: {details.get('Typ', 'N/A')}, Beschreibung: {desc_texts[0] if desc_texts else 'N/A'}"
            if mi_joined:
                context_line += f", MedizinischeInterpretation: {mi_joined}"
            total_tokens += count_tokens(context_line)
        full_catalog_token_count = total_tokens
        logger.info("  Vollständiger Katalog-Kontext enthält %s Tokens.", full_catalog_token_count)

    if pauschale_bedingungen_data and all_loaded_successfully:
        logger.info("  Beginne Indizierung und Sortierung der Pauschalbedingungen...")
        pauschale_bedingungen_indexed.clear()
        PAUSCHALE_KEY_FOR_INDEX = 'Pauschale'
        GRUPPE_KEY_FOR_SORT = 'Gruppe'
        BEDID_KEY_FOR_SORT = 'BedingungsID'

        temp_construction_dict: Dict[str, List[Dict[str, Any]]] = {}

        for cond_item in pauschale_bedingungen_data:
            pauschale_code_val = cond_item.get(PAUSCHALE_KEY_FOR_INDEX)
            if pauschale_code_val:
                pauschale_code_str = str(pauschale_code_val)
                if pauschale_code_str not in temp_construction_dict:
                    temp_construction_dict[pauschale_code_str] = []
                temp_construction_dict[pauschale_code_str].append(cond_item)
            else:
                logger.warning("  WARNUNG: Pauschalbedingung ohne Pauschalencode gefunden: %s", cond_item.get('BedingungsID', 'ID unbekannt'))

        for pauschale_code_key, conditions_list in temp_construction_dict.items():
            conditions_list.sort(
                key=lambda c: (
                    c.get(GRUPPE_KEY_FOR_SORT, float('inf')),
                    c.get(BEDID_KEY_FOR_SORT, float('inf'))
                )
            )
            pauschale_bedingungen_indexed[pauschale_code_key] = conditions_list

        logger.info("  Pauschalbedingungen indiziert und sortiert (%s Pauschalen mit Bedingungen).", len(pauschale_bedingungen_indexed))
        
        try:
            from regelpruefer_pauschale import build_pauschale_condition_structure_index
            global prepared_structures
            prepared_structures = build_pauschale_condition_structure_index(pauschale_bedingungen_data)
            logger.info("  Pauschalbedingungen-Strukturen vorberechnet (%s Einträge).", len(prepared_structures))
        except Exception as e_prep:
             logger.error("  FEHLER bei der Vorberechnung der Pauschalbedingungen-Strukturen: %s", e_prep)
             traceback.print_exc()

    elif not pauschale_bedingungen_data and all_loaded_successfully:
        logger.warning("  WARNUNG: Keine Pauschalbedingungen zum Indizieren vorhanden (pauschale_bedingungen_data ist leer).")
    elif not all_loaded_successfully:
        logger.warning("  WARNUNG: Überspringe Indizierung der Pauschalbedingungen aufgrund vorheriger Ladefehler.")

    pauschale_lp_index.clear()
    pauschale_lp_index_by_lkn.clear()
    if pauschale_lp_data and pauschalen_dict:
        for entry in pauschale_lp_data:
            lkn_val = entry.get("Leistungsposition")
            pc_val = entry.get("Pauschale")
            if not (lkn_val and pc_val):
                continue
            lkn_key = str(lkn_val).strip().upper()
            pc_key = str(pc_val).strip()
            if lkn_key and pc_key in pauschalen_dict:
                pauschale_lp_index[pc_key].add(lkn_key)
                pauschale_lp_index_by_lkn[lkn_key].add(pc_key)
        logger.info(
            "  Pauschale-LP-Index aufgebaut (%s Pauschalen, %s direkte LKN-Zuordnungen).",
            len(pauschale_lp_index),
            sum(len(v) for v in pauschale_lp_index.values()),
        )

    pauschale_cond_lkn_index.clear()
    pauschale_cond_lkn_index_by_lkn.clear()
    pauschale_cond_table_index.clear()
    pauschale_cond_table_index_by_table.clear()
    if pauschale_bedingungen_data and pauschalen_dict:
        BED_TYP_KEY = "Bedingungstyp"; BED_WERTE_KEY = "Werte"
        for cond in pauschale_bedingungen_data:
            pc_val = cond.get("Pauschale")
            if not (pc_val and str(pc_val) in pauschalen_dict):
                continue
            pc_key = str(pc_val)
            typ = str(cond.get(BED_TYP_KEY, "")).upper()
            werte = cond.get(BED_WERTE_KEY, "")
            if not werte:
                continue
            if typ in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN", "LKN IN LISTE"]:
                for lkn in str(werte).split(","):
                    lkn_norm = lkn.strip().upper()
                    if lkn_norm:
                        pauschale_cond_lkn_index[pc_key].add(lkn_norm)
                        pauschale_cond_lkn_index_by_lkn[lkn_norm].add(pc_key)
            elif typ in ["LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE", "LKN IN TABELLE"]:
                for table_name in (t.strip().lower() for t in str(werte).split(",") if t.strip()):
                    if table_name:
                        pauschale_cond_table_index[pc_key].add(table_name)
                        pauschale_cond_table_index_by_table[table_name].add(pc_key)
        logger.info(
            "  Pauschalbedingungen-Indizes aufgebaut (Pauschale->LKN: %s, Pauschale->Tabellen: %s).",
            len(pauschale_cond_lkn_index),
            len(pauschale_cond_table_index),
        )

    return all_loaded_successfully


# --- Daten laden Funktion ---
def load_data() -> bool:
    """Lädt Tarif-, Synonym- und Regeldaten aus dem lokalen ``data``-Verzeichnis."""

    global daten_geladen

    logger.info("--- Lade Daten ---")
    _reset_data_containers()

    all_loaded_successfully = _load_catalogs()
    _load_optional_datasets()
    all_loaded_successfully = _load_rules() and all_loaded_successfully
    all_loaded_successfully = _build_indices(all_loaded_successfully) and all_loaded_successfully

    logger.info("--- Daten laden abgeschlossen ---")
    if not all_loaded_successfully:
        logger.warning("WARNUNG: Einige kritische Daten konnten nicht geladen werden!")
        daten_geladen = False
    else:
        logger.info("Alle Daten erfolgreich geladen.")
        daten_geladen = True
    logger.debug("DEBUG: load_data() beendet. leistungskatalog_dict leer? %s", not leistungskatalog_dict)
    return all_loaded_successfully

# Einsatz von Flask
# Die App-Instanz, auf die Gunicorn zugreift
app: FlaskType = create_app()

# Hilfsfunktion zum stabilen Parsen von LLM-JSON-Antworten
def parse_llm_json_response(raw_text_response: str) -> Union[Dict[str, Any], List[Any]]:
    """Extrahiert JSON aus einem LLM-Rohtext und parst es robust (Markdown, Kommentare, Balancing)."""

    def _strip_code_fence(txt: str) -> str:
        s = (txt or "").strip()
        if "```" not in s:
            return s
        start = s.find("```")
        after = s[start + 3 :]
        nl = after.find("\n")
        if nl != -1:
            body = after[nl + 1 :]
            end = body.find("```")
            if end != -1:
                return body[:end].strip()
        return s

    def _strip_json_comments(src: str) -> str:
        out: List[str] = []
        i, n = 0, len(src)
        in_str = False
        esc = False
        while i < n:
            ch = src[i]
            if in_str:
                out.append(ch)
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                i += 1
            else:
                if ch == '"':
                    in_str = True
                    out.append(ch)
                    i += 1
                elif ch == "/" and i + 1 < n and src[i + 1] == "/":
                    i += 2
                    while i < n and src[i] not in ("\n", "\r"):
                        i += 1
                elif ch == "/" and i + 1 < n and src[i + 1] == "*":
                    i += 2
                    while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                        i += 1
                    i = i + 2 if i + 1 < n else n
                else:
                    out.append(ch)
                    i += 1
        return "".join(out)

    def _clean_trailing_commas(src: str) -> str:
        return re.sub(r",\s*(?=[}\]])", "", src)

    def _sanitize_control_chars(src: str) -> str:
        return "".join(ch for ch in src if ord(ch) >= 32 or ch in "\n\t\r")

    def _repair_object_separators(src: str) -> str:
        """Fügt fehlende schließende Klammern ein, wenn ein neuer Objektblock startet."""
        out: List[str] = []
        stack: List[str] = []
        in_str = False
        esc = False
        i, n = 0, len(src)
        while i < n:
            ch = src[i]
            if in_str:
                out.append(ch)
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
                out.append(ch)
                i += 1
                continue
            if ch in "{[":
                stack.append(ch)
                out.append(ch)
                i += 1
                continue
            if ch == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
                out.append(ch)
                i += 1
                continue
            if ch == "]":
                if stack and stack[-1] == "[":
                    stack.pop()
                out.append(ch)
                i += 1
                continue
            if ch == ",":
                j = i + 1
                while j < n and src[j].isspace():
                    j += 1
                next_char = src[j] if j < n else ""
                k = i - 1
                while k >= 0 and src[k].isspace():
                    k -= 1
                prev_char = src[k] if k >= 0 else ""
                # Heuristik: Wenn wir uns noch in einem offenen Objekt befinden,
                # das nicht sauber mit '}' abgeschlossen wurde, und direkt danach
                # ein neuer Objekt-Block startet, füge eine schließende Klammer ein.
                if (
                    next_char == "{"
                    and prev_char not in ("}", "]")
                    and stack
                    and stack[-1] == "{"
                ):
                    out.append("}")
                    stack.pop()
                    out.append(",")
                    i += 1
                    continue
            out.append(ch)
            i += 1
        return "".join(out)

    def _balanced_fragment(src: str) -> str | None:
        def _scan(open_ch: str, close_ch: str) -> str | None:
            i = src.find(open_ch)
            if i == -1:
                return None
            stack = 0
            in_str = False
            esc = False
            for j in range(i, len(src)):
                ch = src[j]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                    continue
                if ch == open_ch:
                    stack += 1
                elif ch == close_ch:
                    stack -= 1
                    if stack == 0:
                        return src[i : j + 1]
            return None

        return _scan("{", "}") or _scan("[", "]")

    def _balance_brackets(src: str) -> str:
        stack: List[str] = []
        in_str = False
        esc = False
        for ch in src:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in ("}", "]") and stack:
                stack.pop()
        return src + "".join(reversed(stack))

    def _attempt_parse(txt: str) -> Any | None:
        cleaned = _sanitize_control_chars(txt)
        for base in (cleaned, _strip_json_comments(cleaned)):
            if not base:
                continue
            for variant in (base, _repair_object_separators(base)):
                candidate = _clean_trailing_commas(variant)
                try:
                    return json.loads(candidate)
                except Exception:
                    continue
        return None

    source = _strip_code_fence(raw_text_response)
    parsed = _attempt_parse(source)
    if parsed is not None:
        return parsed

    first_start_candidates = [pos for pos in (source.find("{"), source.find("[")) if pos != -1]
    last_end = max(source.rfind("}"), source.rfind("]"))
    if first_start_candidates and last_end != -1:
        first_start = min(first_start_candidates)
        if last_end > first_start:
            sliced = source[first_start : last_end + 1]
            parsed = _attempt_parse(sliced)
            if parsed is not None:
                return parsed

    balanced = _balanced_fragment(source)
    if balanced:
        parsed = _attempt_parse(balanced)
        if parsed is not None:
            return parsed

    if first_start_candidates:
        fragment = source[min(first_start_candidates) :]
        fragment = _balance_brackets(_clean_trailing_commas(_strip_json_comments(fragment)))
        parsed = _attempt_parse(fragment)
        if parsed is not None:
            return parsed

    raise json.JSONDecodeError("Could not parse LLM JSON response", raw_text_response or "", 0)


def validate_stage1_result(raw_response: Any, provider_label: str = "LLM_S1") -> Dict[str, Any]:
    """Validiert und normalisiert das Ergebnis der LLM-Stufe 1 für alle Provider."""
    if isinstance(raw_response, list):
        if len(raw_response) == 1 and isinstance(raw_response[0], dict):
            llm_response_json = cast(Dict[str, Any], raw_response[0])
            logger.info("%s_INFO: JSON-Antwort war eine Liste, erstes Element wurde extrahiert.", provider_label)
        else:
            logger.error("%s_ERROR: Antwort ist eine Liste, aber nicht im erwarteten Format (einelementige Liste mit Objekt): %s", provider_label, type(raw_response))
            raise ValueError("Antwort ist eine Liste, aber nicht im erwarteten Format.")
    elif isinstance(raw_response, dict):
        llm_response_json = raw_response
    else:
        logger.error("%s_ERROR: Antwort ist kein JSON-Objekt, sondern %s", provider_label, type(raw_response))
        raise ValueError("Antwort ist kein JSON-Objekt.")

    llm_response_json.setdefault("identified_leistungen", [])
    llm_response_json.setdefault("extracted_info", {})
    llm_response_json.setdefault("begruendung_llm", "N/A")

    if not isinstance(llm_response_json["identified_leistungen"], list):
        logger.error("%s_ERROR: 'identified_leistungen' ist keine Liste, sondern %s", provider_label, type(llm_response_json["identified_leistungen"]))
        raise ValueError("'identified_leistungen' ist keine Liste.")
    if not isinstance(llm_response_json["extracted_info"], dict):
        logger.error("%s_ERROR: 'extracted_info' ist kein Dictionary, sondern %s", provider_label, type(llm_response_json["extracted_info"]))
        raise ValueError("'extracted_info' ist kein Dictionary.")
    if not isinstance(llm_response_json["begruendung_llm"], str):
        logger.warning("%s_WARN: 'begruendung_llm' ist kein String, sondern %s. Wird auf N/A gesetzt.", provider_label, type(llm_response_json["begruendung_llm"]))
        llm_response_json["begruendung_llm"] = "N/A"

    extracted_info_defaults = {
        "dauer_minuten": None,
        "menge_allgemein": None,
        "alter": None,
        "alter_operator": None,
        "geschlecht": None,
        "seitigkeit": "unbekannt",
        "anzahl_prozeduren": None,
    }
    expected_types_extracted_info = {
        "dauer_minuten": (int, type(None)),
        "menge_allgemein": (int, type(None)),
        "alter": (int, type(None)),
        "alter_operator": (str, type(None)),
        "geschlecht": (str, type(None)),
        "seitigkeit": (str, type(None)),
        "anzahl_prozeduren": (int, type(None)),
    }
    current_extracted_info = llm_response_json["extracted_info"]
    validated_extracted_info: Dict[str, Any] = {}
    for key, default_value in extracted_info_defaults.items():
        val = current_extracted_info.get(key) if isinstance(current_extracted_info, dict) else None
        if val is None:
            validated_extracted_info[key] = default_value
            if key == "seitigkeit" and default_value == "unbekannt":
                validated_extracted_info[key] = "unbekannt"
            continue

        expected_type_tuple = expected_types_extracted_info[key]
        if isinstance(val, expected_type_tuple):
            validated_extracted_info[key] = "unbekannt" if key == "seitigkeit" and val is None else val
        else:
            conversion_successful = False
            if expected_type_tuple[0] is int and val is not None:
                try:
                    validated_extracted_info[key] = int(val)
                    conversion_successful = True
                    logger.info("%s_INFO: Wert für '%s' ('%s') zu int konvertiert.", provider_label, key, val)
                except (ValueError, TypeError):
                    pass
            elif expected_type_tuple[0] is str and val is not None:
                try:
                    validated_extracted_info[key] = str(val)
                    conversion_successful = True
                    logger.info("%s_INFO: Wert für '%s' ('%s') zu str konvertiert.", provider_label, key, val)
                except (ValueError, TypeError):
                    pass
            if not conversion_successful:
                validated_extracted_info[key] = default_value
                logger.warning(
                    "%s_WARN: Typfehler für '%s'. Erwartet %s, bekam %s ('%s'). Default '%s'.",
                    provider_label,
                    key,
                    expected_type_tuple,
                    type(val),
                    val,
                    default_value,
                )
    llm_response_json["extracted_info"] = validated_extracted_info

    validated_identified_leistungen = []
    for i, item in enumerate(llm_response_json.get("identified_leistungen", [])):
        if not isinstance(item, dict):
            logger.warning("%s_WARN: Element %s in 'identified_leistungen' ist kein Dictionary. Übersprungen: %s", provider_label, i, item)
            continue
        lkn_val = item.get("lkn")
        menge_val = item.get("menge")
        if not isinstance(lkn_val, str) or not lkn_val.strip():
            logger.warning("%s_WARN: Ungültige oder leere LKN in Element %s. Übersprungen: %s", provider_label, i, item)
            continue
        item["lkn"] = lkn_val.strip().upper()
        if menge_val is None:
            item["menge"] = 1
        elif not isinstance(menge_val, int):
            try:
                item["menge"] = int(menge_val)
            except (ValueError, TypeError):
                item["menge"] = 1
                logger.warning("%s_WARN: Menge '%s' (LKN: %s) ungültig. Auf 1 gesetzt.", provider_label, menge_val, item.get("lkn"))
        if item.get("menge", 1) < 0:
            item["menge"] = 1
            logger.warning("%s_WARN: Negative Menge %s (LKN: %s). Auf 1 gesetzt.", provider_label, item.get("menge"), item.get("lkn"))
        item.setdefault("typ", "N/A")
        lkn_key = item.get("lkn")
        if leistungskatalog_dict and lkn_key and lkn_key in leistungskatalog_dict:
            item["beschreibung"] = leistungskatalog_dict[lkn_key].get("Beschreibung", "N/A")
        else:
            item.setdefault("beschreibung", "N/A")
        validated_identified_leistungen.append(item)
    llm_response_json["identified_leistungen"] = validated_identified_leistungen
    logger.info("%s_INFO: LLM Stufe 1 Antwortstruktur und Basistypen validiert/normalisiert.", provider_label)
    return llm_response_json


def _prepare_stage1_prompt(
    user_input: str,
    katalog_context: str,
    lang: str,
    query_variants: Optional[List[str]],
    provider_label: str,
) -> tuple[str, int]:
    """Erzeugt Stage-1-Prompt inkl. Kürzung/Tokenzählung für alle Provider."""
    prompt = get_stage1_prompt(user_input, katalog_context, lang, query_variants=query_variants)
    prompt_tokens = count_tokens(prompt)
    token_budget = GEMINI_TOKEN_BUDGET
    if prompt_tokens > token_budget:
        if GEMINI_TRIM_ENABLED:
            try:
                original_prompt_tokens = prompt_tokens
                ratio = max(0.2, token_budget / max(1.0, float(prompt_tokens)))
                new_len = max(GEMINI_TRIM_MIN_CONTEXT_CHARS, int(len(katalog_context) * ratio))
                trimmed_context = katalog_context[:new_len]
                prompt = get_stage1_prompt(user_input, trimmed_context, lang, query_variants=query_variants)
                trimmed_prompt_tokens = count_tokens(prompt)
                logger.warning(
                    "LLM Stufe 1: Prompt zu lang (%s Tokens). Kontext auf %s Zeichen gekürzt (jetzt %s Tokens).",
                    original_prompt_tokens,
                    new_len,
                    trimmed_prompt_tokens,
                )
                logger.warning(
                    "LLM Stufe 1 (%s): Prompt gekürzt auf Budget (%s). Kontext nun %s Zeichen (Tokens ~%s).",
                    provider_label,
                    token_budget,
                    new_len,
                    trimmed_prompt_tokens,
                )
                prompt_tokens = trimmed_prompt_tokens
            except Exception:
                # Fallback: belasse Prompt unverändert, wenn Kürzen fehlschlägt
                pass
        else:
            logger.warning(
                "LLM Stufe 1: Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0); Prompt wird unverändert übertragen.",
                prompt_tokens,
                token_budget,
            )
    return prompt, prompt_tokens


def _should_retry_request(exc: RequestException) -> bool:
    """Bestimmt, ob bei HTTP-Fehlern erneut versucht werden soll (429/5xx)."""
    resp_obj = getattr(exc, "response", None)
    status = getattr(resp_obj, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


def _post_with_retries(
    url: str,
    payload: Dict[str, Any],
    timeout: int,
    max_retries: int,
    backoff_seconds: float,
    logger_prefix: str,
    before_request: Optional[Callable[[], None]] = None,
) -> Any:
    """Führt POST-Anfrage mit Retry-Logik (429/5xx) und optionalem Hook vor Request aus."""
    last_error: RequestException | None = None
    for attempt in range(max_retries):
        try:
            if before_request:
                before_request()
            response = requests.post(url, json=payload, timeout=timeout)
            logger.info("%s Antwort Status Code: %s", logger_prefix, response.status_code)
            if response.status_code == 429:
                raise HTTPError(response=response)
            response.raise_for_status()
            return response
        except RequestException as exc:
            last_error = exc
            if attempt < max_retries - 1 and _should_retry_request(exc):
                resp_obj = getattr(exc, "response", None)
                status = getattr(resp_obj, "status_code", None)
                wait_time = backoff_seconds * (2 ** attempt)
                logger.warning("%s Fehler %s. Neuer Versuch in %s Sekunden.", logger_prefix, status or str(exc), wait_time)
                time.sleep(wait_time)
                continue
            raise
    raise last_error if last_error else ConnectionError(f"{logger_prefix}: Keine Antwort erhalten")

# --- LLM Stufe 1: LKN Identifikation ---
def call_gemini_stage1(
    user_input: str,
    katalog_context: str,
    model: str,
    lang: str = "de",
    query_variants: Optional[List[str]] = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Ruft Gemini für Stage 1 auf und liefert extrahierte Leistungen plus Tokenzahlen."""
    api_key = _get_api_key("gemini")
    logger.debug(
        "LLM_S1_INIT: Aufruf von call_gemini_stage1. GEMINI_API_KEY vorhanden: %s",
        bool(api_key),
    )
    if not api_key:
        logger.error(
            "LLM_S1_ERROR: GEMINI_API_KEY fehlt oder ist leer. Funktion wird vorzeitig beendet."
        )
        return (
            {
                "identified_leistungen": [],
                "extracted_info": {},
                "begruendung_llm": "Fehler: API Key nicht konfiguriert.",
            },
            {"input_tokens": 0, "output_tokens": 0},
        )
    prompt, prompt_tokens = _prepare_stage1_prompt(
        user_input, katalog_context, lang, query_variants, provider_label="Gemini"
    )

    response_tokens = 0
    if LOG_TOKENS:
        detail_logger.info("LLM Stufe 1 Prompt Tokens: %s", prompt_tokens)
    if LOG_LLM_INPUT:
        detail_logger.info("LLM Stufe 1 Anfrage (Input-Text): %s", user_input)
    if LOG_LLM_PROMPT:
        detail_logger.info("LLM Stufe 1 Prompt: %s", prompt)

    gemini_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    )
    generation_config: Dict[str, Any] = {
        "response_mime_type": "application/json",
        "maxOutputTokens": 65536,
    }
    if STAGE1_TEMPERATURE is not None:
        generation_config["temperature"] = STAGE1_TEMPERATURE

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    logger.info("Sende Anfrage Stufe 1 an Gemini Model: %s...", model)
    if LOG_LLM_INPUT:
        detail_logger.debug(f"LLM_S1_REQUEST_PAYLOAD: {json.dumps(payload, ensure_ascii=False)}")
    try:
        response = _post_with_retries(
            gemini_url,
            payload,
            timeout=90,
            max_retries=GEMINI_MAX_RETRIES,
            backoff_seconds=GEMINI_BACKOFF_SECONDS,
            logger_prefix="Gemini Stufe 1",
            before_request=enforce_llm_min_interval,
        )
        gemini_data = response.json()
        if LOG_LLM_OUTPUT:
            detail_logger.debug(
                f"LLM_S1_RAW_GEMINI_RESPONSE: {json.dumps(gemini_data, ensure_ascii=False)}"
            )
            detail_logger.info(
                f"LLM_S1_RAW_GEMINI_DATA: {json.dumps(gemini_data, ensure_ascii=False)}"
            )


        candidate: Dict[str, Any] | None = None
        raw_text_response: str = ""

        if gemini_data is None:
            error_details = "Fehler: Keine Daten von Gemini erhalten (gemini_data is None)."
            logger.error("%s", error_details)
            raise ValueError(error_details) # Oder eine andere Fehlerbehandlung

        if not gemini_data.get('candidates'): # Diese Prüfung ist jetzt sicher
            finish_reason_feedback = gemini_data.get('promptFeedback', {}).get('blockReason')
            safety_ratings_feedback = gemini_data.get('promptFeedback', {}).get('safetyRatings')
            error_details = f"Keine Kandidaten gefunden. Feedback: Reason={finish_reason_feedback}, Safety={safety_ratings_feedback}"
            logger.warning("%s", error_details)
            
            # Versuch, Text direkt aus gemini_data zu extrahieren, falls 'candidates' fehlt
            # (Dieser Teil ist etwas ungewöhnlich, wenn die Struktur immer 'candidates' haben sollte)
            raw_text_response = gemini_data.get('text', '') 
            if not raw_text_response:
                 raise ValueError(error_details) 
        else:
            candidate_list = gemini_data.get('candidates') # Gibt None zurück, wenn 'candidates' nicht existiert
            if candidate_list and isinstance(candidate_list, list) and len(candidate_list) > 0:
                candidate = candidate_list[0]
                # Sicherstellen, dass candidate ein dict ist, bevor .get() verwendet wird
                if isinstance(candidate, dict):
                    content = candidate.get('content', {})
                    if isinstance(content, dict):
                        parts = content.get('parts', []) # Default auf leere Liste
                        if parts and isinstance(parts, list) and len(parts) > 0:
                            first_part = parts[0]
                            if isinstance(first_part, dict):
                                raw_text_response = first_part.get('text', '')
                        elif parts and isinstance(parts, list) and len(parts) > 0 and parts[0] is None : # Explizit None prüfen, falls Gemini das macht
                            logger.warning("LLM_S1_WARN: Erster Teil der Antwort ist None.")
                            raw_text_response = "" # Sicherstellen, dass es ein String ist
                        elif not parts:
                             logger.warning("LLM_S1_WARN: 'parts' Array ist leer in der Gemini Antwort.")
                             raw_text_response = ""
                    elif content is None:
                        logger.warning("LLM_S1_WARN: 'content' ist None in der Gemini Antwort.")
                        raw_text_response = ""
                    else: # content ist kein dict
                         logger.warning(f"LLM_S1_WARN: 'content' ist kein dict, sondern {type(content)}.")
                         raw_text_response = ""
                elif candidate is None:
                     logger.warning("LLM_S1_WARN: 'candidate' ist None in der Gemini Antwort (innerhalb candidate_list).")
                     raw_text_response = ""
                else: # candidate ist kein dict
                    logger.warning(f"LLM_S1_WARN: 'candidate' ist kein dict, sondern {type(candidate)} (innerhalb candidate_list).")
                    raw_text_response = ""
            elif not candidate_list: # candidate_list ist leer
                 logger.warning("LLM_S1_WARN: 'candidates' Array ist leer in der Gemini Antwort.")
                 raw_text_response = ""
            # else: candidate_list ist nicht None, aber auch keine Liste (sollte nicht passieren bei Gemini)

        if LOG_LLM_OUTPUT:
            detail_logger.info(f"LLM_S1_RAW_TEXT_RESPONSE: '{raw_text_response}'")
        response_tokens = count_tokens(raw_text_response)
        if LOG_TOKENS:
            detail_logger.info("LLM Stufe 1 Antwort Tokens: %s", response_tokens)

        if not raw_text_response:
            if candidate and isinstance(candidate, dict):
                finish_reason_candidate = candidate.get('finishReason', 'UNKNOWN')
                safety_ratings_candidate = candidate.get('safetyRatings')
                if finish_reason_candidate != 'STOP':
                    raise ValueError(f"Gemini stopped with reason: {finish_reason_candidate}, Safety: {safety_ratings_candidate}")
                else:
                    logger.warning("Leere Textantwort von Gemini (candidate vorhanden, STOP).")
            elif candidate is None: # Explicitly handle the None case that Pylance is worried about
                # This 'else' corresponds to 'if candidate and isinstance(candidate, dict)' being false
                # because candidate was None.
                raise ValueError("Unerwarteter Zustand: Kein Candidate und keine Textantwort von Gemini (candidate was None).")
            else:
                # This 'else' handles the case where candidate is not None but also not a dict (should not happen with current typing)
                raise ValueError(f"Unerwarteter Zustand: Candidate is not a dict ({type(candidate)}) and no text response.")

        try:
            llm_response_json = parse_llm_json_response(raw_text_response)
        except json.JSONDecodeError as json_err:
            logger.error(f"Fehler beim Parsen der LLM Stufe 1 Antwort: {json_err}. Rohtext: {raw_text_response[:500]}...")
            llm_response_json = {
                "identified_leistungen": [],
                "extracted_info": {},
                "begruendung_llm": f"Fehler: Ungültiges JSON vom LLM erhalten. {json_err}"
            }

        llm_response_json = validate_stage1_result(llm_response_json, provider_label="LLM_S1")
        if LOG_S1_PARSED_JSON:
            detail_logger.info(f"LLM_S1_PARSED_JSON: {json.dumps(llm_response_json, indent=2, ensure_ascii=False)}")
        return llm_response_json, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}

    except RequestException as req_err:
        error_detail = ""
        resp_obj = getattr(req_err, "response", None)
        if isinstance(req_err, HTTPError) and resp_obj is not None:
            error_detail = f"{resp_obj.status_code} {resp_obj.text}"
        else:
            error_detail = str(req_err)
        logger.error("Netzwerkfehler bei Gemini Stufe 1: %s", error_detail)
        raise ConnectionError(f"Netzwerkfehler bei Gemini Stufe 1: {error_detail}")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as proc_err:
        logger.error("Fehler beim Verarbeiten der LLM Stufe 1 Antwort: %s", proc_err)
        traceback.print_exc()
        raise ValueError(f"Verarbeitungsfehler LLM Stufe 1: {proc_err}")
    except Exception as e:
        logger.error("Unerwarteter Fehler im LLM Stufe 1: %s", e)
        traceback.print_exc()
        raise e



def call_openai_stage1(
    user_input: str,
    katalog_context: str,
    model: str,
    api_key: Optional[str],
    base_url: Optional[str],
    provider: str,
    lang: str = "de",
    query_variants: Optional[List[str]] = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Ruft ein OpenAI-kompatibles Modell für Stage 1 und liefert Ergebnis + Tokenzähler."""
    if not api_key:
        logger.error(
            "LLM_S1_ERROR: %s_API_KEY fehlt oder ist leer. Funktion wird vorzeitig beendet.",
            provider.upper(),
        )
        return (
            {
                "identified_leistungen": [],
                "extracted_info": {},
                "begruendung_llm": "Fehler: API Key nicht konfiguriert.",
            },
            {"input_tokens": 0, "output_tokens": 0},
        )
    base_url = base_url or "https://api.openai.com/v1"
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"
    prompt, prompt_tokens = _prepare_stage1_prompt(
        user_input, katalog_context, lang, query_variants, provider_label=provider
    )

    response_tokens = 0
    if LOG_TOKENS:
        detail_logger.info("LLM Stufe 1 Prompt Tokens: %s", prompt_tokens)
    if LOG_LLM_INPUT:
        detail_logger.info("LLM Stufe 1 Anfrage (Input-Text): %s", user_input)
    if LOG_LLM_PROMPT:
        detail_logger.info("LLM Stufe 1 Prompt: %s", prompt)
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover - optional dependency
        raise RuntimeError("openai package not available") from e
    # Deaktiviert SDK-interne Retries, damit unsere eigene Drossel/Retry greift
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)  # type: ignore[reportGeneralTypeIssues]
    # Einfache Retry-Logik bei 5xx/Serverfehlern
    last_exc: Exception | None = None
    resp = None  # ensure defined for static analyzers
    # Versuche = 1 (Erstversuch) + OPENAI_SERVER_ERROR_MAX_RETRIES (Wiederholungen)
    for attempt in range(OPENAI_SERVER_ERROR_MAX_RETRIES + 1):
        try:
            # Provider-spezifischer Body: manche Klone unterstützen response_format oder max_new_tokens nicht stabil
            eb: Dict[str, Any] = {}
            if provider == "openai":
                # Keep extra_body minimal for OpenAI GPT‑5 family
                eb = {}
            elif provider == "ollama":
                # Some OpenAI-compatible clones (e.g., Ollama endpoints) accept 'max_new_tokens'.
                eb = {"max_new_tokens": min(OPENAI_MAX_OUTPUT_TOKENS, 512)}
            # apertus: keine response_format/max_new_tokens im extra_body senden

            # Nachrichtenformat: Für Apertus im Parts-Format (wie im Connectivity-Test)
            if provider == "apertus":
                _messages: List[Dict[str, Any]] = [
                    {"role": "system", "content": [{"type": "text", "text": "Du bist ein hilfreicher Assistent."}]},
                    {"role": "user", "content": [{"type": "text", "text": prompt}]},
                ]
            else:
                _messages = [
                    {"role": "system", "content": "Du bist ein hilfreicher Assistent."},
                    {"role": "user", "content": prompt},
                ]
            messages_typed = cast(List[ChatCompletionMessageParam], _messages)
            
            # Token caps per provider to reduce truncation
            if provider == "apertus":
                out_tokens = OPENAI_MAX_OUTPUT_TOKENS_APERTUS
            elif provider == "openai":
                out_tokens = min(OPENAI_MAX_OUTPUT_TOKENS, 4096)
            else:
                out_tokens = min(OPENAI_MAX_OUTPUT_TOKENS, 512)
            # OpenAI (gpt-5/5-mini) erwartet 'max_completion_tokens' statt 'max_tokens'
            token_arg = {(
                "max_completion_tokens" if provider == "openai" else "max_tokens"
            ): out_tokens}
            # Use configured sampling temperature; defaults skip unsupported providers
            temp_arg = _temperature_kwargs(STAGE1_TEMPERATURE)
            resp = chat_completion_safe(
                model=model,
                messages=messages_typed,
                user=f"arzttarif-assistent/{APP_VERSION}",
                timeout=OPENAI_TIMEOUT,
                extra_body=eb,
                extra_headers={
                    "User-Agent": f"Arzttarif-Assistent/{APP_VERSION}",
                    "Accept": "application/json",
                },
                client=client,
                **token_arg,
                **temp_arg,
            )
            break
        except Exception as e:
            last_exc = e
            err_txt = str(e)
            low = err_txt.lower()
            if "content_filter" in err_txt or "request blocked by content policy" in err_txt:
                logger.error("%s Stufe 1 durch Content-Policy blockiert: %s", provider, err_txt)
                raise PermissionError(f"{provider} Stufe 1 durch Content-Policy blockiert") from e
            status = None
            try:
                resp_obj = getattr(e, "response", None)
                status = getattr(resp_obj, "status_code", None)
            except Exception:
                status = None
            is_server_side = (isinstance(status, int) and status >= 500) or ("server_error" in low) or ("internal server error" in low)
            if is_server_side and attempt < OPENAI_SERVER_ERROR_MAX_RETRIES:
                logger.warning("%s Stufe 1: Serverfehler (%s). Wiederhole nach kurzer Pause...", provider, status or err_txt)
                time.sleep(OPENAI_SERVER_ERROR_RETRY_DELAY_SECONDS)
                continue
            raise ConnectionError(f"{provider} Stufe 1 Fehler: {e}") from e
    if resp is None:
        if last_exc is not None:
            raise ConnectionError(f"{provider} Stufe 1 Fehler: {last_exc}") from last_exc
        raise ConnectionError(f"{provider} Stufe 1 Fehler: Unbekannter Fehler")
    # Normalize content: some OpenAI‑compatible providers return a list of parts
    msg_obj = resp.choices[0].message
    raw_msg = getattr(msg_obj, "content", None)
    # Log finish_reason to detect truncation (e.g., 'length')
    try:
        finish_reason = getattr(resp.choices[0], "finish_reason", None)
        if finish_reason and LOG_LLM_OUTPUT:
            detail_logger.info("LLM_S1_%s_FINISH_REASON: %s", provider.upper(), finish_reason)
    except Exception:
        pass
    if isinstance(raw_msg, list):
        try:
            content = "".join(
                part.get("text", "") for part in raw_msg if isinstance(part, dict)
            )
        except Exception:
            content = ""  # fallback to empty; will trigger JSON error downstream
    else:
        content = raw_msg or ""
    # Fallback: some models return data via tool_calls (content may be empty)
    if not content:
        try:
            tool_calls = getattr(msg_obj, "tool_calls", None)
            tc_list = tool_calls if isinstance(tool_calls, list) else []
            args_chunks: List[str] = []
            for tc in tc_list:
                # Support both SDK objects and plain dicts
                func = getattr(tc, "function", None) or (tc.get("function") if isinstance(tc, dict) else None)
                if func is None:
                    continue
                args = getattr(func, "arguments", None) or (func.get("arguments") if isinstance(func, dict) else None)
                if isinstance(args, str) and args.strip():
                    args_chunks.append(args)
            if args_chunks:
                content = "\n".join(args_chunks)
                try:
                    detail_logger.info("LLM_S1_CONTENT_FROM_TOOL_CALLS (%s)", provider)
                except Exception:
                    pass
        except Exception:
            pass
    if LOG_LLM_OUTPUT:
        detail_logger.info("LLM_S1_RAW_%s_RESPONSE: %s", provider.upper(), content)
    response_tokens = count_tokens(content)
    if LOG_TOKENS:
        detail_logger.info("LLM Stufe 1 Antwort Tokens: %s", response_tokens)
    try:
        parsed = parse_llm_json_response(content or "{}")
    except json.JSONDecodeError as parse_err:
        try:
            detail_logger.error("LLM_S1_INVALID_JSON_RAW (%s): %s", provider, content)
        except Exception:
            pass
        raise ValueError(f"{provider} Stufe 1: ungültige JSON-Antwort ({parse_err})")
    data = validate_stage1_result(parsed, provider_label=f"LLM_S1_{provider.upper()}")
    if LOG_S1_PARSED_JSON:
        detail_logger.info(
            "LLM_S1_%s_PARSED_JSON: %s",
            provider.upper(),
            json.dumps(data, indent=2, ensure_ascii=False),
        )
    return data, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}

def call_gemini_stage2_mapping(
    tardoc_lkn: str,
    tardoc_desc: str,
    candidate_pauschal_lkns: Dict[str, str],
    model: str,
    lang: str = "de",
) -> tuple[str | None, dict[str, int]]:
    """Lässt Gemini ein Mapping von TARDOC-LKN zu Pauschalen-Kandidaten vornehmen."""
    api_key = _get_api_key("gemini")
    if not api_key:
        raise ValueError("GEMINI_API_KEY nicht konfiguriert.")
    if not candidate_pauschal_lkns:
        logger.warning("Keine Kandidaten-LKNs für Mapping von %s übergeben.", tardoc_lkn)
        return None, {"input_tokens": 0, "output_tokens": 0}

    candidates_text = "\n".join([f"- {lkn}: {desc}" for lkn, desc in candidate_pauschal_lkns.items()])
    if len(candidates_text) > 15000:  # Limit Kontextlänge (Anpassen nach Bedarf)
        logger.warning(
            "Kandidatenliste für %s zu lang (%s Zeichen), wird gekürzt.",
            tardoc_lkn,
            len(candidates_text),
        )
        candidates_text = candidates_text[:15000] + "\n..."  # Einfache Kürzung

    prompt = get_stage2_mapping_prompt(tardoc_lkn, tardoc_desc, candidates_text, lang)
    prompt_tokens = count_tokens(prompt)
    # Proaktives Kürzen sehr langer Prompts auf Basis des konfigurierten Budgets
    TOKEN_BUDGET = GEMINI_TOKEN_BUDGET
    if prompt_tokens > TOKEN_BUDGET:
        if GEMINI_TRIM_ENABLED:
            try:
                original_prompt_tokens = prompt_tokens
                ratio = max(0.2, TOKEN_BUDGET / max(1.0, float(prompt_tokens)))
                new_len = max(GEMINI_TRIM_MIN_CONTEXT_CHARS, int(len(candidates_text) * ratio))
                trimmed_candidates_text = candidates_text[:new_len]
                prompt = get_stage2_mapping_prompt(
                    tardoc_lkn, tardoc_desc, trimmed_candidates_text, lang
                )
                trimmed_prompt_tokens = count_tokens(prompt)
                logger.warning(
                    "LLM Stufe 2 (Mapping): Prompt zu lang (%s Tokens). Kontext auf %s Zeichen gekürzt (jetzt %s Tokens).",
                    original_prompt_tokens,
                    new_len,
                    trimmed_prompt_tokens,
                )
                logger.warning(
                    "LLM Stufe 2 (Gemini Mapping): Prompt gekürzt auf Budget (%s). Kontext nun %s Zeichen (Tokens ~%s).",
                    TOKEN_BUDGET,
                    new_len,
                    trimmed_prompt_tokens,
                )
                prompt_tokens = trimmed_prompt_tokens
                candidates_text = trimmed_candidates_text
            except Exception:
                # Fallback: belasse Prompt unverändert, wenn Kürzen fehlschlägt
                pass
        else:
            # WICHTIG: Diese Warnung und das unveränderte Prompt-Handling dürfen ohne expliziten Auftrag nicht angepasst werden.
            logger.warning(
                "LLM Stufe 2 (Mapping): Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0); Prompt wird unverändert übertragen.",
                prompt_tokens,
                TOKEN_BUDGET,
            )

    response_tokens = 0
    if LOG_TOKENS:
        detail_logger.info("LLM Stufe 2 (Mapping) Prompt Tokens: %s", prompt_tokens)
    if LOG_LLM_PROMPT:
        detail_logger.info("LLM Stufe 2 (Mapping) Prompt: %s", prompt)

    gemini_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    )
    generation_config: Dict[str, Any] = {
        "response_mime_type": "application/json", # Beibehalten, da Gemini manchmal JSON sendet
        "maxOutputTokens": 512, # Fuer eine kurze Liste von Codes sollte das reichen
    }
    if STAGE2_MAPPING_TEMPERATURE is not None:
        generation_config["temperature"] = STAGE2_MAPPING_TEMPERATURE

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    logger.info(
        "Sende Anfrage Stufe 2 (Mapping) für %s an Gemini Model: %s...",
        tardoc_lkn,
        model,
    )
    try:
        response = _post_with_retries(
            gemini_url,
            payload,
            timeout=GEMINI_TIMEOUT,
            max_retries=GEMINI_MAX_RETRIES,
            backoff_seconds=GEMINI_BACKOFF_SECONDS,
            logger_prefix="Gemini Stufe 2 (Mapping)",
        )
        gemini_data = response.json()

        raw_text_response_part = ""
        if gemini_data.get('candidates'):
            candidate_list_map = gemini_data.get('candidates')
            if candidate_list_map and isinstance(candidate_list_map, list) and len(candidate_list_map) > 0:
                content_map = candidate_list_map[0].get('content', {})
                parts_map = content_map.get('parts', [{}])
                if parts_map and isinstance(parts_map, list) and len(parts_map) > 0:
                     raw_text_response_part = parts_map[0].get('text', '').strip()
        if LOG_LLM_OUTPUT:
            detail_logger.debug("DEBUG: Roher Text von LLM Stufe 2 (Mapping) für %s: '%s'", tardoc_lkn, raw_text_response_part)
        response_tokens = count_tokens(raw_text_response_part)
        if LOG_TOKENS:
            detail_logger.info("LLM Stufe 2 (Mapping) Antwort Tokens: %s", response_tokens)

        if not raw_text_response_part:
            logger.info("Kein passendes Mapping für %s gefunden (LLM-Antwort war leer).", tardoc_lkn)
            return None, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}
        if raw_text_response_part.upper() == "NONE":
            logger.info("Kein passendes Mapping für %s gefunden (LLM sagte explizit NONE).", tardoc_lkn)
            return None, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}

        extracted_codes_from_llm = []
        try: # Versuche zuerst, als JSON zu parsen
            parsed_data = json.loads(raw_text_response_part)
            if isinstance(parsed_data, dict) and "EQUIVALENT_LKNS" in parsed_data and isinstance(parsed_data["EQUIVALENT_LKNS"], list):
                extracted_codes_from_llm = [str(code).strip().upper().replace('"', '') for code in parsed_data["EQUIVALENT_LKNS"] if str(code).strip()]
            elif isinstance(parsed_data, list): # Falls es direkt eine Liste ist
                extracted_codes_from_llm = [str(code).strip().upper().replace('"', '') for code in parsed_data if str(code).strip()]
        except json.JSONDecodeError: # Wenn kein JSON, dann als Text behandeln
            text_to_split = str(raw_text_response_part)
            match_markdown = re.search(r'```(?:json|text)?\s*([\s\S]*?)\s*```', text_to_split, re.IGNORECASE) # Erkenne auch ```text
            if match_markdown:
                text_to_split = str(match_markdown.group(1).strip())
            
            # Entferne Anführungszeichen und splitte nach Komma
            extracted_codes_from_llm = [
                str(code).strip().upper().replace('"', '')
                for code in text_to_split.split(',')
                if str(code).strip() and str(code).strip().upper() != "NONE"
            ]
        
        if LOG_LLM_OUTPUT:
            detail_logger.info(f"LLM Stage 2 (Mapping) for {tardoc_lkn} - Raw response: '{raw_text_response_part}'")
            detail_logger.info(f"LLM Stage 2 (Mapping) for {tardoc_lkn} - Extracted codes: {extracted_codes_from_llm}")
            detail_logger.info(
                "Mapping-Antwort (%s) geparst: %s",
                'JSON' if (isinstance(extracted_codes_from_llm, list) and raw_text_response_part.startswith('[') or raw_text_response_part.startswith('{')) else 'Text',
                extracted_codes_from_llm,
            )

        for code in extracted_codes_from_llm:
            if code in candidate_pauschal_lkns:
                logger.info("Mapping erfolgreich (aus Liste): %s -> %s", tardoc_lkn, code)
                return code, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}

        if extracted_codes_from_llm: # Nur loggen, wenn LLM was zurückgab, das nicht passte
            logger.warning(
                "Keiner der vom Mapping-LLM zurückgegebenen Codes (%s) war valide oder passte für %s.",
                extracted_codes_from_llm,
                tardoc_lkn,
            )
        else: # Fall, wo raw_text_response_part nicht NONE war, aber nichts extrahiert wurde
            logger.warning(
                "Kein passendes Mapping für %s gefunden (LLM-Antwort konnte nicht zu Codes geparst werden: '%s').",
                tardoc_lkn,
                raw_text_response_part,
            )
        return None, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}

    except RequestException as req_err:
        logger.error("Netzwerkfehler bei Gemini Stufe 2 (Mapping): %s", req_err)
        return None, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}  # Wichtig, um ConnectionError weiterzugeben
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.error("Fehler beim Verarbeiten der Mapping-Antwort für %s: %s", tardoc_lkn, e)
        traceback.print_exc()
        return None, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}
    except Exception as e:
        logger.error("Unerwarteter Fehler im LLM Stufe 2 (Mapping) für %s: %s", tardoc_lkn, e)
        traceback.print_exc()
        return None, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}



def call_openai_stage2_mapping(
    tardoc_lkn: str,
    tardoc_desc: str,
    candidate_pauschal_lkns: Dict[str, str],
    model: str,
    api_key: Optional[str],
    base_url: Optional[str],
    provider: str,
    lang: str = "de",
) -> tuple[str | None, dict[str, int]]:
    """Verwendet ein OpenAI-kompatibles Modell für das Stage-2-Mapping auf Pauschalen."""
    if not api_key:
        raise ValueError(f"{provider.upper()}_API_KEY nicht konfiguriert.")
    if not candidate_pauschal_lkns:
        logger.warning("Keine Kandidaten-LKNs für Mapping von %s übergeben.", tardoc_lkn)
        return None, {"input_tokens": 0, "output_tokens": 0}
    candidates_text = "\n".join(
        [f"- {lkn}: {desc}" for lkn, desc in candidate_pauschal_lkns.items()]
    )
    if len(candidates_text) > 15000:
        candidates_text = candidates_text[:15000] + "\n..."
    prompt = get_stage2_mapping_prompt(tardoc_lkn, tardoc_desc, candidates_text, lang)
    prompt_tokens = count_tokens(prompt)
    # Proaktives Kürzen sehr langer Prompts auf Basis des konfigurierten Budgets
    TOKEN_BUDGET = GEMINI_TOKEN_BUDGET
    if prompt_tokens > TOKEN_BUDGET:
        if GEMINI_TRIM_ENABLED:
            try:
                original_prompt_tokens = prompt_tokens
                ratio = max(0.2, TOKEN_BUDGET / max(1.0, float(prompt_tokens)))
                new_len = max(GEMINI_TRIM_MIN_CONTEXT_CHARS, int(len(candidates_text) * ratio))
                trimmed_candidates_text = candidates_text[:new_len]
                prompt = get_stage2_mapping_prompt(
                    tardoc_lkn, tardoc_desc, trimmed_candidates_text, lang
                )
                trimmed_prompt_tokens = count_tokens(prompt)
                logger.warning(
                    "LLM Stufe 2 (Mapping): Prompt zu lang (%s Tokens). Kontext auf %s Zeichen gekürzt (jetzt %s Tokens).",
                    original_prompt_tokens,
                    new_len,
                    trimmed_prompt_tokens,
                )
                logger.warning(
                    "LLM Stufe 2 (Mapping %s): Prompt gekürzt auf Budget (%s). Kontext nun %s Zeichen (Tokens ~%s).",
                    provider.capitalize(),
                    TOKEN_BUDGET,
                    new_len,
                    trimmed_prompt_tokens,
                )
                prompt_tokens = trimmed_prompt_tokens
                candidates_text = trimmed_candidates_text
            except Exception:
                # Fallback: belasse Prompt unverändert, wenn Kürzen fehlschlägt
                pass
        else:
            # WICHTIG: Diese Warnung und das unveränderte Prompt-Handling dürfen ohne expliziten Auftrag nicht angepasst werden.
            logger.warning(
                "LLM Stufe 2 (Mapping): Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0); Prompt wird unverändert übertragen.",
                prompt_tokens,
                TOKEN_BUDGET,
            )

    response_tokens = 0
    if LOG_TOKENS:
        detail_logger.info("LLM Stufe 2 (Mapping) Prompt Tokens: %s", prompt_tokens)
    if LOG_LLM_PROMPT:
        detail_logger.info("LLM Stufe 2 (Mapping) Prompt: %s", prompt)
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover - optional dependency
        raise RuntimeError("openai package not available") from e
    base_url = base_url or "https://api.openai.com/v1"
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"
    # Deaktiviert SDK-interne Retries, damit unsere eigene Drossel/Retry greift
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)  # type: ignore[reportGeneralTypeIssues]
    # Retry-Logik bei 5xx analog Stufe 1
    last_exc: Exception | None = None
    resp = None
    for attempt in range(OPENAI_SERVER_ERROR_MAX_RETRIES + 1):
        try:
            # Avoid unsupported params on OpenAI: do not send 'max_new_tokens'.
            _extra_body = {} if provider == "openai" else {"max_new_tokens": OPENAI_MAX_OUTPUT_TOKENS}
            token_arg = {(
                "max_completion_tokens" if provider == "openai" else "max_tokens"
            ): OPENAI_MAX_OUTPUT_TOKENS}
            # Use configured sampling temperature; defaults skip unsupported providers
            temp_arg = _temperature_kwargs(STAGE2_MAPPING_TEMPERATURE)
            resp = chat_completion_safe(
                model=model,
                messages=[
                    {"role": "system", "content": "Du bist ein hilfreicher Assistent."},
                    {"role": "user", "content": prompt},
                ],
                user=f"arzttarif-assistent/{APP_VERSION}",
                timeout=OPENAI_TIMEOUT,
                extra_body=_extra_body,
                extra_headers={
                    "User-Agent": f"Arzttarif-Assistent/{APP_VERSION}",
                    "Accept": "application/json",
                },
                client=client,
                **token_arg,
                **temp_arg,
            )
            break
        except Exception as e:
            last_exc = e
            err_txt = str(e)
            if "content_filter" in err_txt or "Request blocked by content policy" in err_txt:
                logger.error("%s Stufe 2 (Mapping) durch Content-Policy blockiert: %s", provider, err_txt)
                raise PermissionError(f"{provider} Stufe 2 (Mapping) durch Content-Policy blockiert") from e
            status = None
            try:
                resp_obj = getattr(e, "response", None)
                status = getattr(resp_obj, "status_code", None)
            except Exception:
                status = None
            is_server_side = (isinstance(status, int) and status >= 500) or ("server_error" in err_txt.lower()) or ("internal server error" in err_txt.lower())
            if is_server_side and attempt < OPENAI_SERVER_ERROR_MAX_RETRIES:
                logger.warning("%s Stufe 2 (Mapping): Serverfehler (%s). Wiederhole nach %.1fs …", provider, status or err_txt, OPENAI_SERVER_ERROR_RETRY_DELAY_SECONDS)
                time.sleep(OPENAI_SERVER_ERROR_RETRY_DELAY_SECONDS)
                continue
            raise ConnectionError(f"{provider} Stufe 2 (Mapping) Fehler: {e}") from e
    if resp is None:
        if last_exc is not None:
            raise ConnectionError(f"{provider} Stufe 2 (Mapping) Fehler: {last_exc}") from last_exc
        raise ConnectionError(f"{provider} Stufe 2 (Mapping) Fehler: Unbekannter Fehler")
    content = (resp.choices[0].message.content or "").strip()
    if LOG_LLM_OUTPUT:
        detail_logger.debug("LLM Stage 2 (Mapping) raw %s response for %s: '%s'", provider, tardoc_lkn, content)
    response_tokens = count_tokens(content)
    if LOG_TOKENS:
        detail_logger.info("LLM Stufe 2 (Mapping) Antwort Tokens: %s", response_tokens)
    return (content or None), {"input_tokens": prompt_tokens, "output_tokens": response_tokens}

# --- LLM Stufe 2: Pauschalen-Ranking ---
def call_gemini_stage2_ranking(
    user_input: str,
    potential_pauschalen_text: str,
    model: str,
    lang: str = "de",
) -> tuple[list[str], dict[str, int]]:
    """Bewertet Pauschalen-Kandidaten mit Gemini und liefert Top-Liste plus Tokenzahlen."""
    api_key = _get_api_key("gemini")
    if not api_key:
        return ([line.split(":", 1)[0].strip() for line in potential_pauschalen_text.splitlines() if ":" in line][:5], {"input_tokens": 0, "output_tokens": 0})

    prompt = get_stage2_ranking_prompt(user_input, potential_pauschalen_text, lang)
    prompt_tokens = count_tokens(prompt)
    # Proaktives Kürzen sehr langer Prompts auf Basis des konfigurierten Budgets
    TOKEN_BUDGET = GEMINI_TOKEN_BUDGET
    if prompt_tokens > TOKEN_BUDGET:
        if GEMINI_TRIM_ENABLED:
            try:
                original_prompt_tokens = prompt_tokens
                ratio = max(0.2, TOKEN_BUDGET / max(1.0, float(prompt_tokens)))
                new_len = max(
                    GEMINI_TRIM_MIN_CONTEXT_CHARS,
                    int(len(potential_pauschalen_text) * ratio),
                )
                trimmed_pauschalen_text = potential_pauschalen_text[:new_len]
                prompt = get_stage2_ranking_prompt(
                    user_input, trimmed_pauschalen_text, lang
                )
                trimmed_prompt_tokens = count_tokens(prompt)
                logger.warning(
                    "LLM Stufe 2 (Ranking): Prompt zu lang (%s Tokens). Kontext auf %s Zeichen gekürzt (jetzt %s Tokens).",
                    original_prompt_tokens,
                    new_len,
                    trimmed_prompt_tokens,
                )
                logger.warning(
                    "LLM Stufe 2 (Gemini Ranking): Prompt gekürzt auf Budget (%s). Kontext nun %s Zeichen (Tokens ~%s).",
                    TOKEN_BUDGET,
                    new_len,
                    trimmed_prompt_tokens,
                )
                prompt_tokens = trimmed_prompt_tokens
                potential_pauschalen_text = trimmed_pauschalen_text
            except Exception:
                # Fallback: belasse Prompt unverändert, wenn Kürzen fehlschlägt
                pass
        else:
            # WICHTIG: Diese Warnung und das unveränderte Prompt-Handling dürfen ohne expliziten Auftrag nicht angepasst werden.
            logger.warning(
                "LLM Stufe 2 (Ranking): Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0); Prompt wird unverändert übertragen.",
                prompt_tokens,
                TOKEN_BUDGET,
            )

    response_tokens = 0
    if LOG_TOKENS:
        detail_logger.info("LLM Stufe 2 (Ranking) Prompt Tokens: %s", prompt_tokens)
    if LOG_LLM_PROMPT:
        detail_logger.info("LLM Stufe 2 (Ranking) Prompt: %s", prompt)

    gemini_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    )
    generation_config: Dict[str, Any] = {
        "maxOutputTokens": 500,
    }
    if STAGE2_RANKING_TEMPERATURE is not None:
        generation_config["temperature"] = STAGE2_RANKING_TEMPERATURE

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    logger.info("Sende Anfrage Stufe 2 (Ranking) an Gemini Model: %s...", model)
    try:
        response = _post_with_retries(
            gemini_url,
            payload,
            timeout=GEMINI_TIMEOUT,
            max_retries=GEMINI_MAX_RETRIES,
            backoff_seconds=GEMINI_BACKOFF_SECONDS,
            logger_prefix="Gemini Stufe 2 (Ranking)",
            before_request=enforce_llm_min_interval,
        )
        gemini_data = response.json()

        ranked_text = ""
        if gemini_data.get('candidates'):
            candidate_list_rank = gemini_data.get('candidates')
            if candidate_list_rank and isinstance(candidate_list_rank, list) and len(candidate_list_rank) > 0:
                content_rank = candidate_list_rank[0].get('content', {})
                parts_rank = content_rank.get('parts', [{}])
                if parts_rank and isinstance(parts_rank, list) and len(parts_rank) > 0:
                    ranked_text = parts_rank[0].get('text', '').strip()
        
        ranked_text_cleaned = ranked_text.replace("`", "") # Entferne Backticks
        # Erlaube auch Leerzeichen als Trenner, falls Komma fehlt, und filtere leere Strings nach Split
        ranked_codes = [
            code.strip().upper() for code_group in ranked_text_cleaned.split(',')
            for code in code_group.split() # Erlaube Split nach Space innerhalb von Komma-Segmenten
            if code.strip() and re.match(r'^[A-Z0-9.]+$', code.strip().upper())
        ]
        # Entferne Duplikate unter Beibehaltung der Reihenfolge
        seen = set()
        ranked_codes = [x for x in ranked_codes if not (x in seen or seen.add(x))]

        if LOG_LLM_OUTPUT:
            detail_logger.info(f"LLM Stage 2 (Ranking) - Raw response: '{ranked_text}'")
            detail_logger.info(f"LLM Stage 2 (Ranking) - Extracted and cleaned codes: {ranked_codes}")
            detail_logger.info("LLM Stufe 2 Gerankte Codes nach Filter: %s (aus Rohtext: '%s')", ranked_codes, ranked_text)
        response_tokens = count_tokens(ranked_text)
        if LOG_TOKENS:
            detail_logger.info("LLM Stufe 2 (Ranking) Antwort Tokens: %s", response_tokens)
        if not ranked_codes and ranked_text:  # Nur warnen, wenn Text da war, aber keine Codes extrahiert wurden
            logger.warning("LLM Stufe 2 (Ranking) hat keine gültigen Codes aus '%s' zurückgegeben.", ranked_text)
        elif not ranked_text:
            logger.warning("LLM Stufe 2 (Ranking) hat leeren Text zurückgegeben.")

        if not ranked_codes:
            fallback_candidates = []
            for line in potential_pauschalen_text.splitlines():
                if ":" not in line:
                    continue
                candidate_code = line.split(":", 1)[0].strip().upper()
                if candidate_code and re.match(r'^[A-Z0-9.]+$', candidate_code):
                    if candidate_code not in fallback_candidates:
                        fallback_candidates.append(candidate_code)
            if fallback_candidates:
                ranked_codes = fallback_candidates[:5]
                logger.info(
                    "LLM Stufe 2 (Ranking) nutzt Fallback-Reihenfolge: %s",
                    ranked_codes,
                )
        return ranked_codes, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}
    except RequestException as req_err:
        logger.error("Netzwerkfehler bei Gemini Stufe 2 (Ranking): %s", req_err)
        raise ConnectionError(f"Netzwerkfehler bei Gemini Stufe 2 (Ranking): {req_err}")  # Wichtig für analyze_billing
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as e:
        logger.error("Fehler beim Extrahieren/Verarbeiten des Rankings: %s", e)
        traceback.print_exc()
        return [], {"input_tokens": prompt_tokens, "output_tokens": response_tokens}  # Leere Liste, damit Fallback greift
    except Exception as e:
        logger.error("Unerwarteter Fehler im LLM Stufe 2 (Ranking): %s", e)
        traceback.print_exc()
        raise e  # Erneut auslösen, um den Fehler im Hauptteil zu fangen



def call_openai_stage2_ranking(
    user_input: str,
    potential_pauschalen_text: str,
    model: str,
    api_key: Optional[str],
    base_url: Optional[str],
    provider: str,
    lang: str = "de",
) -> tuple[list[str], dict[str, int]]:
    """Bewertet Pauschalen-Kandidaten mit OpenAI-kompatiblen Modellen und zählt Tokens."""
    if not api_key:
        return ([line.split(":", 1)[0].strip() for line in potential_pauschalen_text.splitlines() if ":" in line][:5], {"input_tokens": 0, "output_tokens": 0})
    prompt = get_stage2_ranking_prompt(user_input, potential_pauschalen_text, lang)
    prompt_tokens = count_tokens(prompt)
    # Proaktives Kürzen sehr langer Prompts auf Basis des konfigurierten Budgets
    TOKEN_BUDGET = GEMINI_TOKEN_BUDGET
    if prompt_tokens > TOKEN_BUDGET:
        if GEMINI_TRIM_ENABLED:
            try:
                original_prompt_tokens = prompt_tokens
                ratio = max(0.2, TOKEN_BUDGET / max(1.0, float(prompt_tokens)))
                new_len = max(
                    GEMINI_TRIM_MIN_CONTEXT_CHARS,
                    int(len(potential_pauschalen_text) * ratio),
                )
                trimmed_pauschalen_text = potential_pauschalen_text[:new_len]
                prompt = get_stage2_ranking_prompt(
                    user_input, trimmed_pauschalen_text, lang
                )
                trimmed_prompt_tokens = count_tokens(prompt)
                logger.warning(
                    "LLM Stufe 2 (Ranking): Prompt zu lang (%s Tokens). Kontext auf %s Zeichen gekürzt (jetzt %s Tokens).",
                    original_prompt_tokens,
                    new_len,
                    trimmed_prompt_tokens,
                )
                logger.warning(
                    "LLM Stufe 2 (Ranking %s): Prompt gekürzt auf Budget (%s). Kontext nun %s Zeichen (Tokens ~%s).",
                    provider.capitalize(),
                    TOKEN_BUDGET,
                    new_len,
                    trimmed_prompt_tokens,
                )
                prompt_tokens = trimmed_prompt_tokens
                potential_pauschalen_text = trimmed_pauschalen_text
            except Exception:
                # Fallback: belasse Prompt unverändert, wenn Kürzen fehlschlägt
                pass
        else:
            # WICHTIG: Diese Warnung und das unveränderte Prompt-Handling dürfen ohne expliziten Auftrag nicht angepasst werden.
            logger.warning(
                "LLM Stufe 2 (Ranking): Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0); Prompt wird unverändert übertragen.",
                prompt_tokens,
                TOKEN_BUDGET,
            )

    response_tokens = 0
    if LOG_TOKENS:
        detail_logger.info("LLM Stufe 2 (Ranking) Prompt Tokens: %s", prompt_tokens)
    if LOG_LLM_PROMPT:
        detail_logger.info("LLM Stufe 2 (Ranking) Prompt: %s", prompt)
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:  # pragma: no cover - optional dependency
        raise RuntimeError("openai package not available") from e
    base_url = base_url or "https://api.openai.com/v1"
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"
    # Deaktiviert SDK-interne Retries, damit unsere eigene Drossel/Retry greift
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)  # type: ignore[reportGeneralTypeIssues]
    # Retry-Logik bei 5xx analog Stufe 1
    last_exc: Exception | None = None
    resp = None
    for attempt in range(OPENAI_SERVER_ERROR_MAX_RETRIES + 1):
        try:
            # Avoid unsupported params on OpenAI: do not send 'max_new_tokens'.
            _extra_body = {} if provider == "openai" else {"max_new_tokens": OPENAI_MAX_OUTPUT_TOKENS}
            token_arg = {(
                "max_completion_tokens" if provider == "openai" else "max_tokens"
            ): OPENAI_MAX_OUTPUT_TOKENS}
            # Use configured sampling temperature; defaults skip unsupported providers
            temp_arg = _temperature_kwargs(STAGE2_RANKING_TEMPERATURE)
            resp = chat_completion_safe(
                model=model,
                messages=[
                    {"role": "system", "content": "Du bist ein hilfreicher Assistent."},
                    {"role": "user", "content": prompt},
                ],
                user=f"arzttarif-assistent/{APP_VERSION}",
                timeout=OPENAI_TIMEOUT,
                extra_body=_extra_body,
                extra_headers={
                    "User-Agent": f"Arzttarif-Assistent/{APP_VERSION}",
                    "Accept": "application/json",
                },
                client=client,
                **token_arg,
                **temp_arg,
            )
            break
        except Exception as e:
            last_exc = e
            err_txt = str(e)
            if "content_filter" in err_txt or "Request blocked by content policy" in err_txt:
                logger.error("%s Stufe 2 (Ranking) durch Content-Policy blockiert: %s", provider, err_txt)
                raise PermissionError(f"{provider} Stufe 2 (Ranking) durch Content-Policy blockiert") from e
            status = None
            try:
                resp_obj = getattr(e, "response", None)
                status = getattr(resp_obj, "status_code", None)
            except Exception:
                status = None
            is_server_side = (isinstance(status, int) and status >= 500) or ("server_error" in err_txt.lower()) or ("internal server error" in err_txt.lower())
            if is_server_side and attempt < OPENAI_SERVER_ERROR_MAX_RETRIES:
                logger.warning("%s Stufe 2 (Ranking): Serverfehler (%s). Wiederhole nach %.1fs …", provider, status or err_txt, OPENAI_SERVER_ERROR_RETRY_DELAY_SECONDS)
                time.sleep(OPENAI_SERVER_ERROR_RETRY_DELAY_SECONDS)
                continue
            raise ConnectionError(f"{provider} Stufe 2 (Ranking) Fehler: {e}") from e
    if resp is None:
        if last_exc is not None:
            raise ConnectionError(f"{provider} Stufe 2 (Ranking) Fehler: {last_exc}") from last_exc
        raise ConnectionError(f"{provider} Stufe 2 (Ranking) Fehler: Unbekannter Fehler")
    content = resp.choices[0].message.content or ""
    if LOG_LLM_OUTPUT:
        detail_logger.info(f"LLM Stage 2 (Ranking) raw {provider} response: '{content}'")
    response_tokens = count_tokens(content)
    if LOG_TOKENS:
        detail_logger.info("LLM Stufe 2 (Ranking) Antwort Tokens: %s", response_tokens)
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return [str(c).strip().upper() for c in data if str(c).strip()], {"input_tokens": prompt_tokens, "output_tokens": response_tokens}
    except Exception:
        pass
    ranked_codes = [
        line.strip().split()[0].upper()
        for line in content.replace("`", "").splitlines()
        if line.strip()
    ]
    seen: set[str] = set()
    ranked_codes = [c for c in ranked_codes if not (c in seen or seen.add(c))]
    if not ranked_codes:
        fallback_candidates = []
        for line in potential_pauschalen_text.splitlines():
            if ":" not in line:
                continue
            candidate_code = line.split(":", 1)[0].strip().upper()
            if candidate_code and re.match(r'^[A-Z0-9.]+$', candidate_code):
                if candidate_code not in fallback_candidates:
                    fallback_candidates.append(candidate_code)
        if fallback_candidates:
            ranked_codes = fallback_candidates[:5]
            logger.info(
                "%s Stufe 2 (Ranking) nutzt Fallback-Reihenfolge: %s",
                provider,
                ranked_codes,
            )
    return ranked_codes, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}



def call_llm_stage1(
    user_input: str,
    katalog_context: str,
    lang: str = "de",
    query_variants: Optional[List[str]] = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Ruft Stage 1 beim konfigurierten Provider auf und normalisiert das Ergebnis."""
    if STAGE1_PROVIDER == "gemini":
        result = call_gemini_stage1(
            user_input, katalog_context, STAGE1_MODEL, lang, query_variants=query_variants
        )
    else:
        api_key = _get_api_key(STAGE1_PROVIDER)
        base_url = _get_base_url(STAGE1_PROVIDER)
        if STAGE1_PROVIDER == "ollama":
            base_url = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
            if not api_key:
                api_key = os.getenv("OLLAMA_API_KEY", "ollama")
        elif STAGE1_PROVIDER == "apertus":
            # Default PublicAI (Apertus) OpenAI-compatible endpoint if not provided
            # Discovery ergab: https://api.publicai.co/v1 liefert /models JSON
            base_url = base_url or "https://api.publicai.co/v1"
        result = call_openai_stage1(
            user_input,
            katalog_context,
            STAGE1_MODEL,
            api_key,
            base_url,
            STAGE1_PROVIDER,
            lang,
            query_variants=query_variants,
        )
    if isinstance(result, tuple):
        return result
    return result, {"input_tokens": 0, "output_tokens": 0}



def call_llm_stage2_mapping(
    tardoc_lkn: str,
    tardoc_desc: str,
    candidate_pauschal_lkns: Dict[str, str],
    lang: str = "de",
) -> tuple[str | None, dict[str, int]]:
    """Steuert Stage 2 (Mapping) abhängig vom konfigurierten Provider."""
    if STAGE2_PROVIDER == "gemini":
        result = call_gemini_stage2_mapping(
            tardoc_lkn, tardoc_desc, candidate_pauschal_lkns, STAGE2_MODEL, lang
        )
    else:
        api_key = _get_api_key(STAGE2_PROVIDER)
        base_url = _get_base_url(STAGE2_PROVIDER)
        if STAGE2_PROVIDER == "ollama":
            base_url = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
            if not api_key:
                api_key = os.getenv("OLLAMA_API_KEY", "ollama")
        elif STAGE2_PROVIDER == "apertus":
            base_url = base_url or "https://api.publicai.co/v1"
        result = call_openai_stage2_mapping(
            tardoc_lkn,
            tardoc_desc,
            candidate_pauschal_lkns,
            STAGE2_MODEL,
            api_key,
            base_url,
            STAGE2_PROVIDER,
            lang,
        )
    if isinstance(result, tuple):
        return result
    return result, {"input_tokens": 0, "output_tokens": 0}



def call_llm_stage2_ranking(
    user_input: str,
    potential_pauschalen_text: str,
    lang: str = "de",
) -> tuple[list[str], dict[str, int]]:
    """Steuert Stage 2 (Ranking) und bündelt das Ergebnis je nach Provider."""
    if STAGE2_PROVIDER == "gemini":
        result = call_gemini_stage2_ranking(
            user_input, potential_pauschalen_text, STAGE2_MODEL, lang
        )
    else:
        api_key = _get_api_key(STAGE2_PROVIDER)
        base_url = _get_base_url(STAGE2_PROVIDER)
        if STAGE2_PROVIDER == "ollama":
            base_url = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
            if not api_key:
                api_key = os.getenv("OLLAMA_API_KEY", "ollama")
        elif STAGE2_PROVIDER == "apertus":
            base_url = base_url or "https://api.publicai.co/v1"
        result = call_openai_stage2_ranking(
            user_input,
            potential_pauschalen_text,
            STAGE2_MODEL,
            api_key,
            base_url,
            STAGE2_PROVIDER,
            lang,
        )
    if isinstance(result, tuple):
        return result
    return result, {"input_tokens": 0, "output_tokens": 0}

# get_table_content (aus utils.py, hier für Vollständigkeit, falls utils nicht verfügbar)
# Die Funktion get_table_content wurde bereits in utils.py definiert und hier importiert.
# Falls sie nicht in utils.py ist, müsste sie hier implementiert werden.
# Annahme: sie ist in utils.py und funktioniert korrekt.

# --- Ausgelagerte TARDOC-Vorbereitung ---
# prepare_tardoc_abrechnung wird jetzt über prepare_tardoc_abrechnung_func aufgerufen,
# die entweder die echte Funktion aus regelpruefer_einzelleistungen.py oder einen Fallback enthält.

def get_LKNs_from_pauschalen_conditions(
    potential_pauschale_codes: Set[str],
    pauschale_bedingungen_data_list: List[Dict[str, Any]], # Umbenannt
    tabellen_dict: Dict[str, List[Dict[str, Any]]], # Umbenannt
    leistungskatalog: Dict[str, Dict[str, Any]] # Umbenannt
) -> Dict[str, str]:
    """Aggregiert alle LKN-Codes, die in den Bedingungen der übergebenen Pauschalen referenziert werden."""
    # print(f"--- DEBUG: Start get_LKNs_from_pauschalen_conditions für {potential_pauschale_codes} ---")
    condition_lkns_with_desc: Dict[str, str] = {}
    processed_lkn_codes: Set[str] = set()
    BED_PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'

    relevant_conditions = [
        cond for cond in pauschale_bedingungen_data_list # Verwende umbenannt
        if cond.get(BED_PAUSCHALE_KEY) in potential_pauschale_codes and
           cond.get(BED_TYP_KEY, "").upper() in [
               "LEISTUNGSPOSITIONEN IN LISTE", "LKN",
               "LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE"
           ]]
    # print(f"  Anzahl LKN-relevanter Bedingungen: {len(relevant_conditions)}")
    for cond in relevant_conditions:
        typ = cond.get(BED_TYP_KEY, "").upper(); wert = cond.get(BED_WERTE_KEY, "")
        if not wert: continue
        current_lkns_to_add: Set[str] = set()
        if typ in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN"]:
            current_lkns_to_add.update(lkn.strip().upper() for lkn in str(wert).split(',') if lkn.strip()) # str(wert)
        elif typ in ["LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE"]:
            for table_name in (t.strip() for t in str(wert).split(',') if t.strip()): # str(wert)
                content = get_table_content(table_name, "service_catalog", tabellen_dict) # Verwende umbenannt
                for item in content:
                    lkn_code = item.get('Code')
                    if lkn_code:
                        lkn_upper = str(lkn_code).upper() # str(lkn_code)
                        if lkn_upper not in processed_lkn_codes:
                            desc = item.get('Code_Text') or leistungskatalog.get(lkn_upper, {}).get('Beschreibung', 'N/A') # Verwende umbenannt
                            condition_lkns_with_desc[lkn_upper] = desc
                            processed_lkn_codes.add(lkn_upper)
        for lkn_upper in current_lkns_to_add:
            if lkn_upper not in processed_lkn_codes:
                desc = leistungskatalog.get(lkn_upper, {}).get('Beschreibung', 'N/A') # Verwende umbenannt
                condition_lkns_with_desc[lkn_upper] = desc
                processed_lkn_codes.add(lkn_upper)

    # Wenn WA.20-Leistungen enthalten sind, füge alle Codes aus der ANAST-Tabelle hinzu
    if any(code.startswith('WA.20.') for code in condition_lkns_with_desc):
        anast_entries = tabellen_dict.get('anast', []) + tabellen_dict.get('ANAST', [])
        for item in anast_entries:
            lkn_code = str(item.get('Code', '')).upper()
            if lkn_code and lkn_code not in processed_lkn_codes:
                desc = item.get('Code_Text') or leistungskatalog.get(lkn_code, {}).get('Beschreibung', 'N/A')
                condition_lkns_with_desc[lkn_code] = desc
                processed_lkn_codes.add(lkn_code)
    # print(f"  DEBUG (get_LKNs_from_pauschalen): {len(condition_lkns_with_desc)} einzigartige Bedingungs-LKNs gefunden.")
    return condition_lkns_with_desc

# get_pauschale_lkn_candidates: Diese Funktion war sehr ähnlich zu get_relevant_p_pz_condition_lkns.
# Ich habe sie entfernt, da get_LKNs_from_pauschalen_conditions alle LKNs holt und
# get_relevant_p_pz_condition_lkns spezifisch P/PZ filtert.
# Falls sie eine andere Logik hatte (z.B. alle Pauschalen durchsucht, nicht nur die potenziellen),
# müsste sie wiederhergestellt und angepasst werden.

def search_pauschalen(keyword: str) -> List[Dict[str, Any]]:
    """Suche in den Pauschalen nach dem Stichwort und liefere Code + LKNs."""
    if not keyword:
        return []

    def _tokenize(text: str) -> Set[str]:
        """Zerlegt Text in Kleinschreib-Tokens ohne Sonderzeichen."""
        return {t for t in re.findall(r"\w+", text.lower()) if t}

    normalized_query = " ".join(str(keyword).split())
    query_tokens = extract_keywords(normalized_query)
    if not query_tokens:
        query_tokens = {t for t in re.findall(r"\w+", normalized_query.lower()) if len(t) >= 3}
    if not query_tokens:
        query_tokens = {normalized_query.lower()}

    expanded_query_tokens: Set[str] = set()
    for token in query_tokens:
        lowered = token.lower()
        expanded_query_tokens.add(lowered)
        if SYNONYMS_ENABLED and synonym_catalog:
            for variant in expand_query(lowered, synonym_catalog):
                if isinstance(variant, str):
                    expanded_query_tokens.add(variant.lower())

    matches: List[Tuple[int, Dict[str, Any], Set[str]]] = []

    for code, data in pauschalen_dict.items():
        text_de = str(data.get("Pauschale_Text", "") or "")
        text_fr = str(data.get("Pauschale_Text_f", "") or "")
        text_it = str(data.get("Pauschale_Text_i", "") or "")
        searchable_blob = " ".join(part for part in [code, text_de, text_fr, text_it] if part)
        text_tokens = _tokenize(searchable_blob)
        matched_tokens: Set[str] = set()

        for token in expanded_query_tokens:
            if not token:
                continue
            if token in text_tokens:
                matched_tokens.add(token)
                continue
            if any(token in candidate for candidate in text_tokens if len(token) >= 3):
                matched_tokens.add(token)
                continue
            if token in searchable_blob.lower():
                matched_tokens.add(token)

        if not matched_tokens:
            continue

        lkns: Set[str] = set()
        for cond in pauschale_bedingungen_data:
            if cond.get("Pauschale") != code:
                continue
            typ = str(cond.get("Bedingungstyp", "")).upper()
            werte = cond.get("Werte", "")
            if not werte:
                continue
            if typ in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN"]:
                lkns.update(l.strip().upper() for l in str(werte).split(',') if l.strip())
            elif typ in ["LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE"]:
                for table_name in (t.strip() for t in str(werte).split(',') if t.strip()):
                    for item in get_table_content(table_name, "service_catalog", tabellen_dict_by_table):
                        code_item = item.get('Code')
                        if code_item:
                            lkns.add(str(code_item).upper())

        entry = {
            "code": code,
            "text": text_de,
            "lkns": sorted(lkns),
        }
        matches.append((len(matched_tokens), entry, matched_tokens))

    matches.sort(key=lambda item: (-item[0], item[1]["code"]))

    results: List[Dict[str, Any]] = []
    for score, entry, matched_tokens in matches:
        if entry["code"] == "C08.43A":
            logger.info(
                "Suchbegriff \"%s\" liefert Pauschale C08.43A (Tokens: %s, Score: %d)",
                normalized_query,
                sorted(matched_tokens),
                score,
            )
        elif logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "search_pauschalen Treffer %s (Score: %d, Tokens: %s) für Query '%s'",
                entry["code"],
                score,
                sorted(matched_tokens),
                normalized_query,
            )
        results.append(entry)

    return results

def search_chop(term: str, offset: int = 0, limit: int = 20) -> List[Dict[str, str]]:
    """Search CHOP data by code or German description with pagination."""
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 20

    term_lower = term.lower()
    results: List[Dict[str, str]] = []
    skipped = 0

    for item in chop_data:
        code = str(item.get("code", ""))
        desc = str(item.get("description_de", ""))
        extra = str(item.get("freitext_payload", ""))

        match = True
        if term_lower:
            match = (
                term_lower in code.lower()
                or term_lower in desc.lower()
                or term_lower in extra.lower()
            )

        if not match:
            continue

        if skipped < offset:
            skipped += 1
            continue

        results.append({"code": code, "description_de": desc, "freitext_payload": extra})

        if len(results) >= limit:
            break

    return results

def search_icd(term: str, lang: str = 'de', offset: int = 0, limit: int = 20) -> List[Dict[str, str]]:
    """Search ICD data in tabellen_data by code or description for a language with pagination."""
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 20

    lang = lang.lower() if lang in ['de', 'fr', 'it'] else 'de'
    term_lower = term.lower()
    results: List[Dict[str, str]] = []
    skipped = 0

    text_key = 'Code_Text' + {'de': '', 'fr': '_f', 'it': '_i'}.get(lang, '')

    for item in tabellen_data:
        if str(item.get('Tabelle_Typ', '')).lower() != 'icd':
            continue
        code = str(item.get('Code', ''))
        text = str(item.get(text_key, item.get('Code_Text', '')))
        table = str(item.get('Tabelle', ''))

        if term_lower and term_lower not in code.lower() and term_lower not in text.lower() and term_lower not in table.lower():
            continue

        if skipped < offset:
            skipped += 1
            continue

        results.append({'tabelle': str(item.get('Tabelle', '')), 'code': code, 'text': text})

        if len(results) >= limit:
            break

    return results


import threading

# Lock for sequential processing
processing_lock = threading.Lock()


def get_localized_text(details: Dict[str, Any], base: str, lang: str) -> Optional[str]:
    """Return the value of a base field for the requested language.

    Falls back to the German base field if the localized variant is missing.
    """
    suffix = {"de": "", "fr": "_f", "it": "_i"}.get(lang, "")
    key = f"{base}{suffix}"
    text = details.get(key)
    if text is None and suffix:
        text = details.get(base)
    return str(text) if text else None


def _parse_billing_request(request: "Request") -> Dict[str, Any]:
    """Parses and validates the billing analysis request payload."""
    if not request.is_json:
        raise ValueError("Request must be JSON")

    data = request.get_json(silent=True) or {}
    user_input = data.get('inputText', "")
    if isinstance(user_input, str):
        # Vereinheitliche typografische Apostrophe und Gravis, damit Suche/Synonyme greifen.
        user_input = user_input.replace("'", "'").replace("'", "'").replace("`", "'")
    if not user_input.strip():
        raise ValueError("'inputText' darf nicht leer sein")
    heuristic_demo: PatientDemographics = extract_patient_demographics(user_input)

    lang = data.get('lang', 'de')
    if lang not in ['de', 'fr', 'it']:
        lang = 'de'

    icd_input_raw = data.get('icd', [])
    medications_raw = data.get('medications')
    if medications_raw is None:
        medications_raw = data.get('medikamente')
    if medications_raw is None:
        medications_raw = data.get('gtin', [])

    icd_input = [str(i).strip().upper() for i in icd_input_raw if isinstance(i, str) and str(i).strip()]

    medication_inputs: List[str] = []
    if isinstance(medications_raw, str):
        raw_iterable = [medications_raw]
    elif isinstance(medications_raw, list):
        raw_iterable = medications_raw
    else:
        raw_iterable = []
    for token in raw_iterable:
        if not isinstance(token, str):
            token = str(token)
        token_clean = token.strip()
        if token_clean:
            medication_inputs.append(token_clean)

    medication_atcs, unresolved_medications = resolve_medication_inputs(medication_inputs)
    if unresolved_medications:
        logger.info("Nicht zuordenbare Medikamentenangaben: %s", unresolved_medications)

    use_icd_flag_raw = data.get('useIcd')
    if use_icd_flag_raw is None:
        # Standard: Nur dann streng nach ICD prüfen, wenn tatsächlich Codes übergeben wurden.
        # Ohne ICD-Angaben würden Pauschalen mit obligatorischen ICD-Bedingungen sonst
        # systematisch scheitern (z.B. Hallux-Valgus-Operationen).
        use_icd_flag = bool(icd_input)
    else:
        # Nutzer*innen können die Prüfung explizit steuern (z.B. über Checkbox im UI).
        # Akzeptiere auch String-Werte wie "true"/"false" oder "1"/"0".
        if isinstance(use_icd_flag_raw, str):
            use_icd_flag = use_icd_flag_raw.strip().lower() in {"1", "true", "ja", "yes"}
        else:
            use_icd_flag = bool(use_icd_flag_raw)

    if use_icd_flag and not icd_input:
        # Eine explizite ICD-Prüfung ohne übergebene ICD-Codes führt zwangsläufig dazu,
        # dass jede Pauschale mit Diagnosen-Anforderungen scheitert. Das tritt in der
        # Praxis auf, wenn Frontends den Standardwert "True" mitsenden. In diesem Fall
        # schalten wir die ICD-Prüfung defensiv aus und loggen die Anpassung.
        logger.info("ICD-Prüfung deaktiviert, da keine ICD-Codes übermittelt wurden (useIcd-Flag=%s).", use_icd_flag_raw)
        use_icd_flag = False
    age_input = data.get('age')
    gender_input = data.get('gender')

    try:
        alter_user = int(age_input) if age_input is not None and str(age_input).strip() else None
    except (ValueError, TypeError):
        logger.warning(f"Ungueltiger Alterswert '{age_input}'.")
        alter_user = None

    geschlecht_user_raw = str(gender_input).lower().strip() if isinstance(gender_input, str) else None
    if geschlecht_user_raw and geschlecht_user_raw in ['männlich', 'weiblich', 'divers', 'unbekannt']:
        geschlecht_user = geschlecht_user_raw
    else:
        if geschlecht_user_raw:
            logger.warning(f"Ungueltiger Geschlechtswert '{gender_input}'.")
        geschlecht_user = None

    return {
        "user_input": user_input,
        "lang": lang,
        "icd_input": icd_input,
        "medication_inputs": medication_inputs,
        "medication_atcs": medication_atcs,
        "use_icd_flag": use_icd_flag,
        "alter_user": alter_user,
        "geschlecht_user": geschlecht_user,
        "demographics_heuristic": heuristic_demo,
    }


def _build_context_for_llm(user_input: str, lang: str) -> tuple[str, list[tuple[float, str]], list[str]]:
    """
    Performs hybrid search to find relevant LKNs and builds the context for the LLM.
    Returns the context string, top ranking results, and query variants.
    """
    # Nutzung der global definierten MAX_*/MIN_* Konstanten siehe Modulkopf.

    def _normalize_query_variants(
        primary_variant: str,
        candidates: List[str],
    ) -> List[str]:
        """Deduplicate and cap the list of variants while keeping the primary variant."""
        seen: Set[str] = set()
        normalized: List[str] = []
        primary_lower = primary_variant.lower() if isinstance(primary_variant, str) else ""

        def _try_add(value: str) -> None:
            """Übernimmt Varianten, wenn sie neu sind und die Längenbegrenzung einhalten."""
            if not isinstance(value, str):
                return
            stripped = value.strip()
            if not stripped:
                return
            key = stripped.lower()
            if key in seen:
                return
            if len(stripped) > MAX_VARIANT_LENGTH and key != primary_lower:
                return
            seen.add(key)
            normalized.append(stripped)

        if isinstance(primary_variant, str):
            _try_add(primary_variant)

        for cand in candidates:
            if len(normalized) >= MAX_QUERY_VARIANTS:
                break
            _try_add(cand)
        return normalized[:MAX_QUERY_VARIANTS]

    def _ordered_keyword_tokens(text: str) -> List[str]:
        """Extrahiert eindeutige Keyword-Tokens in Reihenfolge ihres Auftretens."""
        ordered_tokens: List[str] = []
        seen_tokens: Set[str] = set()
        if not isinstance(text, str):
            return ordered_tokens
        expanded = expand_compound_words(text)
        for match in re.finditer(r"\b\w+\b", expanded.lower()):
            token = match.group(0)
            if len(token) < 4 or token in STOPWORDS:
                continue
            if token not in seen_tokens:
                seen_tokens.add(token)
                ordered_tokens.append(token)
        return ordered_tokens

    katalog_context_parts = []
    prompt_synonym_entries: List[Tuple[str, str]] = []
    prompt_synonym_seen: Set[str] = set()
    catalog_description_variant_keys: Set[str] = set(catalog_description_lookup)

    def _register_prompt_synonym(candidate: str) -> None:
        """Speichert Synonymvarianten für die spätere Aufnahme in den Prompt."""
        if not isinstance(candidate, str):
            return
        normalized_candidate = " ".join(candidate.split())
        if not normalized_candidate:
            return
        key = normalized_candidate.lower()
        if key in prompt_synonym_seen:
            return
        prompt_synonym_seen.add(key)
        prompt_synonym_entries.append((normalized_candidate, key))
    preprocessed_input = expand_compound_words(user_input)
    demographics_hint: PatientDemographics = extract_patient_demographics(user_input)
    synonym_seed_input = preprocessed_input
    demographic_seed_terms = _build_demographic_seed_terms(demographics_hint)
    if demographic_seed_terms:
        extra_terms = " ".join(dict.fromkeys(demographic_seed_terms))
        synonym_seed_input = f"{synonym_seed_input} {extra_terms}".strip()
    query_variants: List[str] = [synonym_seed_input]
    seed_top_codes: List[str] = []
    base_keyword_tokens = extract_keywords(synonym_seed_input)
    if base_keyword_tokens:
        seed_keyword_results = cast(
            List[Tuple[float, str]],
            rank_leistungskatalog_entries(
                base_keyword_tokens,
                leistungskatalog_dict,
                token_doc_freq,
                limit=SEED_KEYWORD_RESULT_LIMIT,
                return_scores=True,
            ),
        )
        seed_top_codes = [
            code for _, code in seed_keyword_results[:KEYWORD_VARIANT_DESCRIPTION_LIMIT]
        ]
        if seed_top_codes:
            lang_desc_field_map = {
                "de": "Beschreibung",
                "fr": "Beschreibung_f",
                "it": "Beschreibung_i",
            }
            desc_field = lang_desc_field_map.get(lang, "Beschreibung")
            for candidate_code in seed_top_codes:
                details = leistungskatalog_dict.get(candidate_code, {})
                if not isinstance(details, dict):
                    continue
                for field in (desc_field, "Beschreibung"):
                    value = details.get(field)
                    if not isinstance(value, str):
                        continue
                    cleaned = " ".join(value.split())
                    if not cleaned or len(cleaned) > MAX_VARIANT_LENGTH:
                        continue
                    query_variants.append(cleaned)
                    catalog_description_variant_keys.add(cleaned.lower())
    direct_synonym_codes: List[str] = []
    if SYNONYMS_ENABLED:
        candidate_bases: List[str] = []
        base_candidates = []
        for candidate in [preprocessed_input, synonym_seed_input]:
            if candidate and candidate not in base_candidates:
                base_candidates.append(candidate)
        for base_candidate in base_candidates:
            normalized = " ".join(base_candidate.lower().split())
            if base_candidate in synonym_catalog.entries and base_candidate not in candidate_bases:
                candidate_bases.append(base_candidate)
            for base in synonym_catalog.index.get(normalized, []):
                if base not in candidate_bases:
                    candidate_bases.append(base)

        code_set: Set[str] = set()
        for base in candidate_bases:
            entry = synonym_catalog.entries.get(base)
            if not entry:
                continue
            for code in entry.lkns:
                code_norm = code.strip().upper()
                if code_norm:
                    code_set.add(code_norm)
        if code_set:
            direct_synonym_codes = sorted(code_set)
            logger.info(
                "Direkter Synonym-Treffer: '%s' -> %s",
                synonym_seed_input,
                direct_synonym_codes,
            )

    if SYNONYMS_ENABLED:
        try:
            # expand_query now returns a list, not a dict
            expanded_variants = expand_query(
                synonym_seed_input,
                synonym_catalog,
                lang=lang,
            )
            base_prompt_key = (
                " ".join(synonym_seed_input.split()).lower()
                if isinstance(synonym_seed_input, str)
                else ""
            )
            for variant in expanded_variants:
                if not isinstance(variant, str):
                    continue
                normalized_variant = " ".join(variant.split())
                if (
                    not normalized_variant
                    or len(normalized_variant) > MAX_VARIANT_LENGTH
                ):
                    continue
                key = normalized_variant.lower()
                if key == base_prompt_key or key in catalog_description_variant_keys:
                    continue
                _register_prompt_synonym(normalized_variant)
            query_variants = _normalize_query_variants(
                synonym_seed_input,
                query_variants + expanded_variants,
            )
        except Exception as e:
            logger.warning("Synonym expansion failed: %s", e)
            query_variants = _normalize_query_variants(
                synonym_seed_input,
                query_variants,
            )

        # If the full Eingabetext selbst kein Synonym ist, erweitere auf Token-Ebene.
        lower_seen_variants = {
            str(variant).lower(): str(variant)
            for variant in query_variants
            if isinstance(variant, str)
        }
        token_candidate_order: List[str] = []

        def _extend_token_candidates(source: str) -> None:
            """Fügt Keyword-Tokens aus einer Quelle für spätere Synonymerkennung hinzu."""
            try:
                for token in _ordered_keyword_tokens(source):
                    if token not in token_candidate_order:
                        token_candidate_order.append(token)
            except Exception as token_err:
                logger.debug(
                    "Keyword extraction for synonym expansion failed: %s",
                    token_err,
                )

        _extend_token_candidates(synonym_seed_input)
        _extend_token_candidates(preprocessed_input)

        token_variant_budget = MAX_TOKEN_VARIANT_ADDITIONS
        for token in token_candidate_order:
            if token_variant_budget <= 0 or len(query_variants) >= MAX_QUERY_VARIANTS:
                break
            if not isinstance(token, str) or len(token) < 4:
                continue
            try:
                token_variants = expand_query(token, synonym_catalog, lang=lang)
            except Exception as exp_err:
                logger.debug("Token-based synonym expansion failed for '%s': %s", token, exp_err)
                continue

            has_additional_variant = any(
                isinstance(variant, str)
                and variant.strip()
                and variant.lower() not in lower_seen_variants
                and variant.lower() != token.lower()
                for variant in token_variants
            )
            if not has_additional_variant:
                continue

            for variant in token_variants:
                if (
                    token_variant_budget <= 0
                    or len(query_variants) >= MAX_QUERY_VARIANTS
                ):
                    break
                if not isinstance(variant, str):
                    continue
                normalized_variant = variant.strip()
                if (
                    not normalized_variant
                    or len(normalized_variant) > MAX_VARIANT_LENGTH
                ):
                    continue
                key = normalized_variant.lower()
                if key in lower_seen_variants or key == token.lower():
                    continue
                query_variants.append(normalized_variant)
                lower_seen_variants[key] = normalized_variant
                if key not in catalog_description_variant_keys:
                    _register_prompt_synonym(normalized_variant)
                token_variant_budget -= 1
                if token_variant_budget <= 0:
                    break

        query_variants = _normalize_query_variants(
            query_variants[0] if query_variants else synonym_seed_input,
            query_variants,
        )

    synonym_hint_codes: Set[str] = set(direct_synonym_codes)
    if SYNONYMS_ENABLED and synonym_catalog:
        for variant in query_variants:
            if not isinstance(variant, str):
                continue
            normalized_variant = " ".join(variant.lower().split())
            base_terms = list(synonym_catalog.index.get(normalized_variant, []))
            if not base_terms and variant in synonym_catalog.entries:
                base_terms.append(variant)
            for base_term in base_terms:
                entry = synonym_catalog.entries.get(base_term)
                if not entry:
                    continue
                for code in entry.lkns:
                    normalized_code = str(code).strip().upper()
                    if normalized_code:
                        synonym_hint_codes.add(normalized_code)
    demographic_matches = _match_codes_for_demographics(demographics_hint)
    if demographic_matches:
        synonym_hint_codes.update(demographic_matches)
        logger.debug("Demografie-Hinweise fügten Kandidaten hinzu: %s", sorted(demographic_matches))
    for candidate_code in seed_top_codes:
        normalized_code = str(candidate_code).strip().upper()
        if normalized_code:
            synonym_hint_codes.add(normalized_code)

    if preprocessed_input not in query_variants:
        query_variants.append(preprocessed_input)

    keyword_token_set: Set[str] = set()
    for _q in query_variants:
        keyword_token_set.update(extract_keywords(_q))

    # Für die Embedding-Suche nur den vorverarbeiteten Input verwenden
    embedding_query = preprocessed_input
    logger.info(
        "Embedding-Anfrage ohne Synonym-Erweiterung: '%s'",
        embedding_query,
    )

    # --- HYBRID SEARCH: Combine Keyword and Embedding search results ---

    # 1. Keyword-based search (reliable for synonyms and direct matches)
    # We limit this to a reasonable number to get high-quality candidates.
    keyword_results = cast(
        List[Tuple[float, str]],
        rank_leistungskatalog_entries(
            keyword_token_set,
            leistungskatalog_dict,
            token_doc_freq,
            limit=100,
            return_scores=True,
        ),
    )
    keyword_codes = [code for _, code in keyword_results]
    logger.info(f"Keyword-Suche fand {len(keyword_codes)} Kandidaten.")
    keyword_focus_limit = max(KEYWORD_PRIORITY_LIMIT, KEYWORD_VARIANT_DESCRIPTION_LIMIT)
    keyword_top_codes = [code for _, code in keyword_results[:keyword_focus_limit]]
    for candidate_code in keyword_top_codes:
        normalized_code = str(candidate_code).strip().upper()
        if normalized_code:
            synonym_hint_codes.add(normalized_code)
    direct_synonym_codes = sorted(synonym_hint_codes)

    # 2. Embedding-based search (for semantic similarity)
    embedding_results: List[Tuple[float, str]] = []
    embedding_codes_ranked: List[str] = []
    if USE_RAG and embedding_model and faiss_index:
        logger.info(
            "Suchanfrage für RAG (ohne Synonym-Erweiterung): %s",
            embedding_query,
        )
        max_tokens = getattr(embedding_model, "get_max_seq_length", lambda: 128)()
        tokenizer_max = getattr(embedding_model.tokenizer, "model_max_length", max_tokens)
        limit = min(max_tokens, tokenizer_max)
        special_tokens = getattr(
            embedding_model.tokenizer, "num_special_tokens_to_add", lambda *a, **k: 0
        )(False)
        limit = max(limit - special_tokens, 0)
        embedding_token_ids = embedding_model.tokenizer.encode(
            embedding_query, add_special_tokens=False
        )
        if len(embedding_token_ids) > limit:
            embedding_query = embedding_model.tokenizer.decode(
                embedding_token_ids[:limit]
            ).strip()
        q_vec = embedding_model.encode(
            [embedding_query], convert_to_numpy=True
        )[0]

        embedding_results = rank_embeddings_entries(
            q_vec,
            faiss_index,
            embedding_codes,
            limit=100,
        )
        embedding_codes_ranked = [code for _, code in embedding_results]
        logger.info(
            f"Embedding-Suche (RAG) fand {len(embedding_codes_ranked)} Kandidaten."
        )

    # 3. Combine and de-duplicate results
    # The order is important: direct codes first, then keyword matches, then semantic matches.
    direct_codes_from_input = [c.upper() for c in extract_lkn_codes_from_text(user_input)]
    direct_codes = list(direct_codes_from_input)
    for code in direct_synonym_codes:
        if code not in direct_codes:
            direct_codes.append(code)
    synonym_only_codes = [
        code for code in direct_synonym_codes if code not in direct_codes_from_input
    ]

    combined_codes = direct_codes + keyword_codes + embedding_codes_ranked
    ranked_codes = list(dict.fromkeys(combined_codes))  # De-duplicate while preserving order
    extra_variant_codes: List[str] = []
    target_shortfall = (
        len(ranked_codes) < MIN_RANKED_CODE_TARGET
        or len(keyword_results) < MIN_KEYWORD_RESULTS
    )
    if target_shortfall and query_variants:
        logger.debug(
            "Starte zusätzliche Variantensuche: %s Basis-Kandidaten, %s Keyword-Ergebnisse.",
            len(ranked_codes),
            len(keyword_results),
        )
        for variant in query_variants[:EXTRA_VARIANT_SEARCH_LIMIT]:
            variant_tokens = extract_keywords(variant)
            if not variant_tokens:
                continue
            variant_results = cast(
                List[Tuple[float, str]],
                rank_leistungskatalog_entries(
                    variant_tokens,
                    leistungskatalog_dict,
                    token_doc_freq,
                    limit=EXTRA_VARIANT_RESULT_LIMIT,
                    return_scores=True,
                ),
            )
            for _, code in variant_results:
                if code in ranked_codes or code in extra_variant_codes:
                    continue
                extra_variant_codes.append(code)
                if len(ranked_codes) + len(extra_variant_codes) >= MIN_RANKED_CODE_TARGET:
                    break
            if len(ranked_codes) + len(extra_variant_codes) >= MIN_RANKED_CODE_TARGET:
                break
        if extra_variant_codes:
            ranked_codes.extend(extra_variant_codes)
            logger.info(
                "Fallback-Suche pro Variante ergänzte %s zusätzliche Kandidaten.",
                len(extra_variant_codes),
            )

    logger.info(
        f"Kombinierte Suche ergab {len(ranked_codes)} einzigartige Kandidaten für den Kontext."
    )
    # --- DEBUGGING START ---
    logger.debug(f"DEBUG: ranked_codes: {ranked_codes[:10]}")  # Logge die ersten 10 gerankten Codes
    # --- DEBUGGING END ---

    # Build top ranking list prioritizing direct matches but including keyword hits even with RAG
    top_ranking_results = []
    seen_rank_codes: Set[str] = set()

    def _add_direct_codes(codes: List[str]) -> None:
        """Fügt direkt erkannte Codes mit Höchstscore zur Rankingliste hinzu."""
        for direct_code in codes:
            normalized = direct_code.strip().upper()
            if not normalized or normalized in seen_rank_codes:
                continue
            top_ranking_results.append((1.0, normalized))
            seen_rank_codes.add(normalized)

    def _add_scored_entries(entries: List[Tuple[float, str]]) -> None:
        """Fügt Code/Score-Paare hinzu, wenn sie noch nicht gerankt wurden."""
        for score, code in entries:
            normalized = code.strip().upper()
            if not normalized or normalized in seen_rank_codes:
                continue
            top_ranking_results.append((score, normalized))
            seen_rank_codes.add(normalized)

    priority_keyword_entries = (
        keyword_results[:KEYWORD_PRIORITY_LIMIT]
        if KEYWORD_PRIORITY_LIMIT > 0
        else keyword_results
    )
    remaining_keyword_entries = (
        keyword_results[KEYWORD_PRIORITY_LIMIT:]
        if KEYWORD_PRIORITY_LIMIT > 0
        else []
    )
    synonym_rank_hints = (
        synonym_only_codes[:MAX_DIRECT_SYNONYM_RANK_HINTS]
        if MAX_DIRECT_SYNONYM_RANK_HINTS > 0
        else synonym_only_codes
    )

    _add_direct_codes(direct_codes_from_input)
    if priority_keyword_entries:
        _add_scored_entries(priority_keyword_entries)
    if synonym_rank_hints:
        _add_direct_codes(synonym_rank_hints)
    if remaining_keyword_entries:
        _add_scored_entries(remaining_keyword_entries)
    if USE_RAG and embedding_model and faiss_index:
        _add_scored_entries(embedding_results)
    if extra_variant_codes:
        for code in extra_variant_codes:
            normalized = code.strip().upper()
            if not normalized or normalized in seen_rank_codes:
                continue
            top_ranking_results.append((0.05, normalized))
            seen_rank_codes.add(normalized)

    def _collect_code_text(code: str) -> str:
        """Fasst alle Textfelder einer LKN zu einem Suchstring zusammen."""
        details = leistungskatalog_dict.get(code)
        if not isinstance(details, dict):
            return ""
        collected_parts: List[str] = []
        for value in details.values():
            if isinstance(value, str):
                collected_parts.append(value.lower())
            elif isinstance(value, list):
                collected_parts.extend(str(v).lower() for v in value if v is not None)
            elif isinstance(value, dict):
                collected_parts.extend(
                    str(v).lower()
                    for v in value.values()
                    if isinstance(v, str)
                )
        return " ".join(collected_parts)

    # Apply a generic keyword-based post-filter to prioritise codes mentioning the query terms
    meaningful_tokens = {
        tok.lower().strip()
        for tok in keyword_token_set
        if isinstance(tok, str) and tok.strip() and len(tok.strip()) >= 3
    }

    if meaningful_tokens:
        filtered_results = [
            entry
            for entry in top_ranking_results
            if any(token in _collect_code_text(entry[1]) for token in meaningful_tokens)
        ]
        if filtered_results:
            logger.info(
                "Schlüsselwortbasierte Nachfilterung: %s von %s Kandidaten behalten.",
                len(filtered_results),
                len(top_ranking_results),
            )
            top_ranking_results = filtered_results

    top_ranking_results = top_ranking_results[:5]

    # Baue den Kontext: erzwungene Codes zuerst, dann restliche Kandidaten, optional begrenzt
    included: set[str] = set()
    med_info_candidates: List[str] = []

    def _shorten_text(value: str, max_length: int = 220) -> str:
        """Kürzt Beschreibungen auf eine kompakte Ein-Zeilen-Darstellung."""
        collapsed = " ".join(str(value).split())
        if len(collapsed) <= max_length:
            return collapsed
        return collapsed[: max_length - 1].rstrip() + "…"

    def _add_line_for(code: str) -> None:
        """Fügt Kontextzeilen für einen Code hinzu und trackt eingebundene Einträge."""
        details = leistungskatalog_dict.get(code, {})
        desc_text = get_localized_text(details, "Beschreibung", lang)
        mi_text = get_localized_text(details, "MedizinischeInterpretation", lang)
        parts = [f"LKN: {code}"]
        if CONTEXT_INCLUDE_TYP:
            parts.append(f"Typ: {details.get('Typ', 'N/A')}")
        if CONTEXT_INCLUDE_BESCHREIBUNG:
            parts.append(f"Beschreibung: {html.escape(desc_text or 'N/A')}")
        line = ", ".join(parts)
        if CONTEXT_INCLUDE_MED_INTERPRETATION and mi_text:
            line += f", MedizinischeInterpretation: {html.escape(mi_text)}"
        elif mi_text:
            med_info_candidates.append(
                f"LKN: {code}, MedizinischeInterpretation: {html.escape(_shorten_text(mi_text))}"
            )
        demo_line = _format_tardoc_demographics(code, lang)
        if demo_line:
            line += f", Demografie: {html.escape(demo_line)}"
        katalog_context_parts.append(line)
        included.add(code)

    # 1) Erzwinge bestimmte Codes
    for forced in CONTEXT_FORCE_INCLUDE_CODES:
        if forced in leistungskatalog_dict and forced not in included:
            _add_line_for(forced)
            if CONTEXT_MAX_ITEMS and len(katalog_context_parts) >= CONTEXT_MAX_ITEMS:
                break

    # 2) Fülle mit gerankten Kandidaten auf
    if not (CONTEXT_MAX_ITEMS and len(katalog_context_parts) >= CONTEXT_MAX_ITEMS):
        for lkn_code in ranked_codes:
            if lkn_code in included:
                continue
            if lkn_code not in leistungskatalog_dict:
                continue
            _add_line_for(lkn_code)
            if CONTEXT_MAX_ITEMS and len(katalog_context_parts) >= CONTEXT_MAX_ITEMS:
                break
    katalog_context_str = "\n".join(katalog_context_parts)
    current_token_count = count_tokens(katalog_context_str)
    if (
        not CONTEXT_INCLUDE_MED_INTERPRETATION
        and med_info_candidates
        and current_token_count < MIN_CONTEXT_TOKEN_THRESHOLD
    ):
        katalog_context_parts.extend(med_info_candidates[:MAX_FALLBACK_MED_LINES])
        katalog_context_str = "\n".join(katalog_context_parts)
        current_token_count = count_tokens(katalog_context_str)
        logger.info(
            "Medizinische Interpretation als Fallback ergänzt (%s zusätzliche Zeilen).",
            min(len(med_info_candidates), MAX_FALLBACK_MED_LINES),
        )
    logger.info("Tokens im Katalog-Kontext dieses Requests: %s", current_token_count)
    # --- DEBUGGING START ---
    logger.debug(f"DEBUG: len(katalog_context_str): {len(katalog_context_str)}")
    if not katalog_context_str:
        logger.error("DEBUG: katalog_context_str ist leer. Abbruch vor LLM-Aufruf.")
    # --- DEBUGGING END ---
    if not katalog_context_str:
        raise ValueError("Leistungskatalog für LLM-Kontext (Stufe 1) ist leer.")

    normalized_query_keys = {
        " ".join(str(value).split()).lower()
        for value in query_variants
        if isinstance(value, str) and str(value).strip()
    }

    filtered_prompt_synonyms: List[str] = []
    for display_value, key in prompt_synonym_entries:
        if key not in normalized_query_keys:
            continue
        if key in catalog_description_variant_keys:
            continue
        filtered_prompt_synonyms.append(display_value)
        if len(filtered_prompt_synonyms) >= MAX_PROMPT_SYNONYMS:
            break

    prompt_base = (
        " ".join(synonym_seed_input.split())
        if isinstance(synonym_seed_input, str)
        else ""
    )
    prompt_variants: List[str] = []
    if filtered_prompt_synonyms:
        if prompt_base:
            prompt_variants.append(prompt_base)
        prompt_variants.extend(filtered_prompt_synonyms)
    elif prompt_base:
        prompt_variants = [prompt_base]

    return katalog_context_str, top_ranking_results, prompt_variants


def _validate_and_apply_rules(
    llm_stage1_result: Dict[str, Any],
    lang: str,
    icd_input: List[str],
    medication_atcs: List[str],
    alter_user: Optional[int],
    alter_operator: Optional[str],
    geschlecht_user: Optional[str],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Vergleicht LLM-Vorschläge mit Katalog und Regelwerk.

    Es werden zwei parallele Strukturen zurückgegeben: eine Liste der
    regelkonformen Leistungen (inklusive angepasster Mengen) sowie ein ausführlich
    pro LKN dokumentierter Datensatz mit allen angewendeten Regeln,
    übersetzten Meldungen und finaler Menge. Diese Informationen speisen das
    HTML-Protokoll in der Oberfläche.
    """
    final_validated_llm_leistungen: List[Dict[str, Any]] = []
    for leistung_llm in llm_stage1_result.get("identified_leistungen", []):
        lkn_llm_val = leistung_llm.get("lkn")
        if not isinstance(lkn_llm_val, str): continue
        lkn_llm = lkn_llm_val.strip().upper()
        if not lkn_llm: continue

        menge_llm = leistung_llm.get("menge", 1)
        local_lkn_data = leistungskatalog_dict.get(lkn_llm)
        if local_lkn_data:
            final_validated_llm_leistungen.append({
                "lkn": lkn_llm,
                "typ": local_lkn_data.get("Typ", leistung_llm.get("typ", "N/A")),
                "beschreibung": local_lkn_data.get("Beschreibung", leistung_llm.get("beschreibung", "N/A")),
                "menge": menge_llm
            })
        else:
            logger.warning(
                "Vom LLM (Stufe 1) identifizierte LKN '%s' nicht im lokalen Katalog. Wird ignoriert.",
                lkn_llm,
            )
    llm_stage1_result["identified_leistungen"] = final_validated_llm_leistungen
    logger.info("%s LKNs nach LLM Stufe 1 und lokaler Katalogvalidierung.", len(final_validated_llm_leistungen))

    regel_ergebnisse_details_list: List[Dict[str, Any]] = []
    rule_checked_leistungen_list: List[Dict[str, Any]] = []
    if not final_validated_llm_leistungen:
        msg_none = translate_rule_error_message("Keine LKN vom LLM identifiziert/validiert.", lang)
        regel_ergebnisse_details_list.append({"lkn": None, "initiale_menge": 0, "regelpruefung": {"abrechnungsfaehig": False, "fehler": [msg_none]}, "finale_menge": 0})
    else:
        alle_lkn_codes_fuer_regelpruefung = [str(l.get("lkn")) for l in final_validated_llm_leistungen if l.get("lkn")]
        typen_map_fuer_regeln = {
            str(l.get("lkn")).upper(): str(l.get("typ") or "").upper()
            for l in final_validated_llm_leistungen
            if l.get("lkn")
        }
        for leistung_data in final_validated_llm_leistungen:
            lkn_code_val = leistung_data.get("lkn")
            if not isinstance(lkn_code_val, str): continue
            lkn_code = lkn_code_val

            menge_initial_val = leistung_data.get("menge", 1)
            regel_ergebnis_dict: Dict[str, Any] = {"abrechnungsfaehig": False, "fehler": ["Regelprüfung nicht durchgeführt."]}
            finale_menge_nach_regeln = 0
            if rp_lkn_module and hasattr(rp_lkn_module, 'pruefe_abrechnungsfaehigkeit') and regelwerk_dict:
                lkn_code_upper = lkn_code.upper()
                leistung_typ = typen_map_fuer_regeln.get(lkn_code_upper, "")
                begleit_lkns_upper = [b_lkn.upper() for b_lkn in alle_lkn_codes_fuer_regelpruefung if b_lkn and b_lkn.upper() != lkn_code_upper]
                begleit_typen_context = {
                    code: typ
                    for code, typ in typen_map_fuer_regeln.items()
                    if code != lkn_code_upper
                }
                abrechnungsfall_kontext = {
                    "LKN": lkn_code_upper, "Menge": menge_initial_val,
                    "Typ": leistung_typ,
                    "Begleit_LKNs": begleit_lkns_upper,
                    "Begleit_Typen": begleit_typen_context,
                    "ICD": icd_input,
                    "Geschlecht": geschlecht_user or "unbekannt",
                    "Alter": alter_user,
                    "AlterOperator": alter_operator,
                    "Pauschalen": [], "Medikamente": medication_atcs, "GTIN": medication_atcs
                }
                try:
                    regel_ergebnis_dict = rp_lkn_module.pruefe_abrechnungsfaehigkeit(abrechnungsfall_kontext, regelwerk_dict)
                    if regel_ergebnis_dict.get("abrechnungsfaehig"):
                        finale_menge_nach_regeln = menge_initial_val
                    else:
                        fehler_liste_regel = regel_ergebnis_dict.get("fehler", [])
                        # Manche Regeln reduzieren nur die Menge statt die Position komplett zu sperren.
                        mengen_reduktions_fehler = next((f for f in fehler_liste_regel if "Menge auf" in f and "reduziert" in f), None)
                        if mengen_reduktions_fehler:
                            match_menge = re.search(r"Menge auf (\d+)", str(mengen_reduktions_fehler))
                            if match_menge:
                                try:
                                    finale_menge_nach_regeln = int(match_menge.group(1))
                                    regel_ergebnis_dict["abrechnungsfaehig"] = True
                                    logger.info(
                                        "Menge für LKN %s durch Regelprüfer auf %s angepasst.",
                                        lkn_code,
                                        finale_menge_nach_regeln,
                                    )
                                except ValueError:
                                    finale_menge_nach_regeln = 0
                        else:
                            # Alternativ meldet der Regelprüfer die zulässige Maximalmenge über eine Soft-Fehlermeldung.
                            mengenbesch_fehler = next((f for f in fehler_liste_regel if "Mengenbeschränkung überschritten" in f and "max." in f), None)
                            if mengenbesch_fehler:
                                match_max = re.search(r"max\.\s*(\d+)", str(mengenbesch_fehler))
                                if match_max:
                                    try:
                                        finale_menge_nach_regeln = int(match_max.group(1))
                                        regel_ergebnis_dict["abrechnungsfaehig"] = True
                                        regel_ergebnis_dict.setdefault("fehler", []).append(
                                            f"Menge auf {finale_menge_nach_regeln} reduziert (Mengenbeschränkung)"
                                        )
                                        logger.info(
                                            "Menge für LKN %s automatisch auf %s reduziert wegen Mengenbeschränkung.",
                                            lkn_code,
                                            finale_menge_nach_regeln,
                                        )
                                    except ValueError:
                                        finale_menge_nach_regeln = 0
                        if finale_menge_nach_regeln == 0:
                            logger.info(
                                "LKN %s nicht abrechnungsfähig wegen Regel(n): %s",
                                lkn_code,
                                regel_ergebnis_dict.get('fehler', []),
                            )
                except Exception as e_rule:
                    logger.error("Fehler bei Regelprüfung für LKN %s: %s", lkn_code, e_rule)
                    traceback.print_exc()
                    regel_ergebnis_dict = {"abrechnungsfaehig": False, "fehler": [f"Interner Fehler bei Regelprüfung: {e_rule}"]}
            else:
                logger.warning("Keine Regelprüfung für LKN %s durchgeführt (Regelprüfer oder Regelwerk fehlt).", lkn_code)
                regel_ergebnis_dict = {"abrechnungsfaehig": False, "fehler": ["Regelprüfung nicht verfügbar."]}
            
            if lang in ["fr", "it"]:
                regel_ergebnis_dict["fehler"] = [translate_rule_error_message(m, lang) for m in regel_ergebnis_dict.get("fehler", [])]

            regel_ergebnisse_details_list.append({"lkn": lkn_code, "initiale_menge": menge_initial_val, "regelpruefung": regel_ergebnis_dict, "finale_menge": finale_menge_nach_regeln})
            if regel_ergebnis_dict.get("abrechnungsfaehig") and finale_menge_nach_regeln > 0:
                rule_checked_leistungen_list.append({**leistung_data, "menge": finale_menge_nach_regeln})

    logger.info(
        "Regelkonforme Leistungen für Pauschalenprüfung: %s",
        [f"{l['lkn']} (Menge {l['menge']})" for l in rule_checked_leistungen_list],
    )
    return rule_checked_leistungen_list, regel_ergebnisse_details_list



def _get_tables_for_context_lkn(lkn: str) -> List[str]:
    """Return list of table names that contain the given LKN."""
    normalized = str(lkn or "").strip().upper()
    return lkn_to_tables_index.get(normalized, [])


def find_potential_pauschalen(lkn_codes: Set[str]) -> Set[str]:
    """Liefert Pauschalen-Kandidaten basierend auf LKN- und Tabellen-Indizes."""
    candidates: Set[str] = set()
    for raw_code in lkn_codes:
        if not isinstance(raw_code, str):
            continue
        lkn_code = raw_code.strip().upper()
        if not lkn_code:
            continue
        if lkn_code in pauschale_lp_index_by_lkn:
            candidates.update(pauschale_lp_index_by_lkn[lkn_code])
        if lkn_code in pauschale_cond_lkn_index_by_lkn:
            candidates.update(pauschale_cond_lkn_index_by_lkn[lkn_code])
        for table_name in _get_tables_for_context_lkn(lkn_code):
            table_norm = str(table_name).lower()
            if table_norm in pauschale_cond_table_index_by_table:
                candidates.update(pauschale_cond_table_index_by_table[table_norm])
    return {pc for pc in candidates if pc in pauschalen_dict}

def _determine_final_billing(
    rule_checked_leistungen_list: List[Dict[str, Any]],
    regel_ergebnisse_details_list: List[Dict[str, Any]],
    user_input: str,
    lang: str,
    context: Dict[str, Any],
    token_usage: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Führt Regelresultate mit der Pauschalenlogik zusammen und erzeugt die Antwort.

    Die Funktion entscheidet, ob eine Pauschalenprüfung nötig ist, ruft bei Bedarf
    Mapping/Ranking der Stufe 2 auf und fällt andernfalls auf die reine
    TARDOC-Auswertung zurück. Sie liefert das JSON für den HTTP-Response sowie
    Zusatzdaten aus der Mapping-Stufe für die Detailanzeige im Frontend.
    """
    llm_stage2_mapping_results: Dict[str, Any] = {"mapping_results": []}

    # Kandidaten aus Indizes (auch wenn keine P/PZ LKNs explizit vorhanden sind)
    potential_pauschale_codes_set: Set[str] = set()
    regelkonforme_lkn_codes_fuer_suche = {str(l.get('lkn')).upper() for l in rule_checked_leistungen_list if l.get('lkn')}
    potential_pauschale_codes_set.update(find_potential_pauschalen(regelkonforme_lkn_codes_fuer_suche))

    if potential_pauschale_codes_set:
        logger.info(
            "Pauschalenpotenzial aus Index-Treffern: %s",
            potential_pauschale_codes_set,
        )

    # Zusätzliche Suche über vollständige Daten (Fallback zu Indizes)
    for item_lp in pauschale_lp_data:
        lkn_in_lp_db_val = item_lp.get('Leistungsposition')
        if isinstance(lkn_in_lp_db_val, str) and lkn_in_lp_db_val.upper() in regelkonforme_lkn_codes_fuer_suche:
            pc_code = item_lp.get('Pauschale')
            if pc_code and str(pc_code) in pauschalen_dict:
                potential_pauschale_codes_set.add(str(pc_code))

    regelkonforme_lkns_in_tables_cache: Dict[str, Set[str]] = {}
    for cond_data in pauschale_bedingungen_data:
        pc_code_cond_val = cond_data.get('Pauschale')
        if not (pc_code_cond_val and str(pc_code_cond_val) in pauschalen_dict):
            continue
        pc_code_cond = str(pc_code_cond_val)
        bedingungstyp_cond_str = cond_data.get('Bedingungstyp', "").upper()
        werte_cond_str = cond_data.get('Werte', "")
        if bedingungstyp_cond_str in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN"]:
            werte_liste_cond_set = {w.strip().upper() for w in str(werte_cond_str).split(',') if w.strip()}
            if not regelkonforme_lkn_codes_fuer_suche.isdisjoint(werte_liste_cond_set):
                potential_pauschale_codes_set.add(pc_code_cond)
        elif bedingungstyp_cond_str in ["LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE"]:
            table_refs_cond_set = {t.strip().lower() for t in str(werte_cond_str).split(',') if t.strip()}
            for lkn_regelkonform_raw in regelkonforme_lkn_codes_fuer_suche:
                if isinstance(lkn_regelkonform_raw, str):
                    lkn_regelkonform_str = lkn_regelkonform_raw
                    if lkn_regelkonform_str not in regelkonforme_lkns_in_tables_cache:
                        tables_for_lkn_set = set()
                        for table_name_key_norm, table_entries_list in tabellen_dict_by_table.items():
                            for entry_item in table_entries_list:
                                if entry_item.get('Code', '').upper() == lkn_regelkonform_str and \
                                   entry_item.get('Tabelle_Typ', '').lower() == "service_catalog":
                                    tables_for_lkn_set.add(table_name_key_norm)
                        regelkonforme_lkns_in_tables_cache[lkn_regelkonform_str] = tables_for_lkn_set
                    if not table_refs_cond_set.isdisjoint(regelkonforme_lkns_in_tables_cache[lkn_regelkonform_str]):
                        potential_pauschale_codes_set.add(pc_code_cond)
                        break

    logger.debug(
        "DEBUG: %s potenzielle Pauschalen für Mapping/Prüfung gefunden: %s",
        len(potential_pauschale_codes_set),
        potential_pauschale_codes_set,
    )

    if not potential_pauschale_codes_set:
        logger.info("Keine potenziellen Pauschalen nach initialer Suche gefunden. Gehe zu TARDOC.")
        finale_abrechnung_obj = prepare_tardoc_abrechnung_func(regel_ergebnisse_details_list, leistungskatalog_dict, lang)
        return finale_abrechnung_obj, llm_stage2_mapping_results

    mapping_candidate_lkns_dict = get_LKNs_from_pauschalen_conditions(
        potential_pauschale_codes_set, pauschale_bedingungen_data,
        tabellen_dict_by_table, leistungskatalog_dict)

    tardoc_lkns_to_map_list = [l for l in rule_checked_leistungen_list if l.get('typ') in ['E', 'EZ']]
    mapped_lkn_codes_set: Set[str] = set()
    wa_codes_replaced_by_sa: Set[str] = set()
    mapping_process_had_connection_error = False

    if tardoc_lkns_to_map_list and mapping_candidate_lkns_dict:
        for tardoc_leistung_map_obj in tardoc_lkns_to_map_list:
            t_lkn_code = tardoc_leistung_map_obj.get('lkn')
            t_lkn_desc = tardoc_leistung_map_obj.get('beschreibung')
            current_candidates_for_llm = mapping_candidate_lkns_dict
            if isinstance(t_lkn_code, str) and t_lkn_code.startswith('AG.'):
                anast_table_content_codes = {
                    str(item['Code']).upper() for item in get_table_content("ANAST", "service_catalog", tabellen_dict_by_table) if item.get('Code')
                }
                filtered_anast_candidates = {
                    k: v for k, v in mapping_candidate_lkns_dict.items()
                    if k.startswith('WA.') or k in anast_table_content_codes
                }
                if filtered_anast_candidates:
                    current_candidates_for_llm = filtered_anast_candidates

            t_lkn_code_upper: Optional[str] = None
            if isinstance(t_lkn_code, str):
                t_lkn_code_upper = t_lkn_code.strip().upper()

            direct_mapping_code: Optional[str] = None
            if t_lkn_code_upper and current_candidates_for_llm and t_lkn_code_upper in current_candidates_for_llm:
                direct_mapping_code = t_lkn_code_upper

            if direct_mapping_code:
                mapped_lkn_codes_set.add(direct_mapping_code)
                if ".SA." in direct_mapping_code and isinstance(t_lkn_code, str):
                    source_code = t_lkn_code.strip().upper()
                    if source_code.startswith("WA."):
                        wa_codes_replaced_by_sa.add(source_code)
                logger.info(
                    "LLM Stufe 2 (Mapping) Ǭbersprungen: %s ist bereits Teil der Kandidatenliste.",
                    direct_mapping_code,
                )
                llm_stage2_mapping_results["mapping_results"].append({
                    "tardoc_lkn": t_lkn_code,
                    "tardoc_desc": t_lkn_desc,
                    "mapped_lkn": direct_mapping_code,
                    "candidates_considered_count": len(current_candidates_for_llm),
                    "info": "Direktzuordnung ohne LLM"
                })
                continue

            if t_lkn_code and t_lkn_desc and current_candidates_for_llm:
                try:
                    mapped_target_lkn_code, map_tokens = call_llm_stage2_mapping(str(t_lkn_code), str(t_lkn_desc), current_candidates_for_llm, lang)
                    token_usage["llm_stage2"]["input_tokens"] += map_tokens.get("input_tokens", 0)
                    token_usage["llm_stage2"]["output_tokens"] += map_tokens.get("output_tokens", 0)
                    if mapped_target_lkn_code:
                        mapped_target_lkn_code = str(mapped_target_lkn_code).strip().upper()
                        if mapped_target_lkn_code:
                            mapped_lkn_codes_set.add(mapped_target_lkn_code)
                            if ".SA." in mapped_target_lkn_code and isinstance(t_lkn_code, str):
                                source_code = t_lkn_code.strip().upper()
                                if source_code.startswith("WA."):
                                    wa_codes_replaced_by_sa.add(source_code)
                    llm_stage2_mapping_results["mapping_results"].append({
                        "tardoc_lkn": t_lkn_code, "tardoc_desc": t_lkn_desc,
                        "mapped_lkn": mapped_target_lkn_code,
                        "candidates_considered_count": len(current_candidates_for_llm)
                    })
                except ConnectionError as e_conn_map:
                    logger.error("Verbindung zu LLM Stufe 2 (Mapping) für %s fehlgeschlagen: %s", t_lkn_code, e_conn_map)
                    finale_abrechnung_obj = {"type": "Error", "message": f"Verbindungsfehler zum Analyse-Service (Stufe 2 Mapping): {e_conn_map}"}
                    mapping_process_had_connection_error = True
                    break
                except Exception as e_map_call:
                    logger.error("Fehler bei Aufruf von LLM Stufe 2 (Mapping) für %s: %s", t_lkn_code, e_map_call)
                    traceback.print_exc()
                    llm_stage2_mapping_results["mapping_results"].append({"tardoc_lkn": t_lkn_code, "tardoc_desc": t_lkn_desc, "mapped_lkn": None, "error": str(e_map_call), "candidates_considered_count": len(current_candidates_for_llm)})
            else:
                llm_stage2_mapping_results["mapping_results"].append({"tardoc_lkn": t_lkn_code or "N/A", "tardoc_desc": t_lkn_desc or "N/A", "mapped_lkn": None, "info": "Mapping übersprungen", "candidates_considered_count": len(current_candidates_for_llm) if current_candidates_for_llm else 0})
    else:
        logger.info("Überspringe LKN-Mapping (keine E/EZ LKNs oder keine Mapping-Kandidaten).")

    if mapping_process_had_connection_error:
        return {"type": "Error", "message": "Connection error during mapping"}, llm_stage2_mapping_results

    final_lkn_context_for_pauschale_set: Set[str] = set()
    for leistung in rule_checked_leistungen_list:
        if not isinstance(leistung, dict):
            continue
        raw_code = leistung.get('lkn')
        if not isinstance(raw_code, str):
            continue
        normalized_code = raw_code.strip().upper()
        if normalized_code:
            final_lkn_context_for_pauschale_set.add(normalized_code)

    llm_validated_codes_for_context: Set[str] = set()
    for code in context.get("llm_validated_lkns", []):
        if not isinstance(code, str):
            continue
        normalized_code = code.strip().upper()
        if normalized_code:
            llm_validated_codes_for_context.add(normalized_code)
    final_lkn_context_for_pauschale_set.update(mapped_lkn_codes_set)
    final_lkn_context_for_pauschale_set.update(llm_validated_codes_for_context)
    contains_sa_code = any(".SA." in code for code in final_lkn_context_for_pauschale_set)
    if contains_sa_code:
        wa_codes_to_remove = set(wa_codes_replaced_by_sa)
        wa_codes_to_remove.update(
            code
            for code in final_lkn_context_for_pauschale_set
            if code.startswith("WA.") and code in llm_validated_codes_for_context
        )
        if wa_codes_to_remove:
            final_lkn_context_for_pauschale_set = {
                code
                for code in final_lkn_context_for_pauschale_set
                if code not in wa_codes_to_remove
            }
    final_lkn_context_list_for_pauschale = list(final_lkn_context_for_pauschale_set)
    logger.info(
        "Finaler LKN-Kontext für Pauschalen-Hauptprüfung (%s LKNs): %s",
        len(final_lkn_context_list_for_pauschale),
        final_lkn_context_list_for_pauschale,
    )

    # --- OPTIMIERUNG: Index-basierte Suche statt linearer Scan ---
    erweiterte_lkn_suchmenge = {str(l).upper() for l in final_lkn_context_for_pauschale_set}
    neu_gefundene_codes = find_potential_pauschalen(erweiterte_lkn_suchmenge)
    if neu_gefundene_codes:
        potential_pauschale_codes_set.update(neu_gefundene_codes)
    logger.debug(
        "DEBUG: %s potenzielle Pauschalen nach erweiterter Suche: %s",
        len(potential_pauschale_codes_set),
        potential_pauschale_codes_set,
    )

    pauschale_haupt_pruef_kontext = {
        "ICD": context.get("icd_input"),
        "Medikamente": context.get("medication_atcs"),
        "GTIN": context.get("medication_atcs"),
        "Alter": context.get("alter_context_val"),
        "AlterOperator": context.get("alter_operator_context"),
        "AlterBeiEintritt": context.get("alter_context_val"),
        "AlterSource": context.get("alter_source_context"),
        "Geschlecht": context.get("geschlecht_context_val") or "unbekannt",
        "GeschlechtSource": context.get("geschlecht_source_context"),
        "useIcd": context.get("use_icd_flag"),
        "LKN": final_lkn_context_list_for_pauschale,
        "Seitigkeit": context.get("seitigkeit_context_val"),
        "Anzahl": context.get("anzahl_fuer_pauschale_context"),
    }
    context["pauschale_haupt_pruef_kontext"] = pauschale_haupt_pruef_kontext
    try:
        logger.info(f"Starte Pauschalen-Hauptprüfung (useIcd=%s)...", context.get("use_icd_flag"))
        pauschale_pruef_ergebnis_dict = determine_applicable_pauschale_func(
            user_input, rule_checked_leistungen_list, pauschale_haupt_pruef_kontext,
            pauschale_lp_data, pauschale_bedingungen_data, pauschalen_dict,
            leistungskatalog_dict, tabellen_dict_by_table,
            pauschale_lp_index, pauschale_cond_lkn_index, pauschale_cond_table_index, lkn_to_tables_index,
            potential_pauschale_codes_set,
            lang,
            prepared_structures=prepared_structures # Pass pre-computed structures
        )
        finale_abrechnung_obj = pauschale_pruef_ergebnis_dict
        if finale_abrechnung_obj.get("type") == "Pauschale":
            logger.info("Anwendbare Pauschale gefunden: %s", finale_abrechnung_obj.get('details', {}).get('Pauschale'))
        else:
            logger.info("Keine anwendbare Pauschale. Grund: %s", finale_abrechnung_obj.get('message', 'Unbekannt'))
    except Exception as e_pauschale_main:
        logger.error("Fehler bei Pauschalen-Hauptprüfung: %s", e_pauschale_main)
        traceback.print_exc()
        finale_abrechnung_obj = {"type": "Error", "message": f"Interner Fehler bei Pauschalen-Hauptprüfung: {e_pauschale_main}"}

    if finale_abrechnung_obj is None or finale_abrechnung_obj.get("type") != "Pauschale":
        logger.info("Keine gültige Pauschale ausgewählt oder Prüfung übersprungen. Bereite TARDOC-Abrechnung vor.")
        finale_abrechnung_obj = prepare_tardoc_abrechnung_func(regel_ergebnisse_details_list, leistungskatalog_dict, lang)

    return finale_abrechnung_obj, llm_stage2_mapping_results


# --- API Endpunkt ---
@app.route('/api/analyze-billing', methods=['POST'])
def analyze_billing():
    """Zentrale API: führt den zweistufigen LLM-Workflow für eine Abrechnungsanfrage aus."""
    with processing_lock:
        try:
            req_data = _parse_billing_request(request)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    user_input = req_data["user_input"]
    lang = req_data["lang"]
    icd_input = req_data["icd_input"]
    medication_inputs = req_data["medication_inputs"]
    medication_atcs = req_data["medication_atcs"]
    use_icd_flag = req_data["use_icd_flag"]
    alter_user = req_data["alter_user"]
    geschlecht_user = req_data["geschlecht_user"]
    heuristic_demo = cast(PatientDemographics, req_data.get("demographics_heuristic", {}))

    start_time = time.time()
    request_id = f"req_{time.time_ns()}"
    logger.info(f"[{request_id}] --- Start /api/analyze-billing ---")
    normalized_input: Optional[str] = None
    if LOG_INPUT_TEXT or LOG_LLM_INPUT:
        normalized_input = user_input.replace('\r', '\\r').replace('\n', '\\n')
        payload_parts: List[str] = [f"Text={normalized_input}"]
        if icd_input:
            payload_parts.append(f"ICDs={json.dumps(icd_input, ensure_ascii=False)}")
        if medication_inputs:
            payload_parts.append(f"Medikamente={json.dumps(medication_inputs, ensure_ascii=False)}")
        if medication_atcs:
            payload_parts.append(f"ATC={json.dumps(medication_atcs, ensure_ascii=False)}")
        payload_parts.append(f"useIcd={use_icd_flag}")
        if alter_user is not None:
            payload_parts.append(f"Age={alter_user}")
        if geschlecht_user:
            payload_parts.append(f"Gender={geschlecht_user}")
        input_payload_msg = f"[{request_id}] InputText: " + " | ".join(payload_parts)
        if LOG_INPUT_TEXT:
            detail_logger.info(input_payload_msg)
            if CONSOLE_LOG_LEVEL <= logging.INFO:
                logger.info(input_payload_msg)
        elif LOG_LLM_INPUT:
            detail_logger.info(input_payload_msg)
    if LOG_LLM_INPUT and normalized_input is not None:
        detail_logger.info(f"[{request_id}] LLM1 Anfrage-Text: {normalized_input}")
        detail_logger.info(
            f"[{request_id}] Kontextdaten: ICDs={icd_input}, Medikamente={medication_inputs} -> ATC={medication_atcs}, useIcd={use_icd_flag}, Age={alter_user}, Gender={geschlecht_user}"
        )

    token_usage = {"llm_stage1": {"input_tokens": 0, "output_tokens": 0}, "llm_stage2": {"input_tokens": 0, "output_tokens": 0}}

    if not daten_geladen:
        logger.error("Daten nicht geladen. App-Start fehlgeschlagen?")
        return jsonify({"error": "Server data not loaded."}), 503

    try:
        katalog_context_str, top_ranking_results, query_variants = _build_context_for_llm(user_input, lang)
        llm_stage1_result, s1_tokens = call_llm_stage1(user_input, katalog_context_str, lang, query_variants=query_variants)
        token_usage["llm_stage1"]["input_tokens"] += s1_tokens.get("input_tokens", 0)
        token_usage["llm_stage1"]["output_tokens"] += s1_tokens.get("output_tokens", 0)
    except ConnectionError as e:
        return jsonify({"error": f"Verbindungsfehler zum Analyse-Service (Stufe 1): {e}"}), 504
    except PermissionError as e:
        return jsonify({"error": "Anfrage von LLM-Provider aus Inhaltsrichtlinien-Gründen blockiert."}), 403
    except ValueError as e:
        return jsonify({"error": f"Fehler bei der Leistungsanalyse (Stufe 1): {e}"}), 400
    except Exception as e:
        logger.error(f"Unerwarteter Fehler bei LLM1 [{request_id}]: {e}", exc_info=True)
        return jsonify({"error": f"Unerwarteter interner Fehler (Stufe 1): {e}"}), 500

    llm1_time = time.time()
    logger.info(f"[{request_id}] Zeit nach LLM Stufe 1: {llm1_time - start_time:.2f}s")
    extracted_info_llm = llm_stage1_result.get("extracted_info", {})
    patient_context = _merge_patient_demographics(alter_user, geschlecht_user, extracted_info_llm, heuristic_demo)
    alter_context_val: Optional[int] = patient_context.get("age_value")
    alter_operator: Optional[str] = patient_context.get("age_operator")
    alter_context_source: Optional[str] = patient_context.get("age_source")
    geschlecht_context_raw: Optional[str] = patient_context.get("gender_value")
    geschlecht_context_val: str = geschlecht_context_raw or 'unbekannt'
    geschlecht_source: Optional[str] = patient_context.get("gender_source")

    heur_demo_for_match: PatientDemographics = {
        "age_value": alter_context_val,
        "age_operator": alter_operator,
        "gender": geschlecht_context_val if geschlecht_context_val in {"m", "w"} else None,
    }
    heuristic_codes = _match_codes_for_demographics(heur_demo_for_match)
    if heuristic_codes:
        identified_list = llm_stage1_result.setdefault("identified_leistungen", [])
        existing_codes = {
            item.get("lkn", "").strip().upper()
            for item in identified_list
            if isinstance(item, dict) and isinstance(item.get("lkn"), str)
        }
        added_codes = []
        for code in heuristic_codes:
            norm_code = str(code).strip().upper()
            if not norm_code or norm_code in existing_codes:
                continue
            katalog_entry = leistungskatalog_dict.get(norm_code)
            if not katalog_entry:
                continue
            identified_list.append(
                {
                    "lkn": norm_code,
                    "typ": katalog_entry.get("Typ", "N/A"),
                    "beschreibung": katalog_entry.get("Beschreibung", "N/A"),
                    "menge": 1,
                }
            )
            added_codes.append(norm_code)
            existing_codes.add(norm_code)
        if added_codes:
            logger.info("Demografie-Heuristik fügte LKN hinzu: %s", added_codes)

    rule_checked_leistungen_list, regel_ergebnisse_details_list = _validate_and_apply_rules(
        llm_stage1_result, lang, icd_input, medication_atcs, alter_context_val, alter_operator, geschlecht_context_val
    )
    final_validated_llm_leistungen = llm_stage1_result["identified_leistungen"]
    stage1_validated_code_list: List[str] = []
    for item in final_validated_llm_leistungen:
        if not isinstance(item, dict):
            continue
        raw_code = item.get("lkn")
        if not isinstance(raw_code, str):
            continue
        normalized_code = raw_code.strip().upper()
        if normalized_code:
            stage1_validated_code_list.append(normalized_code)

    candidate_codes = [code for _, code in top_ranking_results if (len(top_ranking_results) <= 1 or not final_validated_llm_leistungen or (top_ranking_results[0][0] / (top_ranking_results[1][0] or 1)) <= 1.5)]
    llm_stage1_result["ranking_candidates"] = candidate_codes

    seitigkeit_context_val = extracted_info_llm.get("seitigkeit") or "unbekannt"
    def _to_int(value: Any) -> Optional[int]:
        """Generic helper to normalize int-like values from LLM output."""
        if isinstance(value, bool):
            return None
        try:
            return int(str(value).strip())
        except Exception:
            return None

    anzahl_prozeduren_val = _to_int(extracted_info_llm.get("anzahl_prozeduren"))
    # Bestmögliche Ableitung einer Gesamtanzahl für Pauschalen:
    # 1) explizit extrahierte Anzahl (anzahl_prozeduren)
    # 2) generische Menge aus LLM (menge_allgemein)
    # 3) Summe der Mengen aller identifizierten Leistungen (falls > 0)
    anzahl_fuer_pauschale_context = anzahl_prozeduren_val
    if anzahl_fuer_pauschale_context is None:
        menge_allgemein_val = _to_int(extracted_info_llm.get("menge_allgemein"))
        if isinstance(menge_allgemein_val, int):
            anzahl_fuer_pauschale_context = menge_allgemein_val
    if anzahl_fuer_pauschale_context is None:
        qty_hint = _extract_quantity_hint(user_input)
        if qty_hint is not None:
            anzahl_fuer_pauschale_context = qty_hint
    if anzahl_fuer_pauschale_context is None:
        sum_mengen = 0
        for l in final_validated_llm_leistungen:
            if not isinstance(l, dict):
                continue
            try:
                sum_mengen += int(l.get("menge", 0) or 0)
            except (ValueError, TypeError):
                continue
        if sum_mengen > 0:
            anzahl_fuer_pauschale_context = sum_mengen
    if seitigkeit_context_val.lower() == 'beidseits' and anzahl_fuer_pauschale_context is None:
        if len(final_validated_llm_leistungen) == 1 and final_validated_llm_leistungen[0].get('menge') == 1:
            anzahl_fuer_pauschale_context = 2
        elif any(l.get('lkn') == "C02.CP.0100" and l.get('menge') == 1 for l in final_validated_llm_leistungen):
            anzahl_fuer_pauschale_context = 2

    fallback_pauschale_search = not final_validated_llm_leistungen
    pauschale_context_used: Optional[Dict[str, Any]] = None
    if fallback_pauschale_search:
        try:
            kandidaten_liste = search_pauschalen(user_input)
            kandidaten_text = "\n".join(f"{k['code']}: {k['text']}" for k in kandidaten_liste)
            ranking_codes, rank_tokens = call_llm_stage2_ranking(user_input, kandidaten_text, lang)
            token_usage["llm_stage2"]["input_tokens"] += rank_tokens.get("input_tokens", 0)
            token_usage["llm_stage2"]["output_tokens"] += rank_tokens.get("output_tokens", 0)
        except Exception as e:
            logger.error(f"Fehler beim Fallback-Ranking [{request_id}]: {e}", exc_info=True)
            ranking_codes = []

        potential_pauschale_codes_set = set(ranking_codes)
        if potential_pauschale_codes_set:
            heuristische_lkns = [code for _, code in top_ranking_results]
            pruef_kontext = {
                "ICD": icd_input,
                "Medikamente": medication_atcs,
                "GTIN": medication_atcs,
                "Alter": alter_context_val,
                "AlterOperator": alter_operator,
                "AlterBeiEintritt": alter_context_val,
                "AlterSource": alter_context_source,
                "Geschlecht": geschlecht_context_val or "unbekannt",
                "GeschlechtSource": geschlecht_source,
                "useIcd": use_icd_flag,
                "LKN": heuristische_lkns,
                "Seitigkeit": seitigkeit_context_val,
                "Anzahl": anzahl_fuer_pauschale_context,
            }
            pauschale_context_used = pruef_kontext
            try:
                finale_abrechnung_obj = determine_applicable_pauschale_func(
                    user_input,
                    [],
                    pruef_kontext,
                    pauschale_lp_data,
                    pauschale_bedingungen_data,
                    pauschalen_dict,
                    leistungskatalog_dict,
                    tabellen_dict_by_table,
                    pauschale_lp_index,
                    pauschale_cond_lkn_index,
                    pauschale_cond_table_index,
                    lkn_to_tables_index,
                    potential_pauschale_codes_set,
                    lang,
                    prepared_structures=None,
                )
            except Exception as e:
                logger.error(f"Fehler bei Pauschalen-Fallback-Prüfung [{request_id}]: {e}", exc_info=True)
                finale_abrechnung_obj = None
        else:
            finale_abrechnung_obj = None
        llm_stage2_mapping_results = {}
    else:
        billing_context = {
            "icd_input": icd_input,
            "medication_inputs": medication_inputs,
            "medication_atcs": medication_atcs,
            "alter_context_val": alter_context_val,
            "alter_operator_context": alter_operator,
            "alter_source_context": alter_context_source,
            "geschlecht_context_val": geschlecht_context_val or "unbekannt",
            "geschlecht_source_context": geschlecht_source,
            "use_icd_flag": use_icd_flag,
            "seitigkeit_context_val": seitigkeit_context_val,
            "anzahl_fuer_pauschale_context": anzahl_fuer_pauschale_context,
            "llm_validated_lkns": stage1_validated_code_list,
            "demographics_heuristic": heuristic_demo,
        }
        finale_abrechnung_obj, llm_stage2_mapping_results = _determine_final_billing(rule_checked_leistungen_list, regel_ergebnisse_details_list, user_input, lang, billing_context, token_usage)
        pauschale_context_used = billing_context.get("pauschale_haupt_pruef_kontext")

    rule_time = time.time()
    logger.info(f"[{request_id}] Zeit nach Regelprüfung: {rule_time - llm1_time:.2f}s")

    safe_abrechnung_obj = finale_abrechnung_obj or {}
    # Optionally rerender conditions HTML using structured data and sanitize
    try:
        if RENDER_SERVER_SIDE_CONDITIONS and isinstance(safe_abrechnung_obj, dict):
            # Top-level selected Pauschale
            if 'conditions_structured' in safe_abrechnung_obj and safe_abrechnung_obj.get('conditions_structured'):
                _html = render_condition_groups_html(safe_abrechnung_obj['conditions_structured'], lang)
                safe_abrechnung_obj['bedingungs_pruef_html'] = sanitize_html_fragment(_html)
            # Evaluated candidates
            eval_list = safe_abrechnung_obj.get('evaluated_pauschalen')
            if isinstance(eval_list, list):
                for item in eval_list:
                    if isinstance(item, dict) and item.get('conditions_structured'):
                        _html = render_condition_groups_html(item['conditions_structured'], lang)
                        item['bedingungs_pruef_html'] = sanitize_html_fragment(_html)
            # Explanation rendering
            details = safe_abrechnung_obj.get('details') if isinstance(safe_abrechnung_obj, dict) else None
            if isinstance(details, dict):
                selected_entry = None
                if isinstance(eval_list, list):
                    sel_code = details.get('Pauschale')
                    for c in eval_list:
                        if isinstance(c, dict) and (str(c.get('code')) == str(sel_code)):
                            selected_entry = c
                            break
                exp_html = render_pauschale_explanation_html(selected_entry, eval_list if isinstance(eval_list, list) else [], lang)
                if exp_html:
                    details['pauschale_erklaerung_html'] = sanitize_html_fragment(exp_html)
    except Exception:
        pass
    # Sanitize HTML fragments in abrechnung payload before responding
    try:
        _sanitize_abrechnung_payload(safe_abrechnung_obj)
    except Exception:
        pass

    # Also provide sanitized copy of evaluated_pauschalen at top-level for convenience
    sanitized_evaluated_list = []
    try:
        for _it in safe_abrechnung_obj.get('evaluated_pauschalen', []) or []:
            if isinstance(_it, dict) and 'bedingungs_pruef_html' in _it:
                _clone = dict(_it)
                _clone['bedingungs_pruef_html'] = sanitize_html_fragment(_clone.get('bedingungs_pruef_html') or '')
                sanitized_evaluated_list.append(_clone)
            else:
                sanitized_evaluated_list.append(_it)
    except Exception:
        sanitized_evaluated_list = safe_abrechnung_obj.get('evaluated_pauschalen', []) or []

    final_response_payload = {
        "llm_ergebnis_stufe1": llm_stage1_result,
        "regel_ergebnisse_details": regel_ergebnisse_details_list,
        "abrechnung": finale_abrechnung_obj,
        "llm_ergebnis_stufe2": llm_stage2_mapping_results,
        "evaluated_pauschalen": sanitized_evaluated_list,
        "token_usage": token_usage,
        "fallback_pauschale_search": fallback_pauschale_search,
        "pauschale_context": pauschale_context_used,
    }

    total_time = time.time() - start_time
    logger.info(f"[{request_id}] Gesamtverarbeitungszeit: {total_time:.2f}s")
    logger.info(f"[{request_id}] Sende finale Antwort Typ '{safe_abrechnung_obj.get('type', 'None')}'")
    if LOG_HTML_OUTPUT:
        detail_logger.info(f"[{request_id}] Final response payload (contains HTML): {json.dumps(final_response_payload, ensure_ascii=False, indent=2)}")

    return jsonify(final_response_payload)


@app.route('/api/pauschale-conditions-html', methods=['POST'])
def pauschale_conditions_html() -> Any:
    """Erzeuge Bedingungs-HTML on demand, z.B. wenn die UI Details nachlädt."""
    if not daten_geladen:
        return jsonify({"error": "Server data not loaded."}), 503

    payload = request.get_json(silent=True) or {}
    code_raw = payload.get("code") or ""
    lang = (payload.get("lang") or "de").lower()
    if not code_raw:
        return jsonify({"error": "code missing"}), 400
    pauschale_code = str(code_raw).strip()
    context = payload.get("context") or {}
    if not isinstance(context, dict):
        context = {}

    try:
        result = check_pauschale_conditions(
            pauschale_code,
            context,
            pauschale_bedingungen_data,
            tabellen_dict_by_table,
            leistungskatalog_dict,
            lang,
            pauschalen_dict,
            prepared_structures,
            False,
        )
        html_fragment = sanitize_html_fragment(result.get("html") or "")
        response_payload = {
            "code": pauschale_code,
            "html": html_fragment,
            "errors": result.get("errors", []),
            "prueflogik_expr": result.get("prueflogik_expr"),
            "prueflogik_pretty": result.get("prueflogik_pretty"),
            "group_logic_terms": result.get("group_logic_terms"),
        }
        return jsonify(response_payload)
    except Exception as exc:
        logger.error("Failed to render pauschale conditions on demand for %s: %s", pauschale_code, exc, exc_info=True)
        return jsonify({"error": "could not render conditions"}), 500


def perform_analysis(text: str,
                     icd: list[str] | None = None,
                     medications: list[str] | None = None,
                     use_icd: bool | None = None,
                     age: int | None = None,
                     gender: str | None = None,
                     lang: str = 'de') -> dict:
    """Hilfsfunktion für Tests: ruft die analyze-billing-Logik mit gegebenen Parametern auf."""
    if icd is None:
        icd = []
    if medications is None:
        medications = []

    with app.test_client() as client:
        payload = {
            'inputText': text,
            'icd': icd,
            'medications': medications,
            'gtin': medications,
            'age': age,
            'gender': gender,
            'lang': lang,
        }
        if use_icd is not None:
            payload['useIcd'] = use_icd
        resp = client.post('/api/analyze-billing', json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"analyze-billing failed: {resp.status_code} {resp.get_data(as_text=True)}")
        return resp.get_json()


@app.route('/api/chop')
def chop_lookup() -> Any:
    """Return CHOP suggestions for a search term."""
    if not daten_geladen:
        return jsonify([])
    term = request.args.get('q', '').strip()
    try:
        offset = int(request.args.get('offset', '0'))
    except ValueError:
        offset = 0
    try:
        limit = int(request.args.get('limit', '20'))
    except ValueError:
        limit = 20
    results = search_chop(term, offset=offset, limit=limit)
    return jsonify(results)

@app.route('/api/icd')
def icd_lookup() -> Any:
    """Return ICD suggestions for a search term and language."""
    if not daten_geladen:
        return jsonify([])
    term = request.args.get('q', '').strip()
    lang = request.args.get('lang', 'de').strip().lower()
    try:
        offset = int(request.args.get('offset', '0'))
    except ValueError:
        offset = 0
    try:
        limit = int(request.args.get('limit', '20'))
    except ValueError:
        limit = 20
    results = search_icd(term, lang=lang, offset=offset, limit=limit)
    return jsonify(results)

@app.route('/api/quality', methods=['POST'])
def quality_endpoint():
    """Simple quality check endpoint returning baseline comparison."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json() or {}
    baseline = data.get("baseline")
    # For now, echo baseline as result
    result = baseline
    match = result == baseline
    return jsonify({"result": result, "baseline": baseline, "match": match})

@app.route('/api/test-example', methods=['POST'])
def test_example():
    """Vergleicht das Ergebnis einer Beispielanalyse mit dem Baseline-Resultat."""
    data = request.get_json() or {}
    example_id = str(data.get('id'))
    lang = data.get('lang', 'de')
    if not daten_geladen:
        logger.error("Daten nicht geladen im /api/test-example Endpunkt. Dies sollte nicht passieren, da create_app() die Daten laden sollte.")
        return jsonify({'error': 'Server data not loaded. Please try again later or contact an administrator.'}), 503
    baseline_entry = baseline_results.get(example_id)
    if not baseline_entry:
        return jsonify({'error': 'Baseline not found'}), 404

    baseline = baseline_entry.get('baseline')
    if baseline is None:
        return jsonify({'error': 'Baseline missing for example'}), 404

    query_text = baseline_entry.get('query', {}).get(lang)
    if not query_text:
        return jsonify({'error': 'Query text missing for baseline'}), 404

    try:
        # Heuristik für useIcd und icd_codes in Tests:
        # Wenn eine Pauschale erwartet wird, versuchen wir es erstmal ohne strikte ICD-Prüfung,
        # da die baseline_results.json keine ICDs pro Testfall spezifiziert.
        # Langfristig sollten Testfälle spezifische ICDs und useIcd-Flags haben können.
        expected_pauschale = baseline.get('pauschale')
        test_use_icd = True
        test_icd_codes = [] # Standardmässig keine ICDs für Tests, es sei denn, sie wären in baseline_results definiert

        if expected_pauschale is not None:
            # Wenn eine spezifische Pauschale (nicht C90.xx) erwartet wird,
            # und diese Pauschale möglicherweise ICD-Bedingungen hat, die ohne Test-ICDs fehlschlagen würden.
            # Hier könnte man noch verfeinern, z.B. nur wenn die erwartete Pauschale KEINE C90 ist.
            # Fürs Erste: Wenn Pauschale erwartet, sei weniger streng mit ICDs, da keine Test-ICDs gegeben.
            logger.info(f"TEST_EXAMPLE: Pauschale {expected_pauschale.get('code')} erwartet. Setze useIcd=False für diesen Testlauf.")
            test_use_icd = False

        # Hier könnten in Zukunft ICDs aus baseline_entry gelesen werden, falls vorhanden
        # z.B. test_icd_codes = baseline_entry.get('icd_context', [])
        # z.B. test_use_icd = baseline_entry.get('use_icd_context', test_use_icd)

        analysis_full = perform_analysis(query_text, test_icd_codes, [], test_use_icd, None, None, lang)
    except Exception as e:
        logger.error(f"Error in test_example for ID {example_id}, lang {lang}: {e}", exc_info=True)
        return jsonify({'error': f'Analysis failed: {e}'}), 500

    def simplify(result_dict: dict) -> dict:
        """Mappe die komplexe Analyseantwort auf das einfache Baseline-Schema."""
        if not isinstance(result_dict, dict):
            return {'pauschale': None, 'einzelleistungen': []}
        abrechnung = result_dict.get('abrechnung') or {}
        if not isinstance(abrechnung, dict):
            abrechnung = {}
        if abrechnung.get('type') == 'Pauschale':
            details = abrechnung.get('details') or {}
            if not isinstance(details, dict):
                details = {}
            pc = details.get('Pauschale')
            pauschale = {'code': pc, 'qty': 1} if pc else None
            return {'pauschale': pauschale, 'einzelleistungen': []}
        if abrechnung.get('type') == 'TARDOC':
            leistungen = abrechnung.get('leistungen') or []
            eins = [
                {'code': l.get('lkn'), 'qty': l.get('menge', 1)}
                for l in leistungen
                if isinstance(l, dict) and l.get('lkn')
            ]
            return {'pauschale': None, 'einzelleistungen': eins}
        return {'pauschale': None, 'einzelleistungen': []}

    result = simplify(analysis_full)

    baseline_entry.setdefault('current', {})[lang] = result

    def diff_results(expected: dict, actual: dict) -> str:
        """Gibt kompakte Beschreibung der Differenzen zwischen erwarteten und aktuellen Ergebnissen zurück."""
        parts = []
        if expected.get('pauschale') != actual.get('pauschale'):
            parts.append(f"pauschale {expected.get('pauschale')} != {actual.get('pauschale')}")
        exp_map = {i['code']: i.get('qty', 1) for i in expected.get('einzelleistungen', []) if isinstance(i, dict) and i.get('code')}
        act_map = {i['code']: i.get('qty', 1) for i in actual.get('einzelleistungen', []) if isinstance(i, dict) and i.get('code')}
        for code, qty in exp_map.items():
            if code not in act_map:
                parts.append(f"missing {code}")
            elif act_map[code] != qty:
                parts.append(f"qty {code}: {qty} != {act_map[code]}")
        for code, qty in act_map.items():
            if code not in exp_map:
                parts.append(f"unexpected {code}")
        return '; '.join(parts)

    diff = diff_results(baseline, result)
    passed = diff == ''

    token_usage = {}
    if isinstance(analysis_full, dict):
        token_usage = analysis_full.get('token_usage', {}) or {}
        if not isinstance(token_usage, dict):
            token_usage = {}

    return jsonify({
        'id': example_id,
        'lang': lang,
        'passed': passed,
        'baseline': baseline,
        'result': result,
        'diff': diff,
        'token_usage': token_usage
    })

# --- Feedback via GitHub --------------------------------------------------
@app.route('/api/frontend-log', methods=['POST'])
def frontend_log() -> Any:
    """Receive diagnostic messages from the frontend and write them to the server log."""
    payload: Dict[str, Any]
    raw_text = ""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        raw_text = request.get_data(as_text=True) or ""
        try:
            payload = json.loads(raw_text) if raw_text else {}
        except json.JSONDecodeError:
            payload = {"raw": raw_text}
    event_type = payload.get("eventType") or payload.get("event_type")
    logger.info("Frontend log (%s): %s", event_type, payload)
    return jsonify({"status": "ok"})

@app.route('/api/submit-feedback', methods=['POST'])
def submit_feedback() -> Any:
    """Create a GitHub issue from user feedback."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")

    data = request.get_json() or {}
    category = data.get("category", "Allgemein")
    code = (data.get("code") or "").strip()
    message = data.get("message", "")
    user_input = data.get("user_input", "")
    pauschale = data.get("pauschale")
    einzelleistungen = data.get("einzelleistungen", [])
    begruendung1 = data.get("begruendung_llm1", "")
    begruendung2 = data.get("begruendung_llm2", "")
    context = data.get("context")

    if not token or not repo:
        # Fallback: store feedback locally if GitHub is not configured
        entry = {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "category": category,
            "code": code,
            "message": message,
            "user_input": user_input,
            "pauschale": pauschale,
            "einzelleistungen": einzelleistungen,
            "begruendung_llm1": begruendung1,
            "begruendung_llm2": begruendung2,
            "context": context,
        }
        feedback_file = Path("feedback_local.json")
        try:
            if feedback_file.exists():
                existing = json.loads(feedback_file.read_text(encoding="utf-8"))
            else:
                existing = []
            existing.append(entry)
            feedback_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Stored feedback locally: %s", entry)
        except Exception as exc:
            logger.error("Failed to store feedback locally: %s", exc)
            return jsonify({"error": "Could not save feedback"}), 500
        return jsonify({"status": "saved"})


    title_parts = [category]
    if code:
        title_parts.append(code)
    title = " - ".join(title_parts)
    body_lines = [f"**Kategorie:** {category}"]
    if code:
        body_lines.append(f"**Code:** {code}")
    if user_input:
        body_lines.append(f"**User Input:** {user_input}")
    if pauschale:
        body_lines.append(f"**Pauschale:** {pauschale}")
    if einzelleistungen:
        body_lines.append("**Einzelleistungen:** " + ", ".join(map(str, einzelleistungen)))
    if begruendung1:
        body_lines.append("**Begründung LLM Stufe 1:**\n" + begruendung1)
    if begruendung2:
        body_lines.append("**Begründung LLM Stufe 2:**\n" + begruendung2)
    if context:
        body_lines.append("**Kontext:**\n```")
        try:
            body_lines.append(json.dumps(context, ensure_ascii=False, indent=2))
        except Exception:
            body_lines.append(str(context))
        body_lines.append("```")
    body_lines.append("")
    body_lines.append(message)
    body = "\n".join(body_lines)

    issue_url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {"title": title, "body": body, "labels": ["feedback"]}
    try:
        resp = requests.post(issue_url, json=payload, headers=headers, timeout=10)
    except Exception as exc:
        logger.error("GitHub request failed: %s", exc)
        return jsonify({"error": "Could not submit feedback"}), 500
    if resp.status_code >= 300:
        logger.error("GitHub issue creation failed: %s - %s", resp.status_code, resp.text)
        return jsonify({"error": "GitHub issue creation failed"}), 500

    return jsonify({"status": "ok"})


@app.route('/api/approved-feedback', methods=['GET'])
def approved_feedback() -> Any:
    """Return feedback issues labeled for display."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    label = os.environ.get("FEEDBACK_APPROVED_LABEL", "feedback-approved")
    if not token or not repo:
        return jsonify([])
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    params = {"state": "all", "labels": label}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
    except Exception as exc:
        logger.error("GitHub fetch failed: %s", exc)
        return jsonify([])
    if resp.status_code != 200:
        logger.error("GitHub fetch failed: %s - %s", resp.status_code, resp.text)
        return jsonify([])
    items = [
        {"title": i.get("title", ""), "body": i.get("body", "")}
        for i in resp.json()
    ]
    return jsonify(items)


@app.route('/api/version')
def api_version() -> Any:
    """Return the configured application version."""
    return jsonify({
        "version": APP_VERSION,
        "tarif_version": TARIF_VERSION,
        "brick_quiz_enabled": BRICK_QUIZ_ENABLED,
    })

# --- Static‑Routes & Start ---
_CUSTOM_MIME_TYPES: Dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    "quality.html": "text/html; charset=utf-8",
    "calculator.js": "application/javascript; charset=utf-8",
    "quality.js": "application/javascript; charset=utf-8",
    "translations.json": "application/json; charset=utf-8",
}


def _apply_no_cache_headers(response: Any) -> Any:
    """Force browsers to refresh local assets during development."""
    cache_control = getattr(response, "cache_control", None)
    if cache_control is not None:
        try:
            cache_control.max_age = 0
            cache_control.no_cache = True
            cache_control.no_store = True
            cache_control.must_revalidate = True
        except Exception:
            pass
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            headers["Pragma"] = "no-cache"
            headers["Expires"] = "0"
        except Exception:
            pass
    return response


def _send_static(filename: str, mimetype: str | None = None) -> Any:
    """Wrapper around send_from_directory with disabled caching."""
    options: Dict[str, Any] = {"mimetype": mimetype} if mimetype else {}
    resp = send_from_directory(".", filename, **options)
    return _apply_no_cache_headers(resp)

def _send_brick_static(filename: str, mimetype: str | None = None) -> Any:
    """Serve Brick-Quiz assets with the same no-cache policy as core static files."""
    if not BRICK_QUIZ_STATIC_DIR.exists():
        abort(404)
    options: Dict[str, Any] = {"mimetype": mimetype} if mimetype else {}
    resp = send_from_directory(str(BRICK_QUIZ_STATIC_DIR), filename, **options)
    return _apply_no_cache_headers(resp)


@app.route("/")
def index_route(): # Umbenannt, um Konflikt mit Modul 'index' zu vermeiden, falls es existiert
    """Liefert die im Repository enthaltene Single-Page-Anwendung aus."""
    mimetype = _CUSTOM_MIME_TYPES.get("index.html")
    return _send_static("index.html", mimetype=mimetype)

@app.route("/brick_quiz/")
def brick_quiz_route() -> Any:
    """Expose das Brick-Quiz als eigenständige Teiloberfläche."""
    if not BRICK_QUIZ_ENABLED:
        abort(404)
    return _send_brick_static("Brick.html", mimetype='text/html; charset=utf-8')

@app.route("/brick_quiz/<path:filename>")
def brick_quiz_static(filename: str) -> Any:
    """Stellt statische Assets des Brick-Quiz bereit, sofern aktiviert."""
    if not BRICK_QUIZ_ENABLED:
        abort(404)
    return _serve_brick_asset(filename)

def _serve_brick_asset(filename: str) -> Any:
    """Zentrale Prüfung und Auslieferung für Brick-Quiz-Assets."""
    safe_path = Path(filename)
    if any(part.startswith(".") or part.startswith("..") for part in safe_path.parts):
        abort(404)
    allowed_suffixes = {
        ".css",
        ".js",
        ".json",
        ".png",
        ".jpg",
        ".jpeg",
        ".svg",
        ".gif",
        ".webp",
        ".wav",
        ".mp3",
        ".ogg",
        ".txt",
        ".html",
    }
    if safe_path.suffix and safe_path.suffix.lower() not in allowed_suffixes:
        abort(404)
    return _send_brick_static(filename)

@app.route("/favicon.ico")
def favicon_ico():
    """Stellt das klassische Favicon für ältere Browser-Anfragen bereit."""
    return _send_static("favicon.ico", mimetype='image/vnd.microsoft.icon')

@app.route("/favicon-32.png")
def favicon_png():
    """Gibt das hochauflösende PNG-Favicon zurück."""
    return _send_static("favicon-32.png", mimetype='image/png')

@app.route("/<path:filename>")
def serve_static(filename: str):
    """Erlaubt den direkten Abruf definierter statischer Dateien per HTTP."""
    allowed_files = {
        'calculator.js',
        'quality.js',
        'quality.html',
        'translations.json',
        'favicon.ico',
        'favicon-32.png',
        'favicon-512.png',
        'robots.txt',
    }
    allowed_dirs = {'data'} # Erlaube Zugriff auf data-Ordner
    file_path = Path(filename)

    # Verhindere Zugriff auf Python-Dateien, .env, versteckte Dateien/Ordner
    if (file_path.suffix in ['.py', '.txt', '.env'] or \
        any(part.startswith('.') for part in file_path.parts)):
         logger.warning("Zugriff verweigert (sensible Datei): %s", filename)
         abort(404)

    # Erlaube JS-Datei oder Dateien im data-Verzeichnis (und Unterverzeichnisse)
    if filename in allowed_files or (file_path.parts and file_path.parts[0] in allowed_dirs):
        # print(f"INFO: Sende statische Datei: {filename}")
        mimetype = _CUSTOM_MIME_TYPES.get(filename)
        if mimetype is None:
            suffix = file_path.suffix.lower()
            if suffix == '.html':
                mimetype = 'text/html; charset=utf-8'
            elif suffix in {'.js', '.mjs'}:
                mimetype = 'application/javascript; charset=utf-8'
            elif suffix == '.json':
                
                mimetype = 'application/json; charset=utf-8'
        return _send_static(filename, mimetype=mimetype)
    else:
        logger.warning("Zugriff verweigert (nicht erlaubt): %s", filename)
        abort(404)

def _run_local() -> None:
    """Lokaler Debug-Server (wird von Render **nicht** aufgerufen)."""
    port = int(os.environ.get("PORT", 8000))
    # Use WARNING level so the startup URL is visible even when the general
    # log level is set to WARNING. This ensures users always see where to open
    # the HTML interface.
    logger.warning("🚀 Lokal verfügbar auf http://127.0.0.1:%s", port)
    app.run(host="0.0.0.0", port=port, debug=True)


if __name__ == "__main__" and os.getenv("RENDER_SERVICE_TYPE") is None:
    # Nur wenn das Skript direkt gestartet wird – nicht in der Render-Runtime
    _run_local()
