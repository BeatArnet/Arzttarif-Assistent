# utils.py
import html
from typing import Dict, List, Any

def escape(text: Any) -> str:
    """Escapes HTML special characters in a string."""
    return html.escape(str(text))

def get_table_content(table_ref: str, table_type: str, tabellen_dict_by_table: dict) -> list[dict]:
    """Holt Einträge für eine Tabelle und einen Typ (Case-Insensitive)."""
    content = []
    # Schlüssel für PAUSCHALEN_Tabellen - anpassen falls nötig!
    TAB_CODE_KEY = 'Code'; TAB_TEXT_KEY = 'Code_Text'; TAB_TYP_KEY = 'Tabelle_Typ'

    table_names = [t.strip() for t in table_ref.split(',') if t.strip()]
    all_entries_for_type = []

    for name in table_names:
        normalized_key = name.lower() # Suche immer mit kleinem Schlüssel
        # print(f"DEBUG (get_table_content): Suche normalisierten Schlüssel '{normalized_key}' für Typ '{table_type}'") # Optional

        if normalized_key in tabellen_dict_by_table:
            # print(f"DEBUG (get_table_content): Schlüssel '{normalized_key}' gefunden.") # Optional
            for entry in tabellen_dict_by_table[normalized_key]: # Greife direkt auf die Liste zu
                entry_typ = entry.get(TAB_TYP_KEY)
                if entry_typ and entry_typ.lower() == table_type.lower():
                    code = entry.get(TAB_CODE_KEY); text = entry.get(TAB_TEXT_KEY)
                    if code: all_entries_for_type.append({"Code": code, "Code_Text": text or "N/A"})
        else:
             print(f"WARNUNG (get_table_content): Normalisierter Schlüssel '{normalized_key}' (Original: '{name}') nicht in tabellen_dict_by_table gefunden.")

    unique_content = {item['Code']: item for item in all_entries_for_type}.values()
    return sorted(unique_content, key=lambda x: x.get('Code', ''))