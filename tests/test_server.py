import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add the root directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import server

# --- Test Data ---
MOCK_LLM_RESPONSE = {
    "identified_leistungen": [
        {
            "lkn": "CA.00.0010",
            "typ": "E",
            "menge": 1
        },
        {
            "lkn": "CA.00.0020",
            "typ": "E",
            "menge": 12
        }
    ],
    "extracted_info": {
        "dauer_minuten": 17,
        "menge_allgemein": None,
        "alter": None,
        "geschlecht": None,
        "seitigkeit": "unbekannt",
        "anzahl_prozeduren": None
    },
    "begruendung_llm": "Die Konsultation dauerte 17 Minuten, was zu 1x CA.00.0010 und 12x CA.00.0020 führt."
}

def test_analyze_billing_with_mocked_llm():
    """
    Tests the /api/analyze-billing endpoint with a mocked LLM response.
    """
    with patch('server.call_gemini_stage1', MagicMock(return_value=MOCK_LLM_RESPONSE)) as mock_call_gemini:
        with server.app.test_client() as client:
            response = client.post('/api/analyze-billing', json={'inputText': 'Konsultation HAz, 17 Minuten'})
            assert response.status_code == 200
            data = response.get_json()

            # Check if 'beschreibung' is present in the response
            assert 'llm_ergebnis_stufe1' in data
            assert 'identified_leistungen' in data['llm_ergebnis_stufe1']
            for leistung in data['llm_ergebnis_stufe1']['identified_leistungen']:
                assert 'beschreibung' in leistung
                assert leistung['beschreibung'] is not None
                assert leistung['beschreibung'] != "N/A"


def test_analyze_billing_with_direct_lkn():
    """Input containing an explicit LKN should not cause a 400 error."""
    with patch('server.call_gemini_stage1', MagicMock(return_value=MOCK_LLM_RESPONSE)):
        with server.app.test_client() as client:
            response = client.post('/api/analyze-billing', json={'inputText': 'GG.15.0330 30 Minuten'})
            assert response.status_code == 200


def test_analyze_billing_with_unknown_lkn():
    """Even unknown LKN codes should not trigger a 400 response."""
    with patch('server.call_gemini_stage1', MagicMock(return_value=MOCK_LLM_RESPONSE)):
        with server.app.test_client() as client:
            response = client.post('/api/analyze-billing', json={'inputText': 'GG.99.9999 5 Minuten'})
            assert response.status_code == 200


def test_analyze_billing_with_mixed_lkn():
    """Codes like 'C08.SA.0700' should be accepted."""
    with patch('server.call_gemini_stage1', MagicMock(return_value=MOCK_LLM_RESPONSE)):
        with server.app.test_client() as client:
            response = client.post('/api/analyze-billing', json={'inputText': 'C08.SA.0700'})
            assert response.status_code == 200

def test_submit_feedback_local(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    with server.app.test_client() as client:
        resp = client.post('/api/submit-feedback', json={
            'category': 'Allgemein',
            'message': 'Unit test feedback',
            'context': {'url':'http://test','inputs':{'userInput':'foo'}}
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('status') == 'saved'
    stored = json.loads(Path('feedback_local.json').read_text(encoding='utf-8'))
    assert stored[-1]['message'] == 'Unit test feedback'
    assert stored[-1]['context']['inputs']['userInput'] == 'foo'
