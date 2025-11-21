"""Geschäftslogik zur Prüfung und Erläuterung von Pauschalen-Regeln.

Das Modul wird von ``server.py`` eingebunden, um zu entscheiden, ob eine
vorgeschlagene Pauschale abgerechnet werden darf. Es liest die strukturierten
Bedingungen aus dem Katalogexport, gleicht sie mit dem vom LLM gelieferten
Kontext ab und erstellt verständliche HTML-Berichte. Die Implementierung ist
defensiv gehalten, da viele Bedingungstypen optional sind oder nur teilweise im
Quellmaterial abgebildet werden. Schlägt der Import auf dem Zielsystem fehl,
fallen die Aufrufer auf No-Op-Fallbacks zurück, damit der Rest der Anwendung
weiterläuft.
"""

# regelpruefer_pauschale.py (Version mit korrigiertem Import und 9 Argumenten)
import traceback
import json
import logging
import ast
from dataclasses import dataclass, field
from functools import lru_cache, wraps
from typing import (
    Dict,
    List,
    Any,
    Set,
    Optional,
    Tuple,
    Mapping,
    Iterable,
    Sequence,
    DefaultDict,
    MutableMapping,
    cast,
)
from collections import defaultdict
from utils import (
    escape,
    get_table_content,
    get_lang_field,
    translate,
    translate_condition_type,
    create_html_info_link,
    activate_table_content_cache,
    deactivate_table_content_cache,
)
from runtime_config import load_base_config
import re, html

logger = logging.getLogger(__name__)

__all__ = [
    "check_pauschale_conditions",
    "check_pauschale_conditions_structured",
    "get_simplified_conditions",
    "render_condition_results_html",
    "generate_condition_detail_html",
    "determine_applicable_pauschale",
    "evaluate_pauschale_logic_orchestrator", # Added
    "check_single_condition",               # Added
    "DEFAULT_GROUP_OPERATOR",               # Added
    "get_group_operator_for_pauschale",     # Added
    "build_pauschale_condition_structure_index",
    # _evaluate_boolean_tokens and evaluate_single_condition_group are internal
]

# Standardoperator zur Verknüpfung der Bedingungsgruppen. (Wird für Funktions-Defaults benötigt)
# "UND" ist der konservative Default und kann zentral angepasst werden.
DEFAULT_GROUP_OPERATOR = "UND"


def with_table_content_cache(func):
    """Ensure table lookups reuse a request-scoped cache while the function runs."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        token = activate_table_content_cache()
        try:
            return func(*args, **kwargs)
        finally:
            deactivate_table_content_cache(token)

    return wrapper


_DEFAULT_EXCLUDED_LKN_TABLES = {"or", "elt", "nonelt", "anast"}
_EXCLUDED_LKN_TABLES_CONFIG_SECTION = "REGELPRUEFUNG"
_EXCLUDED_LKN_TABLES_CONFIG_KEY = "pauschale_explanation_excluded_lkn_tables"


@lru_cache(maxsize=1)
def get_excluded_lkn_tables() -> Set[str]:
    """Read the configurable list of LKN tables that should be ignored."""
    try:
        cfg = load_base_config()
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning(
            "Konfiguration konnte nicht geladen werden, nutze Default-Ausschlussliste: %s",
            exc,
        )
        return set(_DEFAULT_EXCLUDED_LKN_TABLES)

    if not cfg.has_section(_EXCLUDED_LKN_TABLES_CONFIG_SECTION):
        return set(_DEFAULT_EXCLUDED_LKN_TABLES)

    raw_value = cfg.get(
        _EXCLUDED_LKN_TABLES_CONFIG_SECTION,
        _EXCLUDED_LKN_TABLES_CONFIG_KEY,
        fallback=",".join(sorted(_DEFAULT_EXCLUDED_LKN_TABLES)),
    )
    candidates = {token.strip().lower() for token in raw_value.split(',') if token.strip()}
    if not candidates:
        return set(_DEFAULT_EXCLUDED_LKN_TABLES)
    return candidates


_COMPARISON_OPERATOR_PATTERN = r"(?:>=|<=|!=|=|>|<|>\s*=|<\s*=|!\s*=)"

CONDITION_PATTERN = re.compile(
    rf"((?:Hauptdiagnose in Tabelle|Hauptdiagnose in Liste|ICD in Tabelle|ICD in Liste|"
    rf"Leistungspositionen in Tabelle|Leistungspositionen in Liste|Medikamente in Liste|"
    rf"Tarifpositionen in Tabelle|Geschlecht in Liste)"
    rf"\s*\([^()]*\)"
    rf"(?:\swhere\s\((?:[^()]+|\([^()]*\))*\))?"
    rf"|Alter in Jahren bei Eintritt\s*{_COMPARISON_OPERATOR_PATTERN}\s*-?\d+"
    rf"|Anzahl\s*{_COMPARISON_OPERATOR_PATTERN}\s*-?\d+"
    rf"|Seitigkeit\s*=\s*'?[A-Za-z]+'?"
    rf"|1\s*=\s*1"
    rf")",
    flags=re.IGNORECASE,
)

DIAGNOSIS_TABLE_EXTRA_CODES = {
    'CAP08': {'S03.0'},
}


ICD_CONDITION_TYPES = {
    'ICD',
    'ICD IN LISTE',
    'ICD IN TABELLE',
    'HAUPTDIAGNOSE IN LISTE',
    'HAUPTDIAGNOSE IN TABELLE',
}

LKN_LIST_CONDITION_TYPES = {
    'LKN',
    'LKN IN LISTE',
    'LEISTUNGSPOSITIONEN IN LISTE',
}

LKN_TABLE_CONDITION_TYPES = {
    'LKN IN TABELLE',
    'LEISTUNGSPOSITIONEN IN TABELLE',
    'TARIFPOSITIONEN IN TABELLE',
}

_PRUEFLOGIK_ICD_TOKENS = ('icd', 'hauptdiagnose')


@dataclass(frozen=True)
class NormalizedContext:
    """Collection of precomputed context values used during rule evaluation."""

    raw: Mapping[str, Any]
    use_icd: bool
    icd_codes: frozenset[str]
    medication_codes: frozenset[str]
    lkn_codes: frozenset[str]
    geschlecht_lower: str
    seitigkeit_lower: str
    alter: Any
    alter_bei_eintritt: Any
    anzahl: Any

    def get(self, key: str, default: Any = None) -> Any:
        """Proxy dict-style access to the original context."""
        return self.raw.get(key, default)


def build_normalized_context(context: Optional[Mapping[str, Any]]) -> NormalizedContext:
    """Return a :class:`NormalizedContext` with cached lookups for expensive checks."""

    base_context: Mapping[str, Any] = context or {}

    icd_codes = frozenset(
        str(icd).upper() for icd in base_context.get("ICD", []) if icd
    )
    medication_candidates = [
        str(item).upper() for item in base_context.get("Medikamente", []) if item
    ]
    if not medication_candidates:
        medication_candidates = [
            str(item).upper() for item in base_context.get("GTIN", []) if item
        ]
    medication_codes = frozenset(medication_candidates)
    lkn_codes = frozenset(
        str(lkn).upper() for lkn in base_context.get("LKN", []) if lkn
    )

    geschlecht_lower = str(base_context.get("Geschlecht", "unbekannt") or "unbekannt").lower()
    seitigkeit_lower = str(base_context.get("Seitigkeit", "unbekannt") or "unbekannt").lower()

    return NormalizedContext(
        raw=base_context,
        use_icd=bool(base_context.get("useIcd", True)),
        icd_codes=icd_codes,
        medication_codes=medication_codes,
        lkn_codes=lkn_codes,
        geschlecht_lower=geschlecht_lower,
        seitigkeit_lower=seitigkeit_lower,
        alter=base_context.get("Alter"),
        alter_bei_eintritt=base_context.get("AlterBeiEintritt"),
        anzahl=base_context.get("Anzahl"),
    )


@dataclass
class PreparedConditionGroup:
    """Static definition of a Pauschalen-Bedingungsgruppe."""

    id: Any
    normalized_id: Any
    sort_index: Any
    parent: Any
    group_operator: str
    negated: bool
    conditions: List[MutableMapping[str, Any]] = field(default_factory=list)
    intra_ops: List[str] = field(default_factory=list)


@dataclass
class PreparedPauschaleStructure:
    """Precomputed representation of all Bedingungen for a Pauschale."""

    groups: List[PreparedConditionGroup] = field(default_factory=list)
    inter_group_ops: List[str] = field(default_factory=list)
    group_children: Dict[Any, List[Dict[str, Any]]] = field(default_factory=dict)
    sequence: List[Dict[str, Any]] = field(default_factory=list)
    has_real_conditions: bool = False
    group_lookup: Dict[Any, PreparedConditionGroup] = field(default_factory=dict)


def _normalize_group_identifier(value: Any) -> Any:
    """Normalize group identifiers to comparable values."""

    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        stripped = str(value).strip()
        if not stripped:
            return None
        return int(stripped)
    except (ValueError, TypeError):
        stripped = str(value).strip()
        return stripped if stripped else None


def _normalize_operator_label(value: Any, default: str = "") -> str:
    """Normalize UND/ODER operators while keeping unknown tokens untouched."""

    if value is None:
        return default
    upper = str(value).strip().upper()
    if upper in ("UND", "AND"):
        return "UND"
    if upper in ("ODER", "OR"):
        return "ODER"
    return upper if upper else default


def _condition_sort_key(cond: Mapping[str, Any]) -> Tuple[Any, Any, Any]:
    """Stable ordering for Bedingungszeilen innerhalb einer Pauschale."""

    return (
        cond.get("GruppeSortIndex", cond.get("Gruppe", 0)),
        cond.get("BedingungSortIndex", cond.get("BedingungsID", 0)),
        cond.get("BedingungsID", 0),
    )


def _sort_group_key(value: Any) -> Tuple[int, str]:
    """Sort key that mirrors the previous orchestrator ordering."""

    if isinstance(value, int):
        return (0, str(value))
    return (1, str(value))


def build_pauschale_condition_structure_index(
    pauschale_bedingungen_data: Sequence[Mapping[str, Any]]
) -> Dict[str, PreparedPauschaleStructure]:
    """Create a map ``pauschale_code -> PreparedPauschaleStructure`` once."""

    grouped: DefaultDict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for cond in pauschale_bedingungen_data:
        code = cond.get("Pauschale")
        if code is None:
            continue
        grouped[str(code)].append(cond)

    return {
        code: _prepare_single_pauschale_structure(code, items)
        for code, items in grouped.items()
    }


def _prepare_single_pauschale_structure(
    pauschale_code: str,
    conditions: Sequence[Mapping[str, Any]],
) -> PreparedPauschaleStructure:
    """Precompute grouping, AST links and ordering for one Pauschale."""

    sorted_conditions = sorted(conditions, key=_condition_sort_key)
    has_real_conditions = any(
        str(cond.get("Bedingungstyp", "")).upper() != "AST VERBINDUNGSOPERATOR"
        for cond in sorted_conditions
    )

    group_meta: Dict[Any, Dict[str, Any]] = {}
    inter_group_operators_map: Dict[Any, str] = {}
    inter_group_ops_out: List[str] = []
    sequence: List[Dict[str, Any]] = []
    ast_links: List[Tuple[Any, Any, str, int]] = []
    groups: List[PreparedConditionGroup] = []
    group_lookup: Dict[Any, PreparedConditionGroup] = {}

    current_group: Optional[PreparedConditionGroup] = None
    synthetic_group_counter = 0

    for cond in sorted_conditions:
        cond_type_upper = str(cond.get("Bedingungstyp", "")).upper()
        if cond_type_upper == "AST VERBINDUNGSOPERATOR":
            parent_norm = _normalize_group_identifier(cond.get("Gruppe"))
            child_candidate = cond.get("Spezialbedingung")
            if child_candidate is None or str(child_candidate).strip() == "":
                child_candidate = cond.get("Werte")
            child_norm = _normalize_group_identifier(child_candidate)
            op_logic = _normalize_operator_label(cond.get("Operator"), default="ODER")
            ast_links.append((parent_norm, child_norm, op_logic, cond.get("BedingungsID", 0)))
            if child_norm is not None and op_logic in ("UND", "ODER"):
                inter_group_operators_map[child_norm] = op_logic
            op_display = _normalize_operator_label(cond.get("Werte"), default="")
            if op_display in ("UND", "ODER"):
                sequence.append({"type": "ast_operator", "operator": op_display})
            continue

        group_id_raw = cond.get("Gruppe")
        normalized_gid = _normalize_group_identifier(group_id_raw)
        if normalized_gid is None:
            normalized_gid = f"__synthetic__{synthetic_group_counter}"
            synthetic_group_counter += 1

        meta = group_meta.setdefault(
            normalized_gid,
            {
                "DisplayId": group_id_raw,
                "GroupNegated": False,
                "ParentGroup": _normalize_group_identifier(cond.get("ParentGroup")),
                "GroupOperator": _normalize_operator_label(cond.get("GruppenOperator")),
                "SortIndex": cond.get("GruppeSortIndex", group_id_raw),
            },
        )
        if cond.get("GroupNegated"):
            meta["GroupNegated"] = True
        if meta.get("ParentGroup") is None:
            meta["ParentGroup"] = _normalize_group_identifier(cond.get("ParentGroup"))
        if not meta.get("GroupOperator"):
            meta["GroupOperator"] = _normalize_operator_label(cond.get("GruppenOperator"))
        if meta.get("SortIndex") is None:
            meta["SortIndex"] = cond.get("GruppeSortIndex", group_id_raw)
        if meta.get("DisplayId") is None:
            meta["DisplayId"] = group_id_raw

        if current_group is None or current_group.normalized_id != normalized_gid:
            if current_group is not None:
                groups.append(current_group)
                group_lookup[current_group.normalized_id] = current_group
            op_between = inter_group_operators_map.pop(normalized_gid, None)
            if op_between:
                inter_group_ops_out.append(op_between)
            meta_for_group = group_meta[normalized_gid]
            current_group = PreparedConditionGroup(
                id=meta_for_group.get("DisplayId"),
                normalized_id=normalized_gid,
                sort_index=meta_for_group.get("SortIndex"),
                parent=meta_for_group.get("ParentGroup"),
                group_operator=meta_for_group.get("GroupOperator", ""),
                negated=bool(meta_for_group.get("GroupNegated")),
            )
            sequence.append({"type": "group", "group_id": normalized_gid})
        else:
            meta_for_group = group_meta[normalized_gid]
            current_group.negated = bool(meta_for_group.get("GroupNegated"))
            current_group.parent = meta_for_group.get("ParentGroup")
            current_group.group_operator = meta_for_group.get("GroupOperator", "")
            if meta_for_group.get("SortIndex") is not None:
                current_group.sort_index = meta_for_group.get("SortIndex")

        current_group.conditions.append(cast(MutableMapping[str, Any], cond))
        if len(current_group.conditions) > 1:
            prev_cond = current_group.conditions[-2]
            link_op = _normalize_operator_label(prev_cond.get("Operator"), default="UND")
            if link_op in ("UND", "ODER"):
                current_group.intra_ops.append(link_op)

    if current_group is not None:
        groups.append(current_group)
        group_lookup[current_group.normalized_id] = current_group

    group_children_map: Dict[Any, List[Dict[str, Any]]] = {}
    for parent_id, child_id, op_val, bed_id in ast_links:
        entry = {
            "child": child_id,
            "operator": op_val if op_val in ("UND", "ODER") else _normalize_operator_label(op_val, default="ODER"),
            "bed_id": bed_id or 0,
        }
        group_children_map.setdefault(parent_id, []).append(entry)

    for entries in group_children_map.values():
        entries.sort(key=lambda item: item.get("bed_id", 0))

    return PreparedPauschaleStructure(
        groups=groups,
        inter_group_ops=inter_group_ops_out,
        group_children=group_children_map,
        sequence=sequence,
        has_real_conditions=has_real_conditions,
        group_lookup=group_lookup,
    )


def _get_prepared_structure(
    pauschale_code: str,
    all_conditions: Sequence[Mapping[str, Any]],
    prepared_index: Optional[Dict[str, PreparedPauschaleStructure]] = None,
) -> PreparedPauschaleStructure:
    """Return the prepared structure for ``pauschale_code`` (compute on demand)."""

    key = str(pauschale_code)
    if prepared_index and key in prepared_index:
        return prepared_index[key]

    relevant = [
        cond for cond in all_conditions if str(cond.get("Pauschale")) == key
    ]
    if not relevant:
        return PreparedPauschaleStructure()
    return _prepare_single_pauschale_structure(key, relevant)


def pauschale_requires_icd(
    pauschale_code: str,
    structure: Optional[PreparedPauschaleStructure],
    pauschalen_dict: Optional[Dict[str, Dict[str, Any]]] | None = None,
) -> bool:
    """Return True if the Pauschale has ICD-triggered requirements."""
    if structure:
        for group in structure.groups:
            for cond in group.conditions:
                cond_type = str(cond.get('Bedingungstyp', '')).upper()
                if cond_type in ICD_CONDITION_TYPES:
                    return True

    if pauschalen_dict:
        details = pauschalen_dict.get(pauschale_code) or {}
        prueflogik_expr = details.get('Pr\u00fcflogik')
        if isinstance(prueflogik_expr, str):
            lowered = prueflogik_expr.lower()
            if any(token in lowered for token in _PRUEFLOGIK_ICD_TOKENS):
                return True
    return False


@with_table_content_cache
def count_matching_lkn_codes(
    context: Mapping[str, Any],
    structure: Optional[PreparedPauschaleStructure],
    tabellen_dict_by_table: Dict[str, List[Dict]],
) -> int:
    """Return how many distinct context LKN codes satisfy LKN conditions for the Pauschale."""
    provided_lkns = {str(lkn).upper() for lkn in context.get('LKN', []) if lkn}
    if not provided_lkns or not structure:
        return 0
    matches: set[str] = set()
    for group in structure.groups:
        for cond in group.conditions:
            cond_type = str(cond.get('Bedingungstyp', '')).upper()
            cond_cache: Dict[str, Any] = cond.setdefault('__parsed_cache__', {})
            if cond_type in LKN_LIST_CONDITION_TYPES:
                values = cond_cache.get('lkn_required_set')
                if values is None:
                    values = frozenset(
                        item.strip().upper() for item in str(cond.get('Werte', '')).split(',') if item.strip()
                    )
                    cond_cache['lkn_required_set'] = values
                matches.update(provided_lkns.intersection(values))
            elif cond_type in LKN_TABLE_CONDITION_TYPES:
                table_ref = str(cond.get('Werte', '')).strip()
                if not table_ref:
                    continue
                cache_key_codes = 'table_codes::service_catalog'
                table_codes = cond_cache.get(cache_key_codes)
                if table_codes is None:
                    entries = get_table_content(table_ref, 'service_catalog', tabellen_dict_by_table)
                    table_codes = frozenset(
                        str(entry.get('Code', '')).upper() for entry in entries if entry.get('Code')
                    )
                    cond_cache[cache_key_codes] = table_codes
                matches.update(provided_lkns.intersection(table_codes))
    return len(matches)


def is_pauschale_code_ge_c90(code: str | None) -> bool:
    """Return True if the Pauschale code is lexicographically >= C90."""
    if not code:
        return False
    normalized = str(code).upper()
    match = re.match(r"([A-Z])(\d+)", normalized)
    if not match:
        return False
    letter, digits_str = match.groups()
    try:
        numeric = int(digits_str)
    except ValueError:
        return False
    if letter > 'C':
        return True
    if letter < 'C':
        return False
    return numeric >= 90


def _parentheses_balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == '(': depth += 1
        elif ch == ')':
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _strip_surrounding_parentheses(text: str) -> str:
    result = text.strip()
    while result.startswith('(') and result.endswith(')'):
        inner = result[1:-1].strip()
        if not inner:
            break
        if _parentheses_balanced(inner):
            result = inner
        else:
            break
    return result


def _normalize_logical_operators(expr: str) -> str:
    expr = re.sub(r'\boder\b', 'or', expr, flags=re.IGNORECASE)
    expr = re.sub(r'\bund\b', 'and', expr, flags=re.IGNORECASE)
    expr = re.sub(r'\bnicht\b', 'not', expr, flags=re.IGNORECASE)
    expr = re.sub(r'(?<![<>!=])=(?!=)', '==', expr)
    return expr


def _parse_comparison(expr: str) -> tuple[str, str]:
    normalized = expr.strip()
    normalized = normalized.replace('> =', '>=').replace('< =', '<=').replace('! =', '!=').replace('= =', '=')
    for operator in ('>=', '<=', '!=', '>', '<', '==', '='):
        if operator in normalized:
            left, right = normalized.split(operator, 1)
            right = right.strip()
            if right.startswith("'") and right.endswith("'"):
                right = right[1:-1]
            if operator == '==':
                operator = '='
            return operator, right
    raise ValueError(f"Cannot parse comparison '{expr}'.")


def _evaluate_simple_condition(
    condition_text: str,
    normalized_context: NormalizedContext,
    tabellen_dict_by_table: Dict[str, List[Dict]],
) -> bool:
    text_lower = condition_text.strip().lower()
    if text_lower.startswith('anzahl'):
        operator, value = _parse_comparison(condition_text[len('Anzahl'):])
        cond = {'Bedingungstyp': 'ANZAHL', 'Vergleichsoperator': operator, 'Werte': value}
        return bool(
            check_single_condition(
                cond,
                normalized_context.raw,
                tabellen_dict_by_table,
                normalized_context,
            )
        )
    if text_lower.startswith('seitigkeit'):
        operator, value = _parse_comparison(condition_text[len('Seitigkeit'):])
        cond = {'Bedingungstyp': 'SEITIGKEIT', 'Vergleichsoperator': operator, 'Werte': value}
        return bool(
            check_single_condition(
                cond,
                normalized_context.raw,
                tabellen_dict_by_table,
                normalized_context,
            )
        )
    if text_lower.startswith('alter in jahren bei eintritt'):
        operator, value = _parse_comparison(condition_text[len('Alter in Jahren bei Eintritt'):])
        cond = {'Bedingungstyp': 'ALTER IN JAHREN BEI EINTRITT', 'Vergleichsoperator': operator, 'Werte': value}
        return bool(
            check_single_condition(
                cond,
                normalized_context.raw,
                tabellen_dict_by_table,
                normalized_context,
            )
        )
    if text_lower.startswith('geschlecht in liste'):
        return bool(
            _evaluate_condition_text(
                condition_text,
                normalized_context,
                tabellen_dict_by_table,
            )
        )
    raise ValueError(f"Unsupported WHERE condition fragment '{condition_text}'.")


def _evaluate_where_clause(
    where_text: str,
    normalized_context: NormalizedContext,
    tabellen_dict_by_table: Dict[str, List[Dict]],
) -> bool:
    clause = _strip_surrounding_parentheses(where_text.strip())
    if not clause:
        return True

    simple_results: List[bool] = []

    def _replace(match: re.Match) -> str:
        idx = len(simple_results)
        fragment = match.group(0)
        simple_results.append(
            _evaluate_simple_condition(
                fragment,
                normalized_context,
                tabellen_dict_by_table,
            )
        )
        return f'__WHERE{idx}__'

    simple_pattern = re.compile(
        r"(Anzahl\s*[<>!=]=?\s*-?\d+|Seitigkeit\s*=\s*'?[A-Za-z]+'?|Alter in Jahren bei Eintritt\s*[<>!=]=?\s*-?\d+|Geschlecht in Liste\s*\([^()]+\))",
        flags=re.IGNORECASE,
    )
    token_expr = simple_pattern.sub(
        _replace,
        clause.replace('> =', '>=').replace('< =', '<=').replace('! =', '!=').replace('= =', '='),
    )

    if not simple_results:
        return True

    expr_python = _normalize_logical_operators(token_expr)
    env = {f'__WHERE{i}__': value for i, value in enumerate(simple_results)}
    return bool(eval(expr_python, {'__builtins__': None}, env))


def _evaluate_condition_text(
    condition_text: str,
    normalized_context: NormalizedContext,
    tabellen_dict_by_table: Dict[str, List[Dict]],
) -> bool:
    text = _strip_surrounding_parentheses(condition_text.strip())
    where_match = re.search(r'\swhere\s', text, flags=re.IGNORECASE)
    if where_match:
        base_text = text[:where_match.start()].strip()
        where_clause = text[where_match.end():].strip()
        return _evaluate_condition_text(
            base_text,
            normalized_context,
            tabellen_dict_by_table,
        ) and _evaluate_where_clause(
            where_clause,
            normalized_context,
            tabellen_dict_by_table,
        )

    if '(' not in text or not text.endswith(')'):
        raise ValueError(f"Unexpected condition fragment '{condition_text}'.")

    prefix, values = text.split('(', 1)
    prefix_lower = prefix.strip().lower()
    values_str = values[:-1].strip()

    type_map = {
        'hauptdiagnose in tabelle': 'HAUPTDIAGNOSE IN TABELLE',
        'hauptdiagnose in liste': 'HAUPTDIAGNOSE IN LISTE',
        'icd in tabelle': 'ICD IN TABELLE',
        'icd in liste': 'ICD IN LISTE',
        'leistungspositionen in tabelle': 'LEISTUNGSPOSITIONEN IN TABELLE',
        'leistungspositionen in liste': 'LEISTUNGSPOSITIONEN IN LISTE',
        'medikamente in liste': 'MEDIKAMENTE IN LISTE',
        'tarifpositionen in tabelle': 'TARIFPOSITIONEN IN TABELLE',
        'geschlecht in liste': 'GESCHLECHT IN LISTE',
    }

    cond_type = type_map.get(prefix_lower)
    if not cond_type:
        raise ValueError(f"Unsupported condition type '{prefix}'.")

    cond = {'Bedingungstyp': cond_type, 'Werte': values_str}
    return bool(
        check_single_condition(
            cond,
            normalized_context.raw,
            tabellen_dict_by_table,
            normalized_context,
        )
    )


def _evaluate_prueflogik_expression(
    prueflogik_expr: str,
    normalized_context: NormalizedContext,
    tabellen_dict_by_table: Dict[str, List[Dict]],
    pauschale_code: str,
    debug: bool = False,
) -> bool:
    values: List[bool] = []

    def _replace(match: re.Match) -> str:
        idx = len(values)
        fragment = match.group(0)
        fragment_clean = fragment.strip()
        fragment_lower = fragment_clean.lower()

        if (
            fragment_lower.startswith('anzahl')
            or fragment_lower.startswith('seitigkeit')
            or fragment_lower.startswith('alter in jahren bei eintritt')
            or fragment_lower.startswith('geschlecht in liste')
        ):
            result = _evaluate_simple_condition(
                fragment_clean,
                normalized_context,
                tabellen_dict_by_table,
            )
        elif fragment_lower.replace(' ', '') == '1=1':
            result = True
        else:
            result = _evaluate_condition_text(
                fragment_clean,
                normalized_context,
                tabellen_dict_by_table,
            )

        values.append(bool(result))
        return f'__COND{idx}__'

    token_expr = CONDITION_PATTERN.sub(_replace, prueflogik_expr)
    if not values:
        raise ValueError("Keine Bedingungen aus der Prüflogik extrahiert.")

    # Replace logical operators with standard tokens for the parser
    expr_normalized = _normalize_logical_operators(token_expr)
    
    # Create a mapping for the evaluator
    context_map = {f'__COND{i}__': val for i, val in enumerate(values)}
    
    return _evaluate_boolean_expression_safe(expr_normalized, context_map)


def _evaluate_boolean_expression_safe(expression: str, context: Dict[str, bool]) -> bool:
    """
    Safely evaluates a boolean expression string with AND, OR, NOT, parens, and variable names.
    Uses a shunting-yard algorithm or recursive descent. Here: Shunting-yard to RPN, then evaluate.
    """
    # 1. Tokenize
    # Tokens: (, ), and, or, not, variable_names
    tokens = _tokenize_boolean_expression(expression)
    
    # 2. Shunting-yard to RPN
    rpn_queue = _shunting_yard(tokens)
    
    # 3. Evaluate RPN
    return _evaluate_rpn(rpn_queue, context)


def _tokenize_boolean_expression(expression: str) -> List[str]:
    """Simple tokenizer for boolean expressions."""
    # Add spaces around parens to make splitting easier
    expr = expression.replace('(', ' ( ').replace(')', ' ) ')
    # Split by whitespace
    raw_tokens = expr.split()
    return [t.lower() if t.lower() in ('and', 'or', 'not') else t for t in raw_tokens]


def _shunting_yard(tokens: List[str]) -> List[str]:
    """Convert infix boolean tokens to Reverse Polish Notation (RPN)."""
    output_queue = []
    operator_stack = []
    precedence = {'not': 3, 'and': 2, 'or': 1}
    
    for token in tokens:
        if token == '(':
            operator_stack.append(token)
        elif token == ')':
            while operator_stack and operator_stack[-1] != '(':
                output_queue.append(operator_stack.pop())
            if operator_stack and operator_stack[-1] == '(':
                operator_stack.pop() # Pop the '('
        elif token in precedence:
            while (operator_stack and operator_stack[-1] != '(' and
                   precedence.get(operator_stack[-1], 0) >= precedence[token]):
                output_queue.append(operator_stack.pop())
            operator_stack.append(token)
        else:
            # Operand (variable name)
            output_queue.append(token)
    
    while operator_stack:
        output_queue.append(operator_stack.pop())
        
    return output_queue


def _evaluate_rpn(rpn_queue: List[str], context: Dict[str, bool]) -> bool:
    """Evaluate RPN queue."""
    stack = []
    
    for token in rpn_queue:
        if token == 'and':
            val2 = stack.pop()
            val1 = stack.pop()
            stack.append(val1 and val2)
        elif token == 'or':
            val2 = stack.pop()
            val1 = stack.pop()
            stack.append(val1 or val2)
        elif token == 'not':
            val = stack.pop()
            stack.append(not val)
        else:
            # Operand
            # If it's a literal True/False (case insensitive)
            if token.lower() == 'true':
                stack.append(True)
            elif token.lower() == 'false':
                stack.append(False)
            else:
                # Look up in context
                # If missing, default to False (or raise error? Defaulting to False is safer for now)
                stack.append(context.get(token, False))
                
    if not stack:
        return False # Should not happen for valid expressions
    return stack[0]


def _format_prueflogik_for_display(prueflogik_expr: str, lang: str = "de") -> str:
    """Return a pretty-printed version of the Prüflogik expression."""
    expr = (prueflogik_expr or "").strip()
    if not expr:
        return ""

    token_map: Dict[str, str] = {}

    def _replace(match: re.Match) -> str:
        token = f"__COND{len(token_map)}__"
        token_map[token] = match.group(0).strip()
        return token

    tokenized_expr = CONDITION_PATTERN.sub(_replace, expr)
    python_expr = _normalize_logical_operators(tokenized_expr)

    try:
        parsed = ast.parse(python_expr, mode="eval")
    except SyntaxError:
        return expr
    except Exception as exc:
        logger.debug("Format Prüflogik: AST parse failed (%s). Returning raw expression.", exc)
        return expr

    def _format_node(node: ast.AST, indent: int = 0) -> str:
        indent_str = " " * indent
        if isinstance(node, ast.BoolOp):
            op_label = translate('AND', lang) if isinstance(node.op, ast.And) else translate('OR', lang)
            parts: List[str] = []
            for idx, value in enumerate(node.values):
                if idx > 0:
                    parts.append(f"{indent_str}{op_label}")
                parts.append(_format_node(value, indent + 2))
            body = "\n".join(parts)
            return f"{indent_str}(\n{body}\n{indent_str})"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            not_label = translate('NOT', lang)
            inner = _format_node(node.operand, indent + 2)
            return f"{indent_str}{not_label} (\n{inner}\n{indent_str})"
        if isinstance(node, ast.Name):
            cond_text = token_map.get(node.id, node.id)
            return f"{indent_str}{cond_text.strip()}"
        if isinstance(node, ast.Constant):
            return f"{indent_str}{str(node.value)}"
        return f"{indent_str}{ast.dump(node)}"

    try:
        formatted = _format_node(parsed.body, 0)
    except Exception as exc:
        logger.debug("Format Prüflogik: Rendering failed (%s). Returning raw expression.", exc)
        return expr

    return formatted.strip()


def _normalize_logic_text(text: str) -> str:
    normalized = re.sub(r'\s+', ' ', text.upper())
    normalized = normalized.replace(' ,', ',').replace(', ', ', ')
    return normalized.strip()


def _strip_outer_parentheses(text: str) -> str:
    result = text.strip()
    while result.startswith("(") and result.endswith(")"):
        candidate = result[1:-1].strip()
        if not candidate:
            break
        paren = 0
        balanced = True
        for ch in candidate:
            if ch == "(":
                paren += 1
            elif ch == ")":
                paren -= 1
                if paren < 0:
                    balanced = False
                    break
        if not balanced or paren != 0:
            break
        result = candidate
    return result


def _split_top_level(expr: str, delimiter: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    start = 0
    i = 0
    length = len(expr)
    while i < length:
        ch = expr[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif depth == 0 and expr.startswith(delimiter, i):
            parts.append(expr[start:i].strip())
            i += len(delimiter)
            start = i
            continue
        i += 1
    tail = expr[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _build_condition_signature_map(
    pauschale_code: str,
    pauschale_bedingungen_data: List[Dict[str, Any]]
) -> Dict[str, Set[str]]:
    signature_map: Dict[str, Set[str]] = defaultdict(set)
    for cond in pauschale_bedingungen_data:
        if cond.get("Pauschale") != pauschale_code:
            continue
        cond_type = str(cond.get("Bedingungstyp", "")).upper()
        if cond_type == "AST VERBINDUNGSOPERATOR":
            continue
        values_raw = str(cond.get("Werte", "")).upper()
        values_normalized = ", ".join(part.strip() for part in values_raw.split(",")) if values_raw else ""
        signature = _normalize_logic_text(f"{cond_type} ({values_normalized})" if values_normalized else cond_type)
        gid = cond.get("Gruppe")
        if gid is not None:
            signature_map[signature].add(str(gid))
    return signature_map


def _extract_group_logic_terms_from_expression(
    pauschale_code: str,
    prueflogik_expr: Optional[str],
    pauschale_bedingungen_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not prueflogik_expr:
        return []
    normalized_expr = _normalize_logic_text(prueflogik_expr)
    if not normalized_expr:
        return []
    top_terms = _split_top_level(normalized_expr, " ODER ")
    if not top_terms:
        return []
    signature_map = _build_condition_signature_map(pauschale_code, pauschale_bedingungen_data)
    logic_terms: List[Dict[str, Any]] = []

    for idx, raw_term in enumerate(top_terms):
        term_body = _strip_outer_parentheses(raw_term)
        factors = _split_top_level(term_body, " UND ")
        if not factors:
            continue
        group_order: List[tuple[str, bool]] = []
        group_states: Dict[str, bool] = {}
        inconsistent = False
        for raw_factor in factors:
            factor_body = _strip_outer_parentheses(raw_factor)
            negated = False
            if factor_body.startswith("NICHT "):
                negated = True
                factor_body = factor_body[len("NICHT "):].strip()
                factor_body = _strip_outer_parentheses(factor_body)
            signature = _normalize_logic_text(factor_body)
            matched_groups = signature_map.get(signature)
            if not matched_groups:
                continue
            desired_state = not negated
            for gid in matched_groups:
                existing_state = group_states.get(gid)
                if existing_state is None:
                    group_states[gid] = desired_state
                    group_order.append((gid, desired_state))
                elif existing_state != desired_state:
                    inconsistent = True
                    break
            if inconsistent:
                break
        if inconsistent or not group_order:
            continue
        term_entry = {
            "operator": "ODER" if idx > 0 else "",
            "groups": [
                {"group_id": gid, "negated": not state}
                for gid, state in group_order
            ],
        }
        logic_terms.append(term_entry)

    return logic_terms


def _extract_group_logic_terms_from_ast(
    pauschale_code: str,
    pauschale_bedingungen_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    ast_entries = [
        cond for cond in pauschale_bedingungen_data
        if cond.get("Pauschale") == pauschale_code
        and str(cond.get("Bedingungstyp", "")).upper() == "AST VERBINDUNGSOPERATOR"
    ]
    if not ast_entries:
        group_ids = sorted({
            str(cond.get("Gruppe"))
            for cond in pauschale_bedingungen_data
            if cond.get("Pauschale") == pauschale_code and cond.get("Gruppe") is not None
        })
        if not group_ids:
            return []
        return [
            {"operator": "ODER" if idx > 0 else "", "groups": [{"group_id": gid, "negated": False}]}
            for idx, gid in enumerate(group_ids)
        ]

    def _normalize_group_id(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            return str(int(str(value).strip()))
        except Exception:
            s = str(value).strip()
            return s if s else None

    group_ids = {
        str(cond.get("Gruppe"))
        for cond in pauschale_bedingungen_data
        if cond.get("Pauschale") == pauschale_code and cond.get("Gruppe") is not None
    }
    children_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    parent_nodes: Set[str] = set()
    child_nodes: Set[str] = set()

    for entry in ast_entries:
        parent_id = _normalize_group_id(entry.get("Gruppe"))
        child_id = _normalize_group_id(entry.get("Spezialbedingung") or entry.get("Werte"))
        operator = str(entry.get("Operator", "ODER")).upper()
        if parent_id is None or child_id is None:
            continue
        children_map[parent_id].append({
            "child": child_id,
            "operator": operator,
        })
        parent_nodes.add(parent_id)
        child_nodes.add(child_id)

    for value in children_map.values():
        value.sort(key=lambda item: item.get("child") or "")

    def _combine_and(left: List[List[tuple[str, bool]]], right: List[List[tuple[str, bool]]]) -> List[List[tuple[str, bool]]]:
        if not left:
            left = [[]]
        if not right:
            right = [[]]
        combined: List[List[tuple[str, bool]]] = []
        for l in left:
            for r in right:
                combined.append(l + r)
        return combined

    def _combine_or(left: List[List[tuple[str, bool]]], right: List[List[tuple[str, bool]]]) -> List[List[tuple[str, bool]]]:
        return (left or []) + (right or [])

    cache: Dict[str, List[List[tuple[str, bool]]]] = {}

    def _combos_for_node(node_id: str) -> List[List[tuple[str, bool]]]:
        if node_id in cache:
            return cache[node_id]
        combos: List[List[tuple[str, bool]]] = []
        if node_id in group_ids:
            combos = [[(node_id, True)]]
        child_entries = children_map.get(node_id, [])
        for child_entry in child_entries:
            child_id = child_entry.get("child")
            if not child_id:
                continue
            child_combos = _combos_for_node(child_id)
            op = child_entry.get("operator", "ODER").upper()
            if op == "UND":
                combos = _combine_and(combos, child_combos)
            else:
                combos = _combine_or(combos, child_combos)
        cache[node_id] = combos
        return combos

    root_nodes = sorted(parent_nodes - child_nodes)
    if not root_nodes:
        root_nodes = sorted(parent_nodes)

    all_combos: List[List[tuple[str, bool]]] = []
    for idx, root in enumerate(root_nodes):
        root_combos = _combos_for_node(root)
        if idx == 0:
            all_combos = root_combos
        else:
            all_combos = _combine_and(all_combos, root_combos)

    if not all_combos:
        all_combos = [[(gid, True)] for gid in sorted(group_ids)]

    def _normalize_combo(combo: List[tuple[str, bool]]) -> Optional[List[tuple[str, bool]]]:
        seen: Dict[str, bool] = {}
        ordered: List[tuple[str, bool]] = []
        for gid, state in combo:
            if gid in seen:
                if seen[gid] != state:
                    return None
                continue
            seen[gid] = state
            ordered.append((gid, state))
        return ordered

    normalized_combos: List[List[tuple[str, bool]]] = []
    seen_signatures: Set[Tuple[Tuple[str, bool], ...]] = set()
    for combo in all_combos:
        normalized = _normalize_combo(combo)
        if not normalized:
            continue
        signature: Tuple[Tuple[str, bool], ...] = tuple(normalized)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        normalized_combos.append(list(normalized))

    normalized_combos.sort(key=lambda combo: [c[0] for c in combo])

    terms: List[Dict[str, Any]] = []
    for idx, combo in enumerate(normalized_combos):
        terms.append({
            "operator": "ODER" if idx > 0 else "",
            "groups": [
                {"group_id": gid, "negated": not state}
                for gid, state in combo
            ],
        })
    return terms


def _extract_group_logic_terms(
    pauschale_code: str,
    prueflogik_expr: Optional[str],
    pauschale_bedingungen_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    expr_terms = _extract_group_logic_terms_from_expression(pauschale_code, prueflogik_expr, pauschale_bedingungen_data)
    if expr_terms:
        return expr_terms
    return _extract_group_logic_terms_from_ast(pauschale_code, pauschale_bedingungen_data)


# === FUNKTION ZUR PRÜFUNG EINER EINZELNEN BEDINGUNG ===
def check_single_condition(
    condition: MutableMapping[str, Any],
    context: Mapping[str, Any],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    normalized_context: Optional[NormalizedContext] = None,
) -> bool:
    """Prüft eine einzelne Bedingungszeile und gibt True/False zurück."""
    normalized_context = normalized_context or build_normalized_context(context)

    check_icd_conditions_at_all = normalized_context.use_icd
    pauschale_code_for_debug = condition.get('Pauschale', 'N/A_PAUSCHALE') # Für besseres Debugging
    gruppe_for_debug = condition.get('Gruppe', 'N/A_GRUPPE') # Für besseres Debugging

    BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'; BED_FELD_KEY = 'Feld'
    BED_MIN_KEY = 'MinWert'; BED_MAX_KEY = 'MaxWert'
    bedingungstyp = condition.get(BED_TYP_KEY, "").upper()
    werte_str = condition.get(BED_WERTE_KEY, "") # Dies ist der Wert aus der Regel-DB
    feld_ref = condition.get(BED_FELD_KEY); min_val_regel = condition.get(BED_MIN_KEY) # Umbenannt für Klarheit
    max_val_regel = condition.get(BED_MAX_KEY); wert_regel_explizit = condition.get(BED_WERTE_KEY) # Umbenannt für Klarheit

    condition_cache: Dict[str, Any] = condition.setdefault('__parsed_cache__', {})

    # Kontextwerte holen
    provided_icds_upper = normalized_context.icd_codes
    provided_medications_upper = normalized_context.medication_codes
    provided_lkns_upper = normalized_context.lkn_codes
    provided_alter = normalized_context.alter
    provided_geschlecht_str = normalized_context.geschlecht_lower
    provided_anzahl = normalized_context.anzahl
    provided_seitigkeit_str = normalized_context.seitigkeit_lower

    # print(f"--- DEBUG check_single --- P: {pauschale_code_for_debug} G: {gruppe_for_debug} Typ: {bedingungstyp}, Regel-Werte: '{werte_str}', Kontext: {context.get('Seitigkeit', 'N/A')}/{context.get('Anzahl', 'N/A')}")

    try:
        if bedingungstyp == "ICD": # ICD IN LISTE
            if not check_icd_conditions_at_all:
                return True
            required_icds: Optional[frozenset[str]] = condition_cache.get('icd_required_set')
            if required_icds is None:
                required_icds = frozenset(
                    w.strip().upper() for w in str(werte_str).split(',') if w.strip()
                )
                condition_cache['icd_required_set'] = required_icds
            if not required_icds:  # Leere Regel-Liste ist immer erfüllt
                return True
            return any(req_icd in provided_icds_upper for req_icd in required_icds)

        elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE": # ICD IN TABELLE
            if not check_icd_conditions_at_all:
                return True
            table_ref = str(werte_str)
            cached_icd_codes: Optional[frozenset[str]] = condition_cache.get('icd_table_codes')
            if cached_icd_codes is None:
                icd_codes_in_rule_table = {
                    entry['Code'].upper()
                    for entry in get_table_content(table_ref, "icd", tabellen_dict_by_table)
                    if entry.get('Code')
                }
                extra_codes = DIAGNOSIS_TABLE_EXTRA_CODES.get(str(table_ref).upper())
                if extra_codes:
                    icd_codes_in_rule_table.update(code.upper() for code in extra_codes)
                cached_icd_codes = frozenset(icd_codes_in_rule_table)
                condition_cache['icd_table_codes'] = cached_icd_codes
            if not cached_icd_codes:  # Wenn Tabelle leer oder nicht gefunden
                return False if provided_icds_upper else True  # Nur erfüllt, wenn auch keine ICDs im Kontext sind
            return any(provided_icd in cached_icd_codes for provided_icd in provided_icds_upper)

        elif bedingungstyp in ("GTIN", "MEDIKAMENTE IN LISTE"):
            required_meds: Optional[frozenset[str]] = condition_cache.get('medication_required_set')
            if required_meds is None:
                required_meds = frozenset(
                    w.strip().upper() for w in str(werte_str).split(',') if w.strip()
                )
                condition_cache['medication_required_set'] = required_meds
            if not required_meds:
                return True
            return any(req_med in provided_medications_upper for req_med in required_meds)

        elif bedingungstyp == "LKN" or bedingungstyp == "LEISTUNGSPOSITIONEN IN LISTE":
            required_lkns: Optional[frozenset[str]] = condition_cache.get('lkn_required_set')
            if required_lkns is None:
                required_lkns = frozenset(
                    w.strip().upper() for w in str(werte_str).split(',') if w.strip()
                )
                condition_cache['lkn_required_set'] = required_lkns
            if not required_lkns:
                return True
            return any(req_lkn in provided_lkns_upper for req_lkn in required_lkns)

        elif bedingungstyp == "GESCHLECHT IN LISTE": # Z.B. Werte: "Männlich,Weiblich"
            if werte_str: # Nur prüfen, wenn Regel einen Wert hat
                gender_values: Optional[frozenset[str]] = condition_cache.get('gender_required_set')
                if gender_values is None:
                    gender_values = frozenset(
                        g.strip().lower() for g in str(werte_str).split(',') if g.strip()
                    )
                    condition_cache['gender_required_set'] = gender_values
                return provided_geschlecht_str in gender_values
            return True # Wenn Regel keinen Wert hat, ist es für jedes Geschlecht ok

        elif bedingungstyp == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp == "TARIFPOSITIONEN IN TABELLE" or bedingungstyp == "LKN IN TABELLE":
            table_ref = werte_str
            if not table_ref:
                return False

            provided_codes: Iterable[str]
            if bedingungstyp == "TARIFPOSITIONEN IN TABELLE":
                table_type = "tariff"
                provided_codes = provided_medications_upper
            else:
                table_type = "service_catalog"
                provided_codes = provided_lkns_upper

            # Optimization: Use pre-computed sets if available
            # tabellen_sets_by_table is expected to be passed in tabellen_dict_by_table under a special key or separate arg
            # For backward compatibility, we check if tabellen_dict_by_table has a special attribute or key
            # But since we can't easily change the signature everywhere yet, we'll look for a special key in the dict
            # OR we rely on the fact that we will update the caller to pass sets.
            
            # Actually, let's try to use the cache key first.
            cache_key_codes = f"table_codes::{table_type}"
            table_codes: Optional[frozenset[str]] = condition_cache.get(cache_key_codes)
            
            if table_codes is None:
                # Try to find pre-computed set in tabellen_dict_by_table (hacky but avoids signature change for now)
                # We will pass a dict that might contain sets as values for keys like "table_name::set"
                # But cleaner is to just build it if not cached.
                
                # Check if we have a pre-computed set in a global or passed structure?
                # The plan said "Update call to determine_applicable_pauschale to pass prepared_structures and tabellen_sets_by_table".
                # But check_single_condition signature is:
                # (condition, context, tabellen_dict_by_table, normalized_context)
                
                # We can check if tabellen_dict_by_table contains the set directly? 
                # No, tabellen_dict_by_table is Dict[str, List[Dict]].
                
                # Let's assume for now we still build it once per condition instance via cache.
                # The bottleneck was likely that we built it every time if cache wasn't persisting across calls?
                # condition_cache is stored IN the condition dict. So it persists as long as the condition dict persists.
                # The issue might be that we are doing this for MANY conditions.
                
                # If we can look up the set from a central store, it's faster.
                # Let's try to access a 'sets' attribute if it exists on the dict (monkey patching) or just optimize the build.
                
                table_entries = get_table_content(table_ref, table_type, tabellen_dict_by_table)
                
                # Optimization: If table_entries is empty, we can return empty set immediately
                if not table_entries:
                    table_codes = frozenset()
                else:
                    # Faster set construction
                    codes = {
                        str(entry.get('Code', '')).upper()
                        for entry in table_entries
                        if entry.get('Code')
                    }
                    table_codes = frozenset(codes)
                
                condition_cache[cache_key_codes] = table_codes
                
            if not table_codes:
                return False
            
            # Fast intersection check
            # return not table_codes.isdisjoint(provided_codes) # This is faster than any(...)
            # But provided_codes might be a list or set. normalized_context.lkn_codes is a set.
            if not isinstance(provided_codes, (set, frozenset)):
                provided_codes = frozenset(provided_codes)
            return not table_codes.isdisjoint(provided_codes)

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
                logger.warning(
                    "WARNUNG (check_single PATIENTENBEDINGUNG): Unbekanntes Feld '%s'.",
                    feld_ref,
                )
                return True # Oder False, je nach gewünschtem Verhalten

        elif bedingungstyp == "ALTER IN JAHREN BEI EINTRITT":
            alter_eintritt = normalized_context.alter_bei_eintritt
            if alter_eintritt is None:
                return False
            try:
                alter_val = int(alter_eintritt)
                regel_wert = int(werte_str)
                vergleichsoperator = condition.get("Vergleichsoperator")

                if vergleichsoperator == ">=":
                    return alter_val >= regel_wert
                elif vergleichsoperator == "<=":
                    return alter_val <= regel_wert
                elif vergleichsoperator == ">":
                    return alter_val > regel_wert
                elif vergleichsoperator == "<":
                    return alter_val < regel_wert
                elif vergleichsoperator == "=":
                    return alter_val == regel_wert
                elif vergleichsoperator == "!=":
                    return alter_val != regel_wert
                else:
                    logger.warning(
                        "WARNUNG (check_single ALTER BEI EINTRITT): Unbekannter Vergleichsoperator '%s'.",
                        vergleichsoperator,
                    )
                    return False
            except (ValueError, TypeError) as e_alter:
                logger.error(
                    "FEHLER (check_single ALTER BEI EINTRITT) Konvertierung: %s. Regelwert: '%s', Kontextwert: '%s'",
                    e_alter,
                    werte_str,
                    alter_eintritt,
                )
                return False

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
                    logger.warning(
                        "WARNUNG (check_single ANZAHL): Unbekannter Vergleichsoperator '%s'.",
                        vergleichsoperator,
                    )
                    return False
            except (ValueError, TypeError) as e_anzahl:
                logger.error(
                    "FEHLER (check_single ANZAHL) Konvertierung: %s. Regelwert: '%s', Kontextwert: '%s'",
                    e_anzahl,
                    werte_str,
                    provided_anzahl,
                )
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
                logger.warning(
                    "WARNUNG (check_single SEITIGKEIT): Unbekannter Vergleichsoperator '%s'.",
                    vergleichsoperator,
                )
                return False
        else:
            logger.warning(
                "WARNUNG (check_single): Unbekannter Pauschalen-Bedingungstyp '%s'. Wird als False angenommen.",
                bedingungstyp,
            )
            return False
    except Exception as e:
        logger.error(
            "FEHLER (check_single) für P: %s G: %s Typ: %s, Werte: %s: %s",
            pauschale_code_for_debug,
            gruppe_for_debug,
            bedingungstyp,
            werte_str,
            e,
        )
        traceback.print_exc()
        return False

def get_beschreibung_fuer_lkn_im_backend(lkn_code: str, leistungskatalog_dict: Dict, lang: str = 'de') -> str:
    details = leistungskatalog_dict.get(str(lkn_code).upper())
    if not details:
        return lkn_code
    return get_lang_field(details, 'Beschreibung', lang) or lkn_code

# This function is no longer needed with the new orchestrator logic
# def get_group_operator_for_pauschale(
#     pauschale_code: str, bedingungen_data: List[Dict], default: str = DEFAULT_GROUP_OPERATOR
# ) -> str:
#     """Liefert den Gruppenoperator (UND/ODER) fuer eine Pauschale."""
#     for cond in bedingungen_data:
#         if cond.get("Pauschale") == pauschale_code and "GruppenOperator" in cond:
#             op = str(cond.get("GruppenOperator", "")).strip().upper()
#             if op in ("UND", "ODER"):
#                 return op
#
#     # Heuristik: Wenn keine explizite Angabe vorhanden ist, aber mehrere Gruppen
#     # existieren und in der ersten Gruppe mindestens eine Zeile mit "ODER"
#     # verknüpft ist, werten wir dies als globalen Gruppenoperator "ODER".
#     first_group_id = None
#     groups_seen: List[Any] = []
#     first_group_has_oder = False
#     for cond in bedingungen_data:
#         if cond.get("Pauschale") != pauschale_code:
#             continue
#         grp = cond.get("Gruppe")
#         if first_group_id is None:
#             first_group_id = grp
#         if grp not in groups_seen:
#             groups_seen.append(grp)
#         if grp == first_group_id:
#             if str(cond.get("Operator", "")).strip().upper() == "ODER":
#                 first_group_has_oder = True
#
#     if len(groups_seen) > 1 and first_group_has_oder:
#         return "ODER"
#
#     return default


@with_table_content_cache
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

    # Weitere Suche: durchlaufe alle Tabellen nach einem passenden ICD-Eintrag
    for entries in tabellen_dict_by_table.values():
        for entry in entries:
            if (
                entry.get('Tabelle_Typ') == 'icd' and
                entry.get('Code', '').upper() == icd_code.upper()
            ):
                return entry.get('Code_Text', icd_code)

    # print(f"DEBUG: ICD {icd_code} nicht gefunden.")
    return icd_code  # Wenn nirgends gefunden, Code selbst zurückgeben

def get_group_operator_for_pauschale(
    pauschale_code: str, bedingungen_data: List[Dict], default: str = DEFAULT_GROUP_OPERATOR
) -> str:
    """Liefert den Gruppenoperator (UND/ODER) fuer eine Pauschale."""
    for cond in bedingungen_data:
        if cond.get("Pauschale") == pauschale_code and "GruppenOperator" in cond:
            op = str(cond.get("GruppenOperator", "")).strip().upper()
            if op in ("UND", "ODER"):
                return op

    # Heuristik: Wenn keine explizite Angabe vorhanden ist, aber mehrere Gruppen
    # existieren und in der ersten Gruppe mindestens eine Zeile mit "ODER"
    # verknüpft ist, werten wir dies als globalen Gruppenoperator "ODER".
    first_group_id = None
    groups_seen: List[Any] = []
    first_group_has_oder = False
    for cond in bedingungen_data:
        if cond.get("Pauschale") != pauschale_code:
            continue
        grp = cond.get("Gruppe")
        if first_group_id is None:
            first_group_id = grp
        if grp not in groups_seen:
            groups_seen.append(grp)
        if grp == first_group_id:
            if str(cond.get("Operator", "")).strip().upper() == "ODER":
                first_group_has_oder = True

    if len(groups_seen) > 1 and first_group_has_oder:
        return "ODER"

    return default


def _evaluate_boolean_tokens(tokens: List[Any]) -> bool:
    """Evaluate a boolean expression represented as tokens.

    Parameters
    ----------
    tokens : list
        Sequence of tokens forming the expression. Each token is either
        ``True``/``False`` or one of the strings ``"AND"``, ``"OR"``,
        ``"("`` or ``")``.

    Returns
    -------
    bool
        Result of the evaluated boolean expression.

    Notes
    -----
    The implementation uses a simplified shunting-yard algorithm to
    transform the infix expression into Reverse Polish Notation before
    evaluation.

    Examples
    --------
    >>> _evaluate_boolean_tokens([True, "AND", False])
    False
    >>> _evaluate_boolean_tokens(["(", True, "OR", False, ")", "AND", True])
    True
    """
    precedence = {"AND": 2, "OR": 1}
    output: List[Any] = []
    op_stack: List[str] = []

    for tok in tokens:
        if isinstance(tok, bool):
            output.append(tok)
        elif tok in ("AND", "OR"):
            while op_stack and op_stack[-1] in ("AND", "OR") and precedence[op_stack[-1]] >= precedence[tok]:
                output.append(op_stack.pop())
            op_stack.append(tok)
        elif tok == "(":
            op_stack.append(tok)
        elif tok == ")":
            while op_stack and op_stack[-1] != "(":
                output.append(op_stack.pop())
            if not op_stack:
                raise ValueError("Unmatched closing parenthesis")
            op_stack.pop()
        else:
            raise ValueError(f"Unknown token {tok}")

    while op_stack:
        op = op_stack.pop()
        if op == "(":
            raise ValueError("Unmatched opening parenthesis")
        output.append(op)

    stack: List[bool] = []
    for tok_idx, tok_rpn in enumerate(output): # Using output which is the RPN list
        if isinstance(tok_rpn, bool):
            stack.append(tok_rpn)
        else: # Operator
            if len(stack) < 2:
                # More debug info
                logger.error(f"RPN Eval Error: Insufficient operands for operator '{tok_rpn}' at RPN index {tok_idx}.")
                logger.error(f"RPN token string: {output}")
                logger.error(f"Current eval stack: {stack}")
                raise ValueError(f"Insufficient operands for {tok_rpn}")
            
            # Explicitly pop and ensure boolean type for safety, though they should be.
            op_b_val = stack.pop()
            op_a_val = stack.pop()

            # Ensure a and b are definitively booleans before operation
            a = bool(op_a_val) 
            b = bool(op_b_val)

            if tok_rpn == "AND":
                stack.append(a and b)
            elif tok_rpn == "OR": # Explicitly check for "OR"
                stack.append(a or b)
            else:
                logger.error(f"RPN Eval Error: Unknown operator '{tok_rpn}' in RPN string at index {tok_idx}.")
                logger.error(f"RPN token string: {output}")
                raise ValueError(f"Unknown operator {tok_rpn} in RPN evaluation")

    if len(stack) != 1:
        # More debug info
        logger.error(f"RPN Eval Error: Stack should contain a single boolean value at the end.")
        logger.error(f"RPN token string: {output}")
        logger.error(f"Final eval stack: {stack}")
        raise ValueError("Invalid boolean expression, stack final length not 1")
    return stack[0]


# === FUNKTION ZUR AUSWERTUNG EINER EINZELNEN BEDINGUNGSGRUPPE ===
def evaluate_single_condition_group(
    conditions_in_group: Sequence[MutableMapping[str, Any]],
    context: Mapping[str, Any],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    pauschale_code_for_debug: str = "N/A_PAUSCHALE", # For logging
    group_id_for_debug: Any = "N/A_GRUPPE",      # For logging
    debug: bool = False,
    normalized_context: Optional[NormalizedContext] = None,
) -> bool:
    """
    Evaluates the conditions for a single, isolated condition group.
    The logic is based on 'Ebene' and 'Operator' within the group.
    """
    if not conditions_in_group:
        if debug: # Ensure logger is accessible or pass it
            logging.info( # Assuming logger is imported as logging
                "DEBUG Pauschale %s, Gruppe %s: Empty group, result: True",
                pauschale_code_for_debug,
                group_id_for_debug
            )
        return True

    normalized_context = normalized_context or build_normalized_context(context)

    diagnostic_types = {"HAUPTDIAGNOSE IN TABELLE", "HAUPTDIAGNOSE IN LISTE", "ICD", "ICD IN TABELLE", "ICD IN LISTE"}
    use_icd_flag = normalized_context.use_icd
    group_has_non_diag = any(str(cond.get('Bedingungstyp', '')).upper() not in diagnostic_types for cond in conditions_in_group)

    baseline_level_group = 1
    first_level_group = conditions_in_group[0].get('Ebene', 1)
    if first_level_group < baseline_level_group:
        first_level_group = baseline_level_group

    first_res_group = check_single_condition(
        conditions_in_group[0],
        context,
        tabellen_dict_by_table,
        normalized_context,
    )

    tokens_group: List[Any] = ["("] * (first_level_group - baseline_level_group)
    tokens_group.append(bool(first_res_group))

    prev_level_group = first_level_group

    for i in range(1, len(conditions_in_group)):
        cond_grp = conditions_in_group[i]
        cur_level_group = cond_grp.get('Ebene', baseline_level_group)
        if cur_level_group < baseline_level_group:
            cur_level_group = baseline_level_group

        linking_operator = str(conditions_in_group[i-1].get('Operator', "UND")).strip().upper()
        if linking_operator not in ["AND", "OR"]: # This check is for already English operators, will adapt
            # Convert German operator from condition data to English for _evaluate_boolean_tokens
            if linking_operator == "UND":
                english_operator = "AND"
            elif linking_operator == "ODER":
                english_operator = "OR"
            else:
                # Default to AND if somehow an unexpected operator string appears
                logger.warning(f"Unexpected linking_operator '{linking_operator}' in Pauschale {pauschale_code_for_debug}, Gruppe {group_id_for_debug}. Defaulting to AND.")
                english_operator = "AND"
        else: # It was already "AND" or "OR" (e.g. if default was applied and it was English)
             english_operator = linking_operator


        if cur_level_group < prev_level_group:
            tokens_group.extend([")"] * (prev_level_group - cur_level_group))

        tokens_group.append(english_operator) # Append the English operator

        if cur_level_group > prev_level_group:
            tokens_group.extend(["("] * (cur_level_group - prev_level_group))

        cur_res_group = check_single_condition(
            cond_grp,
            context,
            tabellen_dict_by_table,
            normalized_context,
        )
        tokens_group.append(bool(cur_res_group))

        prev_level_group = cur_level_group

    tokens_group.extend([")"] * (prev_level_group - baseline_level_group))

    if not any(isinstance(tok, bool) for tok in tokens_group):
        if debug:
             logging.warning( # Assuming logger is imported as logging
                "DEBUG Pauschale %s, Gruppe %s: Token list for group evaluation has no boolean values. Tokens: %s. Defaulting to True.",
                pauschale_code_for_debug, group_id_for_debug, tokens_group
            )
        return True

    calculated_result = False # Default to False
    try:
        # Ensure tokens_group is not empty before calling, though earlier checks should handle it.
        if not tokens_group:
             if debug:
                logging.warning(f"DEBUG Pauschale {pauschale_code_for_debug}, Gruppe {group_id_for_debug}: Empty tokens_group before _evaluate_boolean_tokens. Defaulting to True as per earlier logic for empty group.")
             return True # Consistent with how truly empty groups are handled (or False if that's preferred for error)

        raw_eval_result = _evaluate_boolean_tokens(tokens_group)
        calculated_result = bool(raw_eval_result) # Explicitly cast to bool immediately

        if debug:
            # Construct expr_str_group carefully for logging
            expr_parts = []
            for t_log in tokens_group: # Use a different loop variable for safety if tokens_group could be complex
                if isinstance(t_log, bool):
                    expr_parts.append(str(t_log).lower())
                elif t_log in ("AND", "OR", "(", ")"):
                    expr_parts.append(f" {t_log} " if t_log in ("AND", "OR") else t_log)
                else:
                    expr_parts.append(f" <UNKNOWN_TOKEN:{t_log}> ") # Should not happen if tokens are clean
            expr_str_group = "".join(expr_parts).replace("  ", " ").strip()
            
            logging.info(
                "DEBUG Pauschale %s, Gruppe %s: Eval tokens: %s (Expression: %s) => %s",
                pauschale_code_for_debug,
                group_id_for_debug,
                tokens_group, 
                expr_str_group,
                calculated_result, # Log the captured boolean result
            )
    except Exception as e_eval_group:
        logging.error(
            "FEHLER bei Gruppenlogik-Ausdruck (Pauschale: %s, Gruppe: %s) Tokens: '%s': %s",
            pauschale_code_for_debug,
            group_id_for_debug,
            str(tokens_group), 
            e_eval_group,
        )
        traceback.print_exc()
        # calculated_result remains False (its initialization)

    if not use_icd_flag and not group_has_non_diag:
        provided_icds = [icd for icd in normalized_context.icd_codes if icd]
        if not provided_icds:
            return False
    return calculated_result


# === FUNKTION ZUR AUSWERTUNG DER STRUKTURIERTEN LOGIK (UND/ODER) ===
# This function is now the new orchestrator for pauschale logic evaluation.

def _evaluate_pauschale_logic_via_ast(
    pauschale_code: str,
    context: Mapping[str, Any],
    all_pauschale_bedingungen_data: List[Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    debug: bool = False,
    normalized_context: Optional[NormalizedContext] = None,
    prepared_structures: Optional[Dict[str, PreparedPauschaleStructure]] = None,
) -> bool:
    normalized_context = normalized_context or build_normalized_context(context)

    structure = _get_prepared_structure(
        pauschale_code,
        all_pauschale_bedingungen_data,
        prepared_structures,
    )

    if not structure.groups and not structure.has_real_conditions:
        if debug:
            logger.info(
                "DEBUG Orchestrator Pauschale %s: No conditions defined. Result: True",
                pauschale_code,
            )
        return True

    group_results: Dict[Any, bool] = {}
    for group in structure.groups:
        result_group = evaluate_single_condition_group(
            group.conditions,
            context,
            tabellen_dict_by_table,
            pauschale_code,
            group.id or group.normalized_id,
            debug,
            normalized_context,
        )
        if group.negated:
            result_group = not result_group
        group_results[group.normalized_id] = bool(result_group)

    if not structure.group_children:
        if not group_results:
            if debug:
                logger.info(
                    "DEBUG Orchestrator Pauschale %s: No evaluable groups. Result: True",
                    pauschale_code,
                )
            return True

        default_operator = DEFAULT_GROUP_OPERATOR.upper()
        final_without_ast = None
        for group_id in sorted(group_results.keys(), key=_sort_group_key):
            group_value = group_results[group_id]
            if final_without_ast is None:
                final_without_ast = group_value
            else:
                if default_operator == "UND":
                    final_without_ast = final_without_ast and group_value
                else:
                    final_without_ast = final_without_ast or group_value
            if debug:
                logger.info(
                    "DEBUG Orchestrator Pauschale %s: Group %s => %s (via default %s)",
                    pauschale_code,
                    group_id,
                    group_value,
                    default_operator,
                )
        return bool(final_without_ast)

    children_map: defaultdict[Any, List[Dict[str, Any]]] = defaultdict(list)
    parent_nodes: Set[Any] = set()
    child_nodes: Set[Any] = set()

    for parent_id, entries in structure.group_children.items():
        if not entries:
            continue
        for entry in entries:
            child_id = entry.get("child")
            op_norm = _normalize_operator_label(entry.get("operator"), default="ODER")
            operator_eval = "AND" if op_norm == "UND" else "OR"
            mapped_entry = {
                "child": child_id,
                "operator": operator_eval,
                "bed_id": entry.get("bed_id", 0),
            }
            children_map[parent_id].append(mapped_entry)
            parent_nodes.add(parent_id)
            if child_id is not None:
                child_nodes.add(child_id)

    for entries in children_map.values():
        entries.sort(key=lambda item: item.get("bed_id", 0))

    recursion_stack: Set[Any] = set()
    memoized_results: Dict[Any, bool] = {}

    def evaluate_node(node_id: Any) -> bool:
        if node_id in memoized_results:
            return memoized_results[node_id]
        if node_id in recursion_stack:
            logger.error(
                "FEHLER Orchestrator Pauschale %s: Cycle detected at node %s.",
                pauschale_code,
                node_id,
            )
            return False
        recursion_stack.add(node_id)

        node_entries = children_map.get(node_id, [])
        result_value = group_results.get(node_id)
        result_value = bool(result_value) if result_value is not None else None

        for entry in node_entries:
            child_id = entry["child"]
            child_value = False
            if child_id is not None:
                if child_id in children_map or child_id in parent_nodes:
                    child_value = evaluate_node(child_id)
                else:
                    child_value = bool(group_results.get(child_id, False))
            operator = entry["operator"]
            if result_value is None:
                result_value = child_value
            else:
                if operator == "AND":
                    result_value = result_value and child_value
                else:
                    result_value = result_value or child_value

        if result_value is None:
            result_value = bool(group_results.get(node_id, False))

        memoized_results[node_id] = bool(result_value)
        recursion_stack.remove(node_id)
        return memoized_results[node_id]

    root_candidates = [node for node in parent_nodes if node not in child_nodes]
    if not root_candidates:
        root_candidates = sorted(parent_nodes, key=_sort_group_key)
    else:
        root_candidates = sorted(root_candidates, key=_sort_group_key)

    if not root_candidates:
        final_result_ast = all(group_results.values()) if group_results else True
    else:
        final_result_ast = True
        for index, root in enumerate(root_candidates):
            root_result = evaluate_node(root)
            if debug:
                logger.info(
                    "DEBUG Orchestrator Pauschale %s: Root %s => %s",
                    pauschale_code,
                    root,
                    root_result,
                )
            if index == 0:
                final_result_ast = root_result
            else:
                final_result_ast = final_result_ast and root_result

    accounted_nodes = parent_nodes.union(child_nodes)
    unused_groups = [gid for gid in group_results.keys() if gid not in accounted_nodes]

    for unused_group in sorted(unused_groups, key=_sort_group_key):
        final_result_ast = final_result_ast and group_results[unused_group]
        if debug:
            logger.info(
                "DEBUG Orchestrator Pauschale %s: Combining unused group %s => %s",
                pauschale_code,
                unused_group,
                group_results[unused_group],
            )

    if debug:
        logger.info(
            "DEBUG Orchestrator Pauschale %s: Final evaluation result: %s",
            pauschale_code,
            final_result_ast,
        )

    return bool(final_result_ast)


def evaluate_pauschale_logic_orchestrator(
    pauschale_code: str,
    context: Mapping[str, Any],
    all_pauschale_bedingungen_data: List[Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    pauschalen_dict: Optional[Dict[str, Dict]] = None,
    debug: bool = False,
    prepared_structures: Optional[Dict[str, PreparedPauschaleStructure]] = None,
) -> bool:
    normalized_context = build_normalized_context(context)

    prueflogik_expr = None
    if pauschalen_dict:
        pauschale_details = pauschalen_dict.get(pauschale_code)
        if pauschale_details:
            prueflogik_expr = pauschale_details.get('Pr\u00fcflogik')
    if prueflogik_expr:
        try:
            return _evaluate_prueflogik_expression(
                prueflogik_expr,
                normalized_context,
                tabellen_dict_by_table,
                pauschale_code,
                debug,
            )
        except Exception as exc:
            logger.warning(
                "WARNUNG Orchestrator Pauschale %s: Pr\u00fcflogik-Auswertung fehlgeschlagen (%s). Fallback auf AST-Auswertung.",
                pauschale_code,
                exc,
            )
    return _evaluate_pauschale_logic_via_ast(
        pauschale_code,
        context,
        all_pauschale_bedingungen_data,
        tabellen_dict_by_table,
        debug,
        normalized_context,
        prepared_structures,
    )


# === PRUEFUNG DER BEDINGUNGEN (STRUKTURIERTES RESULTAT) ===
@with_table_content_cache
def check_pauschale_conditions(
    pauschale_code: str,
    context: Mapping[str, Any],
    pauschale_bedingungen_data: list[dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    lang: str = "de",
    pauschalen_dict: Optional[Dict[str, Dict[str, Any]]] = None,
    prepared_structures: Optional[Dict[str, PreparedPauschaleStructure]] = None,
) -> Dict[str, Any]:
    """Render ein HTML-Fragment für die Bedingungen einer Pauschale."""

    BED_TYP_KEY = "Bedingungstyp"
    BED_WERTE_KEY = "Werte"
    BED_FELD_KEY = "Feld"
    BED_MIN_KEY = "MinWert"
    BED_MAX_KEY = "MaxWert"
    BED_VERGLEICHSOP_KEY = "Vergleichsoperator"

    normalized_context = build_normalized_context(context)
    structure = _get_prepared_structure(
        pauschale_code,
        pauschale_bedingungen_data,
        prepared_structures,
    )

    prueflogik_expr: Optional[str] = None
    prueflogik_pretty = ""
    if pauschalen_dict:
        prueflogik_raw = pauschalen_dict.get(pauschale_code, {}).get("Pr\u00fcflogik")
        if isinstance(prueflogik_raw, str) and prueflogik_raw.strip():
            prueflogik_expr = prueflogik_raw.strip()
            prueflogik_pretty = _format_prueflogik_for_display(prueflogik_expr, lang)
    group_logic_terms = _extract_group_logic_terms(
        pauschale_code,
        prueflogik_expr,
        pauschale_bedingungen_data,
    )

    def _render_prueflogik_header() -> str:
        label = translate("prueflogik_header", lang)
        return (
            f"<div class=\"condition-prueflogik\"><strong>{escape(label)}</strong></div>"
        )

    if not structure.has_real_conditions:
        html_snippets: list[str] = []
        if prueflogik_expr:
            html_snippets.append(_render_prueflogik_header())
        html_snippets.append(
            f"<p><i>{translate('no_conditions_for_pauschale', lang)}</i></p>"
        )
        return {
            "html": "".join(html_snippets),
            "errors": [],
            "trigger_lkn_condition_met": False,
            "prueflogik_expr": prueflogik_expr,
            "prueflogik_pretty": prueflogik_pretty,
            "group_logic_terms": group_logic_terms,
        }

    html_parts: list[str] = []
    if prueflogik_expr:
        html_parts.append(_render_prueflogik_header())

    trigger_lkn_condition_overall_met = False
    current_group_open = False

    for token in structure.sequence:
        token_type = token.get("type")
        if token_type == "ast_operator":
            if current_group_open:
                html_parts.append("</div>")
                current_group_open = False
            op_val = str(token.get("operator") or "").upper()
            if op_val == "ODER":
                html_parts.append(
                    f"<div class=\"condition-separator group-operator\">{translate('OR', lang)}</div>"
                )
            elif op_val == "UND":
                html_parts.append(
                    f"<div class=\"condition-separator group-operator\">{translate('AND', lang)}</div>"
                )
            continue

        if token_type != "group":
            continue

        group = structure.group_lookup.get(token.get("group_id"))
        if not group:
            continue

        if current_group_open:
            html_parts.append("</div>")

        group_identifier = group.id if group.id is not None else group.normalized_id
        group_title = f"{translate('condition_group', lang)} {escape(str(group_identifier))}"
        group_class = "condition-group condition-group-negated" if group.negated else "condition-group"
        html_parts.append(
            f"<div class=\"{group_class}\"><div class=\"condition-group-title\">{group_title}</div>"
        )
        current_group_open = True

        for cond_index, cond_data in enumerate(group.conditions):
            if cond_index > 0 and (cond_index - 1) < len(group.intra_ops):
                link_op = group.intra_ops[cond_index - 1]
                if link_op in ("UND", "ODER"):
                    op_label = translate("AND", lang) if link_op == "UND" else translate("OR", lang)
                    html_parts.append(
                        f"<div class=\"condition-separator intra-group-operator\">{op_label}</div>"
                    )

            condition_met = check_single_condition(
                cond_data,
                context,
                tabellen_dict_by_table,
                normalized_context,
            )

            cond_type_upper = str(cond_data.get(BED_TYP_KEY, "")).upper()
            context_hint_allowed = True
            if condition_met and cond_type_upper in (
                "LEISTUNGSPOSITIONEN IN LISTE",
                "LKN",
                "LEISTUNGSPOSITIONEN IN TABELLE",
                "TARIFPOSITIONEN IN TABELLE",
            ):
                trigger_lkn_condition_overall_met = True

            icon_svg_path = "#icon-check" if condition_met else "#icon-cross"
            icon_class = "condition-icon-fulfilled" if condition_met else "condition-icon-not-fulfilled"

            translated_cond_type_display = translate_condition_type(
                cond_data.get(BED_TYP_KEY, "N/A"),
                lang,
            )

            original_werte = str(cond_data.get(BED_WERTE_KEY, ""))
            werte_display = ""

            if cond_type_upper in ("LEISTUNGSPOSITIONEN IN LISTE", "LKN"):
                lkn_codes = [l.strip().upper() for l in original_werte.split(',') if l.strip()]
                if lkn_codes:
                    lkn_details = []
                    for lkn_code in lkn_codes:
                        desc = get_beschreibung_fuer_lkn_im_backend(
                            lkn_code,
                            leistungskatalog_dict,
                            lang,
                        )
                        link_text = escape(lkn_code)
                        link_html = create_html_info_link(lkn_code, "lkn", link_text)
                        desc_html = f" ({escape(desc)})" if desc else ""
                        lkn_details.append(f"{link_html}{desc_html}")
                    werte_display = ", ".join(lkn_details)
                else:
                    werte_display = f"<i>{translate('no_lkns_spec', lang)}</i>"

            elif cond_type_upper in (
                "LEISTUNGSPOSITIONEN IN TABELLE",
                "TARIFPOSITIONEN IN TABELLE",
            ):
                tokens = [t.strip() for t in original_werte.split(',') if t.strip()]
                if len(tokens) == 1 and tokens[0].upper() in ("ODER", "OR", "UND", "AND"):
                    table_names = tokens  # treat as literal table name (e.g., "OR")
                else:
                    table_names = [t for t in tokens if t.upper() not in ("ODER", "OR", "UND", "AND")]
                if table_names:
                    table_links = []
                    for tn in table_names:
                        entries = get_table_content(tn, "service_catalog", tabellen_dict_by_table, lang)
                        data_content = json.dumps(entries)
                        table_links.append(create_html_info_link(tn, "lkn_table", escape(tn), data_content=data_content))
                    werte_display = ", ".join(table_links)
                else:
                    werte_display = ""
                    context_hint_allowed = False

            elif cond_type_upper in ("HAUPTDIAGNOSE IN TABELLE", "ICD IN TABELLE"):
                tokens = [t.strip() for t in original_werte.split(',') if t.strip()]
                if len(tokens) == 1 and tokens[0].upper() in ("ODER", "OR", "UND", "AND"):
                    table_names = tokens
                else:
                    table_names = [t for t in tokens if t.upper() not in ("ODER", "OR", "UND", "AND")]
                if table_names:
                    table_links = []
                    for tn in table_names:
                        entries = get_table_content(tn, "icd", tabellen_dict_by_table, lang)
                        data_content = json.dumps(entries)
                        table_links.append(create_html_info_link(tn, "icd_table", escape(tn), data_content=data_content))
                    werte_display = ", ".join(table_links)
                else:
                    werte_display = ""
                    context_hint_allowed = False

            elif cond_type_upper in ("ICD", "HAUPTDIAGNOSE IN LISTE"):
                icd_codes = [icd.strip().upper() for icd in original_werte.split(',') if icd.strip()]
                if icd_codes:
                    icd_details = []
                    for icd_code in icd_codes:
                        desc_icd = get_beschreibung_fuer_icd_im_backend(
                            icd_code,
                            tabellen_dict_by_table,
                            lang=lang,
                        )
                        link_html = create_html_info_link(icd_code, "diagnosis", escape(icd_code))
                        desc_html = f" ({escape(desc_icd)})" if desc_icd else ""
                        icd_details.append(f"{link_html}{desc_html}")
                    werte_display = ", ".join(icd_details)
                else:
                    werte_display = f"<i>{translate('no_icds_spec', lang)}</i>"

            elif cond_type_upper == "MEDIKAMENTE IN LISTE":
                codes = [med.strip().upper() for med in original_werte.split(',') if med.strip()]
                if codes:
                    meds = [create_html_info_link(code, "medication", escape(code)) for code in codes]
                    werte_display = ", ".join(meds)
                else:
                    werte_display = f"<i>{translate('no_medications_spec', lang)}</i>"

            elif cond_type_upper == "PATIENTENBEDINGUNG":
                feld_name_pat_orig = str(cond_data.get(BED_FELD_KEY, ""))
                feld_name_pat_display = (
                    translate(feld_name_pat_orig.lower(), lang)
                    if feld_name_pat_orig.lower() in ["alter", "geschlecht"]
                    else escape(feld_name_pat_orig.capitalize())
                )

                translated_cond_type_display = translate(
                    "patient_condition_display",
                    lang,
                    field=feld_name_pat_display,
                )

                min_w_pat = cond_data.get(BED_MIN_KEY)
                max_w_pat = cond_data.get(BED_MAX_KEY)
                expl_wert_pat = cond_data.get(BED_WERTE_KEY)

                if feld_name_pat_orig.lower() == "alter":
                    if min_w_pat is not None or max_w_pat is not None:
                        val_disp_parts = []
                        if min_w_pat is not None:
                            val_disp_parts.append(
                                f"{translate('min', lang)} {escape(str(min_w_pat))}"
                            )
                        if max_w_pat is not None:
                            val_disp_parts.append(
                                f"{translate('max', lang)} {escape(str(max_w_pat))}"
                            )
                        werte_display = " ".join(val_disp_parts)
                    elif expl_wert_pat is not None:
                        werte_display = escape(str(expl_wert_pat))
                    else:
                        werte_display = translate('not_specified', lang)
                elif feld_name_pat_orig.lower() == "geschlecht":
                    werte_display = (
                        translate(str(expl_wert_pat).lower(), lang)
                        if expl_wert_pat
                        else translate('not_specified', lang)
                    )
                else:
                    werte_display = escape(
                        str(
                            expl_wert_pat
                            if expl_wert_pat is not None
                            else translate('not_specified', lang)
                        )
                    )

            elif cond_type_upper == "ALTER IN JAHREN BEI EINTRITT":
                op_val = cond_data.get(BED_VERGLEICHSOP_KEY, "=")
                werte_display = f"{escape(op_val)} {escape(original_werte)}"

            elif cond_type_upper == "ANZAHL":
                op_val = cond_data.get(BED_VERGLEICHSOP_KEY, "=")
                werte_display = f"{escape(op_val)} {escape(original_werte)}"

            elif cond_type_upper == "SEITIGKEIT":
                op_val = cond_data.get(BED_VERGLEICHSOP_KEY, "=")
                regel_wert_norm = original_werte.strip().replace("'", "").lower()
                if regel_wert_norm == "b":
                    regel_wert_norm = translate("bilateral", lang)
                elif regel_wert_norm == "e":
                    regel_wert_norm = translate("unilateral", lang)
                elif regel_wert_norm == "l":
                    regel_wert_norm = translate("left", lang)
                elif regel_wert_norm == "r":
                    regel_wert_norm = translate("right", lang)
                else:
                    regel_wert_norm = escape(regel_wert_norm)
                werte_display = f"{escape(op_val)} {regel_wert_norm}"

            elif cond_type_upper == "GESCHLECHT IN LISTE":
                gender_tokens = [g.strip().lower() for g in original_werte.split(',') if g.strip()]
                translated_genders = [translate(g, lang) for g in gender_tokens]
                werte_display = escape(", ".join(translated_genders))

            elif cond_type_upper == "MEDIKAMENTE IN LISTE":
                med_codes = [med.strip() for med in original_werte.split(',') if med.strip()]
                if med_codes:
                    werte_display = escape(", ".join(med_codes))
                else:
                    werte_display = f"<i>{translate('no_medications_spec', lang)}</i>"

            else:
                werte_display = escape(original_werte)

            context_match_info_html = ""
            if condition_met and context_hint_allowed:
                match_details_parts: list[str] = []

                if cond_type_upper in (
                    "ICD",
                    "HAUPTDIAGNOSE IN LISTE",
                    "ICD IN LISTE",
                    "HAUPTDIAGNOSE IN TABELLE",
                    "ICD IN TABELLE",
                ):
                    provided_icds_upper = {
                        p_icd.upper() for p_icd in context.get("ICD", []) if p_icd
                    }

                    required_codes_in_rule = set()
                    if "TABELLE" in cond_type_upper:
                        table_ref = cond_data.get(BED_WERTE_KEY)
                        if table_ref and isinstance(table_ref, str):
                            for entry in get_table_content(
                                table_ref,
                                "icd",
                                tabellen_dict_by_table,
                                lang,
                            ):
                                if entry.get("Code"):
                                    required_codes_in_rule.add(entry["Code"].upper())
                    else:
                        required_codes_in_rule = {
                            w.strip().upper()
                            for w in str(cond_data.get(BED_WERTE_KEY, "")).split(',')
                            if w.strip()
                        }

                    matching_icds = sorted(
                        provided_icds_upper.intersection(required_codes_in_rule)
                    )
                    if matching_icds:
                        linked_matching_icds = []
                        for icd_code in matching_icds:
                            desc = get_beschreibung_fuer_icd_im_backend(
                                icd_code,
                                tabellen_dict_by_table,
                                lang=lang,
                            )
                            display_text = escape(f"{icd_code} ({desc})")
                            linked_matching_icds.append(
                                create_html_info_link(icd_code, "diagnosis", display_text)
                            )
                        if linked_matching_icds:
                            match_details_parts.append(
                                translate(
                                    "fulfilled_by_icd",
                                    lang,
                                    icd_code_link=", ".join(linked_matching_icds),
                                )
                            )

                elif cond_type_upper in (
                    "LEISTUNGSPOSITIONEN IN LISTE",
                    "LKN",
                    "LKN IN LISTE",
                    "LEISTUNGSPOSITIONEN IN TABELLE",
                    "TARIFPOSITIONEN IN TABELLE",
                    "LKN IN TABELLE",
                ):
                    provided_lkns_upper = {
                        lkn.upper() for lkn in context.get("LKN", []) if lkn
                    }

                    required_lkn_codes = set()
                    if "TABELLE" in cond_type_upper:
                        table_ref = cond_data.get(BED_WERTE_KEY)
                        if table_ref and isinstance(table_ref, str):
                            for entry in get_table_content(
                                table_ref,
                                "service_catalog",
                                tabellen_dict_by_table,
                                lang,
                            ):
                                if entry.get("Code"):
                                    required_lkn_codes.add(entry["Code"].upper())
                    else:
                        required_lkn_codes = {
                            w.strip().upper()
                            for w in str(cond_data.get(BED_WERTE_KEY, "")).split(',')
                            if w.strip()
                        }

                    matching_lkns = sorted(
                        provided_lkns_upper.intersection(required_lkn_codes)
                    )
                    if matching_lkns:
                        linked_matching_lkns = []
                        for lkn_code in matching_lkns:
                            desc = get_beschreibung_fuer_lkn_im_backend(
                                lkn_code,
                                leistungskatalog_dict,
                                lang,
                            )
                            display_text = escape(f"{lkn_code} ({desc})")
                            linked_matching_lkns.append(
                                create_html_info_link(lkn_code, "lkn", display_text)
                            )
                        if linked_matching_lkns:
                            match_details_parts.append(
                                translate(
                                    "fulfilled_by_lkn",
                                    lang,
                                    lkn_code_link=", ".join(linked_matching_lkns),
                                )
                            )

                if not match_details_parts:
                    match_details_parts.append(
                        translate('condition_met_context_generic', lang)
                    )
                context_match_info_html = (
                    f"<span class=\"context-match-info fulfilled\">{'; '.join(match_details_parts)}</span>"
                )

            html_parts.append(
                """
                <div class="condition-item">
                    <span class="condition-status-icon {icon_class}">
                        <svg viewBox="0 0 24 24"><use xlink:href="{icon_svg_path}"></use></svg>
                    </span>
                    <span class="condition-type-display">{cond_type_display}:</span>
                    <span class="condition-text-wrapper">{value_html} {context_match}</span>
                </div>
                """.format(
                    icon_class=icon_class,
                    icon_svg_path=icon_svg_path,
                    cond_type_display=escape(translated_cond_type_display),
                    value_html=werte_display,
                    context_match=context_match_info_html,
                )
            )

    if current_group_open:
        html_parts.append("</div>")

    return {
        "html": "".join(html_parts),
        "errors": [],
        "trigger_lkn_condition_met": trigger_lkn_condition_overall_met,
        "prueflogik_expr": prueflogik_expr,
        "prueflogik_pretty": prueflogik_pretty,
        "group_logic_terms": group_logic_terms,
    }
@with_table_content_cache
def check_pauschale_conditions_structured(
    pauschale_code: str,
    context: Mapping[str, Any],
    pauschale_bedingungen_data: list[dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    lang: str = "de",
    pauschalen_dict: Optional[Dict[str, Dict[str, Any]]] = None,
    prepared_structures: Optional[Dict[str, PreparedPauschaleStructure]] = None,
) -> Dict[str, Any]:
    """Gibt eine strukturierte Darstellung der Bedingungen einer Pauschale zurück."""

    BED_TYP_KEY = "Bedingungstyp"
    BED_WERTE_KEY = "Werte"
    BED_FELD_KEY = "Feld"
    BED_MIN_KEY = "MinWert"
    BED_MAX_KEY = "MaxWert"
    BED_VERGLEICHSOP_KEY = "Vergleichsoperator"

    normalized_context = build_normalized_context(context)
    structure = _get_prepared_structure(
        pauschale_code,
        pauschale_bedingungen_data,
        prepared_structures,
    )

    prueflogik_expr: Optional[str] = None
    prueflogik_pretty = ""
    if pauschalen_dict:
        prueflogik_raw = pauschalen_dict.get(pauschale_code, {}).get("Pr\u00fcflogik")
        if isinstance(prueflogik_raw, str) and prueflogik_raw.strip():
            prueflogik_expr = prueflogik_raw.strip()
            prueflogik_pretty = _format_prueflogik_for_display(prueflogik_expr, lang)
    group_logic_terms = _extract_group_logic_terms(
        pauschale_code,
        prueflogik_expr,
        pauschale_bedingungen_data,
    )

    if not structure.has_real_conditions:
        return {
            "groups": [],
            "inter_group_ops": [],
            "group_children": {},
            "trigger_lkn_condition_met": False,
            "prueflogik_expr": prueflogik_expr,
            "prueflogik_pretty": prueflogik_pretty,
            "group_logic_terms": group_logic_terms,
        }

    groups_output: list[dict[str, Any]] = []
    trigger_lkn_condition_overall_met = False

    for group in structure.groups:
        group_entry: dict[str, Any] = {
            "id": group.id,
            "normalized_id": group.normalized_id,
            "conditions": [],
            "intra_ops": list(group.intra_ops),
            "negated": bool(group.negated),
            "sort_index": group.sort_index,
            "parent": group.parent,
            "group_operator": group.group_operator,
        }

        for cond in group.conditions:
            cond_type_upper = str(cond.get(BED_TYP_KEY, "")).upper()
            matched = bool(
                check_single_condition(
                    cond,
                    context,
                    tabellen_dict_by_table,
                    normalized_context,
                )
            )

            if matched and cond_type_upper in (
                "LEISTUNGSPOSITIONEN IN LISTE",
                "LKN",
                "LEISTUNGSPOSITIONEN IN TABELLE",
                "TARIFPOSITIONEN IN TABELLE",
            ):
                trigger_lkn_condition_overall_met = True

            group_entry["conditions"].append(
                {
                    "type": cond.get(BED_TYP_KEY),
                    "werte": cond.get(BED_WERTE_KEY),
                    "feld": cond.get(BED_FELD_KEY),
                    "min": cond.get(BED_MIN_KEY),
                    "max": cond.get(BED_MAX_KEY),
                    "vergleich": cond.get(BED_VERGLEICHSOP_KEY),
                    "matched": matched,
                }
            )

        groups_output.append(group_entry)

    inter_group_ops_out = list(structure.inter_group_ops)
    group_children_out: dict[Any, list[dict[str, Any]]] = {
        parent: [dict(entry) for entry in entries]
        for parent, entries in structure.group_children.items()
    }

    return {
        "groups": groups_output,
        "inter_group_ops": inter_group_ops_out,
        "group_children": group_children_out,
        "trigger_lkn_condition_met": trigger_lkn_condition_overall_met,
        "prueflogik_expr": prueflogik_expr,
        "prueflogik_pretty": prueflogik_pretty,
        "group_logic_terms": group_logic_terms,
    }
def render_condition_results_html(
    results: List[Dict[str, Any]], # results ist hier das Ergebnis von der alten check_pauschale_conditions
    lang: str = "de"
) -> str:
    """Wandelt die von der *alten* `check_pauschale_conditions` gelieferten Ergebnisse in HTML um.
       Diese Funktion wird für die neue HTML-Struktur nicht mehr direkt benötigt.
       Die Logik zur HTML-Erstellung ist jetzt in der neuen `check_pauschale_conditions`.
    """
    # Diese Funktion ist jetzt veraltet für die neue Anforderung der strukturierten HTML-Ausgabe.
    # Sie könnte für Debugging-Zwecke oder eine sehr einfache Darstellung beibehalten werden.
    # Für die Aufgabe hier, die CSS-Klassen zu implementieren, wird sie nicht verwendet.
    logger.warning("render_condition_results_html wird aufgerufen, ist aber für die neue HTML-Struktur veraltet.")
    html_parts = ["<ul class='legacy-condition-list'>"] # Hinweis auf veraltete Liste
    for item in results: # 'results' hier ist die Liste von Dictionaries mit 'erfuellt', 'Bedingungstyp', 'Werte'
        icon_text = "&#10003;" if item.get("erfuellt") else "&#10007;"
        typ_text = escape(str(item.get("Bedingungstyp", "")))
        wert_text = escape(str(item.get("Werte", "")))
        html_parts.append(f"<li>{icon_text} {typ_text}: {wert_text}</li>")
    html_parts.append("</ul>")
    return "".join(html_parts)


# --- Ausgelagerte Pauschalen-Ermittlung ---
@with_table_content_cache
def determine_applicable_pauschale(
    user_input: str, # Bleibt für potenzielles LLM-Ranking, aktuell nicht primär genutzt
    rule_checked_leistungen: list[dict], # Für die initiale Findung potenzieller Pauschalen (derzeit ungenutzt)
    context: Mapping[str, Any], # Enthält LKN, ICD, Alter, Geschlecht, Seitigkeit, Anzahl, useIcd
    pauschale_lp_data: List[Dict],
    pauschale_bedingungen_data: List[Dict],
    pauschalen_dict: Dict[str, Dict], # Dict aller Pauschalen {code: details}
    leistungskatalog_dict: Dict[str, Dict], # Für LKN-Beschreibungen etc.
    tabellen_dict_by_table: Dict[str, List[Dict]], # Für Tabellen-Lookups
    potential_pauschale_codes_input: Set[str] | None = None, # Optional vorabgefilterte Codes
    lang: str = 'de',
    prepared_structures: Dict[str, Any] | None = None
    ) -> dict:
    """Finde die bestmögliche Pauschale anhand der Regeln.

    Parameters
    ----------
    user_input : str
        Ursprüngliche Benutzereingabe (nur zu Loggingzwecken).
    rule_checked_leistungen : list[dict]
        Bereits regelgeprüfte Leistungen.
    context : dict
        Kontextdaten wie LKN, ICD, Alter oder Seitigkeit.
    pauschale_lp_data : list[dict]
        Zuordnung von LKN zu Pauschalen.
    pauschale_bedingungen_data : list[dict]
        Detaillierte Bedingungsdefinitionen.
    pauschalen_dict : dict
        Stammdaten aller Pauschalen.
    leistungskatalog_dict : dict
        LKN-Katalog für Beschreibungen.
    tabellen_dict_by_table : dict
        Inhalte referenzierter Tabellen.
    potential_pauschale_codes_input : set[str], optional
        Vorab festgelegte Kandidaten. Wird ``None`` übergeben, ermittelt die
        Funktion mögliche Codes aus den Kontext-LKN.
    lang : str, optional
        Sprache der Ausgaben, Standard ``"de"``.

    Returns
    -------
    dict
        Ergebnis mit ausgewählter Pauschale, Erklärungs-HTML und allen
        bewerteten Kandidaten.

    Notes
    -----
    Zunächst werden anhand der LKN sowie der Bedingungsdefinitionen mögliche
    Kandidaten gesammelt. Für jeden Code wird
    :func:`evaluate_structured_conditions` aufgerufen. Aus den gültigen
    Pauschalen wird der Kandidat mit dem höchsten Score (Taxpunkte) und dem
    niedrigsten Buchstabensuffix gewählt.

    Examples
    --------
    >>> result = determine_applicable_pauschale(
    ...     "",
    ...     rule_checked_leistungen,
    ...     {"LKN": ["C04.51B"], "Seitigkeit": "re"},
    ...     lp_data,
    ...     bedingungen,
    ...     pauschalen,
    ...     leistungskatalog,
    ...     tabellen,
    ... )
    >>> result["type"]
    'Pauschale'
    """
    logger.info("INFO: Starte Pauschalenermittlung mit strukturierter Bedingungsprüfung...")
    PAUSCHALE_ERKLAERUNG_KEY = 'pauschale_erklaerung_html'; POTENTIAL_ICDS_KEY = 'potential_icds'
    PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN = 'Pauschale_Text'
    LP_LKN_KEY = 'Leistungsposition'; LP_PAUSCHALE_KEY = 'Pauschale' # In PAUSCHALEN_Leistungspositionen
    BED_PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp' # In PAUSCHALEN_Bedingungen
    BED_WERTE_KEY = 'Werte'

    # Keep signature compatibility: rule_checked_leistungen wird aktuell nicht ausgewertet.
    _ = rule_checked_leistungen

    if prepared_structures is None:
        logger.info("INFO: prepared_structures nicht übergeben, erstelle Index on-the-fly (langsam).")
        prepared_structures = build_pauschale_condition_structure_index(pauschale_bedingungen_data)

    use_icd_flag = context.get('useIcd', True)
    requires_icd_cache: Dict[str, bool] = {}
    candidate_lkn_sources: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    context_lkns_in_tables_cache: Dict[str, Set[str]] = {}
    excluded_lkn_tables = get_excluded_lkn_tables()

    def _get_tables_for_context_lkn(lkn_code: str) -> Set[str]:
        """Return cached service catalog tables for a context LKN code."""
        normalized = str(lkn_code or "").upper()
        if not normalized:
            return set()
        cached = context_lkns_in_tables_cache.get(normalized)
        if cached is not None:
            return cached
        tables_for_lkn_ctx: Set[str] = set()
        for table_name_key_norm, table_entries in (tabellen_dict_by_table or {}).items():
            for entry in table_entries:
                if str(entry.get('Tabelle_Typ', '')).lower() != "service_catalog":
                    continue
                if str(entry.get('Code', '')).upper() == normalized:
                    tables_for_lkn_ctx.add(str(table_name_key_norm).lower())
        context_lkns_in_tables_cache[normalized] = tables_for_lkn_ctx
        return tables_for_lkn_ctx

    potential_pauschale_codes: Set[str] = set()
    context_lkns_for_search = {str(lkn).upper() for lkn in context.get("LKN", []) if lkn}

    if potential_pauschale_codes_input is not None:
        potential_pauschale_codes = potential_pauschale_codes_input
        logger.info(
            "DEBUG: Verwende übergebene potenzielle Pauschalen: %s",
            potential_pauschale_codes,
        )
    else:
        logger.info("DEBUG: Suche potenzielle Pauschalen (da nicht übergeben)...")
        # Methode a: Direkte Links aus PAUSCHALEN_Leistungspositionen
        for item in pauschale_lp_data:
            lkn_in_lp = item.get(LP_LKN_KEY)
            if lkn_in_lp and lkn_in_lp.upper() in context_lkns_for_search:
                pc = item.get(LP_PAUSCHALE_KEY)
                if pc and pc in pauschalen_dict:
                    potential_pauschale_codes.add(pc)
        # Methode b: Links aus Bedingungstabelle
        for cond in pauschale_bedingungen_data:
            pc = cond.get(BED_PAUSCHALE_KEY)
            if not (pc and pc in pauschalen_dict): continue
            bedingungstyp_cond = cond.get(BED_TYP_KEY, "").upper()
            werte_cond = cond.get(BED_WERTE_KEY, "")
            if bedingungstyp_cond in LKN_LIST_CONDITION_TYPES:
                werte_liste_cond = {w.strip().upper() for w in str(werte_cond).split(',') if w.strip()}
                if context_lkns_for_search.intersection(werte_liste_cond):
                    potential_pauschale_codes.add(pc)
            elif bedingungstyp_cond in LKN_TABLE_CONDITION_TYPES:
                table_refs_raw = [t.strip() for t in str(werte_cond).split(',') if t.strip()]
                table_refs_cond = {t.lower() for t in table_refs_raw}
                for lkn_ctx in context_lkns_for_search:
                    if table_refs_cond.intersection(_get_tables_for_context_lkn(lkn_ctx)):
                        potential_pauschale_codes.add(pc)
                        break # Go to next condition
        logger.info(
            "DEBUG: Finale potenzielle Pauschalen nach LKN-basierter Suche: %s",
            potential_pauschale_codes,
        )

    # LKN-Quellen für alle Kandidaten ermitteln, egal woher sie stammen.
    # Dies ist entscheidend für die Filterlogik in der Erklärungs-HTML.
    for pc in potential_pauschale_codes:
        # Direkte LKN-Links prüfen
        for item in pauschale_lp_data:
            if item.get(LP_PAUSCHALE_KEY) == pc:
                lkn_in_lp = item.get(LP_LKN_KEY)
                if lkn_in_lp and lkn_in_lp.upper() in context_lkns_for_search:
                    candidate_lkn_sources[pc].append({
                        "lkn": str(lkn_in_lp).upper(), "source": "direct", "table": None
                    })
        # LKN-Bedingungen (Liste und Tabelle) prüfen
        for cond in pauschale_bedingungen_data:
            if cond.get(BED_PAUSCHALE_KEY) != pc: continue
            bedingungstyp_cond = cond.get(BED_TYP_KEY, "").upper()
            werte_cond = cond.get(BED_WERTE_KEY, "")
            if bedingungstyp_cond in LKN_LIST_CONDITION_TYPES:
                werte_liste_cond = {w.strip().upper() for w in str(werte_cond).split(',') if w.strip()}
                matching_codes = context_lkns_for_search.intersection(werte_liste_cond)
                for code in matching_codes:
                    candidate_lkn_sources[pc].append({
                        "lkn": code, "source": "direct", "table": None
                    })
            elif bedingungstyp_cond in LKN_TABLE_CONDITION_TYPES:
                table_refs_raw = [t.strip() for t in str(werte_cond).split(',') if t.strip()]
                table_refs_cond = {t.lower() for t in table_refs_raw}
                for lkn_ctx in context_lkns_for_search:
                    matching_tables = table_refs_cond.intersection(_get_tables_for_context_lkn(lkn_ctx))
                    for table in matching_tables:
                        candidate_lkn_sources[pc].append({
                            "lkn": lkn_ctx, "source": "table", "table": table
                        })


    if not potential_pauschale_codes:
        return {"type": "Error", "message": "Keine potenziellen Pauschalen für die erbrachten Leistungen und den Kontext gefunden.", "evaluated_pauschalen": []}

    evaluated_candidates = []
    # print(f"INFO: Werte strukturierte Bedingungen für {len(potential_pauschale_codes)} potenzielle Pauschalen aus...")
    # print(f"  Kontext für evaluate_structured_conditions: {context}")
    for code in sorted(list(potential_pauschale_codes)): # Sortiert für konsistente Log-Reihenfolge
        if code not in pauschalen_dict:
            # print(f"  WARNUNG: Potenzieller Code {code} nicht in pauschalen_dict gefunden, überspringe.")
            continue
        
        is_pauschale_valid_structured = False
        # bedingungs_html = "" # Removed: HTML generation deferred
        try:
            # evaluate_structured_conditions is now the orchestrator and handles group logic internally
            is_pauschale_valid_structured = evaluate_pauschale_logic_orchestrator( 
                pauschale_code=code,
                context=context,
                all_pauschale_bedingungen_data=pauschale_bedingungen_data,
                tabellen_dict_by_table=tabellen_dict_by_table,
                pauschalen_dict=pauschalen_dict,
                debug=False, # Performance: Disable debug logging in loop
                prepared_structures=prepared_structures,
            )
            
            # Removed: check_pauschale_conditions call
            # check_res = check_pauschale_conditions(...)
            # bedingungs_html = check_res.get("html", "")
            
        except Exception as e_eval:
            logger.error(
                "FEHLER bei evaluate_structured_conditions für Pauschale %s: %s",
                code,
                e_eval,
            )
            traceback.print_exc()

        tp_raw = pauschalen_dict[code].get("Taxpunkte")
        try:
            tp_val = float(tp_raw) if tp_raw is not None else 0.0
        except (ValueError, TypeError):
            tp_val = 0.0

        structure = prepared_structures.get(code)
        requires_icd = requires_icd_cache.setdefault(
            code,
            pauschale_requires_icd(code, structure, pauschalen_dict),
        )
        matched_lkn_count = count_matching_lkn_codes(
            context, structure, tabellen_dict_by_table
        )

        # Removed: check_pauschale_conditions_structured call
        # structured_cond = check_pauschale_conditions_structured(...)
        structured_cond = None # Defer generation

        sources = candidate_lkn_sources.get(code, [])
        unique_sources = []
        seen_signatures = set()
        for s in sources:
            signature = (s['lkn'], s['source'], s['table'])
            if signature not in seen_signatures:
                unique_sources.append(s)
                seen_signatures.add(signature)

        evaluated_candidates.append({
            "code": code,
            "details": pauschalen_dict[code],
            "is_valid_structured": is_pauschale_valid_structured,
            "bedingungs_pruef_html": "", # Placeholder, generated later if needed
            "conditions_structured": structured_cond,
            "taxpunkte": tp_val,
            "requires_icd": requires_icd,
            "matched_lkn_count": matched_lkn_count,
            "lkn_match_sources": sorted(unique_sources, key=lambda x: (x['lkn'], x['source'], x['table'] or '')),
        })

    valid_candidates = [cand for cand in evaluated_candidates if cand["is_valid_structured"]]
    logger.info(
        "DEBUG: Struktur-gültige Kandidaten nach Prüfung: %s",
        [c["code"] for c in valid_candidates],
    )

    # Score pro gültigem Kandidaten berechnen (hier: Taxpunkte als Beispiel)
    for cand in valid_candidates:
        cand["score"] = cand.get("taxpunkte", 0)

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
            logger.info(
                "INFO: Auswahl aus %s struktur-gültigen %s Kandidaten.",
                len(chosen_list_for_selection),
                selection_type_message,
            )

            # Score je Kandidat ermitteln (hier einfach Taxpunkte als Beispiel)
            for cand in chosen_list_for_selection:
                cand["score"] = cand.get("taxpunkte", 0)

            # Sortierung: Höchster Score zuerst, bei Gleichstand entscheidet nur der Buchstabensuffix
            def sort_key_score_suffix(candidate):
                code_str = str(candidate['code'])
                match = re.search(r"([A-Z])$", code_str)
                if match:
                    suffix_ord = ord(match.group(1))
                else:
                    suffix_ord = ord('Z') + 1
                matches = candidate.get('matched_lkn_count', 0)
                return (
                    -matches,
                    suffix_ord,
                    -candidate.get("score", 0),
                )

            chosen_list_for_selection.sort(key=sort_key_score_suffix)
            selected_candidate_info = chosen_list_for_selection[0]
            logger.info(
                "INFO: Gewählte Pauschale nach Score-Sortierung: %s",
                selected_candidate_info["code"],
            )
            # print(f"   DEBUG: Sortierte Kandidatenliste ({selection_type_message}): {[c['code'] for c in chosen_list_for_selection]}")
        else:
             # Sollte nicht passieren, wenn valid_candidates nicht leer war, aber zur Sicherheit
             return {"type": "Error", "message": "Interner Fehler bei der Pauschalenauswahl (Kategorisierung fehlgeschlagen).", "evaluated_pauschalen": evaluated_candidates}
    else: # Keine valid_candidates (keine Pauschale hat die strukturierte Prüfung bestanden)
        logger.info("INFO: Keine Pauschale erfüllt die strukturierten Bedingungen.")
        # Erstelle eine informativere Nachricht, wenn potenzielle Kandidaten da waren
        if potential_pauschale_codes:
            # Hole die Namen der geprüften, aber nicht validen Pauschalen
            gepruefte_codes_namen = [f"{c['code']} ({get_lang_field(c['details'], PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, lang) or 'N/A'})"
                                     for c in evaluated_candidates if not c['is_valid_structured']]
            msg_details = ""
            if gepruefte_codes_namen:
                msg_details = " Folgende potenziellen Pauschalen wurden geprüft, aber deren Bedingungen waren nicht erfüllt: " + ", ".join(gepruefte_codes_namen)

            return {"type": "Error", "message": f"Keine der potenziellen Pauschalen erfüllte die detaillierten UND/ODER-Bedingungen.{msg_details}", "evaluated_pauschalen": evaluated_candidates}
        else: # Sollte durch die Prüfung am Anfang von potential_pauschale_codes abgedeckt sein
            return {"type": "Error", "message": "Keine passende Pauschale gefunden (keine potenziellen Kandidaten).", "evaluated_pauschalen": evaluated_candidates}

    if not selected_candidate_info: # Doppelte Sicherheit
        return {"type": "Error", "message": "Interner Fehler: Keine Pauschale nach Auswahlprozess selektiert.", "evaluated_pauschalen": evaluated_candidates}

    best_pauschale_code = selected_candidate_info["code"]
    best_pauschale_details = selected_candidate_info["details"].copy() # Kopie für Modifikationen

    # Generiere HTML für die Bedingungsprüfung der ausgewählten Pauschale
    condition_errors_html_gen = [] # Initialize with an empty list
    try:
        condition_result_html_dict = check_pauschale_conditions(
            best_pauschale_code,
            context,
            pauschale_bedingungen_data,
            tabellen_dict_by_table,
            leistungskatalog_dict,
            lang,
            pauschalen_dict=pauschalen_dict,
            prepared_structures=prepared_structures,
        )
        bedingungs_pruef_html_result = condition_result_html_dict.get("html", "<p class='error'>Fehler bei HTML-Generierung der Bedingungen.</p>")
        # Errors from check_pauschale_conditions itself (if any were designed to be returned, currently it's an empty list)
        condition_errors_html_gen.extend(condition_result_html_dict.get("errors", []))
        
        # Also generate structured conditions for the selected candidate (was skipped in loop)
        structured_cond_result = check_pauschale_conditions_structured(
            best_pauschale_code,
            context,
            pauschale_bedingungen_data,
            tabellen_dict_by_table,
            lang,
            pauschalen_dict=pauschalen_dict,
            prepared_structures=prepared_structures,
        )
        # Update the selected candidate info in evaluated_candidates list so it has the details
        # This is important if we return the full list of evaluated candidates
        for cand in evaluated_candidates:
            if cand['code'] == best_pauschale_code:
                cand['bedingungs_pruef_html'] = bedingungs_pruef_html_result
                cand['conditions_structured'] = structured_cond_result
                break
                
    except Exception as e_html_gen:
        logger.error(
            "FEHLER bei Aufruf von check_pauschale_conditions (HTML-Generierung) für %s: %s",
            best_pauschale_code,
            e_html_gen,
        )
        traceback.print_exc()
        bedingungs_pruef_html_result = (
            f"<p class='error'>Schwerwiegender Fehler bei HTML-Generierung der Bedingungen: {escape(str(e_html_gen))}</p>"
        )
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
        sources = cand_eval.get("lkn_match_sources") or []
        
        # Strikte LKN-basierte Filterung: Eine Pauschale wird in der Erklärung nur
        # angezeigt, wenn sie mindestens einen relevanten LKN-Bezug zum Kontext hat.
        # Kandidaten ohne LKN-Quellen (z.B. nur durch semantische Suche gefunden)
        # werden somit ausgeblendet.
        
        # Prüfen, ob es überhaupt LKN-Quellen gibt.
        if not sources:
            continue

        # Prüfen, ob mindestens eine dieser Quellen als "relevant" gilt.
        found_relevant_source = False
        for source in sources:
            if source['source'] == 'direct':
                lkn = source['lkn']
                tables_for_lkn = _get_tables_for_context_lkn(lkn)
                # Ein direkter Treffer ist relevant, wenn die LKN in keiner Tabelle ist
                # oder in mindestens einer NICHT ausgeschlossenen Tabelle vorkommt.
                if not tables_for_lkn or (tables_for_lkn - excluded_lkn_tables):
                    found_relevant_source = True
                    break
            elif source['source'] == 'table':
                # Ein Tabellen-Treffer ist relevant, wenn die Tabelle nicht ausgeschlossen ist.
                if source['table'] and source['table'].lower() not in excluded_lkn_tables:
                    found_relevant_source = True
                    break
        
        # Wenn nach Prüfung aller Quellen keine relevante gefunden wurde, überspringen.
        if not found_relevant_source:
            # Ausnahme: C9x-Pauschalen (Fallbacks) werden nie aufgrund von LKN-Irrelevanz ausgeblendet.
            if not is_pauschale_code_ge_c90(cand_eval.get('code')):
                continue

        # Alte Logik (jetzt ersetzt durch die obige, explizitere Prüfung)
        all_sources_are_irrelevant = not found_relevant_source

        # C9x Pauschalen sind generische Fallbacks und sollten nie ausgefiltert werden.
        if is_pauschale_code_ge_c90(cand_eval.get('code')):
            all_sources_are_irrelevant = False
            
        if all_sources_are_irrelevant:
            continue

        if cand_eval['is_valid_structured']:
            status = translate('conditions_met', lang)
            status_class = "condition-status condition-status-positive"
        else:
            status = translate('conditions_not_met', lang)
            status_class = "condition-status condition-status-negative"
        status_text = f"<span class=\"{status_class}\">{status}</span>"
        code_str = escape(cand_eval['code'])
        link = (
            f"<a href='#' class='pauschale-exp-link info-link tag-code' "
            f"data-code='{code_str}'>{code_str}</a>"
        )
        pauschale_erklaerung_html += (
            f"<li><b>{link}</b> "
            f"{escape(get_lang_field(cand_eval['details'], PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, lang) or 'N/A')} "
            f"{status_text}</li>"
        )
    pauschale_erklaerung_html += "</ul>"

    best_code_safe = escape(str(best_pauschale_code))
    best_code_link = (
        f"<a href='#' class='pauschale-exp-link info-link tag-code' "
        f"data-code='{best_code_safe}'>{best_code_safe}</a>"
    )
    best_desc_safe = escape(get_lang_field(best_pauschale_details, PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN, lang) or 'N/A')

    
    if lang == 'fr':
        pauschale_erklaerung_html += (
            f"<p><b>Choix : {best_code_link}</b> "
            f"({best_desc_safe}) - "
            "comme forfait avec la lettre suffixe la plus basse (p. ex. A avant B) parmi les candidats valides "
            "de la catégorie privilégiée (forfaits spécifiques avant forfaits de secours C9x).</p>"
        )
    elif lang == 'it':
        pauschale_erklaerung_html += (
            f"<p><b>Selezionato: {best_code_link}</b> "
            f"({best_desc_safe}) - "
            "come forfait con la lettera suffisso più bassa (es. A prima di B) tra i candidati validi "
            "della categoria preferita (forfait specifici prima dei forfait di fallback C9x).</p>"
        )
    else:
        pauschale_erklaerung_html += (
            f"<p><b>Ausgewählt wurde: {best_code_link}</b> "
            f"({best_desc_safe}) - "
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
                    status_class = "condition-status condition-status-positive"
                else:
                    status = translate('conditions_not_met', lang)
                    status_class = "condition-status condition-status-negative"
                validity_info_html = f"<span class=\"{status_class}\">{status}</span>"

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

    # Try to attach structured conditions for the selected Pauschale, if available
    selected_structured = None
    try:
        if selected_candidate_info:
            selected_structured = check_pauschale_conditions_structured(
                str(selected_candidate_info['code']),
                context,
                pauschale_bedingungen_data,
                tabellen_dict_by_table,
                lang,
                pauschalen_dict=pauschalen_dict,
                prepared_structures=prepared_structures,
            )
    except Exception:
        selected_structured = None

    # HTML für nicht ausgewählte Kandidaten wird nicht mehr vorab erzeugt.
    # Die UI rendert die Bedingungen bei Bedarf über /api/pauschale-conditions-html,
    # sodass alle Pauschalen denselben on-demand Pfad nutzen.
    for cand in evaluated_candidates:
        code_str = str(cand.get("code"))

        if code_str != str(best_pauschale_code):
            continue

        if selected_structured:
            cand["conditions_structured"] = selected_structured
        if not cand.get("bedingungs_pruef_html") and bedingungs_pruef_html_result:
            cand["bedingungs_pruef_html"] = bedingungs_pruef_html_result
        break

    # Die Logik zur Filterung der `evaluated_pauschalen` wurde entfernt, da die Unit-Tests
    # erwarten, die vollständige, ungefilterte Liste zu erhalten, um das Verhalten
    # der Evaluierungslogik zu verifizieren. Die Filterung für die UI kann im Frontend
    # oder in einer dedizierten API-Wrapper-Funktion erfolgen.
    final_result_dict = {
        "type": "Pauschale",
        "details": best_pauschale_details,
        "bedingungs_pruef_html": bedingungs_pruef_html_result,
        "bedingungs_fehler": condition_errors_html_gen, # Fehler aus der HTML-Generierung
        "conditions_met": True, # Da wir hier nur landen, wenn eine Pauschale als gültig ausgewählt wurde
        "evaluated_pauschalen": evaluated_candidates,
        "conditions_structured": selected_structured,
    }
    return final_result_dict


# --- HILFSFUNKTIONEN (auf Modulebene) ---
def get_simplified_conditions(
    pauschale_code: str,
    bedingungen_data: list[dict[str, Any]],
) -> set[tuple[Any, Any]]:
    """
    Wandelt Bedingungen in eine vereinfachte, vergleichbare Darstellung (Set von Tupeln) um.
    Dies dient dazu, Unterschiede zwischen Pauschalen auf einer höheren Ebene zu identifizieren.
    Die Logik hier muss nicht alle Details der `check_single_condition` abbilden,
    sondern eher die Art und den Hauptwert der Bedingung.
    """
    simplified_set: set[tuple[Any, Any]] = set()
    PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp'; BED_WERTE_KEY = 'Werte'
    BED_FELD_KEY = 'Feld'; BED_MIN_KEY = 'MinWert'; BED_MAX_KEY = 'MaxWert'
    BED_VERGLEICHSOP_KEY = 'Vergleichsoperator' # Hinzugefügt
    
    pauschale_conditions = [cond for cond in bedingungen_data if cond.get(PAUSCHALE_KEY) == pauschale_code]

    for cond in pauschale_conditions:
        typ_original = cond.get(BED_TYP_KEY, "").upper()
        wert = str(cond.get(BED_WERTE_KEY, "")).strip() # String und strip
        feld = str(cond.get(BED_FELD_KEY, "")).strip()
        vergleichsop = str(cond.get(BED_VERGLEICHSOP_KEY, "=")).strip() # Default '='
        
        condition_tuple: Optional[tuple[Any, Any]] = None
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
            final_cond_type_for_comparison = 'MEDICATION_LIST'
            condition_tuple = (final_cond_type_for_comparison, tuple(sorted([med.strip().upper() for med in wert.split(',') if med.strip()])))
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
        elif typ_original == "ALTER IN JAHREN BEI EINTRITT":
            final_cond_type_for_comparison = 'PATIENT_ALTER_EINTRITT'
            condition_tuple = (final_cond_type_for_comparison, f"{vergleichsop}{wert}")
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


@with_table_content_cache
def generate_condition_detail_html(
    condition_tuple: tuple[Any, Any],
    leistungskatalog_dict: Dict[str, Dict[str, Any]], # Für LKN-Beschreibungen
    tabellen_dict_by_table: Dict[str, List[Dict[str, Any]]],  # Für Tabelleninhalte und ICD-Beschreibungen
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
        
        elif cond_type_comp == 'MEDICATION_LIST':
            condition_html += translate('require_medication_list', lang)
            if not cond_value_comp: condition_html += f"<i>{translate('no_medications_spec', lang)}</i>"
            else: condition_html += html.escape(", ".join(cond_value_comp))
        
        elif cond_type_comp.startswith('PATIENT_'):
            feld_name_raw = cond_type_comp.split('_', 1)[1]
            feld_name = feld_name_raw.replace('_', ' ').capitalize()
            condition_html += translate(
                'patient_condition',
                lang,
                field=html.escape(feld_name),
                value=html.escape(str(cond_value_comp)),
            )
        
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
        logger.error(
            "FEHLER beim Erstellen der Detailansicht für Vergleichs-Bedingung '%s': %s",
            condition_tuple,
            e_detail_gen,
        )
        traceback.print_exc()
        condition_html += f"<i>Fehler bei Detailgenerierung: {html.escape(str(e_detail_gen))}</i>"
    
    condition_html += "</li>"
    return condition_html
