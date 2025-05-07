# regelpruefer_pauschale.py (Version mit korrigiertem Import und 9 Argumenten)
import traceback
import json
from typing import Dict, List, Any, Set # <-- Set hier importieren
from utils import escape, get_table_content
import re, html

# === FUNKTION ZUR PRÜFUNG EINER EINZELNEN BEDINGUNG ===
def check_single_condition(
    condition: Dict,
    context: Dict,
    tabellen_dict_by_table: Dict[str, List[Dict]]
) -> bool:
    """Prüft eine einzelne Bedingungszeile und gibt True/False zurück."""
    check_icd_conditions_at_all = context.get("useIcd", True)
    BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'; BED_FELD_KEY = 'Feld'
    BED_MIN_KEY = 'MinWert'; BED_MAX_KEY = 'MaxWert'
    bedingungstyp = condition.get(BED_TYP_KEY, "").upper()
    werte_str = condition.get(BED_WERTE_KEY, "")
    feld_ref = condition.get(BED_FELD_KEY); min_val = condition.get(BED_MIN_KEY)
    max_val = condition.get(BED_MAX_KEY); wert_regel = condition.get(BED_WERTE_KEY)
    provided_icds_upper = {p_icd.upper() for p_icd in context.get("ICD", []) if p_icd}
    provided_gtins = set(context.get("GTIN", []))
    provided_lkns_upper = {p_lkn.upper() for p_lkn in context.get("LKN", []) if p_lkn}
    provided_alter = context.get("Alter"); provided_geschlecht_str = context.get("Geschlecht")

    try:
        if bedingungstyp == "ICD":
            if not check_icd_conditions_at_all: return True
            required_icds_in_rule_list = {w.strip().upper() for w in str(werte_str).split(',') if w.strip()}
            if not required_icds_in_rule_list: return True
            return any(req_icd in provided_icds_upper for req_icd in required_icds_in_rule_list)
        elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE":
            if not check_icd_conditions_at_all: return True
            table_ref = werte_str
            icd_codes_in_rule_table = {entry['Code'].upper() for entry in get_table_content(table_ref, "icd", tabellen_dict_by_table) if entry.get('Code')}
            if not icd_codes_in_rule_table: return False if provided_icds_upper else True
            return any(provided_icd in icd_codes_in_rule_table for provided_icd in provided_icds_upper)
        elif bedingungstyp == "GTIN" or bedingungstyp == "MEDIKAMENTE IN LISTE":
            werte_list_gtin = [w.strip() for w in str(werte_str).split(',') if w.strip()]
            if not werte_list_gtin: return True
            return any(req_gtin in provided_gtins for req_gtin in werte_list_gtin)
        elif bedingungstyp == "LKN" or bedingungstyp == "LEISTUNGSPOSITIONEN IN LISTE":
            werte_list_upper_lkn = [w.strip().upper() for w in str(werte_str).split(',') if w.strip()]
            if not werte_list_upper_lkn: return True
            return any(req_lkn in provided_lkns_upper for req_lkn in werte_list_upper_lkn)
        elif bedingungstyp == "GESCHLECHT IN LISTE":
            if provided_geschlecht_str and werte_str:
                geschlechter_in_regel_lower = {g.strip().lower() for g in str(werte_str).split(',') if g.strip()}
                return provided_geschlecht_str.strip().lower() in geschlechter_in_regel_lower
            elif not werte_str: return True
            return False
        elif bedingungstyp == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp == "TARIFPOSITIONEN IN TABELLE":
            table_ref = werte_str
            lkn_codes_in_rule_table = {entry['Code'].upper() for entry in get_table_content(table_ref, "service_catalog", tabellen_dict_by_table) if entry.get('Code')}
            if not lkn_codes_in_rule_table: return False
            return any(provided_lkn in lkn_codes_in_rule_table for provided_lkn in provided_lkns_upper)
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
                 if isinstance(provided_geschlecht_str, str) and isinstance(wert_regel, str):
                     return provided_geschlecht_str.strip().lower() == wert_regel.strip().lower()
                 elif provided_geschlecht_str is None and (wert_regel is None or str(wert_regel).strip().lower() == 'unbekannt' or str(wert_regel).strip() == ""): return True
                 else: return False
            else:
                print(f"WARNUNG (check_single): Unbekanntes Feld '{feld_ref}' für Patientenbedingung.")
                return True
        else:
            print(f"WARNUNG (check_single): Unbekannter Pauschalen-Bedingungstyp '{bedingungstyp}'. Wird als False angenommen.")
            return False
    except Exception as e:
        pauschale_code_for_debug = condition.get('Pauschale', 'N/A_PAUSCHALE')
        gruppe_for_debug = condition.get('Gruppe', 'N/A_GRUPPE')
        print(f"FEHLER (check_single) für P: {pauschale_code_for_debug} G: {gruppe_for_debug} Typ: {bedingungstyp}, Werte: {werte_str}: {e}")
        traceback.print_exc()
        return False

def get_beschreibung_fuer_lkn_im_backend(lkn_code: str, leistungskatalog_dict: Dict) -> str:
    details = leistungskatalog_dict.get(str(lkn_code).upper())
    return details.get('Beschreibung', lkn_code) if details else lkn_code

def get_beschreibung_fuer_icd_im_backend(icd_code: str, tabellen_dict_by_table: Dict, spezifische_icd_tabelle: str = "icd_hauptkatalog") -> str:
    # Diese Funktion ist komplexer, da ICDs in verschiedenen Tabellen sein können.
    # Für eine einfache Annahme: Wir suchen in einer Haupt-ICD-Tabelle oder einer spezifischen.
    # Du müsstest dies an deine Datenstruktur für ICD-Beschreibungen anpassen.
    all_icds = []
    # Versuche, die Beschreibung aus der spezifischen Tabelle zu holen, wenn diese bekannt ist
    # oder aus einer generellen ICD-Liste in tabellen_dict_by_table.
    # Die Logik hängt davon ab, wie deine ICD-Daten strukturiert sind.
    # Hier eine Annahme:
    if spezifische_icd_tabelle in tabellen_dict_by_table: 
        icd_entries_specific = get_table_content(spezifische_icd_tabelle, "icd", tabellen_dict_by_table)
        for entry in icd_entries_specific:
            if entry.get('Code', '').upper() == icd_code.upper():
                return entry.get('Code_Text', icd_code)
    # Fallback: Suche in allen Tabellen vom Typ ICD (kann ineffizient sein)
    # Besser wäre eine dedizierte ICD-Lookup-Struktur oder eine gezieltere Suche.
    # Für den Moment, wenn nicht in spezifischer Tabelle gefunden, Code zurückgeben.
    return icd_code

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
    if not conditions_for_this_pauschale: return True
    grouped_conditions: Dict[Any, List[Dict]] = {}
    for cond in conditions_for_this_pauschale:
        gruppe_id = cond.get(GRUPPE_KEY)
        if gruppe_id is None: continue
        grouped_conditions.setdefault(gruppe_id, []).append(cond)
    if not grouped_conditions: return False
    for gruppe_id, conditions_in_group in grouped_conditions.items():
        if not conditions_in_group: continue
        all_conditions_in_group_met = True
        for cond_item in conditions_in_group:
            if not check_single_condition(cond_item, context, tabellen_dict_by_table):
                all_conditions_in_group_met = False
                break
        if all_conditions_in_group_met: return True # Eine Gruppe reicht
    return False # Keine Gruppe war vollständig erfüllt

# === FUNKTION ZUR HTML-GENERIERUNG DER BEDINGUNGSPRÜFUNG ===
def check_pauschale_conditions(
    pauschale_code: str,
    context: dict,
    pauschale_bedingungen_data: list[dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    leistungskatalog_dict: Dict[str, Dict]
) -> dict:
    errors: list[str] = []
    grouped_html_parts: Dict[Any, List[str]] = {}
    trigger_lkn_condition_met = False

    PAUSCHALE_KEY_IN_BEDINGUNGEN = 'Pauschale'; BED_ID_KEY = 'BedingungsID'
    BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'; BED_FELD_KEY = 'Feld'
    GRUPPE_KEY = 'Gruppe'

    conditions_for_this_pauschale = [
        cond for cond in pauschale_bedingungen_data if cond.get(PAUSCHALE_KEY_IN_BEDINGUNGEN) == pauschale_code
    ]

    if not conditions_for_this_pauschale:
        return {"html": "<ul><li>Keine spezifischen Bedingungen für diese Pauschale definiert.</li></ul>", "errors": [], "trigger_lkn_condition_met": False}

    conditions_for_this_pauschale.sort(key=lambda x: (x.get(GRUPPE_KEY, 0), x.get(BED_ID_KEY, 0)))

    provided_lkns_im_kontext_upper = {str(lkn).upper() for lkn in context.get("LKN", []) if lkn}
    provided_icds_im_kontext_upper = {str(icd).upper() for icd in context.get("ICD", []) if icd}

    for i, cond_definition in enumerate(conditions_for_this_pauschale):
        gruppe_id = cond_definition.get(GRUPPE_KEY, 'Ohne_Gruppe')
        bedingung_id = cond_definition.get(BED_ID_KEY, f"Unbekannt_{i+1}")
        bedingungstyp = cond_definition.get(BED_TYP_KEY, "UNBEKANNT").upper()
        werte_aus_regel = cond_definition.get(BED_WERTE_KEY, "")
        feld_ref_patientenbed = cond_definition.get(BED_FELD_KEY)
        condition_met_this_line = check_single_condition(cond_definition, context, tabellen_dict_by_table)
        
        # SVG Icon HTML basierend auf Erfüllung
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
        li_content += icon_html # Füge das SVG-Icon HTML hier ein
        li_content += f"<span class='condition-type-display'>({escape(bedingungstyp)}):</span> "
        
        specific_description_html = ""; is_lkn_condition_type = False
        kontext_erfuellungs_info_html = ""

        # --- Logik zur Erstellung von specific_description_html und kontext_erfuellungs_info_html ---
        if "IN TABELLE" in bedingungstyp:
            table_names_str = werte_aus_regel
            table_names_list = [t.strip() for t in table_names_str.split(',') if t.strip()]
            type_for_get_table_content = ""; type_prefix = "Code"
            kontext_elemente_fuer_vergleich = set()
            erfuellende_element_beschreibungen_aus_tabellen = {}

            if "LEISTUNGSPOSITIONEN" in bedingungstyp or "TARIFPOSITIONEN" in bedingungstyp:
                type_prefix = "LKN"; type_for_get_table_content = "service_catalog"; is_lkn_condition_type = True
                kontext_elemente_fuer_vergleich = provided_lkns_im_kontext_upper
            elif "HAUPTDIAGNOSE" in bedingungstyp or "ICD" in bedingungstyp :
                type_prefix = "ICD"; type_for_get_table_content = "icd"
                kontext_elemente_fuer_vergleich = provided_icds_im_kontext_upper
            
            specific_description_html += f"Erfordert {type_prefix} aus Tabelle(n): "
            if not table_names_list: specific_description_html += "<i>Kein Tabellenname spezifiziert.</i>"
            else:
                table_links_html_parts = []
                all_codes_in_regel_tabellen = set() 
                for table_name in table_names_list:
                    table_content_entries = get_table_content(table_name, type_for_get_table_content, tabellen_dict_by_table)
                    entry_count = len(table_content_entries); details_content_html = ""
                    current_table_codes_with_desc = {}
                    if table_content_entries:
                        details_content_html = "<ul style='margin-top: 5px; font-size: 0.9em; max-height: 150px; overflow-y: auto; border-top: 1px solid #eee; padding-top: 5px; padding-left: 15px; list-style-position: inside;'>"
                        for item in sorted(table_content_entries, key=lambda x: x.get('Code', '')):
                            item_code = item.get('Code','').upper(); all_codes_in_regel_tabellen.add(item_code)
                            item_text = item.get('Code_Text', 'N/A'); current_table_codes_with_desc[item_code] = item_text
                            details_content_html += f"<li><b>{escape(item_code)}</b>: {escape(item_text)}</li>"
                        details_content_html += "</ul>"
                    table_detail_html = (f"<details><summary>{escape(table_name)}</summary> ({entry_count} Einträge){details_content_html}</details>")
                    table_links_html_parts.append(table_detail_html)
                    for kontext_code in kontext_elemente_fuer_vergleich:
                        if kontext_code in current_table_codes_with_desc: erfuellende_element_beschreibungen_aus_tabellen[kontext_code] = current_table_codes_with_desc[kontext_code]
                
                specific_description_html += ", ".join(table_links_html_parts)
                if condition_met_this_line and erfuellende_element_beschreibungen_aus_tabellen:
                    details_list = [f"<b>{escape(code)}</b> ({escape(desc)})" for code, desc in erfuellende_element_beschreibungen_aus_tabellen.items()]
                    kontext_erfuellungs_info_html = f" <span class='context-match-info fulfilled'>(Erfüllt durch: {', '.join(details_list)})</span>"
                elif condition_met_this_line and not erfuellende_element_beschreibungen_aus_tabellen:
                    erfuellende_kontext_codes_ohne_desc = [k for k in kontext_elemente_fuer_vergleich if k in all_codes_in_regel_tabellen]
                    if erfuellende_kontext_codes_ohne_desc: kontext_erfuellungs_info_html = f" <span class='context-match-info fulfilled'>(Erfüllt durch: {', '.join(escape(c) for c in erfuellende_kontext_codes_ohne_desc)})</span>"
                elif not condition_met_this_line: 
                    fehlende_elemente_details = []
                    for kontext_code in kontext_elemente_fuer_vergleich:
                        if kontext_code not in all_codes_in_regel_tabellen and all_codes_in_regel_tabellen: 
                             desc = get_beschreibung_fuer_lkn_im_backend(kontext_code, leistungskatalog_dict) if type_prefix == "LKN" else get_beschreibung_fuer_icd_im_backend(kontext_code, tabellen_dict_by_table, table_names_list[0] if table_names_list else None)
                             fehlende_elemente_details.append(f"<b>{escape(kontext_code)}</b> ({escape(desc)})")
                    if fehlende_elemente_details : kontext_erfuellungs_info_html = f" <span class='context-match-info not-fulfilled'>(Kontext-Element(e) {', '.join(fehlende_elemente_details)} nicht in Regel-Tabelle(n) gefunden)</span>"
        elif "IN LISTE" in bedingungstyp:
            items_in_list_str = werte_aus_regel
            regel_items_upper = {item.strip().upper() for item in items_in_list_str.split(',') if item.strip()}
            type_prefix = "Code"; kontext_elemente_fuer_vergleich = set()
            if "LEISTUNGSPOSITIONEN" in bedingungstyp or "LKN" in bedingungstyp: type_prefix = "LKN"; is_lkn_condition_type = True; kontext_elemente_fuer_vergleich = provided_lkns_im_kontext_upper
            elif "HAUPTDIAGNOSE" in bedingungstyp or "ICD" in bedingungstyp: type_prefix = "ICD"; kontext_elemente_fuer_vergleich = provided_icds_im_kontext_upper
            specific_description_html += f"Erfordert {type_prefix} aus Liste: "
            if not regel_items_upper: specific_description_html += "<i>Keine Elemente spezifiziert.</i>"
            else: specific_description_html += f"{escape(', '.join(sorted(list(regel_items_upper))))}"
            if condition_met_this_line:
                erfuellende_details = [f"<b>{escape(k)}</b> ({escape(get_beschreibung_fuer_lkn_im_backend(k, leistungskatalog_dict) if type_prefix == 'LKN' else get_beschreibung_fuer_icd_im_backend(k, tabellen_dict_by_table))})" for k in kontext_elemente_fuer_vergleich if k in regel_items_upper]
                if erfuellende_details: kontext_erfuellungs_info_html = f" <span class='context-match-info fulfilled'>(Erfüllt durch: {', '.join(erfuellende_details)})</span>"
            elif regel_items_upper :
                fehlende_details = [f"<b>{escape(k)}</b> ({escape(get_beschreibung_fuer_lkn_im_backend(k, leistungskatalog_dict) if type_prefix == 'LKN' else get_beschreibung_fuer_icd_im_backend(k, tabellen_dict_by_table))})" for k in kontext_elemente_fuer_vergleich if k not in regel_items_upper]
                if fehlende_details: kontext_erfuellungs_info_html = f" <span class='context-match-info not-fulfilled'>(Kontext-Element(e) {', '.join(fehlende_details)} nicht in Regel-Liste)</span>"
        elif bedingungstyp == "PATIENTENBEDINGUNG":
            min_val = cond_definition.get('MinWert'); max_val = cond_definition.get('MaxWert')
            specific_description_html += f"Patient: Feld='{escape(feld_ref_patientenbed)}'"
            if feld_ref_patientenbed == "Alter":
                age_req_parts = []
                if min_val is not None: age_req_parts.append(f"min. {escape(str(min_val))}")
                if max_val is not None: age_req_parts.append(f"max. {escape(str(max_val))}")
                if not age_req_parts and werte_aus_regel: age_req_parts.append(f"exakt {escape(werte_aus_regel)}")
                specific_description_html += f", Anforderung: {(' und '.join(age_req_parts) or 'N/A')}"
                kontext_erfuellungs_info_html = f" <span class='context-match-info'>(Kontext: {escape(str(context.get('Alter', 'N/A')))})</span>"
            elif feld_ref_patientenbed == "Geschlecht":
                specific_description_html += f", Erwartet='{escape(werte_aus_regel)}'"
                kontext_erfuellungs_info_html = f" <span class='context-match-info'>(Kontext: {escape(str(context.get('Geschlecht', 'N/A')))})</span>"
            else: specific_description_html += f", Wert/Ref='{escape(werte_aus_regel or feld_ref_patientenbed or '-')}'"
        elif bedingungstyp == "GESCHLECHT IN LISTE":
             specific_description_html += f"Geschlecht in Liste: {escape(werte_aus_regel)}"
             kontext_erfuellungs_info_html = f" <span class='context-match-info'>(Kontext: {escape(str(context.get('Geschlecht', 'N/A')))})</span>"
        else:
            specific_description_html += f"Detail: {escape(werte_aus_regel or feld_ref_patientenbed or 'N/A')}"
        # ENDE Logik für specific_description_html und kontext_erfuellungs_info_html

        li_content += f"<span class='condition-text-wrapper'>{specific_description_html}{kontext_erfuellungs_info_html}</span>"
        li_content += "</div>"

        if gruppe_id not in grouped_html_parts: grouped_html_parts[gruppe_id] = []
        grouped_html_parts[gruppe_id].append(li_content)
        if not condition_met_this_line: errors.append(f"Bedingung {i+1} ({escape(bedingungstyp)}: {status_label_for_error}) nicht erfüllt.")
        if is_lkn_condition_type and condition_met_this_line: trigger_lkn_condition_met = True
    
    final_html = "" 
    final_html_parts = []
    sorted_group_ids = sorted(grouped_html_parts.keys())

    if not sorted_group_ids: 
        final_html = "<ul><li>Keine gültigen Bedingungsgruppen gefunden.</li></ul>"
    elif len(sorted_group_ids) == 1:
         group_id = sorted_group_ids[0]
         group_html_content = "".join(grouped_html_parts[group_id])
         group_title_text = "Bedingungen (Alle müssen erfüllt sein):"
         final_html = (
            f"<div class='condition-group'>"
            f"<div class='condition-group-title'>{group_title_text}</div>"
            f"{group_html_content}"
            f"</div>"
        )
    else: 
        for idx, group_id in enumerate(sorted_group_ids):
            group_html_content = "".join(grouped_html_parts[group_id])
            group_title_text = f"Logik-Gruppe {escape(str(group_id))} (Alle Bedingungen dieser Gruppe müssen erfüllt sein):"
            group_wrapper_html = (
                f"<div class='condition-group'>"
                f"<div class='condition-group-title'>{group_title_text}</div>"
                f"{group_html_content}"
                f"</div>"
            )
            final_html_parts.append(group_wrapper_html)
            if idx < len(sorted_group_ids) - 1:
                final_html_parts.append("<div class='condition-separator'>ODER</div>")
        final_html = "".join(final_html_parts)

    return {"html": final_html, "errors": errors, "trigger_lkn_condition_met": trigger_lkn_condition_met}

# --- Ausgelagerte Pauschalen-Ermittlung ---
def determine_applicable_pauschale(
    user_input: str,
    rule_checked_leistungen: list[dict],
    context: dict,
    pauschale_lp_data: List[Dict],
    pauschale_bedingungen_data: List[Dict],
    pauschalen_dict: Dict[str, Dict],
    leistungskatalog_dict: Dict[str, Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    potential_pauschale_codes_input: Set[str] | None = None # Argument hinzugefügt
    ) -> dict:
    """
    Ermittelt die anwendbarste Pauschale durch Auswertung der strukturierten Bedingungen.
    Akzeptiert optional eine Liste potenzieller Codes, um die Suche zu überspringen.
    Wählt die "am komplexesten passende" Pauschale aus einer Gruppe (niedrigster Suffix-Buchstabe).
    """
    print("INFO: Starte Pauschalenermittlung mit strukturierter Bedingungsprüfung...")
    PAUSCHALE_ERKLAERUNG_KEY = 'pauschale_erklaerung_html'; POTENTIAL_ICDS_KEY = 'potential_icds'
    LKN_KEY_IN_RULE_CHECKED = 'lkn'; PAUSCHALE_KEY_IN_PAUSCHALEN = 'Pauschale'
    PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN = 'Pauschale_Text'; LP_LKN_KEY = 'Leistungsposition'
    LP_PAUSCHALE_KEY = 'Pauschale'; BED_PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp'
    BED_WERTE_KEY = 'Werte'; TAB_CODE_KEY = 'Code'; TAB_TYP_KEY = 'Tabelle_Typ'; TAB_TABELLE_KEY = 'Tabelle'

    potential_pauschale_codes = set()
    if potential_pauschale_codes_input is not None:
        potential_pauschale_codes = potential_pauschale_codes_input
        print(f"DEBUG: Verwende übergebene potenzielle Pauschalen: {potential_pauschale_codes}")
    else:
        print("DEBUG: Suche potenzielle Pauschalen (da nicht übergeben)...")
        rule_checked_lkns_for_search = [l.get(LKN_KEY_IN_RULE_CHECKED) for l in rule_checked_leistungen if l.get(LKN_KEY_IN_RULE_CHECKED)]
        lkns_in_tables = {}
        for lkn in rule_checked_lkns_for_search:
            for item in pauschale_lp_data:
                if item.get(LP_LKN_KEY) == lkn:
                    pc = item.get(LP_PAUSCHALE_KEY);
                    if pc and pc in pauschalen_dict: potential_pauschale_codes.add(pc)
            for cond in pauschale_bedingungen_data:
                if cond.get(BED_TYP_KEY) == "LEISTUNGSPOSITIONEN IN LISTE":
                    werte_liste = [w.strip() for w in str(cond.get(BED_WERTE_KEY, "")).split(',') if w.strip()]
                    if lkn in werte_liste:
                        pc = cond.get(BED_PAUSCHALE_KEY);
                        if pc and pc in pauschalen_dict: potential_pauschale_codes.add(pc)
            if lkn not in lkns_in_tables:
                 tables_for_lkn = set()
                 for table_name_key in tabellen_dict_by_table.keys():
                      for entry in tabellen_dict_by_table[table_name_key]:
                           if entry.get(TAB_CODE_KEY) == lkn and entry.get(TAB_TYP_KEY) == "service_catalog": tables_for_lkn.add(table_name_key.lower())
                 lkns_in_tables[lkn] = tables_for_lkn
            tables_for_current_lkn_normalized = lkns_in_tables.get(lkn, set())
            if tables_for_current_lkn_normalized:
                for cond in pauschale_bedingungen_data:
                    if cond.get(BED_TYP_KEY) == "LEISTUNGSPOSITIONEN IN TABELLE":
                        table_ref_in_cond_str = cond.get(BED_WERTE_KEY, ""); pc = cond.get(BED_PAUSCHALE_KEY)
                        condition_tables_normalized = {t.strip().lower() for t in table_ref_in_cond_str.split(',') if t.strip()}
                        if not condition_tables_normalized.isdisjoint(tables_for_current_lkn_normalized):
                            if pc and pc in pauschalen_dict: potential_pauschale_codes.add(pc)
        print(f"DEBUG: Finale potenzielle Pauschalen nach LKN-basierter Suche: {potential_pauschale_codes}")

    if not potential_pauschale_codes: return {"type": "Error", "message": "Keine passende Pauschale für die erbrachten Leistungen gefunden."}

    evaluated_candidates = []
    print(f"INFO: Werte strukturierte Bedingungen für {len(potential_pauschale_codes)} potenzielle Pauschalen aus...")
    for code in sorted(list(potential_pauschale_codes)):
        if code not in pauschalen_dict: continue
        is_pauschale_valid = False
        try: is_pauschale_valid = evaluate_structured_conditions(code, context, pauschale_bedingungen_data, tabellen_dict_by_table)
        except Exception as e_eval: print(f"FEHLER bei evaluate_structured_conditions für {code}: {e_eval}")
        evaluated_candidates.append({"code": code, "details": pauschalen_dict[code], "is_valid_structured": is_pauschale_valid})

    valid_candidates = [cand for cand in evaluated_candidates if cand["is_valid_structured"]]
    print(f"DEBUG: Struktur-gültige Kandidaten nach Prüfung: {[c['code'] for c in valid_candidates]}")

    # --- Debugging Bedingungen (optional) ---
    # ...

    selected_candidate_info = None
    if valid_candidates:
        specific_valid_candidates = [c for c in valid_candidates if not c['code'].startswith('C9')]
        fallback_valid_candidates = [c for c in valid_candidates if c['code'].startswith('C9')]
        chosen_list_for_selection = []; selection_type_message = ""
        if specific_valid_candidates: chosen_list_for_selection = specific_valid_candidates; selection_type_message = "spezifischen"
        elif fallback_valid_candidates: chosen_list_for_selection = fallback_valid_candidates; selection_type_message = "Fallback (C9x)"
        if chosen_list_for_selection:
            print(f"INFO: Auswahl aus {len(chosen_list_for_selection)} struktur-gültigen {selection_type_message} Kandidaten.")
            def sort_key_most_complex(candidate): # A vor B vor E
                code = candidate['code']; match = re.match(r"([A-Z0-9.]+)([A-Z])$", code)
                if match: return (match.group(1), ord(match.group(2)))
                return (code, 0)
            chosen_list_for_selection.sort(key=sort_key_most_complex)
            selected_candidate_info = chosen_list_for_selection[0]
            print(f"INFO: Gewählte Pauschale nach Sortierung (Stamm A-Z, Suffix A-Z -> komplexeste zuerst): {selected_candidate_info['code']}")
            print(f"   DEBUG: Sortierte Kandidatenliste ({selection_type_message}): {[c['code'] for c in chosen_list_for_selection]}")
        else: return {"type": "Error", "message": "Interner Fehler bei der Pauschalenauswahl (Kategorisierung)."}
    else: # Keine valid_candidates
        print("INFO: Keine Pauschale erfüllt die strukturierten Bedingungen.")
        if potential_pauschale_codes: return {"type": "Error", "message": "Potenzielle Pauschalen gefunden, aber keine erfüllte die UND/ODER-Bedingungen."}
        else: return {"type": "Error", "message": "Keine passende Pauschale gefunden."}

    if not selected_candidate_info: return {"type": "Error", "message": "Interner Fehler: Keine Pauschale nach Auswahlprozess selektiert."}

    best_pauschale_code = selected_candidate_info["code"]
    best_pauschale_details = selected_candidate_info["details"].copy()
    bedingungs_pruef_html_result = "<p><i>Detail-HTML nicht generiert.</i></p>"; condition_errors = []
    try:
        condition_result_html = check_pauschale_conditions(best_pauschale_code, context, pauschale_bedingungen_data, tabellen_dict_by_table, leistungskatalog_dict)
        bedingungs_pruef_html_result = condition_result_html.get("html", "<p class='error'>Fehler bei HTML-Generierung.</p>")
        condition_errors = condition_result_html.get("errors", [])
    except Exception as e_html_gen:
         print(f"FEHLER bei check_pauschale_conditions (HTML-Generierung) für {best_pauschale_code}: {e_html_gen}")
         bedingungs_pruef_html_result = f"<p class='error'>Fehler bei HTML-Generierung: {e_html_gen}</p>"; condition_errors = [f"Fehler HTML-Generierung: {e_html_gen}"]

    lkns_used_for_check_str_list = [str(lkn) for lkn in context.get('LKN', []) if lkn]
    pauschale_erklaerung_html = "<p>Folgende Pauschalen wurden geprüft basierend auf dem Kontext (regelkonforme & gemappte LKNs: {}):</p>".format(", ".join(lkns_used_for_check_str_list) or "keine")
    pauschale_erklaerung_html += "<p>Folgende Pauschalen erfüllten die strukturierten UND/ODER Bedingungen:</p><ul>"
    valid_candidates_sorted_for_display = sorted(valid_candidates, key=lambda x: x['code'])
    for cand in valid_candidates_sorted_for_display: pauschale_erklaerung_html += f"<li><b>{cand['code']}</b>: {escape(cand['details'].get(PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, 'N/A'))}</li>"
    pauschale_erklaerung_html += "</ul>"
    pauschale_erklaerung_html += f"<p><b>Ausgewählt wurde: {best_pauschale_code}</b> ({escape(best_pauschale_details.get(PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, 'N/A'))}) - als Pauschale mit dem niedrigsten Suffix-Buchstaben (am komplexesten) unter den gültigen Kandidaten der bevorzugten Kategorie (spezifisch vor Fallback).</p>"

    match = re.match(r"([A-Z0-9.]+)([A-Z])$", best_pauschale_code)
    pauschalen_gruppe_stamm = match.group(1) if match else None # Umbenannt für Klarheit
    
    if pauschalen_gruppe_stamm:
        # Finde andere *potenzielle* Pauschalen in derselben Gruppe zum Vergleich
        other_potential_codes_in_group = [
            cand_code for cand_code in potential_pauschale_codes # Vergleiche mit allen potenziellen
            if cand_code.startswith(pauschalen_gruppe_stamm) and cand_code != best_pauschale_code and cand_code in pauschalen_dict
        ]
        if other_potential_codes_in_group:
             pauschale_erklaerung_html += "<hr><p><b>Vergleich mit anderen Pauschalen der Gruppe '{}':</b></p>".format(pauschalen_gruppe_stamm)
             selected_conditions_repr = get_simplified_conditions(best_pauschale_code, pauschale_bedingungen_data)
             
             for other_code in sorted(other_potential_codes_in_group):
                  other_details = pauschalen_dict[other_code]
                  other_was_valid = any(vc['code'] == other_code for vc in valid_candidates)
                  validity_info = '<span style="color:green;">(Auch gültig)</span>' if other_was_valid else '<span style="color:red;">(Nicht gültig)</span>'

                  other_conditions_repr = get_simplified_conditions(other_code, pauschale_bedingungen_data)
                  additional_conditions = other_conditions_repr - selected_conditions_repr
                  missing_conditions = selected_conditions_repr - other_conditions_repr

                  pauschale_erklaerung_html += f"<details style='margin-left: 15px; font-size: 0.9em;'><summary>Unterschiede zu <b>{other_code}</b> ({escape(other_details.get(PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, 'N/A'))}) {validity_info}</summary>"
                  
                  if additional_conditions:
                      pauschale_erklaerung_html += "<p>Zusätzliche/Andere Anforderungen für {}:</p><ul>".format(other_code)
                      for cond_tuple in sorted(list(additional_conditions)):
                            # ---> HIER IST DER AUFRUF VON generate_condition_detail_html <---
                            condition_html_detail = generate_condition_detail_html(cond_tuple, leistungskatalog_dict, tabellen_dict_by_table)
                            pauschale_erklaerung_html += condition_html_detail
                      pauschale_erklaerung_html += "</ul>"
                  
                  if missing_conditions:
                     pauschale_erklaerung_html += "<p>Folgende Anforderungen von {} fehlen bei {}:</p><ul>".format(best_pauschale_code, other_code)
                     for cond_tuple in sorted(list(missing_conditions)):
                         # ---> HIER IST DER AUFRUF VON generate_condition_detail_html <---
                         condition_html_detail = generate_condition_detail_html(cond_tuple, leistungskatalog_dict, tabellen_dict_by_table)
                         pauschale_erklaerung_html += condition_html_detail
                     pauschale_erklaerung_html += "</ul>"
                  
                  if not additional_conditions and not missing_conditions:
                     pauschale_erklaerung_html += "<p><i>Keine unterschiedlichen Bedingungen gefunden (basierend auf vereinfachter Prüfung).</i></p>"
                  pauschale_erklaerung_html += "</details>"
    
    best_pauschale_details[PAUSCHALE_ERKLAERUNG_KEY] = pauschale_erklaerung_html

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
    best_pauschale_details[POTENTIAL_ICDS_KEY] = sorted(unique_icds_dict.values(), key=lambda x: x['Code'])

    final_result = {"type": "Pauschale", "details": best_pauschale_details, "bedingungs_pruef_html": bedingungs_pruef_html_result, "bedingungs_fehler": condition_errors, "conditions_met": True}
    return final_result

# --- HILFSFUNKTIONEN (auf Modulebene) ---
def get_simplified_conditions(pauschale_code: str, bedingungen_data: list[dict]) -> set:
    """ Wandelt Bedingungen in eine strukturiertere, vergleichbare Darstellung um. """
    print(f"--- DEBUG: get_simplified_conditions AUFGERUFEN für Pauschale: {pauschale_code} ---")
    simplified_set = set()
    PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'
    BED_FELD_KEY = 'Feld'; BED_MIN_KEY = 'MinWert'; BED_MAX_KEY = 'MaxWert'
    
    pauschale_conditions = [cond for cond in bedingungen_data if cond.get(PAUSCHALE_KEY) == pauschale_code]

    for cond in pauschale_conditions:
        typ_original = cond.get(BED_TYP_KEY, "").upper()
        wert = cond.get(BED_WERTE_KEY, "")
        feld = cond.get(BED_FELD_KEY, "")
        condition_tuple = None
        final_cond_type = None

        if typ_original == "LEISTUNGSPOSITIONEN IN TABELLE" or typ_original == "TARIFPOSITIONEN IN TABELLE" or typ_original == "LKN IN TABELLE": # LKN IN TABELLE hinzugefügt
            final_cond_type = 'LKN_TABLE'
        elif typ_original == "HAUPTDIAGNOSE IN TABELLE" or typ_original == "ICD IN TABELLE": # ICD IN TABELLE hinzugefügt
            final_cond_type = 'ICD_TABLE'
        elif typ_original == "LEISTUNGSPOSITIONEN IN LISTE" or typ_original == "LKN":
            final_cond_type = 'LKN_LIST'
        elif typ_original == "HAUPTDIAGNOSE IN LISTE" or typ_original == "ICD": # HAUPTDIAGNOSE IN LISTE hinzugefügt
             final_cond_type = 'ICD_LIST'
        elif typ_original == "MEDIKAMENTE IN LISTE" or typ_original == "GTIN":
            final_cond_type = 'GTIN_LIST'
        elif typ_original == "PATIENTENBEDINGUNG" and feld:
            final_cond_type = 'PATIENT' # Der Wert wird dann spezifisch formatiert
        # Füge hier weitere explizite Mappings für andere Original-Typen hinzu, falls nötig

        if final_cond_type == 'PATIENT':
            if cond.get(BED_MIN_KEY) is not None or cond.get(BED_MAX_KEY) is not None:
                bereich_text = f"({cond.get(BED_MIN_KEY, '-')}-{cond.get(BED_MAX_KEY, '-')})"
                condition_tuple = (final_cond_type, f"{feld} {bereich_text}")
            else:
                condition_tuple = (final_cond_type, f"{feld}={wert}")
        elif final_cond_type: # Für alle anderen gemappten Typen
            condition_tuple = (final_cond_type, wert)
        
        if condition_tuple:
            print(f"  DEBUG: get_simplified_conditions (Orig: '{typ_original}') erzeugt Tuple: {condition_tuple}")
            simplified_set.add(condition_tuple)
        else:
            print(f"  WARNUNG: get_simplified_conditions konnte Typ '{typ_original}' nicht zuordnen.")
            
    return simplified_set

def generate_condition_detail_html(
    condition_tuple: tuple,
    leistungskatalog_dict: Dict,
    tabellen_dict_by_table: Dict
    ) -> str:
    """
    Generiert HTML für eine einzelne strukturierte Bedingung im Vergleichsabschnitt
    mit aufklappbaren Details für Tabellen und Beschreibungen für Listen.
    """
    cond_type, cond_value = condition_tuple
    condition_html = "<li>" # Jede Bedingung ist ein Listeneintrag

    try:
        if cond_type == 'LKN_LIST':
            condition_html += f"Erfordert LKN aus Liste: "
            lkn_codes_in_list = [lkn.strip().upper() for lkn in cond_value.split(',') if lkn.strip()]
            if not lkn_codes_in_list:
                condition_html += "<i>(Keine LKNs spezifiziert)</i>"
            else:
                lkn_details_html_parts = []
                for lkn_code in sorted(lkn_codes_in_list):
                    beschreibung = get_beschreibung_fuer_lkn_im_backend(lkn_code, leistungskatalog_dict)
                    lkn_details_html_parts.append(f"<b>{html.escape(lkn_code)}</b> ({html.escape(beschreibung)})")
                condition_html += ", ".join(lkn_details_html_parts)

        elif cond_type == 'LKN_TABLE':
            condition_html += f"Erfordert LKN aus Tabelle(n): "
            table_names_str = cond_value
            table_names_list = [t.strip() for t in table_names_str.split(',') if t.strip()]
            if not table_names_list:
                condition_html += "<i>(Kein Tabellenname spezifiziert)</i>"
            else:
                table_links_html_parts = []
                for table_name in table_names_list:
                    table_content_entries = get_table_content(table_name, "service_catalog", tabellen_dict_by_table)
                    entry_count = len(table_content_entries)
                    details_content_html = ""
                    if table_content_entries:
                        details_content_html = "<ul style='margin-top: 5px; font-size: 0.9em; max-height: 150px; overflow-y: auto; border-top: 1px solid #eee; padding-top: 5px; padding-left: 15px; list-style-position: inside;'>"
                        for item in sorted(table_content_entries, key=lambda x: x.get('Code', '')):
                            item_code = item.get('Code', 'N/A')
                            item_text = item.get('Code_Text', 'N/A')
                            details_content_html += f"<li><b>{html.escape(item_code)}</b>: {html.escape(item_text)}</li>"
                        details_content_html += "</ul>"
                    table_detail_html = (
                        f"<details class='inline-table-details-comparison'>"
                        f"<summary>{html.escape(table_name)}</summary> ({entry_count} Einträge)"
                        f"{details_content_html}"
                        f"</details>"
                    )
                    table_links_html_parts.append(table_detail_html)
                condition_html += ", ".join(table_links_html_parts)

        elif cond_type == 'ICD_TABLE':
            condition_html += f"Erfordert ICD aus Tabelle(n): "
            table_names_str = cond_value
            table_names_list = [t.strip() for t in table_names_str.split(',') if t.strip()]
            if not table_names_list:
                condition_html += "<i>(Kein Tabellenname spezifiziert)</i>"
            else:
                table_links_html_parts = []
                for table_name in table_names_list:
                    table_content_entries = get_table_content(table_name, "icd", tabellen_dict_by_table)
                    entry_count = len(table_content_entries)
                    details_content_html = ""
                    if table_content_entries:
                        details_content_html = "<ul style='margin-top: 5px; font-size: 0.9em; max-height: 150px; overflow-y: auto; border-top: 1px solid #eee; padding-top: 5px; padding-left: 15px; list-style-position: inside;'>"
                        for item in sorted(table_content_entries, key=lambda x: x.get('Code', '')):
                            item_code = item.get('Code', 'N/A')
                            item_text = item.get('Code_Text', 'N/A')
                            details_content_html += f"<li><b>{html.escape(item_code)}</b>: {html.escape(item_text)}</li>"
                        details_content_html += "</ul>"
                    table_detail_html = (
                        f"<details class='inline-table-details-comparison'>"
                        f"<summary>{html.escape(table_name)}</summary> ({entry_count} Einträge)"
                        f"{details_content_html}"
                        f"</details>"
                    )
                    table_links_html_parts.append(table_detail_html)
                condition_html += ", ".join(table_links_html_parts)

        elif cond_type == 'ICD_LIST':
            condition_html += f"Erfordert ICD aus Liste: "
            icd_codes_in_list = [icd.strip().upper() for icd in cond_value.split(',') if icd.strip()]
            if not icd_codes_in_list:
                condition_html += "<i>(Keine ICDs spezifiziert)</i>"
            else:
                icd_details_html_parts = []
                for icd_code in sorted(icd_codes_in_list):
                    beschreibung = get_beschreibung_fuer_icd_im_backend(icd_code, tabellen_dict_by_table) # Annahme
                    icd_details_html_parts.append(f"<b>{html.escape(icd_code)}</b> ({html.escape(beschreibung)})")
                condition_html += ", ".join(icd_details_html_parts)
        
        elif cond_type == 'GTIN_LIST':
            condition_html += f"Erfordert GTIN aus Liste: {html.escape(cond_value)}"
        
        elif cond_type == 'PATIENT':
            condition_html += f"Patientenbedingung: {html.escape(cond_value)}"
        
        else: # Fallback
            condition_html += f"{html.escape(cond_type)}: {html.escape(str(cond_value))}"

    except Exception as e_detail:
        print(f"FEHLER beim Erstellen der Detailansicht für Vergleichs-Bedingung '{condition_tuple}': {e_detail}")
        condition_html += f"<i>Fehler bei Detailgenerierung: {html.escape(str(e_detail))}</i>"
    
    condition_html += "</li>"
    return condition_html