import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import server


def _extract_codes(results):
    return [item.get("code") for item in results]


def test_search_pauschalen_matches_hallux_valgus_with_extra_words():
    query = "Korrekturoperation Hallux valgus rechts"
    results = server.search_pauschalen(query)
    assert "C08.43A" in _extract_codes(results)


def test_search_pauschalen_matches_single_relevant_token():
    results = server.search_pauschalen("valgus")
    assert "C08.43A" in _extract_codes(results)
