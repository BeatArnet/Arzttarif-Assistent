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
import regelpruefer
from typing import Dict, List, Any, Set
from utils import get_table_content
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

# Importiere Regelprüfer-Module und setze Fallbacks
try:
    import regelpruefer # Nur das Modul importieren
    print("✓ Regelprüfer LKN (regelpruefer.py) Modul geladen.")
    # Prüfe explizit auf die Funktion im Modul
    if not hasattr(regelpruefer, 'prepare_tardoc_abrechnung'):
         print("FEHLER: Funktion 'prepare_tardoc_abrechnung' NICHT im Modul regelpruefer gefunden!")
         # Definiere hier ggf. einen Fallback, wenn die Funktion fehlt
         def prepare_tardoc_fallback(r, l): return {"type":"Error", "message":"TARDOC Prep Fallback"}
         prepare_tardoc_abrechnung_func = prepare_tardoc_fallback
    else:
         print("DEBUG: Funktion 'prepare_tardoc_abrechnung' im Modul regelpruefer gefunden.")
         prepare_tardoc_abrechnung_func = regelpruefer.prepare_tardoc_abrechnung # Weise die Funktion einer Variablen zu
except ImportError:
    print("FEHLER: regelpruefer.py nicht gefunden.")
    # ... (Fallback für DummyRegelpruefer) ...
    def prepare_tardoc_fallback(r, l): return {"type":"Error", "message":"TARDOC Prep Fallback (Import Error)"}
    prepare_tardoc_abrechnung_func = prepare_tardoc_fallback

try:
    import regelpruefer_pauschale
    # print(f"DEBUG: Import von regelpruefer_pauschale erfolgreich. Typ: {type(regelpruefer_pauschale)}")
    # Prüfe explizit auf die Funktion NACH dem Import
    if hasattr(regelpruefer_pauschale, 'evaluate_structured_conditions'):
        # print("DEBUG: Funktion 'evaluate_structured_conditions' im Modul gefunden.")
        evaluate_structured_conditions = regelpruefer_pauschale.evaluate_structured_conditions
    else:
        print("FEHLER: Funktion 'evaluate_structured_conditions' NICHT im Modul gefunden!")
        def evaluate_fallback(pc, ctx, bed_data, tab_dict): return False
        evaluate_structured_conditions = evaluate_fallback

    if hasattr(regelpruefer_pauschale, 'check_pauschale_conditions'):
        # print("DEBUG: Funktion 'check_pauschale_conditions' im Modul gefunden.")
        check_pauschale_conditions = regelpruefer_pauschale.check_pauschale_conditions
    else:
        print("FEHLER: Funktion 'check_pauschale_conditions' NICHT im Modul gefunden!")
        def check_html_fallback(pc, ctx, bed_data, tab_dict): return {"html": "HTML-Prüfung nicht verfügbar", "errors": [], "trigger_lkn_condition_met": False}
        check_pauschale_conditions = check_html_fallback

    # Importiere die anderen Hilfsfunktionen, falls sie existieren
    try:
        from regelpruefer_pauschale import get_simplified_conditions, generate_condition_detail_html
        print("DEBUG: Hilfsfunktionen get_simplified_conditions/generate_condition_detail_html importiert.")
    except ImportError:
        print("WARNUNG: Hilfsfunktionen get_simplified_conditions/generate_condition_detail_html nicht gefunden.")
        # Definiere Fallbacks, falls nötig
        def get_simplified_conditions(pc, bed_data): return set()
        def generate_condition_detail_html(ct, lk_dict, tab_dict): return "<li>Detail-Generierung fehlgeschlagen</li>"

    print("✓ Regelprüfer Pauschalen (regelpruefer_pauschale.py) geladen (vereinfachter Import).")

except ImportError:
    print("FEHLER: regelpruefer_pauschale.py konnte nicht importiert werden.")
    # Definiere alle notwendigen Fallbacks
    def evaluate_structured_conditions(pc, ctx, bed_data, tab_dict): return False
    def check_pauschale_conditions(pc, ctx, bed_data, tab_dict): return {"html": "Regelprüfer Pauschale nicht geladen", "errors": ["Regelprüfer Pauschale nicht geladen"], "trigger_lkn_condition_met": False}
    def get_simplified_conditions(pc, bed_data): return set()
    def generate_condition_detail_html(ct, lk_dict, tab_dict): return "<li>Detail-Generierung fehlgeschlagen</li>"

# --- Globale Datencontainer ---
app = Flask(__name__, static_folder='.', static_url_path='') # Flask App Instanz
leistungskatalog_data: list[dict] = []
leistungskatalog_dict: dict[str, dict] = {}
regelwerk_dict: dict[str, dict] = {}
tardoc_data_dict: dict[str, dict] = {}
pauschale_lp_data: list[dict] = []
pauschalen_data: list[dict] = []
pauschalen_dict: dict[str, dict] = {}
pauschale_bedingungen_data: list[dict] = []
tabellen_data: list[dict] = []
tabellen_dict_by_table: dict[str, list[dict]] = {}

# --- Daten laden Funktion ---
def load_data():
    # print("--- DEBUG: load_data() WURDE AUFGERUFEN ---")
    # Deklariere ALLE globalen Variablen, die in dieser Funktion geändert werden
    global leistungskatalog_data, leistungskatalog_dict, regelwerk_dict, tardoc_data_dict
    global pauschale_lp_data, pauschalen_data, pauschalen_dict, pauschale_bedingungen_data, tabellen_data
    global tabellen_dict_by_table, daten_geladen

    # Lokales Flag für diesen Ladevorgang
    all_loaded_successfully = True

    files_to_load = {
        "Leistungskatalog": (LEISTUNGSKATALOG_PATH, leistungskatalog_data, 'LKN', leistungskatalog_dict),
        "PauschaleLP": (PAUSCHALE_LP_PATH, pauschale_lp_data, None, None),
        "Pauschalen": (PAUSCHALEN_PATH, pauschalen_data, 'Pauschale', pauschalen_dict),
        "PauschaleBedingungen": (PAUSCHALE_BED_PATH, pauschale_bedingungen_data, None, None),
        "TARDOC": (TARDOC_PATH, [], 'LKN', tardoc_data_dict), # TARDOC nur ins Dict
        "Tabellen": (TABELLEN_PATH, tabellen_data, None, None) # Tabellen nur in Liste (vorerst)
    }
    print("--- Lade Daten ---")
    # Reset all data containers
    leistungskatalog_data.clear(); leistungskatalog_dict.clear(); regelwerk_dict.clear(); tardoc_data_dict.clear()
    pauschale_lp_data.clear(); pauschalen_data.clear(); pauschalen_dict.clear(); pauschale_bedingungen_data.clear(); tabellen_data.clear()
    tabellen_dict_by_table.clear()

    # Lade JSON-Dateien
    for name, (path, target_list, key_field, target_dict) in files_to_load.items():
        try:
            print(f"  Versuche {name} von {path} zu laden...")
            if path.is_file():
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if not isinstance(data, list):
                     print(f"  WARNUNG: {name}-Daten in '{path}' sind keine Liste, überspringe.")
                     continue

                # Fülle das Dictionary, falls gewünscht
                if target_dict is not None and key_field is not None:
                     target_dict.clear()
                     current_key_field = key_field # Lokale Variable für Klarheit
                     items_in_dict = 0
                     for item in data:
                          if isinstance(item, dict):
                               key_value = item.get(current_key_field)
                               if key_value:
                                   target_dict[str(key_value)] = item
                                   items_in_dict += 1
                          # else: # Weniger verbose
                          #      print(f"  WARNUNG: Ungültiger Eintrag (kein Dict) in {name}: {str(item)[:100]}...")
                     print(f"  ✓ {name}-Daten '{path}' geladen ({items_in_dict} Einträge im Dict).")

                # Fülle die Liste, falls gewünscht
                if target_list is not None:
                     target_list.clear()
                     target_list.extend(data)
                     if target_dict is None:
                          print(f"  ✓ {name}-Daten '{path}' geladen ({len(target_list)} Einträge in Liste).")

                # Fülle tabellen_dict_by_table (speziell für "Tabellen")
                if name == "Tabellen":
                    TAB_KEY = "Tabelle"
                    # print(f"  DEBUG (load_data): Beginne Gruppierung für '{name}' mit Schlüssel '{TAB_KEY}'...")
                    tabellen_dict_by_table.clear()
                    items_processed = 0
                    keys_created = set()
                    for item_index, item in enumerate(data):
                        items_processed += 1
                        if isinstance(item, dict):
                            table_name = item.get(TAB_KEY)
                            if table_name:
                                normalized_key = str(table_name).lower()
                                if normalized_key not in tabellen_dict_by_table:
                                    tabellen_dict_by_table[normalized_key] = []
                                    keys_created.add(normalized_key)
                                tabellen_dict_by_table[normalized_key].append(item)
                            # else: # Weniger verbose
                            #     print(f"  WARNUNG (load_data): Eintrag {item_index} in '{name}' fehlt Schlüssel '{TAB_KEY}'.")
                        # else: # Weniger verbose
                        #      print(f"  WARNUNG (load_data): Eintrag {item_index} in '{name}' ist kein Dictionary.")

                    # print(f"  DEBUG (load_data): Gruppierung für '{name}' abgeschlossen. {items_processed} Items verarbeitet.")
                    print(f"  ✓ Tabellen-Daten gruppiert nach Tabelle ({len(tabellen_dict_by_table)} Tabellen).")
                    # Prüfe spezifische Schlüssel nach der Gruppierung
                    missing_keys_check = ['cap13', 'cap14', 'or', 'nonor', 'nonelt', 'ambp.pz', 'anast', 'c08.50']
                    found_keys_check = {k for k in missing_keys_check if k in tabellen_dict_by_table}
                    not_found_keys_check = {k for k in missing_keys_check if k not in tabellen_dict_by_table}
                    # print(f"  DEBUG (load_data): Prüfung spezifischer Tabellen-Schlüssel: Gefunden={found_keys_check}, Fehlend={not_found_keys_check}")
                    if not_found_keys_check:
                         print(f"  FEHLER: Kritische Tabellenschlüssel fehlen in tabellen_dict_by_table!")
                         all_loaded_successfully = False # Kritischer Fehler

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
        if regelpruefer and hasattr(regelpruefer, 'lade_regelwerk'):
            if REGELWERK_PATH.is_file():
                regelwerk_dict.clear()
                regelwerk_dict_loaded = regelpruefer.lade_regelwerk(str(REGELWERK_PATH))
                if regelwerk_dict_loaded:
                    regelwerk_dict.update(regelwerk_dict_loaded)
                    print(f"  ✓ Regelwerk (LKN) '{REGELWERK_PATH}' geladen ({len(regelwerk_dict)} LKNs).")
                else:
                    print(f"  FEHLER: LKN-Regelwerk konnte nicht geladen werden (Funktion gab leeres Dict zurück).")
                    all_loaded_successfully = False
            else:
                print(f"  FEHLER: Regelwerk (LKN) nicht gefunden: {REGELWERK_PATH}")
                regelwerk_dict.clear(); all_loaded_successfully = False
        else:
            print("  ℹ️ Regelprüfung (LKN) nicht verfügbar oder lade_regelwerk fehlt.")
            regelwerk_dict.clear() # Sicherstellen, dass es leer ist
    except Exception as e:
        print(f"  FEHLER beim Laden des LKN-Regelwerks: {e}")
        traceback.print_exc(); regelwerk_dict.clear(); all_loaded_successfully = False

    print("--- Daten laden abgeschlossen ---")
    if not all_loaded_successfully:
        print("WARNUNG: Einige kritische Daten konnten nicht geladen werden!")
    else:
        print("INFO: Alle Daten erfolgreich geladen.")

    # print(f"DEBUG: load_data() beendet. Flag daten_geladen={daten_geladen}")
    print(f"DEBUG: load_data() beendet. leistungskatalog_dict leer? {not leistungskatalog_dict}")
    # print(f"DEBUG: pauschalen_dict leer? {not pauschalen_dict}")
    # print(f"DEBUG: regelwerk_dict leer? {not regelwerk_dict}")
    # print(f"DEBUG: tabellen_dict_by_table leer? {not tabellen_dict_by_table}")

    # Gib den Erfolgsstatus zurück (wird von ensure_data_loaded verwendet)
    return all_loaded_successfully

# --- LLM Stufe 1: LKN Identifikation ---
def call_gemini_stage1(user_input: str, katalog_context: str) -> dict:
    if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY nicht konfiguriert.")
# Innerhalb der Funktion call_gemini_stage1 in server.py

    prompt = f"""**Aufgabe:** Analysiere den folgenden medizinischen Behandlungstext aus der Schweiz äußerst präzise. Deine einzige Aufgabe ist die Identifikation relevanter Leistungs-Katalog-Nummern (LKN), deren Menge und die Extraktion spezifischer Kontextinformationen basierend **ausschließlich** auf dem bereitgestellten Leistungskatalog.

**Kontext: Leistungskatalog (Dies ist die EINZIGE Quelle für gültige LKNs und deren Beschreibungen! Ignoriere jegliches anderes Wissen.)**
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**Anweisungen:** Führe die folgenden Schritte exakt aus:

1.  **LKN Identifikation & STRIKTE Validierung:**
    *   Lies den "Behandlungstext" sorgfältig.
    *   Identifiziere **alle** potenziellen LKN-Codes (Format `XX.##.####`), die die beschriebenen Tätigkeiten repräsentieren könnten. Berücksichtige Hauptleistungen und explizit genannte, relevante Begleitleistungen (z.B. Anästhesie, spezifische Laboranalysen, Bildgebung).
    *   **ABSOLUT KRITISCH:** Für JEDEN potenziellen LKN-Code: Überprüfe **BUCHSTABE FÜR BUCHSTABE und ZIFFER FÜR ZIFFER**, ob dieser Code **EXAKT** so im obigen "Leistungskatalog" als 'LKN:' vorkommt. Verwechsle nicht ähnliche Codes (z.B. C03.AH.0010 ist NICHT C08.AH.0010, es sei denn, beide stehen exakt so im Katalog und passen zur Beschreibung). Nur wenn der LKN-Code exakt existiert, prüfe, ob die **zugehörige Katalog-Beschreibung** zur im Text genannten Tätigkeit passt.
    *   **Beispiel:** Wenn der Text "Operation X mit Anästhesie Y durch Anästhesist" lautet, identifiziere sowohl die LKN für Operation X als auch die LKN für Anästhesie Y (z.B. eine AG.* LKN), sofern beide im Katalog exakt vorhanden sind und die Beschreibungen passen.
    *   Erstelle eine Liste (`identified_leistungen`) **AUSSCHLIESSLICH** mit den LKNs, die diese **exakte** Prüfung im Katalog bestanden haben UND deren Beschreibung zum Text passt.
    *   **VERBOTEN:** Gib niemals LKNs aus, die nicht exakt im Katalog stehen oder deren Beschreibung nicht zur genannten Leistung passt. Erfinde keine LKNs.
    *   Wenn eine Dauer genannt wird, die Basis- und Zuschlagsleistung erfordert (primär bei Konsultationen), stelle sicher, dass **beide** LKNs (Basis + Zuschlag) identifiziert und **validiert** werden.

2.  **Typ & Beschreibung hinzufügen:**
    *   Füge für jede **validierte** LKN in der `identified_leistungen`-Liste den korrekten `typ` und die `beschreibung` **direkt und unverändert aus dem bereitgestellten Katalogkontext für DIESE LKN** hinzu.

3.  **Kontextinformationen extrahieren:**
    *   Extrahiere **nur explizit genannte** Werte aus dem "Behandlungstext": `dauer_minuten` (Zahl), `menge_allgemein` (Zahl), `alter` (Zahl), `geschlecht` ('weiblich', 'männlich', 'divers', 'unbekannt'). Sonst `null`.

4.  **Menge bestimmen (pro validierter LKN):**
    *   Standardmenge ist `1`.
    *   **Zeitbasiert:** Wenn Katalog-Beschreibung "pro X Min" enthält UND `dauer_minuten` (Y) extrahiert wurde, setze `menge` = Y.
    *   **Allgemein:** Wenn `menge_allgemein` (Z) extrahiert wurde UND LKN nicht zeitbasiert ist, setze `menge` = Z.
    *   Sicherstellen: `menge` >= 1.

5.  **Begründung:**
    *   **Kurze** `begruendung_llm`, warum die **validierten** LKNs gewählt wurden. Beziehe dich auf Text und **Katalog-Beschreibungen**. Verwende "Die LKN [Code]...".

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
    // ... ggf. weitere validierte LKNs
  ],
  "extracted_info": {{ "dauer_minuten": null, "menge_allgemein": null, "alter": null, "geschlecht": null }},
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
            "temperature": 0.05, # Noch weiter reduziert für mehr Konsistenz
            "maxOutputTokens": 2048
        }
    }
    print(f"Sende Anfrage Stufe 1 (gehärtet) an Gemini Model: {GEMINI_MODEL}...")
    try:
        response = requests.post(gemini_url, json=payload, timeout=90)
        print(f"Gemini Stufe 1 Antwort Status Code: {response.status_code}")
        response.raise_for_status()
        gemini_data = response.json()
        # ... (Rest der Parsing- und Validierungslogik wie im letzten funktionierenden Stand) ...
        # Stelle sicher, dass die Validierung im Python-Code nach wie vor prüft,
        # ob die zurückgegebenen LKNs im leistungskatalog_dict existieren!
        # ...
        if not gemini_data.get('candidates'):
            finish_reason = gemini_data.get('promptFeedback', {}).get('blockReason')
            safety_ratings = gemini_data.get('promptFeedback', {}).get('safetyRatings')
            error_details = f"Keine Kandidaten gefunden. Finish Reason: {finish_reason}, Safety Ratings: {safety_ratings}"
            print(f"WARNUNG: {error_details}")
            try: raw_text_response = gemini_data['text']
            except KeyError: raise ValueError(error_details)
        else:
            candidate = gemini_data['candidates'][0]
            content = candidate.get('content', {})
            parts = content.get('parts', [{}])[0]
            raw_text_response = parts.get('text', '')

        # print(f"DEBUG: Roher Text von LLM Stufe 1 (gehärtet, gekürzt):\n---\n{raw_text_response[:500]}...\n---")

        if not raw_text_response:
            finish_reason = candidate.get('finishReason', 'UNKNOWN'); safety_ratings = candidate.get('safetyRatings')
            if finish_reason != 'STOP': raise ValueError(f"Gemini stopped with reason: {finish_reason}, Safety: {safety_ratings}")
            else: raise ValueError("Leere Textantwort von Gemini erhalten trotz Status OK.")

        try:
            llm_response_json = json.loads(raw_text_response)
        except json.JSONDecodeError as json_err:
            match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_text_response, re.IGNORECASE)
            if match:
                try: llm_response_json = json.loads(match.group(1)); print("INFO: JSON aus Markdown extrahiert.")
                except json.JSONDecodeError: raise ValueError(f"JSONDecodeError auch nach Markdown-Extraktion: {json_err}. Rohtext: {raw_text_response[:500]}...")
            else: raise ValueError(f"JSONDecodeError: {json_err}. Rohtext: {raw_text_response[:500]}...")

        # print(f"DEBUG: Geparstes LLM JSON Stufe 1 VOR Validierung: {json.dumps(llm_response_json, indent=2, ensure_ascii=False)}")

        # Strikte Validierung (wie vorher)
        # ... (Code für Validierung der Struktur und Typen) ...
        if not isinstance(llm_response_json, dict): raise ValueError("Antwort ist kein JSON-Objekt.")
        if not all(k in llm_response_json for k in ["identified_leistungen", "extracted_info", "begruendung_llm"]): raise ValueError("Hauptschlüssel fehlen.")
        if not isinstance(llm_response_json["identified_leistungen"], list): raise ValueError("'identified_leistungen' ist keine Liste.")
        if not isinstance(llm_response_json["extracted_info"], dict): raise ValueError("'extracted_info' kein Dict.")
        expected_extracted = ["dauer_minuten", "menge_allgemein", "alter", "geschlecht"];
        if not all(k in llm_response_json["extracted_info"] for k in expected_extracted): raise ValueError(f"Schlüssel in 'extracted_info' fehlen.")
        for key, expected_type in [("dauer_minuten", (int, type(None))), ("menge_allgemein", (int, type(None))), ("alter", (int, type(None))), ("geschlecht", (str, type(None)))]:
            if not isinstance(llm_response_json["extracted_info"].get(key), expected_type):
                if key == "geschlecht" and llm_response_json["extracted_info"].get(key) is None: continue
                raise ValueError(f"Typfehler in 'extracted_info': '{key}'")
        expected_leistung = ["lkn", "typ", "beschreibung", "menge"]
        for i, item in enumerate(llm_response_json["identified_leistungen"]):
            if not isinstance(item, dict): raise ValueError(f"Element {i} keine Dict.")
            if not all(k in item for k in expected_leistung): raise ValueError(f"Schlüssel in Element {i} fehlen.")
            menge_val = item.get("menge")
            if menge_val is None: item["menge"] = 1
            elif not isinstance(menge_val, int):
                try: item["menge"] = int(menge_val)
                except (ValueError, TypeError): raise ValueError(f"Menge '{menge_val}' in Element {i} keine Zahl.")
            if item["menge"] < 0: raise ValueError(f"Menge in Element {i} negativ.")
            if not isinstance(item.get("lkn"), str) or not item.get("lkn"): raise ValueError(f"LKN in Element {i} kein String.")
        if "begruendung_llm" not in llm_response_json or not isinstance(llm_response_json["begruendung_llm"], str): llm_response_json["begruendung_llm"] = "N/A"


        print("INFO: LLM Stufe 1 Antwort erfolgreich validiert.")
        return llm_response_json

    except requests.exceptions.RequestException as req_err:
        print(f"FEHLER: Netzwerkfehler bei Gemini Stufe 1: {req_err}")
        raise ConnectionError(f"Netzwerkfehler bei Gemini Stufe 1: {req_err}")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as proc_err:
        print(f"FEHLER: Fehler beim Verarbeiten der LLM Stufe 1 Antwort: {proc_err}")
        raise ValueError(f"Verarbeitungsfehler LLM Stufe 1: {proc_err}")
    except Exception as e:
        print(f"FEHLER: Unerwarteter Fehler im LLM Stufe 1: {e}")
        raise e

def call_gemini_stage2_mapping(tardoc_lkn: str, tardoc_desc: str, candidate_pauschal_lkns: Dict[str, str]) -> str | None:
    """
    Findet die funktional äquivalente Pauschalen-LKN für eine gegebene TARDOC-LKN.
    Args:
        tardoc_lkn: Die TARDOC LKN (z.B. 'AG.00.0030').
        tardoc_desc: Die Beschreibung der TARDOC LKN.
        candidate_pauschal_lkns: Dict der möglichen Pauschalen-LKNs {lkn: beschreibung}.
    Returns:
        Die am besten passende Pauschalen-LKN als String oder None, wenn keine passt.
    """
    if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY nicht konfiguriert.")
    if not candidate_pauschal_lkns:
        print(f"WARNUNG (Mapping): Keine Kandidaten-LKNs für Mapping von {tardoc_lkn} übergeben.")
        return None

    # Baue den Kontext der Kandidaten auf (nur relevante, z.B. Anästhesie?)
    # Hier könnte man filtern, z.B. nur WA.* Kandidaten für AG.* LKNs
    # Vorerst nehmen wir alle übergebenen Kandidaten
    candidates_text = "\n".join([f"- {lkn}: {desc}" for lkn, desc in candidate_pauschal_lkns.items()])
    if len(candidates_text) > 15000: # Limit Kontextlänge (Anpassen nach Bedarf)
        print(f"WARNUNG (Mapping): Kandidatenliste für {tardoc_lkn} zu lang, wird gekürzt.")
        # Einfache Kürzung, intelligentere wäre möglich
        candidates_text = candidates_text[:15000] + "\n..."


# Innerhalb der Funktion call_gemini_stage2_mapping in server.py

    # *** PROMPT STUFE 2 - MAPPING (Aktualisiert) ***
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
    # *** ENDE PROMPT ***

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.05, # Niedrig für konsistente Auswahl
            "maxOutputTokens": 4096 # Antwort ist kurz
         }
    }
    print(f"Sende Anfrage Stufe 2 (Mapping) für {tardoc_lkn} an Gemini Model: {GEMINI_MODEL}...")
    try:
        response = requests.post(gemini_url, json=payload, timeout=60)
        print(f"Gemini Stufe 2 (Mapping) Antwort Status Code: {response.status_code}")
        response.raise_for_status()
        gemini_data = response.json()

        if not gemini_data.get('candidates'):
            raise ValueError("Keine Kandidaten in Stufe 2 (Mapping) Antwort.")
        
        raw_text_response_part = gemini_data['candidates'][0]['content']['parts'][0]['text'].strip()
        print(f"DEBUG: Roher Text von LLM Stufe 2 (Mapping) für {tardoc_lkn}: '{raw_text_response_part}'")

        extracted_codes_from_llm = []

        # VERSUCH 1: Ist der Output ein JSON-String, der eine Liste von LKNs enthält?
        try:
            parsed_json = json.loads(raw_text_response_part)
            if isinstance(parsed_json, dict) and "EQUIVALENT_LKNS" in parsed_json:
                if isinstance(parsed_json["EQUIVALENT_LKNS"], list):
                    extracted_codes_from_llm = [str(code).strip().upper().replace('"', '') for code in parsed_json["EQUIVALENT_LKNS"] if str(code).strip()]
                    print(f"INFO: Mapping-Antwort als JSON-Dict mit 'EQUIVALENT_LKNS' geparst: {extracted_codes_from_llm}")
            elif isinstance(parsed_json, list): # Falls es direkt eine Liste von Strings ist
                 extracted_codes_from_llm = [str(code).strip().upper().replace('"', '') for code in parsed_json if str(code).strip()]
                 print(f"INFO: Mapping-Antwort als JSON-Liste geparst: {extracted_codes_from_llm}")
            
        except json.JSONDecodeError:
            # Wenn kein valides JSON, weiter mit Komma-Splitting
            pass # Fehler wird unten behandelt, wenn extracted_codes_from_llm leer bleibt

        # VERSUCH 2: Wenn oben nichts extrahiert wurde, als kommagetrennte Liste behandeln
        if not extracted_codes_from_llm:
            if raw_text_response_part.upper() == "NONE":
                print(f"INFO: Kein passendes Mapping für {tardoc_lkn} gefunden (LLM sagte explizit NONE).")
                return None
            
            # Bereinige von eventuellen Markdown-Wrappern, bevor gesplittet wird
            match_markdown = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_text_response_part, re.IGNORECASE)
            text_to_split = raw_text_response_part
            if match_markdown:
                print("INFO: Markdown im Mapping-LLM-Output gefunden, extrahiere Inhalt für Split.")
                text_to_split = match_markdown.group(1).strip()
                # Erneuter JSON-Check nach Markdown-Extraktion
                try:
                    parsed_json_after_md = json.loads(text_to_split)
                    if isinstance(parsed_json_after_md, dict) and "EQUIVALENT_LKNS" in parsed_json_after_md:
                         if isinstance(parsed_json_after_md["EQUIVALENT_LKNS"], list):
                            extracted_codes_from_llm = [str(code).strip().upper().replace('"', '') for code in parsed_json_after_md["EQUIVALENT_LKNS"] if str(code).strip()]
                            print(f"INFO: Mapping-Antwort nach MD-Extraktion als JSON-Dict geparst: {extracted_codes_from_llm}")
                    elif isinstance(parsed_json_after_md, list):
                        extracted_codes_from_llm = [str(code).strip().upper().replace('"', '') for code in parsed_json_after_md if str(code).strip()]
                        print(f"INFO: Mapping-Antwort nach MD-Extraktion als JSON-Liste geparst: {extracted_codes_from_llm}")
                except json.JSONDecodeError:
                    pass # Bleibt bei Text-Split


            if not extracted_codes_from_llm: # Wenn immer noch nicht als JSON geparst
                extracted_codes_from_llm = [
                    code.strip().upper().replace('"', '') 
                    for code in text_to_split.split(',') 
                    if code.strip() and code.strip().upper() != "NONE" # NONE nicht als Code nehmen
                ]
                print(f"INFO: Mapping-Antwort als kommagetrennte Liste geparst: {extracted_codes_from_llm}")


        if not extracted_codes_from_llm:
            # Wenn nach allen Versuchen immer noch keine Codes da sind (und nicht explizit NONE)
            # könnte der LLM-Output komplett leer oder unbrauchbar sein.
            if raw_text_response_part and raw_text_response_part.upper() != "NONE":
                print(f"WARNUNG: Konnte keine LKNs aus der LLM-Antwort '{raw_text_response_part}' extrahieren.")
            # Wenn raw_text_response_part leer war, ist das okay, wird unten als "kein Mapping" behandelt.
            # Ansonsten, wenn es Text gab, der nicht NONE war, aber nicht geparsed werden konnte, ist es ein Warnhinweis.


        # Finde den ersten validen Code aus der extrahierten und bereinigten Liste
        for code in extracted_codes_from_llm:
            if code in candidate_pauschal_lkns: # Prüfe gegen die ursprünglichen Kandidaten
                print(f"INFO: Mapping erfolgreich (aus Liste): {tardoc_lkn} -> {code}")
                return code # Gib den ersten validen Code zurück

        # Wenn keiner der zurückgegebenen Codes valide war oder keine Codes extrahiert wurden
        # (und nicht explizit NONE vom LLM kam)
        if extracted_codes_from_llm: # Nur loggen, wenn LLM was zurückgab, das nicht passte
            print(f"WARNUNG: Keiner der vom Mapping-LLM zurückgegebenen/extrahierten Codes ({extracted_codes_from_llm}) war valide für {tardoc_lkn}.")
        elif not raw_text_response_part or raw_text_response_part.upper() == "NONE":
             print(f"INFO: Kein passendes Mapping für {tardoc_lkn} gefunden (LLM-Antwort war leer, NONE oder konnte nicht geparst werden).")

        return None

    except requests.exceptions.RequestException as req_err:
        print(f"FEHLER: Netzwerkfehler bei Gemini Stufe 2 (Mapping): {req_err}")
        return None
    except (KeyError, IndexError, TypeError, ValueError) as e: # JSONDecodeError wird oben gefangen
        print(f"FEHLER beim Verarbeiten der Mapping-Antwort: {e}")
        traceback.print_exc() # Für mehr Details
        return None
    except Exception as e:
        print(f"FEHLER: Unerwarteter Fehler im LLM Stufe 2 (Mapping): {e}")
        traceback.print_exc()
        return None

# --- LLM Stufe 2: Pauschalen-Ranking ---
def call_gemini_stage2_ranking(user_input: str, potential_pauschalen_text: str) -> list[str]:
    # ... (call_gemini_stage2_ranking Funktion bleibt unverändert wie im letzten Schritt) ...
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
    payload = { "contents": [{"parts": [{"text": prompt}]}], "generationConfig": { "temperature": 0.1, "maxOutputTokens": 500 } } # Temp 0.0 für deterministisches Ranking
    print(f"Sende Anfrage Stufe 2 (Ranking) an Gemini Model: {GEMINI_MODEL}...")
    try:
        response = requests.post(gemini_url, json=payload, timeout=45)
        print(f"Gemini Stufe 2 Antwort Status Code: {response.status_code}")
        response.raise_for_status()
        gemini_data = response.json()

        if not gemini_data.get('candidates'): raise ValueError("Keine Kandidaten in Stufe 2 Antwort.")
        ranked_text = gemini_data['candidates'][0]['content']['parts'][0]['text']
        # print(f"DEBUG: Roher Text von LLM Stufe 2 (Ranking):\n---\n{ranked_text}\n---")
        # Entferne mögliche Begründungen oder Formatierungen
        ranked_text = ranked_text.strip().replace("`", "")
        ranked_codes = [code.strip() for code in ranked_text.split(',') if code.strip() and re.match(r'^[A-Z0-9.]+$', code.strip())] # Nur gültige Code-Formate
        print(f"LLM Stufe 2 Gerankte Codes nach Filter: {ranked_codes}")
        if not ranked_codes: print("WARNUNG: LLM Stufe 2 hat keine gültigen Codes zurückgegeben.")
        return ranked_codes
    except requests.exceptions.RequestException as req_err:
        print(f"FEHLER: Netzwerkfehler bei Gemini Stufe 2: {req_err}")
        raise ConnectionError(f"Netzwerkfehler bei Gemini Stufe 2: {req_err}")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as e:
         print(f"FEHLER beim Extrahieren/Verarbeiten des Rankings: {e}")
         # Gib leere Liste zurück, damit der Fallback greift
         return []
    except Exception as e:
         print(f"FEHLER: Unerwarteter Fehler im LLM Stufe 2: {e}")
         raise e

def get_table_content(table_ref: str, table_type: str, tabellen_dict_by_table: dict) -> list[dict]:
    """Holt Einträge für eine Tabelle und einen Typ (Case-Insensitive)."""
    content = []
    TAB_CODE_KEY = 'Code'; TAB_TEXT_KEY = 'Code_Text'; TAB_TYP_KEY = 'Tabelle_Typ'

    table_names = [t.strip() for t in table_ref.split(',') if t.strip()]
    all_entries_for_type = []

    for name in table_names:
        normalized_key = name.lower() # Suche immer mit kleinem Schlüssel
        # print(f"DEBUG (get_table_content): Suche normalisierten Schlüssel '{normalized_key}' für Typ '{table_type}'")

        if normalized_key in tabellen_dict_by_table:
            # print(f"DEBUG (get_table_content): Schlüssel '{normalized_key}' gefunden. Prüfe {len(tabellen_dict_by_table[normalized_key])} Einträge.")
            found_count = 0
            for entry in tabellen_dict_by_table[normalized_key]: # Greife direkt auf die Liste zu
                entry_typ = entry.get(TAB_TYP_KEY)
                if entry_typ and entry_typ.lower() == table_type.lower():
                    code = entry.get(TAB_CODE_KEY); text = entry.get(TAB_TEXT_KEY)
                    if code: all_entries_for_type.append({"Code": code, "Code_Text": text or "N/A"}); found_count +=1
            # print(f"DEBUG (get_table_content): {found_count} Einträge vom Typ '{table_type}' für Tabelle '{name}' gefunden.")
        else:
             print(f"WARNUNG (get_table_content): Normalisierter Schlüssel '{normalized_key}' (Original: '{name}') nicht in tabellen_dict_by_table gefunden.")

    unique_content = {item['Code']: item for item in all_entries_for_type}.values()
    return sorted(unique_content, key=lambda x: x.get('Code', ''))

# --- Ausgelagerte TARDOC-Vorbereitung ---
def prepare_tardoc_abrechnung(regel_ergebnisse_liste: list[dict]) -> dict:
    # ... (prepare_tardoc_abrechnung Funktion bleibt unverändert wie im letzten Schritt) ...
    print("INFO: TARDOC-Abrechnung wird vorbereitet...")
    tardoc_leistungen_final = []
    LKN_KEY = 'lkn' # Schlüssel in regel_ergebnisse_liste
    MENGE_KEY = 'finale_menge' # Schlüssel in regel_ergebnisse_liste

    for res in regel_ergebnisse_liste:
        lkn = res.get(LKN_KEY)
        menge = res.get(MENGE_KEY, 0)
        abrechnungsfaehig = res.get("regelpruefung", {}).get("abrechnungsfaehig", False)

        if not lkn or not abrechnungsfaehig or menge <= 0:
            continue # Überspringe ungültige, nicht abrechenbare oder Menge 0

        lkn_info = leistungskatalog_dict.get(lkn)
        if lkn_info and lkn_info.get("Typ") in ['E', 'EZ']: # Nur Einzelleistungen
            tardoc_leistungen_final.append({
                "lkn": lkn,
                "menge": menge,
                "typ": lkn_info.get("Typ"),
                "beschreibung": lkn_info.get("Beschreibung", "") # Beschreibung aus Katalog
            })
        elif not lkn_info:
             print(f"WARNUNG: Details für LKN {lkn} nicht im Leistungskatalog gefunden, kann nicht zu TARDOC hinzugefügt werden.")

    if not tardoc_leistungen_final:
        return {"type": "Error", "message": "Keine abrechenbaren TARDOC-Leistungen nach Regelprüfung gefunden."}
    else:
        print(f"INFO: {len(tardoc_leistungen_final)} TARDOC-Positionen zur Abrechnung vorbereitet.")
        return { "type": "TARDOC", "leistungen": tardoc_leistungen_final }

def get_relevant_p_pz_condition_lkns(
    potential_pauschale_codes: Set[str],
    pauschale_bedingungen_data: List[Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    leistungskatalog_dict: Dict[str, Dict]
) -> Dict[str, str]:
    """
    Sammelt alle LKNs, die in den Bedingungen der potenziellen Pauschalen vorkommen
    UND vom Typ P oder PZ sind.

    Args:
        potential_pauschale_codes: Set der Pauschalencodes, die potenziell anwendbar sind.
        pauschale_bedingungen_data: Alle Pauschalenbedingungen.
        tabellen_dict_by_table: Aufbereitete Tabellendaten.
        leistungskatalog_dict: Leistungskatalog zum Prüfen des LKN-Typs.

    Returns:
        Dict[str, str]: Dictionary der relevanten P/PZ LKNs {lkn: beschreibung}.
    """
    relevant_lkn_codes = set()
    BED_PAUSCHALE_KEY = 'Pauschale'
    BED_TYP_KEY = 'Bedingungstyp'
    BED_WERTE_KEY = 'Werte'

    # Filtere Bedingungen für die potenziellen Pauschalen
    relevant_conditions = [
        cond for cond in pauschale_bedingungen_data
        if cond.get(BED_PAUSCHALE_KEY) in potential_pauschale_codes
    ]

    for cond in relevant_conditions:
        typ = cond.get(BED_TYP_KEY, "").upper()
        wert = cond.get(BED_WERTE_KEY, "")
        if not wert: continue

        if typ == "LEISTUNGSPOSITIONEN IN LISTE" or typ == "LKN":
            lkns = [lkn.strip().upper() for lkn in wert.split(',') if lkn.strip()]
            relevant_lkn_codes.update(lkns)
        elif typ == "LEISTUNGSPOSITIONEN IN TABELLE" or typ == "TARIFPOSITIONEN IN TABELLE":
            table_names = [t.strip() for t in wert.split(',') if t.strip()]
            for table_name in table_names:
                content = get_table_content(table_name, "service_catalog", tabellen_dict_by_table)
                for item in content:
                    if item.get('Code'): relevant_lkn_codes.add(item['Code'].upper())

    # Filtere nach Typ P/PZ und hole Beschreibung
    valid_p_pz_candidates = {}
    for lkn in relevant_lkn_codes:
        lkn_details = leistungskatalog_dict.get(lkn)
        if lkn_details and lkn_details.get('Typ') in ['P', 'PZ']: # Filter nach Typ!
            valid_p_pz_candidates[lkn] = lkn_details.get('Beschreibung', 'N/A')

    print(f"DEBUG: {len(valid_p_pz_candidates)} relevante P/PZ Bedingungs-LKNs für Mapping gefunden.")
    return valid_p_pz_candidates

def get_LKNs_from_pauschalen_conditions(
    potential_pauschale_codes: Set[str],
    pauschale_bedingungen_data: List[Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    leistungskatalog_dict: Dict[str, Dict] # Wird für Beschreibungen benötigt
) -> Dict[str, str]:
    """
    Sammelt ALLE LKNs (unabhängig vom Typ), die in den Bedingungen der
    übergebenen potenziellen Pauschalencodes vorkommen.
    Holt deren Beschreibungen aus dem Leistungskatalog oder tblTabellen.

    Returns:
        Dict[str, str]: Dictionary der Bedingungs-LKNs {lkn: beschreibung}.
    """
    print(f"--- DEBUG: Start get_LKNs_from_pauschalen_conditions ---")
    print(f"  Suche Bedingungs-LKNs für potenzielle Pauschalen: {potential_pauschale_codes}")

    condition_lkns_with_desc = {}
    processed_lkn_codes = set() # Um doppelte Verarbeitung zu vermeiden

    BED_PAUSCHALE_KEY = 'Pauschale'
    BED_TYP_KEY = 'Bedingungstyp'
    BED_WERTE_KEY = 'Werte'

    relevant_conditions = [
        cond for cond in pauschale_bedingungen_data
        if cond.get(BED_PAUSCHALE_KEY) in potential_pauschale_codes and
           (cond.get(BED_TYP_KEY, "").upper() in [
               "LEISTUNGSPOSITIONEN IN LISTE", "LKN",
               "LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE"
           ])
    ]
    print(f"  Anzahl LKN-relevanter Bedingungen für diese Pauschalen: {len(relevant_conditions)}")

    for cond in relevant_conditions:
        typ = cond.get(BED_TYP_KEY, "").upper()
        wert = cond.get(BED_WERTE_KEY, "")
        if not wert: continue

        current_lkns_to_add = set()

        if typ == "LEISTUNGSPOSITIONEN IN LISTE" or typ == "LKN":
            lkns_in_list = [lkn.strip().upper() for lkn in wert.split(',') if lkn.strip()]
            current_lkns_to_add.update(lkns_in_list)
        elif typ == "LEISTUNGSPOSITIONEN IN TABELLE" or typ == "TARIFPOSITIONEN IN TABELLE":
            table_names_list = [t.strip() for t in wert.split(',') if t.strip()]
            for table_name in table_names_list:
                # Hier holen wir den Code_Text direkt aus get_table_content, falls vorhanden
                content = get_table_content(table_name, "service_catalog", tabellen_dict_by_table)
                for item in content:
                    lkn_code = item.get('Code')
                    if lkn_code:
                        lkn_code_upper = lkn_code.upper()
                        if lkn_code_upper not in processed_lkn_codes:
                            desc = item.get('Code_Text') # Aus tblTabellen
                            if not desc: # Fallback zum Hauptkatalog
                                desc = leistungskatalog_dict.get(lkn_code_upper, {}).get('Beschreibung', 'N/A')
                            condition_lkns_with_desc[lkn_code_upper] = desc
                            processed_lkn_codes.add(lkn_code_upper)

        # Für LKNs aus Listen, Beschreibungen separat holen
        for lkn_code_upper in current_lkns_to_add:
            if lkn_code_upper not in processed_lkn_codes:
                desc = leistungskatalog_dict.get(lkn_code_upper, {}).get('Beschreibung', 'N/A')
                condition_lkns_with_desc[lkn_code_upper] = desc
                processed_lkn_codes.add(lkn_code_upper)

    print(f"  DEBUG: {len(condition_lkns_with_desc)} einzigartige Bedingungs-LKNs (alle Typen) für Mapping-Kandidaten gefunden.")
    # Spezifische Prüfung für WA-Codes, falls die Liste nicht zu lang ist
    if len(condition_lkns_with_desc) < 100: # Nur loggen wenn übersichtlich
        wa_codes_found = {k:v for k,v in condition_lkns_with_desc.items() if k.startswith("WA.")}
        if wa_codes_found:
            print(f"  INFO: WA.* Codes unter den Bedingungs-LKNs: {list(wa_codes_found.keys())}")
        else:
            print(f"  INFO: KEINE WA.* Codes unter den Bedingungs-LKNs gefunden.")
    # print(f"--- DEBUG: Ende get_LKNs_from_pauschalen_conditions ---")
    return condition_lkns_with_desc

def get_pauschale_lkn_candidates(pauschale_bedingungen_data, tabellen_dict_by_table, leistungskatalog_dict):
    """
    Sammelt alle LKNs, die in Pauschalenbedingungen vorkommen UND vom Typ P oder PZ sind.
    Gibt ein Dictionary {lkn: beschreibung} zurück.
    """
    candidate_lkns_from_conditions = set()
    BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'

    for cond in pauschale_bedingungen_data:
        typ = cond.get(BED_TYP_KEY, "").upper(); wert = cond.get(BED_WERTE_KEY, "")
        if not wert: continue

        if typ == "LEISTUNGSPOSITIONEN IN LISTE" or typ == "LKN":
            lkns = [lkn.strip().upper() for lkn in wert.split(',') if lkn.strip()]
            candidate_lkns_from_conditions.update(lkns)
        elif typ == "LEISTUNGSPOSITIONEN IN TABELLE" or typ == "TARIFPOSITIONEN IN TABELLE":
            table_names = [t.strip() for t in wert.split(',') if t.strip()]
            for table_name in table_names:
                # Nutze utils.get_table_content
                content = get_table_content(table_name, "service_catalog", tabellen_dict_by_table)
                for item in content:
                    if item.get('Code'): candidate_lkns_from_conditions.add(item['Code'].upper())

    # Filtere nach Typ P/PZ und hole Beschreibung
    valid_p_pz_candidates = {}
    for lkn in candidate_lkns_from_conditions:
        lkn_details = leistungskatalog_dict.get(lkn) # Suche mit Upper Case Key
        if lkn_details and lkn_details.get('Typ') in ['P', 'PZ']: # Filter nach Typ!
            valid_p_pz_candidates[lkn] = lkn_details.get('Beschreibung', 'N/A')

    # print(f"DEBUG: {len(valid_p_pz_candidates)} gültige Pauschalen-LKN-Kandidaten (Typ P/PZ) für Mapping gefunden.")
    return valid_p_pz_candidates

# --- API Endpunkt ---
@app.route('/api/analyze-billing', methods=['POST'])
def analyze_billing():
    print("\n--- Request an /api/analyze-billing erhalten ---")
    start_time = time.time()

    # Prüfe, ob die globalen Dictionaries (die vom Hook befüllt sein sollten) leer sind
    if not leistungskatalog_dict or not pauschalen_dict or not pauschale_bedingungen_data or not tabellen_dict_by_table or not regelwerk_dict:
        print("FEHLER: Kritische Daten sind nicht geladen (Prüfung in analyze_billing).")
        # Logge den Status zur Sicherheit
        print(f"DEBUG: leistungskatalog_dict leer? {not leistungskatalog_dict}")
        print(f"DEBUG: pauschalen_dict leer? {not pauschalen_dict}")
        # ... (ggf. weitere Dictionaries loggen) ...
        return jsonify({"error": "Kritische Server-Daten nicht initialisiert. Bitte kurz warten oder Administrator kontaktieren."}), 503

    # 1. Eingaben holen und Daten prüfen
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()
    user_input = data.get('inputText')
    icd_input = data.get('icd', [])
    gtin_input = data.get('gtin', [])
    use_icd_flag = data.get('useIcd', False)
    age_input = data.get('age')
    gender_input = data.get('gender')

    try:
        alter_user = int(age_input) if age_input is not None else None
    except (ValueError, TypeError):
        alter_user = None
    geschlecht_user = str(gender_input) if isinstance(gender_input, str) and gender_input else None

    if not user_input: return jsonify({"error": "'inputText' is required"}), 400
    print(f"Empfangener inputText: '{user_input[:100]}...'")
    print(f"Empfangene ICDs: {icd_input}, GTINs: {gtin_input}, useIcd: {use_icd_flag}, Age: {alter_user}, Gender: {geschlecht_user}")

    if not leistungskatalog_dict or not pauschalen_dict or not tardoc_data_dict or not pauschale_bedingungen_data or not tabellen_data:
         print("FEHLER: Kritische Daten nicht geladen. Analyse abgebrochen.")
         return jsonify({"error": "Kritische Server-Daten nicht geladen. Bitte Administrator kontaktieren."}), 503

    # 2. LLM Stufe 1: LKNs identifizieren und validieren
    llm_stage1_result = None
    try:
        katalog_context = "\n".join([
            f"LKN: {item.get('LKN', 'N/A')}, Typ: {item.get('Typ', 'N/A')}, Beschreibung: {html.escape(item.get('Beschreibung', 'N/A'))}"
            for item in leistungskatalog_data if item.get('LKN')
        ])
        if not katalog_context: raise ValueError("Leistungskatalog für LLM-Kontext ist leer.")
        llm_stage1_result = call_gemini_stage1(user_input, katalog_context)
    except ConnectionError as e:
         print(f"FEHLER: Verbindung zu LLM Stufe 1 fehlgeschlagen: {e}")
         return jsonify({"error": f"Verbindungsfehler zum Analyse-Service (Stufe 1): {e}"}), 504
    except ValueError as e:
         print(f"FEHLER: Verarbeitung LLM Stufe 1 fehlgeschlagen: {e}")
         return jsonify({"error": f"Fehler bei der Leistungsanalyse (Stufe 1): {e}"}), 400
    except Exception as e:
         print(f"FEHLER: Unerwarteter Fehler bei LLM Stufe 1: {e}")
         traceback.print_exc()
         return jsonify({"error": f"Unerwarteter interner Fehler (Stufe 1): {e}"}), 500

    llm1_time = time.time()
    print(f"Zeit nach LLM Stufe 1: {llm1_time - start_time:.2f}s")

    # Validierung der LLM Stufe 1 Ergebnisse
    validated_leistungen_llm = []
    identified_leistungen_llm = llm_stage1_result.get("identified_leistungen", []) # Hole Liste oder leere Liste
    
    regel_ergebnisse_liste = []
    rule_checked_leistungen = []
    alle_validen_lkn = []
    mapped_lkns = set()
    final_pauschale_lkn_context_list = []
    
    if not identified_leistungen_llm:
         print("WARNUNG: LLM Stufe 1 hat keine Leistungen identifiziert.")
         # Füge einen Standard-Fehlereintrag hinzu
         regel_ergebnisse_liste.append({
             "lkn": None, "initiale_menge": 0,
             "regelpruefung": {"abrechnungsfaehig": False, "fehler": ["Keine LKN vom LLM identifiziert."]},
             "finale_menge": 0
         })
         # Die anderen Listen bleiben leer (sind schon initialisiert)
    else:
        # --- Dieser Block wird nur ausgeführt, wenn LLM LKNs gefunden hat ---
        # Validierung gegen Katalog
        for leistung in identified_leistungen_llm:
            lkn = leistung.get("lkn")
            menge_llm = leistung.get("menge", 1)
            llm_beschreibung = leistung.get("beschreibung", "N/A von LLM")
            local_data = leistungskatalog_dict.get(str(lkn).upper())
            if local_data:
                 leistung["typ"] = local_data.get("Typ", leistung.get("typ"))
                 leistung["beschreibung"] = local_data.get("Beschreibung", leistung.get("beschreibung"))
                 leistung["lkn"] = str(lkn).upper()
                 leistung["menge"] = max(1, int(menge_llm))
                 validated_leistungen_llm.append(leistung)
            else:
                 print(f"WARNUNG: Vom LLM identifizierte LKN '{lkn}' (LLM-Beschreibung: '{llm_beschreibung}') nicht im lokalen Katalog gefunden. Wird ignoriert.")
        identified_leistungen_llm = validated_leistungen_llm
        llm_stage1_result["identified_leistungen"] = identified_leistungen_llm
        print(f"INFO: {len(identified_leistungen_llm)} LKNs nach Validierung durch LLM Stufe 1 identifiziert.")

    # Check 1: Pauschalenpotenzial prüfen
    nur_tardoc_identifiziert = False
    hat_pauschalen_potential = False # Wird hier gesetzt
    if not identified_leistungen_llm:
        nur_tardoc_identifiziert = True
        print("INFO: Keine LKNs von LLM Stufe 1 identifiziert. Gehe zu TARDOC/Error.")
    else:
        hat_pauschalen_potential = any(l.get('typ') in ['P', 'PZ'] for l in identified_leistungen_llm)
        if not hat_pauschalen_potential:
            nur_tardoc_identifiziert = True
            print("INFO: LLM Stufe 1 fand nur LKNs vom Typ E/EZ. Keine Pauschale möglich.")

    # Initialisiere Stufe 2 Ergebnisse (für Mapping)
    llm_stage2_results_for_frontend = { "mapping_results": [] }

    # 3. Regelprüfung (immer durchführen)
    regel_ergebnisse_liste = []
    rule_checked_leistungen = []
    extracted_info = llm_stage1_result.get("extracted_info", {})
    alter_context = alter_user if alter_user is not None else extracted_info.get("alter")
    geschlecht_context = geschlecht_user if geschlecht_user is not None else extracted_info.get("geschlecht")
    alle_validen_lkn = [l.get("lkn") for l in identified_leistungen_llm if l.get("lkn")]

    if not identified_leistungen_llm:
         regel_ergebnisse_liste.append({
             "lkn": None, "initiale_menge": 0,
             "regelpruefung": {"abrechnungsfaehig": False, "fehler": ["Keine gültige LKN vom LLM identifiziert."]},
             "finale_menge": 0
         })
    else:
        for leistung in identified_leistungen_llm:
            lkn = leistung.get("lkn")
            menge_initial = leistung.get("menge", 1)
            print(f"INFO: Prüfe Regeln für LKN {lkn} (Initiale Menge: {menge_initial})")
            regel_ergebnis = {"abrechnungsfaehig": False, "fehler": ["Regelprüfung nicht durchgeführt."]}
            angepasste_menge = 0
            if regelpruefer and regelwerk_dict:
                abrechnungsfall = {
                    "LKN": lkn, "Menge": menge_initial,
                    "Begleit_LKNs": [b_lkn for b_lkn in alle_validen_lkn if b_lkn != lkn],
                    "ICD": icd_input, "Geschlecht": geschlecht_context, "Alter": alter_context,
                    "Pauschalen": [], "GTIN": gtin_input
                }
                try:
                    regel_ergebnis = regelpruefer.pruefe_abrechnungsfaehigkeit(abrechnungsfall, regelwerk_dict)
                    if regel_ergebnis.get("abrechnungsfaehig"):
                        angepasste_menge = menge_initial
                    else: # Mengen-Anpassungslogik
                        fehler_liste = regel_ergebnis.get("fehler", [])
                        fehler_ohne_menge = [f for f in fehler_liste if "Mengenbeschränkung" not in f and "reduziert" not in f]
                        mengen_fehler = [f for f in fehler_liste if "Mengenbeschränkung" in f]
                        if not fehler_ohne_menge and mengen_fehler:
                            max_menge_match = None
                            match = re.search(r'max\.\s*(\d+(\.\d+)?)', mengen_fehler[0])
                            if match:
                                try: max_menge_match = int(float(match.group(1)))
                                except ValueError: pass
                            if max_menge_match is not None and menge_initial > max_menge_match:
                                angepasste_menge = max_menge_match
                                print(f"INFO: Menge für LKN {lkn} aufgrund Regel angepasst: {menge_initial} -> {angepasste_menge}.")
                                regel_ergebnis["fehler"] = [f"Menge auf {angepasste_menge} reduziert (Regel: max. {max_menge_match}, LLM-Vorschlag: {menge_initial})"]
                                regel_ergebnis["abrechnungsfaehig"] = True
                            else: angepasste_menge = 0
                        else: angepasste_menge = 0
                        if angepasste_menge == 0: print(f"INFO: LKN {lkn} nicht abrechnungsfähig wegen Regel: {fehler_ohne_menge or fehler_liste}")
                except Exception as e_rule:
                    print(f"FEHLER bei Regelprüfung für LKN {lkn}: {e_rule}")
                    regel_ergebnis = {"abrechnungsfaehig": False, "fehler": [f"Interner Fehler bei Regelprüfung: {e_rule}"]}
                    angepasste_menge = 0
            else:
                 print(f"WARNUNG: Keine Regelprüfung für LKN {lkn} durchgeführt.")
                 regel_ergebnis = {"abrechnungsfaehig": False, "fehler": ["Regelprüfung nicht verfügbar."]}
                 angepasste_menge = 0

            regel_ergebnisse_liste.append({
                "lkn": lkn, "initiale_menge": menge_initial,
                "regelpruefung": regel_ergebnis, "finale_menge": angepasste_menge
            })
            if regel_ergebnis.get("abrechnungsfaehig") and angepasste_menge > 0:
                rule_checked_leistungen.append({**leistung, "menge": angepasste_menge})

    # print(f"DEBUG: Inhalt von rule_checked_leistungen nach Regelprüfung: {[l.get('lkn') for l in rule_checked_leistungen]}")
    rule_time = time.time()
    print(f"Zeit nach Regelprüfung: {rule_time - llm1_time:.2f}s")
    final_result = None
    llm_stage2_results_for_frontend = { "mapping_results": [] }

    if nur_tardoc_identifiziert:
        # --- Fall 1: Direkt zu TARDOC ---
        print("INFO: Bereite TARDOC-Abrechnung vor (da nur E/EZ von LLM1 gefunden).")
        final_result = regelpruefer.prepare_tardoc_abrechnung(regel_ergebnisse_liste, leistungskatalog_dict)

    elif not rule_checked_leistungen:
         # --- Fall 2: Nichts mehr übrig nach Regelprüfung ---
         print("WARNUNG: Keine Leistungen nach Regelprüfung übrig. Versuche TARDOC/Error.")
         final_result = regelpruefer.prepare_tardoc_abrechnung(regel_ergebnisse_liste, leistungskatalog_dict)

    if final_result is None: # Pauschale ist möglich UND Leistungen sind übrig
        print("INFO: Pauschalenpotenzial vorhanden. Starte Mapping & Pauschalenprüfung.")

        # --- Schritt 3a: Potenzielle Pauschalen finden ---
        # (Dieser Schritt muss VOR dem Mapping passieren, um die relevanten Kandidaten zu kennen)
        # --- Schritt 3a: Potenzielle Pauschalen finden ---
        # (Dieser Schritt muss VOR dem Mapping passieren, um die relevanten Kandidaten zu kennen)
        potential_pauschale_codes = set()
        rule_checked_lkns_for_search = [l.get('lkn') for l in rule_checked_leistungen if l.get('lkn')]
        lkns_in_tables = {} # Cache für Tabellenzugehörigkeit
        for lkn in rule_checked_lkns_for_search:
            for item in pauschale_lp_data: # a)
                if item.get('Leistungsposition') == lkn:
                    pc = item.get('Pauschale')
                    if pc and pc in pauschalen_dict: potential_pauschale_codes.add(pc)
            for cond in pauschale_bedingungen_data: # b)
                if cond.get('Bedingungstyp') == "LEISTUNGSPOSITIONEN IN LISTE":
                    werte_liste = [w.strip() for w in str(cond.get('Werte', "")).split(',') if w.strip()]
                    if lkn in werte_liste:
                        pc = cond.get('Pauschale')
                        if pc and pc in pauschalen_dict: potential_pauschale_codes.add(pc)
            if lkn not in lkns_in_tables: # c)
                 tables_for_lkn = set()
                 for table_name_key in tabellen_dict_by_table.keys():
                      for entry in tabellen_dict_by_table[table_name_key]:
                           if entry.get('Code') == lkn and entry.get('Tabelle_Typ') == "service_catalog": tables_for_lkn.add(table_name_key.lower())
                 lkns_in_tables[lkn] = tables_for_lkn
            tables_for_current_lkn_normalized = lkns_in_tables.get(lkn, set())
            if tables_for_current_lkn_normalized:
                for cond in pauschale_bedingungen_data:
                    if cond.get('Bedingungstyp') == "LEISTUNGSPOSITIONEN IN TABELLE":
                        table_ref_in_cond_str = cond.get('Werte', "")
                        pc = cond.get('Pauschale')
                        condition_tables_normalized = {t.strip().lower() for t in table_ref_in_cond_str.split(',') if t.strip()}
                        if not condition_tables_normalized.isdisjoint(tables_for_current_lkn_normalized):
                            if pc and pc in pauschalen_dict: potential_pauschale_codes.add(pc)
        # print(f"DEBUG: Potenzielle Pauschalen gefunden: {potential_pauschale_codes}")

        if not potential_pauschale_codes:
             print("INFO: Keine potenziellen Pauschalen gefunden. Bereite TARDOC vor.")
             final_result = regelpruefer.prepare_tardoc_abrechnung(regel_ergebnisse_liste, leistungskatalog_dict)
        else:
            # --- Schritt 3b: Relevante Bedingungs-LKNs für Mapping holen ---
            all_relevant_p_pz_candidates = get_LKNs_from_pauschalen_conditions(
                potential_pauschale_codes,
                pauschale_bedingungen_data,
                tabellen_dict_by_table,
                leistungskatalog_dict
            )

            # --- Schritt 3c: Kontextanreicherung (LKN-Mapping mit gefilterten Kandidaten) ---
            print("INFO: Starte Kontextanreicherung durch LKN-Mapping...")
            tardoc_lkns_to_map = [l for l in rule_checked_leistungen if l.get('typ') in ['E', 'EZ']]
            # print(f"DEBUG: Gefundene TARDOC LKNs zum Mappen: {[l.get('lkn') for l in tardoc_lkns_to_map]}")
            mapped_lkns = set()
            mapping_error_occurred = False

            if tardoc_lkns_to_map and all_relevant_p_pz_candidates:
                for tardoc_leistung in tardoc_lkns_to_map:
                    t_lkn = tardoc_leistung.get('lkn')
                    t_desc = tardoc_leistung.get('beschreibung')

                    # Initialisiere candidates_for_this_mapping mit allen relevanten Kandidaten
                    candidates_for_this_mapping = all_relevant_p_pz_candidates

                    # Optionale, feinere Filterung der Kandidaten für den LLM-Prompt:
                    if t_lkn and t_lkn.startswith('AG.'):
                        anast_table_content = get_table_content("ANAST", "service_catalog", tabellen_dict_by_table)
                        anast_lkn_codes = {item['Code'].upper() for item in anast_table_content if item.get('Code')}
                        
                        filtered_for_anast = {
                            k: v for k, v in all_relevant_p_pz_candidates.items()
                            if k in anast_lkn_codes or k.startswith('WA.')
                        }
                        if filtered_for_anast:
                            candidates_for_this_mapping = filtered_for_anast
                            # print(f"DEBUG: Für Mapping von {t_lkn}, spezifische Kandidaten (ANAST/WA.*) reduziert auf: {list(candidates_for_this_mapping.keys())}")
                        # else:
                            # print(f"WARNUNG: Für {t_lkn} keine spezifischen ANAST/WA.* Kandidaten in Bedingungs-LKNs gefunden. Verwende alle {len(candidates_for_this_mapping)} relevanten P/PZ-Kandidaten.")

                    if t_lkn and t_desc and candidates_for_this_mapping:
                        try:
                            mapped_code = call_gemini_stage2_mapping(t_lkn, t_desc, candidates_for_this_mapping)
                            if mapped_code:
                                if mapped_code in candidates_for_this_mapping:
                                    mapped_lkns.add(mapped_code)
                                    print(f"INFO: {t_lkn} erfolgreich auf validen Kandidaten {mapped_code} gemappt.")
                                else:
                                    print(f"WARNUNG: LLM gab {mapped_code} zurück, was nicht in der gefilterten Kandidatenliste war. Ignoriere.")
                                    mapped_code = None
                            
                            llm_stage2_results_for_frontend["mapping_results"].append({
                                "tardoc_lkn": t_lkn, "tardoc_desc": t_desc,
                                "mapped_lkn": mapped_code,
                                "candidates_considered_count": len(candidates_for_this_mapping)
                            })
                        except ConnectionError as e:
                             print(f"FEHLER: Verbindung zu LLM Stufe 2 (Mapping) fehlgeschlagen: {e}")
                             final_result = {"type": "Error", "message": f"Verbindungsfehler zum Analyse-Service (Stufe 2): {e}"}
                             mapping_error_occurred = True
                             break 
                        except Exception as e_map:
                             print(f"FEHLER bei LLM Stufe 2 (Mapping) für {t_lkn}: {e_map}")
                             traceback.print_exc()
                             llm_stage2_results_for_frontend["mapping_results"].append({
                                "tardoc_lkn": t_lkn, "tardoc_desc": t_desc,
                                "mapped_lkn": None, "error": str(e_map),
                                "candidates_considered_count": len(candidates_for_this_mapping)
                             })
                    else:
                        if t_lkn and t_desc and not candidates_for_this_mapping:
                            print(f"INFO: Mapping für {t_lkn} übersprungen, da nach Filterung keine relevanten P/PZ-Kandidaten übrig blieben.")
                        elif not (t_lkn and t_desc):
                              print(f"WARNUNG: Mapping für Eintrag übersprungen (LKN/Desc fehlen): {tardoc_leistung}")
                        llm_stage2_results_for_frontend["mapping_results"].append({
                            "tardoc_lkn": t_lkn or "N/A", "tardoc_desc": t_desc or "N/A",
                            "mapped_lkn": None,
                            "candidates_considered_count": 0,
                            "info": "Mapping übersprungen (fehlende Daten oder keine Kandidaten nach Filter)"
                        })
            else:
                 print("INFO: Überspringe Mapping (keine E/EZ LKNs oder keine relevanten P/PZ Kandidaten für Bedingungen).")
            # --- Ende Kontextanreicherung ---

            # --- Nur weitermachen, wenn kein schwerwiegender Mapping-Fehler ---
            if not mapping_error_occurred:
                # --- Finalen Kontext für Pauschalenprüfung erstellen ---
                final_pauschale_lkn_context_set = set(l['lkn'] for l in rule_checked_leistungen if l.get('lkn'))
                final_pauschale_lkn_context_set.update(mapped_lkns)
                final_pauschale_lkn_context_list = list(final_pauschale_lkn_context_set)
                print(f"INFO: Finaler LKN-Kontext für Pauschalenprüfung (inkl. Mapping): {final_pauschale_lkn_context_list}")
                pauschale_context = {
                    "ICD": icd_input, "GTIN": gtin_input,
                    "Alter": alter_context, "Geschlecht": geschlecht_context,
                    "useIcd": use_icd_flag, "LKN": final_pauschale_lkn_context_list
                }

                # --- Pauschalenprüfung durchführen ---
                try:
                    print(f"INFO: Versuche, Pauschale zu finden (useIcd={use_icd_flag}, gemappter Kontext)...")
                    pauschale_pruef_ergebnis = regelpruefer_pauschale.determine_applicable_pauschale(
                        user_input, rule_checked_leistungen, pauschale_context,
                        pauschale_lp_data, pauschale_bedingungen_data, pauschalen_dict,
                        leistungskatalog_dict, tabellen_dict_by_table,
                        potential_pauschale_codes
                    )
                    final_result = pauschale_pruef_ergebnis
                    if final_result.get("type") != "Pauschale":
                         print(f"INFO: Keine anwendbare Pauschale gefunden ({final_result.get('message')}). Bereite TARDOC vor.")
                         final_result = regelpruefer.prepare_tardoc_abrechnung(regel_ergebnisse_liste, leistungskatalog_dict)
                    else:
                         print("INFO: Anwendbare Pauschale gefunden.")
                except Exception as e:
                     print(f"FEHLER bei Pauschalen-/TARDOC-Entscheidung nach Mapping: {e}")
                     traceback.print_exc()
                     final_result = {"type": "Error", "message": f"Interner Fehler bei Abrechnungsentscheidung: {e}"}
                # --- Ende Pauschalenprüfung ---

    # Fallback
    if final_result is None:
        print("FEHLER: final_result wurde nicht gesetzt! Fallback zu TARDOC/Error.")
        if rule_checked_leistungen:
             final_result = regelpruefer.prepare_tardoc_abrechnung(regel_ergebnisse_liste, leistungskatalog_dict)
        else:
             final_result = {"type": "Error", "message": "Keine abrechenbaren Leistungen gefunden."}
    # --- ENDE Entscheidung Pauschale vs. TARDOC ---

    decision_time = time.time()
    print(f"Zeit nach Entscheidung Pauschale/TARDOC: {decision_time - rule_time:.2f}s") # rule_time ist hier evtl. nicht definiert

    # 5. Ergebnis an Frontend senden
    final_response = {
        "llm_ergebnis_stufe1": llm_stage1_result,
        "regel_ergebnisse_details": regel_ergebnisse_liste,
        "abrechnung": final_result,
        "llm_ergebnis_stufe2": llm_stage2_results_for_frontend # Enthält jetzt mapping_results
    }

    end_time = time.time()
    # Berechne Gesamtzeit
    total_time = end_time - start_time
    print(f"Gesamtverarbeitungszeit Backend: {total_time:.2f}s")
    print(f"INFO: Sende finale Antwort Typ '{final_result.get('type')}' an Frontend.")
    return jsonify(final_response)

# --- Static‑Routes & Start ---
@app.route("/")
def index(): return send_from_directory(".", "index.html")

@app.route("/favicon.ico")
def favicon_ico(): return send_from_directory(".", "favicon.ico", mimetype='image/vnd.microsoft.icon')

@app.route("/favicon.svg")
def favicon_svg(): return send_from_directory(".", "favicon.svg", mimetype='image/svg+xml')

@app.route("/<path:filename>")
def serve_static(filename):
    # Sicherstellen, dass nur erlaubte Dateien ausgeliefert werden
    allowed_files = {'calculator.js'}
    allowed_dirs = {'data'}

    file_path = Path(filename)
    # Verhindere Zugriff auf Python-Dateien, .env, versteckte Dateien/Ordner
    if (file_path.suffix in ['.py', '.txt', '.env'] or
        any(part.startswith('.') for part in file_path.parts)):
         print(f"WARNUNG: Zugriff verweigert (sensible Datei): {filename}")
         abort(404)

    # Erlaube JS-Datei oder Dateien im data-Verzeichnis
    if filename in allowed_files or (len(file_path.parts) > 0 and file_path.parts[0] in allowed_dirs):
         #print(f"INFO: Sende statische Datei: {filename}")
         return send_from_directory('.', filename)
    else:
         print(f"WARNUNG: Zugriff verweigert (nicht erlaubt): {filename}")
         abort(404)

if __name__ == "__main__":
    print("INFO: Starte Server direkt (lokales Debugging). Lade Daten initial...")
    load_data()
    print(f"🚀 Server läuft lokal für Debugging → http://127.0.0.1:8000")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
    # app.run(host="127.0.0.1", port=8000, debug=True) # Debug=True für Entwicklung