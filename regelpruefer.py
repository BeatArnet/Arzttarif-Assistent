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