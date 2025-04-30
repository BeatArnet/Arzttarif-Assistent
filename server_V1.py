# server.py - Zweistufiger LLM-Ansatz mit Backend-Regelprüfung

import os
import re
import json
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, request, abort
import requests
from dotenv import load_dotenv

# Importiere Regelprüfer und Pauschalen-Bedingungsprüfer
try:
    import regelpruefer
    # Annahme: regelpruefer.py enthält jetzt auch check_pauschale_conditions
    if not hasattr(regelpruefer, 'check_pauschale_conditions'):
        print("WARNUNG: Funktion 'check_pauschale_conditions' nicht in regelpruefer.py gefunden. Bedingungsprüfung übersprungen.")
        # Dummy-Funktion
        def check_pauschale_conditions(pauschale_code, context, pauschale_bedingungen_data, tabellen_data):
            print(f"WARNUNG: Bedingungsprüfung für {pauschale_code} übersprungen.")
            return {"allMet": True, "html": "Bedingungsprüfung nicht implementiert", "errors": []} # Annahme: Immer OK
        regelpruefer.check_pauschale_conditions = check_pauschale_conditions

    print("✓ Regelprüfer Modul geladen.")
except ImportError:
    print("FEHLER: regelpruefer.py nicht gefunden.")
    # Dummy-Funktionen
    def lade_regelwerk(datei_pfad): return {}
    def pruefe_abrechnungsfaehigkeit(fall, werk): return {"abrechnungsfaehig": False, "fehler": ["Regelprüfer nicht geladen."]}
    def check_pauschale_conditions(pauschale_code, context, pauschale_bedingungen_data, tabellen_data): return {"allMet": False, "html": "Regelprüfer nicht geladen", "errors": ["Regelprüfer nicht geladen"]}
    regelpruefer = None # type: ignore

# --- Konfiguration ---
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', "gemini-1.5-pro-latest")
DATA_DIR = Path("data")
LEISTUNGSKATALOG_PATH = DATA_DIR / "tblLeistungskatalog.json"
REGELWERK_PATH = DATA_DIR / "strukturierte_regeln_komplett.json"
TARDOC_PATH = DATA_DIR / "TARDOCGesamt_optimiert_Tarifpositionen.json"
PAUSCHALE_LP_PATH = DATA_DIR / "tblPauschaleLeistungsposition.json"
PAUSCHALEN_PATH = DATA_DIR / "tblPauschalen.json"
PAUSCHALE_BED_PATH = DATA_DIR / "tblPauschaleBedingungen.json"
TABELLEN_PATH = DATA_DIR / "tblTabellen.json"

# --- Initialisierung ---
app = Flask(__name__, static_folder='.', static_url_path='')
leistungskatalog_data: list[dict] = []
leistungskatalog_dict: dict[str, dict] = {} # Für schnellen Typ-Lookup
regelwerk_dict: dict[str, dict] = {}
tardoc_data_dict: dict[str, dict] = {} # TARDOC-Daten als Dict für schnellen Lookup
pauschale_lp_data: list[dict] = []
pauschalen_data: list[dict] = []
pauschalen_dict: dict[str, dict] = {} # Für schnellen Detail-Lookup
pauschale_bedingungen_data: list[dict] = []
tabellen_data: list[dict] = []

# --- Daten laden ---
def load_data():
    global leistungskatalog_data, leistungskatalog_dict, regelwerk_dict, tardoc_data_dict
    global pauschale_lp_data, pauschalen_data, pauschalen_dict, pauschale_bedingungen_data, tabellen_data

    files_to_load = {
        "Leistungskatalog": (LEISTUNGSKATALOG_PATH, leistungskatalog_data),
        "PauschaleLP": (PAUSCHALE_LP_PATH, pauschale_lp_data),
        "Pauschalen": (PAUSCHALEN_PATH, pauschalen_data),
        "PauschaleBedingungen": (PAUSCHALE_BED_PATH, pauschale_bedingungen_data),
        "TARDOC": (TARDOC_PATH, []), # Wird direkt ins Dict geladen
        "Tabellen": (TABELLEN_PATH, tabellen_data)
    }

    print("--- Lade Daten ---")
    for name, (path, target_list) in files_to_load.items():
        try:
            if path.is_file():
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if name == "TARDOC":
                         # --- !!! ANPASSEN: Korrekten Schlüssel für LKN in TARDOC-Daten !!! ---
                         TARDOC_LKN_KEY = 'LKN' # Oder 'Tarifposition'
                         # --- !!! ENDE ANPASSUNG !!! ---
                         for item in data:
                              if item and TARDOC_LKN_KEY in item: tardoc_data_dict[item[TARDOC_LKN_KEY]] = item
                         print(f"✓ {name}-Daten '{path}' geladen ({len(tardoc_data_dict)} Einträge im Dict).")
                    elif name == "Pauschalen":
                         pauschalen_data.extend(data) # Füge zur Liste hinzu
                         # --- !!! ANPASSEN: Korrekten Schlüssel für Pauschale in Pauschalen-Daten !!! ---
                         PAUSCHALE_KEY = 'Pauschale'
                         # --- !!! ENDE ANPASSUNG !!! ---
                         for item in data:
                              if item and PAUSCHALE_KEY in item: pauschalen_dict[item[PAUSCHALE_KEY]] = item
                         print(f"✓ {name}-Daten '{path}' geladen ({len(pauschalen_data)} Einträge / {len(pauschalen_dict)} im Dict).")
                    elif name == "Leistungskatalog":
                         leistungskatalog_data.extend(data)
                         # --- !!! ANPASSEN: Korrekten Schlüssel für LKN im Katalog !!! ---
                         KATALOG_LKN_KEY = 'LKN'
                         # --- !!! ENDE ANPASSUNG !!! ---
                         for item in data:
                              if item and KATALOG_LKN_KEY in item: leistungskatalog_dict[item[KATALOG_LKN_KEY]] = item
                         print(f"✓ {name}-Daten '{path}' geladen ({len(leistungskatalog_data)} Einträge / {len(leistungskatalog_dict)} im Dict).")
                    else:
                         target_list.extend(data) # Füge zur entsprechenden globalen Liste hinzu
                         print(f"✓ {name}-Daten '{path}' geladen ({len(target_list)} Einträge).")

            else: print(f"FEHLER: {name}-Datei nicht gefunden: {path}")
        except Exception as e: print(f"FEHLER beim Laden der {name}-Daten ({path}): {e}")

    # Lade Regelwerk
    if regelpruefer and REGELWERK_PATH.is_file():
         regelwerk_dict = regelpruefer.lade_regelwerk(str(REGELWERK_PATH))
         print(f"✓ Regelwerk '{REGELWERK_PATH}' geladen ({len(regelwerk_dict)} LKNs).")
    elif regelpruefer: print(f"FEHLER: Regelwerk nicht gefunden: {REGELWERK_PATH}"); regelwerk_dict = {}
    else: print("ℹ️ Regelprüfung deaktiviert."); regelwerk_dict = {}
    print("--- Daten laden abgeschlossen ---")


# --- LLM Stufe 1: LKN Identifikation ---
def call_gemini_stage1(user_input: str, katalog_context: str) -> dict:
    if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY nicht konfiguriert.")
    # Prompt für LISTE von Leistungen und extrahierte Infos
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

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": 1024 # Etwas mehr Platz für Listen
         }
    }
    print(f"Sende Anfrage Stufe 1 an Gemini Model: {GEMINI_MODEL}...")
    response = requests.post(gemini_url, json=payload, timeout=60)
    print(f"Gemini Stufe 1 Antwort Status Code: {response.status_code}")
    if not response.ok:
        raise ConnectionError(f"Gemini API Stufe 1 Error {response.status_code}: {response.text}")

    gemini_data = response.json()
    try:
        # Pfad zum Text kann variieren, prüfe auf Existenz
        candidate = gemini_data.get('candidates', [{}])[0]
        content = candidate.get('content', {})
        parts = content.get('parts', [{}])[0]
        raw_text_response = parts.get('text', '')

        # *** NEU: Logge die rohe Textantwort ***
        print(f"DEBUG: Roher Text von LLM Stufe 1:\n---\n{raw_text_response}\n---")
        # *** ENDE LOG ***

        if not raw_text_response:
             finish_reason = candidate.get('finishReason', 'UNKNOWN')
             if finish_reason != 'STOP':
                  raise ValueError(f"Gemini stopped with reason: {finish_reason} - Response: {gemini_data}")
             else:
                  raise ValueError("Leere Textantwort von Gemini erhalten.")

        llm_response_json = json.loads(raw_text_response)
        print(f"DEBUG: Geparses LLM JSON Stufe 1 VOR Validierung: {json.dumps(llm_response_json, indent=2)}")
        print(f"LLM Stufe 1 Antwort JSON: {llm_response_json}") # Dieser Log bleibt

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
             # Prüfe, ob Menge eine Zahl ist (oder null)
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
    except Exception as e:
        import traceback
        print(f"Unerwarteter FEHLER im LLM Stufe 1: {e}")
        print(traceback.format_exc())
        raise e

# --- LLM Stufe 2: Pauschalen-Ranking ---
def call_gemini_stage2_ranking(user_input: str, potential_pauschalen_text: str) -> list[str]:
    """ Ruft Gemini auf, um eine Liste potenzieller Pauschalen zu ranken. """
    if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY nicht konfiguriert.")
    prompt = f"""Basierend auf dem folgenden Behandlungstext, welche der unten aufgeführten Pauschalen passt inhaltlich am besten?
Berücksichtige die Beschreibung der Pauschale ('Pauschale_Text').
Gib eine priorisierte Liste der Pauschalen-Codes zurück, beginnend mit der besten Übereinstimmung.
Gib NUR die Pauschalen-Codes als kommagetrennte Liste zurück (z.B. "CODE1,CODE2,CODE3").

Behandlungstext: "{user_input}"

Potenzielle Pauschalen:
--- Pauschalen Start ---
{potential_pauschalen_text}
--- Pauschalen Ende ---

Priorisierte Pauschalen-Codes (nur kommagetrennte Liste):"""

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    # Hier KEIN JSON als Antworttyp fordern, da wir nur eine Textliste wollen
    payload = { "contents": [{"parts": [{"text": prompt}]}], "generationConfig": { "temperature": 0.1, "maxOutputTokens": 500 } }
    print(f"Sende Anfrage Stufe 2 (Ranking) an Gemini Model: {GEMINI_MODEL}...")
    response = requests.post(gemini_url, json=payload, timeout=45)
    print(f"Gemini Stufe 2 Antwort Status Code: {response.status_code}")
    if not response.ok: raise ConnectionError(f"Gemini API Stufe 2 Error {response.status_code}: {response.text}")
    gemini_data = response.json()
    try:
        ranked_text = gemini_data['candidates'][0]['content']['parts'][0]['text']
        # *** NEU: Logge die rohe Textantwort ***
        print(f"DEBUG: Roher Text von LLM Stufe 2 (Ranking):\n---\n{ranked_text}\n---")
        # *** ENDE LOG ***
        print(f"LLM Stufe 2 Antwort (Ranking Text): '{ranked_text}'")
        ranked_codes = [code.strip() for code in ranked_text.split(',') if code.strip()]
        print(f"LLM Stufe 2 Gerankte Codes: {ranked_codes}")
        return ranked_codes
    except (KeyError, IndexError, TypeError) as e:
        print(f"FEHLER beim Extrahieren des Rankings aus LLM Stufe 2 Antwort: {e}")
        return [] # Leere Liste bei Fehler
    except Exception as e: print(f"Unerwarteter FEHLER im LLM Stufe 2: {e}"); raise e


# --- API Endpunkt ---
@app.route('/api/analyze-billing', methods=['POST'])
def analyze_billing():
    print("\n--- Request an /api/analyze-billing erhalten ---")
    # 1. Eingaben holen
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()
    user_input = data.get('inputText')
    icd_input = data.get('icd', [])
    gtin_input = data.get('gtin', []) # GTINs für Pauschalenprüfung
    if not user_input: return jsonify({"error": "'inputText' is required"}), 400
    print(f"Empfangener inputText: {user_input}")
    print(f"Empfangene ICDs: {icd_input}, GTINs: {gtin_input}")

    # 2. LLM Stufe 1: LKNs identifizieren
    llm_stage1_result = None
    try:
        if not leistungskatalog_data: raise ValueError("Leistungskatalog nicht geladen")
        katalog_context = "\n".join([f"LKN: {item.get('LKN', 'N/A')}, Typ: {item.get('Typ', 'N/A')}, Beschreibung: {item.get('Beschreibung', 'N/A')}" for item in leistungskatalog_data])
        llm_stage1_result = call_gemini_stage1(user_input, katalog_context)
    except Exception as e: return jsonify({"error": f"LLM Stufe 1 Fehler: {e}"}), 500

    # 3. Regelprüfung für identifizierte LKNs
    regel_ergebnisse_liste = []
    identified_leistungen_llm = llm_stage1_result.get("identified_leistungen", [])
    extracted_info = llm_stage1_result.get("extracted_info", {})
    alter_llm = extracted_info.get("alter")
    geschlecht_llm = extracted_info.get("geschlecht")

    # *** HIER INITIALISIEREN ***
    rule_checked_leistungen = [] # Liste der LKNs, die Regeln bestehen (als Dict mit finaler Menge)
    # *** ENDE INITIALISIERUNG ***

    if not identified_leistungen_llm:
         regel_ergebnisse_liste.append({
             "lkn": None,
             "regelpruefung": {"abrechnungsfaehig": False, "fehler": ["Keine gültige LKN vom LLM identifiziert."]},
             "finale_menge": 0
         })
    else:
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
            try:
                menge_initial = int(menge_initial)
                if menge_initial < 0: menge_initial = 1
            except (ValueError, TypeError):
                print(f"WARNUNG: Ungültige Menge '{leistung.get('menge')}' vom LLM für {lkn}, verwende 1.")
                menge_initial = 1

            print(f"Prüfe LKN {lkn} mit initialer Menge vom LLM: {menge_initial}")

            regel_ergebnis = {"abrechnungsfaehig": False, "fehler": ["Regelprüfung nicht durchgeführt."]}
            if regelpruefer and regelwerk_dict:
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

            # *** Mengenanpassungslogik HIER ***
            angepasste_menge = menge_initial
            if not regel_ergebnis.get("abrechnungsfaehig", False):
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
                 # Stelle sicher, dass 'leistung' hier das Original-Dict vom LLM ist
                 rule_checked_leistungen.append({**leistung, "menge": angepasste_menge})


    # 4. Entscheidung Pauschale vs. TARDOC
    final_result = {}
    # Prüfe, ob *irgendeine* P/PZ LKN *ursprünglich* identifiziert wurde UND die Regelprüfung bestanden hat
    hatPauschalenTypRegelkonform = any(
        l.get("typ") in ['P', 'PZ'] and
        next((r for r in regel_ergebnisse_liste if r["lkn"] == l.get("lkn")), {}).get("regelpruefung", {}).get("abrechnungsfaehig")
        for l in identified_leistungen_llm # Prüfe ursprüngliche Liste
    )

    if hatPauschalenTypRegelkonform:
        print("INFO: Regelkonforme P/PZ LKN gefunden. Pauschalenabrechnung wird geprüft...")
        # --- Pauschalen-Logik ---
        # 4a. Potenzielle Pauschalen finden (basierend auf ALLEN regelkonformen LKNs)
        potential_pauschale_codes = set()
        # --- !!! ANPASSEN: Schlüsselnamen !!! ---
        LKN_KEY_IN_PAUSCHALE_LP = 'Leistungsposition'
        PAUSCHALE_KEY_IN_PAUSCHALE_LP = 'Pauschale'
        PAUSCHALE_KEY_IN_PAUSCHALEN = 'Pauschale'
        # --- !!! ENDE ANPASSUNG !!! ---

        rule_checked_lkns = [r["lkn"] for r in regel_ergebnisse_liste if r["regelpruefung"]["abrechnungsfaehig"]]
        for item in pauschale_lp_data:
            if item.get(LKN_KEY_IN_PAUSCHALE_LP) in rule_checked_lkns:
                 if item.get(PAUSCHALE_KEY_IN_PAUSCHALE_LP):
                      potential_pauschale_codes.add(item[PAUSCHALE_KEY_IN_PAUSCHALE_LP])

        for l in rule_checked_leistungen: # Direkte Trigger hinzufügen
            if l.get("typ") in ['P', 'PZ'] and l.get("lkn") in pauschalen_dict:
                 potential_pauschale_codes.add(l["lkn"])

        if not potential_pauschale_codes:
             final_result = {"type": "Error", "message": "Pauschale notwendig (Typ P/PZ identifiziert), aber keine potenziellen Pauschalen gefunden."}
        else:
            # 4b. Details holen und Text für LLM Stufe 2 bauen
            potential_details = [pauschalen_dict[code] for code in potential_pauschale_codes if code in pauschalen_dict]
            if not potential_details:
                 final_result = {"type": "Error", "message": "Pauschalen-Codes gefunden, aber keine Details in tblPauschalen."}
            else:
                 pauschalen_context_text = "\n".join([f"Code: {p[PAUSCHALE_KEY_IN_PAUSCHALEN]}, Text: {p.get('Pauschale_Text', 'N/A')}" for p in potential_details])

                 # 4c. LLM Stufe 2: Ranking aufrufen
                 ranked_pauschale_codes = []
                 try:
                      ranked_pauschale_codes = call_gemini_stage2_ranking(user_input, pauschalen_context_text)
                 except Exception as e:
                      print(f"FEHLER bei LLM Stufe 2: {e}")
                      # Fallback: Nutze alle potenziellen Pauschalen unsortiert
                      ranked_pauschale_codes = list(potential_pauschale_codes)

                 if not ranked_pauschale_codes:
                      final_result = {"type": "Error", "message": "LLM Stufe 2 lieferte kein Pauschalen-Ranking."}
                 else:
                      # 4d. Bedingungen der gerankten Pauschalen prüfen
                      found_applicable_pauschale = False
                      bedingungs_pruef_html_result = "Keine anwendbare Pauschale geprüft." # Default
                      for pauschale_code in ranked_pauschale_codes:
                           if pauschale_code not in pauschalen_dict: continue # Überspringe unbekannte Codes

                           print(f"Prüfe Bedingungen für gerankte Pauschale: {pauschale_code}")
                           # Baue Kontext für Bedingungsprüfung
                           bedingungs_context = {
                               "ICD": icd_input, "GTIN": gtin_input,
                               "LKN": rule_checked_lkns # Alle regelkonformen LKNs
                           }
                           # Rufe deterministische Bedingungsprüfung auf
                           condition_result = regelpruefer.check_pauschale_conditions(
                               pauschale_code, bedingungs_context, pauschale_bedingungen_data, tabellen_data
                           )

                           if condition_result.get("allMet"):
                                print(f"Pauschale {pauschale_code} erfüllt Bedingungen.")
                                final_result = {
                                    "type": "Pauschale",
                                    "details": pauschalen_dict[pauschale_code], # Details der anwendbaren Pauschale
                                    "bedingungs_pruef_html": condition_result.get("html", "") # Optional HTML für Details
                                }
                                found_applicable_pauschale = True
                                break # Erste passende Pauschale gefunden

                      if not found_applicable_pauschale:
                           final_result = {"type": "Error", "message": "Pauschale notwendig, aber keine der potenziellen/gerankten Pauschalen erfüllt die Bedingungen."}
    else:
        # --- TARDOC-Logik ---
        print("INFO: Keine regelkonforme P/PZ LKN gefunden oder keine P/PZ identifiziert. TARDOC-Abrechnung wird vorbereitet...")
        tardoc_leistungen_final = []
        for res in regel_ergebnisse_liste:
            lkn_info = leistungskatalog_dict.get(res["lkn"])
            # *** GEÄNDERTE BEDINGUNG ***
            # Nimm E/EZ-Typen, wenn eine FINALE Menge > 0 existiert
            # (Die Regelprüfung hat die Menge ggf. angepasst und abrechnungsfaehig auf True gesetzt ODER
            #  die ursprüngliche Prüfung war OK und Menge war > 0)
            if lkn_info and lkn_info.get("Typ") in ['E', 'EZ'] and res["finale_menge"] > 0:
                # Füge hinzu, wenn die Regelprüfung OK ist (entweder ursprünglich oder nach Anpassung)
                if res["regelpruefung"]["abrechnungsfaehig"]:
                    tardoc_leistungen_final.append({
                        "lkn": res["lkn"],
                        "menge": res["finale_menge"], # Die finale Menge
                        "typ": lkn_info.get("Typ"),
                        "beschreibung": lkn_info.get("Beschreibung", "")
                    })
                else:
                    # Optional: Logge, warum eine LKN mit Menge > 0 trotzdem nicht aufgenommen wird
                    print(f"INFO: LKN {res['lkn']} hat finale Menge {res['finale_menge']}, ist aber nicht abrechnungsfähig wegen: {res['regelpruefung']['fehler']}")

        if not tardoc_leistungen_final:
             final_result = {"type": "Error", "message": "Keine abrechenbaren TARDOC-Leistungen gefunden."}
        else:
             final_result = {
                 "type": "TARDOC",
                 "leistungen": tardoc_leistungen_final # Liste der abzurechnenden TARDOC-Leistungen
             }

    # 5. Kombiniertes Ergebnis an Frontend senden
    # Füge LLM Stufe 1 Ergebnis hinzu für Transparenz
    final_response = {
        "llm_ergebnis_stufe1": llm_stage1_result,
        "regel_ergebnisse_details": regel_ergebnisse_liste, # Sende ALLE Regelergebnisse
        "abrechnung": final_result
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

