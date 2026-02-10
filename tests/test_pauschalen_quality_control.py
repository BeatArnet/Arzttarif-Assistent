from __future__ import annotations

from pathlib import Path

from quality_control.pauschalen_quality_control import run_quality_checks


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def _format_failed_checks(report: dict) -> str:
    checks = report.get("checks") or []
    failed = [c for c in checks if str(c.get("status")) == "fail"]
    if not failed:
        return ""
    lines = []
    for check in failed:
        lines.append(f"- {check.get('id')}: {check.get('issue_count')} issues")
    return "\n".join(lines)


def test_pauschalen_quality_report_is_green() -> None:
    report = run_quality_checks(DATA_DIR)
    assert report.get("summary", {}).get("status") == "pass", _format_failed_checks(report)


def test_reference_cases_check_is_green() -> None:
    report = run_quality_checks(DATA_DIR)
    checks = report.get("checks") or []
    reference_check = next((c for c in checks if c.get("id") == "reference_cases"), None)
    assert reference_check is not None, "reference_cases check missing"
    assert reference_check.get("status") == "pass", str(reference_check)

