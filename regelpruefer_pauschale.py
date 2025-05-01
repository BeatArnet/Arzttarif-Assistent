# regelpruefer_pauschale.py

"""
Modul zur Prüfung der Bedingungen für TARDOC-Pauschalen.
"""
import json
from typing import Dict, List, Any # Typing hinzugefügt

def check_pauschale_conditions(
    pauschale_code: str,
    context: dict, # Enthält ICD, GTIN, LKN (Liste aller regelkonformen LKNs im Fall), Alter, Geschlecht
    pauschale_bedingungen_data: list[dict],
    tabellen_data: list[dict]
) -> dict:
    """
    Prüft die Bedingungen für eine gegebene Pauschale deterministisch.

    Args:
        pauschale_code: Der Code der zu prüfenden Pauschale.
        context: Dictionary mit Kontextinformationen des Abrechnungsfalls.
                 Erwartete Keys im context: 'ICD' (list), 'GTIN' (list), 'LKN' (list), 'Alter' (int/None), 'Geschlecht' (str/None).
        pauschale_bedingungen_data: Liste aller Bedingungsobjekte aus tblPauschaleBedingungen.json.
        tabellen_data: Liste aller Einträge aus tblTabellen.json.

    Returns:
        Dict mit Schlüsseln:
          - allMet (bool): True, wenn alle Bedingungen erfüllt sind.
          - html (str): HTML-String zur Darstellung der Prüfungsergebnisse.
          - errors (list): Liste der nicht erfüllten Bedingungen (Strings).
    """
    errors: list[str] = []
    condition_details: list[str] = [] # Für detailliertes Logging/HTML
    all_met = True

    # Finde alle Bedingungen für diese Pauschale
    # Annahme: Schlüssel in pauschale_bedingungen_data ist 'Pauschale'
    conditions = [cond for cond in pauschale_bedingungen_data if cond.get("Pauschale") == pauschale_code]

    if not conditions:
        print(f"Info: Keine spezifischen Bedingungen für Pauschale {pauschale_code} gefunden.")
        # Erzeuge HTML auch wenn keine Bedingungen da sind
        html_details = "<ul><li>Keine spezifischen Bedingungen gefunden.</li></ul>"
        return {"allMet": True, "html": html_details, "errors": []}

    print(f"Info: Prüfe {len(conditions)} Bedingungen für Pauschale {pauschale_code}...")

    # Kontext extrahieren (sicherstellen, dass es Listen sind, wo nötig)
    provided_icds = context.get("ICD", [])
    provided_gtins = context.get("GTIN", [])
    provided_lkns = context.get("LKN", [])
    provided_alter = context.get("Alter")
    provided_geschlecht = context.get("Geschlecht")
    if isinstance(provided_icds, str): provided_icds = [provided_icds]
    if isinstance(provided_gtins, str): provided_gtins = [provided_gtins]
    if isinstance(provided_lkns, str): provided_lkns = [provided_lkns]

    # Iteriere durch jede Bedingung
    for i, cond in enumerate(conditions):
        # Annahme: Schlüsselnamen in pauschale_bedingungen_data
        bedingungstyp = cond.get("Bedingungstyp", "").upper()
        werte_str = cond.get("Werte", "")
        werte_list = [w.strip() for w in str(werte_str).split(',') if w.strip()]
        tabelle_ref = cond.get("Tabelle")
        feld_ref = cond.get("Feld") # Für Patientenbedingungen
        min_val = cond.get("MinWert")
        max_val = cond.get("MaxWert")

        condition_met = False
        status_text = "NICHT geprüft"
        bedingung_text = f"Typ: {bedingungstyp}, Wert/Ref: '{werte_str or tabelle_ref or feld_ref or '-'}'"
        if feld_ref: bedingung_text = f"Typ: {bedingungstyp}, Feld: {feld_ref}, Wert: '{werte_str or str(min_val)+'-'+str(max_val)}'"


        try:
            if not werte_list and not tabelle_ref and not feld_ref:
                print(f"WARNUNG: Bedingung {i+1} für {pauschale_code} hat keine Werte/Tabelle/Feld.")
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
                 # Annahme: Schlüsselnamen in tabellen_data
                 codes_in_tabelle = [e.get("Code") for e in tabellen_data if e.get("Tabelle") == tabelle_ref and e.get("Tabelle_Typ") == "service_catalog" and e.get("Code")]
                 condition_met = any(code.upper() in (p_lkn.upper() for p_lkn in provided_lkns) for code in codes_in_tabelle)
                 bedingung_text += f" (Tabelle: {tabelle_ref})"
                 status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
            elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE":
                 # Annahme: Schlüsselnamen in tabellen_data
                 codes_in_tabelle = [e.get("Code") for e in tabellen_data if e.get("Tabelle") == tabelle_ref and e.get("Tabelle_Typ") == "icd" and e.get("Code")]
                 condition_met = any(code.upper() in (p_icd.upper() for p_icd in provided_icds) for code in codes_in_tabelle)
                 bedingung_text += f" (Tabelle: {tabelle_ref})"
                 status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
            elif bedingungstyp == "MEDIKAMENTE IN LISTE":
                 condition_met = any(req_gtin in provided_gtins for req_gtin in werte_list)
                 status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
            elif bedingungstyp == "PATIENTENBEDINGUNG":
                 wert_regel = cond.get("Wert") # Wert aus der Regel
                 wert_fall = context.get(feld_ref) # Wert aus dem Kontext holen

                 if wert_fall is None: condition_met = False; status_text = "NICHT erfüllt (Kontext fehlt)"
                 elif feld_ref == "Alter":
                     try:
                         alter_patient = int(wert_fall); alter_ok = True; range_parts = []
                         if min_val is not None and alter_patient < int(min_val): alter_ok = False; range_parts.append(f"min. {min_val}")
                         if max_val is not None and alter_patient > int(max_val): alter_ok = False; range_parts.append(f"max. {max_val}")
                         if wert_regel is not None and alter_patient != int(wert_regel): alter_ok = False; range_parts.append(f"exakt {wert_regel}")
                         condition_met = alter_ok; status_text = "Erfüllt" if condition_met else f"NICHT erfüllt ({' '.join(range_parts)})"
                     except (ValueError, TypeError): condition_met = False; status_text = "NICHT erfüllt (ungültiger Wert)"
                 elif feld_ref == "Geschlecht":
                     if isinstance(wert_regel, str) and isinstance(wert_fall, str): condition_met = wert_fall.lower() == wert_regel.lower(); status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
                     else: condition_met = False; status_text = "NICHT erfüllt (ungültiger Wert)"
                 elif feld_ref == "GTIN": # Prüft, ob *mindestens einer* der benötigten GTINs im Kontext ist
                     required_gtins_cond = [str(wert_regel)] if isinstance(wert_regel, (str, int)) else [str(w) for w in (wert_regel or [])]
                     condition_met = any(req in provided_gtins for req in required_gtins_cond); status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
                 else: print(f"WARNUNG: Unbekanntes Feld '{feld_ref}' für Patientenbedingung Pauschale {pauschale_code}."); condition_met = True; status_text = "Erfüllt (unbekanntes Feld)"
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