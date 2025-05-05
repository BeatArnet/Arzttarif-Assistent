# regelpruefer_pauschale.py (Version mit strukturierter Auswertung UND HTML-Generierung)

import json
from typing import Dict, List, Any
from utils import escape, get_table_content 
import re, html

# === FUNKTION ZUR PRÜFUNG EINER EINZELNEN BEDINGUNG ===
def check_single_condition(
    condition: Dict, # Ein einzelnes Bedingungs-Dictionary
    context: Dict,
    tabellen_dict_by_table: Dict[str, List[Dict]]
) -> bool:
    """Prüft eine einzelne Bedingungszeile und gibt True/False zurück."""
    print(f"DEBUG (check_single): Erhaltene Tabellen-Keys (Auszug): {list(tabellen_dict_by_table.keys())[:10]}")

    use_icd_check = context.get("useIcd", True) # Default: True
    # Schlüssel für Bedingungen - anpassen!
    BED_TYP_KEY = 'Bedingungstyp'
    BED_WERTE_KEY = 'Werte'
    BED_FELD_KEY = 'Feld'
    BED_MIN_KEY = 'MinWert'
    BED_MAX_KEY = 'MaxWert'

    bedingungstyp = condition.get(BED_TYP_KEY, "").upper()
    werte_str = condition.get(BED_WERTE_KEY, "")
    werte_list_upper = [w.strip().upper() for w in str(werte_str).split(',') if w.strip()]
    feld_ref = condition.get(BED_FELD_KEY)
    min_val = condition.get(BED_MIN_KEY)
    max_val = condition.get(BED_MAX_KEY)
    wert_regel = condition.get(BED_WERTE_KEY) # Wert aus Regel für Patientenbedingung

    # Kontext sicher holen
    provided_icds_upper = {p_icd.upper() for p_icd in context.get("ICD", []) if p_icd}
    provided_gtins = set(context.get("GTIN", []))
    provided_lkns_upper = {p_lkn.upper() for p_lkn in context.get("LKN", []) if p_lkn}
    provided_alter = context.get("Alter")
    provided_geschlecht = context.get("Geschlecht")

    try:
        if bedingungstyp == "ICD":
            if not use_icd_check:
                print("DEBUG (check_single): ICD-Prüfung übersprungen (Checkbox).")
                return True # Ignorieren -> Erfüllt
            # Prüfe, ob *mindestens einer* der geforderten ICDs im Kontext ist
            return any(req_icd in provided_icds_upper for req_icd in werte_list_upper)

        elif bedingungstyp == "GTIN" or bedingungstyp == "MEDIKAMENTE IN LISTE":
            werte_list_gtin = [w.strip() for w in str(werte_str).split(',') if w.strip()]
            # Prüfe, ob *mindestens einer* der geforderten GTINs im Kontext ist
            return any(req_gtin in provided_gtins for req_gtin in werte_list_gtin)

        elif bedingungstyp == "LKN" or bedingungstyp == "LEISTUNGSPOSITIONEN IN LISTE":
             # Prüfe, ob *mindestens einer* der geforderten LKNs im Kontext ist
            return any(req_lkn in provided_lkns_upper for req_lkn in werte_list_upper)

        elif bedingungstyp == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp == "TARIFPOSITIONEN IN TABELLE":
            table_ref = werte_str # Kann kommasepariert sein
            codes_in_tabelle = get_table_content(table_ref, "service_catalog", tabellen_dict_by_table)
            if not codes_in_tabelle: return False # Keine Codes in Tabelle(n) -> nicht erfüllt
            # Prüfe, ob *mindestens einer* der LKNs aus der/den Tabelle(n) im Kontext ist
            return any(entry['Code'].upper() in provided_lkns_upper for entry in codes_in_tabelle)

        elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE":
            if not use_icd_check:
                print("DEBUG (check_single): ICD-Tabellen-Prüfung übersprungen (Checkbox).")
                return True # Ignorieren -> Erfüllt
            table_ref = werte_str # Kann kommasepariert sein
            codes_in_tabelle = get_table_content(table_ref, "icd", tabellen_dict_by_table)
            if not codes_in_tabelle: return False # Keine Codes in Tabelle(n) -> nicht erfüllt
             # Prüfe, ob *mindestens einer* der ICDs aus der/den Tabelle(n) im Kontext ist
            return any(entry['Code'].upper() in provided_icds_upper for entry in codes_in_tabelle)

        elif bedingungstyp == "PATIENTENBEDINGUNG":
            wert_fall = context.get(feld_ref)
            if feld_ref == "Alter":
                if wert_fall is None: return False
                try:
                    alter_patient = int(wert_fall); alter_ok = True
                    if min_val is not None and alter_patient < int(min_val): alter_ok = False
                    if max_val is not None and alter_patient > int(max_val): alter_ok = False
                    if min_val is None and max_val is None and wert_regel is not None and alter_patient != int(wert_regel): alter_ok = False
                    return alter_ok
                except (ValueError, TypeError): return False
            elif feld_ref == "Geschlecht":
                 if isinstance(wert_fall, str) and isinstance(wert_regel, str):
                     return wert_fall.lower() == wert_regel.lower()
                 elif wert_fall is None and wert_regel is None:
                     return True
                 else:
                     return False
            else: # Unbekanntes Feld
                print(f"WARNUNG (check_single): Unbekanntes Feld '{feld_ref}' für Patientenbedingung.")
                return True # Unbekannt -> OK

        else: # Unbekannter Bedingungstyp
            print(f"WARNUNG (check_single): Unbekannter Pauschalen-Bedingungstyp '{bedingungstyp}'. Wird als False angenommen.")
            return False # Unbekannt -> NOK

    except Exception as e:
        print(f"FEHLER (check_single) bei Prüfung Einzelbedingung ({bedingungstyp}, {werte_str}): {e}")
        return False # Bei Fehler gilt Bedingung als nicht erfüllt

# === FUNKTION ZUR AUSWERTUNG DER STRUKTURIERTEN LOGIK (UND/ODER) ===
def evaluate_structured_conditions(
    pauschale_code: str,
    context: Dict,
    pauschale_bedingungen_data: List[Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]]
) -> bool:
    """
    Wertet die strukturierte UND/ODER-Logik aus.
    Berücksichtigt useIcd-Flag für ICD-Bedingungen.
    """
    PAUSCHALE_KEY = 'Pauschale'; GRUPPE_KEY = 'Gruppe'; OPERATOR_KEY = 'Operator'; BED_TYP_KEY = 'Bedingungstyp'
    use_icd_check = context.get("useIcd", True) # Hole Flag

    conditions = [cond for cond in pauschale_bedingungen_data if cond.get(PAUSCHALE_KEY) == pauschale_code]
    if not conditions: return True

    grouped_conditions: Dict[Any, List[Dict]] = {}
    for cond in conditions:
        gruppe = cond.get(GRUPPE_KEY)
        if gruppe is None: continue
        grouped_conditions.setdefault(gruppe, []).append(cond)
    if not grouped_conditions: return True

    overall_result = False
    print(f"DEBUG (evaluate): Prüfe {len(grouped_conditions)} Gruppen für {pauschale_code} (useIcd={use_icd_check})")
    for gruppe, conditions_in_group in grouped_conditions.items():
        if not conditions_in_group: continue
        group_operator = conditions_in_group[0].get(OPERATOR_KEY, 'UND').upper()
        if group_operator not in ['UND', 'ODER']: group_operator = 'UND'

        group_met = False
        results_in_group = []
        non_icd_results_in_group = [] # Ergebnisse ohne ICD-Bedingungen

        for cond in conditions_in_group:
            cond_type = cond.get(BED_TYP_KEY, "").upper()
            is_icd_condition = "ICD" in cond_type or "DIAGNOSE" in cond_type

            # Prüfe die Einzelbedingung (berücksichtigt use_icd_check intern)
            single_result = check_single_condition(cond, context, tabellen_dict_by_table)
            results_in_group.append(single_result)

            # Sammle Ergebnisse der Nicht-ICD-Bedingungen separat
            if not is_icd_condition:
                non_icd_results_in_group.append(single_result)

        # Werte die Gruppe aus
        if group_operator == 'UND':
            # Alle Bedingungen (inkl. evtl. ignorierter ICDs) müssen True sein
            group_met = all(results_in_group)
        elif group_operator == 'ODER':
            # Mindestens eine Bedingung muss True sein.
            # Wenn ICDs ignoriert werden, prüfen wir zusätzlich, ob mindestens
            # eine *Nicht-ICD*-Bedingung erfüllt ist, um zu verhindern, dass
            # die Gruppe nur wegen ignorierter ICDs True wird.
            group_met = any(results_in_group)
            # if not use_icd_check:
            #      group_met = any(results_in_group) and any(non_icd_results_in_group)
            # else:
            #      group_met = any(results_in_group)

        print(f"DEBUG (evaluate): Gruppe {gruppe} (Op: {group_operator}): Einzel={results_in_group}, NonICD={non_icd_results_in_group if not use_icd_check and group_operator=='ODER' else 'N/A'}, GruppenErgebnis={group_met}")

        if group_met:
            overall_result = True
            print(f"DEBUG (evaluate): Gruppe {gruppe} erfüllt, Gesamtergebnis für {pauschale_code} ist True.")
            break

    print(f"DEBUG (evaluate): FINALES Ergebnis für {pauschale_code}: {overall_result}")
    return overall_result

# === FUNKTION ZUR HTML-GENERIERUNG DER BEDINGUNGSPRÜFUNG (für die Anzeige) ===
def check_pauschale_conditions(
    pauschale_code: str,
    context: dict,
    pauschale_bedingungen_data: list[dict],
    tabellen_dict_by_table: Dict[str, List[Dict]]
) -> dict:
    """
    Prüft die Bedingungen für eine gegebene Pauschale deterministisch.
    Generiert detailliertes HTML inkl. klickbarer Tabellenreferenzen für die Anzeige.
    Gibt auch den LKN-Trigger-Status zurück.
    """
    errors: list[str] = []
    condition_details_html: str = "<ul>"
    all_met_overall = True # Wird nicht mehr für die Auswahl verwendet, nur für Info
    trigger_lkn_condition_met = False # Wurde irgendeine LKN-Bedingung erfüllt?

    # Schlüsseldefinitionen...
    PAUSCHALE_KEY_IN_BEDINGUNGEN = 'Pauschale'
    BED_TYP_KEY = 'Bedingungstyp'
    BED_WERTE_KEY = 'Werte'
    BED_FELD_KEY = 'Feld'
    BED_MIN_KEY = 'MinWert'
    BED_MAX_KEY = 'MaxWert'

    conditions = [cond for cond in pauschale_bedingungen_data if cond.get(PAUSCHALE_KEY_IN_BEDINGUNGEN) == pauschale_code]

    if not conditions:
        condition_details_html += "<li>Keine spezifischen Bedingungen gefunden.</li></ul>"
        # allMet ist hier True, da keine Bedingungen verletzt wurden
        return {"html": condition_details_html, "errors": [], "trigger_lkn_condition_met": False}

    print(f"--- DEBUG [check_pauschale_conditions HTML]: Starte Prüfung für {pauschale_code} ---")
    # Kontext nur einmal holen
    provided_icds_upper = {p_icd.upper() for p_icd in context.get("ICD", []) if p_icd}
    provided_gtins = set(context.get("GTIN", []))
    provided_lkns_upper = {p_lkn.upper() for p_lkn in context.get("LKN", []) if p_lkn}
    provided_alter = context.get("Alter")
    provided_geschlecht = context.get("Geschlecht")

    for i, cond in enumerate(conditions):
        bedingungstyp = cond.get(BED_TYP_KEY, "").upper()
        werte_str = cond.get(BED_WERTE_KEY, "")
        feld_ref = cond.get(BED_FELD_KEY)

        # Prüfe diese einzelne Bedingung mit der Hilfsfunktion
        # Wichtig: Der Kontext wird hier korrekt übergeben
        condition_met_this_line = check_single_condition(cond, context, tabellen_dict_by_table)

        # Setze Status und Beschreibung für HTML
        status_text = "Erfüllt" if condition_met_this_line else "NICHT erfüllt"
        li_content = f"<li>Bedingung {i+1}: {escape(bedingungstyp)}"
        details_fuer_bedingung = ""
        bedingung_beschreibung = ""
        is_lkn_condition = False

        # Generiere Beschreibung und Details für HTML
        try:
            if bedingungstyp == "ICD":
                bedingung_beschreibung = f" - Erfordert ICD: {escape(werte_str)}"
            elif bedingungstyp == "GTIN" or bedingungstyp == "MEDIKAMENTE IN LISTE":
                bedingung_beschreibung = f" - Erfordert GTIN/Medikament: {escape(werte_str)}"
            elif bedingungstyp == "LKN" or bedingungstyp == "LEISTUNGSPOSITIONEN IN LISTE":
                bedingung_beschreibung = f" - Erfordert LKN: {escape(werte_str)}"
                is_lkn_condition = True
            elif bedingungstyp == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp == "TARIFPOSITIONEN IN TABELLE":
                bedingung_beschreibung = f" - Erfordert LKN aus "
                is_lkn_condition = True
                table_names = [t.strip() for t in werte_str.split(',') if t.strip()]
                all_content = []; valid_table_names = []
                for table_name in table_names:
                    table_content = get_table_content(table_name, "service_catalog", tabellen_dict_by_table)
                    if table_content: all_content.extend(table_content); valid_table_names.append(table_name)
                if all_content:
                    sorted_content = sorted({item['Code']: item for item in all_content}.values(), key=lambda x: x['Code'])
                    table_links = ", ".join([f"'{escape(t)}'" for t in valid_table_names])
                    details_fuer_bedingung += f"<details class='inline-details' style='display: inline-block; margin-left: 5px; vertical-align: middle;'><summary style='display: inline; cursor: pointer; color: blue; text-decoration: underline;'>Tabelle(n): {table_links}</summary><div style='margin-top: 5px; border: 1px solid #eee; padding: 5px; background: #f9f9f9;'><ul>"
                    for item in sorted_content: details_fuer_bedingung += f"<li><b>{escape(item['Code'])}</b>: {escape(item['Code_Text'])}</li>"
                    details_fuer_bedingung += "</ul></div></details>"
                elif table_names: bedingung_beschreibung += f" Tabelle(n): {escape(werte_str)} (leer oder nicht gefunden)"
                else: bedingung_beschreibung += " Tabelle: (Keine Angabe)"
            elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE":
                bedingung_beschreibung = f" - Erfordert ICD aus "
                table_names = [t.strip() for t in werte_str.split(',') if t.strip()]
                all_content = []; valid_table_names = []
                for table_name in table_names:
                    table_content = get_table_content(table_name, "icd", tabellen_dict_by_table)
                    if table_content: all_content.extend(table_content); valid_table_names.append(table_name)
                if all_content:
                    sorted_content = sorted({item['Code']: item for item in all_content}.values(), key=lambda x: x['Code'])
                    table_links = ", ".join([f"'{escape(t)}'" for t in valid_table_names])
                    details_fuer_bedingung += f"<details class='inline-details' style='display: inline-block; margin-left: 5px; vertical-align: middle;'><summary style='display: inline; cursor: pointer; color: blue; text-decoration: underline;'>Tabelle(n): {table_links}</summary><div style='margin-top: 5px; border: 1px solid #eee; padding: 5px; background: #f9f9f9;'><ul>"
                    for item in sorted_content: details_fuer_bedingung += f"<li><b>{escape(item['Code'])}</b>: {escape(item['Code_Text'])}</li>"
                    details_fuer_bedingung += "</ul></div></details>"
                elif table_names: bedingung_beschreibung += f" Tabelle(n): {escape(werte_str)} (leer oder nicht gefunden)"
                else: bedingung_beschreibung += " Tabelle: (Keine Angabe)"
            elif bedingungstyp == "PATIENTENBEDINGUNG":
                 min_val = cond.get(BED_MIN_KEY); max_val = cond.get(BED_MAX_KEY); wert_regel = cond.get(BED_WERTE_KEY)
                 bedingung_beschreibung = f" - Patientenbedingung: Feld='{escape(feld_ref)}'"
                 if feld_ref == "Alter": bedingung_beschreibung += f", Bereich/Wert='{min_val or '-'} bis {max_val or '-'} / {wert_regel or '-'}'"
                 elif feld_ref == "Geschlecht": bedingung_beschreibung += f", Erwartet='{escape(wert_regel)}'"
            elif bedingungstyp == "GESCHLECHT IN LISTE": # Beschreibung für HTML
                 bedingung_beschreibung = f" - Geschlecht in Liste: {escape(werte_str)}"
            else: # Unbekannter Typ
                 bedingung_beschreibung = f" - Wert/Ref: {escape(werte_str or feld_ref or '-')}"

            # Aktualisiere trigger_lkn_condition_met (nur für Rückgabewert)
            if is_lkn_condition and condition_met_this_line:
                trigger_lkn_condition_met = True

        except Exception as e_html: # Fehler bei HTML-Generierung abfangen
             print(f"FEHLER bei HTML-Generierung für Bedingung {i+1} ({pauschale_code}): {e_html}")
             bedingung_beschreibung = f" - FEHLER bei Detailgenerierung: {escape(str(e_html))}"
             status_text = "FEHLER" # Status auf Fehler setzen

        # Füge Listeneintrag zum HTML hinzu
        color = "green" if condition_met_this_line else "red" if not status_text.startswith("FEHLER") else "orange"
        li_content += bedingung_beschreibung
        # Füge Details nur hinzu, wenn sie nicht schon Teil der Beschreibung sind (für Tabellen)
        if not ("IN TABELLE" in bedingungstyp and details_fuer_bedingung):
             li_content += details_fuer_bedingung # Füge Tabellen-Details hinzu, falls vorhanden
        li_content += f': <span style="color:{color}; font-weight:bold;">{status_text}</span></li>'
        condition_details_html += li_content

        # Aktualisiere Gesamtstatus und Fehlerliste
        if not condition_met_this_line:
            all_met_overall = False # Wenn eine Zeile nicht erfüllt ist, ist nicht alles erfüllt
            if not status_text.startswith("FEHLER"):
                 errors.append(f"Bedingung {i+1}: {escape(bedingungstyp)}{bedingung_beschreibung}")
            else: # Füge auch explizite Fehler hinzu
                 errors.append(f"Fehler bei Prüfung Bedingung {i+1}: {status_text.replace('FEHLER bei Prüfung: ','')}")

    condition_details_html += "</ul>"
    print(f"--- DEBUG [check_pauschale_conditions HTML]: Abschluss Prüfung für {pauschale_code}: allMetOverall={all_met_overall}, triggerLKNMet={trigger_lkn_condition_met} ---")

    # Gibt jetzt kein 'allMet' mehr zurück, da dies durch evaluate_structured_conditions bestimmt wird
    return {
        "html": condition_details_html,
        "errors": errors,
        "trigger_lkn_condition_met": trigger_lkn_condition_met
    }

# --- HILFSFUNKTIONEN (auf Modulebene) ---
def get_simplified_conditions(pauschale_code: str, bedingungen_data: list[dict]) -> set:
    """ Wandelt Bedingungen in eine strukturiertere, vergleichbare Darstellung um. """
    simplified_set = set()
    PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'
    BED_FELD_KEY = 'Feld'; BED_MIN_KEY = 'MinWert'; BED_MAX_KEY = 'MaxWert'
    pauschale_conditions = [cond for cond in bedingungen_data if cond.get(PAUSCHALE_KEY) == pauschale_code]
    for cond in pauschale_conditions:
        typ = cond.get(BED_TYP_KEY, "").upper(); wert = cond.get(BED_WERTE_KEY, ""); feld = cond.get(BED_FELD_KEY, "")
        condition_tuple = None
        if "IN TABELLE" in typ: condition_tuple = (typ.replace("LEISTUNGSPOSITIONEN", "LKN").replace("HAUPTDIAGNOSE","ICD").replace("TARIFPOSITIONEN","LKN"), wert) # Typ vereinfachen
        elif "IN LISTE" in typ: condition_tuple = (typ.replace("LEISTUNGSPOSITIONEN", "LKN").replace("MEDIKAMENTE","GTIN"), wert)
        elif typ == "ICD": condition_tuple = ('ICD_LIST', wert)
        elif typ == "GTIN": condition_tuple = ('GTIN_LIST', wert)
        elif typ == "LKN": condition_tuple = ('LKN_LIST', wert)
        elif typ == "PATIENTENBEDINGUNG" and feld:
             if cond.get(BED_MIN_KEY) is not None or cond.get(BED_MAX_KEY) is not None:
                 bereich_text = f"({cond.get(BED_MIN_KEY, '-')}-{cond.get(BED_MAX_KEY, '-')})"
                 condition_tuple = ('PATIENT', f"{feld} {bereich_text}")
             else: condition_tuple = ('PATIENT', f"{feld}={wert}")
        if condition_tuple: simplified_set.add(condition_tuple)
    return simplified_set


def generate_condition_detail_html(
    condition_tuple: tuple,
    leistungskatalog_dict: Dict, # Benötigt für LKN-Beschreibungen
    tabellen_dict_by_table: Dict # Benötigt für Tabelleninhalte
    ) -> str:
    """Generiert HTML für eine einzelne strukturierte Bedingung mit aufklappbaren Details."""

    cond_type, cond_value = condition_tuple
    condition_html = "<li>"
    nested_details_html = ""
    description = f"{cond_type}: {html.escape(str(cond_value))}"
    try:
        if cond_type == 'LKN_LIST':
            description = f"Erfordert LKN aus Liste: {html.escape(cond_value)}"
            lkns = [lkn.strip() for lkn in cond_value.split(',') if lkn.strip()]
            if lkns:
                nested_details_html += f"<details style='margin-left: 25px; font-size: 0.9em;'><summary>Zeige {len(lkns)} LKN(s)</summary><ul>"
                for lkn in lkns: desc = leistungskatalog_dict.get(lkn, {}).get('Beschreibung', 'Beschreibung nicht gefunden'); nested_details_html += f"<li><b>{html.escape(lkn)}</b>: {html.escape(desc)}</li>"
                nested_details_html += "</ul></details>"
        elif cond_type == 'LKN_TABLE':
            description = "Erfordert LKN aus "
            table_names = [t.strip() for t in cond_value.split(',') if t.strip()]
            all_content = []; valid_table_names = []
            for table_name in table_names:
                table_content = get_table_content(table_name, "service_catalog", tabellen_dict_by_table)
                if table_content: all_content.extend(table_content); valid_table_names.append(table_name)
            if all_content:
                 sorted_content = sorted({item['Code']: item for item in all_content}.values(), key=lambda x: x['Code'])
                 table_links = ", ".join([f"'{html.escape(t)}'" for t in valid_table_names])
                 nested_details_html += f"<details class='inline-details' style='display: inline-block; margin-left: 5px; vertical-align: middle;'><summary style='display: inline; cursor: pointer; color: blue; text-decoration: underline;'>Tabelle(n): {table_links}</summary><div style='margin-top: 5px; border: 1px solid #eee; padding: 5px; background: #f9f9f9;'><ul>"
                 for item in sorted_content: nested_details_html += f"<li><b>{html.escape(item['Code'])}</b>: {html.escape(item['Code_Text'])}</li>"
                 nested_details_html += "</ul></div></details>"
                 description += nested_details_html
            elif table_names: description += f" Tabelle(n): {html.escape(cond_value)} (leer oder nicht gefunden)"
            else: description += " Tabelle: (Keine Angabe)"
        elif cond_type == 'ICD_TABLE':
            description = "Erfordert ICD aus "
            table_names = [t.strip() for t in cond_value.split(',') if t.strip()]
            all_content = []; valid_table_names = []
            for table_name in table_names:
                table_content = get_table_content(table_name, "icd", tabellen_dict_by_table)
                if table_content: all_content.extend(table_content); valid_table_names.append(table_name)
            if all_content:
                 sorted_content = sorted({item['Code']: item for item in all_content}.values(), key=lambda x: x['Code'])
                 table_links = ", ".join([f"'{html.escape(t)}'" for t in valid_table_names])
                 nested_details_html += f"<details class='inline-details' style='display: inline-block; margin-left: 5px; vertical-align: middle;'><summary style='display: inline; cursor: pointer; color: blue; text-decoration: underline;'>Tabelle(n): {table_links}</summary><div style='margin-top: 5px; border: 1px solid #eee; padding: 5px; background: #f9f9f9;'><ul>"
                 for item in sorted_content: nested_details_html += f"<li><b>{html.escape(item['Code'])}</b>: {html.escape(item['Code_Text'])}</li>"
                 nested_details_html += "</ul></div></details>"
                 description += nested_details_html
            elif table_names: description += f" Tabelle(n): {html.escape(cond_value)} (leer oder nicht gefunden)"
            else: description += " Tabelle: (Keine Angabe)"
        elif cond_type == 'ICD_LIST': description = f"Erfordert ICD aus Liste: {html.escape(cond_value)}"
        elif cond_type == 'GTIN_LIST': description = f"Erfordert GTIN aus Liste: {html.escape(cond_value)}"
        elif cond_type == 'PATIENT': description = f"Patientenbedingung: {html.escape(cond_value)}"
        condition_html += description
    except Exception as e_detail: print(f"FEHLER beim Erstellen der Detailansicht für Bedingung '{condition_tuple}': {e_detail}"); condition_html += f"FEHLER bei Detailgenerierung: {html.escape(str(e_detail))}"
    condition_html += "</li>"
    return condition_html
