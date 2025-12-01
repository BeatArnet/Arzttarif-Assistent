# regelpruefer_einzelleistungen.py

"""Regelwerk für individuelle Tarifpositionen ohne Pauschalen.

Die Hilfsfunktionen laden den JSON-Regelkatalog und prüfen sämtliche
Konfigurationen gegen eine vorgeschlagene Abrechnungsposition. Abgedeckt werden
Mengenbegrenzungen, Pflicht-Basisleistungen, gegenseitige Ausschlüsse,
optionale Zuschläge, Patientendaten, ICD-Vorgaben u.v.m. Der öffentliche Einstieg
``pruefe_abrechnungsfaehigkeit`` wird von ``server.py`` nach den LLM-Vorschlägen
aufgerufen und liefert strukturierte Fehler zurück, damit die Oberfläche
verletzte Regeln hervorheben kann.
"""
import logging
import re  # Importiere Regex für Mengenanpassung
import configparser
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Set, TypedDict, cast

from utils import get_lang_field

logger = logging.getLogger(__name__)

# Konfiguration für Regelprüfung laden
config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8-sig")
KUMULATION_EXPLIZIT = config.getint("REGELPRUEFUNG", "kumulation_explizit", fallback=0)

# --- Konstanten für Regeltypen (zur besseren Lesbarkeit) ---
REGEL_MENGE = "Mengenbeschränkung"
REGEL_ZUSCHLAG_ZU = "Nur als Zuschlag zu"
REGEL_NICHT_KUMULIERBAR = "Nicht kumulierbar mit"
REGEL_MOEG_ZUSATZPOSITIONEN = "Mögliche Zusatzpositionen"
REGEL_PAT_BEDINGUNG = "Patientenbedingung"  # Neuer, generischer Typ
REGEL_DIAGNOSE = "Diagnosepflicht"
REGEL_PAUSCHAL_AUSSCHLUSS = "Pauschalenausschluss"
# Regex-Pattern zur Erkennung von Varianten
REGEX_NICHT_KUMULIERBAR_VARIANT = re.compile(
    r"^Nicht kumulierbar(?:\s*\(([^)]*)\))?\s*mit$"
)
# Fügen Sie hier weitere Typen hinzu, falls Ihr Regelmodell sie enthält


class FallKontext(TypedDict, total=False):
    LKN: str
    Menge: int
    Begleit_LKNs: List[str]
    Begleit_Typen: Dict[str, str]
    Typ: str
    Alter: int
    Geschlecht: str
    Medikamente: List[str]
    GTIN: List[str]
    ICD: List[str]
    Pauschalen: List[str]


class RegelDefinition(TypedDict, total=False):
    Typ: str
    MaxMenge: int
    LKNs: List[str]
    LKN: List[str] | str
    Feld: str
    Wert: str | int | None
    MinWert: int | None
    MaxWert: int | None
    ICD: List[str] | str
    ICDs: List[str] | str
    Pauschale: List[str] | str
    Pauschalen: List[str] | str


def _coerce_fall(fall_input: FallKontext | Mapping[str, Any]) -> FallKontext:
    """Cast eingehende Fälle defensiv auf den TypedDict."""
    return cast(FallKontext, fall_input)


def _coerce_rule(rule_input: RegelDefinition | Mapping[str, Any]) -> RegelDefinition:
    """Cast Regeldatensätze aus JSON/Dict in den TypedDict."""
    return cast(RegelDefinition, rule_input)


@dataclass
class RuleEvaluationContext:
    fall: FallKontext
    lkn: str
    menge: int
    begleit: List[str]
    begleit_typen: Dict[str, str]
    leistungsgruppen_map: Dict[str, Set[str]]
    medications: List[str]


@dataclass
class RuleEvaluationState:
    errors: List[str] = field(default_factory=list)
    allowed: bool = True
    moegliche_zusatzpositionen: List[str] = field(default_factory=list)
    hat_kumulierbar_regel: bool = False

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.allowed = False


RuleHandler = Callable[[RegelDefinition, RuleEvaluationContext, RuleEvaluationState], None]


# --- Hauptfunktion zur Regelprüfung für LKNs ---
def _normalize_rule_codes(
    entries: object,
    *,
    uppercase: bool = True,
) -> List[str]:
    if entries is None:
        return []
    if isinstance(entries, str):
        values = [entries]
    else:
        values = list(entries) if isinstance(entries, Sequence) else []
    if uppercase:
        return [str(entry).upper() for entry in values if entry]
    return [str(entry) for entry in values if entry]


def _check_rule_menge(
    rule: RegelDefinition,
    ctx: RuleEvaluationContext,
    state: RuleEvaluationState,
) -> None:
    max_menge = rule.get("MaxMenge")
    if isinstance(max_menge, (int, float)) and ctx.menge > max_menge:
        state.add_error(
            f"Mengenbeschränkung überschritten (max. {max_menge}, angefragt {ctx.menge})"
        )


def _check_rule_zuschlag(
    rule: RegelDefinition,
    ctx: RuleEvaluationContext,
    state: RuleEvaluationState,
) -> None:
    parents = _normalize_rule_codes(rule.get("LKNs") or rule.get("LKN"))
    if not parents:
        logger.info(
            "Regel 'Nur als Zuschlag zu' ohne Basisangabe bei LKN %s ignoriert.",
            ctx.lkn,
        )
        return
    if not any(parent in ctx.begleit for parent in parents):
        state.add_error(
            "Nur als Zuschlag zu " + ", ".join(parents) + " zulässig (Basis fehlt)"
        )


def _collect_possible_additions(
    rule: RegelDefinition,
    ctx: RuleEvaluationContext,
    state: RuleEvaluationState,
) -> None:
    zusatz = _normalize_rule_codes(rule.get("LKNs") or rule.get("LKN"))
    state.moegliche_zusatzpositionen.extend(zusatz)


def _check_rule_patient_condition(
    rule: RegelDefinition,
    ctx: RuleEvaluationContext,
    state: RuleEvaluationState,
) -> None:
    field = rule.get("Feld")
    if not field:
        return
    wert_regel = rule.get("Wert")
    min_val = rule.get("MinWert")
    max_val = rule.get("MaxWert")
    wert_fall = ctx.fall.get(field)

    bedingung_text = f"Patientenbedingung ({field})"
    field_normalized = str(field).upper()

    if wert_fall is None:
        state.add_error(f"{bedingung_text} nicht erfüllt: Kontextwert fehlt")
        return

    if field == "Alter":
        try:
            alter_patient = int(wert_fall)
        except (TypeError, ValueError):
            state.add_error(
                f"{bedingung_text}: Ungültiger Alterswert im Fall ({wert_fall})"
            )
            return
        range_parts: List[str] = []
        if min_val is not None and alter_patient < int(min_val):
            range_parts.append(f"min. {min_val}")
        if max_val is not None and alter_patient > int(max_val):
            range_parts.append(f"max. {max_val}")
        if wert_regel is not None and alter_patient != int(wert_regel):
            range_parts.append(f"exakt {wert_regel}")
        if range_parts:
            state.add_error(
                f"{bedingung_text} ({' '.join(range_parts)}) nicht erfüllt (Patient: {alter_patient})"
            )
        return

    if field == "Geschlecht":
        if isinstance(wert_regel, str) and isinstance(wert_fall, str):
            if wert_fall.lower() != wert_regel.lower():
                state.add_error(
                    f"{bedingung_text}: erwartet '{wert_regel}', gefunden '{wert_fall}'"
                )
        else:
            state.add_error(
                f"{bedingung_text}: Ungültige Werte für Geschlechtsprüfung"
            )
        return

    if field_normalized in {"GTIN", "MEDIKAMENTE", "MEDIKAMENT", "ATC"}:
        required_medications = (
            [str(wert_regel)]
            if isinstance(wert_regel, (str, int))
            else [str(w) for w in (wert_regel or [])]
        )
        provided_medications_upper = ctx.medications
        if not any(
            str(req).upper() in provided_medications_upper for req in required_medications
        ):
            state.add_error(
                f"{bedingung_text}: Erwartet einen von {required_medications}, nicht gefunden"
            )
        return

    logger.info(
        "Unbekanntes Feld '%s' für Patientenbedingung bei LKN %s.",
        field,
        ctx.lkn,
    )


def _check_rule_diagnose(
    rule: RegelDefinition,
    ctx: RuleEvaluationContext,
    state: RuleEvaluationState,
) -> None:
    required_icds = rule.get("ICD") or rule.get("ICDs") or []
    required_icds = _normalize_rule_codes(required_icds)
    provided_icds = ctx.fall.get("ICD", [])
    if isinstance(provided_icds, str):
        provided_icds = [provided_icds]
    provided_upper = {str(code).upper() for code in provided_icds if code}
    if required_icds and not any(req in provided_upper for req in required_icds):
        state.add_error(
            f"Erforderliche Diagnose(n) nicht vorhanden (Benötigt: {', '.join(required_icds)})"
        )


def _check_rule_pauschal_ausschluss(
    rule: RegelDefinition,
    ctx: RuleEvaluationContext,
    state: RuleEvaluationState,
) -> None:
    verbotene = rule.get("Pauschale") or rule.get("Pauschalen") or []
    verbotene = _normalize_rule_codes(verbotene)
    abgerechnete = ctx.fall.get("Pauschalen", [])
    if isinstance(abgerechnete, str):
        abgerechnete = [abgerechnete]
    abgerechnete_upper = {str(code).upper() for code in abgerechnete if code}
    if any(verb in abgerechnete_upper for verb in verbotene):
        state.add_error(
            f"Leistung nicht zulässig bei gleichzeitiger Abrechnung der Pauschale(n): {', '.join(verbotene)}"
        )


def _check_rule_kumulation(
    typ: str,
    rule: RegelDefinition,
    ctx: RuleEvaluationContext,
    state: RuleEvaluationState,
) -> bool:
    if REGEX_NICHT_KUMULIERBAR_VARIANT.match(typ):
        not_with = _normalize_rule_codes(rule.get("LKNs") or rule.get("LKN"))
        type_match = REGEX_NICHT_KUMULIERBAR_VARIANT.match(typ)
        if type_match and type_match.group(1):
            typen_filter = [
                t.strip().upper() for t in type_match.group(1).split(",") if t.strip()
            ]
        else:
            typen_filter = []
        konflikt: List[str] = []
        for code in ctx.begleit:
            if code not in not_with:
                continue
            if not typen_filter:
                konflikt.append(code)
                continue
            code_typ = ctx.begleit_typen.get(code)
            if code_typ and code_typ in typen_filter:
                konflikt.append(code)
            elif not code_typ:
                konflikt.append(code)
        if konflikt:
            state.add_error("Nicht kumulierbar mit: " + ", ".join(konflikt))
        return True

    if typ.startswith("Nur kumulierbar"):
        allowed_entries = _normalize_rule_codes(rule.get("LKNs") or rule.get("LKN"), uppercase=False)

        def match_entry(entry: str) -> bool:
            entry_str = entry.strip()
            entry_upper = entry_str.upper()
            if entry_upper.startswith("KAPITEL"):
                prefix = entry_upper.replace("KAPITEL", "").strip()
                return any(code.startswith(prefix) for code in ctx.begleit)
            if entry_upper.startswith("LEISTUNGSGRUPPE"):
                gruppe = entry_upper.replace("LEISTUNGSGRUPPE", "").strip()
                group_lkns = ctx.leistungsgruppen_map.get(gruppe)
                if group_lkns is None:
                    return True
                return any(code in group_lkns for code in ctx.begleit)
            return any(entry_upper == code for code in ctx.begleit)

        if not any(match_entry(entry) for entry in allowed_entries):
            state.add_error("Nur kumulierbar mit: " + ", ".join(allowed_entries))
        return True

    if typ.startswith("Kumulierbar"):
        entries = _normalize_rule_codes(rule.get("LKNs") or rule.get("LKN"))
        state.moegliche_zusatzpositionen.extend(entries)
        state.hat_kumulierbar_regel = True
        return True

    return False


HANDLER_DISPATCH: Dict[str, RuleHandler] = {
    REGEL_MENGE: _check_rule_menge,
    REGEL_ZUSCHLAG_ZU: _check_rule_zuschlag,
    REGEL_MOEG_ZUSATZPOSITIONEN: _collect_possible_additions,
    REGEL_PAT_BEDINGUNG: _check_rule_patient_condition,
    REGEL_DIAGNOSE: _check_rule_diagnose,
    REGEL_PAUSCHAL_AUSSCHLUSS: _check_rule_pauschal_ausschluss,
}


def pruefe_abrechnungsfaehigkeit(
    fall: FallKontext | Mapping[str, Any],
    regelwerk: Mapping[str, Sequence[RegelDefinition | Mapping[str, Any]]],
    leistungsgruppen_map: Mapping[str, Sequence[str]] | None = None,
    *,
    kumulation_explizit: Optional[int] = None,
) -> dict:
    """
    Pr?ft, ob eine gegebene Leistungsposition abrechnungsf?hig ist.

    Args:
        fall: Kontext zur Leistung (LKN, Menge, ICD, Begleit-LKNs, Pauschalen,
              optional Alter, Geschlecht, GTIN).
        regelwerk: Mapping von LKN zu Regel-Definitionen aus lade_regelwerk.
        leistungsgruppen_map: Optionales Mapping f?r Gruppenkumulationen.
        kumulation_explizit: Override f?r die explizite Kumulationspr?fung.
    """
    kumulation_explizit = KUMULATION_EXPLIZIT if kumulation_explizit is None else kumulation_explizit

    fall_data = _coerce_fall(fall)

    lkn = str(fall_data.get("LKN") or "").upper()
    menge = int(fall_data.get("Menge", 0) or 0)
    begleit = [str(code).upper() for code in (fall_data.get("Begleit_LKNs") or []) if code]
    typ_lkn = str(fall_data.get("Typ") or "").upper()

    raw_begleit_typen = fall_data.get("Begleit_Typen") or {}
    if isinstance(raw_begleit_typen, MutableMapping):
        begleit_typen = {
            str(code).upper(): str(t).upper()
            for code, t in raw_begleit_typen.items()
            if code
        }
    else:
        begleit_typen = {}
    if typ_lkn and lkn and lkn not in begleit_typen:
        begleit_typen[lkn] = typ_lkn

    norm_leistungsgruppen = {
        str(k).upper(): {str(c).upper() for c in (v or []) if c}
        for k, v in (leistungsgruppen_map or {}).items()
    }

    medications = fall_data.get("Medikamente")
    if medications is None:
        medications = fall_data.get("GTIN")
    if medications is None:
        medications = []
    if isinstance(medications, str):
        medications = [medications]
    medications_upper = [str(code).upper() for code in medications if code]

    ctx = RuleEvaluationContext(
        fall=fall_data,
        lkn=lkn,
        menge=menge,
        begleit=begleit,
        begleit_typen=begleit_typen,
        leistungsgruppen_map=norm_leistungsgruppen,
        medications=medications_upper,
    )
    state = RuleEvaluationState()

    rules_raw = list(regelwerk.get(lkn) or [])
    if not rules_raw:
        return {"abrechnungsfaehig": True, "fehler": []}

    rules = [_coerce_rule(rule) for rule in rules_raw]

    for rule in rules:
        typ = str(rule.get("Typ") or "").strip()
        if not typ:
            continue
        handler = HANDLER_DISPATCH.get(typ)
        if handler:
            handler(rule, ctx, state)
            continue
        if _check_rule_kumulation(typ, rule, ctx, state):
            continue
        logger.info("Unbekannter Regeltyp '%s' f?r LKN %s ignoriert.", typ, lkn)

    if kumulation_explizit and state.hat_kumulierbar_regel and state.moegliche_zusatzpositionen:
        state.moegliche_zusatzpositionen = list(dict.fromkeys(state.moegliche_zusatzpositionen))

        def code_erlaubt(code: str) -> bool:
            for entry in state.moegliche_zusatzpositionen:
                entry_upper = entry.upper()
                if entry_upper.startswith("KAPITEL"):
                    prefix = entry_upper.replace("KAPITEL", "").strip()
                    if code.startswith(prefix):
                        return True
                elif entry_upper.startswith("LEISTUNGSGRUPPE"):
                    gruppe = entry_upper.replace("LEISTUNGSGRUPPE", "").strip()
                    group_lkns = norm_leistungsgruppen.get(gruppe)
                    if group_lkns is None or code in group_lkns:
                        return True
                elif code == entry_upper:
                    return True
            return False

        ungueltig = [code for code in begleit if not code_erlaubt(code)]
        if ungueltig:
            state.add_error(
                "Nur kumulierbar mit: " + ", ".join(state.moegliche_zusatzpositionen)
            )

    return {"abrechnungsfaehig": state.allowed, "fehler": state.errors}


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
