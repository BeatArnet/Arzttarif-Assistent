# regelpruefer_pauschale.py (Version mit strukturierter Auswertung UND HTML-Generierung)
import traceback
import json
from typing import Dict, List, Any
from utils import escape, get_table_content 
import re, html

# === FUNKTION ZUR PRÜFUNG EINER EINZELNEN BEDINGUNG ===
def check_single_condition(
    condition: Dict,
    context: Dict,
    tabellen_dict_by_table: Dict[str, List[Dict]]
) -> bool:
    """Prüft eine einzelne Bedingungszeile und gibt True/False zurück."""

    # Dieses Flag steuert, ob ICD-Bedingungen ÜBERHAUPT GEPRÜFT werden.
    # Wenn False, werden ICD-Bedingungen als "erfüllt" (True) betrachtet.
    # Wenn True, erfolgt eine spezifische Prüfung.
    check_icd_conditions_at_all = context.get("useIcd", True)

    BED_TYP_KEY = 'Bedingungstyp'
    BED_WERTE_KEY = 'Werte'
    # ... (andere Schlüsseldefinitionen)

    bedingungstyp = condition.get(BED_TYP_KEY, "").upper()
    werte_str = condition.get(BED_WERTE_KEY, "")
    # ... (andere Variableninitialisierungen)

    provided_icds_upper = {p_icd.upper() for p_icd in context.get("ICD", []) if p_icd}
    # ... (andere Kontextvariablen)

    try:
        if bedingungstyp == "ICD": # ICD IN LISTE
            if not check_icd_conditions_at_all: # Wenn useIcd=False
                # print(f"DEBUG (check_single): ICD-Listen-Bedingung '{werte_str}' ignoriert (useIcd=False).")
                return True # Bedingung ignorieren -> Erfüllt
            
            # Strikte Prüfung, wenn check_icd_conditions_at_all = True:
            # Ist mindestens einer der *im Kontext vorhandenen ICDs* in der *in der Regel definierten Liste*?
            # ODER umgekehrt: Ist mindestens einer der *in der Regel definierten ICDs* im *Kontext*?
            # Die zweite Variante ist üblicher: Die Regel gibt vor, was da sein muss.
            required_icds_in_rule_list = {w.strip().upper() for w in str(werte_str).split(',') if w.strip()}
            if not required_icds_in_rule_list: # Wenn die Regel keine ICDs vorgibt
                # print(f"DEBUG (check_single): ICD-Listen-Bedingung '{werte_str}' ist leer, gilt als erfüllt.")
                return True # Keine spezifische Anforderung
            # print(f"DEBUG (check_single): ICD-Listen-Prüfung: Regel fordert {required_icds_in_rule_list}, Kontext hat {provided_icds_upper}")
            return any(req_icd in provided_icds_upper for req_icd in required_icds_in_rule_list)

        elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE": # ICD IN TABELLE
            if not check_icd_conditions_at_all: # Wenn useIcd=False
                # print(f"DEBUG (check_single): ICD-Tabellen-Bedingung '{werte_str}' ignoriert (useIcd=False).")
                return True # Bedingung ignorieren -> Erfüllt

            # Strikte Prüfung, wenn check_icd_conditions_at_all = True:
            table_ref = werte_str
            # Hole alle Codes des Typs "icd" aus der/den referenzierten Tabelle(n)
            icd_codes_in_rule_table = {entry['Code'].upper() for entry in get_table_content(table_ref, "icd", tabellen_dict_by_table) if entry.get('Code')}
            
            if not icd_codes_in_rule_table: # Wenn die Regel-Tabelle für ICDs leer ist oder nicht existiert
                # print(f"DEBUG (check_single): ICD-Tabellen-Bedingung '{werte_str}' referenziert leere/unbekannte ICD-Tabelle, gilt als NICHT erfüllt, wenn Kontext-ICDs vorhanden.")
                # Wenn die Regel keine spezifischen ICDs fordert (leere Tabelle), aber der Kontext welche hat,
                # ist die spezifische Anforderung "ICD aus DIESER Tabelle" nicht erfüllt.
                # Wenn der Kontext auch keine ICDs hätte, wäre es True.
                # Aber hier geht es um eine spezifische Anforderung.
                return False if provided_icds_upper else True # Nicht erfüllt, wenn Kontext-ICDs da sind, sonst ja.
                                                              # Sicherer: return False, da eine spezifische Tabelle erwartet wird.
                                                              # Überlegung: Wenn die Regel sagt "ICD aus Tabelle X" und X ist leer, ist die Bedingung unerfüllbar.
            
            # print(f"DEBUG (check_single): ICD-Tabellen-Prüfung: Regel-Tabelle '{table_ref}' enthält {icd_codes_in_rule_table}, Kontext hat {provided_icds_upper}")
            # Ist mindestens einer der *im Kontext vorhandenen ICDs* auch in der *Menge der ICDs aus der Regel-Tabelle*?
            return any(provided_icd in icd_codes_in_rule_table for provided_icd in provided_icds_upper)

        # --- Andere Bedingungstypen bleiben wie zuvor ---
        elif bedingungstyp == "GTIN" or bedingungstyp == "MEDIKAMENTE IN LISTE":
            # ... (unverändert)
            werte_list_gtin = [w.strip() for w in str(werte_str).split(',') if w.strip()]
            if not werte_list_gtin: return True # Keine spezifische Anforderung
            return any(req_gtin in context.get("GTIN", []) for req_gtin in werte_list_gtin)

        elif bedingungstyp == "LKN" or bedingungstyp == "LEISTUNGSPOSITIONEN IN LISTE":
            # ... (unverändert)
            werte_list_upper_lkn = [w.strip().upper() for w in str(werte_str).split(',') if w.strip()]
            if not werte_list_upper_lkn: return True # Keine spezifische Anforderung
            return any(req_lkn in {p_lkn.upper() for p_lkn in context.get("LKN", []) if p_lkn} for req_lkn in werte_list_upper_lkn)
        
        elif bedingungstyp == "GESCHLECHT IN LISTE":
            # ... (unverändert)
            provided_geschlecht_str = context.get("Geschlecht")
            if provided_geschlecht_str and werte_str: 
                geschlechter_in_regel_lower = {g.strip().lower() for g in str(werte_str).split(',') if g.strip()}
                return provided_geschlecht_str.strip().lower() in geschlechter_in_regel_lower
            elif not werte_str: 
                return True
            return False 

        elif bedingungstyp == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp == "TARIFPOSITIONEN IN TABELLE":
            # ... (unverändert)
            table_ref = werte_str 
            lkn_codes_in_rule_table = {entry['Code'].upper() for entry in get_table_content(table_ref, "service_catalog", tabellen_dict_by_table) if entry.get('Code')}
            if not lkn_codes_in_rule_table: return False # Regel fordert LKNs aus einer leeren/unbekannten Tabelle
            return any(provided_lkn in lkn_codes_in_rule_table for provided_lkn in {p_lkn.upper() for p_lkn in context.get("LKN", []) if p_lkn})


        elif bedingungstyp == "PATIENTENBEDINGUNG":
            # ... (unverändert)
            # ... (Logik für Alter und Geschlecht (exakt) bleibt)
            feld_ref = condition.get('Feld')
            wert_regel = condition.get('Werte') # Wert aus Regel für Patientenbedingung
            min_val = condition.get('MinWert')
            max_val = condition.get('MaxWert')
            wert_fall = context.get(feld_ref)

            if feld_ref == "Alter":
                if wert_fall is None: return False
                try:
                    alter_patient = int(wert_fall); alter_ok = True
                    if min_val is not None and alter_patient < int(min_val): alter_ok = False
                    if max_val is not None and alter_patient > int(max_val): alter_ok = False
                    # Fall für exakten Wert, wenn kein Bereich definiert ist
                    if min_val is None and max_val is None and wert_regel is not None and alter_patient != int(wert_regel): alter_ok = False
                    return alter_ok
                except (ValueError, TypeError): return False
            elif feld_ref == "Geschlecht":
                 provided_geschlecht_str = context.get("Geschlecht")
                 if isinstance(provided_geschlecht_str, str) and isinstance(wert_regel, str):
                     return provided_geschlecht_str.strip().lower() == wert_regel.strip().lower()
                 elif provided_geschlecht_str is None and (wert_regel is None or str(wert_regel).strip().lower() == 'unbekannt' or str(wert_regel).strip() == ""):
                     return True # Beide unbekannt/nicht spezifiziert
                 else: 
                     return False # Einer ist spezifiziert, der andere nicht (oder unterschiedlich)
            else: 
                print(f"WARNUNG (check_single): Unbekanntes Feld '{feld_ref}' für Patientenbedingung.")
                return True # Unbekannte Felder gelten als erfüllt, um nicht zu blockieren

        else: 
            print(f"WARNUNG (check_single): Unbekannter Pauschalen-Bedingungstyp '{bedingungstyp}'. Wird als False angenommen.")
            return False 

    except Exception as e:
        print(f"FEHLER (check_single) bei Prüfung Einzelbedingung ({bedingungstyp}, {werte_str}): {e}")
        traceback.print_exc() 
        return False
        
# === FUNKTION ZUR AUSWERTUNG DER STRUKTURIERTEN LOGIK (UND/ODER) ===
def evaluate_structured_conditions(
    pauschale_code: str,
    context: Dict,
    pauschale_bedingungen_data: List[Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]]
) -> bool:
    """
    Wertet die strukturierte Logik für eine Pauschale aus.
    Eine Pauschale ist gültig, wenn MINDESTENS EINE ihrer Bedingungs-GRUPPEN vollständig erfüllt ist.
    Innerhalb einer GRUPPE müssen ALLE einzelnen Bedingungen (unabhängig von 'Ebene' oder 'Operator' der Einzelbedingung)
    erfüllt sein (implizite UND-Logik für die Komponenten einer Gruppe).
    """
    PAUSCHALE_KEY = 'Pauschale'
    GRUPPE_KEY = 'Gruppe'
    # Der 'Operator' und 'Ebene' Schlüssel der einzelnen Bedingungen wird hier ignoriert,
    # da die Logik pro Gruppe als striktes UND aller ihrer Komponenten interpretiert wird,
    # und die Pauschale als ODER über die erfüllten Gruppen.

    # Hole alle Bedingungen für die spezifische Pauschale
    conditions_for_this_pauschale = [
        cond for cond in pauschale_bedingungen_data if cond.get(PAUSCHALE_KEY) == pauschale_code
    ]

    if not conditions_for_this_pauschale:
        # print(f"DEBUG (evaluate): Keine Bedingungen für Pauschale {pauschale_code} gefunden, gilt als gültig.")
        return True # Keine Bedingungen -> immer gültig

    # Gruppiere die Bedingungen nach ihrem 'Gruppe'-Schlüssel
    grouped_conditions: Dict[Any, List[Dict]] = {}
    for cond in conditions_for_this_pauschale:
        gruppe_id = cond.get(GRUPPE_KEY)
        if gruppe_id is None: 
            # print(f"WARNUNG (evaluate): Bedingung ohne Gruppe für Pauschale {pauschale_code}: {cond}")
            continue # Bedingung ohne Gruppe kann nicht ausgewertet werden
        grouped_conditions.setdefault(gruppe_id, []).append(cond)

    if not grouped_conditions:
        # print(f"DEBUG (evaluate): Keine gültigen Gruppen für Pauschale {pauschale_code} nach Filterung, gilt als NICHT gültig (oder True, wenn keine Bedingungen da waren - oben abgefangen).")
        # Wenn conditions_for_this_pauschale da war, aber keine davon eine Gruppe hatte.
        return False 

    # print(f"DEBUG (evaluate): Prüfe {len(grouped_conditions)} Gruppen für Pauschale {pauschale_code}.")

    # Iteriere durch jede Gruppe. Wenn EINE Gruppe vollständig erfüllt ist, ist die Pauschale gültig.
    for gruppe_id, conditions_in_group in grouped_conditions.items():
        if not conditions_in_group: # Sollte nicht passieren, wenn Gruppe existiert
            continue

        # print(f"  DEBUG (evaluate): Prüfe Gruppe {gruppe_id} mit {len(conditions_in_group)} Bedingungen.")
        all_conditions_in_group_met = True # Annahme für UND-Logik innerhalb der Gruppe
        
        condition_results_in_group_for_log = [] # Für detaillierteres Logging

        for cond_item_idx, cond_item in enumerate(conditions_in_group):
            single_cond_met = check_single_condition(cond_item, context, tabellen_dict_by_table)
            condition_results_in_group_for_log.append(f"Cond{cond_item_idx+1}({cond_item.get('Bedingungstyp','N/A')}:{cond_item.get('Werte','N/A')}):{single_cond_met}")
            
            if not single_cond_met:
                all_conditions_in_group_met = False
                break # Wenn eine Bedingung in der Gruppe nicht erfüllt ist, ist die ganze Gruppe nicht erfüllt

        # print(f"  DEBUG (evaluate): Gruppe {gruppe_id} Ergebnisse: [{', '.join(condition_results_in_group_for_log)}]. Gruppe erfüllt: {all_conditions_in_group_met}")

        if all_conditions_in_group_met:
            # print(f"DEBUG (evaluate): Gruppe {gruppe_id} für Pauschale {pauschale_code} ist VOLLSTÄNDIG erfüllt.")
            return True # Mindestens eine Gruppe ist erfüllt, also ist die Pauschale gültig

    # Wenn keine Gruppe vollständig erfüllt wurde
    # print(f"DEBUG (evaluate): KEINE Gruppe für Pauschale {pauschale_code} wurde vollständig erfüllt.")
    return False

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

    PAUSCHALE_ERKLAERUNG_KEY = 'pauschale_erklaerung_html'
    POTENTIAL_ICDS_KEY = 'potential_icds'
    LKN_KEY_IN_RULE_CHECKED = 'lkn'
    PAUSCHALE_KEY_IN_PAUSCHALEN = 'Pauschale' # In tblPauschalen
    PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN = 'Pauschale_Text' # In tblPauschalen
    LP_LKN_KEY = 'Leistungsposition'; LP_PAUSCHALE_KEY = 'Pauschale' # In tblPauschaleLeistungsposition
    BED_PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte' # In tblPauschaleBedingungen
    TAB_CODE_KEY = 'Code'; TAB_TYP_KEY = 'Tabelle_Typ'; TAB_TABELLE_KEY = 'Tabelle' # In tblTabellen

    potential_pauschale_codes = set()
    rule_checked_lkns = [l.get(LKN_KEY_IN_RULE_CHECKED) for l in rule_checked_leistungen if l.get(LKN_KEY_IN_RULE_CHECKED)]
    print(f"DEBUG: Regelkonforme LKNs für Pauschalen-Suche: {rule_checked_lkns}")
    lkns_in_tables = {} 
    for lkn in rule_checked_lkns:
        found_via_a = False; found_via_b = False; found_via_c = False
        for item in pauschale_lp_data:
            if item.get(LP_LKN_KEY) == lkn:
                pauschale_code_a = item.get(LP_PAUSCHALE_KEY)
                if pauschale_code_a and pauschale_code_a in pauschalen_dict: potential_pauschale_codes.add(pauschale_code_a); found_via_a = True
        for cond in pauschale_bedingungen_data:
            if cond.get(BED_TYP_KEY) == "LEISTUNGSPOSITIONEN IN LISTE":
                werte_liste = [w.strip() for w in str(cond.get(BED_WERTE_KEY, "")).split(',') if w.strip()]
                if lkn in werte_liste:
                    pauschale_code_b = cond.get(BED_PAUSCHALE_KEY)
                    if pauschale_code_b and pauschale_code_b in pauschalen_dict: potential_pauschale_codes.add(pauschale_code_b); found_via_b = True
        if lkn not in lkns_in_tables:
             tables_for_lkn = set()
             for table_name_key in tabellen_dict_by_table.keys():
                  for entry in tabellen_dict_by_table[table_name_key]:
                       if entry.get(TAB_CODE_KEY) == lkn and entry.get(TAB_TYP_KEY) == "service_catalog": tables_for_lkn.add(table_name_key.lower()) # Store normalized
             lkns_in_tables[lkn] = tables_for_lkn
        tables_for_current_lkn_normalized = lkns_in_tables.get(lkn, set())
        if tables_for_current_lkn_normalized:
            for cond in pauschale_bedingungen_data:
                if cond.get(BED_TYP_KEY) == "LEISTUNGSPOSITIONEN IN TABELLE":
                    table_ref_in_cond_str = cond.get(BED_WERTE_KEY, "")
                    pauschale_code_c = cond.get(BED_PAUSCHALE_KEY)
                    condition_tables_normalized = {t.strip().lower() for t in table_ref_in_cond_str.split(',') if t.strip()}
                    if not condition_tables_normalized.isdisjoint(tables_for_current_lkn_normalized):
                        if pauschale_code_c and pauschale_code_c in pauschalen_dict: potential_pauschale_codes.add(pauschale_code_c); found_via_c = True
    
    print(f"DEBUG: Finale potenzielle Pauschalen nach LKN-basierter Suche: {potential_pauschale_codes}")

    if not potential_pauschale_codes:
        print("INFO: Keine potenziellen Pauschalen-Codes für die erbrachten Leistungen gefunden.")
        return {"type": "Error", "message": "Keine passende Pauschale für die erbrachten Leistungen gefunden."}

    evaluated_candidates = []
    print(f"INFO: Werte strukturierte Bedingungen für {len(potential_pauschale_codes)} potenzielle Pauschalen aus...")
    for code in potential_pauschale_codes:
        if code not in pauschalen_dict: continue
        bedingungs_context = context 
        is_pauschale_valid = False
        try:
            is_pauschale_valid = evaluate_structured_conditions(
                code,
                bedingungs_context,
                pauschale_bedingungen_data,
                tabellen_dict_by_table
            )
        except Exception as e_eval:
             print(f"FEHLER bei evaluate_structured_conditions für {code}: {e_eval}")
             is_pauschale_valid = False
        # print(f"DEBUG: Strukturierte Prüfung für {code}: Gültig = {is_pauschale_valid}") # Weniger verbose hier
        evaluated_candidates.append({"code": code, "details": pauschalen_dict[code], "is_valid_structured": is_pauschale_valid})

    valid_candidates = [cand for cand in evaluated_candidates if cand["is_valid_structured"]]
    print(f"DEBUG: Struktur-gültige Kandidaten nach Prüfung: {[c['code'] for c in valid_candidates]}")

    # --- TEMPORÄRES DEBUGGING: Bedingungen der relevanten Kandidaten ausgeben ---
    debug_pauschalen_codes = ['C08.50A', 'C08.50B', 'C08.50E']
    for pc_debug_code in debug_pauschalen_codes:
        if any(cand['code'] == pc_debug_code for cand in valid_candidates): # Nur wenn sie unter den gültigen sind
            print(f"--- DEBUG BEDINGUNGEN FÜR {pc_debug_code} ---")
            conditions_for_pc = [
                cond for cond in pauschale_bedingungen_data if cond.get(BED_PAUSCHALE_KEY) == pc_debug_code
            ]
            if conditions_for_pc:
                for cond_item in conditions_for_pc:
                    print(f"  Gruppe: {cond_item.get('Gruppe')}, Operator: {cond_item.get('Operator')}, Typ: {cond_item.get(BED_TYP_KEY)}, Werte: {cond_item.get(BED_WERTE_KEY)}, Feld: {cond_item.get('Feld')}")
            else:
                print(f"  Keine Bedingungen für {pc_debug_code} in tblPauschaleBedingungen gefunden.")
            print(f"--- ENDE DEBUG BEDINGUNGEN FÜR {pc_debug_code} ---")
    # --- ENDE TEMPORÄRES DEBUGGING ---

    selected_candidate_info = None
    if valid_candidates:
        specific_valid = [c for c in valid_candidates if not c['code'].startswith('C9')]
        fallback_valid = [c for c in valid_candidates if c['code'].startswith('C9')]

        if specific_valid:
            specific_valid.sort(key=lambda x: x['code'], reverse=False) 
            selected_candidate_info = specific_valid[0]
            print(f"INFO: Spezifischste Pauschale ausgewählt (A-Z Sortierung der spezifischen), deren strukturierte Bedingungen erfüllt sind: {selected_candidate_info['code']}")
        elif fallback_valid:
            fallback_valid.sort(key=lambda x: x['code'], reverse=False) 
            selected_candidate_info = fallback_valid[0]
            print(f"INFO: Spezifischste Fallback-Pauschale ausgewählt (A-Z Sortierung), deren strukturierte Bedingungen erfüllt sind: {selected_candidate_info['code']}")
        else:
             print("FEHLER: Gültige Kandidaten gefunden, aber weder spezifisch noch Fallback?") 
             return {"type": "Error", "message": "Interner Fehler bei der Pauschalenauswahl."}
    else:
        print("INFO: Keine Pauschale erfüllt die strukturierten Bedingungen.")
        return {"type": "Error", "message": "Keine Pauschale gefunden, deren UND/ODER-Bedingungen vollständig erfüllt sind (Kontext prüfen!)."}

    best_pauschale_code = selected_candidate_info["code"]
    best_pauschale_details = selected_candidate_info["details"].copy() # Wichtig .copy()

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
