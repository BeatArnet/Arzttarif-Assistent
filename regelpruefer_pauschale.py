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
            if not use_icd_check:
                 group_met = any(results_in_group) and any(non_icd_results_in_group)
            else:
                 group_met = any(results_in_group)


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

# --- Ausgelagerte Pauschalen-Ermittlung ---
def determine_applicable_pauschale(
    user_input: str,
    rule_checked_leistungen: list[dict],
    context: dict,
    # Benötigte Daten als Argumente übergeben
    pauschale_lp_data: List[Dict],
    pauschale_bedingungen_data: List[Dict],
    pauschalen_dict: Dict[str, Dict],
    leistungskatalog_dict: Dict[str, Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]]
    ) -> dict:
    """
    Ermittelt die anwendbarste Pauschale durch Auswertung der strukturierten Bedingungen.
    Wählt die niedrigste gültige aus (A vor B vor E...).
    Gibt entweder die Pauschale oder einen Error zurück.
    """
    print("INFO: Starte Pauschalenermittlung mit strukturierter Bedingungsprüfung...")

    # Schlüssel und globale Variablen...
    PAUSCHALE_ERKLAERUNG_KEY = 'pauschale_erklaerung_html'
    POTENTIAL_ICDS_KEY = 'potential_icds'
    LKN_KEY_IN_RULE_CHECKED = 'lkn'
    PAUSCHALE_KEY_IN_PAUSCHALEN = 'Pauschale'
    PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN = 'Pauschale_Text'
    LP_LKN_KEY = 'Leistungsposition'; LP_PAUSCHALE_KEY = 'Pauschale'
    BED_PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'
    TAB_CODE_KEY = 'Code'; TAB_TYP_KEY = 'Tabelle_Typ'; TAB_TABELLE_KEY = 'Tabelle'

    # 1. Finde potenzielle Pauschalen
    potential_pauschale_codes = set()
    rule_checked_lkns = [l.get(LKN_KEY_IN_RULE_CHECKED) for l in rule_checked_leistungen if l.get(LKN_KEY_IN_RULE_CHECKED)]
    print(f"DEBUG: Regelkonforme LKNs für Pauschalen-Suche: {rule_checked_lkns}")
    lkns_in_tables = {}
    for lkn in rule_checked_lkns:
        # print(f"DEBUG: Suche Pauschalen für LKN: {lkn}") # Optional
        found_via_a = False; found_via_b = False; found_via_c = False
        # Methode a)
        for item in pauschale_lp_data:
            if item.get(LP_LKN_KEY) == lkn:
                pauschale_code_a = item.get(LP_PAUSCHALE_KEY)
                if pauschale_code_a and pauschale_code_a in pauschalen_dict: potential_pauschale_codes.add(pauschale_code_a); found_via_a = True
        # if found_via_a: print(f"DEBUG: Pauschalen via Methode A für {lkn} hinzugefügt: {potential_pauschale_codes}") # Optional
        # Methode b)
        for cond in pauschale_bedingungen_data:
            if cond.get(BED_TYP_KEY) == "LEISTUNGSPOSITIONEN IN LISTE":
                werte_liste = [w.strip() for w in str(cond.get(BED_WERTE_KEY, "")).split(',') if w.strip()]
                if lkn in werte_liste:
                    pauschale_code_b = cond.get(BED_PAUSCHALE_KEY)
                    if pauschale_code_b and pauschale_code_b in pauschalen_dict: potential_pauschale_codes.add(pauschale_code_b); found_via_b = True
        # if found_via_b: print(f"DEBUG: Pauschalen via Methode B für {lkn} hinzugefügt: {potential_pauschale_codes}") # Optional
        # Methode c)
        if lkn not in lkns_in_tables:
             tables_for_lkn = set()
             for table_name_key in tabellen_dict_by_table.keys():
                  for entry in tabellen_dict_by_table[table_name_key]:
                       if entry.get(TAB_CODE_KEY) == lkn and entry.get(TAB_TYP_KEY) == "service_catalog": tables_for_lkn.add(table_name_key)
             lkns_in_tables[lkn] = tables_for_lkn
             # print(f"DEBUG: LKN {lkn} gefunden in normalisierten Tabellen (Set): {lkns_in_tables[lkn]}") # Optional
        tables_for_current_lkn_normalized = lkns_in_tables.get(lkn, set())
        if tables_for_current_lkn_normalized:
            for cond in pauschale_bedingungen_data:
                if cond.get(BED_TYP_KEY) == "LEISTUNGSPOSITIONEN IN TABELLE":
                    table_ref_in_cond_str = cond.get(BED_WERTE_KEY, "")
                    pauschale_code_c = cond.get(BED_PAUSCHALE_KEY)
                    condition_tables_normalized = {t.strip().lower() for t in table_ref_in_cond_str.split(',') if t.strip()}
                    if not condition_tables_normalized.isdisjoint(tables_for_current_lkn_normalized):
                        # print(f"DEBUG: Match! LKN-Tabellen {tables_for_current_lkn_normalized} überschneiden sich mit Bedingungs-Tabellen {condition_tables_normalized} für Pauschale {pauschale_code_c}") # Optional
                        if pauschale_code_c and pauschale_code_c in pauschalen_dict: potential_pauschale_codes.add(pauschale_code_c); found_via_c = True
        # if found_via_c: print(f"DEBUG: Pauschalen via Methode C für {lkn} hinzugefügt: {potential_pauschale_codes}") # Optional

    print(f"DEBUG: Finale potenzielle Pauschalen nach Schleife: {potential_pauschale_codes}")

    if not potential_pauschale_codes:
        print("INFO: Keine potenziellen Pauschalen-Codes für die erbrachten Leistungen gefunden.")
        return {"type": "Error", "message": "Keine passende Pauschale für die erbrachten Leistungen gefunden."}

    # 2. Werte die strukturierte Logik für ALLE potenziellen Kandidaten aus
    evaluated_candidates = []
    print(f"INFO: Werte strukturierte Bedingungen für {len(potential_pauschale_codes)} potenzielle Pauschalen aus...")
    for code in potential_pauschale_codes:
        if code not in pauschalen_dict: continue
        bedingungs_context = context # Enthält bereits useIcd
        is_pauschale_valid = False
        try:
            is_pauschale_valid = evaluate_structured_conditions( # Direkter Aufruf
                code,
                bedingungs_context,
                pauschale_bedingungen_data,
                tabellen_dict_by_table
            )
        except Exception as e_eval:
             print(f"FEHLER bei evaluate_structured_conditions für {code}: {e_eval}")
             is_pauschale_valid = False
        print(f"DEBUG: Strukturierte Prüfung für {code}: Gültig = {is_pauschale_valid}")
        evaluated_candidates.append({"code": code, "details": pauschalen_dict[code], "is_valid_structured": is_pauschale_valid})

    # 3. Filtere die Kandidaten, die die strukturierte Prüfung bestanden haben
    valid_candidates = [cand for cand in evaluated_candidates if cand["is_valid_structured"]]
    print(f"DEBUG: Struktur-gültige Kandidaten nach Prüfung: {[c['code'] for c in valid_candidates]}")

    # 4. Wähle die beste Pauschale aus den STRUKTURIELL GÜLTIGEN Kandidaten
    selected_candidate_info = None
    if valid_candidates:
        # --- NEUE AUSWAHL-LOGIK: Spezifischste (A vor B) ---
        # Trenne spezifische und Fallback-Pauschalen
        specific_valid = [c for c in valid_candidates if not c['code'].startswith('C9')]
        fallback_valid = [c for c in valid_candidates if c['code'].startswith('C9')]

        if specific_valid:
            # Priorisiere spezifische Pauschalen: Wähle die "spezifischste" (niedrigster Buchstabe)
            specific_valid.sort(key=lambda x: x['code'], reverse=False) # A vor B vor E
            selected_candidate_info = specific_valid[0]
            print(f"INFO: Spezifischste Pauschale ausgewählt (A-Z Sortierung), deren strukturierte Bedingungen erfüllt sind: {selected_candidate_info['code']}")
        elif fallback_valid:
            # Nur wenn keine spezifische passt, nimm die "spezifischste" Fallback-Pauschale
            fallback_valid.sort(key=lambda x: x['code'], reverse=False) # C90 vor C99? Oder höchste Nummer? Hier A-Z
            selected_candidate_info = fallback_valid[0]
            print(f"INFO: Spezifischste Fallback-Pauschale ausgewählt (A-Z Sortierung), deren strukturierte Bedingungen erfüllt sind: {selected_candidate_info['code']}")
        else:
             print("FEHLER: Gültige Kandidaten gefunden, aber weder spezifisch noch Fallback?") # Sollte nicht passieren
             return {"type": "Error", "message": "Interner Fehler bei der Pauschalenauswahl."}
        # --- ENDE NEUE AUSWAHL-LOGIK ---

    else:
        # Fallback: Keine Pauschale erfüllt die strukturierte Logik
        print("INFO: Keine Pauschale erfüllt die strukturierten Bedingungen.")
        return {"type": "Error", "message": "Keine Pauschale gefunden, deren UND/ODER-Bedingungen vollständig erfüllt sind (Kontext prüfen!)."}

    # --- Ab hier verwenden wir selected_candidate_info ---
    best_pauschale_code = selected_candidate_info["code"]
    best_pauschale_details = selected_candidate_info["details"].copy()

    # 5. Generiere das Detail-HTML für die ausgewählte Pauschale
    bedingungs_pruef_html_result = "<p><i>Detail-HTML nicht generiert.</i></p>"
    condition_errors = []
    bedingungs_context_html = context # Enthält useIcd
    try:
        # Direkter Aufruf der Funktion im selben Modul
        condition_result_html = check_pauschale_conditions(
            best_pauschale_code,
            bedingungs_context_html,
            pauschale_bedingungen_data,
            tabellen_dict_by_table
        )
        bedingungs_pruef_html_result = condition_result_html.get("html", "<p class='error'>Fehler bei HTML-Generierung.</p>")
        condition_errors = condition_result_html.get("errors", [])
        # trigger_lkn_met = condition_result_html.get("trigger_lkn_condition_met", False) # Optional holen
    except Exception as e_html_gen:
         print(f"FEHLER bei check_pauschale_conditions (HTML-Generierung) für {best_pauschale_code}: {e_html_gen}")
         bedingungs_pruef_html_result = f"<p class='error'>Fehler bei HTML-Generierung: {e_html_gen}</p>"
         condition_errors = [f"Fehler HTML-Generierung: {e_html_gen}"]

    # 6. Pauschalen-Begründung erstellen
    rule_checked_lkns_str_list = [str(lkn) for lkn in rule_checked_lkns if lkn]
    pauschale_erklaerung_html = "<p>Folgende Pauschalen wurden basierend auf den regelkonformen Leistungen ({}) geprüft:</p>".format(", ".join(rule_checked_lkns_str_list) or "keine")
    pauschale_erklaerung_html += "<p>Folgende Pauschalen erfüllten die strukturierten UND/ODER Bedingungen:</p><ul>"
    for cand in sorted(valid_candidates, key=lambda x: x['code']): # Sortiere A-Z für die Anzeige
         pauschale_text = cand["details"].get(PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, 'N/A')
         pauschale_erklaerung_html += f"<li><b>{cand['code']}</b>: {pauschale_text}</li>"
    pauschale_erklaerung_html += "</ul>"
    pauschale_erklaerung_html += f"<p><b>Ausgewählt wurde: {best_pauschale_code}</b> ({best_pauschale_details.get(PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, 'N/A')}) - als <b>erste (spezifischste)</b> Pauschale (A-Z Sortierung), deren strukturierte Bedingungen erfüllt sind.</p>"

    # 7. Vergleich mit anderen Pauschalen
    match = re.match(r"([A-Z0-9.]+)[A-Z]$", best_pauschale_code)
    pauschalen_gruppe = match.group(1) if match else None
    if pauschalen_gruppe:
        all_candidates_in_group = [
            cand_code for cand_code in potential_pauschale_codes
            if cand_code.startswith(pauschalen_gruppe) and cand_code != best_pauschale_code and cand_code in pauschalen_dict
        ]
        if all_candidates_in_group:
             pauschale_erklaerung_html += "<hr><p><b>Vergleich mit anderen Pauschalen der Gruppe '{}':</b></p>".format(pauschalen_gruppe)
             selected_conditions_repr = get_simplified_conditions(best_pauschale_code, pauschale_bedingungen_data)
             for other_code in sorted(all_candidates_in_group):
                  other_details = pauschalen_dict[other_code]
                  other_conditions_repr = get_simplified_conditions(other_code, pauschale_bedingungen_data)
                  additional_conditions = other_conditions_repr - selected_conditions_repr
                  missing_conditions = selected_conditions_repr - other_conditions_repr

                  pauschale_erklaerung_html += f"<details style='margin-left: 15px; font-size: 0.9em;'><summary>Unterschiede zu <b>{other_code}</b> ({other_details.get(PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, 'N/A')})</summary>"
                  if additional_conditions:
                      pauschale_erklaerung_html += "<p>Zusätzliche/Andere Anforderungen für {}:</p><ul>".format(other_code)
                      for cond_tuple in sorted(list(additional_conditions)):
                            condition_html = generate_condition_detail_html(cond_tuple, leistungskatalog_dict, tabellen_dict_by_table)
                            pauschale_erklaerung_html += condition_html
                      pauschale_erklaerung_html += "</ul>"
                  if missing_conditions:
                     pauschale_erklaerung_html += "<p>Folgende Anforderungen von {} fehlen bei {}:</p><ul>".format(best_pauschale_code, other_code)
                     for cond_tuple in sorted(list(missing_conditions)):
                         condition_html = generate_condition_detail_html(cond_tuple, leistungskatalog_dict, tabellen_dict_by_table)
                         pauschale_erklaerung_html += condition_html
                     pauschale_erklaerung_html += "</ul>"
                  if not additional_conditions and not missing_conditions:
                     pauschale_erklaerung_html += "<p><i>Keine unterschiedlichen Bedingungen gefunden (basierend auf vereinfachter Prüfung).</i></p>"
                  pauschale_erklaerung_html += "</details>"
    best_pauschale_details[PAUSCHALE_ERKLAERUNG_KEY] = pauschale_erklaerung_html

    # 8. Potenzielle ICDs ermitteln
    potential_icds = []
    pauschale_conditions_selected = [cond for cond in pauschale_bedingungen_data if cond.get(BED_PAUSCHALE_KEY) == best_pauschale_code]
    for cond in pauschale_conditions_selected:
        if cond.get(BED_TYP_KEY) == "HAUPTDIAGNOSE IN TABELLE":
            tabelle_ref = cond.get(BED_WERTE_KEY)
            if tabelle_ref:
                icd_entries = get_table_content(tabelle_ref, "icd", tabellen_dict_by_table)
                for entry in icd_entries:
                    code = entry.get('Code'); text = entry.get('Code_Text')
                    if code: potential_icds.append({"Code": code, "Code_Text": text or "N/A"})
    unique_icds_dict = {icd['Code']: icd for icd in potential_icds if icd.get('Code')}
    sorted_unique_icds = sorted(unique_icds_dict.values(), key=lambda x: x['Code'])
    best_pauschale_details[POTENTIAL_ICDS_KEY] = sorted_unique_icds

    # 9. Finale Pauschalen-Antwort erstellen
    final_result = {
        "type": "Pauschale",
        "details": best_pauschale_details,
        "bedingungs_pruef_html": bedingungs_pruef_html_result,
        "bedingungs_fehler": condition_errors,
        "conditions_met": True # Da wir nur struktur-gültige auswählen
    }
    return final_result

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
