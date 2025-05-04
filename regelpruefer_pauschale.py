# regelpruefer_pauschale.py

import json
from typing import Dict, List, Any
import html # Für escaping

# Helper function to escape HTML
def escape(text: Any) -> str:
    """Escapes HTML special characters in a string."""
    return html.escape(str(text))

# Helper function to get table content
def get_table_content(table_ref: str, table_type: str, tabellen_dict_by_table: Dict[str, List[Dict]]) -> List[Dict]:
    """Holt Einträge für eine Tabelle und einen Typ."""
    content = []
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


def check_pauschale_conditions(
    pauschale_code: str,
    context: dict,
    pauschale_bedingungen_data: list[dict],
    tabellen_dict_by_table: Dict[str, List[Dict]]
) -> dict:
    """
    Prüft die Bedingungen für eine gegebene Pauschale deterministisch.
    Generiert detailliertes HTML inkl. klickbarer Tabellenreferenzen.
    """
    errors: list[str] = []
    condition_details_html: str = "<ul>"
    all_met = True
    trigger_lkn_condition_met = False

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
        return {"allMet": True, "html": condition_details_html, "errors": [], "trigger_lkn_condition_met": False}

    print(f"--- DEBUG [check_pauschale_conditions]: Starte Prüfung für {pauschale_code} ---")
    provided_icds_upper = {p_icd.upper() for p_icd in context.get("ICD", []) if p_icd}
    provided_gtins = set(context.get("GTIN", []))
    provided_lkns_upper = {p_lkn.upper() for p_lkn in context.get("LKN", []) if p_lkn}
    provided_alter = context.get("Alter")
    provided_geschlecht = context.get("Geschlecht")
    print(f"DEBUG [check_pauschale_conditions]: Kontext LKNs (Upper): {provided_lkns_upper}")

    for i, cond in enumerate(conditions):
        bedingungstyp = cond.get(BED_TYP_KEY, "").upper()
        werte_str = cond.get(BED_WERTE_KEY, "") # Kann kommasepariert sein ODER Tabellenname
        werte_list_upper = [w.strip().upper() for w in str(werte_str).split(',') if w.strip()]
        feld_ref = cond.get(BED_FELD_KEY)
        min_val = cond.get(BED_MIN_KEY)
        max_val = cond.get(BED_MAX_KEY)
        wert_regel = cond.get(BED_WERTE_KEY)

        condition_met_this_line = False
        status_text = "NICHT geprüft"
        # Start des Listeneintrags, Bedingungstyp zuerst
        li_content = f"<li>Bedingung {i+1}: {escape(bedingungstyp)}"
        details_fuer_bedingung = "" # Wird jetzt für Tabelleninhalte verwendet
        is_lkn_condition = False
        bedingung_beschreibung = "" # Textbeschreibung der Bedingung

        print(f"DEBUG [check_pauschale_conditions]: Prüfe Bedingung {i+1}: Typ='{bedingungstyp}', Wert='{werte_str}', Feld='{feld_ref}'")

        try:
            if bedingungstyp == "ICD":
                bedingung_beschreibung = f" - Erfordert ICD: {escape(werte_str)}"
                condition_met_this_line = any(req_icd in provided_icds_upper for req_icd in werte_list_upper)

            elif bedingungstyp == "GTIN" or bedingungstyp == "MEDIKAMENTE IN LISTE":
                bedingung_beschreibung = f" - Erfordert GTIN/Medikament: {escape(werte_str)}"
                werte_list_gtin = [w.strip() for w in str(werte_str).split(',') if w.strip()]
                condition_met_this_line = any(req_gtin in provided_gtins for req_gtin in werte_list_gtin)

            elif bedingungstyp == "LKN" or bedingungstyp == "LEISTUNGSPOSITIONEN IN LISTE":
                bedingung_beschreibung = f" - Erfordert LKN: {escape(werte_str)}"
                is_lkn_condition = True
                condition_met_this_line = any(req_lkn in provided_lkns_upper for req_lkn in werte_list_upper)

            elif bedingungstyp == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp == "TARIFPOSITIONEN IN TABELLE":
                bedingung_beschreibung = f" - Erfordert LKN aus " # Tabellen kommen separat
                is_lkn_condition = True
                table_names = [t.strip() for t in werte_str.split(',') if t.strip()]
                all_content = []
                valid_table_names = [] # Nur Tabellen, die gefunden wurden

                for table_name in table_names:
                    table_content = get_table_content(table_name, "service_catalog", tabellen_dict_by_table)
                    if table_content:
                        all_content.extend(table_content)
                        valid_table_names.append(table_name)
                    else:
                        print(f"WARNUNG: Tabelle '{table_name}' (LKN) nicht gefunden oder leer.")

                if all_content:
                    unique_content = {item['Code']: item for item in all_content}.values()
                    sorted_content = sorted(unique_content, key=lambda x: x['Code'])
                    condition_met_this_line = any(entry['Code'].upper() in provided_lkns_upper for entry in sorted_content)

                    # --- NEUE HTML Struktur für Tabellen ---
                    table_links = ", ".join([f"'{escape(t)}'" for t in valid_table_names])
                    details_fuer_bedingung += f"<details class='inline-details' style='display: inline-block; margin-left: 5px; vertical-align: middle;'><summary style='display: inline; cursor: pointer; color: blue; text-decoration: underline;'>Tabelle(n): {table_links}</summary><div style='margin-top: 5px; border: 1px solid #eee; padding: 5px; background: #f9f9f9;'><ul>"
                    for item in sorted_content:
                        details_fuer_bedingung += f"<li><b>{escape(item['Code'])}</b>: {escape(item['Code_Text'])}</li>"
                    details_fuer_bedingung += "</ul></div></details>"
                    # --- ENDE NEUE HTML ---
                elif table_names: # Tabellen genannt, aber keine gefunden/leer
                     bedingung_beschreibung += f" Tabelle(n): {escape(werte_str)} (leer oder nicht gefunden)"
                     condition_met_this_line = False
                else: # Sollte nicht vorkommen, wenn Typ ... IN TABELLE ist
                     bedingung_beschreibung += " Tabelle: (Keine Angabe)"
                     condition_met_this_line = False


            elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE":
                bedingung_beschreibung = f" - Erfordert ICD aus " # Tabellen kommen separat
                table_names = [t.strip() for t in werte_str.split(',') if t.strip()]
                all_content = []
                valid_table_names = []

                for table_name in table_names:
                    table_content = get_table_content(table_name, "icd", tabellen_dict_by_table)
                    if table_content:
                        all_content.extend(table_content)
                        valid_table_names.append(table_name)
                    else:
                        print(f"WARNUNG: Tabelle '{table_name}' (ICD) nicht gefunden oder leer.")

                if all_content:
                    unique_content = {item['Code']: item for item in all_content}.values()
                    sorted_content = sorted(unique_content, key=lambda x: x['Code'])
                    condition_met_this_line = any(entry['Code'].upper() in provided_icds_upper for entry in sorted_content)

                    # --- NEUE HTML Struktur für Tabellen ---
                    table_links = ", ".join([f"'{escape(t)}'" for t in valid_table_names])
                    details_fuer_bedingung += f"<details class='inline-details' style='display: inline-block; margin-left: 5px; vertical-align: middle;'><summary style='display: inline; cursor: pointer; color: blue; text-decoration: underline;'>Tabelle(n): {table_links}</summary><div style='margin-top: 5px; border: 1px solid #eee; padding: 5px; background: #f9f9f9;'><ul>"
                    for item in sorted_content:
                        details_fuer_bedingung += f"<li><b>{escape(item['Code'])}</b>: {escape(item['Code_Text'])}</li>"
                    details_fuer_bedingung += "</ul></div></details>"
                    # --- ENDE NEUE HTML ---
                elif table_names:
                     bedingung_beschreibung += f" Tabelle(n): {escape(werte_str)} (leer oder nicht gefunden)"
                     condition_met_this_line = False
                else:
                     bedingung_beschreibung += " Tabelle: (Keine Angabe)"
                     condition_met_this_line = False

            elif bedingungstyp == "PATIENTENBEDINGUNG":
                wert_fall = context.get(feld_ref)
                bedingung_beschreibung = f" - Patientenbedingung: Feld='{escape(feld_ref)}'"
                condition_met_this_line = False
                if feld_ref == "Alter":
                    bedingung_beschreibung += f", Bereich/Wert='{min_val or '-'} bis {max_val or '-'} / {wert_regel or '-'}'"
                    if wert_fall is None: status_text = "NICHT erfüllt (Alter fehlt)"
                    else:
                        try:
                            alter_patient = int(wert_fall); alter_ok = True
                            if min_val is not None and alter_patient < int(min_val): alter_ok = False
                            if max_val is not None and alter_patient > int(max_val): alter_ok = False
                            if min_val is None and max_val is None and wert_regel is not None and alter_patient != int(wert_regel): alter_ok = False
                            condition_met_this_line = alter_ok
                        except (ValueError, TypeError): status_text = "NICHT erfüllt (ungültiger Wert)"
                elif feld_ref == "Geschlecht":
                     bedingung_beschreibung += f", Erwartet='{escape(wert_regel)}'"
                     if isinstance(wert_fall, str) and isinstance(wert_regel, str):
                         condition_met_this_line = wert_fall.lower() == wert_regel.lower()
                     elif wert_fall is None and wert_regel is None:
                         condition_met_this_line = True
                     else:
                         condition_met_this_line = False
                else:
                    print(f"WARNUNG: Unbekanntes Feld '{feld_ref}' für Patientenbedingung Pauschale {pauschale_code}.")
                    condition_met_this_line = True # Unbekannt -> OK

            else: # Unbekannter Bedingungstyp
                print(f"WARNUNG: Unbekannter Pauschalen-Bedingungstyp '{bedingungstyp}' für {pauschale_code}.")
                bedingung_beschreibung = f" - Wert/Ref: {escape(werte_str or feld_ref or '-')}"
                condition_met_this_line = True # Unbekannt -> OK

            # Setze Status Text basierend auf condition_met_this_line, falls nicht schon explizit gesetzt
            if status_text == "NICHT geprüft":
                status_text = "Erfüllt" if condition_met_this_line else "NICHT erfüllt"

            # Aktualisiere trigger_lkn_condition_met
            if is_lkn_condition and condition_met_this_line:
                trigger_lkn_condition_met = True

        except Exception as e:
            print(f"FEHLER bei Prüfung Bedingung {i+1} für {pauschale_code}: {e}")
            condition_met_this_line = False
            status_text = f"FEHLER bei Prüfung: {escape(str(e))}"
            errors.append(f"Fehler bei Prüfung Bedingung {i+1}: {escape(str(e))}")

        print(f"DEBUG [check_pauschale_conditions]: Bedingung {i+1} Ergebnis: {condition_met_this_line}")

        # Füge Listeneintrag zum HTML hinzu (Struktur geändert)
        color = "green" if condition_met_this_line else "red"
        # Füge Beschreibung und Details (falls vorhanden) zusammen
        li_content += bedingung_beschreibung
        li_content += details_fuer_bedingung # Enthält das <details>-Element für Tabellen
        # Füge Status am Ende hinzu
        li_content += f': <span style="color:{color}; font-weight:bold;">{status_text}</span></li>'
        condition_details_html += li_content

        # Aktualisiere Gesamtstatus und Fehlerliste
        if not condition_met_this_line:
            all_met = False
            if not status_text.startswith("FEHLER"):
                 # Füge jetzt die kombinierte Beschreibung hinzu
                 errors.append(f"Bedingung {i+1}: {escape(bedingungstyp)}{bedingung_beschreibung}")

    # Ende der Schleife über Bedingungen

    condition_details_html += "</ul>"
    print(f"--- DEBUG [check_pauschale_conditions]: Abschluss Prüfung für {pauschale_code}: allMet={all_met}, triggerLKNMet={trigger_lkn_condition_met} ---")

    return {
        "allMet": all_met,
        "html": condition_details_html,
        "errors": errors,
        "trigger_lkn_condition_met": trigger_lkn_condition_met
    }