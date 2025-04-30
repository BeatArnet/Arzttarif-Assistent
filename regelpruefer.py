# regelpruefer.py

"""
Modul zur Prüfung der Abrechnungsregeln (Regelwerk) für TARDOC-Leistungen
und der Bedingungen für Pauschalen.
"""
import json
import re # Importiere Regex für Mengenanpassung

# --- Konstanten für Regeltypen (zur besseren Lesbarkeit) ---
REGEL_MENGE = "Mengenbeschränkung"
REGEL_ZUSCHLAG_ZU = "Nur als Zuschlag zu"
REGEL_NICHT_KUMULIERBAR = "Nicht kumulierbar mit"
REGEL_PAT_GESCHLECHT = "Patientenbedingung: Geschlecht" # Veraltet, nutze Patientenbedingung
REGEL_PAT_ALTER = "Patientenbedingung: Alter"       # Veraltet, nutze Patientenbedingung
REGEL_PAT_BEDINGUNG = "Patientenbedingung" # Neuer, generischer Typ
REGEL_DIAGNOSE = "Diagnosepflicht"
REGEL_PAUSCHAL_AUSSCHLUSS = "Pauschalenausschluss"
# Fügen Sie hier weitere Typen hinzu, falls Ihr Regelmodell sie enthält

# --- Ladefunktion für das Regelwerk ---
def lade_regelwerk(path: str) -> dict:
    """
    Lädt das Regelwerk aus einer JSON-Datei und gibt ein Mapping von LKN zu Regeln zurück.

    Args:
        path: Pfad zur JSON-Datei mit strukturierten Regeln.
    Returns:
        Dict[str, list]: Schlüssel sind LKN-Codes, Werte sind Listen von Regel-Definitionsdicts.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        mapping: dict = {}
        # Annahme: data ist eine Liste von Objekten, jedes mit "LKN" und "Regeln"
        for entry in data:
            lkn = entry.get("LKN")
            if not lkn:
                print(f"WARNUNG: Regelobjekt ohne LKN gefunden: {entry}")
                continue
            rules = entry.get("Regeln") or []
            mapping[lkn] = rules
        return mapping
    except FileNotFoundError:
        print(f"FEHLER: Regelwerk-Datei nicht gefunden: {path}")
        return {}
    except json.JSONDecodeError as e:
        print(f"FEHLER: Fehler beim Parsen der Regelwerk-JSON-Datei '{path}': {e}")
        return {}
    except Exception as e:
        print(f"FEHLER: Unerwarteter Fehler beim Laden des Regelwerks '{path}': {e}")
        return {}

# --- Hauptfunktion zur Regelprüfung für LKNs ---
def pruefe_abrechnungsfaehigkeit(fall: dict, regelwerk: dict) -> dict:
    """
    Prüft, ob eine gegebene Leistungsposition abrechnungsfähig ist.

    Args:
        fall: Dict mit Kontext zur Leistung (LKN, Menge, ICD, Begleit-LKNs, Pauschalen,
              optional Alter, Geschlecht, GTIN).
        regelwerk: Mapping von LKN zu Regel-Definitionen aus lade_regelwerk.
    Returns:
        Dict mit Schlüsseln:
          - abrechnungsfaehig (bool): True, wenn alle Regeln erfüllt sind.
          - fehler (list): Liste der Regelverstöße (Fehlermeldungen).
    """
    lkn = fall.get("LKN")
    menge = fall.get("Menge", 0) or 0
    begleit = fall.get("Begleit_LKNs") or []
    # Kontextdaten
    alter = fall.get("Alter")
    geschlecht = fall.get("Geschlecht")
    gtins = fall.get("GTIN") or [] # Stelle sicher, dass GTIN hier ankommt
    if isinstance(gtins, str): gtins = [gtins] # Mache zur Liste, falls String

    errors: list = []
    allowed = True

    # Hole die Regeln für diese LKN
    rules = regelwerk.get(lkn) or []
    if not rules:
        # Keine Regeln definiert -> gilt als OK
        return {"abrechnungsfaehig": True, "fehler": []}

    for rule in rules:
        typ = rule.get("Typ")
        if not typ: continue # Regel ohne Typ ignorieren

        # --- Mengenbesschränkung ---
        if typ == REGEL_MENGE:
            max_menge = rule.get("MaxMenge")
            if isinstance(max_menge, (int, float)) and menge > max_menge:
                allowed = False
                errors.append(f"Mengenbeschränkung überschritten (max. {max_menge}, angefragt {menge})")

        # --- Nur als Zuschlag zu ---
        elif typ == REGEL_ZUSCHLAG_ZU:
            parent = rule.get("LKN")
            if parent and parent not in begleit:
                allowed = False
                errors.append(f"Nur als Zuschlag zu {parent} zulässig (Basis fehlt)")

        # --- Nicht kumulierbar mit ---
        elif typ == REGEL_NICHT_KUMULIERBAR:
            not_with = rule.get("LKNs") or rule.get("LKN") or []
            if isinstance(not_with, str): not_with = [not_with]
            konflikt = [code for code in begleit if code in not_with]
            if konflikt:
                allowed = False
                codes = ", ".join(konflikt)
                errors.append(f"Nicht kumulierbar mit: {codes}")

        # --- Patientenbedingung (Generisch) ---
        elif typ == REGEL_PAT_BEDINGUNG:
            field = rule.get("Feld") # z.B. "Alter", "Geschlecht", "GTIN"
            wert_regel = rule.get("Wert") # Wert aus der Regel
            min_val = rule.get("MinWert") # Für Bereiche (z.B. Alter)
            max_val = rule.get("MaxWert") # Für Bereiche (z.B. Alter)
            wert_fall = fall.get(field) # Wert aus dem Abrechnungsfall

            bedingung_text = f"Patientenbedingung ({field})"
            condition_met = False

            if wert_fall is None:
                condition_met = False # Bedingung nicht prüfbar/erfüllt, wenn Wert fehlt
                errors.append(f"{bedingung_text} nicht erfüllt: Kontextwert fehlt")
            elif field == "Alter":
                try:
                    alter_patient = int(wert_fall)
                    alter_ok = True
                    range_parts = []
                    if min_val is not None and alter_patient < int(min_val): alter_ok = False; range_parts.append(f"min. {min_val}")
                    if max_val is not None and alter_patient > int(max_val): alter_ok = False; range_parts.append(f"max. {max_val}")
                    if wert_regel is not None and alter_patient != int(wert_regel): alter_ok = False; range_parts.append(f"exakt {wert_regel}") # Exakter Wert?
                    condition_met = alter_ok
                    if not condition_met: errors.append(f"{bedingung_text} ({' '.join(range_parts)}) nicht erfüllt (Patient: {alter_patient})")
                except (ValueError, TypeError):
                    condition_met = False; errors.append(f"{bedingung_text}: Ungültiger Alterswert im Fall ({wert_fall})")
            elif field == "Geschlecht":
                if isinstance(wert_regel, str) and isinstance(wert_fall, str):
                    condition_met = wert_fall.lower() == wert_regel.lower()
                    if not condition_met: errors.append(f"{bedingung_text}: erwartet '{wert_regel}', gefunden '{wert_fall}'")
                else: condition_met = False; errors.append(f"{bedingung_text}: Ungültige Werte für Geschlechtsprüfung")
            elif field == "GTIN":
                 # Prüfe, ob mindestens ein benötigter GTIN im Fall vorhanden ist
                 required_gtins = [str(wert_regel)] if isinstance(wert_regel, (str, int)) else [str(w) for w in (wert_regel or [])]
                 provided_gtins_str = [str(g) for g in (gtins or [])] # Nutze gtins Variable
                 condition_met = any(req in provided_gtins_str for req in required_gtins)
                 if not condition_met: errors.append(f"{bedingung_text}: Erwartet einen von {required_gtins}, nicht gefunden")
            else:
                 print(f"WARNUNG: Unbekanntes Feld '{field}' für Patientenbedingung bei LKN {lkn}.")
                 condition_met = True # Unbekannte Felder ignorieren? Oder Fehler? Hier: Ignorieren

            if not condition_met: allowed = False

        # --- Diagnosepflicht ---
        elif typ == REGEL_DIAGNOSE:
            required_icds = rule.get("ICD") or rule.get("ICDs", [])
            if isinstance(required_icds, str): required_icds = [required_icds]
            provided_icds = fall.get("ICD", [])
            if isinstance(provided_icds, str): provided_icds = [provided_icds]

            if required_icds and not any(req_icd.upper() in (p_icd.upper() for p_icd in provided_icds) for req_icd in required_icds):
                 allowed = False
                 errors.append(f"Erforderliche Diagnose(n) nicht vorhanden (Benötigt: {', '.join(required_icds)})")

        # --- Pauschalenausschluss ---
        elif typ == REGEL_PAUSCHAL_AUSSCHLUSS:
             verbotene_pauschalen = rule.get("Pauschale") or rule.get("Pauschalen", [])
             if isinstance(verbotene_pauschalen, str): verbotene_pauschalen = [verbotene_pauschalen]
             abgerechnete_pauschalen = fall.get("Pauschalen", [])
             if isinstance(abgerechnete_pauschalen, str): abgerechnete_pauschalen = [abgerechnete_pauschalen]

             if any(verb in abgerechnete_pauschalen for verb in verbotene_pauschalen):
                  allowed = False
                  errors.append(f"Leistung nicht zulässig bei gleichzeitiger Abrechnung der Pauschale(n): {', '.join(verbotene_pauschalen)}")

        # --- Unbekannter Regeltyp ---
        else:
            print(f"WARNUNG: Unbekannter Regeltyp '{typ}' für LKN {lkn} ignoriert.")
            continue

    return {"abrechnungsfaehig": allowed, "fehler": errors}


# --- Funktion zur Prüfung von Pauschalenbedingungen ---
def check_pauschale_conditions(
    pauschale_code: str,
    context: dict, # Enthält ICD, GTIN, LKN (Liste aller regelkonformen LKNs im Fall)
    pauschale_bedingungen_data: list[dict],
    tabellen_data: list[dict]
) -> dict:
    """
    Prüft die Bedingungen für eine gegebene Pauschale.
    """
    errors: list[str] = []
    condition_details: list[str] = [] # Für detailliertes Logging/HTML
    all_met = True

    # Finde alle Bedingungen für diese Pauschale
    # --- !!! ANPASSEN: Korrekten Schlüssel für Pauschale in Bedingungs-Daten !!! ---
    PAUSCHALE_KEY_BED = 'Pauschale'
    # --- !!! ENDE ANPASSUNG !!! ---
    conditions = [cond for cond in pauschale_bedingungen_data if cond.get(PAUSCHALE_KEY_BED) == pauschale_code]

    if not conditions:
        print(f"Info: Keine spezifischen Bedingungen für Pauschale {pauschale_code} gefunden.")
        return {"allMet": True, "html": "<ul><li>Keine spezifischen Bedingungen gefunden.</li></ul>", "errors": []}

    print(f"Info: Prüfe {len(conditions)} Bedingungen für Pauschale {pauschale_code}...")

    # Kontext extrahieren
    provided_icds = context.get("ICD", [])
    provided_gtins = context.get("GTIN", [])
    provided_lkns = context.get("LKN", [])
    if isinstance(provided_icds, str): provided_icds = [provided_icds]
    if isinstance(provided_gtins, str): provided_gtins = [provided_gtins]
    if isinstance(provided_lkns, str): provided_lkns = [provided_lkns]

    # Iteriere durch jede Bedingung
    for i, cond in enumerate(conditions):
        # --- !!! ANPASSEN: Korrekte Schlüsselnamen für Bedingungen !!! ---
        bedingungstyp = cond.get("Bedingungstyp", "").upper()
        werte_str = cond.get("Werte", "") # Kann kommasepariert sein
        tabelle_ref = cond.get("Tabelle") # Für Typ "IN TABELLE"
        # --- !!! ENDE ANPASSUNG !!! ---

        werte_list = [w.strip() for w in str(werte_str).split(',') if w.strip()]

        condition_met = False
        status_text = "NICHT geprüft"
        bedingung_text = f"Typ: {bedingungstyp}, Wert/Ref: '{werte_str or tabelle_ref or '-'}'"

        try:
            if not werte_list and not tabelle_ref:
                print(f"WARNUNG: Bedingung {i+1} für {pauschale_code} hat keine Werte oder Tabelle.")
                condition_met = True; status_text = "Erfüllt (keine Werte)"
            elif bedingungstyp == "ICD":
                condition_met = any(req_icd.upper() in (p_icd.upper() for p_icd in provided_icds) for req_icd in werte_list)
                status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
            elif bedingungstyp == "GTIN":
                 condition_met = any(req_gtin in provided_gtins for req_gtin in werte_list)
                 status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
            elif bedingungstyp == "LKN" or bedingungstyp == "LEISTUNGSPOSITIONEN IN LISTE":
                 condition_met = any(req_lkn.upper() in (p_lkn.upper() for p_lkn in provided_lkns) for req_lkn in werte_list)
                 status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
            elif bedingungstyp == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp == "TARIFPOSITIONEN IN TABELLE":
                 # --- !!! ANPASSEN: Korrekte Schlüsselnamen in tblTabellen !!! ---
                 TAB_CODE_KEY = "Code"
                 TAB_TABELLE_KEY = "Tabelle"
                 TAB_TYP_KEY = "Tabelle_Typ"
                 # --- !!! ENDE ANPASSUNG !!! ---
                 codes_in_tabelle = [
                     e.get(TAB_CODE_KEY) for e in tabellen_data
                     if e.get(TAB_TABELLE_KEY) == tabelle_ref and e.get(TAB_TYP_KEY) == "service_catalog" and e.get(TAB_CODE_KEY)
                 ]
                 condition_met = any(code.upper() in (p_lkn.upper() for p_lkn in provided_lkns) for code in codes_in_tabelle)
                 bedingung_text += f" (Tabelle: {tabelle_ref})"
                 status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
            elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE":
                 # --- !!! ANPASSEN: Korrekte Schlüsselnamen in tblTabellen !!! ---
                 TAB_CODE_KEY = "Code"
                 TAB_TABELLE_KEY = "Tabelle"
                 TAB_TYP_KEY = "Tabelle_Typ"
                 # --- !!! ENDE ANPASSUNG !!! ---
                 codes_in_tabelle = [
                     e.get(TAB_CODE_KEY) for e in tabellen_data
                     if e.get(TAB_TABELLE_KEY) == tabelle_ref and e.get(TAB_TYP_KEY) == "icd" and e.get(TAB_CODE_KEY)
                 ]
                 condition_met = any(code.upper() in (p_icd.upper() for p_icd in provided_icds) for code in codes_in_tabelle)
                 bedingung_text += f" (Tabelle: {tabelle_ref})"
                 status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
            elif bedingungstyp == "MEDIKAMENTE IN LISTE":
                 condition_met = any(req_gtin in provided_gtins for req_gtin in werte_list)
                 status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
            elif bedingungstyp == "PATIENTENBEDINGUNG":
                 field = cond.get("Feld")
                 wert_regel = cond.get("Wert")
                 min_val = cond.get("MinWert")
                 max_val = cond.get("MaxWert")
                 wert_fall = context.get(field)
                 bedingung_text = f"Typ: {bedingungstyp}, Feld: {field}, Wert: '{wert_regel or str(min_val)+'-'+str(max_val)}'"

                 if wert_fall is None: condition_met = False; status_text = "NICHT erfüllt (Kontext fehlt)"
                 elif field == "Alter":
                     try:
                         alter_patient = int(wert_fall); alter_ok = True; range_parts = []
                         if min_val is not None and alter_patient < int(min_val): alter_ok = False; range_parts.append(f"min. {min_val}")
                         if max_val is not None and alter_patient > int(max_val): alter_ok = False; range_parts.append(f"max. {max_val}")
                         if wert_regel is not None and alter_patient != int(wert_regel): alter_ok = False; range_parts.append(f"exakt {wert_regel}")
                         condition_met = alter_ok; status_text = "Erfüllt" if condition_met else f"NICHT erfüllt ({' '.join(range_parts)})"
                     except (ValueError, TypeError): condition_met = False; status_text = "NICHT erfüllt (ungültiger Wert)"
                 elif field == "Geschlecht":
                     if isinstance(wert_regel, str) and isinstance(wert_fall, str): condition_met = wert_fall.lower() == wert_regel.lower(); status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
                     else: condition_met = False; status_text = "NICHT erfüllt (ungültiger Wert)"
                 elif field == "GTIN":
                     required_gtins_cond = [str(wert_regel)] if isinstance(wert_regel, (str, int)) else [str(w) for w in (wert_regel or [])]
                     condition_met = any(req in provided_gtins for req in required_gtins_cond); status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
                 else: print(f"WARNUNG: Unbekanntes Feld '{field}' für Patientenbedingung Pauschale {pauschale_code}."); condition_met = True; status_text = "Erfüllt (unbekanntes Feld)"
            else:
                print(f"WARNUNG: Unbekannter Pauschalen-Bedingungstyp '{bedingungstyp}' für {pauschale_code}. Wird als erfüllt angenommen.")
                condition_met = True
                status_text = "Erfüllt (unbekannter Typ)"

        except Exception as e:
            print(f"FEHLER bei Prüfung Bedingung {i+1} für {pauschale_code}: {e}")
            condition_met = False
            status_text = f"FEHLER bei Prüfung: {e}"
            errors.append(f"Fehler bei Prüfung Bedingung {bedingung_text}: {e}")

        # Füge Detail mit Status hinzu
        color = "green" if condition_met else "red" if status_text.startswith("NICHT") else "orange"
        condition_details.append(f'<li>{bedingung_text}: <span style="color:{color}; font-weight:bold;">{status_text}</span></li>')

        if not condition_met:
            all_met = False
            if not status_text.startswith("FEHLER"):
                 errors.append(f"Bedingung nicht erfüllt: {bedingung_text}")

    # Erstelle HTML-String für Details
    html_details = "<ul>" + "".join(condition_details) + "</ul>"

    return {
        "allMet": all_met,
        "html": html_details,
        "errors": errors
    }