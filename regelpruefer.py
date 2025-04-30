"""
Modul zur Prüfung der Abrechnungsregeln (Regelwerk) für TARDOC-Leistungen.
Dieses Modul stellt Funktionen zum Laden des Regelwerks aus einer JSON-Datei
und zur Prüfung der Abrechnungsfähigkeit einer einzelnen Leistungsposition bereit.
"""
import json

def lade_regelwerk(path: str) -> dict:
    """
    Lädt das Regelwerk aus einer JSON-Datei und gibt ein Mapping von LKN zu Regeln zurück.

    Args:
        path: Pfad zur JSON-Datei mit strukturierten Regeln.
    Returns:
        Dict[str, list]: Schlüssel sind LKN-Codes, Werte sind Listen von Regel-Definitionsdicts.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    mapping: dict = {}
    for entry in data:
        lkn = entry.get("LKN")
        if not lkn:
            continue
        # Regeln unter dem Schlüssel "Regeln"
        rules = entry.get("Regeln") or []
        mapping[lkn] = rules
    return mapping

def pruefe_abrechnungsfaehigkeit(fall: dict, regelwerk: dict) -> dict:
    """
    Prüft, ob eine gegebene Leistungsposition abrechnungsfähig ist.

    Args:
        fall: Dict mit Kontext zur Leistung (LKN, Menge, ICD, Begleit-LKNs, Pauschalen,
              optional Alter, Geschlecht, GTIN).
        regelwerk: Mapping von LKN zu Regel-Definitionen aus lade_regelwerk.
    Returns:
        Dict mit Schlüsseln:
          - abbrechnungsfaehig (bool): True, wenn alle Regeln erfüllt sind.
          - fehler (list): Liste der Regelverstöße (Fehlermeldungen).
    """
    lkn = fall.get("LKN")
    menge = fall.get("Menge", 0) or 0
    begleit = fall.get("Begleit_LKNs") or []
    # Kontextdaten
    alter = fall.get("Alter")
    geschlecht = fall.get("Geschlecht")
    gtins = fall.get("GTIN") or []

    errors: list = []
    allowed = True

    # Hole die Regeln für diese LKN
    rules = regelwerk.get(lkn) or []
    # Keine Regeln => immer abrechnungsfähig
    for rule in rules:
        typ = rule.get("Typ")
        # Mengenbeschränkung: MaxMenge pro Sitzung
        if typ == "Mengenbeschränkung":
            max_menge = rule.get("MaxMenge")
            if isinstance(max_menge, (int, float)) and menge > max_menge:
                allowed = False
                errors.append(f"Mengenbeschränkung überschritten (max. {max_menge}, angefragt {menge})")
        # Nicht kumulierbar mit bestimmten LKNs
        elif typ == "Nicht kumulierbar mit":
            not_with = rule.get("LKNs") or []
            konflikt = [code for code in begleit if code in not_with]
            if konflikt:
                allowed = False
                codes = ", ".join(konflikt)
                errors.append(f"Nicht kumulierbar mit: {codes}")
        # Nur als Zuschlag zu einer anderen LKN
        elif typ == "Nur als Zuschlag zu":
            parent = rule.get("LKN")
            if parent and parent not in begleit:
                allowed = False
                errors.append(f"Nur als Zuschlag zu {parent}")
        # Patientenbedingung (Alter, Geschlecht etc.)
        elif typ == "Patientenbedingung":
            field = rule.get("Feld")
            wert = rule.get("Wert")
            # Wert aus dem Kontext holen
            val = None
            # Unterstützte Felder: Geschlecht, Alter, GTIN
            if field == "Geschlecht":
                val = geschlecht
            elif field == "Alter":
                val = alter
            elif field.upper() == "GTIN":
                # GTIN-Liste enthält mehrere Werte
                val = gtins
            # Prüfung je nach Datentyp
            if val is None:
                allowed = False
                errors.append(f"Patientenbedingung ({field}) nicht erfüllt: kein Wert")
            else:
                # Listen: prüfe, ob Wert in Liste
                if isinstance(val, list):
                    if isinstance(wert, list):
                        if not any(v in val for v in wert):
                            allowed = False
                            errors.append(f"Patientenbedingung ({field}): erwartet {wert}, gefunden {val}")
                    else:
                        if wert not in val:
                            allowed = False
                            errors.append(f"Patientenbedingung ({field}): erwartet {wert}, gefunden {val}")
                # Zahlen und Strings
                else:
                    # String-Vergleich (case-insensitive)
                    if isinstance(val, str) and isinstance(wert, str):
                        if val.lower() != wert.lower():
                            allowed = False
                            errors.append(f"Patientenbedingung ({field}): erwartet {wert}, gefunden {val}")
                    else:
                        # Versuche numerische Prüfung
                        try:
                            if float(val) != float(wert):
                                allowed = False
                                errors.append(f"Patientenbedingung ({field}): erwartet {wert}, gefunden {val}")
                        except Exception:
                            pass
        # Unbekannte Regeltypen werden ignoriert
        else:
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

    Args:
        pauschale_code: Der Code der zu prüfenden Pauschale.
        context: Dictionary mit Kontextinformationen (ICD, GTIN, LKN als Listen).
        pauschale_bedingungen_data: Liste aller Bedingungsobjekte aus tblPauschaleBedingungen.
        tabellen_data: Liste aller Einträge aus tblTabellen.

    Returns:
        Dict mit Schlüsseln:
          - allMet (bool): True, wenn alle Bedingungen erfüllt sind.
          - html (str): (Optional) HTML-String zur Darstellung der Prüfung (wie im JS).
                         Hier vereinfacht als Liste von Fehlern/Erfolgen.
          - errors (list): Liste der nicht erfüllten Bedingungen (Strings).
    """
    errors: list[str] = []
    condition_details: list[str] = [] # Für detailliertes Logging/HTML
    all_met = True

    # Finde alle Bedingungen für diese Pauschale
    conditions = [cond for cond in pauschale_bedingungen_data if cond.get("Pauschale") == pauschale_code]

    if not conditions:
        print(f"Info: Keine spezifischen Bedingungen für Pauschale {pauschale_code} gefunden.")
        return {"allMet": True, "html": "Keine Bedingungen gefunden.", "errors": []}

    print(f"Info: Prüfe {len(conditions)} Bedingungen für Pauschale {pauschale_code}...")

    # Kontext extrahieren (sicherstellen, dass es Listen sind)
    provided_icds = context.get("ICD", [])
    provided_gtins = context.get("GTIN", [])
    provided_lkns = context.get("LKN", [])
    if isinstance(provided_icds, str): provided_icds = [provided_icds]
    if isinstance(provided_gtins, str): provided_gtins = [provided_gtins]
    if isinstance(provided_lkns, str): provided_lkns = [provided_lkns]

    # Iteriere durch jede Bedingung
    for i, cond in enumerate(conditions):
        bedingungstyp = cond.get("Bedingungstyp", "").upper()
        werte_str = cond.get("Werte", "")
        werte_list = [w.strip() for w in str(werte_str).split(',') if w.strip()] # Aufteilen und leere entfernen
        tabelle_ref = cond.get("Tabelle") # Für Typ "IN TABELLE"

        condition_met = False
        bedingung_text = f"Typ: {bedingungstyp}, Wert/Ref: '{werte_str or tabelle_ref or '-'}'"

        if not werte_list and not tabelle_ref:
            print(f"WARNUNG: Bedingung {i+1} für {pauschale_code} hat keine Werte oder Tabelle.")
            condition_met = True # Im Zweifel als erfüllt annehmen? Oder False? Hier: True
        elif bedingungstyp == "ICD":
            condition_met = any(req_icd.upper() in (p_icd.upper() for p_icd in provided_icds) for req_icd in werte_list)
        elif bedingungstyp == "GTIN":
             condition_met = any(req_gtin in provided_gtins for req_gtin in werte_list)
        elif bedingungstyp == "LKN" or bedingungstyp == "LEISTUNGSPOSITIONEN IN LISTE":
             condition_met = any(req_lkn.upper() in (p_lkn.upper() for p_lkn in provided_lkns) for req_lkn in werte_list)
        elif bedingungstyp == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp == "TARIFPOSITIONEN IN TABELLE":
             # Suche Codes aus tblTabellen basierend auf der Referenz-Tabelle
             codes_in_tabelle = [
                 e.get("Code") for e in tabellen_data
                 if e.get("Tabelle") == tabelle_ref and e.get("Tabelle_Typ") == "service_catalog" and e.get("Code")
             ]
             condition_met = any(code.upper() in (p_lkn.upper() for p_lkn in provided_lkns) for code in codes_in_tabelle)
             bedingung_text += f" (Tabelle: {tabelle_ref})" # Füge Tabellenname hinzu
        elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE":
             codes_in_tabelle = [
                 e.get("Code") for e in tabellen_data
                 if e.get("Tabelle") == tabelle_ref and e.get("Tabelle_Typ") == "icd" and e.get("Code")
             ]
             condition_met = any(code.upper() in (p_icd.upper() for p_icd in provided_icds) for code in codes_in_tabelle)
             bedingung_text += f" (Tabelle: {tabelle_ref})"
        elif bedingungstyp == "MEDIKAMENTE IN LISTE":
             # Annahme: Werte sind GTINs
             condition_met = any(req_gtin in provided_gtins for req_gtin in werte_list)
        else:
            print(f"WARNUNG: Unbekannter Pauschalen-Bedingungstyp '{bedingungstyp}' für {pauschale_code}. Wird als erfüllt angenommen.")
            condition_met = True

        status_text = "Erfüllt" if condition_met else "NICHT erfüllt"
        condition_details.append(f" - {bedingung_text}: {status_text}")

        if not condition_met:
            all_met = False
            errors.append(f"Bedingung nicht erfüllt: {bedingung_text}")

    # Erstelle einfachen HTML-String für Details (optional)
    html_details = "<ul>" + "".join([f"<li>{detail}</li>" for detail in condition_details]) + "</ul>"

    return {
        "allMet": all_met,
        "html": html_details, # Optional, für Frontend-Anzeige
        "errors": errors      # Liste der Fehlertexte
    }