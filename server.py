# server.py - Zweistufiger LLM-Ansatz mit Backend-Regelprüfung (Erweitert)
import os
import re
import json
import time # für Zeitmessung
import traceback # für detaillierte Fehlermeldungen
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, request, abort
import requests
from dotenv import load_dotenv
import regelpruefer # Dein Modul
from typing import Dict, List, Any, Set, Tuple, Callable # Tuple und Callable hinzugefügt
from utils import get_table_content # Angenommen, diese Funktion existiert in utils.py
import html

# --- Konfiguration ---
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', "gemini-1.5-flash-latest")
DATA_DIR = Path("data")
LEISTUNGSKATALOG_PATH = DATA_DIR / "tblLeistungskatalog.json"
REGELWERK_PATH = DATA_DIR / "strukturierte_regeln_komplett.json" # Prüfe diesen Pfad!
TARDOC_PATH = DATA_DIR / "TARDOCGesamt_optimiert_Tarifpositionen.json"
PAUSCHALE_LP_PATH = DATA_DIR / "tblPauschaleLeistungsposition.json"
PAUSCHALEN_PATH = DATA_DIR / "tblPauschalen.json"
PAUSCHALE_BED_PATH = DATA_DIR / "tblPauschaleBedingungen.json"
TABELLEN_PATH = DATA_DIR / "tblTabellen.json"

# --- Typ-Aliase für Klarheit ---
EvaluateStructuredConditionsType = Callable[[str, Dict[Any, Any], List[Dict[Any, Any]], Dict[str, List[Dict[Any, Any]]]], bool]
CheckPauschaleConditionsType = Callable[[str, Dict[Any, Any], List[Dict[Any, Any]], Dict[str, List[Dict[Any, Any]]], Dict[str, Dict[Any, Any]]], Dict[str, Any]]
GetSimplifiedConditionsType = Callable[[str, List[Dict[Any, Any]]], Set[Any]]
GenerateConditionDetailHtmlType = Callable[[Tuple[Any, ...], Dict[Any, Any], Dict[Any, Any]], str]
DetermineApplicablePauschaleType = Callable[
    [str, List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], Dict[str, Any], Dict[str, List[Dict[str, Any]]], Set[str]],
    Dict[str, Any]
]
PrepareTardocAbrechnungType = Callable[[List[Dict[Any,Any]], Dict[str, Dict[Any,Any]]], Dict[str,Any]]

# --- Standard-Fallbacks für Funktionen aus regelpruefer_pauschale ---
def default_evaluate_fallback( # Matches: evaluate_structured_conditions(pauschale_code: str, context: Dict, pauschale_bedingungen_data: List[Dict], tabellen_dict_by_table: Dict[str, List[Dict]]) -> bool
    pauschale_code: str,
    context: Dict[Any, Any],
    pauschale_bedingungen_data: List[Dict[Any, Any]],
    tabellen_dict_by_table: Dict[str, List[Dict[Any, Any]]]
) -> bool:
    print("WARNUNG: Fallback für 'evaluate_structured_conditions' aktiv.")
    return False

def default_check_html_fallback( # Matches: check_pauschale_conditions(pauschale_code: str, context: dict, pauschale_bedingungen_data: list[dict], tabellen_dict_by_table: Dict[str, List[Dict]], leistungskatalog_dict: Dict[str, Dict]) -> dict
    pauschale_code: str,
    context: Dict[Any, Any],
    pauschale_bedingungen_data: List[Dict[Any, Any]],
    tabellen_dict_by_table: Dict[str, List[Dict[Any, Any]]],
    leistungskatalog_dict: Dict[str, Dict[Any, Any]]
) -> Dict[str, Any]:
    print("WARNUNG: Fallback für 'check_pauschale_conditions' aktiv.")
    return {"html": "HTML-Prüfung nicht verfügbar (Fallback)", "errors": ["Fallback aktiv"], "trigger_lkn_condition_met": False}

def default_get_simplified_conditions_fallback( # Matches: get_simplified_conditions(pauschale_code: str, bedingungen_data: list[dict]) -> set
    pauschale_code: str,
    bedingungen_data: List[Dict[Any, Any]]
) -> Set[Any]:
    print("WARNUNG: Fallback für 'get_simplified_conditions' aktiv.")
    return set()

def default_generate_condition_detail_html_fallback(
    condition_tuple: Tuple[Any, ...], # Name aus Pylance-Fehler
    leistungskatalog_dict: Dict[Any, Any], # Name aus Pylance-Fehler
    tabellen_dict_by_table: Dict[Any, Any] # Name aus Pylance-Fehler
) -> str:
    print("WARNUNG: Fallback für 'generate_condition_detail_html' aktiv.")
    return "<li>Detail-Generierung fehlgeschlagen (Fallback)</li>"

def default_determine_applicable_pauschale_fallback(
    user_input_param: str, rule_checked_leistungen_list_param: List[Dict[str, Any]],
    pauschale_haupt_pruef_kontext_param: Dict[str, Any],
    pauschale_lp_data_param: List[Dict[str, Any]],
    pauschale_bedingungen_data_param: List[Dict[str, Any]],
    pauschalen_dict_param: Dict[str, Any],
    leistungskatalog_dict_param: Dict[str, Any],
    tabellen_dict_by_table_param: Dict[str, List[Dict[str, Any]]],
    potential_pauschale_codes_set_param: Set[str]
) -> Dict[str, Any]:
    print("WARNUNG: Fallback für 'determine_applicable_pauschale' aktiv.")
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
    # Für regelpruefer.py (LKN-Regeln)
    rp_lkn_module = None
    import regelpruefer as rp_lkn_module
    print("✓ Regelprüfer LKN (regelpruefer.py) Modul geladen.")
    if hasattr(rp_lkn_module, 'prepare_tardoc_abrechnung'):
        prepare_tardoc_abrechnung_func = rp_lkn_module.prepare_tardoc_abrechnung
        print("DEBUG: 'prepare_tardoc_abrechnung' aus regelpruefer.py zugewiesen.")
    else:
        print("FEHLER: 'prepare_tardoc_abrechnung' NICHT in regelpruefer.py gefunden! Verwende Fallback.")
        def prepare_tardoc_lkn_fb(r: List[Dict[Any,Any]], l: Dict[str, Dict[Any,Any]]) -> Dict[str,Any]:
            return {"type":"Error", "message":"TARDOC Prep Fallback (LKN Funktion fehlt)"}
        prepare_tardoc_abrechnung_func = prepare_tardoc_lkn_fb
except ImportError:
    print("FEHLER: regelpruefer.py nicht gefunden! Verwende Fallbacks für LKN-Regelprüfung.")
    def prepare_tardoc_lkn_import_fb(r: List[Dict[Any,Any]], l: Dict[str, Dict[Any,Any]]) -> Dict[str,Any]:
        return {"type":"Error", "message":"TARDOC Prep Fallback (LKN Modulimportfehler)"}
    prepare_tardoc_abrechnung_func = prepare_tardoc_lkn_import_fb

try:
    # Für regelpruefer_pauschale.py
    print("INFO: Versuche, regelpruefer_pauschale.py zu importieren...")
    import regelpruefer_pauschale as rpp_module
    print(f"DEBUG: Importversuch abgeschlossen. rpp_module ist: {rpp_module}")
    print(f"DEBUG: Inhalt von rpp_module: {dir(rpp_module)}")
    print("✓ Regelprüfer Pauschalen (regelpruefer_pauschale.py) Modul geladen.")

    if rpp_module and hasattr(rpp_module, 'evaluate_structured_conditions'):
        evaluate_structured_conditions = rpp_module.evaluate_structured_conditions
    else: print("FEHLER: 'evaluate_structured_conditions' nicht in regelpruefer_pauschale.py (oder Modul nicht geladen)! Fallback aktiv.")

    if rpp_module and hasattr(rpp_module, 'check_pauschale_conditions'):
        check_pauschale_conditions = rpp_module.check_pauschale_conditions
    else: print("FEHLER: 'check_pauschale_conditions' nicht in regelpruefer_pauschale.py (oder Modul nicht geladen)! Fallback aktiv.")

    if rpp_module and hasattr(rpp_module, 'get_simplified_conditions'):
        get_simplified_conditions = rpp_module.get_simplified_conditions
    else: print("FEHLER: 'get_simplified_conditions' nicht in regelpruefer_pauschale.py (oder Modul nicht geladen)! Fallback aktiv.")

    if rpp_module and hasattr(rpp_module, 'generate_condition_detail_html'):
        generate_condition_detail_html = rpp_module.generate_condition_detail_html
    else: print("FEHLER: 'generate_condition_detail_html' nicht in regelpruefer_pauschale.py (oder Modul nicht geladen)! Fallback aktiv.")

    if rpp_module and hasattr(rpp_module, 'determine_applicable_pauschale'):
        determine_applicable_pauschale_func = rpp_module.determine_applicable_pauschale
        print("DEBUG: 'determine_applicable_pauschale' aus regelpruefer_pauschale.py zugewiesen.")
    else: print("FEHLER: 'determine_applicable_pauschale' nicht in regelpruefer_pauschale.py (oder Modul nicht geladen)! Fallback aktiv.")

except ImportError as e_imp:
    print(f"FEHLER (ImportError): regelpruefer_pauschale.py konnte nicht importiert werden: {e_imp}! Standard-Fallbacks bleiben aktiv.")
    traceback.print_exc()
except Exception as e_gen: # Fängt auch andere Fehler während des Imports
    print(f"FEHLER (Allgemein beim Import): Ein Fehler trat beim Laden von regelpruefer_pauschale.py auf: {e_gen}! Standard-Fallbacks bleiben aktiv.")
    traceback.print_exc()
    # Setze rpp_module auf None, um hasattr-Fehler unten zu vermeiden, falls es nicht initialisiert wurde
    rpp_module = None # Sicherstellen, dass es definiert ist, auch wenn der Import fehlschlug

# --- Globale Datencontainer ---
app = Flask(__name__, static_folder='.', static_url_path='') # Flask App Instanz
leistungskatalog_data: list[dict] = []
leistungskatalog_dict: dict[str, dict] = {}
regelwerk_dict: dict[str, list] = {} # Annahme: lade_regelwerk gibt List[RegelDict] pro LKN
tardoc_data_dict: dict[str, dict] = {}
pauschale_lp_data: list[dict] = []
pauschalen_data: list[dict] = []
pauschalen_dict: dict[str, dict] = {}
pauschale_bedingungen_data: list[dict] = []
tabellen_data: list[dict] = []
tabellen_dict_by_table: dict[str, list[dict]] = {}
daten_geladen: bool = False

def create_app() -> Flask:
    """
    Erstellt die Flask-Instanz.  
    Render (bzw. Gunicorn) ruft diese Factory einmal pro Worker auf
    und bekommt das WSGI-Objekt zurück.
    """
    app = Flask(__name__, static_folder='.', static_url_path='')

    # Daten nur einmal laden – egal ob lokal oder Render-Worker
    global daten_geladen
    if not daten_geladen:
        print("INFO: Initialer Daten-Load beim App-Start …")
        if not load_data():
            raise RuntimeError("Kritische Daten konnten nicht geladen werden.")

    # Ab hier bleiben alle @app.route-Dekorationen unverändert
    return app

# --- Daten laden Funktion ---
def load_data() -> bool:
    global leistungskatalog_data, leistungskatalog_dict, regelwerk_dict, tardoc_data_dict
    global pauschale_lp_data, pauschalen_data, pauschalen_dict, pauschale_bedingungen_data, tabellen_data
    global tabellen_dict_by_table, daten_geladen

    all_loaded_successfully = True
    print("--- Lade Daten ---")
    # Reset all data containers
    leistungskatalog_data.clear(); leistungskatalog_dict.clear(); regelwerk_dict.clear(); tardoc_data_dict.clear()
    pauschale_lp_data.clear(); pauschalen_data.clear(); pauschalen_dict.clear(); pauschale_bedingungen_data.clear(); tabellen_data.clear()
    tabellen_dict_by_table.clear()

    files_to_load = {
        "Leistungskatalog": (LEISTUNGSKATALOG_PATH, leistungskatalog_data, 'LKN', leistungskatalog_dict),
        "PauschaleLP": (PAUSCHALE_LP_PATH, pauschale_lp_data, None, None),
        "Pauschalen": (PAUSCHALEN_PATH, pauschalen_data, 'Pauschale', pauschalen_dict),
        "PauschaleBedingungen": (PAUSCHALE_BED_PATH, pauschale_bedingungen_data, None, None),
        "TARDOC": (TARDOC_PATH, [], 'LKN', tardoc_data_dict), # TARDOC nur ins Dict
        "Tabellen": (TABELLEN_PATH, tabellen_data, None, None) # Tabellen nur in Liste (vorerst)
    }

    for name, (path, target_list_ref, key_field, target_dict_ref) in files_to_load.items():
        try:
            print(f"  Versuche {name} von {path} zu laden...")
            if path.is_file():
                with open(path, 'r', encoding='utf-8') as f:
                    data_from_file = json.load(f)

                if not isinstance(data_from_file, list):
                     print(f"  WARNUNG: {name}-Daten in '{path}' sind keine Liste, überspringe.")
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
                     print(f"  ✓ {name}-Daten '{path}' geladen ({items_in_dict} Einträge im Dict).")

                if target_list_ref is not None:
                     target_list_ref.clear() # target_list_ref ist die globale Liste
                     target_list_ref.extend(data_from_file)
                     if target_dict_ref is None: # Nur loggen, wenn nicht schon fürs Dict geloggt
                          print(f"  ✓ {name}-Daten '{path}' geladen ({len(target_list_ref)} Einträge in Liste).")

                if name == "Tabellen": # Spezifische Behandlung für 'Tabellen'
                    TAB_KEY = "Tabelle"
                    tabellen_dict_by_table.clear()
                    for item in data_from_file: # data_from_file ist hier der Inhalt von tblTabellen.json
                        if isinstance(item, dict):
                            table_name = item.get(TAB_KEY)
                            if table_name: # Stelle sicher, dass table_name nicht None ist
                                normalized_key = str(table_name).lower()
                                if normalized_key not in tabellen_dict_by_table:
                                    tabellen_dict_by_table[normalized_key] = []
                                tabellen_dict_by_table[normalized_key].append(item)
                    print(f"  ✓ Tabellen-Daten gruppiert nach Tabelle ({len(tabellen_dict_by_table)} Tabellen).")
                    missing_keys_check = ['cap13', 'cap14', 'or', 'nonor', 'nonelt', 'ambp.pz', 'anast', 'c08.50']
                    not_found_keys_check = {k for k in missing_keys_check if k not in tabellen_dict_by_table}
                    if not_found_keys_check:
                         print(f"  FEHLER: Kritische Tabellenschlüssel fehlen in tabellen_dict_by_table: {not_found_keys_check}!")
                         all_loaded_successfully = False
            else:
                print(f"  FEHLER: {name}-Datei nicht gefunden: {path}")
                if name in ["Leistungskatalog", "Pauschalen", "TARDOC", "PauschaleBedingungen", "Tabellen"]:
                    all_loaded_successfully = False
        except (json.JSONDecodeError, IOError, Exception) as e:
             print(f"  FEHLER beim Laden/Verarbeiten von {name} ({path}): {e}")
             all_loaded_successfully = False
             traceback.print_exc()

    # Lade Regelwerk LKN
    try:
        print(f"  Versuche Regelwerk (LKN) von {REGELWERK_PATH} zu laden...")
        # rp_lkn_module wurde oben importiert
        if rp_lkn_module and hasattr(rp_lkn_module, 'lade_regelwerk'):
            if REGELWERK_PATH.is_file():
                regelwerk_dict.clear()
                regelwerk_dict_loaded = rp_lkn_module.lade_regelwerk(str(REGELWERK_PATH))
                if regelwerk_dict_loaded: # Annahme: Gibt Dict[str, List[Regel]] zurück
                    regelwerk_dict.update(regelwerk_dict_loaded)
                    print(f"  ✓ Regelwerk (LKN) '{REGELWERK_PATH}' geladen ({len(regelwerk_dict)} LKNs).")
                else:
                    print(f"  FEHLER: LKN-Regelwerk konnte nicht geladen werden (Funktion gab leeres Dict zurück).")
                    all_loaded_successfully = False
            else:
                print(f"  FEHLER: Regelwerk (LKN) nicht gefunden: {REGELWERK_PATH}")
                regelwerk_dict.clear(); all_loaded_successfully = False
        else:
            print("  ℹ️ Regelprüfung (LKN) nicht verfügbar oder lade_regelwerk fehlt im Modul regelpruefer.")
            regelwerk_dict.clear()
    except Exception as e:
        print(f"  FEHLER beim Laden des LKN-Regelwerks: {e}")
        traceback.print_exc(); regelwerk_dict.clear(); all_loaded_successfully = False

    print("--- Daten laden abgeschlossen ---")
    if not all_loaded_successfully:
        print("WARNUNG: Einige kritische Daten konnten nicht geladen werden!")
        daten_geladen = False
    else:
        print("INFO: Alle Daten erfolgreich geladen.")
        daten_geladen = True
    print(f"DEBUG: load_data() beendet. leistungskatalog_dict leer? {not leistungskatalog_dict}")
    return all_loaded_successfully

# Einsatz von Flask
app = Flask(__name__, static_folder='.', static_url_path='') # Flask App Instanz
# Die App-Instanz, auf die Gunicorn zugreift
app: Flask = create_app()

# --- LLM Stufe 1: LKN Identifikation ---
def call_gemini_stage1(user_input: str, katalog_context: str) -> dict:
    if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY nicht konfiguriert.")

    prompt = f"""**Aufgabe:** Analysiere den folgenden medizinischen Behandlungstext aus der Schweiz äußerst präzise. Deine Aufgabe ist die Identifikation relevanter Leistungs-Katalog-Nummern (LKN), deren Menge und die Extraktion spezifischer Kontextinformationen basierend **ausschließlich** auf dem bereitgestellten Leistungskatalog.

**Kontext: Leistungskatalog (Dies ist die EINZIGE Quelle für gültige LKNs und deren Beschreibungen! Ignoriere jegliches anderes Wissen.)**
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**Anweisungen:** Führe die folgenden Schritte exakt aus:

1.  **LKN Identifikation & STRIKTE Validierung:**
    *   Lies den "Behandlungstext" sorgfältig.
    *   Identifiziere **alle** potenziellen LKN-Codes (Format `XX.##.####`), die die beschriebenen Tätigkeiten repräsentieren könnten.
    *   Bedenke, dass im Text mehrere Leistungen dokumentiert  mehrere LKNs gültig sein können (z.B. chirurgischer Eingriff PLUS/und/mit/;/./, Anästhesie). 
    *   **ABSOLUT KRITISCH:** Für JEDEN potenziellen LKN-Code: Überprüfe **BUCHSTABE FÜR BUCHSTABE und ZIFFER FÜR ZIFFER**, ob dieser Code **EXAKT** so im obigen "Leistungskatalog" als 'LKN:' vorkommt. Nur wenn der LKN-Code exakt existiert, prüfe, ob die **zugehörige Katalog-Beschreibung** zur im Text genannten Tätigkeit passt.
    *   Erstelle eine Liste (`identified_leistungen`) **AUSSCHLIESSLICH** mit den LKNs, die diese **exakte** Prüfung im Katalog bestanden haben UND deren Beschreibung zum Text passt.

2.  **Typ & Beschreibung hinzufügen:**
    *   Füge für jede **validierte** LKN in der `identified_leistungen`-Liste den korrekten `typ` und die `beschreibung` **direkt und unverändert aus dem bereitgestellten Katalogkontext für DIESE LKN** hinzu.

3.  **Kontextinformationen extrahieren (KRITISCH für Zusatzbedingungen):**
    *   Extrahiere **nur explizit genannte** Werte aus dem "Behandlungstext":
        *   `dauer_minuten` (Zahl, z.B. für Konsultationen)
        *   `menge_allgemein` (Zahl, z.B. "3 Warzen entfernt")
        *   `alter` (Zahl, Alter des Patienten)
        *   `geschlecht` ('weiblich', 'männlich', 'divers', 'unbekannt')
        *   `seitigkeit` (String: 'einseitig', 'beidseits', 'links', 'rechts', 'unbekannt'. Leite 'beidseits' auch von "bds." oder "beide Augen" etc. ab. Wenn keine Angabe, dann 'unbekannt'.)
        *   `anzahl_prozeduren` (Zahl: Falls eine Anzahl von Eingriffen genannt wird, die nicht direkt die Menge einer einzelnen LKN ist, z.B. "zwei Injektionen". Wenn nicht explizit genannt, dann `null`.)
    *   Wenn ein Wert nicht explizit genannt wird, setze ihn auf `null` (außer `seitigkeit`, die 'unbekannt' sein kann).

4.  **Menge bestimmen (pro validierter LKN):**
    *   Standardmenge ist `1`.
    *   **Zeitbasiert:** Wenn Katalog-Beschreibung "pro X Min" enthält UND `dauer_minuten` (Y) extrahiert wurde, setze `menge` = Y.
    *   **Allgemein:** Wenn `menge_allgemein` (Z) extrahiert wurde UND LKN nicht zeitbasiert ist UND `anzahl_prozeduren` `null` ist (oder nicht passt), setze `menge` = Z.
    *   **Spezifische Anzahl Prozeduren:** Wenn `anzahl_prozeduren` extrahiert wurde und sich klar auf die aktuelle LKN bezieht (z.B. "zwei Injektionen" und LKN ist Injektion), setze `menge` = `anzahl_prozeduren`. Dies hat Vorrang vor `menge_allgemein` für diese LKN.
    *   Sicherstellen: `menge` >= 1.

5.  **Begründung:**
    *   **Kurze** `begruendung_llm`, warum die **validierten** LKNs gewählt wurden. Beziehe dich auf Text und **Katalog-Beschreibungen**.

**Output-Format:** **NUR** valides JSON, **KEIN** anderer Text.
```json
{{
  "identified_leistungen": [
    {{
      "lkn": "VALIDIERTE_LKN_1",
      "typ": "TYP_AUS_KATALOG_1",
      "beschreibung": "BESCHREIBUNG_AUS_KATALOG_1",
      "menge": MENGE_ZAHL_LKN_1
    }}
  ],
  "extracted_info": {{
    "dauer_minuten": null,
    "menge_allgemein": null,
    "alter": null,
    "geschlecht": null,
    "seitigkeit": "unbekannt",
    "anzahl_prozeduren": null
  }},
  "begruendung_llm": "<Begründung>"
}}

Wenn absolut keine passende LKN aus dem Katalog gefunden wird, gib ein JSON-Objekt mit einer leeren "identified_leistungen"-Liste zurück.

Behandlungstext: "{user_input}"

JSON-Antwort:"""

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.05,
            "maxOutputTokens": 2048
        }
    }
    print(f"Sende Anfrage Stufe 1 an Gemini Model: {GEMINI_MODEL}...")
    try:
        response = requests.post(gemini_url, json=payload, timeout=90)
        print(f"Gemini Stufe 1 Antwort Status Code: {response.status_code}")
        response.raise_for_status()
        gemini_data = response.json()

        candidate: Dict[str, Any] | None = None # KORREKTUR: Initialisierung mit Typ
        raw_text_response: str = "" # KORREKTUR: Initialisierung mit Typ

        if gemini_data is None: # NEUE PRÜFUNG HIER
            error_details = "Fehler: Keine Daten von Gemini erhalten (gemini_data is None)."
            print(f"FEHLER: {error_details}")
            raise ValueError(error_details) # Oder eine andere Fehlerbehandlung

        if not gemini_data.get('candidates'): # Diese Prüfung ist jetzt sicher
            finish_reason_feedback = gemini_data.get('promptFeedback', {}).get('blockReason')
            safety_ratings_feedback = gemini_data.get('promptFeedback', {}).get('safetyRatings')
            error_details = f"Keine Kandidaten gefunden. Feedback: Reason={finish_reason_feedback}, Safety={safety_ratings_feedback}"
            print(f"WARNUNG: {error_details}")
            
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
                            # else: raw_text_response bleibt '', da first_part kein dict
                        # else: raw_text_response bleibt '', da parts leer
                    # else: raw_text_response bleibt '', da content kein dict
                # else: raw_text_response bleibt '', da candidate kein dict
            # else: raw_text_response bleibt '', da candidate_list leer oder kein list oder None

        if not raw_text_response:
            if candidate and isinstance(candidate, dict): # Modified condition
                finish_reason_candidate = candidate.get('finishReason', 'UNKNOWN')
                safety_ratings_candidate = candidate.get('safetyRatings')
                if finish_reason_candidate != 'STOP':
                    raise ValueError(f"Gemini stopped with reason: {finish_reason_candidate}, Safety: {safety_ratings_candidate}")
                else:
                    print("WARNUNG: Leere Textantwort von Gemini (candidate vorhanden, STOP).")
            elif candidate is None: # Explicitly handle the None case that Pylance is worried about
                # This 'else' corresponds to 'if candidate and isinstance(candidate, dict)' being false
                # because candidate was None.
                raise ValueError("Unerwarteter Zustand: Kein Candidate und keine Textantwort von Gemini (candidate was None).")
            else:
                # This 'else' handles the case where candidate is not None but also not a dict (should not happen with current typing)
                raise ValueError(f"Unerwarteter Zustand: Candidate is not a dict ({type(candidate)}) and no text response.")

        try:
            llm_response_json = json.loads(raw_text_response)
        except json.JSONDecodeError as json_err:
            if not raw_text_response.strip(): # Wenn der String komplett leer oder nur Whitespace ist
                print("WARNUNG: LLM Stufe 1 lieferte leeren String, der nicht als JSON geparst werden kann. Erstelle leeres Ergebnis.")
                # Erstelle ein leeres, aber valides Grundgerüst, um Folgefehler zu vermeiden
                llm_response_json = {
                    "identified_leistungen": [],
                    "extracted_info": {
                        "dauer_minuten": None, "menge_allgemein": None, "alter": None,
                        "geschlecht": None, "seitigkeit": "unbekannt", "anzahl_prozeduren": None
                    },
                    "begruendung_llm": "LLM lieferte leere Antwort."
                }
            else: # Es gab Text, aber er war kein valides JSON
                match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_text_response, re.IGNORECASE)
                if match:
                    try: llm_response_json = json.loads(match.group(1)); print("INFO: JSON aus Markdown extrahiert.")
                    except json.JSONDecodeError: raise ValueError(f"JSONDecodeError auch nach Markdown-Extraktion: {json_err}. Rohtext: {raw_text_response[:500]}...")
                else: raise ValueError(f"JSONDecodeError: {json_err}. Rohtext: {raw_text_response[:500]}...")

        print(f"DEBUG: Geparstes LLM JSON Stufe 1 VOR Validierung: {json.dumps(llm_response_json, indent=2, ensure_ascii=False)}")

        # Strikte Validierung der Hauptstruktur
        if not isinstance(llm_response_json, dict):
            raise ValueError("Antwort ist kein JSON-Objekt.")
        # Stelle sicher, dass die Schlüssel existieren, auch wenn sie leer sein könnten (nach dem leeren Fall oben)
        llm_response_json.setdefault("identified_leistungen", [])
        llm_response_json.setdefault("extracted_info", {})
        llm_response_json.setdefault("begruendung_llm", "N/A")


        if not isinstance(llm_response_json["identified_leistungen"], list):
            raise ValueError("'identified_leistungen' ist keine Liste.")
        if not isinstance(llm_response_json["extracted_info"], dict):
            raise ValueError("'extracted_info' ist kein Dictionary.")
        if not isinstance(llm_response_json["begruendung_llm"], str):
            llm_response_json["begruendung_llm"] = "N/A" # Default, wenn nicht String

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
                    try: validated_extracted_info[key] = int(val); conversion_successful = True; print(f"INFO: Wert für '{key}' ('{val}') zu int konvertiert.")
                    except (ValueError, TypeError): pass
                elif expected_type_tuple[0] is str and val is not None:
                    try: validated_extracted_info[key] = str(val); conversion_successful = True; print(f"INFO: Wert für '{key}' ('{val}') zu str konvertiert.")
                    except (ValueError, TypeError): pass
                if not conversion_successful:
                    validated_extracted_info[key] = default_value
                    print(f"WARNUNG: Typfehler für '{key}'. Erwartet {expected_type_tuple}, bekam {type(val)} ('{val}'). Default '{default_value}'.")
        llm_response_json["extracted_info"] = validated_extracted_info

        validated_identified_leistungen = []
        expected_leistung_keys = ["lkn", "typ", "beschreibung", "menge"]
        for i, item in enumerate(llm_response_json.get("identified_leistungen", [])): # Sicherer Zugriff
            if not isinstance(item, dict):
                print(f"WARNUNG: Element {i} in 'identified_leistungen' ist kein Dictionary. Übersprungen: {item}")
                continue
            # Minimalprüfung auf lkn und menge, da Typ/Beschreibung eh überschrieben werden
            lkn_val = item.get("lkn")
            menge_val = item.get("menge")

            if not isinstance(lkn_val, str) or not lkn_val.strip():
                print(f"WARNUNG: Ungültige oder leere LKN in Element {i}. Übersprungen: {item}")
                continue
            item["lkn"] = lkn_val.strip().upper()

            if menge_val is None: item["menge"] = 1
            elif not isinstance(menge_val, int):
                try: item["menge"] = int(menge_val)
                except (ValueError, TypeError): item["menge"] = 1; print(f"WARNUNG: Menge '{menge_val}' (LKN: {item['lkn']}) ungültig. Auf 1 gesetzt.")
            if item["menge"] < 0: item["menge"] = 1; print(f"WARNUNG: Negative Menge {item['menge']} (LKN: {item['lkn']}). Auf 1 gesetzt.")
            
            # Typ und Beschreibung sind optional vom LLM, werden eh aus lokalem Katalog genommen
            item.setdefault("typ", "N/A")
            item.setdefault("beschreibung", "N/A")
            validated_identified_leistungen.append(item)
        llm_response_json["identified_leistungen"] = validated_identified_leistungen
        print("INFO: LLM Stufe 1 Antwortstruktur und Basistypen validiert/normalisiert.")
        return llm_response_json

    except requests.exceptions.RequestException as req_err:
        print(f"FEHLER: Netzwerkfehler bei Gemini Stufe 1: {req_err}")
        raise ConnectionError(f"Netzwerkfehler bei Gemini Stufe 1: {req_err}")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as proc_err:
        print(f"FEHLER: Fehler beim Verarbeiten der LLM Stufe 1 Antwort: {proc_err}")
        traceback.print_exc()
        raise ValueError(f"Verarbeitungsfehler LLM Stufe 1: {proc_err}")
    except Exception as e:
        print(f"FEHLER: Unerwarteter Fehler im LLM Stufe 1: {e}")
        traceback.print_exc()
        raise e

def call_gemini_stage2_mapping(tardoc_lkn: str, tardoc_desc: str, candidate_pauschal_lkns: Dict[str, str]) -> str | None:
    if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY nicht konfiguriert.")
    if not candidate_pauschal_lkns:
        print(f"WARNUNG (Mapping): Keine Kandidaten-LKNs für Mapping von {tardoc_lkn} übergeben.")
        return None

    candidates_text = "\n".join([f"- {lkn}: {desc}" for lkn, desc in candidate_pauschal_lkns.items()])
    if len(candidates_text) > 15000: # Limit Kontextlänge (Anpassen nach Bedarf)
        print(f"WARNUNG (Mapping): Kandidatenliste für {tardoc_lkn} zu lang ({len(candidates_text)} Zeichen), wird gekürzt.")
        candidates_text = candidates_text[:15000] + "\n..." # Einfache Kürzung

    prompt = f"""**Aufgabe:** Du bist ein Experte für medizinische Abrechnungssysteme in der Schweiz (TARDOC und Pauschalen). Deine Aufgabe ist es, für die gegebene TARDOC-Einzelleistung (Typ E/EZ) die funktional **äquivalente** Leistung aus der "Kandidatenliste" zu finden. Die Kandidatenliste enthält LKNs (aller Typen, oft P/PZ), die als Bedingungen in potenziell relevanten Pauschalen vorkommen.

**Gegebene TARDOC-Leistung (Typ E/EZ):**
*   LKN: {tardoc_lkn}
*   Beschreibung: {tardoc_desc}
*   Kontext: Diese Leistung (z.B. eine spezifische Anästhesie) wurde im Rahmen einer Behandlung erbracht, für die eine Pauschalenabrechnung geprüft wird.

**Mögliche Äquivalente (Kandidatenliste - LKNs für Pauschalen-Bedingungen):**
Finde aus DIESER spezifischen Liste die Kandidaten-LKN, die die **gleiche Art von medizinischer Tätigkeit** wie die gegebene TARDOC-Leistung beschreibt (z.B. `AG.*` entspricht oft einer `WA.*`-LKN).
--- Kandidaten Start ---
{candidates_text}
--- Kandidaten Ende ---

**Analyse & Entscheidung:**
1.  Verstehe die **medizinische Kernfunktion** der gegebenen TARDOC-Leistung (z.B. "Anästhesie", "Bildgebung", "Laboranalyse").
2.  Identifiziere die Kandidaten-LKN aus der Liste, die diese Kernfunktion am besten repräsentiert. Achte auf spezifische Übereinstimmungen (z.B. Anästhesie-Typ).
3.  Priorisiere nach Passgenauigkeit, falls mehrere Kandidaten sehr ähnlich sind. Die spezifischste Übereinstimmung zuerst.

**Antwort:**
*   Gib eine **reine, kommagetrennte Liste** der LKN-Codes der passenden Kandidaten zurück. Beispiel: `WA.10.0010,WA.10.0020,WA.10.0030`
*   Wenn **keine** der Kandidaten-LKNs funktional passt, gib exakt das Wort `NONE` zurück.
*   Gib **absolut keinen anderen Text, keine Erklärungen, keine JSON-Formatierung oder Markdown** aus. NUR die reine Code-Liste (z.B. `CODE1,CODE2`) oder das Wort `NONE`.

Priorisierte Liste der besten Kandidaten-LKNs (nur reine kommagetrennte Liste oder NONE):"""

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json", # Beibehalten, da Gemini manchmal JSON sendet
            "temperature": 0.05,
            "maxOutputTokens": 512 # Für eine kurze Liste von Codes sollte das reichen
         }
    }
    print(f"Sende Anfrage Stufe 2 (Mapping) für {tardoc_lkn} an Gemini Model: {GEMINI_MODEL}...")
    try:
        response = requests.post(gemini_url, json=payload, timeout=60)
        print(f"Gemini Stufe 2 (Mapping) Antwort Status Code: {response.status_code}")
        response.raise_for_status()
        gemini_data = response.json()

        raw_text_response_part = ""
        if gemini_data.get('candidates'):
            candidate_list_map = gemini_data.get('candidates')
            if candidate_list_map and isinstance(candidate_list_map, list) and len(candidate_list_map) > 0:
                content_map = candidate_list_map[0].get('content', {})
                parts_map = content_map.get('parts', [{}])
                if parts_map and isinstance(parts_map, list) and len(parts_map) > 0:
                     raw_text_response_part = parts_map[0].get('text', '').strip()
        print(f"DEBUG: Roher Text von LLM Stufe 2 (Mapping) für {tardoc_lkn}: '{raw_text_response_part}'")

        if not raw_text_response_part:
            print(f"INFO: Kein passendes Mapping für {tardoc_lkn} gefunden (LLM-Antwort war leer).")
            return None
        if raw_text_response_part.upper() == "NONE":
            print(f"INFO: Kein passendes Mapping für {tardoc_lkn} gefunden (LLM sagte explizit NONE).")
            return None

        extracted_codes_from_llm = []
        try: # Versuche zuerst, als JSON zu parsen
            parsed_data = json.loads(raw_text_response_part)
            if isinstance(parsed_data, dict) and "EQUIVALENT_LKNS" in parsed_data and isinstance(parsed_data["EQUIVALENT_LKNS"], list):
                extracted_codes_from_llm = [str(code).strip().upper().replace('"', '') for code in parsed_data["EQUIVALENT_LKNS"] if str(code).strip()]
            elif isinstance(parsed_data, list): # Falls es direkt eine Liste ist
                extracted_codes_from_llm = [str(code).strip().upper().replace('"', '') for code in parsed_data if str(code).strip()]
        except json.JSONDecodeError: # Wenn kein JSON, dann als Text behandeln
            text_to_split = raw_text_response_part
            match_markdown = re.search(r'```(?:json|text)?\s*([\s\S]*?)\s*```', text_to_split, re.IGNORECASE) # Erkenne auch ```text
            if match_markdown:
                text_to_split = match_markdown.group(1).strip()
            
            # Entferne Anführungszeichen und splitte nach Komma
            extracted_codes_from_llm = [
                code.strip().upper().replace('"', '')
                for code in text_to_split.split(',')
                if code.strip() and code.strip().upper() != "NONE"
            ]
        
        print(f"INFO: Mapping-Antwort ({'JSON' if isinstance(extracted_codes_from_llm, list) and raw_text_response_part.startswith('[') or raw_text_response_part.startswith('{') else 'Text'}) geparst: {extracted_codes_from_llm}")

        for code in extracted_codes_from_llm:
            if code in candidate_pauschal_lkns:
                print(f"INFO: Mapping erfolgreich (aus Liste): {tardoc_lkn} -> {code}")
                return code

        if extracted_codes_from_llm: # Nur loggen, wenn LLM was zurückgab, das nicht passte
            print(f"WARNUNG: Keiner der vom Mapping-LLM zurückgegebenen Codes ({extracted_codes_from_llm}) war valide oder passte für {tardoc_lkn}.")
        else: # Fall, wo raw_text_response_part nicht NONE war, aber nichts extrahiert wurde
             print(f"WARNUNG: Kein passendes Mapping für {tardoc_lkn} gefunden (LLM-Antwort konnte nicht zu Codes geparst werden: '{raw_text_response_part}').")
        return None

    except requests.exceptions.RequestException as req_err:
        print(f"FEHLER: Netzwerkfehler bei Gemini Stufe 2 (Mapping): {req_err}")
        return None # Wichtig, um ConnectionError weiterzugeben
    except (KeyError, IndexError, TypeError, ValueError) as e:
        print(f"FEHLER beim Verarbeiten der Mapping-Antwort für {tardoc_lkn}: {e}")
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"FEHLER: Unerwarteter Fehler im LLM Stufe 2 (Mapping) für {tardoc_lkn}: {e}")
        traceback.print_exc()
        return None

# --- LLM Stufe 2: Pauschalen-Ranking ---
def call_gemini_stage2_ranking(user_input: str, potential_pauschalen_text: str) -> list[str]:
    if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY nicht konfiguriert.")
    prompt = f"""Basierend auf dem folgenden Behandlungstext, welche der unten aufgeführten Pauschalen passt inhaltlich am besten?
Berücksichtige die Beschreibung der Pauschale ('Pauschale_Text').
Gib eine priorisierte Liste der Pauschalen-Codes zurück, beginnend mit der besten Übereinstimmung.
Gib NUR die Pauschalen-Codes als kommagetrennte Liste zurück (z.B. "CODE1,CODE2,CODE3"). KEINE Begründung oder anderen Text.

Behandlungstext: "{user_input}"

Potenzielle Pauschalen:
--- Pauschalen Start ---
{potential_pauschalen_text}
--- Pauschalen Ende ---

Priorisierte Pauschalen-Codes (nur kommagetrennte Liste):"""

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = { "contents": [{"parts": [{"text": prompt}]}], "generationConfig": { "temperature": 0.1, "maxOutputTokens": 500 } }
    print(f"Sende Anfrage Stufe 2 (Ranking) an Gemini Model: {GEMINI_MODEL}...")
    try:
        response = requests.post(gemini_url, json=payload, timeout=45)
        print(f"Gemini Stufe 2 (Ranking) Antwort Status Code: {response.status_code}")
        response.raise_for_status()
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

        print(f"LLM Stufe 2 Gerankte Codes nach Filter: {ranked_codes} (aus Rohtext: '{ranked_text}')")
        if not ranked_codes and ranked_text: # Nur warnen, wenn Text da war, aber keine Codes extrahiert wurden
            print(f"WARNUNG: LLM Stufe 2 (Ranking) hat keine gültigen Codes aus '{ranked_text}' zurückgegeben.")
        elif not ranked_text:
            print("WARNUNG: LLM Stufe 2 (Ranking) hat leeren Text zurückgegeben.")
        return ranked_codes
    except requests.exceptions.RequestException as req_err:
        print(f"FEHLER: Netzwerkfehler bei Gemini Stufe 2 (Ranking): {req_err}")
        raise ConnectionError(f"Netzwerkfehler bei Gemini Stufe 2 (Ranking): {req_err}") # Wichtig für analyze_billing
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as e:
         print(f"FEHLER beim Extrahieren/Verarbeiten des Rankings: {e}")
         traceback.print_exc()
         return [] # Leere Liste, damit Fallback greift
    except Exception as e:
         print(f"FEHLER: Unerwarteter Fehler im LLM Stufe 2 (Ranking): {e}")
         traceback.print_exc()
         raise e # Erneut auslösen, um den Fehler im Hauptteil zu fangen

# get_table_content (aus utils.py, hier für Vollständigkeit, falls utils nicht verfügbar)
# Die Funktion get_table_content wurde bereits in utils.py definiert und hier importiert.
# Falls sie nicht in utils.py ist, müsste sie hier implementiert werden.
# Annahme: sie ist in utils.py und funktioniert korrekt.

# --- Ausgelagerte TARDOC-Vorbereitung ---
# prepare_tardoc_abrechnung wird jetzt über prepare_tardoc_abrechnung_func aufgerufen,
# die entweder die echte Funktion aus regelpruefer.py oder einen Fallback enthält.

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
    # print(f"  DEBUG (get_LKNs_from_pauschalen): {len(condition_lkns_with_desc)} einzigartige Bedingungs-LKNs gefunden.")
    return condition_lkns_with_desc

# get_pauschale_lkn_candidates: Diese Funktion war sehr ähnlich zu get_relevant_p_pz_condition_lkns.
# Ich habe sie entfernt, da get_LKNs_from_pauschalen_conditions alle LKNs holt und
# get_relevant_p_pz_condition_lkns spezifisch P/PZ filtert.
# Falls sie eine andere Logik hatte (z.B. alle Pauschalen durchsucht, nicht nur die potenziellen),
# müsste sie wiederhergestellt und angepasst werden.

# --- API Endpunkt ---
@app.route('/api/analyze-billing', methods=['POST'])
def analyze_billing():
    print("\n--- Request an /api/analyze-billing erhalten ---")
    start_time = time.time()

    if not daten_geladen:
        print("WARNUNG: Server-Daten nicht initialisiert. Versuche erneutes Laden...")
        if not load_data():
            print("FEHLER: Kritische Server-Daten konnten nicht geladen werden.")
            return jsonify({"error": "Kritische Server-Daten nicht initialisiert. Administrator kontaktieren."}), 503

    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()
    user_input = data.get('inputText', "") # Default zu leerem String
    icd_input_raw = data.get('icd', [])
    gtin_input_raw = data.get('gtin', [])
    use_icd_flag = data.get('useIcd', True)
    age_input = data.get('age')
    gender_input = data.get('gender')

    # Bereinige ICD und GTIN Eingaben
    icd_input = [str(i).strip().upper() for i in icd_input_raw if isinstance(i, str) and str(i).strip()]
    gtin_input = [str(g).strip().upper() for g in gtin_input_raw if isinstance(g, str) and str(g).strip()]


    try: alter_user = int(age_input) if age_input is not None and str(age_input).strip() else None
    except (ValueError, TypeError): alter_user = None; print(f"WARNUNG: Ungültiger Alterswert '{age_input}'.")
    
    geschlecht_user_raw = str(gender_input).lower().strip() if isinstance(gender_input, str) else None
    if geschlecht_user_raw and geschlecht_user_raw in ['männlich', 'weiblich', 'divers', 'unbekannt']:
        geschlecht_user = geschlecht_user_raw
    else:
        if geschlecht_user_raw: print(f"WARNUNG: Ungültiger Geschlechtswert '{gender_input}'.")
        geschlecht_user = None # Wird später zu 'unbekannt' wenn nötig

    if not user_input.strip(): return jsonify({"error": "'inputText' darf nicht leer sein"}), 400 # Prüfe auf leeren String
    print(f"Input: '{user_input[:100]}...', ICDs: {icd_input}, GTINs: {gtin_input}, useIcd: {use_icd_flag}, Age: {alter_user}, Gender: {geschlecht_user}")

    llm_stage1_result: Dict[str, Any] = {"identified_leistungen": [], "extracted_info": {}, "begruendung_llm": ""}
    try:
        katalog_context_parts = [
            f"LKN: {lkn_code}, Typ: {details.get('Typ', 'N/A')}, Beschreibung: {html.escape(str(details.get('Beschreibung', 'N/A')))}" # str() für Beschreibung
            for lkn_code, details in leistungskatalog_dict.items() # Globale Variable hier OK
        ]
        katalog_context_str = "\n".join(katalog_context_parts)
        if not katalog_context_str: raise ValueError("Leistungskatalog für LLM-Kontext (Stufe 1) ist leer.")
        llm_stage1_result = call_gemini_stage1(user_input, katalog_context_str)
    except ConnectionError as e: print(f"FEHLER: Verbindung zu LLM1 fehlgeschlagen: {e}"); return jsonify({"error": f"Verbindungsfehler zum Analyse-Service (Stufe 1): {e}"}), 504
    except ValueError as e: print(f"FEHLER: Verarbeitung LLM1 fehlgeschlagen: {e}"); return jsonify({"error": f"Fehler bei der Leistungsanalyse (Stufe 1): {e}"}), 400
    except Exception as e: print(f"FEHLER: Unerwarteter Fehler bei LLM1: {e}"); traceback.print_exc(); return jsonify({"error": f"Unerwarteter interner Fehler (Stufe 1): {e}"}), 500
    llm1_time = time.time(); print(f"Zeit nach LLM Stufe 1: {llm1_time - start_time:.2f}s")

    final_validated_llm_leistungen: List[Dict[str,Any]] = []
    # Nutze get mit Fallback auf leere Liste, falls "identified_leistungen" fehlt
    for leistung_llm in llm_stage1_result.get("identified_leistungen", []):
        lkn_llm_val = leistung_llm.get("lkn")
        if not isinstance(lkn_llm_val, str): continue # Überspringe, wenn LKN kein String ist
        lkn_llm = lkn_llm_val.strip().upper()
        if not lkn_llm: continue # Überspringe leere LKN nach strip

        menge_llm = leistung_llm.get("menge", 1)
        local_lkn_data = leistungskatalog_dict.get(lkn_llm) # Globale Variable hier OK
        if local_lkn_data:
            final_validated_llm_leistungen.append({
                "lkn": lkn_llm,
                "typ": local_lkn_data.get("Typ", leistung_llm.get("typ", "N/A")),
                "beschreibung": local_lkn_data.get("Beschreibung", leistung_llm.get("beschreibung", "N/A")),
                "menge": menge_llm
            })
        else: print(f"WARNUNG: Vom LLM (Stufe 1) identifizierte LKN '{lkn_llm}' nicht im lokalen Katalog. Wird ignoriert.")
    llm_stage1_result["identified_leistungen"] = final_validated_llm_leistungen
    print(f"INFO: {len(final_validated_llm_leistungen)} LKNs nach LLM Stufe 1 und lokaler Katalogvalidierung.")

    extracted_info_llm = llm_stage1_result.get("extracted_info", {})
    alter_context_val = alter_user if alter_user is not None else extracted_info_llm.get("alter")
    # Für Regelprüfer immer einen String, nicht None
    geschlecht_context_val = geschlecht_user if geschlecht_user is not None else extracted_info_llm.get("geschlecht")
    if geschlecht_context_val is None: geschlecht_context_val = "unbekannt"
    
    seitigkeit_context_val = extracted_info_llm.get("seitigkeit", "unbekannt")
    anzahl_prozeduren_val = extracted_info_llm.get("anzahl_prozeduren")
    anzahl_fuer_pauschale_context = anzahl_prozeduren_val
    if seitigkeit_context_val.lower() == 'beidseits' and anzahl_fuer_pauschale_context is None:
        if len(final_validated_llm_leistungen) == 1 and final_validated_llm_leistungen[0].get('menge') == 1:
            anzahl_fuer_pauschale_context = 2; print(f"INFO (Heuristik): 'Anzahl' für Pauschale auf 2 gesetzt.")
        elif any(l.get('lkn') == "C02.CP.0100" and l.get('menge') == 1 for l in final_validated_llm_leistungen):
             anzahl_fuer_pauschale_context = 2; print(f"INFO (Heuristik C02.CP.0100): 'Anzahl' für Pauschale auf 2 gesetzt.")

    regel_ergebnisse_details_list: List[Dict[str, Any]] = []
    rule_checked_leistungen_list: List[Dict[str, Any]] = []
    if not final_validated_llm_leistungen:
         regel_ergebnisse_details_list.append({"lkn": None, "initiale_menge": 0, "regelpruefung": {"abrechnungsfaehig": False, "fehler": ["Keine LKN vom LLM identifiziert/validiert."]}, "finale_menge": 0})
    else:
        alle_lkn_codes_fuer_regelpruefung = [str(l.get("lkn")) for l in final_validated_llm_leistungen if l.get("lkn")] # Sicherstellen, dass es Strings sind
        for leistung_data in final_validated_llm_leistungen:
            lkn_code_val = leistung_data.get("lkn")
            if not isinstance(lkn_code_val, str): continue # Sollte durch obige Validierung nicht passieren
            lkn_code = lkn_code_val

            menge_initial_val = leistung_data.get("menge", 1)
            # print(f"INFO: Prüfe Regeln für LKN {lkn_code} (Initiale Menge: {menge_initial_val})")
            regel_ergebnis_dict: Dict[str,Any] = {"abrechnungsfaehig": False, "fehler": ["Regelprüfung nicht durchgeführt."]}
            finale_menge_nach_regeln = 0
            # rp_lkn_module wurde oben importiert
            if rp_lkn_module and hasattr(rp_lkn_module, 'pruefe_abrechnungsfaehigkeit') and regelwerk_dict: # Globale Variable hier OK
                abrechnungsfall_kontext = {
                    "LKN": lkn_code, "Menge": menge_initial_val,
                    "Begleit_LKNs": [b_lkn for b_lkn in alle_lkn_codes_fuer_regelpruefung if b_lkn != lkn_code],
                    "ICD": icd_input, "Geschlecht": geschlecht_context_val, "Alter": alter_context_val,
                    "Pauschalen": [], "GTIN": gtin_input
                }
                try:
                    regel_ergebnis_dict = rp_lkn_module.pruefe_abrechnungsfaehigkeit(abrechnungsfall_kontext, regelwerk_dict) # Globale Variable hier OK
                    if regel_ergebnis_dict.get("abrechnungsfaehig"):
                        finale_menge_nach_regeln = menge_initial_val
                    else:
                        fehler_liste_regel = regel_ergebnis_dict.get("fehler", [])
                        mengen_reduktions_fehler = next((f for f in fehler_liste_regel if "Menge auf" in f and "reduziert" in f), None)
                        if mengen_reduktions_fehler:
                            match_menge = re.search(r'Menge auf (\d+)', mengen_reduktions_fehler)
                            if match_menge:
                                try:
                                    finale_menge_nach_regeln = int(match_menge.group(1))
                                    regel_ergebnis_dict["abrechnungsfaehig"] = True
                                    print(f"INFO: Menge für LKN {lkn_code} durch Regelprüfer auf {finale_menge_nach_regeln} angepasst.")
                                except ValueError: finale_menge_nach_regeln = 0 # Fallback
                        if finale_menge_nach_regeln == 0: print(f"INFO: LKN {lkn_code} nicht abrechnungsfähig wegen Regel(n): {regel_ergebnis_dict.get('fehler', [])}")
                except Exception as e_rule: print(f"FEHLER bei Regelprüfung für LKN {lkn_code}: {e_rule}"); traceback.print_exc(); regel_ergebnis_dict = {"abrechnungsfaehig": False, "fehler": [f"Interner Fehler bei Regelprüfung: {e_rule}"]}
            else: print(f"WARNUNG: Keine Regelprüfung für LKN {lkn_code} durchgeführt (Regelprüfer oder Regelwerk fehlt)."); regel_ergebnis_dict = {"abrechnungsfaehig": False, "fehler": ["Regelprüfung nicht verfügbar."]}
            
            regel_ergebnisse_details_list.append({"lkn": lkn_code, "initiale_menge": menge_initial_val, "regelpruefung": regel_ergebnis_dict, "finale_menge": finale_menge_nach_regeln})
            if regel_ergebnis_dict.get("abrechnungsfaehig") and finale_menge_nach_regeln > 0:
                rule_checked_leistungen_list.append({**leistung_data, "menge": finale_menge_nach_regeln})
    rule_time = time.time(); print(f"Zeit nach Regelprüfung: {rule_time - llm1_time:.2f}s")
    print(f"Regelkonforme Leistungen für Pauschalenprüfung: {[l['lkn']+' (Menge '+str(l['menge'])+')' for l in rule_checked_leistungen_list]}")

    finale_abrechnung_obj: Dict[str, Any] | None = None # Kann None sein
    llm_stage2_mapping_results: Dict[str, Any] = { "mapping_results": [] }

    hat_pauschalen_potential_nach_regeln = any(l.get('typ') in ['P', 'PZ'] for l in rule_checked_leistungen_list)
    if not rule_checked_leistungen_list or not hat_pauschalen_potential_nach_regeln:
        print("INFO: Keine P/PZ LKNs nach Regelprüfung oder keine LKNs übrig. Gehe direkt zu TARDOC.")
    else:
        print("INFO: Pauschalenpotenzial nach Regelprüfung vorhanden. Starte LKN-Mapping & Pauschalen-Hauptprüfung.")
        potential_pauschale_codes_set: Set[str] = set()
        regelkonforme_lkn_codes_fuer_suche = {str(l.get('lkn')) for l in rule_checked_leistungen_list if l.get('lkn')} # Sicherstellen Strings
        
        for item_lp in pauschale_lp_data: # Globale Variable
            lkn_in_lp_db_val = item_lp.get('Leistungsposition')
            if isinstance(lkn_in_lp_db_val, str) and lkn_in_lp_db_val in regelkonforme_lkn_codes_fuer_suche:
                pc_code = item_lp.get('Pauschale')
                if pc_code and str(pc_code) in pauschalen_dict: potential_pauschale_codes_set.add(str(pc_code)) # Globale Variable
        
        regelkonforme_lkns_in_tables_cache: Dict[str, Set[str]] = {}
        for cond_data in pauschale_bedingungen_data: # Globale Variable
            pc_code_cond_val = cond_data.get('Pauschale')
            if not (pc_code_cond_val and str(pc_code_cond_val) in pauschalen_dict): continue # Globale Variable
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
                    if isinstance(lkn_regelkonform_raw, str): # KORREKTUR für Fehler 1 & 2
                        lkn_regelkonform_str = lkn_regelkonform_raw
                        if lkn_regelkonform_str not in regelkonforme_lkns_in_tables_cache:
                            tables_for_lkn_set = set()
                            for table_name_key_norm, table_entries_list in tabellen_dict_by_table.items(): # Globale Variable
                                for entry_item in table_entries_list:
                                    if entry_item.get('Code', '').upper() == lkn_regelkonform_str and \
                                       entry_item.get('Tabelle_Typ', '').lower() == "service_catalog":
                                        tables_for_lkn_set.add(table_name_key_norm)
                            regelkonforme_lkns_in_tables_cache[lkn_regelkonform_str] = tables_for_lkn_set
                        
                        if not table_refs_cond_set.isdisjoint(regelkonforme_lkns_in_tables_cache[lkn_regelkonform_str]):
                            potential_pauschale_codes_set.add(pc_code_cond)
                            break
        print(f"DEBUG: {len(potential_pauschale_codes_set)} potenzielle Pauschalen für Mapping/Prüfung gefunden: {potential_pauschale_codes_set}")

        if not potential_pauschale_codes_set:
             print("INFO: Keine potenziellen Pauschalen nach initialer Suche gefunden. Gehe zu TARDOC.")
        else:
            mapping_candidate_lkns_dict = get_LKNs_from_pauschalen_conditions(
                potential_pauschale_codes_set, pauschale_bedingungen_data, # Globale Variablen
                tabellen_dict_by_table, leistungskatalog_dict) # Globale Variablen
            # print(f"DEBUG: {len(mapping_candidate_lkns_dict)} LKN-Kandidaten für LLM-Mapping vorbereitet.")

            tardoc_lkns_to_map_list = [l for l in rule_checked_leistungen_list if l.get('typ') in ['E', 'EZ']]
            # print(f"DEBUG: {len(tardoc_lkns_to_map_list)} TARDOC LKNs (E/EZ) zum Mappen identifiziert: {[l.get('lkn') for l in tardoc_lkns_to_map_list]}")
            mapped_lkn_codes_set: Set[str] = set()
            mapping_process_had_connection_error = False

            if tardoc_lkns_to_map_list and mapping_candidate_lkns_dict:
                for tardoc_leistung_map_obj in tardoc_lkns_to_map_list:
                    t_lkn_code = tardoc_leistung_map_obj.get('lkn')
                    t_lkn_desc = tardoc_leistung_map_obj.get('beschreibung')
                    current_candidates_for_llm = mapping_candidate_lkns_dict
                    if isinstance(t_lkn_code, str) and t_lkn_code.startswith('AG.'):
                        anast_table_content_codes = {
                            str(item['Code']).upper() for item in get_table_content("ANAST", "service_catalog", tabellen_dict_by_table) if item.get('Code') # Globale Variable
                        }
                        filtered_anast_candidates = {
                            k: v for k, v in mapping_candidate_lkns_dict.items()
                            if k.startswith('WA.') or k in anast_table_content_codes
                        }
                        if filtered_anast_candidates:
                            current_candidates_for_llm = filtered_anast_candidates
                            # print(f"  INFO: Für Mapping von {t_lkn_code} wurden Kandidaten auf ANAST/WA.* ({len(current_candidates_for_llm)}) reduziert.")

                    if t_lkn_code and t_lkn_desc and current_candidates_for_llm:
                        try:
                            mapped_target_lkn_code = call_gemini_stage2_mapping(str(t_lkn_code), str(t_lkn_desc), current_candidates_for_llm)
                            if mapped_target_lkn_code:
                                mapped_lkn_codes_set.add(mapped_target_lkn_code)
                                # print(f"INFO: LKN-Mapping: {t_lkn_code} -> {mapped_target_lkn_code}")
                            llm_stage2_mapping_results["mapping_results"].append({
                                "tardoc_lkn": t_lkn_code, "tardoc_desc": t_lkn_desc,
                                "mapped_lkn": mapped_target_lkn_code,
                                "candidates_considered_count": len(current_candidates_for_llm)
                            })
                        except ConnectionError as e_conn_map:
                             print(f"FEHLER: Verbindung zu LLM Stufe 2 (Mapping) für {t_lkn_code} fehlgeschlagen: {e_conn_map}")
                             finale_abrechnung_obj = {"type": "Error", "message": f"Verbindungsfehler zum Analyse-Service (Stufe 2 Mapping): {e_conn_map}"}
                             mapping_process_had_connection_error = True; break 
                        except Exception as e_map_call:
                             print(f"FEHLER bei Aufruf von LLM Stufe 2 (Mapping) für {t_lkn_code}: {e_map_call}"); traceback.print_exc()
                             llm_stage2_mapping_results["mapping_results"].append({"tardoc_lkn": t_lkn_code, "tardoc_desc": t_lkn_desc, "mapped_lkn": None, "error": str(e_map_call), "candidates_considered_count": len(current_candidates_for_llm)})
                    else:
                        llm_stage2_mapping_results["mapping_results"].append({"tardoc_lkn": t_lkn_code or "N/A", "tardoc_desc": t_lkn_desc or "N/A", "mapped_lkn": None, "info": "Mapping übersprungen", "candidates_considered_count": len(current_candidates_for_llm) if current_candidates_for_llm else 0})
            else: print("INFO: Überspringe LKN-Mapping (keine E/EZ LKNs oder keine Mapping-Kandidaten).")
            mapping_time = time.time(); print(f"Zeit nach LKN-Mapping: {mapping_time - rule_time:.2f}s")

            if not mapping_process_had_connection_error:
                final_lkn_context_for_pauschale_set = {str(l.get('lkn')) for l in rule_checked_leistungen_list if l.get('lkn')} # Sicherstellen Strings
                final_lkn_context_for_pauschale_set.update(mapped_lkn_codes_set)
                final_lkn_context_list_for_pauschale = list(final_lkn_context_for_pauschale_set)
                print(f"INFO: Finaler LKN-Kontext für Pauschalen-Hauptprüfung ({len(final_lkn_context_list_for_pauschale)} LKNs): {final_lkn_context_list_for_pauschale}")

                pauschale_haupt_pruef_kontext = {
                    "ICD": icd_input, "GTIN": gtin_input, "Alter": alter_context_val,
                    "Geschlecht": geschlecht_context_val, "useIcd": use_icd_flag,
                    "LKN": final_lkn_context_list_for_pauschale, "Seitigkeit": seitigkeit_context_val,
                    "Anzahl": anzahl_fuer_pauschale_context
                }
                try:
                    print(f"INFO: Starte Pauschalen-Hauptprüfung (useIcd={use_icd_flag})...")
                    # KORREKTUR: Aufruf über die Funktionsvariable determine_applicable_pauschale_func
                    pauschale_pruef_ergebnis_dict = determine_applicable_pauschale_func(
                        user_input, rule_checked_leistungen_list, pauschale_haupt_pruef_kontext,
                        pauschale_lp_data, pauschale_bedingungen_data, pauschalen_dict, # Globale Variablen
                        leistungskatalog_dict, tabellen_dict_by_table, potential_pauschale_codes_set # Globale Variablen
                    )
                    finale_abrechnung_obj = pauschale_pruef_ergebnis_dict
                    if finale_abrechnung_obj.get("type") == "Pauschale": print(f"INFO: Anwendbare Pauschale gefunden: {finale_abrechnung_obj.get('details',{}).get('Pauschale')}")
                    else: print(f"INFO: Keine anwendbare Pauschale. Grund: {finale_abrechnung_obj.get('message', 'Unbekannt')}")
                except Exception as e_pauschale_main:
                     print(f"FEHLER bei Pauschalen-Hauptprüfung: {e_pauschale_main}"); traceback.print_exc()
                     finale_abrechnung_obj = {"type": "Error", "message": f"Interner Fehler bei Pauschalen-Hauptprüfung: {e_pauschale_main}"}

    if finale_abrechnung_obj is None or finale_abrechnung_obj.get("type") != "Pauschale":
        print("INFO: Keine gültige Pauschale ausgewählt oder Prüfung übersprungen. Bereite TARDOC-Abrechnung vor.")
        # prepare_tardoc_abrechnung_func wurde oben initialisiert (entweder echt oder Fallback)
        finale_abrechnung_obj = prepare_tardoc_abrechnung_func(regel_ergebnisse_details_list, leistungskatalog_dict) # Globale Variable

    decision_time = time.time(); print(f"Zeit nach finaler Entscheidung: {decision_time - start_time:.2f}s (seit Start)")
    final_response_payload = {
        "llm_ergebnis_stufe1": llm_stage1_result,
        "regel_ergebnisse_details": regel_ergebnisse_details_list,
        "abrechnung": finale_abrechnung_obj,
        "llm_ergebnis_stufe2": llm_stage2_mapping_results
    }
    end_time = time.time(); total_time = end_time - start_time
    print(f"Gesamtverarbeitungszeit Backend: {total_time:.2f}s")
    print(f"INFO: Sende finale Antwort Typ '{finale_abrechnung_obj.get('type') if finale_abrechnung_obj else 'None'}' an Frontend.")
    return jsonify(final_response_payload)

# --- Static‑Routes & Start ---
@app.route("/")
def index_route(): # Umbenannt, um Konflikt mit Modul 'index' zu vermeiden, falls es existiert
    return send_from_directory(".", "index.html")

@app.route("/favicon.ico")
def favicon_ico():
    return send_from_directory(".", "favicon.ico", mimetype='image/vnd.microsoft.icon')

@app.route("/favicon.svg")
def favicon_svg():
    return send_from_directory(".", "favicon.svg", mimetype='image/svg+xml')

@app.route("/<path:filename>")
def serve_static(filename: str): # Typ hinzugefügt
    allowed_files = {'calculator.js'}
    allowed_dirs = {'data'} # Erlaube Zugriff auf data-Ordner
    file_path = Path(filename)

    # Verhindere Zugriff auf Python-Dateien, .env, versteckte Dateien/Ordner
    if (file_path.suffix in ['.py', '.txt', '.env'] or \
        any(part.startswith('.') for part in file_path.parts)):
         print(f"WARNUNG: Zugriff verweigert (sensible Datei): {filename}")
         abort(404)

    # Erlaube JS-Datei oder Dateien im data-Verzeichnis (und Unterverzeichnisse)
    if filename in allowed_files or (file_path.parts and file_path.parts[0] in allowed_dirs):
         # print(f"INFO: Sende statische Datei: {filename}")
         return send_from_directory('.', filename)
    else:
         print(f"WARNUNG: Zugriff verweigert (nicht erlaubt): {filename}")
         abort(404)

def _run_local() -> None:
    """Lokaler Debug-Server (wird von Render **nicht** aufgerufen)."""
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀  Lokal verfügbar auf http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)


if __name__ == "__main__" and os.getenv("RENDER_SERVICE_TYPE") is None:
    # Nur wenn das Skript direkt gestartet wird – nicht in der Render-Runtime
    _run_local()
