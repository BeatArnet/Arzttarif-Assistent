# regelpruefer_pauschale.py (Version mit korrigiertem Import und 9 Argumenten)
import traceback
import json
from typing import Dict, List, Any, Set # <-- Set hier importieren
from utils import escape, get_table_content, get_lang_field, translate, translate_condition_type
import re, html

# === FUNKTION ZUR PRÜFUNG EINER EINZELNEN BEDINGUNG ===
def check_single_condition(
    condition: Dict,
    context: Dict,
    tabellen_dict_by_table: Dict[str, List[Dict]]
) -> bool:
    """Prüft eine einzelne Bedingungszeile und gibt True/False zurück."""
    check_icd_conditions_at_all = context.get("useIcd", True)
    pauschale_code_for_debug = condition.get('Pauschale', 'N/A_PAUSCHALE') # Für besseres Debugging
    gruppe_for_debug = condition.get('Gruppe', 'N/A_GRUPPE') # Für besseres Debugging

    BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'; BED_FELD_KEY = 'Feld'
    BED_MIN_KEY = 'MinWert'; BED_MAX_KEY = 'MaxWert'
    bedingungstyp = condition.get(BED_TYP_KEY, "").upper()
    werte_str = condition.get(BED_WERTE_KEY, "") # Dies ist der Wert aus der Regel-DB
    feld_ref = condition.get(BED_FELD_KEY); min_val_regel = condition.get(BED_MIN_KEY) # Umbenannt für Klarheit
    max_val_regel = condition.get(BED_MAX_KEY); wert_regel_explizit = condition.get(BED_WERTE_KEY) # Umbenannt für Klarheit

    # Kontextwerte holen
    provided_icds_upper = {p_icd.upper() for p_icd in context.get("ICD", []) if p_icd}
    provided_gtins = set(context.get("GTIN", []))
    provided_lkns_upper = {p_lkn.upper() for p_lkn in context.get("LKN", []) if p_lkn}
    provided_alter = context.get("Alter")
    provided_geschlecht_str = str(context.get("Geschlecht", "unbekannt")).lower() # Default 'unbekannt' und lower
    provided_anzahl = context.get("Anzahl") # Aus dem Kontext für "ANZAHL" Typ
    provided_seitigkeit_str = str(context.get("Seitigkeit", "unbekannt")).lower() # Default 'unbekannt' und lower

    # print(f"--- DEBUG check_single --- P: {pauschale_code_for_debug} G: {gruppe_for_debug} Typ: {bedingungstyp}, Regel-Werte: '{werte_str}', Kontext: {context.get('Seitigkeit', 'N/A')}/{context.get('Anzahl', 'N/A')}")

    try:
        if bedingungstyp == "ICD": # ICD IN LISTE
            if not check_icd_conditions_at_all: return False
            required_icds_in_rule_list = {w.strip().upper() for w in str(werte_str).split(',') if w.strip()}
            if not required_icds_in_rule_list: return True # Leere Regel-Liste ist immer erfüllt
            return any(req_icd in provided_icds_upper for req_icd in required_icds_in_rule_list)

        elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE": # ICD IN TABELLE
            if not check_icd_conditions_at_all: return False
            table_ref = werte_str
            icd_codes_in_rule_table = {entry['Code'].upper() for entry in get_table_content(table_ref, "icd", tabellen_dict_by_table) if entry.get('Code')}
            if not icd_codes_in_rule_table: # Wenn Tabelle leer oder nicht gefunden
                 return False if provided_icds_upper else True # Nur erfüllt, wenn auch keine ICDs im Kontext sind
            return any(provided_icd in icd_codes_in_rule_table for provided_icd in provided_icds_upper)

        elif bedingungstyp == "GTIN" or bedingungstyp == "MEDIKAMENTE IN LISTE":
            werte_list_gtin = [w.strip() for w in str(werte_str).split(',') if w.strip()]
            if not werte_list_gtin: return True
            return any(req_gtin in provided_gtins for req_gtin in werte_list_gtin)

        elif bedingungstyp == "LKN" or bedingungstyp == "LEISTUNGSPOSITIONEN IN LISTE":
            werte_list_upper_lkn = [w.strip().upper() for w in str(werte_str).split(',') if w.strip()]
            if not werte_list_upper_lkn: return True
            return any(req_lkn in provided_lkns_upper for req_lkn in werte_list_upper_lkn)

        elif bedingungstyp == "GESCHLECHT IN LISTE": # Z.B. Werte: "Männlich,Weiblich"
            if werte_str: # Nur prüfen, wenn Regel einen Wert hat
                geschlechter_in_regel_lower = {g.strip().lower() for g in str(werte_str).split(',') if g.strip()}
                return provided_geschlecht_str in geschlechter_in_regel_lower
            return True # Wenn Regel keinen Wert hat, ist es für jedes Geschlecht ok

        elif bedingungstyp == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp == "TARIFPOSITIONEN IN TABELLE":
            table_ref = werte_str
            lkn_codes_in_rule_table = {entry['Code'].upper() for entry in get_table_content(table_ref, "service_catalog", tabellen_dict_by_table) if entry.get('Code')}
            if not lkn_codes_in_rule_table: return False # Leere Tabelle kann nicht erfüllt werden, wenn LKNs im Kontext sind (implizit)
            return any(provided_lkn in lkn_codes_in_rule_table for provided_lkn in provided_lkns_upper)

        elif bedingungstyp == "PATIENTENBEDINGUNG": # Für Alter, Geschlecht (spezifisch)
            # feld_ref ist hier z.B. "Alter" oder "Geschlecht"
            # wert_regel_explizit ist der Wert aus der Spalte "Werte" der Bedingungstabelle
            # min_val_regel, max_val_regel sind MinWert/MaxWert aus der Bedingungstabelle
            if feld_ref == "Alter":
                if provided_alter is None: return False # Alter muss im Kontext sein
                try:
                    alter_patient = int(provided_alter); alter_ok = True
                    if min_val_regel is not None and alter_patient < int(min_val_regel): alter_ok = False
                    if max_val_regel is not None and alter_patient > int(max_val_regel): alter_ok = False
                    # Wenn weder Min noch Max, aber ein expliziter Wert in der Regel steht
                    if min_val_regel is None and max_val_regel is None and wert_regel_explizit is not None:
                        if alter_patient != int(wert_regel_explizit): alter_ok = False
                    return alter_ok
                except (ValueError, TypeError): return False
            elif feld_ref == "Geschlecht":
                 # Hier wird ein exakter String-Vergleich erwartet (z.B. Regelwert 'Männlich')
                 if isinstance(wert_regel_explizit, str):
                     return provided_geschlecht_str == wert_regel_explizit.strip().lower()
                 return False # Wenn Regelwert kein String ist
            else:
                print(f"WARNUNG (check_single PATIENTENBEDINGUNG): Unbekanntes Feld '{feld_ref}'.")
                return True # Oder False, je nach gewünschtem Verhalten

        elif bedingungstyp == "ANZAHL":
            if provided_anzahl is None: return False
            try:
                kontext_anzahl_val = int(provided_anzahl)
                regel_wert_anzahl_val = int(werte_str)
                vergleichsoperator = condition.get('Vergleichsoperator')

                if vergleichsoperator == ">=": return kontext_anzahl_val >= regel_wert_anzahl_val
                elif vergleichsoperator == "<=": return kontext_anzahl_val <= regel_wert_anzahl_val
                elif vergleichsoperator == ">": return kontext_anzahl_val > regel_wert_anzahl_val
                elif vergleichsoperator == "<": return kontext_anzahl_val < regel_wert_anzahl_val
                elif vergleichsoperator == "=": return kontext_anzahl_val == regel_wert_anzahl_val
                elif vergleichsoperator == "!=": return kontext_anzahl_val != regel_wert_anzahl_val
                else:
                    print(f"WARNUNG (check_single ANZAHL): Unbekannter Vergleichsoperator '{vergleichsoperator}'.")
                    return False
            except (ValueError, TypeError) as e_anzahl:
                print(f"FEHLER (check_single ANZAHL) Konvertierung: {e_anzahl}. Regelwert: '{werte_str}', Kontextwert: '{provided_anzahl}'")
                return False

        elif bedingungstyp == "SEITIGKEIT":
            # werte_str aus der Regel ist z.B. "'B'" oder "'E'"
            regel_wert_seitigkeit_norm = werte_str.strip().replace("'", "").lower()
            vergleichsoperator = condition.get('Vergleichsoperator')
            # provided_seitigkeit_str ist schon lower und hat Default 'unbekannt'

            if vergleichsoperator == "=":
                if regel_wert_seitigkeit_norm == 'b': return provided_seitigkeit_str == 'beidseits'
                elif regel_wert_seitigkeit_norm == 'e': return provided_seitigkeit_str in ['einseitig', 'links', 'rechts']
                elif regel_wert_seitigkeit_norm == 'l': return provided_seitigkeit_str == 'links'
                elif regel_wert_seitigkeit_norm == 'r': return provided_seitigkeit_str == 'rechts'
                else: return provided_seitigkeit_str == regel_wert_seitigkeit_norm # Direkter Vergleich
            elif vergleichsoperator == "!=":
                if regel_wert_seitigkeit_norm == 'b': return provided_seitigkeit_str != 'beidseits'
                elif regel_wert_seitigkeit_norm == 'e': return provided_seitigkeit_str not in ['einseitig', 'links', 'rechts']
                elif regel_wert_seitigkeit_norm == 'l': return provided_seitigkeit_str != 'links'
                elif regel_wert_seitigkeit_norm == 'r': return provided_seitigkeit_str != 'rechts'
                else: return provided_seitigkeit_str != regel_wert_seitigkeit_norm
            else:
                print(f"WARNUNG (check_single SEITIGKEIT): Unbekannter Vergleichsoperator '{vergleichsoperator}'.")
                return False
        else:
            print(f"WARNUNG (check_single): Unbekannter Pauschalen-Bedingungstyp '{bedingungstyp}'. Wird als False angenommen.")
            return False
    except Exception as e:
        print(f"FEHLER (check_single) für P: {pauschale_code_for_debug} G: {gruppe_for_debug} Typ: {bedingungstyp}, Werte: {werte_str}: {e}")
        traceback.print_exc()
        return False

def get_beschreibung_fuer_lkn_im_backend(lkn_code: str, leistungskatalog_dict: Dict, lang: str = 'de') -> str:
    details = leistungskatalog_dict.get(str(lkn_code).upper())
    if not details:
        return lkn_code
    return get_lang_field(details, 'Beschreibung', lang) or lkn_code

def get_beschreibung_fuer_icd_im_backend(
    icd_code: str,
    tabellen_dict_by_table: Dict,
    spezifische_icd_tabelle: str | None = None,
    lang: str = 'de'
) -> str:
    """Liefert die Beschreibung eines ICD-Codes in der gewünschten Sprache."""
    # Wenn eine spezifische Tabelle bekannt ist (z.B. aus der Bedingung), diese zuerst prüfen
    if spezifische_icd_tabelle:
        icd_entries_specific = get_table_content(spezifische_icd_tabelle, "icd", tabellen_dict_by_table, lang)
        for entry in icd_entries_specific:
            if entry.get('Code', '').upper() == icd_code.upper():
                return entry.get('Code_Text', icd_code)

    # Fallback: Suche in einer generellen Haupt-ICD-Tabelle, falls vorhanden und definiert
    # Du müsstest den Namen deiner Haupt-ICD-Tabelle hier eintragen, z.B. "icd10gm_codes"
    haupt_icd_tabelle_name = "icd_hauptkatalog" # Beispielname, anpassen!
    # print(f"DEBUG: Suche ICD {icd_code} in Haupttabelle {haupt_icd_tabelle_name}")
    icd_entries_main = get_table_content(haupt_icd_tabelle_name, "icd", tabellen_dict_by_table, lang)
    for entry in icd_entries_main:
        if entry.get('Code', '').upper() == icd_code.upper():
            return entry.get('Code_Text', icd_code)
            
    # print(f"DEBUG: ICD {icd_code} nicht in spezifischer oder Haupttabelle gefunden.")
    return icd_code # Wenn nirgends gefunden, Code selbst zurückgeben

# === FUNKTION ZUR AUSWERTUNG DER STRUKTURIERTEN LOGIK (UND/ODER) ===
def evaluate_structured_conditions(
    pauschale_code: str,
    context: Dict,
    pauschale_bedingungen_data: List[Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]]
) -> bool:
    """
    Wertet die strukturierte Logik für eine Pauschale aus.
    Logik: ODER zwischen Gruppen, UND innerhalb jeder Gruppe.
    """
    PAUSCHALE_KEY = 'Pauschale'; GRUPPE_KEY = 'Gruppe'
    conditions_for_this_pauschale = [cond for cond in pauschale_bedingungen_data if cond.get(PAUSCHALE_KEY) == pauschale_code]
    if not conditions_for_this_pauschale:
        # print(f"DEBUG evaluate_structured_conditions: Keine Bedingungen für Pauschale {pauschale_code} definiert -> True")
        return True # Keine Bedingungen = immer erfüllt

    OPERATOR_KEY = 'Operator'

    grouped_conditions: Dict[Any, List[Dict]] = {}
    for cond in conditions_for_this_pauschale:
        gruppe_id = cond.get(GRUPPE_KEY)
        if gruppe_id is None:
            # print(f"WARNUNG evaluate_structured_conditions: Bedingung ohne Gruppe für Pauschale {pauschale_code}: {cond}")
            continue  # Bedingungen ohne Gruppe können nicht ausgewertet werden in dieser Logik
        grouped_conditions.setdefault(gruppe_id, []).append(cond)

    if not grouped_conditions:
        # print(f"DEBUG evaluate_structured_conditions: Keine gültigen Gruppen für Pauschale {pauschale_code} nach Filterung -> False (oder True, je nach Definition)")
        # Wenn es Bedingungen gab, aber keine davon eine Gruppe hatte, ist es unklar.
        # Aktuell: False, da keine Gruppe erfüllt werden kann.
        return False

    # print(f"DEBUG evaluate_structured_conditions: Pauschale {pauschale_code}, {len(grouped_conditions)} Gruppen gefunden.")
    for gruppe_id, conditions_in_group in grouped_conditions.items():
        if not conditions_in_group:
            continue  # Leere Gruppe überspringen

        tokens = []
        for cond_item in conditions_in_group:
            result = check_single_condition(cond_item, context, tabellen_dict_by_table)
            tokens.append((result, cond_item.get(OPERATOR_KEY, 'UND').upper()))

        if not tokens:
            continue

        # Evaluate AND before OR using the operators between conditions
        partial_results = [tokens[0][0]]
        for idx in range(1, len(tokens)):
            prev_op = tokens[idx - 1][1]
            current_res = tokens[idx][0]
            if prev_op == 'UND':
                partial_results[-1] = partial_results[-1] and current_res
            else:  # ODER
                partial_results.append(current_res)

        group_result = any(partial_results)

        if group_result:
            # print(f"  -> Gruppe {gruppe_id} ist erfüllt. Pauschale {pauschale_code} ist gültig.")
            return True  # Eine erfüllte Gruppe reicht (ODER-Logik zwischen Gruppen)

    # print(f"DEBUG evaluate_structured_conditions: Keine Gruppe für Pauschale {pauschale_code} war vollständig erfüllt -> False")
    return False # Keine Gruppe war vollständig erfüllt

# === FUNKTION ZUR HTML-GENERIERUNG DER BEDINGUNGSPRÜFUNG ===
def check_pauschale_conditions(
    pauschale_code: str,
    context: dict,
    pauschale_bedingungen_data: list[dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    leistungskatalog_dict: Dict[str, Dict],
    lang: str = 'de'
) -> dict:
    """Generate a detailed HTML report for the given pauschale.

    Parameters
    ----------
    pauschale_code : str
        Code der zu prüfenden Pauschale.
    context : dict
        Kontextdaten wie LKN, ICD etc.
    pauschale_bedingungen_data : list[dict]
        Bedingungen aller Pauschalen.
    tabellen_dict_by_table : dict
        Nach Tabellennamen gruppierte Einträge.
    leistungskatalog_dict : dict
        LKN-Katalog für Beschreibungen.
    lang : str, optional
        Sprache der Beschreibungen, standardmäßig "de".

    Returns
    -------
    dict
        HTML-Ausgabe, Fehlerliste und LKN-Trigger-Flag.
    """

    errors: list[str] = []
    grouped_html_parts: Dict[Any, List[str]] = {}
    trigger_lkn_condition_met = False # Wird nicht mehr direkt hier gesetzt, sondern von aufrufender Funktion

    PAUSCHALE_KEY_IN_BEDINGUNGEN = 'Pauschale'; BED_ID_KEY = 'BedingungsID'
    BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'; BED_FELD_KEY = 'Feld'
    GRUPPE_KEY = 'Gruppe'

    conditions_for_this_pauschale = [
        cond for cond in pauschale_bedingungen_data if cond.get(PAUSCHALE_KEY_IN_BEDINGUNGEN) == pauschale_code
    ]

    if not conditions_for_this_pauschale:
        return {"html": "<ul><li>Keine spezifischen Bedingungen für diese Pauschale definiert.</li></ul>", "errors": [], "trigger_lkn_condition_met": False}

    conditions_for_this_pauschale.sort(key=lambda x: (x.get(GRUPPE_KEY, float('inf')), x.get(BED_ID_KEY, 0))) # Ohne Gruppe ans Ende

    provided_lkns_im_kontext_upper = {str(lkn).upper() for lkn in context.get("LKN", []) if lkn}
    provided_icds_im_kontext_upper = {str(icd).upper() for icd in context.get("ICD", []) if icd}

    for i, cond_definition in enumerate(conditions_for_this_pauschale): # cond_definition wird hier definiert
        gruppe_id = cond_definition.get(GRUPPE_KEY, 'Ohne_Gruppe') # Default für Anzeige
        bedingung_id = cond_definition.get(BED_ID_KEY, f"Unbekannt_{i+1}")
        bedingungstyp = cond_definition.get(BED_TYP_KEY, "UNBEKANNT").upper()
        werte_aus_regel = cond_definition.get(BED_WERTE_KEY, "") # werte_aus_regel wird hier definiert
        feld_ref_patientenbed = cond_definition.get(BED_FELD_KEY)
        
        condition_met_this_line = check_single_condition(cond_definition, context, tabellen_dict_by_table)
        
        icon_html = ""
        if condition_met_this_line:
            icon_html = """<span class="condition-status-icon condition-icon-fulfilled">
                               <svg width="1em" height="1em"><use xlink:href="#icon-check"></use></svg>
                           </span>"""
        else:
            icon_html = """<span class="condition-status-icon condition-icon-not-fulfilled">
                               <svg width="1em" height="1em"><use xlink:href="#icon-cross"></use></svg>
                           </span>"""
        
        status_label_for_error = "Erfüllt" if condition_met_this_line else "NICHT erfüllt"
        
        li_content = f"<div data-bedingung-id='{escape(str(bedingung_id))}' class='condition-item-row'>"
        li_content += icon_html
        translated_type = translate_condition_type(bedingungstyp, lang)
        li_content += f"<span class='condition-type-display'>({escape(translated_type)}):</span> "
        
        specific_description_html = ""
        is_lkn_condition_type = False # Für trigger_lkn_condition_met (obwohl das hier nicht mehr direkt gesetzt wird)
        kontext_erfuellungs_info_html = ""

        if "IN TABELLE" in bedingungstyp:
            table_names_str = werte_aus_regel
            table_names_list = [t.strip() for t in table_names_str.split(',') if t.strip()]
            type_for_get_table_content = ""; type_prefix = "Code"
            kontext_elemente_fuer_vergleich = set()
            erfuellende_element_beschreibungen_aus_tabellen = {}
            aktuelle_tabelle_fuer_icd_fallback = table_names_list[0] if table_names_list else None


            if "LEISTUNGSPOSITIONEN" in bedingungstyp or "TARIFPOSITIONEN" in bedingungstyp:
                type_prefix = "LKN"; type_for_get_table_content = "service_catalog"; is_lkn_condition_type = True
                kontext_elemente_fuer_vergleich = provided_lkns_im_kontext_upper
            elif "HAUPTDIAGNOSE" in bedingungstyp or "ICD" in bedingungstyp :
                type_prefix = "ICD"; type_for_get_table_content = "icd"
                kontext_elemente_fuer_vergleich = provided_icds_im_kontext_upper
            
            specific_description_html += translate('require_lkn_table' if type_prefix == 'LKN' else 'require_icd_table', lang)
            if not table_names_list: specific_description_html += f"<i>{translate('no_table_name', lang)}</i>"
            else:
                table_links_html_parts = []
                all_codes_in_regel_tabellen = set() 
                for table_name in table_names_list:
                    table_content_entries = get_table_content(table_name, type_for_get_table_content, tabellen_dict_by_table, lang)
                    entry_count = len(table_content_entries); details_content_html = ""
                    current_table_codes_with_desc = {}
                    if table_content_entries:
                        details_content_html = "<ul style='margin-top: 5px; font-size: 0.9em; max-height: 150px; overflow-y: auto; border-top: 1px solid #eee; padding-top: 5px; padding-left: 15px; list-style-position: inside;'>"
                        for item in sorted(table_content_entries, key=lambda x: x.get('Code', '')):
                            item_code = item.get('Code','').upper(); all_codes_in_regel_tabellen.add(item_code)
                            item_text = item.get('Code_Text', 'N/A')
                            if type_prefix == "LKN":
                                item_text = get_beschreibung_fuer_lkn_im_backend(item_code, leistungskatalog_dict, lang)
                            current_table_codes_with_desc[item_code] = item_text
                            details_content_html += f"<li><b>{escape(item_code)}</b>: {escape(item_text)}</li>"
                        details_content_html += "</ul>"
                    entries_label = translate('entries_label', lang)
                    table_detail_html = (f"<details><summary>{escape(table_name)}</summary> ({entry_count} {entries_label}){details_content_html}</details>")
                    table_links_html_parts.append(table_detail_html)
                    # Finde erfüllende Elemente für diese spezifische Tabelle
                    for kontext_code in kontext_elemente_fuer_vergleich:
                        if kontext_code in current_table_codes_with_desc:
                             erfuellende_element_beschreibungen_aus_tabellen[kontext_code] = current_table_codes_with_desc[kontext_code]
                
                specific_description_html += ", ".join(table_links_html_parts)
                if condition_met_this_line and erfuellende_element_beschreibungen_aus_tabellen:
                    details_list = [f"<b>{escape(code)}</b> ({escape(desc)})" for code, desc in erfuellende_element_beschreibungen_aus_tabellen.items() if code in kontext_elemente_fuer_vergleich]
                    if details_list:
                        kontext_erfuellungs_info_html = (
                            f" <span class='context-match-info fulfilled'>"
                            f"{translate('fulfilled_by', lang, items=', '.join(details_list))}"
                            f"</span>"
                        )
                elif condition_met_this_line: # Erfüllt, aber keine Beschreibung gefunden (sollte nicht passieren, wenn Logik stimmt)
                    erfuellende_kontext_codes_ohne_desc = [k for k in kontext_elemente_fuer_vergleich if k in all_codes_in_regel_tabellen]
                    if erfuellende_kontext_codes_ohne_desc:
                        kontext_erfuellungs_info_html = (
                            f" <span class='context-match-info fulfilled'>"
                            f"{translate('fulfilled_by', lang, items=', '.join(escape(c) for c in erfuellende_kontext_codes_ohne_desc))}"
                            f"</span>"
                        )
                elif not condition_met_this_line and all_codes_in_regel_tabellen : # Nicht erfüllt UND Regel-Tabelle hatte Codes
                    fehlende_elemente_details = []
                    # Zeige Kontext-Elemente, die NICHT in der Regel-Tabelle waren
                    for kontext_code in kontext_elemente_fuer_vergleich:
                        if kontext_code not in all_codes_in_regel_tabellen:
                            desc = get_beschreibung_fuer_lkn_im_backend(kontext_code, leistungskatalog_dict, lang) if type_prefix == "LKN" else get_beschreibung_fuer_icd_im_backend(
                                kontext_code,
                                tabellen_dict_by_table,
                                spezifische_icd_tabelle=aktuelle_tabelle_fuer_icd_fallback if aktuelle_tabelle_fuer_icd_fallback is not None else None,
                                lang=lang,
                            )
                            fehlende_elemente_details.append(f"<b>{escape(kontext_code)}</b> ({escape(desc)})")
                    if fehlende_elemente_details:
                        kontext_erfuellungs_info_html = (
                            f" <span class='context-match-info not-fulfilled'>"
                            f"{translate('context_items_not_in_table', lang, items=', '.join(fehlende_elemente_details))}"
                            f"</span>"
                        )
                elif not condition_met_this_line and not all_codes_in_regel_tabellen: # Nicht erfüllt und Regel-Tabelle war leer
                     kontext_erfuellungs_info_html = f" <span class='context-match-info not-fulfilled'>{translate('tables_empty', lang)}</span>"


        elif "IN LISTE" in bedingungstyp:
            items_in_list_str = werte_aus_regel
            regel_items_upper = {item.strip().upper() for item in items_in_list_str.split(',') if item.strip()}
            type_prefix = "Code"; kontext_elemente_fuer_vergleich = set()
            if "LEISTUNGSPOSITIONEN" in bedingungstyp or "LKN" in bedingungstyp:
                type_prefix = "LKN"; is_lkn_condition_type = True; kontext_elemente_fuer_vergleich = provided_lkns_im_kontext_upper
            elif "HAUPTDIAGNOSE" in bedingungstyp or "ICD" in bedingungstyp:
                type_prefix = "ICD"; kontext_elemente_fuer_vergleich = provided_icds_im_kontext_upper
            elif "GESCHLECHT" in bedingungstyp: # Speziell für GESCHLECHT IN LISTE
                type_prefix = "Geschlecht"; kontext_elemente_fuer_vergleich = {str(context.get('Geschlecht', 'N/A')).lower()}
                regel_items_lower_geschlecht = {item.strip().lower() for item in items_in_list_str.split(',') if item.strip()} # Regel-Items für Geschlecht auch lower
                specific_description_html += translate('geschlecht_list', lang)
                if not regel_items_lower_geschlecht: specific_description_html += f"<i>{translate('no_gender_spec', lang)}</i>"
                else: specific_description_html += f"{escape(', '.join(sorted(list(regel_items_lower_geschlecht))))}"
                if condition_met_this_line:
                    erfuellendes_geschlecht = next((g for g in kontext_elemente_fuer_vergleich if g in regel_items_lower_geschlecht), None)
                    if erfuellendes_geschlecht:
                        kontext_erfuellungs_info_html = (
                            f" <span class='context-match-info fulfilled'>"
                            f"{translate('fulfilled_by', lang, items=escape(erfuellendes_geschlecht))}"
                            f"</span>"
                        )
                # Keine "nicht erfüllt" Info hier, da es nur eine Liste ist.
            else: # Allgemeiner Fall für andere Listen (GTIN etc.)
                specific_description_html += translate('require_gtin_list' if type_prefix != 'Geschlecht' else 'geschlecht_list', lang)
                if not regel_items_upper: specific_description_html += f"<i>{translate('no_gtins_spec' if type_prefix != 'Geschlecht' else 'no_gender_spec', lang)}</i>"
                else: specific_description_html += f"{escape(', '.join(sorted(list(regel_items_upper))))}"
                # Für GTIN etc. keine Beschreibung, nur Erfüllungsstatus
                if condition_met_this_line:
                    erfuellende_items = [k for k in kontext_elemente_fuer_vergleich if k in regel_items_upper]
                    if erfuellende_items:
                        kontext_erfuellungs_info_html = (
                            f" <span class='context-match-info fulfilled'>"
                            f"{translate('fulfilled_by', lang, items=escape(', '.join(erfuellende_items)))}"
                            f"</span>"
                        )
                elif regel_items_upper: # Nicht erfüllt und Regel hatte Items
                     kontext_erfuellungs_info_html = f" <span class='context-match-info not-fulfilled'>{translate('no_context_in_list', lang)}</span>"


            # Dieser Block ist nur für LKN/ICD Listen, nicht für Geschlecht/GTIN
            if type_prefix in ["LKN", "ICD"]:
                specific_description_html += translate('require_lkn_list' if type_prefix in ['LKN','ICD'] else 'require_gtin_list', lang)
                if not regel_items_upper: specific_description_html += f"<i>{translate('no_lkns_spec' if type_prefix in ['LKN','ICD'] else 'no_gtins_spec', lang)}</i>"
                else: specific_description_html += f"{escape(', '.join(sorted(list(regel_items_upper))))}"

                if condition_met_this_line:
                    erfuellende_details = []
                    for k_kontext in kontext_elemente_fuer_vergleich:
                        if k_kontext in regel_items_upper:
                            desc = get_beschreibung_fuer_lkn_im_backend(k_kontext, leistungskatalog_dict, lang) if type_prefix == 'LKN' else get_beschreibung_fuer_icd_im_backend(
                                k_kontext,
                                tabellen_dict_by_table,
                                lang=lang,
                            )
                            erfuellende_details.append(f"<b>{escape(k_kontext)}</b> ({escape(desc)})")
                    if erfuellende_details:
                        kontext_erfuellungs_info_html = (
                            f" <span class='context-match-info fulfilled'>"
                            f"{translate('fulfilled_by', lang, items=', '.join(erfuellende_details))}"
                            f"</span>"
                        )
                elif regel_items_upper : # Nicht erfüllt UND Regel-Liste hatte Items
                    fehlende_details = []
                    # Zeige Kontext-Elemente, die NICHT in der Regel-Liste waren
                    for k_kontext in kontext_elemente_fuer_vergleich:
                        if k_kontext not in regel_items_upper:
                             desc = get_beschreibung_fuer_lkn_im_backend(k_kontext, leistungskatalog_dict, lang) if type_prefix == 'LKN' else get_beschreibung_fuer_icd_im_backend(
                                 k_kontext,
                                 tabellen_dict_by_table,
                                 lang=lang,
                             )
                             fehlende_details.append(f"<b>{escape(k_kontext)}</b> ({escape(desc)})")
                    if fehlende_details:
                        kontext_erfuellungs_info_html = (
                            f" <span class='context-match-info not-fulfilled'>"
                            f"{translate('context_items_not_in_list', lang, items=', '.join(fehlende_details))}"
                            f"</span>"
                        )
                elif not regel_items_upper: # Nicht erfüllt und Regel-Liste war leer
                     kontext_erfuellungs_info_html = f" <span class='context-match-info not-fulfilled'>{translate('rule_list_empty', lang)}</span>"


        elif bedingungstyp == "PATIENTENBEDINGUNG":
            min_val_regel_html = cond_definition.get('MinWert'); max_val_regel_html = cond_definition.get('MaxWert')
            specific_description_html += f"Patient: Feld='{escape(feld_ref_patientenbed)}'"
            if feld_ref_patientenbed == "Alter":
                age_req_parts = []
                if min_val_regel_html is not None: age_req_parts.append(f"min. {escape(str(min_val_regel_html))}")
                if max_val_regel_html is not None: age_req_parts.append(f"max. {escape(str(max_val_regel_html))}")
                if not age_req_parts and werte_aus_regel: age_req_parts.append(f"exakt {escape(werte_aus_regel)}")
                specific_description_html += f", Anforderung: {(' und '.join(age_req_parts) or 'N/A')}"
                kontext_erfuellungs_info_html = (
                    f" <span class='context-match-info {'fulfilled' if condition_met_this_line else 'not-fulfilled'}'>"
                    f"{translate('context_value', lang, value=escape(str(context.get('Alter', 'N/A'))))}"
                    f"</span>"
                )
            elif feld_ref_patientenbed == "Geschlecht":
                specific_description_html += f", Erwartet='{escape(werte_aus_regel)}'"
                kontext_erfuellungs_info_html = (
                    f" <span class='context-match-info {'fulfilled' if condition_met_this_line else 'not-fulfilled'}'>"
                    f"{translate('context_value', lang, value=escape(str(context.get('Geschlecht', 'N/A'))))}"
                    f"</span>"
                )
            else: # Andere Patientenbedingungen
                specific_description_html += f", Wert/Ref='{escape(werte_aus_regel or feld_ref_patientenbed or '-')}'"
                # Allgemeine Kontextanzeige für andere Felder
                kontext_wert_allg = context.get(feld_ref_patientenbed, 'N/A')
                kontext_erfuellungs_info_html = (
                    f" <span class='context-match-info {'fulfilled' if condition_met_this_line else 'not-fulfilled'}'>"
                    f"{translate('context_value', lang, value=escape(str(kontext_wert_allg)))}"
                    f"</span>"
                )
        
        # Die folgenden elif-Blöcke sind NEU für ANZAHL und SEITIGKEIT
        elif bedingungstyp == "ANZAHL":
            vergleichsop_html = cond_definition.get('Vergleichsoperator', '=')
            specific_description_html += f"Anzahl {escape(vergleichsop_html)} {escape(werte_aus_regel)}"
            kontext_wert_anzahl_html = context.get('Anzahl', 'N/A')
            kontext_erfuellungs_info_html = (
                f" <span class='context-match-info {'fulfilled' if condition_met_this_line else 'not-fulfilled'}'>"
                f"{translate('context_value', lang, value=escape(str(kontext_wert_anzahl_html)))}"
                f"</span>"
            )

        elif bedingungstyp == "SEITIGKEIT":
            vergleichsop_html = cond_definition.get('Vergleichsoperator', '=')
            specific_description_html += f"Seitigkeit {escape(vergleichsop_html)} {escape(werte_aus_regel)}" # Zeige Regelwert wie in DB (z.B. 'B')
            kontext_wert_seitigkeit_html = context.get('Seitigkeit', 'N/A') # Kontext ist schon normalisiert (z.B. 'beidseits')
            kontext_erfuellungs_info_html = (
                f" <span class='context-match-info {'fulfilled' if condition_met_this_line else 'not-fulfilled'}'>"
                f"{translate('context_value', lang, value=escape(str(kontext_wert_seitigkeit_html)))}"
                f"</span>"
            )
        
        # Fallback für noch nicht explizit behandelte Typen in der HTML-Generierung
        else:
            translated_type_fb = translate_condition_type(bedingungstyp, lang)
            specific_description_html += f"Bedingung: {escape(translated_type_fb)} - Wert: {escape(werte_aus_regel or feld_ref_patientenbed or 'N/A')}"
            # Allgemeine Kontextanzeige
            kontext_wert_fallback = "N/A"
            if feld_ref_patientenbed and feld_ref_patientenbed in context:
                kontext_wert_fallback = context.get(feld_ref_patientenbed)
            elif bedingungstyp in context: # Falls der Kontext direkt den Typ als Key hat (unwahrscheinlich hier)
                kontext_wert_fallback = context.get(bedingungstyp)
            kontext_erfuellungs_info_html = (
                f" <span class='context-match-info {'fulfilled' if condition_met_this_line else 'not-fulfilled'}'>"
                f"{translate('context_value', lang, value=escape(str(kontext_wert_fallback)))}"
                f"</span>"
            )


        li_content += f"<span class='condition-text-wrapper'>{specific_description_html}{kontext_erfuellungs_info_html}</span>"
        li_content += "</div>"

        if gruppe_id not in grouped_html_parts: grouped_html_parts[gruppe_id] = []
        grouped_html_parts[gruppe_id].append(li_content)
        
        if not condition_met_this_line:
            # Nur Fehler hinzufügen, wenn die Bedingung tatsächlich relevant für die Gültigkeit war
            # (Diese Logik ist komplexer und hängt von der UND/ODER Auswertung ab,
            # daher hier nur generischer Fehler, wenn Zeile nicht erfüllt)
            errors.append(f"Einzelbedingung '{escape(bedingungstyp)}: {escape(werte_aus_regel)}' (ID: {bedingung_id}) nicht erfüllt.")
        # trigger_lkn_condition_met wird hier nicht mehr gesetzt, da es von der Gesamtlogik abhängt.
    
    final_html = "" 
    final_html_parts = []
    # Sortiere Gruppen-IDs numerisch, falls möglich, sonst alphabetisch. 'Ohne_Gruppe' ans Ende.
    sorted_group_ids = sorted(
        grouped_html_parts.keys(),
        key=lambda x: (isinstance(x, str) and x == 'Ohne_Gruppe', x)
    )


    if not sorted_group_ids:
        final_html = f"<ul><li>{translate('no_valid_groups', lang)}</li></ul>"
    elif len(sorted_group_ids) == 1 and sorted_group_ids[0] == 'Ohne_Gruppe':
         # Spezialfall: Nur Bedingungen ohne explizite Gruppe (implizites UND)
         group_id = sorted_group_ids[0]
         group_html_content = "".join(grouped_html_parts[group_id])
         group_title_text = translate('group_conditions', lang)
         final_html = (
            f"<div class='condition-group'>"
            f"<div class='condition-group-title'>{group_title_text}</div>"
            f"{group_html_content}"
            f"</div>"
        )
    else: # Mehrere Gruppen oder eine definierte Gruppe
        has_defined_groups = any(gid != 'Ohne_Gruppe' for gid in sorted_group_ids)
        is_multigroup_logic = len([gid for gid in sorted_group_ids if gid != 'Ohne_Gruppe']) > 1

        for idx, group_id in enumerate(sorted_group_ids):
            if group_id == 'Ohne_Gruppe' and not has_defined_groups: # Sollte durch obigen Fall abgedeckt sein
                continue

            group_html_content = "".join(grouped_html_parts[group_id])
            
            group_title_text = ""
            if group_id == 'Ohne_Gruppe':
                group_title_text = translate('group_additional', lang)
            else:
                group_title_text = translate('group_logic', lang, id=escape(str(group_id)))

            group_wrapper_html = (
                f"<div class='condition-group'>"
                f"<div class='condition-group-title'>{group_title_text}</div>"
                f"{group_html_content}"
                f"</div>"
            )
            final_html_parts.append(group_wrapper_html)

            # Füge "ODER" nur zwischen definierten Gruppen hinzu, wenn es mehrere davon gibt
            if group_id != 'Ohne_Gruppe' and is_multigroup_logic and \
               idx < len([gid for gid in sorted_group_ids if gid != 'Ohne_Gruppe']) -1 :
                final_html_parts.append(
                    f"<div class='condition-separator'>{translate('or_separator', lang)}</div>"
                )
        
        final_html = "".join(final_html_parts)

    # Das 'trigger_lkn_condition_met' Flag sollte idealerweise von der aufrufenden Logik
    # (determine_applicable_pauschale) basierend auf der *ausgewählten* Pauschale und deren
    # erfüllten Bedingungen bestimmt werden, nicht global hier.
    # Fürs Erste lassen wir es hier, aber es ist nicht ganz präzise.
    # Besser: determine_applicable_pauschale prüft, ob die gewählte Pauschale eine LKN-Bedingung hatte, die erfüllt wurde.
    final_trigger_lkn_met = False
    if evaluate_structured_conditions(pauschale_code, context, pauschale_bedingungen_data, tabellen_dict_by_table):
        # Prüfe, ob irgendeine erfüllte LKN-Bedingung in den *gültigen* Gruppen existiert
        for cond_def in conditions_for_this_pauschale:
            cond_typ = cond_def.get(BED_TYP_KEY, "").upper()
            if ("LEISTUNGSPOSITIONEN" in cond_typ or "TARIFPOSITIONEN" in cond_typ or "LKN" in cond_typ) and \
               check_single_condition(cond_def, context, tabellen_dict_by_table):
                final_trigger_lkn_met = True
                break


    return {"html": final_html, "errors": errors, "trigger_lkn_condition_met": final_trigger_lkn_met}


# --- Ausgelagerte Pauschalen-Ermittlung ---
def determine_applicable_pauschale(
    user_input: str, # Bleibt für potenzielles LLM-Ranking, aktuell nicht primär genutzt
    rule_checked_leistungen: list[dict], # Für die initiale Findung potenzieller Pauschalen
    context: dict, # Enthält LKN, ICD, Alter, Geschlecht, Seitigkeit, Anzahl, useIcd
    pauschale_lp_data: List[Dict],
    pauschale_bedingungen_data: List[Dict],
    pauschalen_dict: Dict[str, Dict], # Dict aller Pauschalen {code: details}
    leistungskatalog_dict: Dict[str, Dict], # Für LKN-Beschreibungen etc.
    tabellen_dict_by_table: Dict[str, List[Dict]], # Für Tabellen-Lookups
    potential_pauschale_codes_input: Set[str] | None = None, # Optional vorabgefilterte Codes
    lang: str = 'de'
    ) -> dict:
    """
    Ermittelt die anwendbarste Pauschale durch Auswertung der strukturierten Bedingungen.
    """
    print("INFO: Starte Pauschalenermittlung mit strukturierter Bedingungsprüfung...")
    PAUSCHALE_ERKLAERUNG_KEY = 'pauschale_erklaerung_html'; POTENTIAL_ICDS_KEY = 'potential_icds'
    LKN_KEY_IN_RULE_CHECKED = 'lkn'; PAUSCHALE_KEY_IN_PAUSCHALEN = 'Pauschale' # In PAUSCHALEN_Pauschalen
    PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN = 'Pauschale_Text'
    LP_LKN_KEY = 'Leistungsposition'; LP_PAUSCHALE_KEY = 'Pauschale' # In PAUSCHALEN_Leistungspositionen
    BED_PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp' # In PAUSCHALEN_Bedingungen
    BED_WERTE_KEY = 'Werte'

    potential_pauschale_codes: Set[str] = set()
    if potential_pauschale_codes_input is not None:
        potential_pauschale_codes = potential_pauschale_codes_input
        print(f"DEBUG: Verwende übergebene potenzielle Pauschalen: {potential_pauschale_codes}")
    else:
        print("DEBUG: Suche potenzielle Pauschalen (da nicht übergeben)...")
        # LKNs aus dem Kontext (regelkonform + gemappt) für die Suche verwenden
        context_lkns_for_search = {str(lkn).upper() for lkn in context.get("LKN", []) if lkn}
        # print(f"  Kontext-LKNs für Suche: {context_lkns_for_search}")

        # Methode a: Direkte Links aus PAUSCHALEN_Leistungspositionen
        for item in pauschale_lp_data:
            lkn_in_lp = item.get(LP_LKN_KEY)
            if lkn_in_lp and lkn_in_lp.upper() in context_lkns_for_search:
                pc = item.get(LP_PAUSCHALE_KEY)
                if pc and pc in pauschalen_dict: potential_pauschale_codes.add(pc)
        # print(f"  Potenzielle Pauschalen nach Methode a: {potential_pauschale_codes}")

        # Methode b & c: LKNs in Bedingungen (Liste oder Tabelle)
        # Cache für Tabellenzugehörigkeit von Kontext-LKNs
        context_lkns_in_tables_cache: Dict[str, Set[str]] = {}

        for cond in pauschale_bedingungen_data:
            pc = cond.get(BED_PAUSCHALE_KEY)
            if not (pc and pc in pauschalen_dict): continue # Nur für existierende Pauschalen

            bedingungstyp_cond = cond.get(BED_TYP_KEY, "").upper()
            werte_cond = cond.get(BED_WERTE_KEY, "")

            if bedingungstyp_cond == "LEISTUNGSPOSITIONEN IN LISTE" or bedingungstyp_cond == "LKN":
                werte_liste_cond = {w.strip().upper() for w in str(werte_cond).split(',') if w.strip()}
                if not context_lkns_for_search.isdisjoint(werte_liste_cond): # Schnittmenge nicht leer
                    potential_pauschale_codes.add(pc)

            elif bedingungstyp_cond == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp_cond == "TARIFPOSITIONEN IN TABELLE":
                table_refs_cond = {t.strip().lower() for t in str(werte_cond).split(',') if t.strip()}
                for lkn_ctx in context_lkns_for_search:
                    if lkn_ctx not in context_lkns_in_tables_cache:
                        tables_for_lkn_ctx = set()
                        for table_name_key_norm, table_entries in tabellen_dict_by_table.items():
                            for entry in table_entries:
                                if entry.get('Code', '').upper() == lkn_ctx and \
                                   entry.get('Tabelle_Typ', '').lower() == "service_catalog":
                                    tables_for_lkn_ctx.add(table_name_key_norm) # Bereits normalisiert (lower)
                        context_lkns_in_tables_cache[lkn_ctx] = tables_for_lkn_ctx
                    
                    if not table_refs_cond.isdisjoint(context_lkns_in_tables_cache[lkn_ctx]):
                        potential_pauschale_codes.add(pc)
                        break # Ein Treffer für diese Bedingung reicht
        print(f"DEBUG: Finale potenzielle Pauschalen nach LKN-basierter Suche: {potential_pauschale_codes}")


    if not potential_pauschale_codes:
        return {"type": "Error", "message": "Keine potenziellen Pauschalen für die erbrachten Leistungen und den Kontext gefunden."}

    evaluated_candidates = []
    # print(f"INFO: Werte strukturierte Bedingungen für {len(potential_pauschale_codes)} potenzielle Pauschalen aus...")
    # print(f"  Kontext für evaluate_structured_conditions: {context}")
    for code in sorted(list(potential_pauschale_codes)): # Sortiert für konsistente Log-Reihenfolge
        if code not in pauschalen_dict:
            # print(f"  WARNUNG: Potenzieller Code {code} nicht in pauschalen_dict gefunden, überspringe.")
            continue
        
        is_pauschale_valid_structured = False
        try:
            # print(f"  Prüfe Pauschale: {code}...")
            is_pauschale_valid_structured = evaluate_structured_conditions(
                code, context, pauschale_bedingungen_data, tabellen_dict_by_table
            )
            # print(f"    -> Ergebnis für {code}: {is_pauschale_valid_structured}")
        except Exception as e_eval:
            print(f"FEHLER bei evaluate_structured_conditions für Pauschale {code}: {e_eval}")
            traceback.print_exc()
            # Behandle als nicht valide, wenn Fehler auftritt
        
        evaluated_candidates.append({
            "code": code,
            "details": pauschalen_dict[code],
            "is_valid_structured": is_pauschale_valid_structured
        })

    valid_candidates = [cand for cand in evaluated_candidates if cand["is_valid_structured"]]
    print(f"DEBUG: Struktur-gültige Kandidaten nach Prüfung: {[c['code'] for c in valid_candidates]}")

    selected_candidate_info = None
    if valid_candidates:
        specific_valid_candidates = [c for c in valid_candidates if not str(c['code']).startswith('C9')]
        fallback_valid_candidates = [c for c in valid_candidates if str(c['code']).startswith('C9')]
        
        chosen_list_for_selection = []
        selection_type_message = ""

        if specific_valid_candidates:
            chosen_list_for_selection = specific_valid_candidates
            selection_type_message = "spezifischen"
        elif fallback_valid_candidates: # Nur wenn keine spezifischen gültig sind
            chosen_list_for_selection = fallback_valid_candidates
            selection_type_message = "Fallback (C9x)"
        
        if chosen_list_for_selection:
            print(f"INFO: Auswahl aus {len(chosen_list_for_selection)} struktur-gültigen {selection_type_message} Kandidaten.")
            
            # Sortierung: A vor B vor E (d.h. Suffix-Buchstabe aufsteigend)
            def sort_key_pauschale_suffix(candidate):
                code_str = str(candidate['code'])
                match = re.match(r"([A-Z0-9.]+)([A-Z])$", code_str)
                if match:
                    return (match.group(1), ord(match.group(2))) # Stamm, dann ASCII des Suffix
                return (code_str, 0) # Kein Suffix oder unerwartetes Format

            chosen_list_for_selection.sort(key=sort_key_pauschale_suffix)
            selected_candidate_info = chosen_list_for_selection[0] # Die "einfachste" passende (A ist besser als B)
            print(f"INFO: Gewählte Pauschale nach Sortierung (Suffix A-Z -> einfachste zuerst): {selected_candidate_info['code']}")
            # print(f"   DEBUG: Sortierte Kandidatenliste ({selection_type_message}): {[c['code'] for c in chosen_list_for_selection]}")
        else:
             # Sollte nicht passieren, wenn valid_candidates nicht leer war, aber zur Sicherheit
             return {"type": "Error", "message": "Interner Fehler bei der Pauschalenauswahl (Kategorisierung fehlgeschlagen)."}
    else: # Keine valid_candidates (keine Pauschale hat die strukturierte Prüfung bestanden)
        print("INFO: Keine Pauschale erfüllt die strukturierten Bedingungen.")
        # Erstelle eine informativere Nachricht, wenn potenzielle Kandidaten da waren
        if potential_pauschale_codes:
            # Hole die Namen der geprüften, aber nicht validen Pauschalen
            gepruefte_codes_namen = [f"{c['code']} ({get_lang_field(c['details'], PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, lang) or 'N/A'})"
                                     for c in evaluated_candidates if not c['is_valid_structured']]
            msg_details = ""
            if gepruefte_codes_namen:
                msg_details = " Folgende potenziellen Pauschalen wurden geprüft, aber deren Bedingungen waren nicht erfüllt: " + ", ".join(gepruefte_codes_namen)

            return {"type": "Error", "message": f"Keine der potenziellen Pauschalen erfüllte die detaillierten UND/ODER-Bedingungen.{msg_details}"}
        else: # Sollte durch die Prüfung am Anfang von potential_pauschale_codes abgedeckt sein
            return {"type": "Error", "message": "Keine passende Pauschale gefunden (keine potenziellen Kandidaten)."}

    if not selected_candidate_info: # Doppelte Sicherheit
        return {"type": "Error", "message": "Interner Fehler: Keine Pauschale nach Auswahlprozess selektiert."}

    best_pauschale_code = selected_candidate_info["code"]
    best_pauschale_details = selected_candidate_info["details"].copy() # Kopie für Modifikationen

    # Generiere HTML für die Bedingungsprüfung der ausgewählten Pauschale
    bedingungs_pruef_html_result = f"<p><i>{translate('detail_html_not_generated', lang)}</i></p>"
    condition_errors_html_gen = []
    try:
        condition_result_html_dict = check_pauschale_conditions(
            best_pauschale_code,
            context,
            pauschale_bedingungen_data,
            tabellen_dict_by_table,
            leistungskatalog_dict,
            lang
        )
        bedingungs_pruef_html_result = condition_result_html_dict.get("html", "<p class='error'>Fehler bei HTML-Generierung der Bedingungen.</p>")
        condition_errors_html_gen = condition_result_html_dict.get("errors", [])
    except Exception as e_html_gen:
         print(f"FEHLER bei check_pauschale_conditions (HTML-Generierung) für {best_pauschale_code}: {e_html_gen}")
         traceback.print_exc()
         bedingungs_pruef_html_result = f"<p class='error'>Schwerwiegender Fehler bei HTML-Generierung der Bedingungen: {escape(str(e_html_gen))}</p>"
         condition_errors_html_gen = [f"Fehler HTML-Generierung: {e_html_gen}"]

    # Erstelle die Erklärung für die Pauschalenauswahl
    # Kontext-LKNs für die Erklärung (aus dem `context` Dictionary)
    lkns_fuer_erklaerung = [str(lkn) for lkn in context.get('LKN', []) if lkn]
    if lang == 'fr':
        pauschale_erklaerung_html = (
            f"<p>Sur la base du contexte (p.ex. LKN : {escape(', '.join(lkns_fuer_erklaerung) or 'aucun')}, "
            f"latéralité : {escape(str(context.get('Seitigkeit')))}, nombre : {escape(str(context.get('Anzahl')))}, "
            f"vérification ICD active : {context.get('useIcd', True)}) les forfaits suivants ont été vérifiés :</p>"
        )
    elif lang == 'it':
        pauschale_erklaerung_html = (
            f"<p>Sulla base del contesto (ad es. LKN: {escape(', '.join(lkns_fuer_erklaerung) or 'nessuna')}, "
            f"lateralità: {escape(str(context.get('Seitigkeit')))}, numero: {escape(str(context.get('Anzahl')))}, "
            f"verifica ICD attiva: {context.get('useIcd', True)}) sono stati verificati i seguenti forfait:</p>"
        )
    else:
        pauschale_erklaerung_html = (
            f"<p>Basierend auf dem Kontext (u.a. LKNs: {escape(', '.join(lkns_fuer_erklaerung) or 'keine')}, "
            f"Seitigkeit: {escape(str(context.get('Seitigkeit')))}, Anzahl: {escape(str(context.get('Anzahl')))}, "
            f"ICD-Prüfung aktiv: {context.get('useIcd', True)}) wurden folgende Pauschalen geprüft:</p>"
        )
    
    # Liste aller potenziell geprüften Pauschalen (vor der Validierung)
    pauschale_erklaerung_html += "<ul>"
    for cand_eval in sorted(evaluated_candidates, key=lambda x: x['code']):
        if cand_eval['is_valid_structured']:
            status = translate('conditions_met', lang)
            status_text = f"<span style=\"color:green;\">{status}</span>"
        else:
            status = translate('conditions_not_met', lang)
            status_text = f"<span style=\"color:red;\">{status}</span>"
        pauschale_erklaerung_html += (
            f"<li><b>{escape(cand_eval['code'])}</b>: "
            f"{escape(get_lang_field(cand_eval['details'], PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, lang) or 'N/A')} "
            f"{status_text}</li>"
        )
    pauschale_erklaerung_html += "</ul>"
    
    if lang == 'fr':
        pauschale_erklaerung_html += (
            f"<p><b>Choix : {escape(best_pauschale_code)}</b> "
            f"({escape(get_lang_field(best_pauschale_details, PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, lang) or 'N/A')}) - "
            "comme forfait avec la lettre suffixe la plus basse (p. ex. A avant B) parmi les candidats valides "
            "de la catégorie privilégiée (forfaits spécifiques avant forfaits de secours C9x).</p>"
        )
    elif lang == 'it':
        pauschale_erklaerung_html += (
            f"<p><b>Selezionato: {escape(best_pauschale_code)}</b> "
            f"({escape(get_lang_field(best_pauschale_details, PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, lang) or 'N/A')}) - "
            "come forfait con la lettera suffisso più bassa (es. A prima di B) tra i candidati validi "
            "della categoria preferita (forfait specifici prima dei forfait di fallback C9x).</p>"
        )
    else:
        pauschale_erklaerung_html += (
            f"<p><b>Ausgewählt wurde: {escape(best_pauschale_code)}</b> "
            f"({escape(get_lang_field(best_pauschale_details, PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, lang) or 'N/A')}) - "
            f"als die Pauschale mit dem niedrigsten Suffix-Buchstaben (z.B. A vor B) unter den gültigen Kandidaten "
            f"der bevorzugten Kategorie (spezifische Pauschalen vor Fallback-Pauschalen C9x).</p>"
        )

    # Vergleich mit anderen Pauschalen der gleichen Gruppe (Stamm)
    match_stamm = re.match(r"([A-Z0-9.]+)([A-Z])$", str(best_pauschale_code))
    pauschalen_stamm_code = match_stamm.group(1) if match_stamm else None
    
    if pauschalen_stamm_code:
        # Finde andere *potenzielle* Pauschalen (aus evaluated_candidates) in derselben Gruppe
        other_evaluated_codes_in_group = [
            cand for cand in evaluated_candidates
            if str(cand['code']).startswith(pauschalen_stamm_code) and str(cand['code']) != best_pauschale_code
        ]
        if other_evaluated_codes_in_group:
            if lang == 'fr':
                pauschale_erklaerung_html += f"<hr><p><b>Comparaison avec d'autres forfaits du groupe '{escape(pauschalen_stamm_code)}':</b></p>"
            elif lang == 'it':
                pauschale_erklaerung_html += f"<hr><p><b>Confronto con altri forfait del gruppo '{escape(pauschalen_stamm_code)}':</b></p>"
            else:
                pauschale_erklaerung_html += f"<hr><p><b>Vergleich mit anderen Pauschalen der Gruppe '{escape(pauschalen_stamm_code)}':</b></p>"
            selected_conditions_repr_set = get_simplified_conditions(best_pauschale_code, pauschale_bedingungen_data)

            for other_cand in sorted(other_evaluated_codes_in_group, key=lambda x: x['code']):
                other_code_str = str(other_cand['code'])
                other_details_dict = other_cand['details']
                other_was_valid_structured = other_cand['is_valid_structured']
                if other_was_valid_structured:
                    status = translate('conditions_also_met', lang)
                    validity_info_html = f"<span style=\"color:green;\">{status}</span>"
                else:
                    status = translate('conditions_not_met', lang)
                    validity_info_html = f"<span style=\"color:red;\">{status}</span>"

                other_conditions_repr_set = get_simplified_conditions(other_code_str, pauschale_bedingungen_data)
                additional_conditions_for_other = other_conditions_repr_set - selected_conditions_repr_set
                missing_conditions_in_other = selected_conditions_repr_set - other_conditions_repr_set

                diff_label = translate('diff_to', lang)
                pauschale_erklaerung_html += (
                    f"<details style='margin-left: 15px; font-size: 0.9em;'>"
                    f"<summary>{diff_label} <b>{escape(other_code_str)}</b> ({escape(get_lang_field(other_details_dict, PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, lang) or 'N/A')}) {validity_info_html}</summary>"
                )

                if additional_conditions_for_other:
                    if lang == 'fr':
                        pauschale_erklaerung_html += f"<p>Exigences supplémentaires / autres pour {escape(other_code_str)}:</p><ul>"
                    elif lang == 'it':
                        pauschale_erklaerung_html += f"<p>Requisiti supplementari / altri per {escape(other_code_str)}:</p><ul>"
                    else:
                        pauschale_erklaerung_html += f"<p>Zusätzliche/Andere Anforderungen für {escape(other_code_str)}:</p><ul>"
                    for cond_tuple_item in sorted(list(additional_conditions_for_other)):
                        condition_html_detail_item = generate_condition_detail_html(cond_tuple_item, leistungskatalog_dict, tabellen_dict_by_table, lang)
                        pauschale_erklaerung_html += condition_html_detail_item
                    pauschale_erklaerung_html += "</ul>"
                  
                if missing_conditions_in_other:
                    if lang == 'fr':
                        pauschale_erklaerung_html += f"<p>Les exigences suivantes de {escape(best_pauschale_code)} manquent pour {escape(other_code_str)}:</p><ul>"
                    elif lang == 'it':
                        pauschale_erklaerung_html += f"<p>I seguenti requisiti di {escape(best_pauschale_code)} mancano in {escape(other_code_str)}:</p><ul>"
                    else:
                        pauschale_erklaerung_html += f"<p>Folgende Anforderungen von {escape(best_pauschale_code)} fehlen bei {escape(other_code_str)}:</p><ul>"
                    for cond_tuple_item in sorted(list(missing_conditions_in_other)):
                        condition_html_detail_item = generate_condition_detail_html(cond_tuple_item, leistungskatalog_dict, tabellen_dict_by_table, lang)
                        pauschale_erklaerung_html += condition_html_detail_item
                    pauschale_erklaerung_html += "</ul>"

                if not additional_conditions_for_other and not missing_conditions_in_other:
                    if lang == 'fr':
                        pauschale_erklaerung_html += "<p><i>Aucune différence de conditions essentielles trouvée (basé sur un contrôle simplifié type/valeur). Des différences détaillées peuvent exister au niveau du nombre ou de groupes logiques spécifiques.</i></p>"
                    elif lang == 'it':
                        pauschale_erklaerung_html += "<p><i>Nessuna differenza nelle condizioni principali trovata (basato su un confronto semplificato tipo/valore). Differenze dettagliate possibili nel numero o in gruppi logici specifici.</i></p>"
                    else:
                        pauschale_erklaerung_html += "<p><i>Keine unterschiedlichen Kernbedingungen gefunden (basierend auf vereinfachter Typ/Wert-Prüfung). Detaillierte Unterschiede können in der Anzahl oder spezifischen Logikgruppen liegen.</i></p>"
                pauschale_erklaerung_html += "</details>"
    
    best_pauschale_details[PAUSCHALE_ERKLAERUNG_KEY] = pauschale_erklaerung_html

    # Potenzielle ICDs für die ausgewählte Pauschale sammeln
    potential_icds_list = []
    pauschale_conditions_for_selected = [
        cond for cond in pauschale_bedingungen_data if cond.get(BED_PAUSCHALE_KEY) == best_pauschale_code
    ]
    for cond_item_icd in pauschale_conditions_for_selected:
        if cond_item_icd.get(BED_TYP_KEY, "").upper() == "HAUPTDIAGNOSE IN TABELLE":
            tabelle_ref_icd = cond_item_icd.get(BED_WERTE_KEY)
            if tabelle_ref_icd:
                icd_entries_list = get_table_content(tabelle_ref_icd, "icd", tabellen_dict_by_table, lang)
                for entry_icd in icd_entries_list:
                    code_icd = entry_icd.get('Code'); text_icd = entry_icd.get('Code_Text')
                    if code_icd: potential_icds_list.append({"Code": code_icd, "Code_Text": text_icd or "N/A"})
    
    unique_icds_dict_result = {icd_item['Code']: icd_item for icd_item in potential_icds_list if icd_item.get('Code')}
    best_pauschale_details[POTENTIAL_ICDS_KEY] = sorted(unique_icds_dict_result.values(), key=lambda x: x['Code'])

    final_result_dict = {
        "type": "Pauschale",
        "details": best_pauschale_details,
        "bedingungs_pruef_html": bedingungs_pruef_html_result,
        "bedingungs_fehler": condition_errors_html_gen, # Fehler aus der HTML-Generierung
        "conditions_met": True # Da wir hier nur landen, wenn eine Pauschale als gültig ausgewählt wurde
    }
    return final_result_dict


# --- HILFSFUNKTIONEN (auf Modulebene) ---
def get_simplified_conditions(pauschale_code: str, bedingungen_data: list[dict]) -> set:
    """
    Wandelt Bedingungen in eine vereinfachte, vergleichbare Darstellung (Set von Tupeln) um.
    Dies dient dazu, Unterschiede zwischen Pauschalen auf einer höheren Ebene zu identifizieren.
    Die Logik hier muss nicht alle Details der `check_single_condition` abbilden,
    sondern eher die Art und den Hauptwert der Bedingung.
    """
    simplified_set = set()
    PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'
    BED_FELD_KEY = 'Feld'; BED_MIN_KEY = 'MinWert'; BED_MAX_KEY = 'MaxWert'
    BED_VERGLEICHSOP_KEY = 'Vergleichsoperator' # Hinzugefügt
    
    pauschale_conditions = [cond for cond in bedingungen_data if cond.get(PAUSCHALE_KEY) == pauschale_code]

    for cond in pauschale_conditions:
        typ_original = cond.get(BED_TYP_KEY, "").upper()
        wert = str(cond.get(BED_WERTE_KEY, "")).strip() # String und strip
        feld = str(cond.get(BED_FELD_KEY, "")).strip()
        vergleichsop = str(cond.get(BED_VERGLEICHSOP_KEY, "=")).strip() # Default '='
        
        condition_tuple = None
        # Normalisiere Typen für den Vergleich
        # Ziel ist es, semantisch ähnliche Bedingungen gleich zu behandeln
        
        final_cond_type_for_comparison = typ_original # Default

        if typ_original in ["LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE", "LKN IN TABELLE"]:
            final_cond_type_for_comparison = 'LKN_TABLE'
            condition_tuple = (final_cond_type_for_comparison, tuple(sorted([t.strip().lower() for t in wert.split(',') if t.strip()]))) # Tabellennamen als sortiertes Tuple
        elif typ_original in ["HAUPTDIAGNOSE IN TABELLE", "ICD IN TABELLE"]:
            final_cond_type_for_comparison = 'ICD_TABLE'
            condition_tuple = (final_cond_type_for_comparison, tuple(sorted([t.strip().lower() for t in wert.split(',') if t.strip()])))
        elif typ_original in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN"]:
            final_cond_type_for_comparison = 'LKN_LIST'
            condition_tuple = (final_cond_type_for_comparison, tuple(sorted([lkn.strip().upper() for lkn in wert.split(',') if lkn.strip()]))) # LKNs als sortiertes Tuple
        elif typ_original in ["HAUPTDIAGNOSE IN LISTE", "ICD"]:
             final_cond_type_for_comparison = 'ICD_LIST'
             condition_tuple = (final_cond_type_for_comparison, tuple(sorted([icd.strip().upper() for icd in wert.split(',') if icd.strip()])))
        elif typ_original in ["MEDIKAMENTE IN LISTE", "GTIN"]:
            final_cond_type_for_comparison = 'GTIN_LIST'
            condition_tuple = (final_cond_type_for_comparison, tuple(sorted([gtin.strip() for gtin in wert.split(',') if gtin.strip()])))
        elif typ_original == "PATIENTENBEDINGUNG" and feld:
            final_cond_type_for_comparison = f'PATIENT_{feld.upper()}' # z.B. PATIENT_ALTER
            # Für Alter mit Min/Max eine normalisierte Darstellung
            if feld.lower() == "alter":
                min_w = cond.get(BED_MIN_KEY)
                max_w = cond.get(BED_MAX_KEY)
                if min_w is not None or max_w is not None:
                    wert_repr = f"min:{min_w or '-'}_max:{max_w or '-'}"
                else:
                    wert_repr = f"exact:{wert}"
                condition_tuple = (final_cond_type_for_comparison, wert_repr)
            else: # Für andere Patientenbedingungen (z.B. Geschlecht)
                condition_tuple = (final_cond_type_for_comparison, wert.lower())
        elif typ_original == "ANZAHL":
            final_cond_type_for_comparison = 'ANZAHL_CHECK'
            condition_tuple = (final_cond_type_for_comparison, f"{vergleichsop}{wert}")
        elif typ_original == "SEITIGKEIT":
            final_cond_type_for_comparison = 'SEITIGKEIT_CHECK'
            # Normalisiere den Regelwert für den Vergleich (z.B. 'B' -> 'beidseits')
            norm_regel_wert = wert.strip().replace("'", "").lower()
            if norm_regel_wert == 'b': norm_regel_wert = 'beidseits'
            elif norm_regel_wert == 'e': norm_regel_wert = 'einseitig' # Vereinfachung für Vergleich
            condition_tuple = (final_cond_type_for_comparison, f"{vergleichsop}{norm_regel_wert}")
        elif typ_original == "GESCHLECHT IN LISTE": # Bereits oben durch PATIENT_GESCHLECHT abgedeckt, wenn Feld gesetzt ist
            final_cond_type_for_comparison = 'GESCHLECHT_LIST_CHECK'
            condition_tuple = (final_cond_type_for_comparison, tuple(sorted([g.strip().lower() for g in wert.split(',') if g.strip()])))
        else:
            # Fallback für unbekannte oder nicht spezifisch behandelte Typen
            # print(f"  WARNUNG: get_simplified_conditions: Unbehandelter Typ '{typ_original}' für Pauschale {pauschale_code}. Verwende Originaltyp und Wert.")
            condition_tuple = (typ_original, wert) # Als Fallback
            
        if condition_tuple:
            simplified_set.add(condition_tuple)
        # else:
            # print(f"  WARNUNG: get_simplified_conditions konnte für Pauschale {pauschale_code} Typ '{typ_original}' mit Wert '{wert}' kein Tupel erzeugen.")
            
    return simplified_set


def generate_condition_detail_html(
    condition_tuple: tuple,
    leistungskatalog_dict: Dict, # Für LKN-Beschreibungen
    tabellen_dict_by_table: Dict,  # Für Tabelleninhalte und ICD-Beschreibungen
    lang: str = 'de'
    ) -> str:
    """
    Generiert HTML für eine einzelne vereinfachte Bedingung (aus get_simplified_conditions)
    im Vergleichsabschnitt der Pauschalenerklärung.
    """
    cond_type_comp, cond_value_comp = condition_tuple # cond_value_comp kann String oder Tuple sein
    condition_html = "<li>"

    try:
        # Formatierung basierend auf dem normalisierten Typ aus get_simplified_conditions
        if cond_type_comp == 'LKN_LIST':
            condition_html += translate('require_lkn_list', lang)
            if not cond_value_comp: # cond_value_comp ist hier ein Tuple von LKNs
                condition_html += f"<i>{translate('no_lkns_spec', lang)}</i>"
            else:
                lkn_details_html_parts = []
                for lkn_code in cond_value_comp: # Iteriere über das Tuple
                    beschreibung = get_beschreibung_fuer_lkn_im_backend(lkn_code, leistungskatalog_dict, lang)
                    lkn_details_html_parts.append(f"<b>{html.escape(lkn_code)}</b> ({html.escape(beschreibung)})")
                condition_html += ", ".join(lkn_details_html_parts)

        elif cond_type_comp == 'LKN_TABLE':
            condition_html += translate('require_lkn_table', lang)
            if not cond_value_comp: # cond_value_comp ist Tuple von Tabellennamen
                condition_html += f"<i>{translate('no_table_name', lang)}</i>"
            else:
                table_links_html_parts = []
                for table_name_norm in cond_value_comp: # Iteriere über Tuple von normalisierten Tabellennamen
                    # Hole Original-Tabellenname, falls möglich (für Anzeige), sonst normalisierten
                    # Dies ist schwierig ohne die Original-Bedingungsdaten hier.
                    # Wir verwenden den normalisierten Namen für get_table_content.
                    table_content_entries = get_table_content(table_name_norm, "service_catalog", tabellen_dict_by_table, lang)
                    entry_count = len(table_content_entries)
                    details_content_html = ""
                    if table_content_entries:
                        details_content_html = "<ul style='margin-top: 5px; font-size: 0.9em; max-height: 150px; overflow-y: auto; border-top: 1px solid #eee; padding-top: 5px; padding-left: 15px; list-style-position: inside;'>"
                        for item in sorted(table_content_entries, key=lambda x: x.get('Code', '')):
                            item_code = item.get('Code', 'N/A'); item_text = get_beschreibung_fuer_lkn_im_backend(item_code, leistungskatalog_dict, lang)
                            details_content_html += f"<li><b>{html.escape(item_code)}</b>: {html.escape(item_text)}</li>"
                        details_content_html += "</ul>"
                    entries_label = translate('entries_label', lang)
                    table_detail_html = (
                        f"<details class='inline-table-details-comparison'>"
                        f"<summary>{html.escape(table_name_norm.upper())}</summary> ({entry_count} {entries_label}){details_content_html}</details>"
                    )
                    table_links_html_parts.append(table_detail_html)
                condition_html += ", ".join(table_links_html_parts)

        elif cond_type_comp == 'ICD_TABLE':
            condition_html += translate('require_icd_table', lang)
            if not cond_value_comp: # Tuple von Tabellennamen
                condition_html += f"<i>{translate('no_table_name', lang)}</i>"
            else:
                table_links_html_parts = []
                for table_name_norm in cond_value_comp:
                    table_content_entries = get_table_content(table_name_norm, "icd", tabellen_dict_by_table, lang)
                    entry_count = len(table_content_entries)
                    details_content_html = ""
                    if table_content_entries:
                        details_content_html = "<ul>"
                        for item in sorted(table_content_entries, key=lambda x: x.get('Code', '')):
                            item_code = item.get('Code', 'N/A'); item_text = item.get('Code_Text', 'N/A')
                            details_content_html += f"<li><b>{html.escape(item_code)}</b>: {html.escape(item_text)}</li>"
                        details_content_html += "</ul>"
                    entries_label = translate('entries_label', lang)
                    table_detail_html = (
                        f"<details class='inline-table-details-comparison'>"
                        f"<summary>{html.escape(table_name_norm.upper())}</summary> ({entry_count} {entries_label}){details_content_html}</details>"
                    )
                    table_links_html_parts.append(table_detail_html)
                condition_html += ", ".join(table_links_html_parts)

        elif cond_type_comp == 'ICD_LIST':
            condition_html += translate('require_icd_list', lang)
            if not cond_value_comp: # Tuple von ICDs
                condition_html += f"<i>{translate('no_icds_spec', lang)}</i>"
            else:
                icd_details_html_parts = []
                for icd_code in cond_value_comp:
                    beschreibung = get_beschreibung_fuer_icd_im_backend(icd_code, tabellen_dict_by_table, lang=lang)
                    icd_details_html_parts.append(f"<b>{html.escape(icd_code)}</b> ({html.escape(beschreibung)})")
                condition_html += ", ".join(icd_details_html_parts)
        
        elif cond_type_comp == 'GTIN_LIST':
            condition_html += translate('require_gtin_list', lang)
            if not cond_value_comp: condition_html += f"<i>{translate('no_gtins_spec', lang)}</i>"
            else: condition_html += html.escape(", ".join(cond_value_comp))
        
        elif cond_type_comp.startswith('PATIENT_'):
            feld_name = cond_type_comp.split('_', 1)[1].capitalize()
            condition_html += translate('patient_condition', lang, field=html.escape(feld_name), value=html.escape(str(cond_value_comp)))
        
        elif cond_type_comp == 'ANZAHL_CHECK':
            condition_html += translate('anzahl_condition', lang, value=html.escape(str(cond_value_comp)))

        elif cond_type_comp == 'SEITIGKEIT_CHECK':
            condition_html += translate('seitigkeit_condition', lang, value=html.escape(str(cond_value_comp)))
        
        elif cond_type_comp == 'GESCHLECHT_LIST_CHECK':
            condition_html += translate('geschlecht_list', lang)
            if not cond_value_comp: condition_html += f"<i>{translate('no_gender_spec', lang)}</i>"
            else: condition_html += html.escape(", ".join(cond_value_comp))

        else: # Allgemeiner Fallback für andere Typen aus get_simplified_conditions
            condition_html += f"{html.escape(cond_type_comp)}: {html.escape(str(cond_value_comp))}"

    except Exception as e_detail_gen:
        print(f"FEHLER beim Erstellen der Detailansicht für Vergleichs-Bedingung '{condition_tuple}': {e_detail_gen}")
        traceback.print_exc()
        condition_html += f"<i>Fehler bei Detailgenerierung: {html.escape(str(e_detail_gen))}</i>"
    
    condition_html += "</li>"
    return condition_html
