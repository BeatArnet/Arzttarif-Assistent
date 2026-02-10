"""Run repeatable PAUSCHALEN quality checks and create visual reports.

Usage:
    python run_pauschalen_quality_control.py
"""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any, Dict

from quality_control.pauschalen_quality_control import run_quality_checks


def _build_html_report(report: Dict[str, Any], max_issues: int) -> str:
    summary = report.get("summary") or {}
    checks = report.get("checks") or []
    issues = report.get("issues") or []

    total_checks = int(summary.get("total_checks") or 0)
    passed_checks = int(summary.get("passed_checks") or 0)
    failed_checks = int(summary.get("failed_checks") or 0)
    total_issues = int(summary.get("total_issues") or 0)
    pass_ratio = (passed_checks / total_checks * 100.0) if total_checks else 0.0
    status = str(summary.get("status") or "fail").lower()
    status_label = "PASS" if status == "pass" else "FAIL"
    status_class = "status-pass" if status == "pass" else "status-fail"

    checks_rows = []
    for check in checks:
        check_status = str(check.get("status") or "fail")
        issue_count = int(check.get("issue_count") or 0)
        checks_rows.append(
            "<tr>"
            f"<td>{escape(str(check.get('id') or ''))}</td>"
            f"<td>{escape(str(check.get('title') or ''))}</td>"
            f"<td class=\"{'ok' if check_status == 'pass' else 'bad'}\">{escape(check_status.upper())}</td>"
            f"<td>{issue_count}</td>"
            "</tr>"
        )

    issues_rows = []
    displayed_issues = issues[:max_issues]
    for issue in displayed_issues:
        details = issue.get("details")
        detail_text = ""
        if details:
            detail_text = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
        issues_rows.append(
            "<tr>"
            f"<td>{escape(str(issue.get('check_id') or ''))}</td>"
            f"<td>{escape(str(issue.get('severity') or ''))}</td>"
            f"<td>{escape(str(issue.get('pauschale') or ''))}</td>"
            f"<td>{escape(str(issue.get('location') or ''))}</td>"
            f"<td>{escape(str(issue.get('message') or ''))}</td>"
            f"<td>{escape(detail_text)}</td>"
            "</tr>"
        )

    issues_note = ""
    if len(displayed_issues) < len(issues):
        issues_note = (
            f"<p class=\"note\">Es werden {len(displayed_issues)} von {len(issues)} Issues angezeigt. "
            "JSON-Report enthält alle Einträge.</p>"
        )

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pauschalen Quality Report</title>
  <style>
    :root {{
      --ok: #0a7f3f;
      --bad: #b42318;
      --ink: #1f2937;
      --muted: #64748b;
      --bg: #f7fafc;
      --card: #ffffff;
      --line: #e2e8f0;
      --bar-bg: #e2e8f0;
      --accent: #1363df;
    }}
    body {{
      margin: 0;
      padding: 24px;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    .wrap {{
      max-width: 1200px;
      margin: 0 auto;
      display: grid;
      gap: 16px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px;
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
    }}
    h1 {{
      margin: 0;
      font-size: 1.5rem;
    }}
    .meta {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .status-chip {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 6px 12px;
      color: #fff;
      font-weight: 700;
      font-size: 0.85rem;
      letter-spacing: 0.04em;
    }}
    .status-pass {{ background: var(--ok); }}
    .status-fail {{ background: var(--bad); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      background: #fff;
    }}
    .metric .k {{
      font-size: 0.8rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .metric .v {{
      font-size: 1.25rem;
      font-weight: 700;
      margin-top: 4px;
    }}
    .bar {{
      margin-top: 8px;
      width: 100%;
      height: 12px;
      border-radius: 999px;
      overflow: hidden;
      background: var(--bar-bg);
    }}
    .bar > span {{
      display: block;
      height: 100%;
      width: {pass_ratio:.2f}%;
      background: linear-gradient(90deg, var(--accent), #1d9bf0);
    }}
    .table-wrap {{
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #f8fafc;
      color: #0f172a;
      font-weight: 600;
    }}
    .ok {{
      color: var(--ok);
      font-weight: 700;
    }}
    .bad {{
      color: var(--bad);
      font-weight: 700;
    }}
    .note {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.88rem;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="card">
      <h1>Pauschalen Quality Control Report</h1>
      <div class="meta">Generiert am: {escape(str(report.get("generated_at") or ""))}</div>
      <div class="meta">Schema-Version: {escape(str(report.get("logic_schema_version") or ""))}</div>
      <div class="meta">Quelle: {escape(str((report.get("inputs") or {}).get("logic_path") or ""))}</div>
      <div style="margin-top: 12px;">
        <span class="status-chip {status_class}">{status_label}</span>
      </div>
      <div class="bar"><span></span></div>
      <div class="meta">{pass_ratio:.1f}% Checks bestanden</div>
    </section>

    <section class="card">
      <div class="grid">
        <div class="metric"><div class="k">Pauschalen</div><div class="v">{int(report.get("total_pauschalen") or 0)}</div></div>
        <div class="metric"><div class="k">Checks gesamt</div><div class="v">{total_checks}</div></div>
        <div class="metric"><div class="k">Checks ok</div><div class="v">{passed_checks}</div></div>
        <div class="metric"><div class="k">Checks fail</div><div class="v">{failed_checks}</div></div>
        <div class="metric"><div class="k">Issues gesamt</div><div class="v">{total_issues}</div></div>
      </div>
    </section>

    <section class="card">
      <h2>Check-Übersicht</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>ID</th><th>Check</th><th>Status</th><th>Issues</th></tr>
          </thead>
          <tbody>
            {''.join(checks_rows)}
          </tbody>
        </table>
      </div>
    </section>

    <section class="card">
      <h2>Issue-Details</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Check</th><th>Severity</th><th>Pauschale</th><th>Location</th><th>Message</th><th>Details</th></tr>
          </thead>
          <tbody>
            {''.join(issues_rows) if issues_rows else '<tr><td colspan="6" class="ok">Keine Issues.</td></tr>'}
          </tbody>
        </table>
      </div>
      {issues_note}
    </section>
  </div>
</body>
</html>
"""


def _parse_args() -> argparse.Namespace:
    default_data_dir = Path(__file__).resolve().parent / "data"
    default_report_dir = Path(__file__).resolve().parent / "quality_reports"
    parser = argparse.ArgumentParser(description="Run PAUSCHALEN quality control checks.")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir, help="Directory with JSON exports.")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=default_report_dir / "pauschalen_quality_report.json",
        help="Path for machine-readable report JSON.",
    )
    parser.add_argument(
        "--html-out",
        type=Path,
        default=default_report_dir / "pauschalen_quality_report.html",
        help="Path for visual HTML report.",
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        default=500,
        help="Maximum number of issue rows rendered in HTML report.",
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Always exit with code 0, even when checks fail.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = run_quality_checks(args.data_dir)

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.html_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    args.html_out.write_text(_build_html_report(report, max_issues=max(1, args.max_issues)), encoding="utf-8")

    summary = report.get("summary") or {}
    status = str(summary.get("status") or "fail").lower()
    print(f"Quality status: {status.upper()}")
    print(f"Checks: {summary.get('passed_checks')}/{summary.get('total_checks')} passed")
    print(f"Issues: {summary.get('total_issues')}")
    print(f"JSON report: {args.json_out}")
    print(f"HTML report: {args.html_out}")

    if status != "pass" and not args.no_strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
