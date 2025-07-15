import json
import logging
from pathlib import Path
from typing import List
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env file at the very beginning
load_dotenv()

from server import app

BASELINE_PATH = Path(__file__).resolve().parent / "data" / "baseline_results.json"


def run_tests() -> None:
    """Run /api/test-example for all examples and print summary."""
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

    with app.test_client() as client:
        for ex_id, entry in baseline_data.items():
            langs = list(entry.get("query", {}).keys())
            for lang in langs:
                resp = client.post(
                    "/api/test-example",
                    json={"id": int(ex_id), "lang": lang},
                )
                if resp.status_code != 200:
                    logger.error(
                        "Beispiel %s [%s] Fehler: HTTP %s",
                        ex_id,
                        lang,
                        resp.status_code,
                    )
                    results.append(False)
                    continue

                data = resp.get_json() or {}
                passed = bool(data.get("passed"))
                diff = data.get("diff", "")
                status = "PASS" if passed else "FAIL"
                logger.info(
                    "Beispiel %s [%s]: %s%s",
                    ex_id,
                    lang,
                    status,
                    f" - {diff}" if diff else "",
                )
                results.append(passed)

    total = len(results)
    passed_count = sum(1 for r in results if r)
    logger.info("\n%s/%s Tests bestanden.", passed_count, total)


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
