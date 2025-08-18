# regelpruefer_einzelleistungen.py

"""
Modul zur Prüfung der Abrechnungsregeln (Regelwerk) für TARDOC-Leistungen
und der Bedingungen für Pauschalen.
"""
import json
import logging
import re  # Importiere Regex für Mengenanpassung
import configparser
from typing import Dict, List
from utils import get_lang_field

logger = logging.getLogger(__name__)

# Konfiguration für Regelprüfung laden
config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")
KUMULATION_EXPLIZIT = config.getint("REGELPRUEFUNG", "kumulation_explizit", fallback=0)

# --- Konstanten für Regeltypen (zur besseren Lesbarkeit) ---
REGEL_MENGE = "Mengenbeschränkung"
REGEL_ZUSCHLAG_ZU = "Nur als Zuschlag zu"
REGEL_NICHT_KUMULIERBAR = "Nicht kumulierbar mit"
REGEL_MOEG_ZUSATZPOSITIONEN = "Mögliche Zusatzpositionen"
REGEL_PAT_GESCHLECHT = (
    "Patientenbedingung: Geschlecht"  # Veraltet, nutze Patientenbedingung
)
REGEL_PAT_ALTER = "Patientenbedingung: Alter"  # Veraltet, nutze Patientenbedingung
REGEL_PAT_BEDINGUNG = "Patientenbedingung"  # Neuer, generischer Typ
REGEL_DIAGNOSE = "Diagnosepflicht"
REGEL_PAUSCHAL_AUSSCHLUSS = "Pauschalenausschluss"
# Regex-Pattern zur Erkennung von Varianten
REGEX_NICHT_KUMULIERBAR_VARIANT = re.compile(
    r"^Nicht kumulierbar(?:\s*\(([^)]*)\))?\s*mit$"
)
REGEX_NUR_KUMULIERBAR_VARIANT = re.compile(
    r"^Nur kumulierbar(?:\s*\(([^)]*)\))?\s*mit$"
)
REGEX_KUMULIERBAR_VARIANT = re.compile(r"^Kumulierbar(?:\s*\(([^)]*)\))?\s*mit$")
# Fügen Sie hier weitere Typen hinzu, falls Ihr Regelmodell sie enthält


# --- Ladefunktion für das Regelwerk ---
def lade_regelwerk(path: str) -> dict:
    """
    Lädt das Regelwerk aus einer JSON-Datei und gibt ein Mapping von LKN zu Regeln zurück.

    Args:
        path: Pfad zur JSON-Datei mit strukturierten Regeln.
    Returns:
        Dict[str, list]: Schlüssel sind LKN-Codes, Werte sind Listen von Regel-Definitionsdicts.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        mapping: dict = {}
        # Annahme: data ist eine Liste von Objekten, jedes mit "LKN" und "Regeln"
        for entry in data:
            lkn = entry.get("LKN")
            if not lkn:
                logger.warning("WARNUNG: Regelobjekt ohne LKN gefunden: %s", entry)
                continue
            lkn = str(lkn).upper()
            rules = entry.get("Regeln") or []
            mapping[lkn] = rules
        return mapping
    except FileNotFoundError:
        logger.error("FEHLER: Regelwerk-Datei nicht gefunden: %s", path)
        return {}
    except json.JSONDecodeError as e:
        logger.error(
            "FEHLER: Fehler beim Parsen der Regelwerk-JSON-Datei '%s': %s",
            path,
            e,
        )
        return {}
    except Exception as e:
        logger.error(
            "FEHLER: Unerwarteter Fehler beim Laden des Regelwerks '%s': %s",
            path,
            e,
        )
        return {}


# --- Hauptfunktion zur Regelprüfung für LKNs ---
def pruefe_abrechnungsfaehigkeit(
    fall: dict, regelwerk: dict, leistungsgruppen_map: dict | None = None
) -> dict:
    """
    Prüft, ob eine gegebene Leistungsposition abrechnungsfähig ist.

    Args:
        fall: Dict mit Kontext zur Leistung (LKN, Menge, ICD, Begleit-LKNs, Pauschalen,
              optional Alter, Geschlecht, GTIN).
        regelwerk: Mapping von LKN zu Regel-Definitionen aus lade_regelwerk.
    Returns:
        Dict mit Schlüsseln:
          - abrechnungsfaehig (bool): True, wenn alle Regeln erfüllt sind.
          - fehler (list): Liste der Regelverstösse (Fehlermeldungen).
    """
    lkn = str(fall.get("LKN") or "").upper()
    menge = fall.get("Menge", 0) or 0
    begleit = [str(code).upper() for code in (fall.get("Begleit_LKNs") or [])]
    leistungsgruppen_map = {
        str(k).upper(): {str(c).upper() for c in v}
        for k, v in (leistungsgruppen_map or {}).items()
    }
    # Kontextdaten
    alter = fall.get("Alter")
    geschlecht = fall.get("Geschlecht")
    gtins = fall.get("GTIN") or []  # Stelle sicher, dass GTIN hier ankommt
    if isinstance(gtins, str):
        gtins = [gtins]  # Mache zur Liste, falls String

    errors: list = []
    allowed = True
    moegliche_zusatzpositionen: list[str] = []
    hat_kumulierbar_regel = False

    # Hole die Regeln für diese LKN
    rules = regelwerk.get(lkn) or []
    if not rules:
        # Keine Regeln definiert -> gilt als OK
        return {"abrechnungsfaehig": True, "fehler": []}

    for rule in rules:
        typ = rule.get("Typ")
        if not typ:
            continue  # Regel ohne Typ ignorieren

        # --- Mengenbesschränkung ---
        if typ == REGEL_MENGE:
            max_menge = rule.get("MaxMenge")
            if isinstance(max_menge, (int, float)) and menge > max_menge:
                allowed = False
                errors.append(
                    f"Mengenbeschränkung überschritten (max. {max_menge}, angefragt {menge})"
                )

        # --- Nur als Zuschlag zu ---
        elif typ == REGEL_ZUSCHLAG_ZU:
            parent = rule.get("LKN")
            if isinstance(parent, str):
                parent = parent.upper()
            if parent and parent not in begleit:
                allowed = False
                errors.append(f"Nur als Zuschlag zu {parent} zulässig (Basis fehlt)")

        # --- Mögliche Zusatzpositionen ---
        elif typ == REGEL_MOEG_ZUSATZPOSITIONEN:
            zusatz = rule.get("LKNs") or rule.get("LKN") or []
            if isinstance(zusatz, str):
                zusatz = [zusatz]
            zusatz = [str(z).upper() for z in zusatz]
            moegliche_zusatzpositionen.extend(zusatz)

        # --- Nicht kumulierbar mit (inkl. Varianten) ---
        elif REGEX_NICHT_KUMULIERBAR_VARIANT.match(typ):
            not_with = rule.get("LKNs") or rule.get("LKN") or []
            if isinstance(not_with, str):
                not_with = [not_with]
            not_with = [str(nw).upper() for nw in not_with]
            type_match = REGEX_NICHT_KUMULIERBAR_VARIANT.match(typ)
            if type_match and type_match.group(1):
                typen_filter = [
                    t.strip().upper()
                    for t in type_match.group(1).split(",")
                    if t.strip()
                ]
            else:
                typen_filter = []
            konflikt = [
                code
                for code in begleit
                if code in not_with
                and (not typen_filter or code[:1] in typen_filter)
            ]
            if konflikt:
                allowed = False
                codes = ", ".join(konflikt)
                errors.append(f"Nicht kumulierbar mit: {codes}")

        # --- Nur kumulierbar mit ---
        elif typ.startswith("Nur kumulierbar"):
            allowed_entries = rule.get("LKNs") or rule.get("LKN") or []
            if isinstance(allowed_entries, str):
                allowed_entries = [allowed_entries]

            def match_entry(entry: str) -> bool:
                entry_str = entry.strip()
                entry_upper = entry_str.upper()
                if entry_upper.startswith("KAPITEL"):
                    prefix = entry_upper.replace("KAPITEL", "").strip()
                    return any(code.startswith(prefix) for code in begleit)
                if entry_upper.startswith("LEISTUNGSGRUPPE"):
                    gruppe = entry_upper.replace("LEISTUNGSGRUPPE", "").strip()
                    group_lkns = leistungsgruppen_map.get(gruppe)
                    if group_lkns is None:
                        return True  # Ohne Mapping keine Prüfung
                    return any(code in group_lkns for code in begleit)
                return any(entry_upper == code for code in begleit)

            if not any(match_entry(e) for e in allowed_entries):
                allowed = False
                errors.append("Nur kumulierbar mit: " + ", ".join(allowed_entries))

        # --- Kumulierbar mit ---
        elif typ.startswith("Kumulierbar"):
            entries = rule.get("LKNs") or rule.get("LKN") or []
            if isinstance(entries, str):
                entries = [entries]
            entries = [str(e).upper() for e in entries]
            moegliche_zusatzpositionen.extend(entries)
            hat_kumulierbar_regel = True
            continue  # Auswertung (nur bei expliziter Kumulation) erfolgt nach der Schleife

        # --- Patientenbedingung (Generisch) ---
        elif typ == REGEL_PAT_BEDINGUNG:
            field = rule.get("Feld")  # z.B. "Alter", "Geschlecht", "GTIN"
            wert_regel = rule.get("Wert")  # Wert aus der Regel
            min_val = rule.get("MinWert")  # Für Bereiche (z.B. Alter)
            max_val = rule.get("MaxWert")  # Für Bereiche (z.B. Alter)
            wert_fall = fall.get(field)  # Wert aus dem Abrechnungsfall

            bedingung_text = f"Patientenbedingung ({field})"
            condition_met = False

            if wert_fall is None:
                condition_met = (
                    False  # Bedingung nicht prüfbar/erfüllt, wenn Wert fehlt
                )
                errors.append(f"{bedingung_text} nicht erfüllt: Kontextwert fehlt")
            elif field == "Alter":
                try:
                    alter_patient = int(wert_fall)
                    alter_ok = True
                    range_parts = []
                    if min_val is not None and alter_patient < int(min_val):
                        alter_ok = False
                        range_parts.append(f"min. {min_val}")
                    if max_val is not None and alter_patient > int(max_val):
                        alter_ok = False
                        range_parts.append(f"max. {max_val}")
                    if wert_regel is not None and alter_patient != int(wert_regel):
                        alter_ok = False
                        range_parts.append(f"exakt {wert_regel}")  # Exakter Wert?
                    condition_met = alter_ok
                    if not condition_met:
                        errors.append(
                            f"{bedingung_text} ({' '.join(range_parts)}) nicht erfüllt (Patient: {alter_patient})"
                        )
                except (ValueError, TypeError):
                    condition_met = False
                    errors.append(
                        f"{bedingung_text}: Ungültiger Alterswert im Fall ({wert_fall})"
                    )
            elif field == "Geschlecht":
                if isinstance(wert_regel, str) and isinstance(wert_fall, str):
                    condition_met = wert_fall.lower() == wert_regel.lower()
                    if not condition_met:
                        errors.append(
                            f"{bedingung_text}: erwartet '{wert_regel}', gefunden '{wert_fall}'"
                        )
                else:
                    condition_met = False
                    errors.append(
                        f"{bedingung_text}: Ungültige Werte für Geschlechtsprüfung"
                    )
            elif field == "GTIN":
                # Prüfe, ob mindestens ein benötigter GTIN im Fall vorhanden ist
                required_gtins = (
                    [str(wert_regel)]
                    if isinstance(wert_regel, (str, int))
                    else [str(w) for w in (wert_regel or [])]
                )
                provided_gtins_str = [
                    str(g) for g in (gtins or [])
                ]  # Nutze gtins Variable
                condition_met = any(req in provided_gtins_str for req in required_gtins)
                if not condition_met:
                    errors.append(
                        f"{bedingung_text}: Erwartet einen von {required_gtins}, nicht gefunden"
                    )
            else:
                logger.info(
                    "Unbekanntes Feld '%s' für Patientenbedingung bei LKN %s.",
                    field,
                    lkn,
                )
                condition_met = True  # Unbekannte Felder ignorieren

            if not condition_met:
                allowed = False

        # --- Diagnosepflicht ---
        elif typ == REGEL_DIAGNOSE:
            required_icds = rule.get("ICD") or rule.get("ICDs", [])
            if isinstance(required_icds, str):
                required_icds = [required_icds]
            provided_icds = fall.get("ICD", [])
            if isinstance(provided_icds, str):
                provided_icds = [provided_icds]

            if required_icds and not any(
                req_icd.upper() in (p_icd.upper() for p_icd in provided_icds)
                for req_icd in required_icds
            ):
                allowed = False
                errors.append(
                    f"Erforderliche Diagnose(n) nicht vorhanden (Benötigt: {', '.join(required_icds)})"
                )

        # --- Pauschalenausschluss ---
        elif typ == REGEL_PAUSCHAL_AUSSCHLUSS:
            verbotene_pauschalen = rule.get("Pauschale") or rule.get("Pauschalen", [])
            if isinstance(verbotene_pauschalen, str):
                verbotene_pauschalen = [verbotene_pauschalen]
            abgerechnete_pauschalen = fall.get("Pauschalen", [])
            if isinstance(abgerechnete_pauschalen, str):
                abgerechnete_pauschalen = [abgerechnete_pauschalen]

            if any(verb in abgerechnete_pauschalen for verb in verbotene_pauschalen):
                allowed = False
                errors.append(
                    f"Leistung nicht zulässig bei gleichzeitiger Abrechnung der Pauschale(n): {', '.join(verbotene_pauschalen)}"
                )

        # --- Unbekannter Regeltyp ---
        else:
            logger.info(
                "Unbekannter Regeltyp '%s' für LKN %s ignoriert.",
                typ,
                lkn,
            )
            continue

    # Explizite Kumulation prüfen, falls konfiguriert und Regeln vorhanden
    if KUMULATION_EXPLIZIT and hat_kumulierbar_regel and moegliche_zusatzpositionen:
        moegliche_zusatzpositionen = list(dict.fromkeys(moegliche_zusatzpositionen))

        def code_erlaubt(code: str) -> bool:
            for entry in moegliche_zusatzpositionen:
                e_str = entry.strip()
                e_upper = e_str.upper()
                if e_upper.startswith("KAPITEL"):
                    prefix = e_upper.replace("KAPITEL", "").strip()
                    if code.startswith(prefix):
                        return True
                elif e_upper.startswith("LEISTUNGSGRUPPE"):
                    gruppe = e_upper.replace("LEISTUNGSGRUPPE", "").strip()
                    group_lkns = leistungsgruppen_map.get(gruppe)
                    if group_lkns is None:
                        return True  # Ohne Mapping keine Prüfung
                    if code in group_lkns:
                        return True
                elif code == e_upper:
                    return True
            return False

        ungueltig = [code for code in begleit if not code_erlaubt(code)]
        if ungueltig:
            allowed = False
            errors.append(
                "Nur kumulierbar mit: " + ", ".join(moegliche_zusatzpositionen)
            )

    return {"abrechnungsfaehig": allowed, "fehler": errors}


def prepare_tardoc_abrechnung(
    regel_ergebnisse_liste: list[dict], leistungskatalog_dict: dict, lang: str = "de"
) -> dict:
    """
    Filtert regelkonforme TARDOC-Leistungen (Typ E/EZ) aus den Regelergebnissen
    und bereitet die Liste für die Frontend-Antwort vor.
    """
    logger.info("INFO (regelpruefer): TARDOC-Abrechnung wird vorbereitet...")
    tardoc_leistungen_final = []
    LKN_KEY = "lkn"
    MENGE_KEY = "finale_menge"

    for res in regel_ergebnisse_liste:
        lkn = res.get(LKN_KEY)
        menge = res.get(MENGE_KEY, 0)
        abrechnungsfaehig = res.get("regelpruefung", {}).get("abrechnungsfaehig", False)

        if not lkn or not abrechnungsfaehig or menge <= 0:
            continue

        # Hole Details aus dem übergebenen Leistungskatalog
        lkn_info = leistungskatalog_dict.get(str(lkn).upper())  # Suche Case-Insensitive

        if lkn_info and lkn_info.get("Typ") in ["E", "EZ"]:
            tardoc_leistungen_final.append(
                {
                    "lkn": lkn,
                    "menge": menge,
                    "typ": lkn_info.get("Typ"),
                    "beschreibung": get_lang_field(lkn_info, "Beschreibung", lang)
                    or "",
                }
            )
        elif not lkn_info:
            logger.warning(
                "WARNUNG (prepare_tardoc): Details für LKN %s nicht im Leistungskatalog gefunden.",
                lkn,
            )

    if not tardoc_leistungen_final:
        return {
            "type": "Error",
            "message": "Keine abrechenbaren TARDOC-Leistungen nach Regelprüfung gefunden.",
        }
    else:
        logger.info(
            "INFO (regelpruefer): %s TARDOC-Positionen zur Abrechnung vorbereitet.",
            len(tardoc_leistungen_final),
        )
        return {"type": "TARDOC", "leistungen": tardoc_leistungen_final}
