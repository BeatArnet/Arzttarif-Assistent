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
from functools import lru_cache
from typing import Dict, List, Any, Set, Optional, Tuple
from collections import defaultdict
from utils import escape, get_table_content, get_lang_field, translate, translate_condition_type, create_html_info_link
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
    # _evaluate_boolean_tokens and evaluate_single_condition_group are internal
]

# Standardoperator zur Verknüpfung der Bedingungsgruppen. (Wird für Funktions-Defaults benötigt)
# "UND" ist der konservative Default und kann zentral angepasst werden.
DEFAULT_GROUP_OPERATOR = "UND"


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

def pauschale_requires_icd(
    pauschale_code: str,
    pauschale_bedingungen_data: List[Dict[str, Any]],
    pauschalen_dict: Optional[Dict[str, Dict[str, Any]]] | None = None,
) -> bool:
    """Return True if the Pauschale has ICD-triggered requirements."""
    for cond in pauschale_bedingungen_data:
        if cond.get('Pauschale') != pauschale_code:
            continue
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


def count_matching_lkn_codes(
    pauschale_code: str,
    context: Dict[str, Any],
    pauschale_bedingungen_data: List[Dict[str, Any]],
    tabellen_dict_by_table: Dict[str, List[Dict]],
) -> int:
    """Return how many distinct context LKN codes satisfy LKN conditions for the Pauschale."""
    provided_lkns = {str(lkn).upper() for lkn in context.get('LKN', []) if lkn}
    if not provided_lkns:
        return 0
    matches: set[str] = set()
    for cond in pauschale_bedingungen_data:
        if cond.get('Pauschale') != pauschale_code:
            continue
        cond_type = str(cond.get('Bedingungstyp', '')).upper()
        if cond_type in LKN_LIST_CONDITION_TYPES:
            values = {item.strip().upper() for item in str(cond.get('Werte', '')).split(',') if item.strip()}
            matches.update(provided_lkns.intersection(values))
        elif cond_type in LKN_TABLE_CONDITION_TYPES:
            table_ref = str(cond.get('Werte', '')).strip()
            if not table_ref:
                continue
            entries = get_table_content(table_ref, 'service_catalog', tabellen_dict_by_table)
            table_codes = {str(entry.get('Code', '')).upper() for entry in entries if entry.get('Code')}
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


def _evaluate_simple_condition(condition_text: str, context: Dict, tabellen_dict_by_table: Dict[str, List[Dict]]) -> bool:
    text_lower = condition_text.strip().lower()
    if text_lower.startswith('anzahl'):
        operator, value = _parse_comparison(condition_text[len('Anzahl'):])
        cond = {'Bedingungstyp': 'ANZAHL', 'Vergleichsoperator': operator, 'Werte': value}
        return bool(check_single_condition(cond, context, tabellen_dict_by_table))
    if text_lower.startswith('seitigkeit'):
        operator, value = _parse_comparison(condition_text[len('Seitigkeit'):])
        cond = {'Bedingungstyp': 'SEITIGKEIT', 'Vergleichsoperator': operator, 'Werte': value}
        return bool(check_single_condition(cond, context, tabellen_dict_by_table))
    if text_lower.startswith('alter in jahren bei eintritt'):
        operator, value = _parse_comparison(condition_text[len('Alter in Jahren bei Eintritt'):])
        cond = {'Bedingungstyp': 'ALTER IN JAHREN BEI EINTRITT', 'Vergleichsoperator': operator, 'Werte': value}
        return bool(check_single_condition(cond, context, tabellen_dict_by_table))
    if text_lower.startswith('geschlecht in liste'):
        return bool(_evaluate_condition_text(condition_text, context, tabellen_dict_by_table))
    raise ValueError(f"Unsupported WHERE condition fragment '{condition_text}'.")


def _evaluate_where_clause(where_text: str, context: Dict, tabellen_dict_by_table: Dict[str, List[Dict]]) -> bool:
    clause = _strip_surrounding_parentheses(where_text.strip())
    if not clause:
        return True

    simple_results: List[bool] = []

    def _replace(match: re.Match) -> str:
        idx = len(simple_results)
        fragment = match.group(0)
        simple_results.append(_evaluate_simple_condition(fragment, context, tabellen_dict_by_table))
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


def _evaluate_condition_text(condition_text: str, context: Dict, tabellen_dict_by_table: Dict[str, List[Dict]]) -> bool:
    text = _strip_surrounding_parentheses(condition_text.strip())
    where_match = re.search(r'\swhere\s', text, flags=re.IGNORECASE)
    if where_match:
        base_text = text[:where_match.start()].strip()
        where_clause = text[where_match.end():].strip()
        return _evaluate_condition_text(base_text, context, tabellen_dict_by_table) and _evaluate_where_clause(where_clause, context, tabellen_dict_by_table)

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
    return bool(check_single_condition(cond, context, tabellen_dict_by_table))


def _evaluate_prueflogik_expression(
    prueflogik_expr: str,
    context: Dict,
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
            result = _evaluate_simple_condition(fragment_clean, context, tabellen_dict_by_table)
        elif fragment_lower.replace(' ', '') == '1=1':
            result = True
        else:
            result = _evaluate_condition_text(fragment_clean, context, tabellen_dict_by_table)

        values.append(bool(result))
        return f'__COND{idx}__'

    token_expr = CONDITION_PATTERN.sub(_replace, prueflogik_expr)
    if not values:
        raise ValueError("Keine Bedingungen aus der Pr\u00fcflogik extrahiert.")

    expr_python = _normalize_logical_operators(token_expr)
    env = {f'__COND{i}__': value for i, value in enumerate(values)}
    return bool(eval(expr_python, {'__builtins__': None}, env))


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
    provided_medications_upper = {str(m).upper() for m in context.get("Medikamente", []) if m}
    if not provided_medications_upper:
        provided_medications_upper = {str(m).upper() for m in context.get("GTIN", []) if m}
    provided_lkns_upper = {p_lkn.upper() for p_lkn in context.get("LKN", []) if p_lkn}
    provided_alter = context.get("Alter")
    provided_geschlecht_str = str(context.get("Geschlecht", "unbekannt")).lower() # Default 'unbekannt' und lower
    provided_anzahl = context.get("Anzahl") # Aus dem Kontext für "ANZAHL" Typ
    provided_seitigkeit_str = str(context.get("Seitigkeit", "unbekannt")).lower() # Default 'unbekannt' und lower

    # print(f"--- DEBUG check_single --- P: {pauschale_code_for_debug} G: {gruppe_for_debug} Typ: {bedingungstyp}, Regel-Werte: '{werte_str}', Kontext: {context.get('Seitigkeit', 'N/A')}/{context.get('Anzahl', 'N/A')}")

    try:
        if bedingungstyp == "ICD": # ICD IN LISTE
            if not check_icd_conditions_at_all: return True
            required_icds_in_rule_list = {w.strip().upper() for w in str(werte_str).split(',') if w.strip()}
            if not required_icds_in_rule_list: return True # Leere Regel-Liste ist immer erfüllt
            return any(req_icd in provided_icds_upper for req_icd in required_icds_in_rule_list)

        elif bedingungstyp == "HAUPTDIAGNOSE IN TABELLE": # ICD IN TABELLE
            if not check_icd_conditions_at_all: return True
            table_ref = werte_str
            icd_codes_in_rule_table = {entry['Code'].upper() for entry in get_table_content(table_ref, "icd", tabellen_dict_by_table) if entry.get('Code')}
            extra_codes = DIAGNOSIS_TABLE_EXTRA_CODES.get(str(table_ref).upper())
            if extra_codes:
                icd_codes_in_rule_table.update(code.upper() for code in extra_codes)
            if not icd_codes_in_rule_table: # Wenn Tabelle leer oder nicht gefunden
                 return False if provided_icds_upper else True # Nur erfüllt, wenn auch keine ICDs im Kontext sind
            return any(provided_icd in icd_codes_in_rule_table for provided_icd in provided_icds_upper)

        elif bedingungstyp in ("GTIN", "MEDIKAMENTE IN LISTE"):
            werte_list_med = [w.strip().upper() for w in str(werte_str).split(',') if w.strip()]
            if not werte_list_med: return True
            return any(req_med in provided_medications_upper for req_med in werte_list_med)

        elif bedingungstyp == "LKN" or bedingungstyp == "LEISTUNGSPOSITIONEN IN LISTE":
            werte_list_upper_lkn = [w.strip().upper() for w in str(werte_str).split(',') if w.strip()]
            if not werte_list_upper_lkn: return True
            return any(req_lkn in provided_lkns_upper for req_lkn in werte_list_upper_lkn)

        elif bedingungstyp == "GESCHLECHT IN LISTE": # Z.B. Werte: "Männlich,Weiblich"
            if werte_str: # Nur prüfen, wenn Regel einen Wert hat
                geschlechter_in_regel_lower = {g.strip().lower() for g in str(werte_str).split(',') if g.strip()}
                return provided_geschlecht_str in geschlechter_in_regel_lower
            return True # Wenn Regel keinen Wert hat, ist es für jedes Geschlecht ok

        elif bedingungstyp == "LEISTUNGSPOSITIONEN IN TABELLE" or bedingungstyp == "TARIFPOSITIONEN IN TABELLE" or bedingungstyp == "LKN IN TABELLE":
            table_ref = werte_str
            if not table_ref:
                return False

            if bedingungstyp == "TARIFPOSITIONEN IN TABELLE":
                table_type = "tariff"
                provided_codes = provided_medications_upper
            else:
                table_type = "service_catalog"
                provided_codes = provided_lkns_upper

            table_entries = get_table_content(table_ref, table_type, tabellen_dict_by_table)
            table_codes = {
                str(entry.get('Code', '')).upper()
                for entry in table_entries
                if entry.get('Code')
            }
            if not table_codes:
                return False
            return any(code in table_codes for code in provided_codes)

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
            alter_eintritt = context.get("AlterBeiEintritt")
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
    conditions_in_group: List[Dict],
    context: Dict,
    tabellen_dict_by_table: Dict[str, List[Dict]],
    pauschale_code_for_debug: str = "N/A_PAUSCHALE", # For logging
    group_id_for_debug: Any = "N/A_GRUPPE",      # For logging
    debug: bool = False
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

    diagnostic_types = {"HAUPTDIAGNOSE IN TABELLE", "HAUPTDIAGNOSE IN LISTE", "ICD", "ICD IN TABELLE", "ICD IN LISTE"}
    use_icd_flag = context.get('useIcd', True)
    group_has_non_diag = any(str(cond.get('Bedingungstyp', '')).upper() not in diagnostic_types for cond in conditions_in_group)

    baseline_level_group = 1
    first_level_group = conditions_in_group[0].get('Ebene', 1)
    if first_level_group < baseline_level_group:
        first_level_group = baseline_level_group

    first_res_group = check_single_condition(
        conditions_in_group[0], context, tabellen_dict_by_table
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

        cur_res_group = check_single_condition(cond_grp, context, tabellen_dict_by_table)
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
        provided_icds = [icd for icd in context.get('ICD', []) if icd]
        if not provided_icds:
            return False
    return calculated_result


# === FUNKTION ZUR AUSWERTUNG DER STRUKTURIERTEN LOGIK (UND/ODER) ===
# This function is now the new orchestrator for pauschale logic evaluation.

def _evaluate_pauschale_logic_via_ast(
    pauschale_code: str,
    context: Dict,
    all_pauschale_bedingungen_data: List[Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    debug: bool = False,
) -> bool:
    def _condition_sort_key(cond: Dict[str, Any]) -> tuple[Any, Any, Any]:
        return (
            cond.get("GruppeSortIndex", cond.get("Gruppe", 0)),
            cond.get("BedingungSortIndex", cond.get("BedingungsID", 0)),
            cond.get("BedingungsID", 0),
        )

    conditions_for_pauschale = sorted(
        [cond for cond in all_pauschale_bedingungen_data if cond.get("Pauschale") == pauschale_code],
        key=_condition_sort_key
    )

    if not conditions_for_pauschale:
        if debug:
            logger.info("DEBUG Orchestrator Pauschale %s: No conditions defined. Result: True", pauschale_code)
        return True

    def _normalize_group_id(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            string_value = str(value).strip()
            return string_value if string_value else None

    def _normalize_operator(value: Any) -> str:
        if value is None:
            return "OR"
        value_upper = str(value).strip().upper()
        if value_upper in ("UND", "AND"):
            return "AND"
        if value_upper in ("ODER", "OR"):
            return "OR"
        logger.warning(
            "WARNUNG Orchestrator Pauschale %s: Unexpected operator '%s'. Defaulting to OR.",
            pauschale_code,
            value,
        )
        return "OR"

    def _sort_key(value: Any) -> tuple[int, str]:
        if isinstance(value, int):
            return (0, str(value))
        return (1, str(value))

    group_conditions_map: defaultdict[Any, List[Dict]] = defaultdict(list)
    group_meta: Dict[Any, Dict[str, Any]] = {}
    ast_entries: List[Dict] = []
    synthetic_group_counter = 0

    for cond in conditions_for_pauschale:
        cond_type_upper = str(cond.get("Bedingungstyp", "")).upper()
        if cond_type_upper == "AST VERBINDUNGSOPERATOR":
            ast_entries.append(cond)
            continue

        group_id_raw = cond.get("Gruppe")
        group_id_normalized = _normalize_group_id(group_id_raw)
        if group_id_normalized is None:
            group_id_normalized = f"__synthetic__{synthetic_group_counter}"
            synthetic_group_counter += 1
        group_conditions_map[group_id_normalized].append(cond)
        meta = group_meta.setdefault(group_id_normalized, {})
        meta.setdefault("GroupNegated", bool(cond.get("GroupNegated")))
        if "ParentGroup" not in meta:
            meta["ParentGroup"] = _normalize_group_id(cond.get("ParentGroup"))
        if "GroupOperator" not in meta:
            meta["GroupOperator"] = _normalize_operator(cond.get("GruppenOperator"))
        if "GruppeSortIndex" not in meta and "GruppeSortIndex" in cond:
            meta["GruppeSortIndex"] = cond.get("GruppeSortIndex")

    group_results: Dict[Any, bool] = {}
    for group_id, conds_in_group in group_conditions_map.items():
        result_group = evaluate_single_condition_group(
            conds_in_group,
            context,
            tabellen_dict_by_table,
            pauschale_code,
            conds_in_group[0].get("Gruppe", group_id),
            debug,
        )
        if group_meta.get(group_id, {}).get("GroupNegated"):
            result_group = not result_group
        group_results[group_id] = bool(result_group)

    if not ast_entries:
        if not group_results:
            if debug:
                logger.info("DEBUG Orchestrator Pauschale %s: No evaluable groups. Result: True", pauschale_code)
            return True

        default_operator = DEFAULT_GROUP_OPERATOR.upper()
        final_without_ast = None
        for group_id in sorted(group_results.keys(), key=_sort_key):
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

    for ast_cond in ast_entries:
        parent_id = _normalize_group_id(ast_cond.get("Gruppe"))
        child_id = _normalize_group_id(ast_cond.get("Spezialbedingung") or ast_cond.get("Werte"))
        operator_normalized = _normalize_operator(ast_cond.get("Operator"))
        entry = {
            "child": child_id,
            "operator": operator_normalized,
            "bed_id": ast_cond.get("BedingungsID", 0),
        }
        children_map[parent_id].append(entry)
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
        root_candidates = sorted(parent_nodes, key=_sort_key)
    else:
        root_candidates = sorted(root_candidates, key=_sort_key)

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

    for unused_group in sorted(unused_groups, key=_sort_key):
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
    context: Dict,
    all_pauschale_bedingungen_data: List[Dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    pauschalen_dict: Optional[Dict[str, Dict]] = None,
    debug: bool = False
) -> bool:
    prueflogik_expr = None
    if pauschalen_dict:
        pauschale_details = pauschalen_dict.get(pauschale_code)
        if pauschale_details:
            prueflogik_expr = pauschale_details.get('Pr\u00fcflogik')
    if prueflogik_expr:
        try:
            return _evaluate_prueflogik_expression(prueflogik_expr, context, tabellen_dict_by_table, pauschale_code, debug)
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
    )


# === PRUEFUNG DER BEDINGUNGEN (STRUKTURIERTES RESULTAT) ===
def check_pauschale_conditions(
    pauschale_code: str,
    context: dict,
    pauschale_bedingungen_data: list[dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    leistungskatalog_dict: Dict[str, Dict[str, Any]],
    lang: str = "de",
    pauschalen_dict: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Prueft alle Bedingungen einer Pauschale und generiert strukturiertes HTML,
    inklusive Inter- und Intra-Gruppen-Operatoren und korrekter Übersetzung für Gruppentitel.
    """
    PAUSCHALE_KEY = "Pauschale"
    BED_TYP_KEY = "Bedingungstyp"
    BED_ID_KEY = "BedingungsID"
    GRUPPE_KEY = "Gruppe"
    OPERATOR_KEY = "Operator"
    BED_WERTE_KEY = "Werte"
    BED_FELD_KEY = "Feld"
    BED_MIN_KEY = "MinWert"
    BED_MAX_KEY = "MaxWert"
    BED_VERGLEICHSOP_KEY = "Vergleichsoperator"

    def _normalize_group_id(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            string_value = str(value).strip()
            return string_value if string_value else None

    def _condition_sort_key(cond: Dict[str, Any]) -> tuple[Any, Any, Any]:
        return (
            cond.get("GruppeSortIndex", cond.get(GRUPPE_KEY, 0)),
            cond.get("BedingungSortIndex", cond.get(BED_ID_KEY, 0)),
            cond.get(BED_ID_KEY, 0),
        )

    all_conditions_for_pauschale_sorted_by_id = sorted(
        [c for c in pauschale_bedingungen_data if c.get(PAUSCHALE_KEY) == pauschale_code],
        key=_condition_sort_key
    )

    prueflogik_expr: Optional[str] = None
    prueflogik_pretty: str = ""
    if pauschalen_dict:
        prueflogik_raw = pauschalen_dict.get(pauschale_code, {}).get('Pr\u00fcflogik')
        if isinstance(prueflogik_raw, str) and prueflogik_raw.strip():
            prueflogik_expr = prueflogik_raw.strip()
            prueflogik_pretty = _format_prueflogik_for_display(prueflogik_expr, lang)
    group_logic_terms = _extract_group_logic_terms(pauschale_code, prueflogik_expr, pauschale_bedingungen_data)

    def _render_prueflogik_header() -> str:
        label = translate('prueflogik_header', lang)
        return f"<div class=\"condition-prueflogik\"><strong>{escape(label)}</strong></div>"

    if not any(str(c.get(BED_TYP_KEY, "")).upper() != "AST VERBINDUNGSOPERATOR" for c in all_conditions_for_pauschale_sorted_by_id):
        html_snippets: list[str] = []
        if prueflogik_expr:
            html_snippets.append(_render_prueflogik_header())
        html_snippets.append(f"<p><i>{translate('no_conditions_for_pauschale', lang)}</i></p>")
        return {
            "html": "".join(html_snippets),
            "errors": [],
            "trigger_lkn_condition_met": False,
            "prueflogik_expr": prueflogik_expr,
            "prueflogik_pretty": prueflogik_pretty,
            "group_logic_terms": group_logic_terms,
        }

    html_parts = []
    current_display_group_id = None
    last_processed_actual_condition = None
    trigger_lkn_condition_overall_met = False
    group_negated_map: Dict[Any, bool] = {}
    for _cond in all_conditions_for_pauschale_sorted_by_id:
        if str(_cond.get(BED_TYP_KEY, "")).upper() == "AST VERBINDUNGSOPERATOR":
            continue
        gid_norm = _normalize_group_id(_cond.get(GRUPPE_KEY))
        if gid_norm not in group_negated_map:
            group_negated_map[gid_norm] = bool(_cond.get("GroupNegated"))

    pending_operator_by_group: Dict[Any, str] = {}
    for _cond in all_conditions_for_pauschale_sorted_by_id:
        if str(_cond.get(BED_TYP_KEY, "")).upper() == "AST VERBINDUNGSOPERATOR":
            child_raw = _cond.get('Spezialbedingung') or _cond.get(BED_WERTE_KEY)
            child_group_id = _normalize_group_id(child_raw)
            op_val = str(_cond.get(OPERATOR_KEY, "ODER")).upper()
            translated = ''
            if op_val == "ODER":
                translated = translate('OR', lang)
            elif op_val == "UND":
                translated = translate('AND', lang)
            if child_group_id is not None and translated:
                pending_operator_by_group[child_group_id] = translated

    if prueflogik_expr:
        html_parts.append(_render_prueflogik_header())

    for idx, cond_data in enumerate(all_conditions_for_pauschale_sorted_by_id):
        condition_type_upper = str(cond_data.get(BED_TYP_KEY, "")).upper()

        if condition_type_upper == "AST VERBINDUNGSOPERATOR":
            if current_display_group_id is not None:
                html_parts.append("</div>")
                current_display_group_id = None
                last_processed_actual_condition = None
            continue

        else:
            actual_cond_group_id = cond_data.get(GRUPPE_KEY)

            if actual_cond_group_id != current_display_group_id:
                # Close the previous group div if it exists
                if current_display_group_id is not None:
                    html_parts.append("</div>")

                # Logic to add the operator between groups
                operator_for_group = pending_operator_by_group.pop(_normalize_group_id(actual_cond_group_id), None)
                if operator_for_group:
                    html_parts.append(f"<div class=\"condition-separator inter-group-operator\">{operator_for_group}</div>")
                elif last_processed_actual_condition:
                    previous_condition_index = idx - 1
                    if previous_condition_index >= 0:
                        prev_cond_data = all_conditions_for_pauschale_sorted_by_id[previous_condition_index]
                        if str(prev_cond_data.get(BED_TYP_KEY, "")).upper() != "AST VERBINDUNGSOPERATOR":
                            inter_group_op_val = str(last_processed_actual_condition.get(OPERATOR_KEY, "UND")).upper()
                            translated_inter_group_op = ""
                            if inter_group_op_val == "ODER":
                                translated_inter_group_op = translate('OR', lang)
                            elif inter_group_op_val == "UND":
                                translated_inter_group_op = translate('AND', lang)

                            if translated_inter_group_op:
                                html_parts.append(f"<div class=\"condition-separator inter-group-operator\">{translated_inter_group_op}</div>")

                # Start the new group
                current_display_group_id = actual_cond_group_id
                normalized_group_id = _normalize_group_id(actual_cond_group_id)
                negated_flag = group_negated_map.get(normalized_group_id, False)
                group_title = f"{translate('condition_group', lang)} {escape(str(current_display_group_id))}"
                group_class = "condition-group condition-group-negated" if negated_flag else "condition-group"
                html_parts.append(f"<div class=\"{group_class}\"><div class=\"condition-group-title\">{group_title}</div>")
                last_processed_actual_condition = None # Reset for the new group

            elif last_processed_actual_condition and \
                 last_processed_actual_condition.get(GRUPPE_KEY) == current_display_group_id:
                # This is for the operator *within* a group (intra-group)
                linking_op_val = str(last_processed_actual_condition.get(OPERATOR_KEY, "UND")).upper()
                translated_linking_op = ""
                if linking_op_val == "ODER":
                    translated_linking_op = translate('OR', lang)
                elif linking_op_val == "UND":
                    translated_linking_op = translate('AND', lang)

                if translated_linking_op:
                    html_parts.append(f"<div class=\"condition-separator intra-group-operator\">{translated_linking_op}</div>")

            condition_met = check_single_condition(cond_data, context, tabellen_dict_by_table)

            current_cond_data_type_upper = str(cond_data.get(BED_TYP_KEY, "")).upper()
            if condition_met and current_cond_data_type_upper in [
                "LEISTUNGSPOSITIONEN IN LISTE", "LKN",
                "LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE"
            ]:
                trigger_lkn_condition_overall_met = True

            icon_svg_path = "#icon-check" if condition_met else "#icon-cross"
            icon_class = "condition-icon-fulfilled" if condition_met else "condition-icon-not-fulfilled"
            translated_cond_type_display = translate_condition_type(cond_data.get(BED_TYP_KEY, "N/A"), lang)

            original_werte = str(cond_data.get(BED_WERTE_KEY, ""))
            werte_display = ""

            active_condition_type_for_display = current_cond_data_type_upper

            if active_condition_type_for_display in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN", "LKN IN LISTE"]:
                lkn_codes = [l.strip().upper() for l in original_werte.split(',') if l.strip()]
                if lkn_codes:
                    linked_lkn_parts = []
                    for lkn_c in lkn_codes:
                        desc = get_beschreibung_fuer_lkn_im_backend(lkn_c, leistungskatalog_dict, lang)
                        display_text = escape(f"{lkn_c} ({desc})")
                        linked_lkn_parts.append(create_html_info_link(lkn_c, "lkn", display_text))
                    werte_display = translate('condition_text_lkn_list', lang, linked_codes=", ".join(linked_lkn_parts))
                else:
                    werte_display = f"<i>{translate('no_lkns_spec', lang)}</i>"

            elif active_condition_type_for_display in ["LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE", "LKN IN TABELLE"]:
                table_names_orig = [t.strip() for t in original_werte.split(',') if t.strip()]
                if table_names_orig:
                    linked_table_names = []
                    for tn in table_names_orig:
                        table_content = get_table_content(tn, "service_catalog", tabellen_dict_by_table, lang)
                        table_content_json = json.dumps(table_content)
                        linked_table_names.append(create_html_info_link(tn, "lkn_table", escape(tn), data_content=table_content_json))
                    werte_display = translate('condition_text_lkn_table', lang, table_names=", ".join(linked_table_names))
                else:
                    werte_display = f"<i>{translate('no_table_name', lang)}</i>"

            elif active_condition_type_for_display in ["HAUPTDIAGNOSE IN TABELLE", "ICD IN TABELLE"]:
                table_names_icd = [t.strip() for t in original_werte.split(',') if t.strip()]
                if table_names_icd:
                    linked_table_names_icd = []
                    for tn in table_names_icd:
                        table_content = get_table_content(tn, "icd", tabellen_dict_by_table, lang)
                        table_content_json = json.dumps(table_content)
                        linked_table_names_icd.append(create_html_info_link(tn, "icd_table", escape(tn), data_content=table_content_json))
                    werte_display = translate('condition_text_icd_table', lang, table_names=", ".join(linked_table_names_icd))
                else:
                    werte_display = f"<i>{translate('no_table_name', lang)}</i>"

            elif active_condition_type_for_display in ["ICD", "HAUPTDIAGNOSE IN LISTE", "ICD IN LISTE"]:
                icd_codes_list = [icd.strip().upper() for icd in original_werte.split(',') if icd.strip()]
                if icd_codes_list:
                    linked_icd_parts = []
                    for icd_c in icd_codes_list:
                        desc_icd = get_beschreibung_fuer_icd_im_backend(icd_c, tabellen_dict_by_table, lang=lang)
                        display_text = escape(f"{icd_c} ({desc_icd})")
                        linked_icd_parts.append(create_html_info_link(icd_c, "diagnosis", display_text))
                    werte_display = translate('condition_text_icd_list', lang, linked_codes=", ".join(linked_icd_parts))
                else:
                     werte_display = f"<i>{translate('no_icds_spec', lang)}</i>"

            elif active_condition_type_for_display == "PATIENTENBEDINGUNG":
                feld_name_pat_orig = str(cond_data.get(BED_FELD_KEY, ""))
                feld_name_pat_display = translate(feld_name_pat_orig.lower(), lang) if feld_name_pat_orig.lower() in ['alter', 'geschlecht'] else escape(feld_name_pat_orig.capitalize())
                
                min_w_pat = cond_data.get(BED_MIN_KEY)
                max_w_pat = cond_data.get(BED_MAX_KEY)
                expl_wert_pat = cond_data.get(BED_WERTE_KEY)

                # Update translated_cond_type_display for PATIENTENBEDINGUNG to include the field
                translated_cond_type_display = translate('patient_condition_display', lang, field=feld_name_pat_display)

                if feld_name_pat_orig.lower() == "alter":
                    if min_w_pat is not None or max_w_pat is not None:
                        val_disp_parts = []
                        if min_w_pat is not None: val_disp_parts.append(f"{translate('min', lang)} {escape(str(min_w_pat))}")
                        if max_w_pat is not None: val_disp_parts.append(f"{translate('max', lang)} {escape(str(max_w_pat))}")
                        werte_display = " ".join(val_disp_parts)
                    elif expl_wert_pat is not None:
                        werte_display = escape(str(expl_wert_pat))
                    else:
                        werte_display = translate('not_specified', lang)
                elif feld_name_pat_orig.lower() == "geschlecht":
                     werte_display = translate(str(expl_wert_pat).lower(), lang) if expl_wert_pat else translate('not_specified', lang)
                else: # Other patient conditions
                    werte_display = escape(str(expl_wert_pat if expl_wert_pat is not None else translate('not_specified', lang)))

            elif active_condition_type_for_display == "ALTER IN JAHREN BEI EINTRITT":
                op_val = cond_data.get(BED_VERGLEICHSOP_KEY, "=")
                werte_display = f"{escape(op_val)} {escape(original_werte)}"

            elif active_condition_type_for_display == "ANZAHL":
                op_val_anz = cond_data.get(BED_VERGLEICHSOP_KEY, "=")
                werte_display = f"{escape(op_val_anz)} {escape(original_werte)}"

            elif active_condition_type_for_display == "SEITIGKEIT":
                op_val_seit = cond_data.get(BED_VERGLEICHSOP_KEY, "=")
                regel_wert_seit_norm_disp = original_werte.strip().replace("'", "").lower()
                # Translate the seitigkeit value for display
                if regel_wert_seit_norm_disp == 'b': regel_wert_seit_norm_disp = translate('bilateral', lang)
                elif regel_wert_seit_norm_disp == 'e': regel_wert_seit_norm_disp = translate('unilateral', lang)
                elif regel_wert_seit_norm_disp == 'l': regel_wert_seit_norm_disp = translate('left', lang)
                elif regel_wert_seit_norm_disp == 'r': regel_wert_seit_norm_disp = translate('right', lang)
                else: regel_wert_seit_norm_disp = escape(regel_wert_seit_norm_disp) # Escape if not a known key
                werte_display = f"{escape(op_val_seit)} {regel_wert_seit_norm_disp}"

            elif active_condition_type_for_display == "GESCHLECHT IN LISTE":
                gender_list_keys = [g.strip().lower() for g in original_werte.split(',') if g.strip()]
                translated_genders = [translate(g_key, lang) for g_key in gender_list_keys]
                werte_display = escape(", ".join(translated_genders))
            
            elif active_condition_type_for_display == "MEDIKAMENTE IN LISTE":
                med_codes = [med.strip() for med in original_werte.split(',') if med.strip()]
                if med_codes:
                    # Medikamentencodes werden hier lediglich angezeigt.
                    werte_display = escape(", ".join(med_codes))
                else:
                    werte_display = f"<i>{translate('no_medications_spec', lang)}</i>"
            else: # Fallback for any other types
                werte_display = escape(original_werte)

            # Context match information
            context_match_info_html = ""
            if condition_met:
                match_details_parts = []
                # Check for ICD matches (List or Table)
                if active_condition_type_for_display in ["ICD", "HAUPTDIAGNOSE IN LISTE", "ICD IN LISTE", "HAUPTDIAGNOSE IN TABELLE", "ICD IN TABELLE"]:
                    provided_icds_upper = {p_icd.upper() for p_icd in context.get("ICD", []) if p_icd}
                    
                    required_codes_in_rule = set()
                    if "TABELLE" in active_condition_type_for_display:
                        table_ref_icd = cond_data.get(BED_WERTE_KEY)
                        if table_ref_icd and isinstance(table_ref_icd, str): # Check if table_ref_icd is a string and not None
                            for entry in get_table_content(table_ref_icd, "icd", tabellen_dict_by_table, lang): # lang for potential text in table
                                 if entry.get('Code'): required_codes_in_rule.add(entry['Code'].upper())
                        # If table_ref_icd is None or not a string, required_codes_in_rule remains empty for table part
                    else: # LIST type
                        required_codes_in_rule = {w.strip().upper() for w in str(cond_data.get(BED_WERTE_KEY, "")).split(',') if w.strip()}
                    
                    matching_icds = list(provided_icds_upper.intersection(required_codes_in_rule))
                    if matching_icds:
                        linked_matching_icds = []
                        for icd_c_match in sorted(matching_icds):
                            desc_icd_match = get_beschreibung_fuer_icd_im_backend(icd_c_match, tabellen_dict_by_table, lang=lang)
                            display_text_match = escape(f"{icd_c_match} ({desc_icd_match})")
                            linked_matching_icds.append(create_html_info_link(icd_c_match, "diagnosis", display_text_match))
                        if linked_matching_icds:
                             match_details_parts.append(translate('fulfilled_by_icd', lang, icd_code_link=", ".join(linked_matching_icds)))

                # Check for LKN matches (List or Table)
                elif active_condition_type_for_display in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN", "LKN IN LISTE", "LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE", "LKN IN TABELLE"]:
                    provided_lkns_upper = {p_lkn.upper() for p_lkn in context.get("LKN", []) if p_lkn}
                    
                    required_lkn_codes_in_rule = set()
                    if "TABELLE" in active_condition_type_for_display:
                        table_ref_lkn = cond_data.get(BED_WERTE_KEY)
                        if table_ref_lkn and isinstance(table_ref_lkn, str): # Check if table_ref_lkn is a string and not None
                            for entry in get_table_content(table_ref_lkn, "service_catalog", tabellen_dict_by_table, lang): # lang for potential text
                                if entry.get('Code'): required_lkn_codes_in_rule.add(entry['Code'].upper())
                        # If table_ref_lkn is None or not a string, required_lkn_codes_in_rule remains empty for table part
                    else: # LIST type
                        required_lkn_codes_in_rule = {w.strip().upper() for w in str(cond_data.get(BED_WERTE_KEY, "")).split(',') if w.strip()}

                    matching_lkns = list(provided_lkns_upper.intersection(required_lkn_codes_in_rule))
                    if matching_lkns:
                        linked_matching_lkns = []
                        for lkn_c_match in sorted(matching_lkns):
                            desc_lkn_match = get_beschreibung_fuer_lkn_im_backend(lkn_c_match, leistungskatalog_dict, lang)
                            display_text_match = escape(f"{lkn_c_match} ({desc_lkn_match})")
                            linked_matching_lkns.append(create_html_info_link(lkn_c_match, "lkn", display_text_match))
                        if linked_matching_lkns:
                            match_details_parts.append(translate('fulfilled_by_lkn', lang, lkn_code_link=", ".join(linked_matching_lkns)))
                
                # Fallback generic message if no specific details were generated but condition is met
                if not match_details_parts:
                    match_details_parts.append(translate('condition_met_context_generic', lang))
                
                context_match_info_html = f"<span class=\"context-match-info fulfilled\">({'; '.join(match_details_parts)})</span>"


            html_parts.append(f"""
                <div class="condition-item-row">
                    <span class="condition-status-icon {icon_class}">
                        <svg viewBox="0 0 24 24"><use xlink:href="{icon_svg_path}"></use></svg>
                    </span>
                    <span class="condition-type-display">{escape(translated_cond_type_display)}:</span>
                    <span class="condition-text-wrapper">{werte_display} {context_match_info_html}</span>
                </div>
            """)
            last_processed_actual_condition = cond_data

    if current_display_group_id is not None:
        html_parts.append("</div>")

    return {
        "html": "".join(html_parts),
        "errors": [],
        "trigger_lkn_condition_met": trigger_lkn_condition_overall_met,
        "prueflogik_expr": prueflogik_expr,
        "prueflogik_pretty": prueflogik_pretty,
        "group_logic_terms": group_logic_terms,
    }
    """
    Prueft alle Bedingungen einer Pauschale und generiert strukturiertes HTML.
    """
    PAUSCHALE_KEY = "Pauschale"
    BED_TYP_KEY = "Bedingungstyp"
    BED_ID_KEY = "BedingungsID"
    GRUPPE_KEY = "Gruppe"
    OPERATOR_KEY = "Operator" # Für UND/ODER Logik innerhalb der Gruppe
    BED_WERTE_KEY = "Werte"
    BED_FELD_KEY = "Feld"
    BED_MIN_KEY = "MinWert"
    BED_MAX_KEY = "MaxWert"
    BED_VERGLEICHSOP_KEY = "Vergleichsoperator"

    # Get ALL conditions for the pauschale, sorted by BedingungsID for sequential processing
    all_conditions_for_pauschale_sorted = sorted(
        [c for c in pauschale_bedingungen_data if c.get(PAUSCHALE_KEY) == pauschale_code],
        key=lambda x: x.get(BED_ID_KEY, 0)
    )

    if not any(str(c.get(BED_TYP_KEY, "")).upper() != "AST VERBINDUNGSOPERATOR" for c in all_conditions_for_pauschale_sorted):
        html_snippets: list[str] = []
        if prueflogik_expr:
            html_snippets.append(_render_prueflogik_header())
        html_snippets.append(f"<p><i>{translate('no_conditions_for_pauschale', lang)}</i></p>")
        return {
            "html": "".join(html_snippets),
            "errors": [],
            "trigger_lkn_condition_met": False,
            "prueflogik_expr": prueflogik_expr,
            "prueflogik_pretty": prueflogik_pretty,
            "group_logic_terms": group_logic_terms,
        }

    html_parts = []
    current_group_id_for_display_logic = None # Tracks the current group being displayed
    last_actual_condition_in_current_group = None # To get the operator for intra-group separator
    trigger_lkn_condition_overall_met = False # Für das Resultat der Funktion

    # Need to re-sort for display purposes: by Group, then Ebene, then BedingungsID for non-AST items
    # This is tricky because AST operators break this sorting.
    # We will iterate through the BedingungsID sorted list and manage display groups manually.

    # Let's refine the iteration to handle group display and AST operators correctly.
    # We'll iterate through the BedingungsID-sorted list, which reflects the defined logical order.

    processed_groups_in_current_ast_block = set()

    for i, cond_data in enumerate(all_conditions_for_pauschale_sorted):
        condition_type_upper = str(cond_data.get(BED_TYP_KEY, "")).upper()

        if condition_type_upper == "AST VERBINDUNGSOPERATOR":
            if current_group_id_for_display_logic is not None: # Close the last open condition-group
                html_parts.append("</div>")
                current_group_id_for_display_logic = None
                last_actual_condition_in_current_group = None
                processed_groups_in_current_ast_block.clear()


            ast_operator_value = str(cond_data.get(BED_WERTE_KEY, "ODER")).upper()
            if ast_operator_value == "ODER":
                html_parts.append(f"<div class=\"condition-separator group-operator\">{translate('OR', lang)}</div>")
            elif ast_operator_value == "UND":
                html_parts.append(f"<div class=\"condition-separator group-operator\">{translate('AND', lang)}</div>")
            # else: don't display if it's not UND/ODER (should not happen with clean data)

        else: # It's an actual condition line
            group_val = cond_data.get(GRUPPE_KEY)

            if group_val != current_group_id_for_display_logic:
                if current_group_id_for_display_logic is not None: # Close previous group
                    html_parts.append("</div>") # condition-group

                # Check if this group is new within the current AST block or if an implicit operator is needed
                if group_val in processed_groups_in_current_ast_block and last_actual_condition_in_current_group:
                    # This means we are starting a new group, but there was a previous group in this same AST block.
                    # The operator from the last condition of that *previous group* should apply.
                    # This is complex as `last_actual_condition_in_current_group` refers to the previous line.
                    # The logic for implicit inter-group operators (if not AST) is handled by orchestrator.
                    # For display, if an AST operator wasn't just printed, and we are switching groups,
                    # the orchestrator implies UND by default between groups in a sequence if no AST.
                    # This display logic might not perfectly mirror the orchestrator's implicit UND between groups
                    # without an explicit AST operator. The user asked for operators between groups.
                    # AST operators are explicit. Implicit ones are harder to display here cleanly.
                    # For now, we only display explicit AST operators.
                    pass


                current_group_id_for_display_logic = group_val
                processed_groups_in_current_ast_block.add(group_val)
                group_title = f"{translate('condition_group', lang)} {escape(str(current_group_id_for_display_logic))}"
                html_parts.append(f"<div class=\"condition-group\"><div class=\"condition-group-title\">{group_title}</div>")
                last_actual_condition_in_current_group = None # Reset for the new group

            # Intra-Gruppen Operator (between conditions *within* the same group div)
            if last_actual_condition_in_current_group and last_actual_condition_in_current_group.get(GRUPPE_KEY) == current_group_id_for_display_logic:
                # Operator from the *previous actual condition line* within the same group
                prev_cond_operator_intra = str(last_actual_condition_in_current_group.get(OPERATOR_KEY, "UND")).upper()
                if prev_cond_operator_intra == "ODER":
                    html_parts.append(f"<div class=\"condition-separator\">{translate('OR', lang)}</div>")
                elif prev_cond_operator_intra == "UND":
                    html_parts.append(f"<div class=\"condition-separator\">{translate('AND', lang)}</div>")

            condition_met = check_single_condition(cond_data, context, tabellen_dict_by_table)

        # Überprüfen, ob eine LKN-basierte Bedingung erfüllt ist (für das Funktionsergebnis)
        cond_type_upper = str(cond_data.get(BED_TYP_KEY, "")).upper()
        if condition_met and cond_type_upper in [
            "LEISTUNGSPOSITIONEN IN LISTE", "LKN",
            "LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE"
        ]:
            trigger_lkn_condition_overall_met = True


        icon_svg_path = "#icon-check" if condition_met else "#icon-cross"
        icon_class = "condition-icon-fulfilled" if condition_met else "condition-icon-not-fulfilled"

        # Bedingungstext formatieren
        translated_cond_type = translate_condition_type(cond_data.get(BED_TYP_KEY, "N/A"), lang)

        # Werte-Darstellung verbessern
        werte_display = ""
        # ... (Logik zur besseren Darstellung von Werten, siehe vorherige Implementierung von `generate_condition_detail_html`)
        # Für den Moment: einfache Darstellung
        original_werte = str(cond_data.get(BED_WERTE_KEY, ""))

        if cond_type_upper in ["LEISTUNGSPOSITIONEN IN LISTE", "LKN"]:
            lkn_codes = [l.strip().upper() for l in original_werte.split(',') if l.strip()]
            lkn_details_parts = []
            if lkn_codes:
                for lkn_c in lkn_codes:
                    # leistungskatalog_dict wird jetzt direkt an check_pauschale_conditions übergeben
                    desc = get_beschreibung_fuer_lkn_im_backend(lkn_c, leistungskatalog_dict, lang)
                    lkn_details_parts.append(f"<b>{escape(lkn_c)}</b> ({escape(desc)})")
                werte_display = ", ".join(lkn_details_parts)
            else:
                werte_display = f"<i>{translate('no_lkns_spec', lang)}</i>"

        elif cond_type_upper in ["LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE"]:
            table_names_orig = [t.strip() for t in original_werte.split(',') if t.strip()]
            table_links_parts = []
            if table_names_orig:
                for table_name_o in table_names_orig:
                    # TODO: Hier könnte man die Anzahl der Einträge und eine aufklappbare Liste einfügen,
                    # ähnlich wie in generate_condition_detail_html.
                    # Fürs Erste nur der Tabellenname.
                    table_links_parts.append(f"<i>{escape(table_name_o)}</i>")
                werte_display = ", ".join(table_links_parts)
            else:
                werte_display = f"<i>{translate('no_table_name', lang)}</i>"

        elif cond_type_upper in ["HAUPTDIAGNOSE IN TABELLE", "ICD IN TABELLE"]:
            table_names_icd = [t.strip() for t in original_werte.split(',') if t.strip()]
            table_links_icd_parts = []
            if table_names_icd:
                for table_name_i in table_names_icd:
                    table_links_icd_parts.append(f"<i>{escape(table_name_i)}</i>")
                werte_display = ", ".join(table_links_icd_parts)
            else:
                werte_display = f"<i>{translate('no_table_name', lang)}</i>"

        elif cond_type_upper in ["ICD", "HAUPTDIAGNOSE IN LISTE"]:
            icd_codes_list = [icd.strip().upper() for icd in original_werte.split(',') if icd.strip()]
            icd_details_parts = []
            if icd_codes_list:
                for icd_c in icd_codes_list:
                    # Annahme: tabellen_dict_by_table ist im context oder global
                    desc_icd = get_beschreibung_fuer_icd_im_backend(icd_c, tabellen_dict_by_table, lang=lang)
                    icd_details_parts.append(f"<b>{escape(icd_c)}</b> ({escape(desc_icd)})")
                werte_display = ", ".join(icd_details_parts)
            else:
                 werte_display = f"<i>{translate('no_icds_spec', lang)}</i>"

        elif cond_type_upper == "PATIENTENBEDINGUNG":
            feld_name_pat = str(cond_data.get(BED_FELD_KEY, "")).capitalize()
            min_w_pat = cond_data.get(BED_MIN_KEY)
            max_w_pat = cond_data.get(BED_MAX_KEY)
            expl_wert_pat = cond_data.get(BED_WERTE_KEY)

            if feld_name_pat.lower() == "alter":
                if min_w_pat is not None or max_w_pat is not None:
                    val_disp = []
                    if min_w_pat is not None: val_disp.append(f"{translate('min', lang)} {escape(str(min_w_pat))}")
                    if max_w_pat is not None: val_disp.append(f"{translate('max', lang)} {escape(str(max_w_pat))}")
                    werte_display = " ".join(val_disp)
                else:
                    werte_display = escape(str(expl_wert_pat))
            else: # z.B. Geschlecht
                werte_display = escape(str(expl_wert_pat))
            translated_cond_type = translate('patient_condition_display', lang, field=escape(feld_name_pat))

        elif cond_type_upper == "ALTER IN JAHREN BEI EINTRITT":
            op_val = cond_data.get(BED_VERGLEICHSOP_KEY, "=")
            werte_display = f"{escape(op_val)} {escape(original_werte)}"

        elif cond_type_upper == "ANZAHL":
            op_val_anz = cond_data.get(BED_VERGLEICHSOP_KEY, "=")
            werte_display = f"{escape(op_val_anz)} {escape(original_werte)}"

        elif cond_type_upper == "SEITIGKEIT":
            op_val_seit = cond_data.get(BED_VERGLEICHSOP_KEY, "=")
            # Normalisiere Regelwert für Anzeige
            regel_wert_seit_norm_disp = original_werte.strip().replace("'", "").lower()
            if regel_wert_seit_norm_disp == 'b': regel_wert_seit_norm_disp = translate('bilateral', lang)
            elif regel_wert_seit_norm_disp == 'e': regel_wert_seit_norm_disp = translate('unilateral', lang)
            elif regel_wert_seit_norm_disp == 'l': regel_wert_seit_norm_disp = translate('left', lang)
            elif regel_wert_seit_norm_disp == 'r': regel_wert_seit_norm_disp = translate('right', lang)
            werte_display = f"{escape(op_val_seit)} {escape(regel_wert_seit_norm_disp)}"

        elif cond_type_upper == "GESCHLECHT IN LISTE":
            gender_list = [g.strip().lower() for g in original_werte.split(',') if g.strip()]
            translated_genders = [translate(g, lang) for g in gender_list]
            werte_display = escape(", ".join(translated_genders))

        else: # Fallback für andere Typen
            werte_display = escape(original_werte)

        # Kontext-Info für erfüllte Bedingungen
        context_match_info_html = ""
        if condition_met:
            match_details = [] # Hier Details sammeln, was genau zum Match geführt hat
            # Beispiel für ICD:
            if cond_type_upper == "ICD" or cond_type_upper == "HAUPTDIAGNOSE IN LISTE":
                provided_icds_upper = {p_icd.upper() for p_icd in context.get("ICD", []) if p_icd}
                required_icds_in_rule_list = {w.strip().upper() for w in str(cond_data.get(BED_WERTE_KEY, "")).split(',') if w.strip()}
                matching_icds = list(provided_icds_upper.intersection(required_icds_in_rule_list))
                if matching_icds:
                    match_details.append(f"{translate('fulfilled_by_icd', lang)}: {', '.join(matching_icds)}")
            # TODO: Ähnliche Logik für LKN, GTIN, etc. hinzufügen

            if match_details:
                context_match_info_html = f"<span class=\"context-match-info fulfilled\">({'; '.join(match_details)})</span>"
            else: # Generischer Text, wenn keine spezifischen Details gesammelt wurden
                context_match_info_html = f"<span class=\"context-match-info fulfilled\">({translate('condition_met_context_generic', lang)})</span>"


        html_parts.append(f"""
            <div class="condition-item-row">
                <span class="condition-status-icon {icon_class}">
                    <svg viewBox="0 0 24 24"><use xlink:href="{icon_svg_path}"></use></svg>
                </span>
                <span class="condition-type-display">{escape(translated_cond_type)}:</span>
                <span class="condition-text-wrapper">{werte_display} {context_match_info_html}</span>
            </div>
        """)

    if current_group is not None: # Letzte Gruppe abschliessen
        html_parts.append("</div>") # condition-group

    # Rückgabe als Dictionary, um konsistent mit der vorherigen Struktur zu sein,
    # die möglicherweise auch Fehler oder andere Infos zurückgeben könnte.
    return {
        "html": "".join(html_parts),
        "errors": [], # Vorerst keine Fehlerbehandlung hier, kann erweitert werden
        "trigger_lkn_condition_met": trigger_lkn_condition_overall_met,
        "prueflogik_expr": prueflogik_expr,
        "prueflogik_pretty": prueflogik_pretty,
        "group_logic_terms": group_logic_terms,
    }


def check_pauschale_conditions_structured(
    pauschale_code: str,
    context: dict,
    pauschale_bedingungen_data: list[dict],
    tabellen_dict_by_table: Dict[str, List[Dict]],
    lang: str = "de",
    pauschalen_dict: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return a structured representation of conditions for a Pauschale.

    The result contains groups with conditions and the connecting operators.
    This function performs the same boolean checks as the HTML generator but
    returns data only, allowing server-side rendering and sanitization.
    """
    PAUSCHALE_KEY = "Pauschale"
    BED_TYP_KEY = "Bedingungstyp"
    BED_ID_KEY = "BedingungsID"
    GRUPPE_KEY = "Gruppe"
    OPERATOR_KEY = "Operator"

    conditions_sorted = sorted(
        [c for c in pauschale_bedingungen_data if c.get(PAUSCHALE_KEY) == pauschale_code],
        key=lambda x: x.get(BED_ID_KEY, 0),
    )

    prueflogik_expr: Optional[str] = None
    prueflogik_pretty: str = ""
    if pauschalen_dict:
        prueflogik_raw = pauschalen_dict.get(pauschale_code, {}).get('Pr\u00fcflogik')
        if isinstance(prueflogik_raw, str) and prueflogik_raw.strip():
            prueflogik_expr = prueflogik_raw.strip()
            prueflogik_pretty = _format_prueflogik_for_display(prueflogik_expr, lang)
    group_logic_terms = _extract_group_logic_terms(pauschale_code, prueflogik_expr, pauschale_bedingungen_data)

    # Collect operator overrides defined by AST VERBINDUNGSOPERATOR
    inter_group_operators_map: Dict[Any, str] = {}
    ast_links: list[tuple[Any, Any, str, int]] = []

    def _normalize_group_id(value: Any) -> Any:
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except Exception:
            s = str(value).strip()
            return s if s else None

    def _normalize_operator(value: Any) -> str:
        if value is None:
            return ""
        value_upper = str(value).strip().upper()
        if value_upper in ("UND", "AND"):
            return "UND"
        if value_upper in ("ODER", "OR"):
            return "ODER"
        return value_upper

    group_meta: Dict[Any, Dict[str, Any]] = {}

    for entry in conditions_sorted:
        gid_norm = _normalize_group_id(entry.get(GRUPPE_KEY))
        meta = group_meta.setdefault(
            gid_norm,
            {
                "GroupNegated": False,
                "ParentGroup": _normalize_group_id(entry.get("ParentGroup")),
                "GroupOperator": "",
                "SortIndex": entry.get("GruppeSortIndex", entry.get(GRUPPE_KEY, 0)),
            },
        )
        if entry.get("GroupNegated"):
            meta["GroupNegated"] = True
        if meta.get("GroupOperator") == "":
            meta["GroupOperator"] = _normalize_operator(entry.get("GruppenOperator"))
        if meta.get("ParentGroup") is None:
            meta["ParentGroup"] = _normalize_group_id(entry.get("ParentGroup"))

    for c in conditions_sorted:
        if str(c.get(BED_TYP_KEY, "")).upper() == "AST VERBINDUNGSOPERATOR":
            parent_id_norm = _normalize_group_id(c.get(GRUPPE_KEY))
            child_raw = c.get('Spezialbedingung') or c.get('Werte')
            gid = _normalize_group_id(child_raw)
            op_val = str(c.get(OPERATOR_KEY, "ODER")).upper()
            if gid is not None and op_val in ("UND", "ODER"):
                inter_group_operators_map[gid] = op_val
            if parent_id_norm is not None and gid is not None:
                ast_links.append((parent_id_norm, gid, op_val, c.get(BED_ID_KEY, 0)))

    groups: list[dict[str, Any]] = []
    current_gid: Any = None
    current_group: dict[str, Any] | None = None
    inter_group_ops_out: list[str] = []
    any_lkn_condition_met = False

    last_condition_in_group: dict | None = None
    for cond in conditions_sorted:
        cond_type_upper = str(cond.get(BED_TYP_KEY, "")).upper()
        if cond_type_upper == "AST VERBINDUNGSOPERATOR":
            # close group if open
            if current_group is not None:
                groups.append(current_group)
                current_group = None
            current_gid = None
            last_condition_in_group = None
            continue

        gid = cond.get(GRUPPE_KEY)
        if gid != current_gid:
            # append inter-group operator (if any) between groups
            if current_group is not None:
                groups.append(current_group)
                current_group = None
                last_condition_in_group = None
            # operator between groups
            op_between = inter_group_operators_map.pop(_normalize_group_id(gid), None)
            if op_between:
                inter_group_ops_out.append(op_between)
            current_gid = gid
            normalized_gid = _normalize_group_id(gid)
            current_group = {
                "id": gid,
                "conditions": [],
                "intra_ops": [],
                "negated": bool(group_meta.get(normalized_gid, {}).get("GroupNegated")),
                "sort_index": group_meta.get(normalized_gid, {}).get("SortIndex", cond.get("GruppeSortIndex", gid)),
                "normalized_id": normalized_gid,
                "parent": group_meta.get(normalized_gid, {}).get("ParentGroup"),
                "group_operator": group_meta.get(normalized_gid, {}).get("GroupOperator"),
            }

        # compute match
        met = bool(check_single_condition(cond, context, tabellen_dict_by_table))

        # detect if LKN-related condition matched (for convenience flag)
        if met and cond_type_upper in (
            "LEISTUNGSPOSITIONEN IN LISTE", "LKN",
            "LEISTUNGSPOSITIONEN IN TABELLE", "TARIFPOSITIONEN IN TABELLE",
        ):
            any_lkn_condition_met = True

        # store condition summary
        cond_entry = {
            "type": cond.get(BED_TYP_KEY),
            "werte": cond.get('Werte'),
            "feld": cond.get('Feld'),
            "min": cond.get('MinWert'),
            "max": cond.get('MaxWert'),
            "vergleich": cond.get('Vergleichsoperator'),
            "matched": met,
        }
        if current_group is None:
            # ensure group exists even if data inconsistent
            normalized_gid = _normalize_group_id(gid)
            meta = group_meta.get(normalized_gid, {})
            current_group = {
                "id": gid,
                "conditions": [],
                "intra_ops": [],
                "negated": bool(meta.get("GroupNegated")),
                "sort_index": meta.get("SortIndex", cond.get("GruppeSortIndex", gid)),
                "normalized_id": normalized_gid,
                "parent": meta.get("ParentGroup"),
                "group_operator": meta.get("GroupOperator"),
            }
            current_gid = gid
        current_group["conditions"].append(cond_entry)

        # intra-group operator (based on previous actual condition)
        if last_condition_in_group is not None and last_condition_in_group.get(GRUPPE_KEY) == gid:
            link_op = str(last_condition_in_group.get(OPERATOR_KEY, "UND")).upper()
            if link_op in ("UND", "ODER"):
                current_group["intra_ops"].append(link_op)
        last_condition_in_group = cond

    if current_group is not None:
        groups.append(current_group)

    group_lookup: Dict[Any, dict[str, Any]] = {}
    for grp in groups:
        normalized_gid = grp.get("normalized_id")
        if normalized_gid is None:
            normalized_gid = _normalize_group_id(grp.get("id"))
            grp["normalized_id"] = normalized_gid
        group_lookup[normalized_gid] = grp

    from collections import defaultdict

    children_map: defaultdict[Any, list[dict[str, Any]]] = defaultdict(list)
    parent_nodes: set[Any] = set()
    child_nodes: set[Any] = set()

    for parent_id, child_id, op_raw, bed_id in ast_links:
        if parent_id is None or child_id is None:
            continue
        parent_meta = group_meta.get(parent_id, {})
        child_meta = group_meta.get(child_id, {})
        display_operator = _normalize_operator(op_raw)
        if child_meta.get("ParentGroup") == parent_id:
            display_operator = _normalize_operator(parent_meta.get("GroupOperator") or display_operator)
        if display_operator not in ("UND", "ODER"):
            display_operator = "UND" if parent_meta.get("GroupOperator") == "UND" else "ODER"
        children_map[parent_id].append({
            "child": child_id,
            "operator": display_operator,
            "bed": bed_id,
        })
        parent_nodes.add(parent_id)
        child_nodes.add(child_id)

    for entries in children_map.values():
        entries.sort(key=lambda item: item.get("bed", 0))

    def _group_sort_key(gid: Any) -> tuple[int, Any, str]:
        grp = group_lookup.get(gid)
        if grp:
            return (0, grp.get("sort_index", gid), str(grp.get("id")))
        return (1, gid if isinstance(gid, int) else 0, str(gid))

    ordered_pairs: list[tuple[dict[str, Any], Optional[str]]] = []
    visited_groups: set[Any] = set()

    def _traverse(node_id: Any, operator_from_parent: Optional[str]) -> None:
        if node_id in visited_groups:
            return
        group_obj = group_lookup.get(node_id)
        if not group_obj:
            return
        ordered_pairs.append((group_obj, operator_from_parent))
        visited_groups.add(node_id)
        for child_entry in children_map.get(node_id, []):
            _traverse(child_entry.get("child"), child_entry.get("operator"))

    root_candidates = sorted(
        [gid for gid in parent_nodes if gid not in child_nodes],
        key=_group_sort_key,
    )
    if not root_candidates:
        root_candidates = sorted(group_lookup.keys(), key=_group_sort_key)

    for root_id in root_candidates:
        _traverse(root_id, None)

    for remaining_id in sorted(group_lookup.keys(), key=_group_sort_key):
        if remaining_id not in visited_groups:
            _traverse(remaining_id, None)

    ordered_groups: list[dict[str, Any]] = []
    ordered_inter_ops: list[str] = []
    for idx, (grp_obj, op_raw) in enumerate(ordered_pairs):
        ordered_groups.append(grp_obj)
        if idx > 0:
            op_value = op_raw if op_raw in ("UND", "ODER") else DEFAULT_GROUP_OPERATOR
            ordered_inter_ops.append(op_value)

    group_children_serializable: Dict[str, list[dict[str, Any]]] = {
        str(parent_id): [
            {"child": entry.get("child"), "operator": entry.get("operator")}
            for entry in entries
        ]
        for parent_id, entries in children_map.items()
    }

    groups = ordered_groups
    inter_group_ops_out = ordered_inter_ops

    return {
        "groups": groups,
        "inter_group_ops": inter_group_ops_out,
        "any_lkn_condition_met": any_lkn_condition_met,
        "pauschale_code": pauschale_code,
        "lang": lang,
        "prueflogik_expr": prueflogik_expr,
        "prueflogik_pretty": prueflogik_pretty,
        "group_logic_terms": group_logic_terms,
        "group_children": group_children_serializable,
        "group_root_ids": [root for root in root_candidates],
    }

# === RENDERER FUER CONDITION-ERGEBNISSE (WIRD NICHT MEHR DIREKT VERWENDET, LOGIK IST IN check_pauschale_conditions) ===
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
    LKN_KEY_IN_RULE_CHECKED = 'lkn'; PAUSCHALE_KEY_IN_PAUSCHALEN = 'Pauschale' # In PAUSCHALEN_Pauschalen
    PAUSCHALE_TEXT_KEY_IN_PAUSCHALEN = 'Pauschale_Text'
    LP_LKN_KEY = 'Leistungsposition'; LP_PAUSCHALE_KEY = 'Pauschale' # In PAUSCHALEN_Leistungspositionen
    BED_PAUSCHALE_KEY = 'Pauschale'; BED_TYP_KEY = 'Bedingungstyp' # In PAUSCHALEN_Bedingungen
    BED_WERTE_KEY = 'Werte'

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
        bedingungs_html = ""
        try:
            # grp_op = get_group_operator_for_pauschale(code, pauschale_bedingungen_data, default=DEFAULT_GROUP_OPERATOR) # Removed
            # evaluate_structured_conditions is now the orchestrator and handles group logic internally
            is_pauschale_valid_structured = evaluate_pauschale_logic_orchestrator( # Renamed for clarity, was evaluate_structured_conditions
                pauschale_code=code,
                context=context,
                all_pauschale_bedingungen_data=pauschale_bedingungen_data,
                tabellen_dict_by_table=tabellen_dict_by_table,
                pauschalen_dict=pauschalen_dict,
                debug=logger.isEnabledFor(logging.DEBUG) # Pass appropriate debug flag
            )
            check_res = check_pauschale_conditions(
                code,
                context,
                pauschale_bedingungen_data,
                tabellen_dict_by_table,
                leistungskatalog_dict,
                lang,
                pauschalen_dict=pauschalen_dict,
            )
            bedingungs_html = check_res.get("html", "")
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

        requires_icd = requires_icd_cache.setdefault(
            code,
            pauschale_requires_icd(code, pauschale_bedingungen_data, pauschalen_dict),
        )
        matched_lkn_count = count_matching_lkn_codes(
            code, context, pauschale_bedingungen_data, tabellen_dict_by_table
        )

        try:
            structured_cond = check_pauschale_conditions_structured(
                code,
                context,
                pauschale_bedingungen_data,
                tabellen_dict_by_table,
                lang,
                pauschalen_dict=pauschalen_dict,
            )
        except Exception:
            structured_cond = None

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
            "bedingungs_pruef_html": bedingungs_html,
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
        )
        bedingungs_pruef_html_result = condition_result_html_dict.get("html", "<p class='error'>Fehler bei HTML-Generierung der Bedingungen.</p>")
        # Errors from check_pauschale_conditions itself (if any were designed to be returned, currently it's an empty list)
        condition_errors_html_gen.extend(condition_result_html_dict.get("errors", []))
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
            status_text = f"<span style=\"color:green;\">{status}</span>"
        else:
            status = translate('conditions_not_met', lang)
            status_text = f"<span style=\"color:red;\">{status}</span>"
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
            )
    except Exception:
        selected_structured = None

    # Finale Filterung der an das Frontend gesendeten Datenliste.
    # Nur Pauschalen aus derselben "Familie" (z.B. C08.50x) und Fallbacks (C9x) behalten.
    stamm_prefix = None
    if best_pauschale_code and best_pauschale_code[-1].isalpha():
        stamm_prefix = best_pauschale_code[:-1]

    if stamm_prefix:
        final_evaluated_pauschalen = [
            cand for cand in evaluated_candidates
            if str(cand['code']).startswith(stamm_prefix) or is_pauschale_code_ge_c90(cand['code'])
        ]
    else:
        # Fallback, falls der beste Code keinem erwarteten Muster folgt,
        # um eine leere Liste zu vermeiden.
        final_evaluated_pauschalen = evaluated_candidates

    final_result_dict = {
        "type": "Pauschale",
        "details": best_pauschale_details,
        "bedingungs_pruef_html": bedingungs_pruef_html_result,
        "bedingungs_fehler": condition_errors_html_gen, # Fehler aus der HTML-Generierung
        "conditions_met": True, # Da wir hier nur landen, wenn eine Pauschale als gültig ausgewählt wurde
        "evaluated_pauschalen": final_evaluated_pauschalen,
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
