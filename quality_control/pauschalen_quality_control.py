"""Repeatable quality checks for canonical PAUSCHALEN logic exports.

This module validates ``data/PAUSCHALEN_Logic.json`` and emits a structured
report that can be consumed by pytest, CI, and HTML reporting scripts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set


OPERATOR_TOKENS: Set[str] = {"AND", "OR", "UND", "ODER"}
LOGIC_OPERATORS: Set[str] = {"AND", "OR"}
ALLOWED_LOGIC_NODE_TYPES: Set[str] = {"AND", "OR", "NOT", "GROUP"}
NUMERIC_COMPARISON_OPERATORS: Set[str] = {"<", "<=", "=", ">=", ">", "!="}
ROOT_GROUP_MARKERS: Set[str] = {"0"}

ALLOWED_CONDITION_VALUE_TYPES: Dict[str, str] = {
    "ALTER IN JAHREN BEI EINTRITT": "age_years",
    "ANZAHL": "number",
    "GESCHLECHT IN LISTE": "sex_list",
    "HAUPTDIAGNOSE IN TABELLE": "icd_table",
    "LEISTUNGSPOSITIONEN IN LISTE": "service_list",
    "LEISTUNGSPOSITIONEN IN TABELLE": "service_table",
    "MEDIKAMENTE IN LISTE": "medication_list",
    "SEITIGKEIT": "laterality",
    "TARIFPOSITIONEN IN TABELLE": "tariff_table",
}

TABLE_CONDITION_TYPES: Set[str] = {
    "HAUPTDIAGNOSE IN TABELLE",
    "LEISTUNGSPOSITIONEN IN TABELLE",
    "TARIFPOSITIONEN IN TABELLE",
}

REFERENCE_CASE_EXPECTATIONS: Dict[str, Dict[str, Any]] = {
    "C04.60A": {
        "root_type": "AND",
        "must_include_or_between": ("2", "3"),
    },
    "C01.05B": {
        "root_type": "OR",
        "required_groups": {"1", "2", "3", "4"},
    },
    "C01.50A": {
        "root_type": "AND",
        "required_groups": {"1", "2"},
    },
}


@dataclass
class Issue:
    """Single validation issue."""

    check_id: str
    severity: str
    message: str
    pauschale: Optional[str] = None
    location: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "severity": self.severity,
            "message": self.message,
            "pauschale": self.pauschale,
            "location": self.location,
            "details": self.details,
        }


@dataclass
class CheckResult:
    """Result of one logical quality check."""

    check_id: str
    title: str
    issues: List[Issue] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "pass" if not self.issues else "fail"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.check_id,
            "title": self.title,
            "status": self.status,
            "issue_count": len(self.issues),
            "metrics": self.metrics,
        }


def _normalize_group_id(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if text and text.lstrip("-").isdigit():
        try:
            return str(int(text))
        except ValueError:
            return text
    return text


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _flatten_values_as_tokens(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, list):
        return [str(item).strip().upper() for item in values if str(item).strip()]
    if isinstance(values, tuple):
        return [str(item).strip().upper() for item in values if str(item).strip()]
    if isinstance(values, set):
        return [str(item).strip().upper() for item in values if str(item).strip()]
    text = str(values).strip().upper()
    if not text:
        return []
    return [part.strip().upper() for part in text.split(",") if part.strip()]


def _build_logic_lookup(pauschalen: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    lookup: Dict[str, Mapping[str, Any]] = {}
    for item in pauschalen:
        code = str(item.get("pauschale") or "").strip()
        if code:
            lookup[code] = item
    return lookup


def _iter_paths_for_key(value: Any, key_name: str, base_path: str = "$") -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{base_path}.{key}"
            if str(key).lower() == key_name.lower():
                yield path
            yield from _iter_paths_for_key(nested, key_name, path)
    elif isinstance(value, list):
        for idx, nested in enumerate(value):
            yield from _iter_paths_for_key(nested, key_name, f"{base_path}[{idx}]")


def _extract_table_names(tabellen_payload: Any) -> Set[str]:
    table_names: Set[str] = set()
    if not isinstance(tabellen_payload, list):
        return table_names
    for row in tabellen_payload:
        if not isinstance(row, dict):
            continue
        table = row.get("Tabelle")
        if table is None:
            continue
        token = str(table).strip().upper()
        if token:
            table_names.add(token)
    return table_names


def _check_global_structure(logic_payload: Any) -> CheckResult:
    result = CheckResult("global_structure", "Top-level Struktur und Metadaten")
    if not isinstance(logic_payload, dict):
        result.issues.append(
            Issue(
                check_id=result.check_id,
                severity="error",
                message="PAUSCHALEN_Logic.json muss ein JSON-Objekt sein.",
            )
        )
        return result
    if not str(logic_payload.get("logic_schema_version") or "").strip():
        result.issues.append(
            Issue(
                check_id=result.check_id,
                severity="error",
                message="logic_schema_version fehlt oder ist leer.",
                location="$.logic_schema_version",
            )
        )
    pauschalen = logic_payload.get("pauschalen")
    if not isinstance(pauschalen, list):
        result.issues.append(
            Issue(
                check_id=result.check_id,
                severity="error",
                message="Top-level Feld 'pauschalen' muss eine Liste sein.",
                location="$.pauschalen",
            )
        )
    else:
        result.metrics["pauschalen_count"] = len(pauschalen)
    return result


def _check_no_legacy_warning_fields(logic_payload: Any, changelog_payload: Any) -> CheckResult:
    result = CheckResult("legacy_and_warnings", "Keine Legacy-Warnfelder und Build-Issues")
    warning_paths = list(_iter_paths_for_key(logic_payload, "LogicWarningsJSON"))
    for path in warning_paths:
        result.issues.append(
            Issue(
                check_id=result.check_id,
                severity="error",
                message="LogicWarningsJSON darf im produktiven Export nicht vorkommen.",
                location=path,
            )
        )

    if isinstance(changelog_payload, dict):
        build_issues = changelog_payload.get("build_issues")
        if isinstance(build_issues, list) and build_issues:
            for idx, issue in enumerate(build_issues):
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        message="build_issues in PAUSCHALEN_Logic_Changelog.json ist nicht leer.",
                        location=f"$.build_issues[{idx}]",
                        details={"issue": issue},
                    )
                )
        result.metrics["build_issues_count"] = len(build_issues) if isinstance(build_issues, list) else 0
    return result


def _check_group_integrity(pauschalen: Iterable[Mapping[str, Any]]) -> CheckResult:
    result = CheckResult("group_integrity", "Gruppen-Referenzintegrität")
    total_groups = 0
    for item in pauschalen:
        code = str(item.get("pauschale") or "").strip()
        groups = [g for g in _as_list(item.get("groups")) if isinstance(g, dict)]
        total_groups += len(groups)
        seen_ids: Set[str] = set()
        group_ids: Set[str] = set()
        for idx, group in enumerate(groups):
            gid = _normalize_group_id(group.get("group_id"))
            if not gid:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.groups[{idx}].group_id",
                        message="group_id fehlt oder ist leer.",
                    )
                )
                continue
            if gid in seen_ids:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.groups[{idx}].group_id",
                        message=f"Doppelte group_id '{gid}'.",
                    )
                )
            seen_ids.add(gid)
            group_ids.add(gid)

        for idx, group in enumerate(groups):
            gid = _normalize_group_id(group.get("group_id"))
            parent = _normalize_group_id(group.get("parent_group_id"))
            if parent and parent not in ROOT_GROUP_MARKERS and parent not in group_ids:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.groups[{idx}].parent_group_id",
                        message=f"parent_group_id '{parent}' verweist auf keine existierende Gruppe.",
                        details={"group_id": gid},
                    )
                )
    result.metrics["group_count"] = total_groups
    return result


def _check_condition_integrity(pauschalen: Iterable[Mapping[str, Any]]) -> CheckResult:
    result = CheckResult("condition_integrity", "Bedingungstypen, Operatoren, Value-Typen")
    total_conditions = 0
    for item in pauschalen:
        code = str(item.get("pauschale") or "").strip()
        groups = [g for g in _as_list(item.get("groups")) if isinstance(g, dict)]
        group_ids = {_normalize_group_id(group.get("group_id")) for group in groups}
        conditions = [c for c in _as_list(item.get("conditions")) if isinstance(c, dict)]
        total_conditions += len(conditions)
        seen_condition_ids: Set[str] = set()
        for idx, cond in enumerate(conditions):
            cid = str(cond.get("condition_id") or "").strip()
            if not cid:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.conditions[{idx}].condition_id",
                        message="condition_id fehlt oder ist leer.",
                    )
                )
            elif cid in seen_condition_ids:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.conditions[{idx}].condition_id",
                        message=f"Doppelte condition_id '{cid}' innerhalb der Pauschale.",
                    )
                )
            seen_condition_ids.add(cid)

            group_id = _normalize_group_id(cond.get("group_id"))
            if not group_id or group_id not in group_ids:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.conditions[{idx}].group_id",
                        message=f"condition.group_id '{group_id}' verweist auf keine existierende Gruppe.",
                    )
                )

            cond_type = str(cond.get("condition_type") or "").strip().upper()
            if cond_type not in ALLOWED_CONDITION_VALUE_TYPES:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.conditions[{idx}].condition_type",
                        message=f"Unbekannter oder nicht freigegebener condition_type '{cond_type}'.",
                    )
                )
            expected_value_type = ALLOWED_CONDITION_VALUE_TYPES.get(cond_type)
            actual_value_type = str(cond.get("value_type") or "").strip()
            if expected_value_type and actual_value_type != expected_value_type:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.conditions[{idx}].value_type",
                        message=(
                            f"value_type '{actual_value_type}' passt nicht zu condition_type '{cond_type}' "
                            f"(erwartet: '{expected_value_type}')."
                        ),
                    )
                )

            logic_operator = str(cond.get("operator") or "").strip().upper()
            if logic_operator not in LOGIC_OPERATORS:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.conditions[{idx}].operator",
                        message=f"Ungültiger condition.operator '{logic_operator}'.",
                    )
                )

            comparison_operator = str(cond.get("comparison_operator") or "").strip()
            if cond_type in {"ALTER IN JAHREN BEI EINTRITT", "ANZAHL"}:
                if comparison_operator not in NUMERIC_COMPARISON_OPERATORS:
                    result.issues.append(
                        Issue(
                            check_id=result.check_id,
                            severity="error",
                            pauschale=code,
                            location=f"{code}.conditions[{idx}].comparison_operator",
                            message=(
                                f"comparison_operator '{comparison_operator}' ist für numerische Bedingungen ungültig."
                            ),
                        )
                    )

            sort_idx = cond.get("condition_sort_index")
            if not isinstance(sort_idx, int):
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.conditions[{idx}].condition_sort_index",
                        message="condition_sort_index muss Integer sein.",
                        details={"value": sort_idx},
                    )
                )
    result.metrics["condition_count"] = total_conditions
    return result


def _check_operator_tokens_in_values(
    pauschalen: Iterable[Mapping[str, Any]],
    table_names: Set[str],
) -> CheckResult:
    result = CheckResult("operator_tokens_in_values", "Keine logischen Platzhalter in condition.values")
    scanned_conditions = 0
    for item in pauschalen:
        code = str(item.get("pauschale") or "").strip()
        conditions = [c for c in _as_list(item.get("conditions")) if isinstance(c, dict)]
        for idx, cond in enumerate(conditions):
            scanned_conditions += 1
            cond_type = str(cond.get("condition_type") or "").strip().upper()
            tokens = _flatten_values_as_tokens(cond.get("values"))
            if not tokens:
                continue
            if not all(token in OPERATOR_TOKENS for token in tokens):
                continue

            # Ausnahme: Operator-Token als echter Tabellenname (z. B. "OR")
            if cond_type in TABLE_CONDITION_TYPES and all(token in table_names for token in tokens):
                continue

            result.issues.append(
                Issue(
                    check_id=result.check_id,
                    severity="error",
                    pauschale=code,
                    location=f"{code}.conditions[{idx}].values",
                    message="condition.values enthält nur Operator-Tokens (AND/OR/UND/ODER).",
                    details={"condition_type": cond_type, "tokens": tokens},
                )
            )
    result.metrics["scanned_conditions"] = scanned_conditions
    return result


def _check_connector_integrity(pauschalen: Iterable[Mapping[str, Any]]) -> CheckResult:
    result = CheckResult("connector_integrity", "AST-Connectoren und Zielreferenzen")
    total_connectors = 0
    for item in pauschalen:
        code = str(item.get("pauschale") or "").strip()
        groups = [g for g in _as_list(item.get("groups")) if isinstance(g, dict)]
        group_ids = {_normalize_group_id(group.get("group_id")) for group in groups}
        connectors = [c for c in _as_list(item.get("connectors")) if isinstance(c, dict)]
        total_connectors += len(connectors)
        for idx, connector in enumerate(connectors):
            source = _normalize_group_id(connector.get("source_group_id"))
            target = _normalize_group_id(connector.get("target_group_id"))
            op = str(connector.get("operator") or "").strip().upper()

            if not target or target not in group_ids:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.connectors[{idx}].target_group_id",
                        message=f"target_group_id '{target}' verweist auf keine existierende Gruppe.",
                    )
                )
            if source and source not in ROOT_GROUP_MARKERS and source not in group_ids:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.connectors[{idx}].source_group_id",
                        message=f"source_group_id '{source}' verweist auf keine existierende Gruppe oder Root-Knoten.",
                    )
                )
            if op not in LOGIC_OPERATORS:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.connectors[{idx}].operator",
                        message=f"Ungültiger connector.operator '{op}'.",
                    )
                )

            sort_idx = connector.get("connector_sort_index")
            if not isinstance(sort_idx, int):
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        location=f"{code}.connectors[{idx}].connector_sort_index",
                        message="connector_sort_index muss Integer sein.",
                        details={"value": sort_idx},
                    )
                )
    result.metrics["connector_count"] = total_connectors
    return result


def _logic_tree_contains_or_between_groups(node: Any, left_group: str, right_group: str) -> bool:
    if not isinstance(node, dict):
        return False
    node_type = str(node.get("type") or "").upper()
    if node_type == "OR":
        children = _as_list(node.get("children"))
        group_ids = {
            _normalize_group_id(child.get("id"))
            for child in children
            if isinstance(child, dict) and str(child.get("type") or "").upper() == "GROUP"
        }
        if _normalize_group_id(left_group) in group_ids and _normalize_group_id(right_group) in group_ids:
            return True
    if node_type == "NOT":
        child = node.get("child")
        if isinstance(child, dict):
            return _logic_tree_contains_or_between_groups(child, left_group, right_group)
    for child in _as_list(node.get("children")):
        if _logic_tree_contains_or_between_groups(child, left_group, right_group):
            return True
    if isinstance(node.get("child"), dict):
        return _logic_tree_contains_or_between_groups(node.get("child"), left_group, right_group)
    return False


def _check_logic_tree_integrity(pauschalen: Iterable[Mapping[str, Any]]) -> CheckResult:
    result = CheckResult("logic_tree_integrity", "Validität der logic_tree-Struktur")
    visited_nodes = 0

    def walk(
        node: Any,
        pauschale_code: str,
        group_ids: Set[str],
        path: str,
    ) -> None:
        nonlocal visited_nodes
        if not isinstance(node, dict):
            result.issues.append(
                Issue(
                    check_id=result.check_id,
                    severity="error",
                    pauschale=pauschale_code,
                    location=path,
                    message="logic_tree Knoten muss ein Objekt sein.",
                    details={"node": node},
                )
            )
            return
        visited_nodes += 1
        node_type = str(node.get("type") or "").upper()
        if node_type not in ALLOWED_LOGIC_NODE_TYPES:
            result.issues.append(
                Issue(
                    check_id=result.check_id,
                    severity="error",
                    pauschale=pauschale_code,
                    location=f"{path}.type",
                    message=f"Ungültiger logic_tree Knotentyp '{node_type}'.",
                )
            )
            return

        if node_type == "GROUP":
            group_id = _normalize_group_id(node.get("id"))
            if not group_id or group_id not in group_ids:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=pauschale_code,
                        location=f"{path}.id",
                        message=f"GROUP-Knoten verweist auf unbekannte Gruppe '{group_id}'.",
                    )
                )
            return

        if node_type == "NOT":
            child_node = node.get("child")
            children_list = _as_list(node.get("children"))
            if isinstance(child_node, dict):
                walk(child_node, pauschale_code, group_ids, f"{path}.child")
                return
            if len(children_list) == 1 and isinstance(children_list[0], dict):
                walk(children_list[0], pauschale_code, group_ids, f"{path}.children[0]")
                return
            result.issues.append(
                Issue(
                    check_id=result.check_id,
                    severity="error",
                    pauschale=pauschale_code,
                    location=path,
                    message="NOT-Knoten benötigt genau ein Kind (child oder children[0]).",
                )
            )
            return

        children = _as_list(node.get("children"))
        if not children:
            result.issues.append(
                Issue(
                    check_id=result.check_id,
                    severity="error",
                    pauschale=pauschale_code,
                    location=f"{path}.children",
                    message=f"{node_type}-Knoten benötigt mindestens ein Kind.",
                )
            )
            return
        for idx, child in enumerate(children):
            walk(child, pauschale_code, group_ids, f"{path}.children[{idx}]")

    for item in pauschalen:
        code = str(item.get("pauschale") or "").strip()
        groups = [g for g in _as_list(item.get("groups")) if isinstance(g, dict)]
        group_ids = {_normalize_group_id(group.get("group_id")) for group in groups}
        logic_tree = item.get("logic_tree")
        walk(logic_tree, code, group_ids, f"{code}.logic_tree")

    result.metrics["visited_nodes"] = visited_nodes
    return result


def _check_reference_cases(pauschale_lookup: Mapping[str, Mapping[str, Any]]) -> CheckResult:
    result = CheckResult("reference_cases", "Referenzpauschalen (C04.60A, C01.05B, C01.50A)")
    for code, expectations in REFERENCE_CASE_EXPECTATIONS.items():
        item = pauschale_lookup.get(code)
        if not item:
            result.issues.append(
                Issue(
                    check_id=result.check_id,
                    severity="error",
                    pauschale=code,
                    message=f"Referenzpauschale '{code}' fehlt im Export.",
                )
            )
            continue

        logic_tree = item.get("logic_tree")
        root_type = str((logic_tree or {}).get("type") or "").upper() if isinstance(logic_tree, dict) else ""
        expected_root = str(expectations.get("root_type") or "").upper()
        if expected_root and root_type != expected_root:
            result.issues.append(
                Issue(
                    check_id=result.check_id,
                    severity="error",
                    pauschale=code,
                    location=f"{code}.logic_tree.type",
                    message=f"Root-Operator ist '{root_type}', erwartet '{expected_root}'.",
                )
            )

        required_groups = expectations.get("required_groups")
        if isinstance(required_groups, set):
            group_ids = {
                _normalize_group_id(group.get("group_id"))
                for group in _as_list(item.get("groups"))
                if isinstance(group, dict)
            }
            missing = sorted({str(g) for g in required_groups if str(g) not in group_ids})
            if missing:
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        message=f"Erwartete Gruppen fehlen: {', '.join(missing)}.",
                    )
                )

        pair = expectations.get("must_include_or_between")
        if isinstance(pair, tuple) and len(pair) == 2:
            if not _logic_tree_contains_or_between_groups(logic_tree, str(pair[0]), str(pair[1])):
                result.issues.append(
                    Issue(
                        check_id=result.check_id,
                        severity="error",
                        pauschale=code,
                        message=(
                            f"Erwartete ODER-Verknüpfung zwischen Gruppen {pair[0]} und {pair[1]} "
                            "nicht im logic_tree gefunden."
                        ),
                    )
                )
    return result


def run_quality_checks(data_dir: Path) -> Dict[str, Any]:
    """Run the PAUSCHALEN quality checks and return a structured report."""
    data_dir = Path(data_dir)
    logic_path = data_dir / "PAUSCHALEN_Logic.json"
    changelog_path = data_dir / "PAUSCHALEN_Logic_Changelog.json"
    tabellen_path = data_dir / "PAUSCHALEN_Tabellen.json"

    logic_payload = json.loads(logic_path.read_text(encoding="utf-8"))
    changelog_payload = {}
    if changelog_path.is_file():
        changelog_payload = json.loads(changelog_path.read_text(encoding="utf-8"))
    tabellen_payload = []
    if tabellen_path.is_file():
        tabellen_payload = json.loads(tabellen_path.read_text(encoding="utf-8"))

    checks: List[CheckResult] = []
    checks.append(_check_global_structure(logic_payload))

    pauschalen = logic_payload.get("pauschalen") if isinstance(logic_payload, dict) else []
    pauschalen_list = [p for p in pauschalen if isinstance(p, dict)] if isinstance(pauschalen, list) else []
    pauschale_lookup = _build_logic_lookup(pauschalen_list)
    table_names = _extract_table_names(tabellen_payload)

    checks.append(_check_no_legacy_warning_fields(logic_payload, changelog_payload))
    checks.append(_check_group_integrity(pauschalen_list))
    checks.append(_check_condition_integrity(pauschalen_list))
    checks.append(_check_operator_tokens_in_values(pauschalen_list, table_names))
    checks.append(_check_connector_integrity(pauschalen_list))
    checks.append(_check_logic_tree_integrity(pauschalen_list))
    checks.append(_check_reference_cases(pauschale_lookup))

    all_issues: List[Issue] = [issue for check in checks for issue in check.issues]
    failed_checks = [check for check in checks if check.status == "fail"]
    passed_checks = [check for check in checks if check.status == "pass"]

    report: Dict[str, Any] = {
        "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "data_dir": str(data_dir),
        "inputs": {
            "logic_path": str(logic_path),
            "changelog_path": str(changelog_path),
            "tabellen_path": str(tabellen_path),
        },
        "logic_schema_version": logic_payload.get("logic_schema_version") if isinstance(logic_payload, dict) else None,
        "total_pauschalen": len(pauschalen_list),
        "summary": {
            "status": "pass" if not failed_checks else "fail",
            "total_checks": len(checks),
            "passed_checks": len(passed_checks),
            "failed_checks": len(failed_checks),
            "total_issues": len(all_issues),
        },
        "checks": [check.as_dict() for check in checks],
        "issues": [issue.as_dict() for issue in all_issues],
    }
    return report
