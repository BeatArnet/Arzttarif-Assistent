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
                         continue # Überspringe, wenn es keine Liste ist

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

                    # Fülle die Liste, falls gewünscht
                    if target_list is not None:
                         target_list.extend(data)
                         # Info nur wenn nicht schon Dict-Info kam
                         if target_dict is None:
                              print(f"✓ {name}-Daten '{path}' geladen ({len(target_list)} Einträge in Liste).")

                    # NEU: Fülle tabellen_dict_by_table
                    if name == "Tabellen":
                        TAB_KEY = "Tabelle" # Schlüssel für den Tabellennamen
                        for item in data:
                            if isinstance(item, dict):
                                table_name = item.get(TAB_KEY)
                                if table_name:
                                    if table_name not in tabellen_dict_by_table:
                                        tabellen_dict_by_table[table_name] = []
                                    tabellen_dict_by_table[table_name].append(item)
                        print(f"✓ Tabellen-Daten gruppiert nach Tabelle ({len(tabellen_dict_by_table)} Tabellen).")

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
    # ... (call_gemini_stage1 Funktion bleibt unverändert wie im letzten Schritt) ...
    if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY nicht konfiguriert.")
    # *** PROMPT STUFE 1 ***
    prompt = f"""Analysiere den folgenden medizinischen Behandlungstext aus der Schweiz SEHR GENAU.
    Deine Aufgabe ist es, ALLE relevanten Leistungs-Katalog-Nummern (LKN) zu identifizieren, deren korrekte Menge zu bestimmen und zusätzliche Informationen zu extrahieren.
    NUTZE ausschliesslich DIE FOLGENDE LISTE ALS DEINE PRIMÄRE REFERENZ für verfügbare LKNs, ihre Typen und Bedeutungen. Ignoriere jegliches anderes Wissen über LKNs:
    --- Leistungskatalog Start ---
    {katalog_context}
    --- Leistungskatalog Ende ---

Führe folgende Schritte durch:
1. Identifiziere ALLE relevanten LKN-Codes (Format: XX.##.####) aus der obigen Liste, 
    die die beschriebene(n) Tätigkeit(en) am besten repräsentieren. 
    Achte auf Schlüsselwörter wie "Hausarzt"/"hausärztlich" für CA.-Codes. 
    Wenn eine Dauer genannt wird, die Basis- und Zuschlagsleistung erfordert (z.B. Konsultation), 
    gib BEIDE LKNs an (z.B. CA.00.0010 und CA.00.0020). 
    Gib niemals 'unknown' oder null als LKN zurück. Nur die LKNs aus der Liste verwenden!
2. Gib für jede identifizierte LKN den zugehörigen Typ und die Beschreibung aus dem Katalog an.
3. Extrahiere explizit genannte Zeitdauern (nur Zahl in Minuten), allgemeine Mengenangaben (z.B. "3 mal", "2 Stück" -> nur Zahl), Alter (nur Zahl) und Geschlecht ('weiblich', 'männlich', 'divers', 'unbekannt') aus dem "Behandlungstext". Gib null an, wenn nichts gefunden wird.
4. **Bestimme die abzurechnende Menge für JEDE identifizierte LKN und schreibe sie als ZAHL in das 'menge'-Feld:**
    - Standardmenge ist 1.
    - **Konsultationsdauer:** WENN eine LKN "pro 5 Min." oder "pro 1 Min." im Katalog hat UND eine Dauer im Text genannt wird (siehe Schritt 3), DANN setze die 'menge' auf die extrahierte Dauer in Minuten (z.B. `menge: 17` für 17 Minuten).
    - **Konsultationszuschlag:** WENN es sich um eine Zuschlagsleistung für Konsultationen handelt (z.B. CA.00.0020 "weitere 5 Min.") UND eine Gesamtdauer extrahiert wurde, DANN berechne die Menge als (Gesamtdauer - Basisdauer [meist 5 Min, siehe Basis-LKN Beschreibung]) / Zuschlagsintervall [meist 5 Min]. Beispiel: Konsultation 17 Min. -> Basis CA.00.0010 (Menge 1) + Zuschlag CA.00.0020 (Menge = (17-5)/5 = 2.4 -> aufrunden auf 3?). *Korrektur: Oft wird die Dauer direkt verwendet. Prüfe die LKN-Beschreibung im Katalog genau!* Wenn CA.00.0020 "pro 5 Min." ist, und die Dauer 17 Min ist, braucht es CA.00.0010 (Menge 1) und CA.00.0020 (Menge 12 -> 17-5=12). *Nochmal Korrektur*: CA.00.0010 (erste 5 Min, Menge 1), CA.00.0020 (pro WEITERE 5 Min). Für 17 Min: 1x CA.00.0010 + 2x CA.00.0020 (für Min 6-10 und 11-15). Min 16&17 werden nicht voll. *FINALE Logik*: Wenn LKN X 'pro 5 min' ist und Dauer Y genannt wird, Menge = Y. Wenn LKN Z 'weitere 5 min' ZUSCHLAG zu LKN B (erste 5 min) ist, und Dauer Y=17, dann LKN B Menge 1, LKN Z Menge = (17 - 5) = 12. ***Vereinfachung***: Wenn die LKN Beschreibung "pro X Min" enthält und eine Dauer Y genannt wird, setze Menge=Y. Die Regelprüfung im Backend korrigiert das ggf.
    - **Allgemeine Menge:** WENN eine allgemeine Menge extrahiert wurde und sich klar auf eine LKN bezieht (die NICHT pro Minute abgerechnet wird), setze die 'menge' für DIESE LKN auf den Wert aus Schritt 3.
5. Stelle sicher, dass JEDE LKN in der `identified_leistungen`-Liste eine numerische `menge` hat (mindestens 1).

Gib das Ergebnis NUR als JSON-Objekt im folgenden Format zurück. KEINEN anderen Text oder Erklärungen hinzufügen.

{{
  "identified_leistungen": [
    {{
      "lkn": "IDENTIFIZIERTE_LKN_1",
      "typ": "TYP_AUS_KATALOG_1",
      "beschreibung": "BESCHREIBUNG_AUS_KATALOG_1",
      "menge": MENGE_ZAHL_LKN_1 // Immer eine Zahl, mind. 1
    }},
    // ... weitere LKNs
  ],
  "extracted_info": {{
    "dauer_minuten": DAUER_IN_MINUTEN_ODER_NULL,
    "menge_allgemein": ALLGEMEINE_MENGE_ODER_NULL,
    "alter": ALTER_ODER_NULL,
    "geschlecht": "GESCHLECHT_STRING_ODER_NULL"
  }},
  "begruendung_llm": "<Kurze Begründung, warum diese spezifische(n) LKN(s) mit diesen Mengen gewählt wurden, 
  basierend auf dem Text und dem Katalog. Verwende 'die LKN' für nachfolgende Nennungen.>"
}}

Wenn absolut keine passende LKN aus dem Katalog gefunden wird, gib ein JSON-Objekt mit einer leeren "identified_leistungen"-Liste zurück.

Behandlungstext: "{user_input}"

JSON-Antwort:"""

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.1, # Sehr niedrig für Konsistenz
            "maxOutputTokens": 2048 # Erhöht, falls der Katalog lang ist
         }
    }
    print(f"Sende Anfrage Stufe 1 an Gemini Model: {GEMINI_MODEL}...")
    try:
        response = requests.post(gemini_url, json=payload, timeout=90) # Längeres Timeout
        print(f"Gemini Stufe 1 Antwort Status Code: {response.status_code}")
        response.raise_for_status() # Wirft HTTPError bei 4xx/5xx

        gemini_data = response.json()
        # Tiefere Prüfung der Antwortstruktur
        if not gemini_data.get('candidates'):
             # Versuche, Safety Ratings oder Blockierungsgründe zu loggen
             finish_reason = gemini_data.get('promptFeedback', {}).get('blockReason')
             safety_ratings = gemini_data.get('promptFeedback', {}).get('safetyRatings')
             error_details = f"Keine Kandidaten gefunden. Finish Reason: {finish_reason}, Safety Ratings: {safety_ratings}"
             print(f"WARNUNG: {error_details}")
             # Versuche, den Rohtext zu parsen, falls doch vorhanden
             try: raw_text_response = gemini_data['text'] # Manchmal ist es direkt da?
             except KeyError: raise ValueError(error_details)
        else:
            candidate = gemini_data['candidates'][0]
            content = candidate.get('content', {})
            parts = content.get('parts', [{}])[0]
            raw_text_response = parts.get('text', '')

        print(f"DEBUG: Roher Text von LLM Stufe 1 (gekürzt):\n---\n{raw_text_response[:500]}...\n---")

        if not raw_text_response:
             finish_reason = candidate.get('finishReason', 'UNKNOWN')
             safety_ratings = candidate.get('safetyRatings')
             if finish_reason != 'STOP': raise ValueError(f"Gemini stopped with reason: {finish_reason}, Safety: {safety_ratings}")
             else: raise ValueError("Leere Textantwort von Gemini erhalten trotz Status OK.")

        # Vorsichtiges Parsen
        try:
             llm_response_json = json.loads(raw_text_response)
        except json.JSONDecodeError as json_err:
             # Versuch, Markdown ```json ... ``` zu extrahieren
             match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_text_response, re.IGNORECASE)
             if match:
                 try:
                     llm_response_json = json.loads(match.group(1))
                     print("INFO: JSON aus Markdown extrahiert.")
                 except json.JSONDecodeError:
                     raise ValueError(f"JSONDecodeError auch nach Markdown-Extraktion: {json_err}. Rohtext: {raw_text_response[:500]}...")
             else:
                 raise ValueError(f"JSONDecodeError: {json_err}. Rohtext: {raw_text_response[:500]}...")

        print(f"DEBUG: Geparstes LLM JSON Stufe 1 VOR Validierung: {json.dumps(llm_response_json, indent=2, ensure_ascii=False)}")

        # Strikte Validierung der Struktur und Typen
        if not isinstance(llm_response_json, dict): raise ValueError("Antwort ist kein JSON-Objekt.")
        if not all(k in llm_response_json for k in ["identified_leistungen", "extracted_info", "begruendung_llm"]): raise ValueError("Hauptschlüssel fehlen (identified_leistungen, extracted_info, begruendung_llm).")
        if not isinstance(llm_response_json["identified_leistungen"], list): raise ValueError("'identified_leistungen' ist keine Liste.")
        if not isinstance(llm_response_json["extracted_info"], dict): raise ValueError("'extracted_info' ist kein Dict.")
        expected_extracted = ["dauer_minuten", "menge_allgemein", "alter", "geschlecht"]
        if not all(k in llm_response_json["extracted_info"] for k in expected_extracted): raise ValueError(f"Schlüssel in 'extracted_info' fehlen (erwartet: {expected_extracted}).")
        # Typen in extracted_info prüfen
        for key, expected_type in [("dauer_minuten", (int, type(None))), ("menge_allgemein", (int, type(None))), ("alter", (int, type(None))), ("geschlecht", (str, type(None)))]:
             if not isinstance(llm_response_json["extracted_info"].get(key), expected_type):
                  # Toleranter bei Geschlecht, falls es mal fehlt
                  if key == "geschlecht" and llm_response_json["extracted_info"].get(key) is None: continue
                  raise ValueError(f"Typfehler in 'extracted_info': '{key}' sollte {expected_type} sein, ist {type(llm_response_json['extracted_info'].get(key))}.")

        expected_leistung_keys = ["lkn", "typ", "beschreibung", "menge"]
        for i, item in enumerate(llm_response_json["identified_leistungen"]):
             if not isinstance(item, dict): raise ValueError(f"Element {i} in 'identified_leistungen' ist kein Dict.")
             if not all(k in item for k in expected_leistung_keys): raise ValueError(f"Schlüssel in Element {i} fehlen (erwartet: {expected_leistung_keys}).")
             # Menge MUSS eine Zahl sein (oder null/None, wird dann zu 1)
             menge_val = item.get("menge")
             if menge_val is None:
                 item["menge"] = 1 # Setze Default 1 wenn null/None
             elif not isinstance(menge_val, int):
                 try: item["menge"] = int(menge_val); print(f"WARNUNG: Menge in Element {i} war {type(menge_val)}, wurde zu int konvertiert.")
                 except (ValueError, TypeError): raise ValueError(f"Menge '{menge_val}' in Element {i} ist keine gültige Zahl.")
             if item["menge"] < 0: raise ValueError(f"Menge in Element {i} ist negativ.")
             # LKN muss ein String sein
             if not isinstance(item.get("lkn"), str) or not item.get("lkn"): raise ValueError(f"LKN in Element {i} ist kein gültiger String.")

        # Begründung sicherstellen
        if "begruendung_llm" not in llm_response_json or not isinstance(llm_response_json["begruendung_llm"], str):
             llm_response_json["begruendung_llm"] = "N/A"

        print("INFO: LLM Stufe 1 Antwort erfolgreich validiert.")
        return llm_response_json

    except requests.exceptions.RequestException as req_err:
        print(f"FEHLER: Netzwerkfehler bei Gemini Stufe 1: {req_err}")
        raise ConnectionError(f"Netzwerkfehler bei Gemini Stufe 1: {req_err}")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as proc_err:
        print(f"FEHLER: Fehler beim Verarbeiten der LLM Stufe 1 Antwort: {proc_err}")
        # Sende den Fehler weiter, damit das Frontend ihn anzeigen kann
        raise ValueError(f"Verarbeitungsfehler LLM Stufe 1: {proc_err}")
    except Exception as e:
        print(f"FEHLER: Unerwarteter Fehler im LLM Stufe 1: {e}")
        raise e # Unerwartete Fehler weiterleiten


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


# --- HILFSFUNKTIONEN (auf Modulebene) ---

def get_simplified_conditions(pauschale_code: str, bedingungen_data: list[dict]) -> set:
    """ Wandelt Bedingungen in eine vereinfachte, vergleichbare Darstellung um (Set von Strings). """
    simplified_set = set()
    # Schlüssel für Bedingungen - anpassen falls nötig!
    PAUSCHALE_KEY_IN_BEDINGUNGEN = 'Pauschale'
    BED_TYP_KEY = 'Bedingungstyp'
    BED_WERTE_KEY = 'Werte'
    BED_FELD_KEY = 'Feld'
    BED_MIN_KEY = 'MinWert'
    BED_MAX_KEY = 'MaxWert'

    pauschale_conditions = [cond for cond in bedingungen_data if cond.get(PAUSCHALE_KEY_IN_BEDINGUNGEN) == pauschale_code]

    for cond in pauschale_conditions:
        typ = cond.get(BED_TYP_KEY, "").upper()
        wert = cond.get(BED_WERTE_KEY, "")
        feld = cond.get(BED_FELD_KEY, "")

        condition_repr = ""
        if "IN TABELLE" in typ:
            condition_repr = f"{typ}:{wert}" # Trenner ':' statt ': ' für einfacheres Splitten
        elif "IN LISTE" in typ:
             condition_repr = f"{typ}:{wert}"
        elif typ == "PATIENTENBEDINGUNG" and feld:
             if cond.get(BED_MIN_KEY) is not None or cond.get(BED_MAX_KEY) is not None:
                 bereich_text = f"({cond.get(BED_MIN_KEY, '-')}-{cond.get(BED_MAX_KEY, '-')})"
                 condition_repr = f"{typ}:{feld} {bereich_text}"
             else:
                 condition_repr = f"{typ}:{feld}={wert}"
        elif typ:
             condition_repr = f"{typ}:{wert}"

        if condition_repr:
            simplified_set.add(condition_repr)

    return simplified_set


def get_table_content(table_ref: str, table_type: str, tabellen_dict_by_table: dict) -> list[dict]:
    """Holt Einträge für eine Tabelle und einen Typ."""
    content = []
    # Schlüssel für tblTabellen - anpassen falls nötig!
    TAB_CODE_KEY = 'Code'
    TAB_TEXT_KEY = 'Code_Text'
    TAB_TYP_KEY = 'Tabelle_Typ'

    if table_ref in tabellen_dict_by_table:
        for entry in tabellen_dict_by_table[table_ref]:
            if entry.get(TAB_TYP_KEY) == table_type:
                code = entry.get(TAB_CODE_KEY)
                text = entry.get(TAB_TEXT_KEY)
                if code:
                    content.append({"Code": code, "Code_Text": text or "N/A"})
    return sorted(content, key=lambda x: x.get('Code', ''))


def generate_condition_detail_html(cond_repr: str) -> str:
    """Generiert HTML für eine einzelne Bedingungsrepräsentation mit aufklappbaren Details."""
    global leistungskatalog_dict, tabellen_dict_by_table # Zugriff auf globale Daten

    condition_html = f"<li>{html.escape(cond_repr)}" # Standardanzeige
    nested_details_html = ""

    try:
        parts = cond_repr.split(':', 1)
        cond_type = parts[0].strip().upper()
        cond_value = parts[1].strip() if len(parts) > 1 else ""

        # --- Logik für aufklappbare Details ---
        if cond_type == "LEISTUNGSPOSITIONEN IN LISTE":
            lkns = [lkn.strip() for lkn in cond_value.split(',') if lkn.strip()]
            if lkns:
                nested_details_html += f"<details style='margin-left: 25px; font-size: 0.9em;'><summary>Zeige {len(lkns)} LKN(s)</summary><ul>"
                for lkn in lkns:
                    # Schlüssel für Leistungskatalog anpassen!
                    desc = leistungskatalog_dict.get(lkn, {}).get('Beschreibung', 'Beschreibung nicht gefunden')
                    nested_details_html += f"<li><b>{html.escape(lkn)}</b>: {html.escape(desc)}</li>"
                nested_details_html += "</ul></details>"

        elif cond_type == "LEISTUNGSPOSITIONEN IN TABELLE" or cond_type == "TARIFPOSITIONEN IN TABELLE":
            table_names = [t.strip() for t in cond_value.split(',') if t.strip()]
            all_content = []
            for table_name in table_names:
                table_content = get_table_content(table_name, "service_catalog", tabellen_dict_by_table)
                if table_content:
                    all_content.extend(table_content)
                else:
                    print(f"WARNUNG: Tabelle '{table_name}' (LKN) für Vergleich nicht gefunden oder leer.")

            if all_content:
                 unique_content = {item['Code']: item for item in all_content}.values()
                 sorted_content = sorted(unique_content, key=lambda x: x['Code'])
                 table_links = ", ".join([f"'{html.escape(t)}'" for t in table_names])
                 nested_details_html += f"<details style='margin-left: 25px; font-size: 0.9em;'><summary>Zeige {len(sorted_content)} LKN(s) aus Tabellen: {table_links}</summary><ul>"
                 for item in sorted_content:
                     nested_details_html += f"<li><b>{html.escape(item['Code'])}</b>: {html.escape(item['Code_Text'])}</li>"
                 nested_details_html += "</ul></details>"
            elif table_names:
                 nested_details_html = " (Tabellen leer oder nicht gefunden)"


        elif cond_type == "HAUPTDIAGNOSE IN TABELLE":
            table_names = [t.strip() for t in cond_value.split(',') if t.strip()]
            all_content = []
            for table_name in table_names:
                table_content = get_table_content(table_name, "icd", tabellen_dict_by_table)
                if table_content:
                    all_content.extend(table_content)
                else:
                    print(f"WARNUNG: Tabelle '{table_name}' (ICD) für Vergleich nicht gefunden oder leer.")

            if all_content:
                 unique_content = {item['Code']: item for item in all_content}.values()
                 sorted_content = sorted(unique_content, key=lambda x: x['Code'])
                 table_links = ", ".join([f"'{html.escape(t)}'" for t in table_names])
                 nested_details_html += f"<details style='margin-left: 25px; font-size: 0.9em;'><summary>Zeige {len(sorted_content)} ICD(s) aus Tabellen: {table_links}</summary><ul>"
                 for item in sorted_content:
                     nested_details_html += f"<li><b>{html.escape(item['Code'])}</b>: {html.escape(item['Code_Text'])}</li>"
                 nested_details_html += "</ul></details>"
            elif table_names:
                 nested_details_html = " (Tabellen leer oder nicht gefunden)"

        # Füge die verschachtelten Details zum Listeneintrag hinzu
        condition_html += nested_details_html

    except Exception as e_detail:
        print(f"FEHLER beim Erstellen der Detailansicht für Bedingung '{cond_repr}': {e_detail}")
        # Fallback zur einfachen Anzeige

    condition_html += "</li>"
    return condition_html


# --- Ausgelagerte Pauschalen-Ermittlung ---
def determine_applicable_pauschale(user_input: str, rule_checked_leistungen: list[dict], context: dict) -> dict:
    """
    Ermittelt die anwendbarste Pauschale, prüft Bedingungen für alle Kandidaten
    und wählt die niedrigste gültige aus.
    Gibt entweder die Pauschale oder einen Error zurück.
    """
    print("INFO: Starte überarbeitete Pauschalenermittlung mit Bedingungsprüfung vor Auswahl...")

    # Schlüssel und globale Variablen
    PAUSCHALE_ERKLAERUNG_KEY = 'pauschale_erklaerung_html'
    POTENTIAL_ICDS_KEY = 'potential_icds'
    LKN_KEY_IN_RULE_CHECKED = 'lkn'
    PAUSCHALE_KEY_IN_PAUSCHALEN = 'Pauschale'
    PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN = 'Pauschale_Text'
    global leistungskatalog_dict, tabellen_dict_by_table, pauschale_lp_data, pauschale_bedingungen_data, pauschalen_dict

    # 1. Finde potenzielle Pauschalen (wie vorher)
    potential_pauschale_codes = set()
    # ... (Logik zum Finden von potential_pauschale_codes via Methode a, b, c wie vorher) ...
    rule_checked_lkns = [l.get(LKN_KEY_IN_RULE_CHECKED) for l in rule_checked_leistungen if l.get(LKN_KEY_IN_RULE_CHECKED)]
    lkns_in_tables = {}
    for lkn in rule_checked_lkns:
        # a) Via tblPauschaleLeistungsposition
        for item in pauschale_lp_data:
            if item.get('Leistungsposition') == lkn: # Anpassen!
                pauschale_code_a = item.get('Pauschale') # Anpassen!
                if pauschale_code_a and pauschale_code_a in pauschalen_dict:
                    potential_pauschale_codes.add(pauschale_code_a)
        # b) Via Bedingungen 'IN LISTE'
        for cond in pauschale_bedingungen_data:
            if cond.get('Bedingungstyp') == "LEISTUNGSPOSITIONEN IN LISTE": # Anpassen!
                werte_liste = [w.strip() for w in str(cond.get('Werte', "")).split(',') if w.strip()] # Anpassen!
                if lkn in werte_liste:
                    pauschale_code_b = cond.get('Pauschale') # Anpassen!
                    if pauschale_code_b and pauschale_code_b in pauschalen_dict:
                        potential_pauschale_codes.add(pauschale_code_b)
        # c) Via Bedingungen 'IN TABELLE'
        if lkn not in lkns_in_tables:
             tables_for_lkn = set()
             for table_name, entries in tabellen_dict_by_table.items():
                  if table_name in ["nonELT", "nonOR"]: continue
                  for entry in entries:
                       if entry.get('Code') == lkn and entry.get('Tabelle_Typ') == "service_catalog": # Anpassen!
                            tables_for_lkn.add(table_name)
             lkns_in_tables[lkn] = tables_for_lkn
        tables_for_current_lkn = lkns_in_tables.get(lkn, set())
        if tables_for_current_lkn:
            for cond in pauschale_bedingungen_data:
                if cond.get('Bedingungstyp') == "LEISTUNGSPOSITIONEN IN TABELLE": # Anpassen!
                    table_ref_in_cond = cond.get('Werte') # Anpassen!
                    if table_ref_in_cond in tables_for_current_lkn:
                        pauschale_code_c = cond.get('Pauschale') # Anpassen!
                        if pauschale_code_c and pauschale_code_c in pauschalen_dict:
                            potential_pauschale_codes.add(pauschale_code_c)

    if not potential_pauschale_codes:
        print("INFO: Keine potenziellen Pauschalen-Codes für die erbrachten Leistungen gefunden.")
        return {"type": "Error", "message": "Keine passende Pauschale für die erbrachten Leistungen gefunden."}

    print(f"INFO: Potenzielle Pauschalen-Codes: {potential_pauschale_codes}")

    # 2. Prüfe Bedingungen für ALLE potenziellen Kandidaten
    candidate_results = []
    print(f"INFO: Prüfe Bedingungen für {len(potential_pauschale_codes)} potenzielle Pauschalen...")
    for code in potential_pauschale_codes:
        if code not in pauschalen_dict: continue # Überspringe, falls nicht in Pauschalen-Liste

        bedingungs_context = {
             "ICD": context.get("ICD", []), "GTIN": context.get("GTIN", []),
             "LKN": rule_checked_lkns, # Alle regelkonformen LKNs übergeben
             "Alter": context.get("Alter"), "Geschlecht": context.get("Geschlecht")
        }
        # --- DEBUG LOGGING ---
        print(f"\n--- DEBUG: Prüfe Bedingungen für Pauschale: {code} ---")
        print(f"DEBUG: Kontext für Prüfung: {bedingungs_context}")
        # --- END DEBUG ---

        condition_result = {"allMet": False, "html": "Prüfung fehlgeschlagen", "errors": ["Prüfung fehlgeschlagen"]} # Default

        # Rufe die Bedingungsprüfung auf oder setze Fallback
        if regelpruefer_pauschale and hasattr(regelpruefer_pauschale, 'check_pauschale_conditions'):
            try:
                condition_result = regelpruefer_pauschale.check_pauschale_conditions(
                    code,
                    bedingungs_context,
                    pauschale_bedingungen_data,
                    tabellen_dict_by_table
                )
                # --- DEBUG LOGGING ---
                print(f"DEBUG: Ergebnis von check_pauschale_conditions für {code}: allMet={condition_result.get('allMet')}, Errors={condition_result.get('errors')}")
                # --- END DEBUG ---
            except Exception as e_cond_check:
                 print(f"FEHLER bei check_pauschale_conditions für {code}: {e_cond_check}")
                 condition_result["html"] = f"<p class='error'>Fehler bei Bedingungsprüfung für {code}: {e_cond_check}</p>"
                 condition_result["errors"] = [f"Fehler bei Bedingungsprüfung: {e_cond_check}"]
                 condition_result["allMet"] = False # Bei Fehler gilt es als nicht erfüllt
        else:
            print(f"WARNUNG: Bedingungsprüfung für {code} übersprungen (Modul fehlt).")
            condition_result = {"allMet": False, "html": "Bedingungsprüfung nicht verfügbar", "errors": ["Bedingungsprüfung nicht verfügbar"]}

        # Füge das Ergebnis für diesen Kandidaten zur Liste hinzu
        # Dieser Block ist INNERHALB der for-Schleife
        candidate_results.append({
            "code": code,
            "details": pauschalen_dict[code], # Hole Details aus dem globalen Dict
            "conditions_met": condition_result.get("allMet", False),
            "trigger_lkn_condition_met": condition_result.get("trigger_lkn_condition_met", False),
            "bedingungs_pruef_html": condition_result.get("html", ""),
            "bedingungs_fehler": condition_result.get("errors", [])
        })
    # print(f"DEBUG: Bedingungsprüfung für {code}: Erfüllt = {condition_result.get('allMet')}")

    # 3. Filtere gültige Kandidaten (Bedingungen erfüllt)
    lkn_triggered_candidates = [cand for cand in candidate_results if cand["trigger_lkn_condition_met"]]
    print(f"DEBUG: Kandidaten, deren LKN-Bedingung erfüllt ist: {[c['code'] for c in lkn_triggered_candidates]}")

    # 4. Wähle die beste Pauschale aus den LKN-GETRIGGERTEN Kandidaten
    selected_candidate = None
    if lkn_triggered_candidates:
        # --- KORREKTUR: Sortiere AUFSTEIGEND (A vor B vor D) ---
        lkn_triggered_candidates.sort(key=lambda x: x['code'], reverse=False) # reverse=False (oder weglassen)
        selected_candidate = lkn_triggered_candidates[0] # Nimm die erste (spezifischste)
        print(f"INFO: Spezifischste Pauschale ausgewählt, deren LKN-Bedingung erfüllt ist: {selected_candidate['code']}")
        # --- ENDE KORREKTUR ---
    else:
        # Fallback: Keine Pauschale wurde durch die LKNs getriggert
        print("INFO: Keine Pauschale gefunden, deren LKN-Bedingung erfüllt ist.")
        return {"type": "Error", "message": "Keine Pauschale gefunden, deren LKN-Bedingung erfüllt ist."}

    # --- Ab hier verwenden wir selected_candidate ---
    best_ranked_code = selected_candidate["code"]
    best_pauschale_details = selected_candidate["details"].copy()
    bedingungs_pruef_html_result = selected_candidate["bedingungs_pruef_html"]
    condition_errors = selected_candidate["bedingungs_fehler"]
    conditions_met = selected_candidate["conditions_met"]
    print(f"INFO: Ausgewählte Pauschale {best_ranked_code} - Alle Bedingungen erfüllt: {conditions_met}")

    # 5. Pauschalen-Begründung erstellen (jetzt basierend auf der Auswahl)
    rule_checked_lkns_str_list = [str(lkn) for lkn in rule_checked_lkns if lkn]
    pauschale_erklaerung_html = "<p>Folgende Pauschalen wurden basierend auf den regelkonformen Leistungen ({}) in Betracht gezogen:</p><ul>".format(", ".join(rule_checked_lkns_str_list) or "keine")
    for cand in sorted(candidate_results, key=lambda x: x['code']): # Sortiert A->E für die Anzeige
         lkn_status_color = "green" if cand["trigger_lkn_condition_met"] else "grey"
         lkn_status_text = "Ja" if cand["trigger_lkn_condition_met"] else "Nein"
         all_status_color = "green" if cand["conditions_met"] else "red"
         all_status_text = "Alle erfüllt" if cand["conditions_met"] else "Nicht alle erfüllt"
         pauschale_text = cand["details"].get(PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, 'N/A')
         pauschale_erklaerung_html += f"<li><b>{cand['code']}</b>: {pauschale_text} (LKN-Bedingung: <span style='color:{lkn_status_color};'>{lkn_status_text}</span>, Gesamt: <span style='color:{all_status_color};'>{all_status_text}</span>)</li>"
    pauschale_erklaerung_html += "</ul>"
    
    # --- Vergleich mit anderen Pauschalen im Kapitel (nur mit denen, die *nicht* ausgewählt wurden) ---
    match = re.match(r"([A-Z0-9.]+)[A-Z]$", best_ranked_code)
    pauschalen_gruppe = match.group(1) if match else None

    if pauschalen_gruppe:
        # Vergleiche nur mit den *anderen* ursprünglichen Kandidaten derselben Gruppe
        other_candidates_in_group = [
            cand for cand in candidate_results
            if cand['code'].startswith(pauschalen_gruppe) and cand['code'] != best_ranked_code
        ]

        if other_candidates_in_group:
            pauschale_erklaerung_html += "<hr><p><b>Vergleich mit anderen geprüften Pauschalen der Gruppe '{}':</b></p>".format(pauschalen_gruppe)
            selected_conditions_repr = get_simplified_conditions(best_ranked_code, pauschale_bedingungen_data)

            for other_cand in sorted(other_candidates_in_group, key=lambda x: x['code']): # Sortiert A->E
                other_code = other_cand['code']
                other_text = other_cand['details'].get(PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, 'N/A')
                other_conditions_met = other_cand['conditions_met']

                pauschale_erklaerung_html += f"<details style='margin-left: 15px; font-size: 0.9em;'><summary><b>{other_code}</b> ({other_text}) - Bedingungen: <span style='color:{'red' if not other_conditions_met else 'grey'};'>{'Nicht erfüllt' if not other_conditions_met else 'Erfüllt (aber höherrangig)'}</span></summary>"

                # Zeige Unterschiede nur, wenn sinnvoll (z.B. wenn andere nicht erfüllt war oder höherrangig)
                other_conditions_repr = get_simplified_conditions(other_code, pauschale_bedingungen_data)
                additional_conditions = other_conditions_repr - selected_conditions_repr # Was hat die andere mehr/anders?
                missing_conditions = selected_conditions_repr - other_conditions_repr # Was hat die ausgewählte mehr/anders?

                if additional_conditions:
                    pauschale_erklaerung_html += "<p>Zusätzliche/Andere Anforderungen für {}:</p><ul>".format(other_code)
                    for cond_repr in sorted(list(additional_conditions)):
                        condition_html = generate_condition_detail_html(cond_repr)
                        pauschale_erklaerung_html += condition_html
                    pauschale_erklaerung_html += "</ul>"

                if missing_conditions:
                     pauschale_erklaerung_html += "<p>Folgende Anforderungen von {} fehlen bei {}:</p><ul>".format(best_ranked_code, other_code)
                     for cond_repr in sorted(list(missing_conditions)):
                         condition_html = generate_condition_detail_html(cond_repr)
                         pauschale_erklaerung_html += condition_html
                     pauschale_erklaerung_html += "</ul>"

                if not additional_conditions and not missing_conditions:
                     pauschale_erklaerung_html += "<p><i>Keine unterschiedlichen Bedingungen gefunden (basierend auf vereinfachter Prüfung).</i></p>"

                # Zeige ggf. die nicht erfüllten Bedingungen der anderen Pauschale
                if not other_conditions_met and other_cand['bedingungs_fehler']:
                     pauschale_erklaerung_html += "<p style='color:red;'>Nicht erfüllte Bedingungen für {}:</p><ul>".format(other_code)
                     for fehler in other_cand['bedingungs_fehler']:
                          pauschale_erklaerung_html += f"<li style='color:red;'>{html.escape(fehler)}</li>"
                     pauschale_erklaerung_html += "</ul>"

                pauschale_erklaerung_html += "</details>" # Schließe Details für other_cand

    best_pauschale_details[PAUSCHALE_ERKLAERUNG_KEY] = pauschale_erklaerung_html
    # --- ENDE Vergleich ---

    # 6. Potenzielle ICDs ermitteln (für die ausgewählte Pauschale)
    potential_icds = []
    # ... (Logik zur ICD-Ermittlung wie vorher) ...
    pauschale_conditions_selected = [cond for cond in pauschale_bedingungen_data if cond.get('Pauschale') == best_ranked_code] # Anpassen!
    for cond in pauschale_conditions_selected:
        if cond.get('Bedingungstyp') == "HAUPTDIAGNOSE IN TABELLE": # Anpassen!
            tabelle_ref = cond.get('Werte') # Anpassen!
            if tabelle_ref and tabelle_ref in tabellen_dict_by_table:
                icd_entries = [ entry for entry in tabellen_dict_by_table[tabelle_ref] if entry.get('Tabelle_Typ') == "icd" ] # Anpassen!
                for entry in icd_entries:
                    code = entry.get('Code'); text = entry.get('Code_Text') # Anpassen!
                    if code: potential_icds.append({"Code": code, "Code_Text": text or "N/A"})
            elif tabelle_ref: print(f"WARNUNG: Tabelle '{tabelle_ref}' für ICD-Bedingung nicht in gruppierten Tabellendaten gefunden.")
    unique_icds_dict = {icd['Code']: icd for icd in potential_icds if icd.get('Code')}
    sorted_unique_icds = sorted(unique_icds_dict.values(), key=lambda x: x['Code'])
    best_pauschale_details[POTENTIAL_ICDS_KEY] = sorted_unique_icds


    # 7. Finale Pauschalen-Antwort erstellen
    final_result = {
        "type": "Pauschale",
        "details": best_pauschale_details, # Enthält jetzt Erklärung und ICDs
        "bedingungs_pruef_html": bedingungs_pruef_html_result, # HTML der Prüfung für die *ausgewählte*
        "bedingungs_fehler": condition_errors, # Fehler der *ausgewählten*
        "conditions_met": conditions_met # Status der *ausgewählten* (sollte True sein)
    }
    return final_result

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
    # ... (analyze_billing Funktion bleibt unverändert wie im letzten Schritt) ...
    print("\n--- Request an /api/analyze-billing erhalten ---")
    start_time = time.time() # Zeitmessung starten

    # 1. Eingaben holen
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json(); user_input = data.get('inputText'); icd_input = data.get('icd', []); gtin_input = data.get('gtin', [])
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
    pauschale_context = { # Kontext für Pauschalen-Prüfung vorbereiten
        "ICD": icd_input, "GTIN": gtin_input,
        "Alter": alter_llm, "Geschlecht": geschlecht_llm
    }

    if not rule_checked_leistungen:
         print("WARNUNG: Keine regelkonformen Leistungen nach Regelprüfung übrig.")
         # Direkt zur TARDOC-Prüfung (die dann wahrscheinlich auch leer sein wird)
         final_result = prepare_tardoc_abrechnung(regel_ergebnisse_liste)
    else:
        try:
            print(f"INFO: Versuche, Pauschale für {len(rule_checked_leistungen)} regelkonforme Leistung(en) zu finden...")
            # Rufe IMMER determine_applicable_pauschale auf
            pauschale_pruef_ergebnis = determine_applicable_pauschale(
                user_input, rule_checked_leistungen, pauschale_context
            )

            # Prüfe das Ergebnis der Pauschalenprüfung
            if pauschale_pruef_ergebnis.get("type") == "Pauschale":
                print("INFO: Anwendbare Pauschale gefunden.")
                final_result = pauschale_pruef_ergebnis
            else:
                # Keine Pauschale gefunden oder anwendbar -> TARDOC
                print(f"INFO: Keine anwendbare Pauschale gefunden ({pauschale_pruef_ergebnis.get('message')}). Bereite TARDOC vor.")
                final_result = prepare_tardoc_abrechnung(regel_ergebnisse_liste)

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