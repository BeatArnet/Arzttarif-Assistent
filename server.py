# server.py - Berechnet initiale Mengen vor Regelprüfung

import os
import re
import json
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, request, abort
import requests
from dotenv import load_dotenv

try:
    import regelpruefer
    print("✓ Regelprüfer Modul geladen.")
except ImportError:
    print("FEHLER: regelpruefer.py nicht gefunden.")
    def lade_regelwerk(datei_pfad): return {}
    def pruefe_abrechnungsfaehigkeit(fall, werk): return {"abrechnungsfaehig": False, "fehler": ["Regelprüfer nicht geladen."]}
    regelpruefer = None

# --- Konfiguration ---
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', "gemini-1.5-pro-latest")
DATA_DIR = Path("data")
LEISTUNGSKATALOG_PATH = DATA_DIR / "tblLeistungskatalog.json"
REGELWERK_PATH = DATA_DIR / "strukturierte_regeln_komplett.json"
TARDOC_PATH = DATA_DIR / "TARDOCGesamt_optimiert_Tarifpositionen.json" # Für Zeit_LieS Lookup

# --- Initialisierung ---
app = Flask(__name__, static_folder='.', static_url_path='')
leistungskatalog_data: list[dict] = []
regelwerk_dict: dict[str, dict] = {}
tardoc_data_dict: dict[str, dict] = {} # TARDOC-Daten als Dict für schnellen Lookup

# --- Daten laden ---
def load_data():
    global leistungskatalog_data, regelwerk_dict, tardoc_data_dict
    # Lade Leistungskatalog
    try:
        if LEISTUNGSKATALOG_PATH.is_file():
            with open(LEISTUNGSKATALOG_PATH, 'r', encoding='utf-8') as f:
                leistungskatalog_data = json.load(f)
            print(f"✓ Leistungskatalog '{LEISTUNGSKATALOG_PATH}' geladen ({len(leistungskatalog_data)} Einträge).")
        else: print(f"FEHLER: Leistungskatalog nicht gefunden: {LEISTUNGSKATALOG_PATH}"); leistungskatalog_data = []
    except Exception as e: print(f"FEHLER beim Laden des Leistungskatalogs: {e}"); leistungskatalog_data = []

    # Lade Regelwerk
    if regelpruefer and REGELWERK_PATH.is_file():
         regelwerk_dict = regelpruefer.lade_regelwerk(str(REGELWERK_PATH))
         print(f"✓ Regelwerk '{REGELWERK_PATH}' geladen ({len(regelwerk_dict)} LKNs).")
    elif regelpruefer: print(f"FEHLER: Regelwerk nicht gefunden: {REGELWERK_PATH}"); regelwerk_dict = {}
    else: print("ℹ️ Regelprüfung deaktiviert."); regelwerk_dict = {}

    # Lade TARDOC-Daten und erstelle Dict für Lookup
    try:
        if TARDOC_PATH.is_file():
             with open(TARDOC_PATH, 'r', encoding='utf-8') as f:
                  tardoc_list = json.load(f)
             # --- !!! ANPASSEN: Korrekten Schlüssel für LKN verwenden !!! ---
             TARDOC_LKN_KEY = 'LKN' # Oder 'Tarifposition', etc.
             # --- !!! ENDE ANPASSUNG !!! ---
             for item in tardoc_list:
                  if item and TARDOC_LKN_KEY in item:
                       tardoc_data_dict[item[TARDOC_LKN_KEY]] = item
             print(f"✓ TARDOC-Daten '{TARDOC_PATH}' geladen ({len(tardoc_data_dict)} Einträge im Dict).")
        else:
             print(f"FEHLER: TARDOC-Datei nicht gefunden: {TARDOC_PATH}")
             tardoc_data_dict = {}
    except Exception as e:
        print(f"FEHLER beim Laden der TARDOC-Daten: {e}")
        tardoc_data_dict = {}


# --- LLM-Aufruf (unverändert zur Version, die Liste liefert) ---
def call_gemini_for_lkn_list(user_input: str, katalog_context: str) -> dict:
    # ... (Code von call_gemini_for_lkn_list wie in der vorletzten Antwort) ...
    # Stellt sicher, dass der Prompt nach der LISTE von Leistungen fragt
    # und die JSON-Struktur mit identified_leistungen (Liste) und extracted_info zurückgibt.
    if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY nicht konfiguriert.")
    # Prompt für strukturierte JSON-Antwort mit MENGE PRO LKN
    prompt = f"""Analysiere den folgenden medizinischen Behandlungstext aus der Schweiz SEHR GENAU.
Deine Aufgabe ist es, ALLE relevanten LKN-Codes zu identifizieren, deren korrekte Menge zu bestimmen und zusätzliche Informationen zu extrahieren.
NUTZE DIE FOLGENDE LISTE ALS DEINE PRIMÄRE REFERENZ für verfügbare LKNs, ihre Typen und Bedeutungen:
--- Leistungskatalog Start ---
{katalog_context}
--- Leistungskatalog Ende ---

Führe folgende Schritte durch:
1. Identifiziere ALLE relevanten LKN-Codes (Format: XX.##.####) aus der obigen Liste, die die beschriebene(n) Tätigkeit(en) am besten repräsentieren. Achte auf "Hausarzt"/"hausärztlich" für CA.-Codes. Wenn eine Dauer genannt wird, die Basis- und Zuschlagsleistung erfordert, gib BEIDE LKNs an. Gib niemals 'unknown' oder null als LKN zurück.
2. Gib für jede identifizierte LKN den zugehörigen Typ und die Beschreibung aus dem Katalog an.
3. Extrahiere explizit genannte Zeitdauern (nur Zahl in Minuten), allgemeine Mengenangaben (nur Zahl), Alter (nur Zahl) und Geschlecht ('weiblich', 'männlich', 'divers', 'unbekannt') aus dem "Behandlungstext". Gib null an, wenn nichts gefunden wird.
4. **Bestimme die abzurechnende Menge für JEDE identifizierte LKN und schreibe sie in das 'menge'-Feld des jeweiligen Objekts in der 'identified_leistungen'-Liste:**
    - Standardmenge ist 1.
    - **WENN** die Beschreibung einer LKN im Katalog "pro 1 Min." o.ä. enthält **UND** eine Dauer für diese Tätigkeit im Text genannt wird (extrahiert in Schritt 3), **DANN** setze die 'menge' für diese LKN auf die extrahierte Dauer (z.B. 5 für 5 Minuten).
    - **WENN** es sich um eine Zuschlagsleistung für Konsultationen handelt (z.B. CA.00.0020) **UND** eine Gesamtdauer für die Konsultation extrahiert wurde, **DANN** berechne die Menge als (Gesamtdauer - Basisdauer [normalerweise 5]) und setze die 'menge' für die Zuschlags-LKN entsprechend (z.B. 10 für 15 Minuten Konsultation). Die Basis-LKN (z.B. CA.00.0010) hat immer die Menge 1.
    - **WENN** eine allgemeine Menge extrahiert wurde und sich eindeutig auf eine LKN bezieht (die NICHT pro Minute abgerechnet wird), setze die 'menge' für DIESE LKN auf diesen Wert.
5. Kapitel: Wenn Du bereits bestimmte Leistungen in einem Kapitel (z.B. Konsultation) gefunden hast, dann schau zuerst nach, ob etwaige weitere Leistungen ebenfalls aus diesem Kapitel genommen werden können.

Gib das Ergebnis NUR als JSON-Objekt im folgenden Format zurück. KEINEN anderen Text oder Erklärungen hinzufügen.

{{
  "identified_leistungen": [
    {{
      "lkn": "IDENTIFIZIERTE_LKN_1",
      "typ": "TYP_AUS_KATALOG_1",
      "beschreibung": "BESCHREIBUNG_AUS_KATALOG_1",
      "menge": MENGE_FUER_LKN_1 // <<-- MENGE HIER ERWARTET!
    }},
    {{
      "lkn": "IDENTIFIZIERTE_LKN_2",
      "typ": "TYP_AUS_KATALOG_2",
      "beschreibung": "BESCHREIBUNG_AUS_KATALOG_2",
      "menge": MENGE_FUER_LKN_2 // <<-- MENGE HIER ERWARTET!
    }}
    // ... weitere LKNs falls gefunden ...
  ],
  "extracted_info": {{
    "dauer_minuten": DAUER_IN_MINUTEN_ODER_NULL,
    "menge_allgemein": ALLGEMEINE_MENGE_ODER_NULL, // Umbenannt
    "alter": ALTER_ODER_NULL,
    "geschlecht": "GESCHLECHT_STRING_ODER_NULL"
  }},
  "begruendung_llm": "<Ganz kurze Begründung, warum diese spezifischen LKN(s) mit diesen Mengen gewählt wurden>"
}}

Wenn absolut keine passende LKN aus dem Katalog gefunden wird, gib ein JSON-Objekt mit einer leeren "identified_leistungen"-Liste zurück.

Behandlungstext: "{user_input}"

JSON-Antwort:"""
    # ... (Rest der Funktion: API-Call, JSON-Parsing, Validierung) ...
    # Beispielhafte Rückgabe (ersetze durch echten API-Call)
    # return {"identified_leistungen": [{'lkn': 'CA.00.0010', 'typ': 'E', 'beschreibung': 'Hausärztliche Konsultation, erste 5 Min.'}, {'lkn': 'CA.00.0020', 'typ': 'EZ', 'beschreibung': '+ Hausärztliche Konsultation, jede weitere 1 Min.'}], "extracted_info": {'dauer_minuten': 15, 'menge': None, 'alter': None, 'geschlecht': 'null'}, "begruendung_llm": "Test"}
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = { "contents": [{"parts": [{"text": prompt}]}], "generationConfig": { "response_mime_type": "application/json", "temperature": 0.2, "maxOutputTokens": 1024 } }
    print(f"Sende Anfrage an Gemini Model: {GEMINI_MODEL}...")
    response = requests.post(gemini_url, json=payload, timeout=60)
    print(f"Gemini Antwort Status Code: {response.status_code}")
    if not response.ok: raise ConnectionError(f"Gemini API Error {response.status_code}: {response.text}")
    gemini_data = response.json()
    try:
        raw_text_response = gemini_data['candidates'][0]['content']['parts'][0]['text']
        llm_response_json = json.loads(raw_text_response)
        print(f"DEBUG: Geparses LLM JSON VOR Validierung: {json.dumps(llm_response_json, indent=2)}")
        print(f"LLM Antwort JSON: {llm_response_json}") # Dieser Log bleibt
        # --- Korrigierte Validierung ---
        # 1. Prüfe Hauptschlüssel
        if not all(k in llm_response_json for k in ["identified_leistungen", "extracted_info", "begruendung_llm"]):
            raise ValueError("Hauptschlüssel 'identified_leistungen', 'extracted_info' oder 'begruendung_llm' fehlt.")

        # 2. Prüfe Typen der Hauptschlüssel
        if not isinstance(llm_response_json["identified_leistungen"], list):
            raise ValueError("'identified_leistungen' ist keine Liste.")
        if not isinstance(llm_response_json["extracted_info"], dict):
            raise ValueError("'extracted_info' ist kein Dictionary.")

        # 3. Prüfe Unterschlüssel in extracted_info (mit korrektem Namen 'menge_allgemein')
        #    Erlaube, dass Werte None/null sind
        expected_extracted_keys = ["dauer_minuten", "menge_allgemein", "alter", "geschlecht"]
        if not all(k in llm_response_json["extracted_info"] for k in expected_extracted_keys):
            missing_keys = [k for k in expected_extracted_keys if k not in llm_response_json["extracted_info"]]
            raise ValueError(f"Folgende Schlüssel fehlen in 'extracted_info': {', '.join(missing_keys)}")

        # 4. Prüfe Struktur und Typen in identified_leistungen (inkl. 'menge')
        expected_leistung_keys = ["lkn", "typ", "beschreibung", "menge"]
        for index, item in enumerate(llm_response_json["identified_leistungen"]):
             if not isinstance(item, dict):
                  raise ValueError(f"Element {index} in 'identified_leistungen' ist kein Dictionary: {item}")
             if not all(k in item for k in expected_leistung_keys):
                  missing_keys = [k for k in expected_leistung_keys if k not in item]
                  raise ValueError(f"Element {index} in 'identified_leistungen' fehlen Schlüssel: {', '.join(missing_keys)} - Element: {item}")
             # Prüfe, ob Menge eine Zahl ist (oder null, falls LLM das liefert)
             if item["menge"] is not None and not isinstance(item["menge"], int):
                  raise ValueError(f"Menge muss eine Zahl (oder null) sein in Element {index} von 'identified_leistungen': {item}")
             # Optional: Prüfe, ob Menge nicht negativ ist (erlaube 0)
             if isinstance(item["menge"], int) and item["menge"] < 0:
                  raise ValueError(f"Menge darf nicht negativ sein in Element {index} von 'identified_leistungen': {item}")
        # --- Ende Korrigierte Validierung ---

        if "begruendung_llm" not in llm_response_json: llm_response_json["begruendung_llm"] = "N/A"
        return llm_response_json

    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as e:
        raw_text_for_error = ""
        try: raw_text_for_error = gemini_data['candidates'][0]['content']['parts'][0]['text']
        except: pass
        print(f"FEHLER beim Verarbeiten der LLM-Antwort: {e}")
        print(f"Roher Text der Antwort (falls verfügbar): '{raw_text_for_error}'")
        raise ValueError(f"Fehler beim Verarbeiten der LLM-Antwort: {e}")
    except Exception as e: print(f"Unerwarteter FEHLER im LLM-Teil: {e}"); raise e


# --- API Endpunkt ---
@app.route('/api/analyze-billing', methods=['POST'])
def analyze_billing():
    print("\n--- Request an /api/analyze-billing erhalten ---")
    # 1. Eingaben holen
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()
    user_input = data.get('inputText')
    icd_input = data.get('icd', [])
    if not user_input: return jsonify({"error": "'inputText' is required"}), 400
    print(f"Empfangener inputText: {user_input}")
    print(f"Empfangene ICDs: {icd_input}")

    # 2. LLM aufrufen
    llm_response_json = None
    try:
        if not leistungskatalog_data: raise ValueError("Leistungskatalog nicht geladen")
        katalog_context = "\n".join([f"LKN: {item.get('LKN', 'N/A')}, Typ: {item.get('Typ', 'N/A')}, Beschreibung: {item.get('Beschreibung', 'N/A')}" for item in leistungskatalog_data])
        # Kontext nicht mehr kürzen für 1.5 Pro
        llm_response_json = call_gemini_for_lkn_list(user_input, katalog_context)
    except (ValueError, ConnectionError) as e: return jsonify({"error": f"LLM-Fehler: {e}"}), 500
    except Exception as e: import traceback; print(f"Unerwarteter FEHLER: {e}\n{traceback.format_exc()}"); return jsonify({"error": "Serverfehler beim LLM-Aufruf"}), 500

    # 3. Initiale Mengenberechnung & Regelprüfung vorbereiten
    regel_ergebnisse_liste = []  # Behält die Ergebnisse für JEDE LKN
    extracted_info = llm_response_json.get("extracted_info", {})
    alter_llm = extracted_info.get("alter")
    geschlecht_llm = extracted_info.get("geschlecht")
    identified_leistungen_llm = llm_response_json.get("identified_leistungen", [])
    rule_checked_leistungen = [] # Liste der LKNs, die Regeln bestehen (als Dict mit finaler Menge)

    if not identified_leistungen_llm: # Wenn nach Filterung nichts übrig bleibt
         regel_ergebnisse_liste.append({
             "lkn": None,
             "regelpruefung": {"abrechnungsfaehig": False, "fehler": ["Keine gültige LKN vom LLM identifiziert."]},
             "finale_menge": 0 # Geändert von 1 zu 0
         })
    else:
        # --- Regelprüfung für jede LKN mit Menge vom LLM ---
        for leistung in identified_leistungen_llm:
            lkn = leistung.get("lkn")
            if not lkn or lkn.lower() == "unknown":
                 # Füge Fehler für ungültige LKN hinzu
                 regel_ergebnisse_liste.append({
                     "lkn": lkn or "unknown",
                     "regelpruefung": {"abrechnungsfaehig": False, "fehler": ["Ungültige LKN vom LLM."]},
                     "finale_menge": 0
                 })
                 continue

            menge_initial = leistung.get("menge", 1)
            try: menge_initial = int(menge_initial); assert menge_initial >= 0
            except: menge_initial = 1

            regel_ergebnis = {"abrechnungsfaehig": False, "fehler": ["Regelprüfung nicht durchgeführt."]}
            
            if not regelpruefer or not regelwerk_dict:
                regel_ergebnis = {"abrechnungsfaehig": True, "fehler": ["Regelprüfung nicht verfügbar."]}
            else:
                # *** DEFINITION VON ABRECHNUNGSFALL HIER EINFÜGEN ***
                abrechnungsfall = {
                    "LKN": lkn,
                    "Menge": menge_initial, # Verwende initiale Menge vom LLM
                    "Begleit_LKNs": [item.get("lkn") for item in identified_leistungen_llm if item.get("lkn") and item.get("lkn") != lkn],
                    "ICD": icd_input,
                    "Geschlecht": geschlecht_llm,
                    "Alter": alter_llm,
                    "Pauschalen": [] # Ggf. anpassen, falls Pauschalen übergeben werden
                }
                # *** ENDE DEFINITION ***
                print(f"Starte Regelprüfung für Fall: {abrechnungsfall}")
                regel_ergebnis = regelpruefer.pruefe_abrechnungsfaehigkeit(abrechnungsfall, regelwerk_dict)
                print(f"Ergebnis Regelprüfung für {lkn}: {regel_ergebnis}")

            # *** Mengenanpassungslogik HIER implementieren ***
            angepasste_menge = menge_initial
            if not regel_ergebnis.get("abrechnungsfaehig", False):
                # *** Mengenanpassungslogik HIER ***
                fehler_liste = regel_ergebnis.get("fehler", [])
                fehler_ohne_menge = [f for f in fehler_liste if "Mengenbeschränkung überschritten" not in f]
                mengen_fehler = [f for f in fehler_liste if "Mengenbeschränkung überschritten" in f]
                if not fehler_ohne_menge and mengen_fehler:
                    max_menge_match = None
                    match = re.search(r'max\. (\d+)', mengen_fehler[0])
                    if match: max_menge_match = int(match.group(1))
                    if max_menge_match is not None and menge_initial > max_menge_match:
                        angepasste_menge = max_menge_match
                        print(f"Menge angepasst von {menge_initial} auf {angepasste_menge} für {lkn}.")
                        regel_ergebnis["fehler"] = [f"Menge auf {angepasste_menge} reduziert (ursprünglich: {menge_initial})"]
                        regel_ergebnis["abrechnungsfaehig"] = True
                    else:
                        angepasste_menge = 0
                        print(f"Mengenfehler für {lkn}, aber Anpassung nicht möglich/nötig.")
                else:
                    angepasste_menge = 0
                    print(f"LKN {lkn} nicht abrechnungsfähig wegen anderer Regeln.")
                # *** ENDE Mengenanpassungslogik ***

            regel_ergebnisse_liste.append({
                "lkn": lkn,
                "regelpruefung": regel_ergebnis,
                "finale_menge": angepasste_menge
            })
            # Füge zur Liste der regelkonformen hinzu, WENN abrechnungsfähig (NACH Anpassung)
            if regel_ergebnis.get("abrechnungsfaehig"):
                # Füge das *ursprüngliche* Leistungsobjekt hinzu, aber mit der finalen Menge
                rule_checked_leistungen.append({**leistung, "menge": angepasste_menge})

        # --- Kombiniertes Ergebnis an Frontend senden ---
        final_response = {
            "llm_ergebnis": llm_response_json, # Enthält jetzt Menge pro LKN
            "regel_ergebnisse": regel_ergebnisse_liste,
            "finale_mengen": regel_ergebnisse_liste, # Enthält finale Mengen für alle LKN
    }
    return jsonify(final_response)

# --- Static‑Routes & Start ---
@app.route("/")
def index(): return send_from_directory(".", "index.html")
@app.route("/<path:filename>")
def serve_static(filename):
    if filename in {'server.py', '.env', 'regelpruefer.py'} or filename.startswith('.'): abort(404)
    if filename.startswith('data/') or filename == 'calculator.js': return send_from_directory('.', filename)
    abort(404)

if __name__ == "__main__":
    load_data()
    print(f"🚀 Server läuft → http://127.0.0.1:8000 (Regelprüfer: {'Aktiv' if regelpruefer else 'Inaktiv'})")
    app.run(host="127.0.0.1", port=8000, debug=True)