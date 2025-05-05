# server.py - Zweistufiger LLM-Ansatz mit Backend-Regelprüfung (Erweitert)
import os
import re
import json
import time # für Zeitmessung
import html # für escaping
import traceback # für detaillierte Fehlermeldungen
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, request, abort
import requests
from dotenv import load_dotenv
import regelpruefer
import regelpruefer_pauschale

# Importiere Regelprüfer-Module und setze Fallbacks
try:
    import regelpruefer
    print("✓ Regelprüfer LKN (regelpruefer.py) Modul geladen.")
except ImportError:
    print("FEHLER: regelpruefer.py nicht gefunden.")
    class DummyRegelpruefer:
        def lade_regelwerk(self, path): return {}
        def pruefe_abrechnungsfaehigkeit(self, fall, werk): return {"abrechnungsfaehig": False, "fehler": ["Regelprüfer LKN nicht geladen."]}
    regelpruefer = DummyRegelpruefer() # type: ignore

try:
    import regelpruefer_pauschale
    if not hasattr(regelpruefer_pauschale, 'check_pauschale_conditions'):
         print("WARNUNG: Funktion 'check_pauschale_conditions' nicht in regelpruefer_pauschale.py gefunden.")
         def check_pauschale_conditions_fallback(pauschale_code, context, pauschale_bedingungen_data, tabellen_dict_by_table):
             print(f"WARNUNG: Bedingungsprüfung für {pauschale_code} übersprungen (Fallback).")
             return {"allMet": True, "html": "<p><i>Bedingungsprüfung nicht verfügbar.</i></p>", "errors": []}
         if 'regelpruefer_pauschale' in locals(): # Nur zuweisen, wenn Modul importiert wurde
             regelpruefer_pauschale.check_pauschale_conditions = check_pauschale_conditions_fallback # type: ignore
    else:
         print("✓ Regelprüfer Pauschalen (regelpruefer_pauschale.py) geladen.")
except ImportError:
    print("FEHLER: regelpruefer_pauschale.py nicht gefunden.")
    def check_pauschale_conditions_fallback(pauschale_code, context, pauschale_bedingungen_data, tabellen_dict_by_table):
        print(f"WARNUNG: Bedingungsprüfung für {pauschale_code} übersprungen (Fallback).")
        return {"allMet": False, "html": "<p><i>Regelprüfer Pauschale nicht geladen.</i></p>", "errors": ["Regelprüfer Pauschale nicht geladen"]}
    # Erstelle Dummy-Modul, falls Import fehlschlägt
    class DummyPauschaleRegelpruefer:
         def check_pauschale_conditions(self, pc, ctx, bed_data, tab_dict): return check_pauschale_conditions_fallback(pc, ctx, bed_data, tab_dict)
    if 'regelpruefer_pauschale' not in locals(): regelpruefer_pauschale = DummyPauschaleRegelpruefer() # type: ignore


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

# --- Globale Datencontainer ---
app = Flask(__name__, static_folder='.', static_url_path='')
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


# --- Daten laden ---
def load_data():
    # ... (load_data Funktion bleibt unverändert wie im letzten Schritt) ...
    global leistungskatalog_data, leistungskatalog_dict, regelwerk_dict, tardoc_data_dict
    global pauschale_lp_data, pauschalen_data, pauschalen_dict, pauschale_bedingungen_data, tabellen_data
    global tabellen_dict_by_table # NEU

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
    tabellen_dict_by_table.clear() # NEU

    all_loaded = True
    for name, (path, target_list, key_field, target_dict) in files_to_load.items():
        try:
            if path.is_file():
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if not isinstance(data, list):
                         print(f"WARNUNG: {name}-Daten in '{path}' sind keine Liste, überspringe.")
                         continue

                    # Fülle das Dictionary, falls gewünscht
                    if target_dict is not None and key_field is not None:
                         current_key_field = key_field # Lokale Variable für Klarheit
                         for item in data:
                              if isinstance(item, dict):
                                   key_value = item.get(current_key_field)
                                   if key_value:
                                       target_dict[str(key_value)] = item # Schlüssel immer als String
                                   else:
                                       print(f"WARNUNG: Eintrag in {name} ohne Schlüssel '{current_key_field}': {str(item)[:100]}...")
                              else:
                                   print(f"WARNUNG: Ungültiger Eintrag (kein Dict) in {name}: {str(item)[:100]}...")
                         print(f"✓ {name}-Daten '{path}' geladen ({len(target_dict)} Einträge im Dict).")
                         # if name == "Leistungskatalog":
                            # print("--- DEBUG: Prüfung leistungskatalog_dict ---")
                            # test_key_wrong = 'C08.AH.0010'
                            # test_key_correct = 'C03.AH.0010'
                            # if test_key_wrong in target_dict:
                            #     print(f"FEHLER ALARM: Unerwarteter Schlüssel '{test_key_wrong}' in leistungskatalog_dict gefunden!")
                            #     print(f"   -> Wert: {target_dict[test_key_wrong]}")
                            # else:
                            #     print(f"INFO: Korrekt - Schlüssel '{test_key_wrong}' NICHT in leistungskatalog_dict gefunden.")
                            #
                            # if test_key_correct in target_dict:
                            #     print(f"INFO: Korrekt - Schlüssel '{test_key_correct}' in leistungskatalog_dict gefunden.")
                            #     print(f"   -> Wert: {target_dict[test_key_correct]}")
                            # else:
                            #     print(f"FEHLER ALARM: Erwarteter Schlüssel '{test_key_correct}' NICHT in leistungskatalog_dict gefunden!")
                            # print("--- ENDE DEBUG: Prüfung leistungskatalog_dict ---")
                    # Fülle die Liste, falls gewünscht
                    if target_list is not None:
                         target_list.extend(data)
                         # Info nur wenn nicht schon Dict-Info kam
                         if target_dict is None:
                              print(f"✓ {name}-Daten '{path}' geladen ({len(target_list)} Einträge in Liste).")

                    # Fülle tabellen_dict_by_table
                    if name == "Tabellen":
                        TAB_KEY = "Tabelle" # <<< PRÜFEN: Ist dieser Schlüssel korrekt?
                        print(f"DEBUG (load_data): Beginne Gruppierung für '{name}' mit Schlüssel '{TAB_KEY}'...")
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
                                        # Logge nur, wenn ein *neuer* Key erstellt wird
                                        # print(f"DEBUG (load_data): Neuer Key erstellt: '{normalized_key}' (Original: '{table_name}')")
                                    tabellen_dict_by_table[normalized_key].append(item)
                                else:
                                    # Logge Items ohne den erwarteten Schlüssel
                                    print(f"WARNUNG (load_data): Eintrag {item_index} in '{name}' fehlt Schlüssel '{TAB_KEY}'. Item: {str(item)[:100]}...")
                            else:
                                # Logge ungültige Items
                                print(f"WARNUNG (load_data): Eintrag {item_index} in '{name}' ist kein Dictionary. Item: {str(item)[:100]}...")

                        print(f"DEBUG (load_data): Gruppierung für '{name}' abgeschlossen. {items_processed} Items verarbeitet.")
                        print(f"✓ Tabellen-Daten gruppiert nach Tabelle ({len(tabellen_dict_by_table)} Tabellen, {len(keys_created)} neue Schlüssel erstellt).")
                        # Prüfe spezifische Schlüssel nach der Gruppierung
                        missing_keys_check = ['cap13', 'cap14', 'or', 'nonor', 'nonelt', 'ambp.pz']
                        found_keys_check = {k for k in missing_keys_check if k in tabellen_dict_by_table}
                        not_found_keys_check = {k for k in missing_keys_check if k not in tabellen_dict_by_table}
                        print(f"DEBUG (load_data): Prüfung spezifischer Schlüssel: Gefunden={found_keys_check}, Fehlend={not_found_keys_check}")
                        if not_found_keys_check:
                             print(f"FEHLER: Kritische Tabellenschlüssel fehlen in tabellen_dict_by_table!")
                             # Optional: Zeige einige der tatsächlich vorhandenen Schlüssel zum Vergleich
                             print(f"DEBUG: Vorhandene Schlüssel (Auszug): {list(tabellen_dict_by_table.keys())[:50]}")              
            else:
                print(f"FEHLER: {name}-Datei nicht gefunden: {path}")
                if name in ["Leistungskatalog", "Pauschalen", "TARDOC", "PauschaleBedingungen", "Tabellen"]: all_loaded = False # Kritische Daten fehlen
        except json.JSONDecodeError as e:
             print(f"FEHLER beim Parsen der {name}-JSON-Datei ({path}): {e}")
             all_loaded = False
        except Exception as e:
             print(f"FEHLER beim Laden der {name}-Daten ({path}): {e}")
             all_loaded = False

    # Lade Regelwerk LKN
    if regelpruefer and hasattr(regelpruefer, 'lade_regelwerk'):
        if REGELWERK_PATH.is_file():
            regelwerk_dict = regelpruefer.lade_regelwerk(str(REGELWERK_PATH))
            print(f"✓ Regelwerk (LKN) '{REGELWERK_PATH}' geladen ({len(regelwerk_dict)} LKNs).")
        else:
            print(f"FEHLER: Regelwerk (LKN) nicht gefunden: {REGELWERK_PATH}")
            regelwerk_dict = {}
            all_loaded = False # Regeln sind wichtig
    else:
        print("ℹ️ Regelprüfung (LKN) nicht verfügbar oder lade_regelwerk fehlt.")
        regelwerk_dict = {}

    print("--- Daten laden abgeschlossen ---")
    if not all_loaded: print("WARNUNG: Einige kritische Daten konnten nicht geladen werden!")

# --- LLM Stufe 1: LKN Identifikation ---
def call_gemini_stage1(user_input: str, katalog_context: str) -> dict:
    if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY nicht konfiguriert.")
    prompt = f"""**Aufgabe:** Analysiere den folgenden medizinischen Behandlungstext aus der Schweiz äußerst präzise. Deine einzige Aufgabe ist die Identifikation relevanter Leistungs-Katalog-Nummern (LKN), deren Menge und die Extraktion spezifischer Kontextinformationen basierend **ausschließlich** auf dem bereitgestellten Leistungskatalog.

**Kontext: Leistungskatalog (Dies ist die EINZIGE Quelle für gültige LKNs und deren Beschreibungen! Ignoriere jegliches anderes Wissen.)**
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

**Anweisungen:** Führe die folgenden Schritte exakt aus:

1.  **LKN Identifikation & STRIKTE Validierung:**
    *   Lies den "Behandlungstext" sorgfältig.
    *   Identifiziere **alle** potenziellen LKN-Codes (Format `XX.##.####`), die die beschriebenen Tätigkeiten repräsentieren könnten.
    *   **ABSOLUT KRITISCH:** Für JEDEN potenziellen LKN-Code: Überprüfe **BUCHSTABE FÜR BUCHSTABE und ZIFFER FÜR ZIFFER**, ob dieser Code **EXAKT** so im obigen "Leistungskatalog" als 'LKN:' vorkommt. Achte besonders auf die ersten Zeichen (z.B. 'C03.' vs. 'C08.').
    *   Erstelle eine Liste (`identified_leistungen`) **AUSSCHLIESSLICH** mit den LKNs, die diese **exakte** Prüfung im Katalog bestanden haben.
    *   **VERBOTEN:** Gib niemals LKNs aus, die nicht exakt im Katalog stehen, auch wenn sie ähnlich klingen oder thematisch passen könnten. Erfinde keine LKNs.
    *   Wenn eine Dauer genannt wird, die Basis- und Zuschlagsleistung erfordert, stelle sicher, dass **beide** LKNs (Basis + Zuschlag) identifiziert und **validiert** werden.

2.  **Typ & Beschreibung hinzufügen:**
    *   Füge für jede **validierte** LKN in der `identified_leistungen`-Liste den korrekten `typ` und die `beschreibung` **direkt und unverändert aus dem bereitgestellten Katalogkontext** hinzu.

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
  "extracted_info": {{ ... }},
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

        print(f"DEBUG: Roher Text von LLM Stufe 1 (gehärtet, gekürzt):\n---\n{raw_text_response[:500]}...\n---")

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

        print(f"DEBUG: Geparstes LLM JSON Stufe 1 VOR Validierung: {json.dumps(llm_response_json, indent=2, ensure_ascii=False)}")

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
    payload = { "contents": [{"parts": [{"text": prompt}]}], "generationConfig": { "temperature": 0.0, "maxOutputTokens": 500 } } # Temp 0.0 für deterministisches Ranking
    print(f"Sende Anfrage Stufe 2 (Ranking) an Gemini Model: {GEMINI_MODEL}...")
    try:
        response = requests.post(gemini_url, json=payload, timeout=45)
        print(f"Gemini Stufe 2 Antwort Status Code: {response.status_code}")
        response.raise_for_status()
        gemini_data = response.json()

        if not gemini_data.get('candidates'): raise ValueError("Keine Kandidaten in Stufe 2 Antwort.")
        ranked_text = gemini_data['candidates'][0]['content']['parts'][0]['text']
        print(f"DEBUG: Roher Text von LLM Stufe 2 (Ranking):\n---\n{ranked_text}\n---")
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
        print(f"DEBUG (get_table_content): Suche normalisierten Schlüssel '{normalized_key}' für Typ '{table_type}'")

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

# --- API Endpunkt ---
@app.route('/api/analyze-billing', methods=['POST'])
def analyze_billing():
    print("\n--- Request an /api/analyze-billing erhalten ---")
    start_time = time.time() # Zeitmessung starten

    # 1. Eingaben holen
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json(); 
    user_input = data.get('inputText'); 
    icd_input = data.get('icd', []); 
    gtin_input = data.get('gtin', [])
    use_icd_flag = data.get('useIcd', True) # Default True
    if not user_input: return jsonify({"error": "'inputText' is required"}), 400
    print(f"Empfangener inputText: '{user_input[:100]}...'")
    print(f"Empfangene ICDs: {icd_input}, GTINs: {gtin_input}")

    # Stelle sicher, dass Daten geladen sind
    if not leistungskatalog_dict or not pauschalen_dict or not tardoc_data_dict or not pauschale_bedingungen_data or not tabellen_data: # Füge fehlende hinzu
         print("FEHLER: Kritische Daten nicht geladen. Analyse abgebrochen.")
         return jsonify({"error": "Kritische Server-Daten nicht geladen. Bitte Administrator kontaktieren."}), 503
    
    # 2. LLM Stufe 1: LKNs identifizieren
    llm_stage1_result = None
    try:
        # Erstelle Katalog-Kontext nur mit relevanten Feldern
        katalog_context = "\n".join([
            f"LKN: {item.get('LKN', 'N/A')}, Typ: {item.get('Typ', 'N/A')}, Beschreibung: {item.get('Beschreibung', 'N/A')}"
            for item in leistungskatalog_data # Nutze Liste für Reihenfolge? Oder Dict? Dict ist schneller für Lookup.
            if item.get('LKN') # Nur wenn LKN existiert
        ])
        if not katalog_context: raise ValueError("Leistungskatalog für LLM-Kontext ist leer.")

        # print("--- DEBUG: Prüfung katalog_context ---")
        # test_key_wrong = 'C08.AH.0010'
        # test_key_correct = 'C03.AH.0010'
        # if test_key_wrong in katalog_context:
        #      print(f"FEHLER ALARM: Unerwarteter LKN '{test_key_wrong}' im katalog_context gefunden!")
        #       # Finde die Zeile(n)
        #       lines_with_wrong_key = [line for line in katalog_context.splitlines() if test_key_wrong in line]
        #       print(f"   -> Zeilen: {lines_with_wrong_key}")
        #  else:
        #       print(f"INFO: Korrekt - LKN '{test_key_wrong}' NICHT im katalog_context gefunden.")
        #
        #  if test_key_correct in katalog_context:
        #       print(f"INFO: Korrekt - LKN '{test_key_correct}' im katalog_context gefunden.")
        #  else:
        #       print(f"FEHLER ALARM: Erwarteter LKN '{test_key_correct}' NICHT im katalog_context gefunden!")
        #  print("--- ENDE DEBUG: Prüfung katalog_context ---")

        llm_stage1_result = call_gemini_stage1(user_input, katalog_context)

    except ConnectionError as e:
         print(f"FEHLER: Verbindung zu LLM Stufe 1 fehlgeschlagen: {e}")
         return jsonify({"error": f"Verbindungsfehler zum Analyse-Service (Stufe 1): {e}"}), 504 # Gateway Timeout
    except ValueError as e: # Fängt Validierungsfehler und andere Fehler von call_gemini_stage1
         print(f"FEHLER: Verarbeitung LLM Stufe 1 fehlgeschlagen: {e}")
         return jsonify({"error": f"Fehler bei der Leistungsanalyse (Stufe 1): {e}"}), 400 # Bad Request oder 500? Eher 400 wenn Input/Format Problem
    except Exception as e:
         print(f"FEHLER: Unerwarteter Fehler bei LLM Stufe 1: {e}")
         return jsonify({"error": f"Unerwarteter interner Fehler (Stufe 1): {e}"}), 500 # Internal Server Error

    llm1_time = time.time()
    print(f"Zeit nach LLM Stufe 1: {llm1_time - start_time:.2f}s")

    # *** Validierung der vom LLM identifizierten LKNs gegen lokalen Katalog ***
    validated_leistungen_llm = []
    identified_leistungen_raw = llm_stage1_result.get("identified_leistungen", [])
    if not identified_leistungen_raw:
         print("WARNUNG: LLM Stufe 1 hat keine Leistungen identifiziert.")
    else:
        for leistung in identified_leistungen_raw:
            lkn = leistung.get("lkn")
            menge_llm = leistung.get("menge", 1) # Menge aus LLM holen

            # Prüfe, ob LKN existiert und im lokalen Katalog vorhanden ist
            local_data = leistungskatalog_dict.get(str(lkn).upper()) # Immer upper case suchen
            if local_data:
                 # Überschreibe Typ und Beschreibung mit lokalen Daten für Konsistenz
                 leistung["typ"] = local_data.get("Typ", leistung.get("typ"))
                 leistung["beschreibung"] = local_data.get("Beschreibung", leistung.get("beschreibung"))
                 leistung["lkn"] = str(lkn).upper() # LKN normalisieren
                 leistung["menge"] = max(1, int(menge_llm)) # Sicherstellen, dass Menge >= 1 ist
                 validated_leistungen_llm.append(leistung)
            else:
                 print(f"WARNUNG: Vom LLM identifizierte LKN '{lkn}' nicht im lokalen Katalog gefunden. Wird ignoriert.")

        # Verwende die validierte Liste für die weitere Verarbeitung
        identified_leistungen_llm = validated_leistungen_llm
        # Aktualisiere das Ergebnisobjekt für Transparenz (wichtig für Frontend)
        llm_stage1_result["identified_leistungen"] = identified_leistungen_llm
        print(f"INFO: {len(identified_leistungen_llm)} LKNs nach Validierung durch LLM Stufe 1 identifiziert.")


    # 3. Regelprüfung für identifizierte LKNs
    regel_ergebnisse_liste = [] # Wird an Frontend gesendet
    rule_checked_leistungen = [] # Nur regelkonforme für Pauschalen-/TARDOC-Entscheid
    extracted_info = llm_stage1_result.get("extracted_info", {})
    alter_llm = extracted_info.get("alter"); geschlecht_llm = extracted_info.get("geschlecht")
    # Liste aller validierten LKNs für den 'Begleit_LKNs'-Kontext
    alle_validen_lkn = [l.get("lkn") for l in identified_leistungen_llm if l.get("lkn")]

    if not identified_leistungen_llm:
         # Spezieller Eintrag für Frontend, wenn LLM nichts fand
         regel_ergebnisse_liste.append({
             "lkn": None,
             "initiale_menge": 0,
             "regelpruefung": {"abrechnungsfaehig": False, "fehler": ["Keine gültige LKN vom LLM identifiziert oder im Katalog gefunden."]},
             "finale_menge": 0
         })
    else:
        for leistung in identified_leistungen_llm:
            lkn = leistung.get("lkn")
            menge_initial = leistung.get("menge", 1) # Bereits validierte Menge >= 1

            print(f"INFO: Prüfe Regeln für LKN {lkn} (Initiale Menge: {menge_initial})")
            regel_ergebnis = {"abrechnungsfaehig": False, "fehler": ["Regelprüfung nicht durchgeführt."]}
            angepasste_menge = 0 # Standard: Nicht abrechenbar

            if regelpruefer and regelwerk_dict:
                # Kontext für die Regelprüfung dieser LKN
                abrechnungsfall = {
                    "LKN": lkn,
                    "Menge": menge_initial,
                    # Begleitleistungen sind ALLE ANDEREN validierten LKNs aus Stufe 1
                    "Begleit_LKNs": [b_lkn for b_lkn in alle_validen_lkn if b_lkn != lkn],
                    "ICD": icd_input,
                    "Geschlecht": geschlecht_llm,
                    "Alter": alter_llm,
                    "Pauschalen": [], # Pauschalen werden hier noch nicht berücksichtigt
                    "GTIN": gtin_input
                }
                try:
                    regel_ergebnis = regelpruefer.pruefe_abrechnungsfaehigkeit(abrechnungsfall, regelwerk_dict)

                    if regel_ergebnis.get("abrechnungsfaehig"):
                        angepasste_menge = menge_initial # Menge bleibt, wenn OK
                    else:
                        # Versuch, Menge anzupassen bei reinem Mengenfehler
                        fehler_liste = regel_ergebnis.get("fehler", [])
                        fehler_ohne_menge = [f for f in fehler_liste if "Mengenbeschränkung" not in f and "reduziert" not in f]
                        mengen_fehler = [f for f in fehler_liste if "Mengenbeschränkung" in f]

                        if not fehler_ohne_menge and mengen_fehler: # Nur Mengenfehler
                            max_menge_match = None
                            match = re.search(r'max\.\s*(\d+(\.\d+)?)', mengen_fehler[0]) # Sucht nach "max. Zahl"
                            if match:
                                try: max_menge_match = int(float(match.group(1))) # Erst float, dann int
                                except ValueError: pass

                            if max_menge_match is not None and menge_initial > max_menge_match:
                                angepasste_menge = max_menge_match
                                print(f"INFO: Menge für LKN {lkn} aufgrund Regel angepasst: {menge_initial} -> {angepasste_menge}.")
                                # Formatiere Fehlermeldung für Frontend
                                regel_ergebnis["fehler"] = [f"Menge auf {angepasste_menge} reduziert (Regel: max. {max_menge_match}, LLM-Vorschlag: {menge_initial})"]
                                regel_ergebnis["abrechnungsfaehig"] = True # Gilt jetzt als abrechnungsfähig mit angepasster Menge
                            else:
                                angepasste_menge = 0 # Menge auf 0 setzen, wenn Anpassung nicht möglich/nötig
                                print(f"INFO: LKN {lkn} nicht abrechnungsfähig wegen Mengenfehler (Anpassung nicht möglich/nötig).")
                        else:
                             angepasste_menge = 0 # Menge auf 0 bei anderen Fehlern
                             print(f"INFO: LKN {lkn} nicht abrechnungsfähig wegen Regel: {fehler_ohne_menge or fehler_liste}")

                except Exception as e_rule:
                    print(f"FEHLER bei Regelprüfung für LKN {lkn}: {e_rule}")
                    regel_ergebnis = {"abrechnungsfaehig": False, "fehler": [f"Interner Fehler bei Regelprüfung: {e_rule}"]}
                    angepasste_menge = 0
            else:
                 # Keine Regelprüfung möglich
                 print(f"WARNUNG: Keine Regelprüfung für LKN {lkn} durchgeführt (Regelprüfer/Regelwerk fehlt). Annahme: Nicht abrechnungsfähig.")
                 regel_ergebnis = {"abrechnungsfaehig": False, "fehler": ["Regelprüfung nicht verfügbar."]}
                 angepasste_menge = 0 # Sicherheitshalber auf 0

            # Ergebnis für Frontend speichern
            regel_ergebnisse_liste.append({
                "lkn": lkn,
                "initiale_menge": menge_initial, # Wichtig für Transparenz im Frontend
                "regelpruefung": regel_ergebnis,
                "finale_menge": angepasste_menge
            })

            # Nur wenn abrechnungsfähig und Menge > 0 zur nächsten Stufe
            if regel_ergebnis.get("abrechnungsfaehig") and angepasste_menge > 0:
                # Füge die *regelkonforme* Leistung zur Liste für die Pauschal/TARDOC-Entscheidung hinzu
                rule_checked_leistungen.append({
                    **leistung, # Nimm ursprüngliche Infos (Typ, Beschreibung)
                    "menge": angepasste_menge # Aber mit der finalen Menge
                })

    rule_time = time.time()
    print(f"Zeit nach Regelprüfung: {rule_time - llm1_time:.2f}s")

    # 4. ENTSCHEIDUNG Pauschale vs. TARDOC (NEUE LOGIK)
    final_result = {"type": "Error", "message": "Abrechnungsentscheidung fehlgeschlagen."}
    pauschale_context = {
        "ICD": icd_input, "GTIN": gtin_input,
        "Alter": alter_llm, "Geschlecht": geschlecht_llm,
        "useIcd": use_icd_flag # Flag weitergeben
    }

    if not rule_checked_leistungen:
         print("WARNUNG: Keine regelkonformen Leistungen nach Regelprüfung übrig.")
         # Rufe TARDOC-Vorbereitung direkt auf
         final_result = regelpruefer.prepare_tardoc_abrechnung(
             regel_ergebnisse_liste,
             leistungskatalog_dict # Übergebe das Katalog-Dict
         )
    else:
        try:
            print(f"INFO: Versuche, Pauschale für {len(rule_checked_leistungen)} Leistung(en) zu finden (useIcd={use_icd_flag})...")
            # Rufe determine_applicable_pauschale mit dem Kontext auf
            pauschale_pruef_ergebnis = regelpruefer_pauschale.determine_applicable_pauschale(
                user_input, rule_checked_leistungen, pauschale_context,
                # Übergebe die globalen Daten-Dictionaries
                pauschale_lp_data,
                pauschale_bedingungen_data,
                pauschalen_dict,
                leistungskatalog_dict,
                tabellen_dict_by_table
            )

            # Prüfe das Ergebnis der Pauschalenprüfung
            if pauschale_pruef_ergebnis.get("type") == "Pauschale":
                print("INFO: Anwendbare Pauschale gefunden.")
                final_result = pauschale_pruef_ergebnis
            else:
                # Keine Pauschale gefunden oder anwendbar -> TARDOC
                print(f"INFO: Keine anwendbare Pauschale gefunden ({pauschale_pruef_ergebnis.get('message')}). Bereite TARDOC vor.")
                final_result = regelpruefer.prepare_tardoc_abrechnung(
                    regel_ergebnisse_liste,
                    leistungskatalog_dict # Übergebe das Katalog-Dict
                )
        except ConnectionError as e:
             print(f"FEHLER: Verbindung zu LLM Stufe 2 fehlgeschlagen: {e}")
             final_result = {"type": "Error", "message": f"Verbindungsfehler zum Analyse-Service (Stufe 2): {e}"}
        except Exception as e:
             print(f"FEHLER bei Pauschalen-/TARDOC-Entscheidung: {e}")
             # Traceback loggen für Debugging
             traceback.print_exc()
             final_result = {"type": "Error", "message": f"Interner Fehler bei Abrechnungsentscheidung: {e}"}


    decision_time = time.time()
    print(f"Zeit nach Entscheidung Pauschale/TARDOC: {decision_time - rule_time:.2f}s")

    # 5. Kombiniertes Ergebnis an Frontend senden
    final_response = {
        "llm_ergebnis_stufe1": llm_stage1_result,
        "regel_ergebnisse_details": regel_ergebnisse_liste,
        "abrechnung": final_result
    }

    end_time = time.time()
    print(f"Gesamtverarbeitungszeit Backend: {end_time - start_time:.2f}s")
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
    load_data() # Lade Daten beim Start
    print(f"🚀 Server läuft → http://127.0.0.1:8000")
    print(f"   Regelprüfer LKN: {'Aktiv' if regelpruefer and hasattr(regelpruefer, 'pruefe_abrechnungsfaehigkeit') else 'Inaktiv'}")
    print(f"   Regelprüfer Pauschale: {'Aktiv' if regelpruefer_pauschale and hasattr(regelpruefer_pauschale, 'check_pauschale_conditions') else 'Inaktiv'}")
    # Wichtige Daten prüfen
    if not leistungskatalog_dict: print("   WARNUNG: Leistungskatalog nicht geladen!")
    if not pauschalen_dict: print("   WARNUNG: Pauschalen nicht geladen!")
    if not tardoc_data_dict: print("   WARNUNG: TARDOC-Daten nicht geladen!")
    if not regelwerk_dict: print("   WARNUNG: LKN-Regelwerk nicht geladen!")
    if not pauschale_bedingungen_data: print("   WARNUNG: Pauschalen-Bedingungen nicht geladen!")
    if not tabellen_dict_by_table: print("   WARNUNG: Referenz-Tabellen nicht geladen/gruppiert!")

    app.run(host="127.0.0.1", port=8000, debug=True) # Debug=True für Entwicklung