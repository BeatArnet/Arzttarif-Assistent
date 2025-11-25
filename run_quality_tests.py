"""Smoke-Test-Werkzeug zur Validierung der Qualitäts-Baseline.

Das Skript startet die Flask-Anwendung im Testmodus, spielt alle Einträge aus
``data/baseline_results.json`` gegen den Endpunkt ``/api/test-example`` und
fasst die Erfolgsquote zusammen. Eine zusätzliche Funktion stößt eine Auswahl
an ``pytest``-Tests an, die sich auf die Abrechnungsregeln konzentrieren. Vor
Änderungen an Prompts oder Regeln lokal mit ``python run_quality_tests.py``
ausführen.
"""

import json
import logging
import math
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env file at the very beginning
load_dotenv()

from server import app

BASELINE_PATH = Path(__file__).resolve().parent / "data" / "baseline_results.json"


def run_tests() -> None:
    """Run /api/test-example for all examples, print summary and performance stats."""
    # Load baseline data directly from file
    with BASELINE_PATH.open("r", encoding="utf-8") as f:
        baseline_data = json.load(f)

    # Daten sollten durch den Import von server (und damit create_app) bereits geladen sein.
    # Überprüfe hier den Status von daten_geladen aus dem server Modul.
    from server import daten_geladen as server_daten_geladen
    if not server_daten_geladen:
        logger.error(
            "Fehler: Server-Daten wurden nicht korrekt initialisiert. Tests können nicht ausgeführt werden."
        )
        return

    results: List[bool] = []
    test_records: List[Dict[str, object]] = []
    perf_metrics = {
        "durations": [],  # Sekunden pro Testfall
        "token_usage": {
            "llm_stage1": {"input_tokens": 0, "output_tokens": 0},
            "llm_stage2": {"input_tokens": 0, "output_tokens": 0},
        },
    }

    def _accumulate_tokens(target: Dict[str, Dict[str, int]], source: Dict[str, object]) -> None:
        """Summiert Tokenzahlen aus einer Antwort in die Gesamtstatistik."""
        for stage in ("llm_stage1", "llm_stage2"):
            tgt = target.setdefault(stage, {"input_tokens": 0, "output_tokens": 0})
            src = source.get(stage) if isinstance(source, dict) else {}
            if not isinstance(src, dict):
                continue
            tgt["input_tokens"] = int(tgt.get("input_tokens", 0) or 0) + int(src.get("input_tokens", 0) or 0)
            tgt["output_tokens"] = int(tgt.get("output_tokens", 0) or 0) + int(src.get("output_tokens", 0) or 0)

    def _percentile(values: List[float], pct: float) -> float:
        """Einfaches Quantil (0..1) für kleine Samples ohne externes Paket."""
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * pct
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)

    suite_started = time.perf_counter()
    with app.test_client() as client:
        # Nutzt bewusst die öffentliche API, wie es auch das Web-Frontend tun würde.
        for ex_id, entry in baseline_data.items():
            langs = list(entry.get("query", {}).keys())
            for lang in langs:
                test_started = time.perf_counter()
                resp = client.post(
                    "/api/test-example",
                    json={"id": int(ex_id), "lang": lang},
                )
                duration = time.perf_counter() - test_started
                perf_metrics["durations"].append(duration)

                if resp.status_code != 200:
                    logger.error(
                        "Beispiel %s [%s] Fehler: HTTP %s (%.2fs)",
                        ex_id,
                        lang,
                        resp.status_code,
                        duration,
                    )
                    results.append(False)
                    test_records.append(
                        {"id": ex_id, "lang": lang, "passed": False, "duration": duration}
                    )
                    continue

                data = resp.get_json() or {}
                token_usage = data.get("token_usage") if isinstance(data, dict) else {}
                _accumulate_tokens(perf_metrics["token_usage"], token_usage if isinstance(token_usage, dict) else {})

                passed = bool(data.get("passed"))
                diff = data.get("diff", "")
                status = "PASS" if passed else "FAIL"
                logger.info(
                    "Beispiel %s [%s]: %s%s (%.2fs)",
                    ex_id,
                    lang,
                    status,
                    f" - {diff}" if diff else "",
                    duration,
                )
                results.append(passed)
                test_records.append(
                    {"id": ex_id, "lang": lang, "passed": passed, "duration": duration}
                )

    total = len(results)
    passed_count = sum(1 for r in results if r)
    suite_elapsed = time.perf_counter() - suite_started

    durations = perf_metrics["durations"]
    avg_duration = sum(durations) / len(durations) if durations else 0.0
    median_duration = statistics.median(durations) if durations else 0.0
    p95_duration = _percentile(durations, 0.95)

    logger.info(
        "\n%s/%s Tests bestanden (%.1f%%). Gesamtzeit: %.2fs | Ø %.2fs | Median %.2fs | p95 %.2fs",
        passed_count,
        total,
        (passed_count / total * 100) if total else 0,
        suite_elapsed,
        avg_duration,
        median_duration,
        p95_duration,
    )

    def _duration_key(record: Dict[str, object]) -> float:
        """Return duration as float for sorting, fallback 0.0."""
        value: Any = record.get("duration")
        try:
            return float(value)
        except Exception:
            return 0.0

    slowest = sorted(test_records, key=_duration_key, reverse=True)[:3]
    for rec in slowest:
        logger.info(
            "Langsam: Beispiel %s [%s] %.2fs (%s)",
            rec.get("id"),
            rec.get("lang"),
            rec.get("duration", 0.0),
            "PASS" if rec.get("passed") else "FAIL",
        )

    tok = perf_metrics["token_usage"]
    s1_in = tok.get("llm_stage1", {}).get("input_tokens", 0)
    s1_out = tok.get("llm_stage1", {}).get("output_tokens", 0)
    s2_in = tok.get("llm_stage2", {}).get("input_tokens", 0)
    s2_out = tok.get("llm_stage2", {}).get("output_tokens", 0)
    logger.info(
        "Tokenverbrauch gesamt: Stage1 %s in / %s out | Stage2 %s in / %s out",
        s1_in,
        s1_out,
        s2_in,
        s2_out,
    )


import pytest

def run_pytest_tests():
    """Runs all pytest tests."""
    test_files = [
        "tests/test_server.py",
        "tests/test_pauschale_logic.py",
        "tests/test_pauschale_selection.py",
    ]
    for test_file in test_files:
        if Path(test_file).exists():
            logger.info(f"Running tests for {test_file}")
            pytest.main([test_file])
        else:
            logger.warning(f"Test file not found: {test_file}")

if __name__ == "__main__":
    run_tests()
    run_pytest_tests()
