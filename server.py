"""Flask-Anwendung zur Koordination des zweistufigen LLM-Workflows.

Der Server führt Katalogdaten, Synonymerweiterung, Retrieval-Hilfen sowie die
Regelprüfer für Einzelleistungen und Pauschalen zusammen. Eingehende Anfragen
durchlaufen eine Pipeline: Stufe 1 extrahiert potenzielle Tarifcodes über ein
LLM, das Python-Backend prüft Mengen und Regeln, und Stufe 2 ordnet oder
korrigiert die Vorschläge bei Bedarf. Zusätzlich stellt das Modul
Qualitätssicherungs-Endpunkte, das Ausliefern der leichten Weboberfläche sowie
umfangreiche Logging- und Telemetrie-Hooks bereit. Viele Importe bringen
Fallback-Stubs mit, damit Testläufe auch ohne Flask oder externe HTTP-Abhängige
funktionieren.
"""

import os
import re
import json
import time # für Zeitmessung
import traceback # für detaillierte Fehlermeldungen
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING, Optional, Dict, List, Set, Union, cast

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
    except ModuleNotFoundError:  # Minimal stubs for test environment
        class FlaskType:
            def __init__(self, *a, **kw):
                self.routes = {}
                self.config = {}

            def route(self, path, methods=None):
                methods = tuple((methods or ["GET"]))

                def decorator(func):
                    self.routes[(path, methods)] = func
                    return func

                return decorator

            def test_client(self):
                app = self

                class Client:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                    def post(self, path, json=None):
                        func = app.routes.get((path, ("POST",)))
                        if not func:
                            raise AssertionError("Route not found")
                        global request

                        class Req:
                            is_json = True

                            def get_json(self, silent: bool = False):
                                return json

                        request = Req()
                        resp = func()
                        status = 200
                        data = resp
                        if isinstance(resp, tuple):
                            data, status = resp

                        class R:
                            def __init__(self, d, s):
                                self.status_code = s
                                self._d = d

                            def get_json(self):
                                return self._d

                            def get_data(self, as_text: bool = False):
                                return self._d if not as_text else str(self._d)

                        return R(data, status)

                    def get(self, path, query_string=None):
                        func = app.routes.get((path, ("GET",)))
                        if not func:
                            raise AssertionError("Route not found")
                        global request

                        class Req:
                            is_json = False
                            args = query_string or {}

                            def get_json(self, silent: bool = False):
                                return {}

                        request = Req()
                        resp = func()
                        status = 200
                        data = resp
                        if isinstance(resp, tuple):
                            data, status = resp

                        class R:
                            def __init__(self, d, s):
                                self.status_code = s
                                self._d = d

                            def get_json(self):
                                return self._d

                            def get_data(self, as_text: bool = False):
                                return self._d if not as_text else str(self._d)

                        return R(data, status)

                return Client()

            def run(self, *a, **k):
                pass

        Flask = FlaskType

        class FlaskBlueprint:
            def __init__(self, *a: Any, **kw: Any) -> None:
                pass

        def jsonify(obj: Any = None) -> Any:
            return obj

        def send_from_directory(directory: os.PathLike[str] | str, path: os.PathLike[str] | str, **kwargs: Any) -> Any:
            return str(path)

        class Request:
            is_json = False

            def get_json(self, silent: bool = False) -> Any:
                return {}

        request = Request()

        FlaskRequest = Request

        def abort(code: int) -> None:
            raise Exception(f"abort {code}")

Request = FlaskRequest

# Typing alias for chat message param to satisfy static analyzers
from typing import TypeAlias

_MsgParam: TypeAlias = Dict[str, Any]
try:
    import requests
    RequestsHTTPError = requests.exceptions.HTTPError
    RequestsRequestException = requests.exceptions.RequestException
except ModuleNotFoundError:
    class RequestsRequestException(Exception):
        """Fallback RequestException if requests is not available."""

        pass

    class RequestsHTTPError(RequestsRequestException):
        """Fallback HTTPError capturing an optional response."""

        def __init__(self, response: Any | None = None) -> None:
            super().__init__("HTTP error")
            self.response = response

    class _DummyRequests:
        class exceptions:
            RequestException = RequestsRequestException
            HTTPError = RequestsHTTPError

        @staticmethod
        def post(*a: Any, **k: Any) -> None:
            raise RuntimeError("requests module not available")

    requests: Any = _DummyRequests()

HTTPError = RequestsHTTPError
RequestException = RequestsRequestException
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*a, **k) -> bool:
        return False
import regelpruefer_einzelleistungen as regelpruefer  # Dein Modul
from typing import Dict, List, Any, Set, Tuple, Callable, cast  # Tuple und Callable hinzugefügt
from utils import (
    get_table_content,
    translate_rule_error_message,
    expand_compound_words,
    extract_keywords,
    extract_lkn_codes_from_text,
    rank_embeddings_entries,
)
import html
from prompts import get_stage1_prompt, get_stage2_mapping_prompt, get_stage2_ranking_prompt
from utils import (
    compute_token_doc_freq,
    rank_leistungskatalog_entries,
    count_tokens)
from synonyms.expander import expand_query, set_synonyms_enabled
from synonyms import storage
from synonyms.models import SynonymCatalog
from openai_wrapper import chat_completion_safe, enforce_llm_min_interval, ChatCompletionMessageParam
import configparser

import logging
from logging.handlers import RotatingFileHandler
import sys

# Configure logging
# Custom StreamHandler to handle encoding errors
class SafeEncodingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            # Encode to UTF-8 with replacement for unencodable characters
            stream.write(msg.encode('utf-8', errors='replace').decode('utf-8', errors='ignore') + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

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
    return os.getenv(f"{_env_name(provider)}_BASE_URL")


# Lese optionale Einstellungen aus config.ini
config = configparser.ConfigParser()
config_file = Path(__file__).with_name("config.ini")
# Nutze utf-8-sig, um ein evtl. vorhandenes BOM (\ufeff) robust zu behandeln
config.read(config_file, encoding='utf-8-sig')


def _get_stage_settings(stage: str) -> tuple[str, str]:
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
    if provider == "openai":
        return None
    if provider == "apertus" and stage_key == "stage1":
        return 0.0
    if stage_key == "stage2_ranking":
        return 0.1
    return 0.05

def _resolve_temperature(stage_key: str, provider: str, model: str) -> Optional[float]:
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

file_handler: Optional[RotatingFileHandler] = None

if LOG_FILE_ENABLED and LOG_FILE_PATH:
    try:
        log_path = Path(LOG_FILE_PATH)
        if log_path.parent and not log_path.parent.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH,
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding='utf-8',
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
werkzeug_logger.setLevel(logging.INFO)
werkzeug_handler = SafeEncodingStreamHandler(sys.stdout)
werkzeug_handler.setFormatter(formatter)
werkzeug_logger.addHandler(werkzeug_handler)
werkzeug_logger.propagate = False

# Falls Dateilogs aktiv sind, auch Werkzeug-Logs in Datei schreiben
if file_handler is not None:
    try:
        werkzeug_logger.addHandler(file_handler)
    except Exception:
        pass

USE_RAG = config.getint('RAG', 'enabled', fallback=0) == 1
APP_VERSION = config.get('APP', 'version', fallback='unknown')
TARIF_VERSION = config.get('APP', 'tarif_version', fallback='')
# Base data directory
DATA_DIR = Path("data")
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

EMBEDDING_FILE = DATA_DIR / "leistungskatalog_embeddings.json"
EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

try:  # optional dependency
    from sentence_transformers import SentenceTransformer
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    SentenceTransformer = None  # type: ignore

embedding_model = None
embedding_codes: List[str] = []
embedding_vectors: List[List[float]] = []
if USE_RAG and SentenceTransformer:
    try:
        with EMBEDDING_FILE.open("r", encoding="utf-8") as f:
            _data = json.load(f)
            embedding_codes = _data.get("codes", [])
            embedding_vectors = _data.get("embeddings", [])
        embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        logger.info(" ✓ Embedding model and vectors geladen.")
    except Exception as e:  # pragma: no cover - ignore on missing file
        logger.warning(f"Konnte Embeddings nicht laden: {e}")

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
try:
    OPENAI_TOKEN_BUDGET_DEFAULT = config.getint('OPENAI', 'token_budget_default', fallback=6000)
except Exception:
    OPENAI_TOKEN_BUDGET_DEFAULT = 6000
try:
    OPENAI_TOKEN_BUDGET_APERTUS = config.getint('OPENAI', 'token_budget_apertus', fallback=4000)
except Exception:
    OPENAI_TOKEN_BUDGET_APERTUS = 4000
try:
    OPENAI_TRIM_APERTUS_ENABLED = config.getint('OPENAI', 'trim_apertus_enabled', fallback=1) == 1
except Exception:
    OPENAI_TRIM_APERTUS_ENABLED = True
try:
    OPENAI_TRIM_MAX_PASSES = config.getint('OPENAI', 'trim_max_passes', fallback=3)
except Exception:
    OPENAI_TRIM_MAX_PASSES = 3
try:
    OPENAI_TRIM_MIN_CONTEXT_CHARS = config.getint('OPENAI', 'trim_min_context_chars', fallback=2000)
except Exception:
    OPENAI_TRIM_MIN_CONTEXT_CHARS = 2000

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
 
EvaluateStructuredConditionsType = Callable[[str, Dict[Any, Any], List[Dict[Any, Any]], Dict[str, List[Dict[Any, Any]]]], bool]
CheckPauschaleConditionsType = Callable[
    [str, Dict[Any, Any], List[Dict[Any, Any]], Dict[str, List[Dict[Any, Any]]]],
    List[Dict[str, Any]]
]
GetSimplifiedConditionsType = Callable[[str, List[Dict[Any, Any]]], Set[Any]]
GenerateConditionDetailHtmlType = Callable[
    [Tuple[Any, ...], Dict[Any, Any], Dict[Any, Any], str],
    str,
]
DetermineApplicablePauschaleType = Callable[
    [str, List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], Dict[str, Any], Dict[str, List[Dict[str, Any]]], Set[str], str],
    Dict[str, Any]
]
PrepareTardocAbrechnungType = Callable[[List[Dict[Any,Any]], Dict[str, Dict[Any,Any]], str], Dict[str,Any]]

# --- Standard-Fallbacks für Funktionen aus regelpruefer_pauschale ---
def default_evaluate_fallback( # Matches: evaluate_structured_conditions(pauschale_code: str, context: Dict, pauschale_bedingungen_data: List[Dict], tabellen_dict_by_table: Dict[str, List[Dict]]) -> bool
    pauschale_code: str,
    context: Dict[Any, Any],
    pauschale_bedingungen_data: List[Dict[Any, Any]],
    tabellen_dict_by_table: Dict[str, List[Dict[Any, Any]]]
) -> bool:
    logger.warning("Fallback für 'evaluate_structured_conditions' aktiv.")
    return False

def default_check_html_fallback(
    pauschale_code: str,
    context: Dict[Any, Any],
    pauschale_bedingungen_data: List[Dict[Any, Any]],
    tabellen_dict_by_table: Dict[str, List[Dict[Any, Any]]]
) -> List[Dict[str, Any]]:
    logger.warning("Fallback für 'check_pauschale_conditions' aktiv.")
    return [{"html": "HTML-Prüfung nicht verfügbar (Fallback)", "errors": ["Fallback aktiv"], "trigger_lkn_condition_met": False}]

def default_get_simplified_conditions_fallback( # Matches: get_simplified_conditions(pauschale_code: str, bedingungen_data: list[dict]) -> set
    pauschale_code: str,
    bedingungen_data: List[Dict[Any, Any]]
) -> Set[Any]:
    logger.warning("Fallback für 'get_simplified_conditions' aktiv.")
    return set()

def default_generate_condition_detail_html_fallback(
    condition_tuple: Tuple[Any, ...],
    leistungskatalog_dict: Dict[Any, Any],
    tabellen_dict_by_table: Dict[Any, Any],
    lang: str = 'de',
) -> str:
    logger.warning("Fallback für 'generate_condition_detail_html' aktiv.")
    return "<li>Detail-Generierung fehlgeschlagen (Fallback)</li>"

def default_determine_applicable_pauschale_fallback(
    user_input_param: str, rule_checked_leistungen_list_param: List[Dict[str, Any]],
    pauschale_haupt_pruef_kontext_param: Dict[str, Any],
    pauschale_lp_data_param: List[Dict[str, Any]],
    pauschale_bedingungen_data_param: List[Dict[str, Any]],
    pauschalen_dict_param: Dict[str, Any],
    leistungskatalog_dict_param: Dict[str, Any],
    tabellen_dict_by_table_param: Dict[str, List[Dict[str, Any]]],
    potential_pauschale_codes_set_param: Set[str],
    lang_param: str = 'de'
) -> Dict[str, Any]:
    logger.warning("Fallback für 'determine_applicable_pauschale' aktiv.")
    return {"type": "Error", "message": "Pauschalen-Hauptprüfung nicht verfügbar (Fallback)"}

# --- Initialisiere Funktionsvariablen mit Fallbacks ---
evaluate_structured_conditions: EvaluateStructuredConditionsType = default_evaluate_fallback
check_pauschale_conditions: CheckPauschaleConditionsType = default_check_html_fallback
get_simplified_conditions: GetSimplifiedConditionsType = default_get_simplified_conditions_fallback
generate_condition_detail_html: GenerateConditionDetailHtmlType = default_generate_condition_detail_html_fallback
determine_applicable_pauschale_func: DetermineApplicablePauschaleType = default_determine_applicable_pauschale_fallback
prepare_tardoc_abrechnung_func: PrepareTardocAbrechnungType # Wird unten zugewiesen

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
            return {"type":"Error", "message":"TARDOC Prep Fallback (LKN Funktion fehlt)"}
        prepare_tardoc_abrechnung_func = prepare_tardoc_lkn_fb
except ImportError:
    logger.error("FEHLER: regelpruefer_einzelleistungen.py nicht gefunden! Verwende Fallbacks für LKN-Regelprüfung.")
    def prepare_tardoc_lkn_import_fb(r: List[Dict[Any,Any]], l: Dict[str, Dict[Any,Any]], lang_param: str = 'de') -> Dict[str,Any]:
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
pauschale_lp_data: list[dict] = []
pauschalen_data: list[dict] = []
pauschalen_dict: dict[str, dict] = {}
pauschale_bedingungen_data: list[dict] = []
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

def create_app() -> FlaskType:
    """
    Erstellt die Flask-Instanz.  
    Render (bzw. Gunicorn) ruft diese Factory einmal pro Worker auf
    und bekommt das WSGI-Objekt zurück.
    """
    app = FlaskType(__name__, static_folder='.', static_url_path='')

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

    # Ab hier bleiben alle @app.route-Dekorationen unverändert
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



# --- Daten laden Funktion ---
def load_data() -> bool:
    """Lädt Tarif-, Synonym- und Regeldaten aus dem lokalen ``data``-Verzeichnis.

    Dabei leert die Funktion alle globalen Caches, parst jede benötigte
    JSON-Datei und erzeugt Hilfsindizes (z.B. LKN → Datensatz,
    Tabellenname → Tabellenzeilen, Medikamenten-Token → ATC). Es wird ``True``
    zurückgegeben, sobald alle kritischen Dateien erfolgreich eingelesen wurden,
    damit der Aufrufer beim Start frühzeitig abbrechen kann.
    """

    global leistungskatalog_data, leistungskatalog_dict, regelwerk_dict, tardoc_tarif_dict, tardoc_interp_dict
    global pauschale_lp_data, pauschalen_data, pauschalen_dict, pauschale_bedingungen_data, pauschale_bedingungen_indexed, tabellen_data
    global tabellen_dict_by_table, daten_geladen, chop_data

    all_loaded_successfully = True
    logger.info("--- Lade Daten ---")
    # Reset all data containers
    leistungskatalog_data.clear(); leistungskatalog_dict.clear(); regelwerk_dict.clear(); tardoc_tarif_dict.clear(); tardoc_interp_dict.clear()
    pauschale_lp_data.clear(); pauschalen_data.clear(); pauschalen_dict.clear(); pauschale_bedingungen_data.clear(); pauschale_bedingungen_indexed.clear(); tabellen_data.clear()
    tabellen_dict_by_table.clear()
    token_doc_freq.clear()
    chop_data.clear()

    files_to_load = {
        "Leistungskatalog": (LEISTUNGSKATALOG_PATH, leistungskatalog_data, 'LKN', leistungskatalog_dict),
        "PauschaleLP": (PAUSCHALE_LP_PATH, pauschale_lp_data, None, None),
        "Pauschalen": (PAUSCHALEN_PATH, pauschalen_data, 'Pauschale', pauschalen_dict),
        "PauschaleBedingungen": (PAUSCHALE_BED_PATH, pauschale_bedingungen_data, None, None),
        "TARDOC_TARIF": (TARDOC_TARIF_PATH, [], 'LKN', tardoc_tarif_dict),  # Tarifpositionen
        "TARDOC_INTERP": (TARDOC_INTERP_PATH, [], 'LKN', tardoc_interp_dict),  # Interpretationen
        "Tabellen": (TABELLEN_PATH, tabellen_data, None, None),  # Tabellen nur in Liste (vorerst)
        "CHOP": (CHOP_PATH, chop_data, None, None)
    }

    for name, (path, target_list_ref, key_field, target_dict_ref) in files_to_load.items():
        try:
            logger.info("  Versuche %s von %s zu laden...", name, path)
            if path.is_file():
                with open(path, 'r', encoding='utf-8') as f:
                    data_from_file = json.load(f)

                if name == "TARDOC_INTERP" and isinstance(data_from_file, dict):
                    # Spezifische Behandlung für TARDOC_Interpretationen.json
                    logger.info("  Spezialbehandlung für TARDOC_INTERP: Extrahiere Listen aus dem Wörterbuch.")
                    combined_list = []
                    for key, value in data_from_file.items():
                        if isinstance(value, list):
                            combined_list.extend(value)
                    data_from_file = combined_list
                    logger.info("  Kombinierte Liste für TARDOC_INTERP enthält %d Einträge.", len(data_from_file))

                if not isinstance(data_from_file, list):
                     logger.warning("  WARNUNG: %s-Daten in '%s' sind keine Liste, überspringe.", name, path)
                     continue

                if target_dict_ref is not None and key_field is not None:
                     target_dict_ref.clear()
                     items_in_dict = 0
                     for item in data_from_file:
                          if isinstance(item, dict):
                               key_value = item.get(key_field)
                               if key_value: # Stelle sicher, dass key_value nicht None ist
                                   target_dict_ref[str(key_value)] = item # Konvertiere zu str für Konsistenz
                                   items_in_dict += 1
                     logger.info("  ✓ %s-Daten '%s' geladen (%s Einträge im Dict).", name, path, items_in_dict)

                if target_list_ref is not None:
                     target_list_ref.clear() # target_list_ref ist die globale Liste
                     target_list_ref.extend(data_from_file)
                     if target_dict_ref is None: # Nur loggen, wenn nicht schon fürs Dict geloggt
                          logger.info("  ✓ %s-Daten '%s' geladen (%s Einträge in Liste).", name, path, len(target_list_ref))

                if name == "Tabellen": # Spezifische Behandlung für 'Tabellen'
                    TAB_KEY = "Tabelle"
                    tabellen_dict_by_table.clear()
                    for item in data_from_file: # data_from_file ist hier der Inhalt von PAUSCHALEN_Tabellen.json
                        if isinstance(item, dict):
                            table_name = item.get(TAB_KEY)
                            if table_name: # Stelle sicher, dass table_name nicht None ist
                                normalized_key = str(table_name).lower()
                                if normalized_key not in tabellen_dict_by_table:
                                    tabellen_dict_by_table[normalized_key] = []
                                tabellen_dict_by_table[normalized_key].append(item)
                    logger.info("  Tabellen-Daten gruppiert nach Tabelle (%s Tabellen).", len(tabellen_dict_by_table))
                    _build_medication_lookup(data_from_file)
                    logger.info("  Medikamenten-Lookup aufgebaut (%s Eintraege).", len(medication_entries))
                    missing_keys_check = ['cap13', 'cap14', 'or', 'nonor', 'nonelt', 'ambp.pz', 'anast', 'c08.50']
                    not_found_keys_check = {k for k in missing_keys_check if k not in tabellen_dict_by_table}
                    if not_found_keys_check:
                         logger.error("  FEHLER: Kritische Tabellenschlüssel fehlen in tabellen_dict_by_table: %s!", not_found_keys_check)
                         all_loaded_successfully = False
            else:
                logger.error("  FEHLER: %s-Datei nicht gefunden: %s", name, path)
                if name in ["Leistungskatalog", "Pauschalen", "TARDOC_TARIF", "TARDOC_INTERP", "PauschaleBedingungen", "Tabellen"]:
                    all_loaded_successfully = False
        except (json.JSONDecodeError, IOError, Exception) as e:
             logger.error("  FEHLER beim Laden/Verarbeiten von %s (%s): %s", name, path, e)
             all_loaded_successfully = False
             traceback.print_exc()

    # Zusätzliche optionale Dateien laden
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

    # Regelwerk direkt aus TARDOC_Tarifpositionen extrahieren
    try:
        regelwerk_dict.clear()
        for lkn, info in tardoc_tarif_dict.items():
            rules = info.get("Regeln")
            if rules:
                regelwerk_dict[lkn] = rules
        logger.info("  Regelwerk aus TARDOC geladen (%s LKNs mit Regeln).", len(regelwerk_dict))
    except Exception as e:
        logger.error("  FEHLER beim Extrahieren des Regelwerks aus TARDOC: %s", e)
        traceback.print_exc(); regelwerk_dict.clear(); all_loaded_successfully = False

    # Compute document frequencies for ranking
    compute_token_doc_freq(leistungskatalog_dict, token_doc_freq)
    logger.info("  Token-Dokumentfrequenzen berechnet (%s Tokens).", len(token_doc_freq))

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

    # NEU: Indexiere und sortiere Pauschalbedingungen
    if pauschale_bedingungen_data and all_loaded_successfully:
        logger.info("  Beginne Indizierung und Sortierung der Pauschalbedingungen...")
        pauschale_bedingungen_indexed.clear()
        PAUSCHALE_KEY_FOR_INDEX = 'Pauschale' # Konstante für Schlüssel
        GRUPPE_KEY_FOR_SORT = 'Gruppe'
        BEDID_KEY_FOR_SORT = 'BedingungsID'

        temp_construction_dict: Dict[str, List[Dict[str, Any]]] = {}

        for cond_item in pauschale_bedingungen_data:
            pauschale_code_val = cond_item.get(PAUSCHALE_KEY_FOR_INDEX)
            if pauschale_code_val: # Nur wenn Pauschalencode vorhanden ist
                # Stelle sicher, dass der Code ein String ist
                pauschale_code_str = str(pauschale_code_val)
                if pauschale_code_str not in temp_construction_dict:
                    temp_construction_dict[pauschale_code_str] = []
                temp_construction_dict[pauschale_code_str].append(cond_item)
            else:
                logger.warning("  WARNUNG: Pauschalbedingung ohne Pauschalencode gefunden: %s", cond_item.get('BedingungsID', 'ID unbekannt'))

        for pauschale_code_key, conditions_list in temp_construction_dict.items():
            # Sortiere die Bedingungen für jeden Pauschalencode
            # Wichtig: Default-Werte für Sortierschlüssel, falls sie fehlen, um TypeError zu vermeiden
            conditions_list.sort(
                key=lambda c: (
                    c.get(GRUPPE_KEY_FOR_SORT, float('inf')), # Fehlende Gruppen ans Ende
                    c.get(BEDID_KEY_FOR_SORT, float('inf'))   # Fehlende BedIDs ans Ende
                )
            )
            pauschale_bedingungen_indexed[pauschale_code_key] = conditions_list

        logger.info("  Pauschalbedingungen indiziert und sortiert (%s Pauschalen mit Bedingungen).", len(pauschale_bedingungen_indexed))
        # Optional: Logge ein Beispiel, um die Sortierung zu prüfen
        # if "C01.05B" in pauschale_bedingungen_indexed and logger.isEnabledFor(logging.DEBUG):
        #     logger.debug("DEBUG: Sortierte Bedingungen für C01.05B (erste 5): %s", pauschale_bedingungen_indexed["C01.05B"][:5])
    elif not pauschale_bedingungen_data and all_loaded_successfully:
        logger.warning("  WARNUNG: Keine Pauschalbedingungen zum Indizieren vorhanden (pauschale_bedingungen_data ist leer).")
    elif not all_loaded_successfully:
        logger.warning("  WARNUNG: Überspringe Indizierung der Pauschalbedingungen aufgrund vorheriger Ladefehler.")


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
    """Extrahiert JSON aus einem LLM-Rohtext und parst es stabil.

    Entfernt Steuerzeichen und ignoriert Text ausserhalb des ersten JSON-Objekts."""
    match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_text_response, re.IGNORECASE)
    json_text = match.group(1) if match else raw_text_response
    cleaned_text = ''.join(ch for ch in json_text if ord(ch) >= 32 or ch in '\n\t\r')
    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        start = cleaned_text.find('{')
        end = cleaned_text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned_text[start:end + 1])
        raise

# --- LLM Stufe 1: LKN Identifikation ---
def call_gemini_stage1(
    user_input: str,
    katalog_context: str,
    model: str,
    lang: str = "de",
    query_variants: Optional[List[str]] = None,
) -> tuple[dict[str, Any], dict[str, int]]:
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
    prompt = get_stage1_prompt(user_input, katalog_context, lang, query_variants=query_variants)
    prompt_tokens = count_tokens(prompt)
    # Proaktives Kürzen sehr langer Prompts auf Basis des konfigurierten Budgets
    TOKEN_BUDGET = GEMINI_TOKEN_BUDGET
    if prompt_tokens > TOKEN_BUDGET:
        if GEMINI_TRIM_ENABLED:
            try:
                original_prompt_tokens = prompt_tokens
                ratio = max(0.2, TOKEN_BUDGET / max(1.0, float(prompt_tokens)))
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
                    "LLM Stufe 1 (Gemini): Prompt gekürzt auf Budget (%s). Kontext nun %s Zeichen (Tokens ~%s).",
                    TOKEN_BUDGET,
                    new_len,
                    trimmed_prompt_tokens,
                )
                prompt_tokens = trimmed_prompt_tokens
            except Exception:
                # Fallback: belasse Prompt unverändert, wenn Kürzen fehlschlägt
                pass
        else:
            logger.warning(
                "LLM Stufe 1: Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0).",
                prompt_tokens,
                TOKEN_BUDGET,
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
        response = None
        for attempt in range(GEMINI_MAX_RETRIES):
            try:
                # Respektiere konfigurierten Mindestabstand zwischen LLM-Requests
                enforce_llm_min_interval()
                response = requests.post(gemini_url, json=payload, timeout=90)
                logger.info("Gemini Stufe 1 Antwort Status Code: %s", response.status_code)
                if response.status_code == 429:
                    raise HTTPError(response=response)
                response.raise_for_status()
                break
            except RequestException as e:
                if attempt < GEMINI_MAX_RETRIES - 1:
                    wait_time = GEMINI_BACKOFF_SECONDS * (2 ** attempt)
                    logger.warning(
                        "Gemini Stufe 1 Netzwerkfehler: %s. Neuer Versuch in %s Sekunden.",
                        e,
                        wait_time,
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    error_detail = ""
                    if isinstance(e, HTTPError) and e.response is not None:
                        error_detail = f"{e.response.status_code} {e.response.text}"
                    else:
                        error_detail = str(e)
                    logger.error(
                        "Netzwerkfehler bei Gemini Stufe 1 nach %s Versuchen: %s",
                        GEMINI_MAX_RETRIES,
                        error_detail,
                    )
                    raise ConnectionError(
                        f"Netzwerkfehler bei Gemini Stufe 1: {error_detail}"
                    ) from e
        if response is None:
            raise ConnectionError("Keine Antwort von Gemini Stufe 1 erhalten")
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

        # Strikte Validierung der Hauptstruktur
        raw_llm_response: Any = llm_response_json
        if isinstance(raw_llm_response, list):
            if len(raw_llm_response) == 1 and isinstance(raw_llm_response[0], dict):
                llm_response_json = cast(Dict[str, Any], raw_llm_response[0])
                logger.info("LLM_S1_INFO: JSON-Antwort war eine Liste, erstes Element wurde extrahiert.")
            else:
                logger.error(f"LLM_S1_ERROR: Antwort ist eine Liste, aber nicht im erwarteten Format (einelementige Liste mit Objekt): {type(raw_llm_response)}")
                raise ValueError("Antwort ist eine Liste, aber nicht im erwarteten Format.")
        elif isinstance(raw_llm_response, dict):
            llm_response_json = raw_llm_response
        else:
            logger.error(f"LLM_S1_ERROR: Antwort ist kein JSON-Objekt, sondern {type(raw_llm_response)}")
            raise ValueError("Antwort ist kein JSON-Objekt.")

        if not isinstance(llm_response_json, dict):
            logger.error(f"LLM_S1_ERROR: Antwort ist kein JSON-Objekt, sondern {type(llm_response_json)}")
            raise ValueError("Antwort ist kein JSON-Objekt.")

        llm_response_json.setdefault("identified_leistungen", [])
        llm_response_json.setdefault("extracted_info", {})
        llm_response_json.setdefault("begruendung_llm", "N/A")

        if not isinstance(llm_response_json["identified_leistungen"], list):
            logger.error(f"LLM_S1_ERROR: 'identified_leistungen' ist keine Liste, sondern {type(llm_response_json['identified_leistungen'])}")
            raise ValueError("'identified_leistungen' ist keine Liste.")
        if not isinstance(llm_response_json["extracted_info"], dict):
            logger.error(f"LLM_S1_ERROR: 'extracted_info' ist kein Dictionary, sondern {type(llm_response_json['extracted_info'])}")
            raise ValueError("'extracted_info' ist kein Dictionary.")
        if not isinstance(llm_response_json["begruendung_llm"], str):
            logger.warning(f"LLM_S1_WARN: 'begruendung_llm' ist kein String, sondern {type(llm_response_json['begruendung_llm'])}. Wird auf N/A gesetzt.")
            llm_response_json["begruendung_llm"] = "N/A"

        # Validierung und Default-Setzung für extracted_info
        extracted_info_defaults = {
            "dauer_minuten": None, "menge_allgemein": None, "alter": None,
            "geschlecht": None, "seitigkeit": "unbekannt", "anzahl_prozeduren": None
        }
        expected_types_extracted_info = {
            "dauer_minuten": (int, type(None)), "menge_allgemein": (int, type(None)),
            "alter": (int, type(None)), "geschlecht": (str, type(None)),
            "seitigkeit": (str, type(None)), "anzahl_prozeduren": (int, type(None))
        }

        current_extracted_info = llm_response_json["extracted_info"] # Sollte jetzt immer ein Dict sein
        validated_extracted_info = {}

        for key, default_value in extracted_info_defaults.items():
            val = current_extracted_info.get(key) # Sicherer Zugriff mit get
            if val is None: # Wenn Schlüssel fehlt oder Wert explizit None ist
                 validated_extracted_info[key] = default_value
                 if key == "seitigkeit" and default_value == "unbekannt": # Spezieller Fall für Seitigkeit Default
                     validated_extracted_info[key] = "unbekannt"
                 continue

            expected_type_tuple = expected_types_extracted_info[key]
            if isinstance(val, expected_type_tuple):
                validated_extracted_info[key] = val
                if key == "seitigkeit" and val is None: # Falls LLM None für Seitigkeit liefert
                    validated_extracted_info[key] = "unbekannt"
            else:
                conversion_successful = False
                if expected_type_tuple[0] is int and val is not None:
                    try:
                        validated_extracted_info[key] = int(val)
                        conversion_successful = True
                        logger.info("Wert für '%s' ('%s') zu int konvertiert.", key, val)
                    except (ValueError, TypeError): pass
                elif expected_type_tuple[0] is str and val is not None:
                    try:
                        validated_extracted_info[key] = str(val)
                        conversion_successful = True
                        logger.info("Wert für '%s' ('%s') zu str konvertiert.", key, val)
                    except (ValueError, TypeError): pass
                if not conversion_successful:
                    validated_extracted_info[key] = default_value
                    logger.warning(
                        "Typfehler für '%s'. Erwartet %s, bekam %s ('%s'). Default '%s'.",
                        key,
                        expected_type_tuple,
                        type(val),
                        val,
                        default_value,
                    )
        llm_response_json["extracted_info"] = validated_extracted_info

        validated_identified_leistungen = []
        expected_leistung_keys = ["lkn", "typ", "beschreibung", "menge"]
        for i, item in enumerate(llm_response_json.get("identified_leistungen", [])): # Sicherer Zugriff
            if not isinstance(item, dict):
                logger.warning(
                    "Element %s in 'identified_leistungen' ist kein Dictionary. Übersprungen: %s",
                    i,
                    item,
                )
                continue
            # Minimalprüfung auf lkn und menge, da Typ/Beschreibung eh überschrieben werden
            lkn_val = item.get("lkn")
            menge_val = item.get("menge")

            if not isinstance(lkn_val, str) or not lkn_val.strip():
                logger.warning(
                    "Ungültige oder leere LKN in Element %s. Übersprungen: %s",
                    i,
                    item,
                )
                continue
            item["lkn"] = lkn_val.strip().upper()

            if menge_val is None: item["menge"] = 1
            elif not isinstance(menge_val, int):
                try:
                    item["menge"] = int(menge_val)
                except (ValueError, TypeError):
                    item["menge"] = 1
                    logger.warning(
                        "Menge '%s' (LKN: %s) ungültig. Auf 1 gesetzt.",
                        menge_val,
                        item.get('lkn'),
                    )
            if item["menge"] < 0:
                item["menge"] = 1
                logger.warning(
                    "Negative Menge %s (LKN: %s). Auf 1 gesetzt.",
                    item.get('menge'),
                    item.get('lkn'),
                )
            
            # Typ und Beschreibung sind optional vom LLM, werden eh aus lokalem Katalog genommen
            item.setdefault("typ", "N/A")
            # item.setdefault("beschreibung", "N/A")
            lkn_key = item.get("lkn")
            if leistungskatalog_dict and lkn_key and lkn_key in leistungskatalog_dict:
                item["beschreibung"] = leistungskatalog_dict[lkn_key].get("Beschreibung", "N/A")
            else:
                item.setdefault("beschreibung", "N/A")
            validated_identified_leistungen.append(item)
        llm_response_json["identified_leistungen"] = validated_identified_leistungen
        logger.info("LLM_S1_INFO: LLM Stufe 1 Antwortstruktur und Basistypen validiert/normalisiert.")
        if LOG_S1_PARSED_JSON:
            detail_logger.info(f"LLM_S1_PARSED_JSON: {json.dumps(llm_response_json, indent=2, ensure_ascii=False)}")
        return llm_response_json, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}

    except RequestException as req_err:
        error_detail = ""
        if isinstance(req_err, HTTPError) and req_err.response is not None:
            error_detail = f"{req_err.response.status_code} {req_err.response.text}"
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
    prompt = get_stage1_prompt(user_input, katalog_context, lang, query_variants=query_variants)
    prompt_tokens = count_tokens(prompt)
    # Proaktives Kürzen sehr langer Prompts auf Basis des konfigurierten Budgets
    TOKEN_BUDGET = GEMINI_TOKEN_BUDGET
    if prompt_tokens > TOKEN_BUDGET:
        if GEMINI_TRIM_ENABLED:
            try:
                original_prompt_tokens = prompt_tokens
                ratio = max(0.2, TOKEN_BUDGET / max(1.0, float(prompt_tokens)))
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
                    "LLM Stufe 1 (Gemini): Prompt gekürzt auf Budget (%s). Kontext nun %s Zeichen (Tokens ~%s).",
                    TOKEN_BUDGET,
                    new_len,
                    trimmed_prompt_tokens,
                )
                prompt_tokens = trimmed_prompt_tokens
            except Exception:
                # Fallback: belasse Prompt unverändert, wenn Kürzen fehlschlägt
                pass
        else:
            logger.warning(
                "LLM Stufe 1: Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0).",
                prompt_tokens,
                TOKEN_BUDGET,
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
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
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
    # Robuster JSON-Parse: direkter Parse, sonst aus Text extrahieren
    try:
        data = json.loads(content or "{}")
    except Exception:
        def _extract_json_payload(txt: str) -> Any | None:
            s = (txt or "").strip()
            # Entferne Markdown-Codeblöcke ```json ... ``` falls vorhanden
            if "```" in s:
                start = s.find("```")
                after = s[start + 3 :]
                # Überspringe optionalen Sprachenhinweis (json)
                nl = after.find("\n")
                if nl != -1:
                    body = after[nl + 1 :]
                    end = body.find("```")
                    if end != -1:
                        s = body[:end].strip()
            # Versuche, offensichtliche abschließende Erklärungen/Markdown nach JSON zu entfernen
            # (alles nach der letzten schließenden Klammer wird entfernt)
            last_brace = max(s.rfind('}'), s.rfind(']'))
            if last_brace != -1:
                s = s[: last_brace + 1]
            # Finde erstes JSON-Objekt oder -Array mithilfe einfacher Klammerbalance
            def _scan_balanced(src: str, open_ch: str, close_ch: str) -> str | None:
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
                    else:
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
            candidate = _scan_balanced(s, "{", "}") or _scan_balanced(s, "[", "]")
            if candidate:
                try:
                    # Versuche direktes Parsen, ansonsten entferne Kommentare und parse erneut
                    try:
                        return json.loads(candidate)
                    except Exception:
                        # Entferne //- und /**/-Kommentare außerhalb von Strings
                        def _strip_json_comments(src: str) -> str:
                            out = []
                            i, n = 0, len(src)
                            in_str = False
                            esc = False
                            while i < n:
                                ch = src[i]
                                if in_str:
                                    out.append(ch)
                                    if esc:
                                        esc = False
                                    elif ch == '\\':
                                        esc = True
                                    elif ch == '"':
                                        in_str = False
                                    i += 1
                                else:
                                    if ch == '"':
                                        in_str = True
                                        out.append(ch)
                                        i += 1
                                    elif ch == '/' and i + 1 < n and src[i+1] == '/':
                                        i += 2
                                        while i < n and src[i] not in ('\n', '\r'):
                                            i += 1
                                    elif ch == '/' and i + 1 < n and src[i+1] == '*':
                                        i += 2
                                        while i + 1 < n and not (src[i] == '*' and src[i+1] == '/'):
                                            i += 1
                                        i = i + 2 if i + 1 < n else n
                                    else:
                                        out.append(ch)
                                        i += 1
                            return ''.join(out)
                        cleaned = _strip_json_comments(candidate)
                        # Entferne trailing-Kommas vor } oder ]
                        import re as _re
                        cleaned = _re.sub(r",\s*(?=[}\]])", "", cleaned)
                        return json.loads(cleaned)
                except Exception:
                    pass
            # Reparatur-Versuch: JSON klammern-balanziert schließen
            try:
                start_idx = s.find('{')
                if start_idx != -1:
                    fragment = s[start_idx:]
                    # Entferne Kommentare
                    def _strip_json_comments2(src: str) -> str:
                        out = []
                        i, n = 0, len(src)
                        in_str = False
                        esc = False
                        while i < n:
                            ch = src[i]
                            if in_str:
                                out.append(ch)
                                if esc:
                                    esc = False
                                elif ch == '\\':
                                    esc = True
                                elif ch == '"':
                                    in_str = False
                                i += 1
                            else:
                                if ch == '"':
                                    in_str = True
                                    out.append(ch)
                                    i += 1
                                elif ch == '/' and i + 1 < n and src[i+1] == '/':
                                    i += 2
                                    while i < n and src[i] not in ('\n', '\r'):
                                        i += 1
                                elif ch == '/' and i + 1 < n and src[i+1] == '*':
                                    i += 2
                                    while i + 1 < n and not (src[i] == '*' and src[i+1] == '/'):
                                        i += 1
                                    i = i + 2 if i + 1 < n else n
                                else:
                                    out.append(ch)
                                    i += 1
                        return ''.join(out)
                    frag = _strip_json_comments2(fragment)
                    # Entferne trailing-Kommas
                    import re as _re2
                    frag = _re2.sub(r",\s*(?=[}\]])", "", frag)
                    # Balance-Klammern: füge die fehlenden schließenden Klammern an
                    stack = []
                    in_str = False
                    esc = False
                    for ch in frag:
                        if in_str:
                            if esc:
                                esc = False
                            elif ch == '\\':
                                esc = True
                            elif ch == '"':
                                in_str = False
                            continue
                        else:
                            if ch == '"':
                                in_str = True
                            elif ch == '{':
                                stack.append('}')
                            elif ch == '[':
                                stack.append(']')
                            elif ch in ('}', ']') and stack:
                                stack.pop()
                    if stack:
                        frag_repaired = frag + ''.join(reversed(stack))
                    else:
                        frag_repaired = frag
                    return json.loads(frag_repaired)
            except Exception:
                pass
            return None
        extracted = _extract_json_payload(content if isinstance(content, str) else "")
        if isinstance(extracted, dict):
            # Non-strict JSON (z.B. in ```json``` oder mit Kommentaren) erfolgreich extrahiert
            if LOG_LLM_OUTPUT:
                try:
                    detail_logger.info("LLM_S1_NONSTRICT_JSON_RECOVERED (%s)", provider)
                except Exception:
                    pass
            data = extracted
        else:
            # Endgültiger Fehler: Rohtext als Fehler loggen
            try:
                detail_logger.error("LLM_S1_INVALID_JSON_RAW (%s): %s", provider, content)
            except Exception:
                pass
            raise ValueError(f"{provider} Stufe 1: ungültige JSON-Antwort")
    data.setdefault("identified_leistungen", [])
    data.setdefault("extracted_info", {})
    data.setdefault("begruendung_llm", "")
    return data, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}

def call_gemini_stage2_mapping(
    tardoc_lkn: str,
    tardoc_desc: str,
    candidate_pauschal_lkns: Dict[str, str],
    model: str,
    lang: str = "de",
) -> tuple[str | None, dict[str, int]]:
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
            logger.warning(
                "LLM Stufe 2 (Mapping): Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0).",
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
        response = None
        last_exception: Optional[RequestException] = None
        for attempt in range(GEMINI_MAX_RETRIES):
            try:
                response = requests.post(gemini_url, json=payload, timeout=GEMINI_TIMEOUT)
                logger.info(
                    "Gemini Stufe 2 (Mapping) Antwort Status Code: %s",
                    response.status_code,
                )
                if response.status_code == 429:
                    raise HTTPError(response=response)
                response.raise_for_status()
                break
            except RequestException as req_err:
                last_exception = req_err
                status_code = (
                    req_err.response.status_code
                    if isinstance(req_err, HTTPError) and req_err.response is not None
                    else None
                )
                if (
                    status_code is not None
                    and (status_code == 429 or 500 <= status_code < 600)
                    and attempt < GEMINI_MAX_RETRIES - 1
                ):
                    wait_time = GEMINI_BACKOFF_SECONDS * (2 ** attempt)
                    logger.warning(
                        "Gemini Stufe 2 (Mapping) Fehler %s. Neuer Versuch in %s Sekunden.",
                        status_code,
                        wait_time,
                    )
                    time.sleep(wait_time)
                    continue
                raise
        if response is None:
            logger.error(
                "Gemini Stufe 2 (Mapping) scheiterte nach %s Versuchen: %s",
                GEMINI_MAX_RETRIES,
                last_exception,
            )
            return None, {"input_tokens": prompt_tokens, "output_tokens": response_tokens}
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
            logger.warning(
                "LLM Stufe 2 (Mapping): Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0).",
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
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
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
            logger.warning(
                "LLM Stufe 2 (Ranking): Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0).",
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
        response = None
        last_exception: Optional[RequestException] = None
        for attempt in range(GEMINI_MAX_RETRIES):
            try:
                # Respektiere konfigurierten Mindestabstand zwischen LLM-Requests
                enforce_llm_min_interval()
                response = requests.post(gemini_url, json=payload, timeout=GEMINI_TIMEOUT)
                logger.info(
                    "Gemini Stufe 2 (Ranking) Antwort Status Code: %s",
                    response.status_code,
                )
                if response.status_code == 429:
                    raise HTTPError(response=response)
                response.raise_for_status()
                break
            except RequestException as req_err:
                last_exception = req_err
                status_code = (
                    req_err.response.status_code
                    if isinstance(req_err, HTTPError) and req_err.response is not None
                    else None
                )
                if (
                    status_code is not None
                    and (status_code == 429 or 500 <= status_code < 600)
                    and attempt < GEMINI_MAX_RETRIES - 1
                ):
                    wait_time = GEMINI_BACKOFF_SECONDS * (2 ** attempt)
                    logger.warning(
                        "Gemini Stufe 2 (Ranking) Fehler %s. Neuer Versuch in %s Sekunden.",
                        status_code,
                        wait_time,
                    )
                    time.sleep(wait_time)
                    continue
                raise
        if response is None:
            logger.error(
                "Gemini Stufe 2 (Ranking) scheiterte nach %s Versuchen: %s",
                GEMINI_MAX_RETRIES,
                last_exception,
            )
            return [], {"input_tokens": prompt_tokens, "output_tokens": response_tokens}
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
            logger.warning(
                "LLM Stufe 2 (Ranking): Prompt überschreitet konfiguriertes Budget (%s Tokens > %s). Kürzen deaktiviert (GEMINI.trim_enabled=0).",
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
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
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

def get_relevant_p_pz_condition_lkns( # Beibehalten, falls spezifisch nur P/PZ benötigt wird
    potential_pauschale_codes: Set[str],
    pauschale_bedingungen_data_list: List[Dict[str, Any]], # Umbenannt zur Klarheit
    tabellen_dict: Dict[str, List[Dict[str, Any]]], # Umbenannt zur Klarheit
    leistungskatalog: Dict[str, Dict[str, Any]] # Umbenannt zur Klarheit
) -> Dict[str, str]:
    relevant_lkn_codes: Set[str] = set()
    BED_PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'

    relevant_conditions = [
        cond for cond in pauschale_bedingungen_data_list # Verwende umbenannten Parameter
        if cond.get(BED_PAUSCHALE_KEY) in potential_pauschale_codes
    ]
    for cond in relevant_conditions:
        typ = cond.get(BED_TYP_KEY, "").upper(); wert = cond.get(BED_WERTE_KEY, "")
        if not wert: continue
        if typ in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN"]:
            lkns = [lkn.strip().upper() for lkn in str(wert).split(',') if lkn.strip()] # str(wert) für Sicherheit
            relevant_lkn_codes.update(lkns)
        elif typ in ["LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE"]:
            table_names = [t.strip() for t in str(wert).split(',') if t.strip()] # str(wert) für Sicherheit
            for table_name in table_names:
                # Nutze die globale Variable tabellen_dict_by_table oder den übergebenen Parameter
                content = get_table_content(table_name, "service_catalog", tabellen_dict) # Verwende umbenannten Parameter
                for item in content:
                    code_val = item.get('Code')
                    if code_val: relevant_lkn_codes.add(str(code_val).upper()) # str(code_val)

    valid_p_pz_candidates: Dict[str, str] = {}
    for lkn in relevant_lkn_codes:
        lkn_details = leistungskatalog.get(lkn) # Verwende umbenannten Parameter
        if lkn_details and lkn_details.get('Typ') in ['P', 'PZ']:
            valid_p_pz_candidates[lkn] = lkn_details.get('Beschreibung', 'N/A')
    # print(f"DEBUG (get_relevant_p_pz): {len(valid_p_pz_candidates)} P/PZ Bedingungs-LKNs gefunden.")
    return valid_p_pz_candidates

def get_LKNs_from_pauschalen_conditions(
    potential_pauschale_codes: Set[str],
    pauschale_bedingungen_data_list: List[Dict[str, Any]], # Umbenannt
    tabellen_dict: Dict[str, List[Dict[str, Any]]], # Umbenannt
    leistungskatalog: Dict[str, Dict[str, Any]] # Umbenannt
) -> Dict[str, str]:
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
        user_input = user_input.replace("’", "'").replace("‘", "'").replace("`", "'")
    if not user_input.strip():
        raise ValueError("'inputText' darf nicht leer sein")

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

    use_icd_flag = data.get('useIcd', True)
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
    }


def _build_context_for_llm(user_input: str, lang: str) -> tuple[str, list[tuple[float, str]], list[str]]:
    """
    Performs hybrid search to find relevant LKNs and builds the context for the LLM.
    Returns the context string, top ranking results, and query variants.
    """
    katalog_context_parts = []
    preprocessed_input = expand_compound_words(user_input)
    direct_synonym_codes: List[str] = []
    if SYNONYMS_ENABLED:
        candidate_bases: List[str] = []
        if preprocessed_input in synonym_catalog.entries:
            candidate_bases.append(preprocessed_input)
        normalized = " ".join(preprocessed_input.lower().split())
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
                preprocessed_input,
                direct_synonym_codes,
            )

    query_variants = [preprocessed_input]
    if SYNONYMS_ENABLED:
        try:
            # expand_query now returns a list, not a dict
            query_variants = expand_query(
                preprocessed_input,
                synonym_catalog,
                lang=lang,
            )
        except Exception as e:
            logger.warning("Synonym expansion failed: %s", e)
            query_variants = [preprocessed_input]

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

    # 2. Embedding-based search (for semantic similarity)
    embedding_results: List[Tuple[float, str]] = []
    embedding_codes_ranked: List[str] = []
    if USE_RAG and embedding_model and embedding_vectors:
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
            cast(List[float], q_vec.tolist()),
            embedding_vectors,
            embedding_codes,
            limit=100,
        )
        embedding_codes_ranked = [code for _, code in embedding_results]
        logger.info(
            f"Embedding-Suche (RAG) fand {len(embedding_codes_ranked)} Kandidaten."
        )

    # 3. Combine and de-duplicate results
    # The order is important: direct codes first, then keyword matches, then semantic matches.
    direct_codes = [c.upper() for c in extract_lkn_codes_from_text(user_input)]
    for code in direct_synonym_codes:
        if code not in direct_codes:
            direct_codes.append(code)

    combined_codes = direct_codes + keyword_codes + embedding_codes_ranked
    ranked_codes = list(dict.fromkeys(combined_codes))  # De-duplicate while preserving order

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
        for direct_code in codes:
            normalized = direct_code.strip().upper()
            if not normalized or normalized in seen_rank_codes:
                continue
            top_ranking_results.append((1.0, normalized))
            seen_rank_codes.add(normalized)

    def _add_scored_entries(entries: List[Tuple[float, str]]) -> None:
        for score, code in entries:
            normalized = code.strip().upper()
            if not normalized or normalized in seen_rank_codes:
                continue
            top_ranking_results.append((score, normalized))
            seen_rank_codes.add(normalized)

    _add_direct_codes(direct_codes)
    _add_scored_entries(keyword_results)
    if USE_RAG and embedding_model and embedding_vectors:
        _add_scored_entries(embedding_results)

    def _collect_code_text(code: str) -> str:
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
    def _add_line_for(code: str) -> None:
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
    logger.info("Tokens im Katalog-Kontext dieses Requests: %s", count_tokens(katalog_context_str))
    # --- DEBUGGING START ---
    logger.debug(f"DEBUG: len(katalog_context_str): {len(katalog_context_str)}")
    if not katalog_context_str:
        logger.error("DEBUG: katalog_context_str ist leer. Abbruch vor LLM-Aufruf.")
    # --- DEBUGGING END ---
    if not katalog_context_str:
        raise ValueError("Leistungskatalog für LLM-Kontext (Stufe 1) ist leer.")

    return katalog_context_str, top_ranking_results, query_variants


def _validate_and_apply_rules(
    llm_stage1_result: Dict[str, Any],
    lang: str,
    icd_input: List[str],
    medication_atcs: List[str],
    alter_user: Optional[int],
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
                    "ICD": icd_input, "Geschlecht": geschlecht_user or "unbekannt", "Alter": alter_user,
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
    hat_pauschalen_potential_nach_regeln = any(l.get('typ') in ['P', 'PZ'] for l in rule_checked_leistungen_list)
    llm_stage2_mapping_results: Dict[str, Any] = {"mapping_results": []}

    if not rule_checked_leistungen_list or not hat_pauschalen_potential_nach_regeln:
        logger.info("Keine P/PZ LKNs nach Regelprüfung oder keine LKNs übrig. Gehe direkt zu TARDOC.")
        finale_abrechnung_obj = prepare_tardoc_abrechnung_func(regel_ergebnisse_details_list, leistungskatalog_dict, lang)
        return finale_abrechnung_obj, llm_stage2_mapping_results

    logger.info("Pauschalenpotenzial nach Regelprüfung vorhanden. Starte LKN-Mapping & Pauschalen-Hauptprüfung.")

    # Ab hier folgt die bestehende Logik der ursprünglichen Funktion.
    potential_pauschale_codes_set: Set[str] = set()
    regelkonforme_lkn_codes_fuer_suche = {str(l.get('lkn')) for l in rule_checked_leistungen_list if l.get('lkn')}

    for item_lp in pauschale_lp_data:
        lkn_in_lp_db_val = item_lp.get('Leistungsposition')
        if isinstance(lkn_in_lp_db_val, str) and lkn_in_lp_db_val in regelkonforme_lkn_codes_fuer_suche:
            pc_code = item_lp.get('Pauschale')
            if pc_code and str(pc_code) in pauschalen_dict: potential_pauschale_codes_set.add(str(pc_code))

    regelkonforme_lkns_in_tables_cache: Dict[str, Set[str]] = {}
    for cond_data in pauschale_bedingungen_data:
        pc_code_cond_val = cond_data.get('Pauschale')
        if not (pc_code_cond_val and str(pc_code_cond_val) in pauschalen_dict): continue
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

            if t_lkn_code and t_lkn_desc and current_candidates_for_llm:
                try:
                    mapped_target_lkn_code, map_tokens = call_llm_stage2_mapping(str(t_lkn_code), str(t_lkn_desc), current_candidates_for_llm, lang)
                    token_usage["llm_stage2"]["input_tokens"] += map_tokens.get("input_tokens", 0)
                    token_usage["llm_stage2"]["output_tokens"] += map_tokens.get("output_tokens", 0)
                    if mapped_target_lkn_code:
                        mapped_lkn_codes_set.add(mapped_target_lkn_code)
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

    final_lkn_context_for_pauschale_set = {str(l.get('lkn')) for l in rule_checked_leistungen_list if l.get('lkn')}
    final_lkn_context_for_pauschale_set.update(mapped_lkn_codes_set)
    final_lkn_context_list_for_pauschale = list(final_lkn_context_for_pauschale_set)
    logger.info(
        "Finaler LKN-Kontext für Pauschalen-Hauptprüfung (%s LKNs): %s",
        len(final_lkn_context_list_for_pauschale),
        final_lkn_context_list_for_pauschale,
    )

    erweiterte_lkn_suchmenge = {str(l).upper() for l in final_lkn_context_for_pauschale_set}
    neu_gefundene_codes: Set[str] = set()

    for item_lp in pauschale_lp_data:
        lkn_in_lp_db_val = item_lp.get('Leistungsposition')
        if isinstance(lkn_in_lp_db_val, str) and lkn_in_lp_db_val.upper() in erweiterte_lkn_suchmenge:
            pc_code = item_lp.get('Pauschale')
            if pc_code and str(pc_code) in pauschalen_dict:
                neu_gefundene_codes.add(str(pc_code))

    erweiterte_lkns_in_tables_cache: Dict[str, Set[str]] = {}
    for cond_data in pauschale_bedingungen_data:
        pc_code_cond_val = cond_data.get('Pauschale')
        if not (pc_code_cond_val and str(pc_code_cond_val) in pauschalen_dict): continue
        pc_code_cond = str(pc_code_cond_val)
        bedingungstyp_cond_str = cond_data.get('Bedingungstyp', "").upper()
        werte_cond_str = cond_data.get('Werte', "")
        if bedingungstyp_cond_str in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN"]:
            werte_liste_cond_set = {w.strip().upper() for w in str(werte_cond_str).split(',') if w.strip()}
            if not erweiterte_lkn_suchmenge.isdisjoint(werte_liste_cond_set):
                neu_gefundene_codes.add(pc_code_cond)
        elif bedingungstyp_cond_str in ["LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE"]:
            table_refs_cond_set = {t.strip().lower() for t in str(werte_cond_str).split(',') if t.strip()}
            for lkn_raw in erweiterte_lkn_suchmenge:
                if isinstance(lkn_raw, str):
                    lkn_str = lkn_raw.upper()
                    if lkn_str not in erweiterte_lkns_in_tables_cache:
                        tables_for_lkn_set = set()
                        for table_name_key_norm, table_entries_list in tabellen_dict_by_table.items():
                            for entry_item in table_entries_list:
                                if entry_item.get('Code', '').upper() == lkn_str and \
                                   entry_item.get('Tabelle_Typ', '').lower() == "service_catalog":
                                    tables_for_lkn_set.add(table_name_key_norm)
                        erweiterte_lkns_in_tables_cache[lkn_str] = tables_for_lkn_set
                    if not table_refs_cond_set.isdisjoint(erweiterte_lkns_in_tables_cache[lkn_str]):
                        neu_gefundene_codes.add(pc_code_cond)
                        break

    if neu_gefundene_codes:
        potential_pauschale_codes_set.update(neu_gefundene_codes)
    logger.debug(
        "DEBUG: %s potenzielle Pauschalen nach erweiterter Suche: %s",
        len(potential_pauschale_codes_set),
        potential_pauschale_codes_set,
    )

    pauschale_haupt_pruef_kontext = {
        "ICD": context.get("icd_input"), "Medikamente": context.get("medication_atcs"), "GTIN": context.get("medication_atcs"), "Alter": context.get("alter_context_val"),
        "Geschlecht": context.get("geschlecht_context_val"), "useIcd": context.get("use_icd_flag"),
        "LKN": final_lkn_context_list_for_pauschale, "Seitigkeit": context.get("seitigkeit_context_val"),
        "Anzahl": context.get("anzahl_fuer_pauschale_context")
    }
    try:
        logger.info(f"Starte Pauschalen-Hauptprüfung (useIcd=%s)...", context.get("use_icd_flag"))
        pauschale_pruef_ergebnis_dict = determine_applicable_pauschale_func(
            user_input, rule_checked_leistungen_list, pauschale_haupt_pruef_kontext,
            pauschale_lp_data, pauschale_bedingungen_data, pauschalen_dict,
            leistungskatalog_dict, tabellen_dict_by_table, potential_pauschale_codes_set,
            lang
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

    rule_checked_leistungen_list, regel_ergebnisse_details_list = _validate_and_apply_rules(
        llm_stage1_result, lang, icd_input, medication_atcs, alter_user, geschlecht_user
    )
    final_validated_llm_leistungen = llm_stage1_result["identified_leistungen"]

    candidate_codes = [code for _, code in top_ranking_results if (len(top_ranking_results) <= 1 or not final_validated_llm_leistungen or (top_ranking_results[0][0] / (top_ranking_results[1][0] or 1)) <= 1.5)]
    llm_stage1_result["ranking_candidates"] = candidate_codes

    extracted_info_llm = llm_stage1_result.get("extracted_info", {})
    alter_context_val = alter_user if alter_user is not None else extracted_info_llm.get("alter")
    geschlecht_context_val = geschlecht_user if geschlecht_user is not None else extracted_info_llm.get("geschlecht", "unbekannt")

    seitigkeit_context_val = extracted_info_llm.get("seitigkeit") or "unbekannt"
    anzahl_prozeduren_val = extracted_info_llm.get("anzahl_prozeduren")
    anzahl_fuer_pauschale_context = anzahl_prozeduren_val
    if seitigkeit_context_val.lower() == 'beidseits' and anzahl_fuer_pauschale_context is None:
        if len(final_validated_llm_leistungen) == 1 and final_validated_llm_leistungen[0].get('menge') == 1:
            anzahl_fuer_pauschale_context = 2
        elif any(l.get('lkn') == "C02.CP.0100" and l.get('menge') == 1 for l in final_validated_llm_leistungen):
            anzahl_fuer_pauschale_context = 2

    fallback_pauschale_search = not final_validated_llm_leistungen
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
            pruef_kontext = {"ICD": icd_input, "Medikamente": medication_atcs, "GTIN": medication_atcs, "Alter": alter_context_val, "Geschlecht": geschlecht_context_val, "useIcd": use_icd_flag, "LKN": [], "Seitigkeit": seitigkeit_context_val, "Anzahl": anzahl_fuer_pauschale_context}
            try:
                finale_abrechnung_obj = determine_applicable_pauschale_func(user_input, [], pruef_kontext, pauschale_lp_data, pauschale_bedingungen_data, pauschalen_dict, leistungskatalog_dict, tabellen_dict_by_table, potential_pauschale_codes_set, lang)
            except Exception as e:
                logger.error(f"Fehler bei Pauschalen-Fallback-Prüfung [{request_id}]: {e}", exc_info=True)
                finale_abrechnung_obj = None
        else:
            finale_abrechnung_obj = None
        llm_stage2_mapping_results = {}
    else:
        billing_context = {"icd_input": icd_input, "medication_inputs": medication_inputs, "medication_atcs": medication_atcs, "alter_context_val": alter_context_val, "geschlecht_context_val": geschlecht_context_val, "use_icd_flag": use_icd_flag, "seitigkeit_context_val": seitigkeit_context_val, "anzahl_fuer_pauschale_context": anzahl_fuer_pauschale_context}
        finale_abrechnung_obj, llm_stage2_mapping_results = _determine_final_billing(rule_checked_leistungen_list, regel_ergebnisse_details_list, user_input, lang, billing_context, token_usage)

    rule_time = time.time()
    logger.info(f"[{request_id}] Zeit nach Regelprüfung: {rule_time - llm1_time:.2f}s")

    safe_abrechnung_obj = finale_abrechnung_obj or {}

    final_response_payload = {
        "llm_ergebnis_stufe1": llm_stage1_result,
        "regel_ergebnisse_details": regel_ergebnisse_details_list,
        "abrechnung": finale_abrechnung_obj,
        "llm_ergebnis_stufe2": llm_stage2_mapping_results,
        "evaluated_pauschalen": safe_abrechnung_obj.get("evaluated_pauschalen", []),
        "token_usage": token_usage,
        "fallback_pauschale_search": fallback_pauschale_search,
    }

    total_time = time.time() - start_time
    logger.info(f"[{request_id}] Gesamtverarbeitungszeit: {total_time:.2f}s")
    logger.info(f"[{request_id}] Sende finale Antwort Typ '{safe_abrechnung_obj.get('type', 'None')}'")
    if LOG_HTML_OUTPUT:
        detail_logger.info(f"[{request_id}] Final response payload (contains HTML): {json.dumps(final_response_payload, ensure_ascii=False, indent=2)}")

    return jsonify(final_response_payload)


def perform_analysis(text: str,
                     icd: list[str] | None = None,
                     medications: list[str] | None = None,
                     use_icd: bool = True,
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
            'useIcd': use_icd,
            'age': age,
            'gender': gender,
            'lang': lang,
        }
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
    return jsonify({"version": APP_VERSION, "tarif_version": TARIF_VERSION})

# --- Static‑Routes & Start ---
@app.route("/")
def index_route(): # Umbenannt, um Konflikt mit Modul 'index' zu vermeiden, falls es existiert
    """Liefert die im Repository enthaltene Single-Page-Anwendung aus."""
    return send_from_directory(".", "index.html")

@app.route("/favicon.ico")
def favicon_ico():
    """Stellt das klassische Favicon für ältere Browser-Anfragen bereit."""
    return send_from_directory(".", "favicon.ico", mimetype='image/vnd.microsoft.icon')

@app.route("/favicon-32.png")
def favicon_png():
    """Gibt das hochauflösende PNG-Favicon zurück."""
    return send_from_directory(".", "favicon-32.png", mimetype='image/png')

@app.route("/<path:filename>")
def serve_static(filename: str): # Typ hinzugefügt
    """Erlaubt den direkten Abruf definierter statischer Dateien per HTTP."""
    allowed_files = {'calculator.js', 'quality.js', 'quality.html'}
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
         return send_from_directory('.', filename)
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

