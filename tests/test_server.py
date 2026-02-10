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

MOCK_LLM_RESPONSE_FR_MUSCLE = {
    "identified_leistungen": [
        {
            "lkn": "C02.CQ.0010",
            "typ": "E",
            "menge": 1,
        }
    ],
    "extracted_info": {
        "dauer_minuten": None,
        "menge_allgemein": 1,
        "alter": None,
        "geschlecht": None,
        "seitigkeit": "rechts",
        "anzahl_prozeduren": 1,
    },
    "begruendung_llm": "FR test response.",
}

MOCK_ANALOGIE_CANDIDATE = {
    "id": "OAAT-2026-C08.FA.0030",
    "analogie_code": "C08.FA.0030",
    "reserve_code": "C00.YY.0010",
    "beschreibung": "Versorgung einer Fraktur u/o Luxation, geschlossene Reposition mit aeusserer Schienung, Handgelenk/Handwurzelknochen/distaler Radius/distale Ulna",
    "beschreibung_fr": "Traitement d'une fracture et/ou luxation, reduction fermee avec attelle externe, poignet/os du carpe/radius distal/ulna distale",
    "beschreibung_it": "Trattamento di frattura e/o lussazione, riduzione chiusa con steccatura esterna, polso/ossa del carpo/radio distale/ulna distale",
    "hinweis": "Reservecode dient ausschliesslich der Dokumentation und hat keinen Leistungsbezug.",
    "gueltig_ab": "2026-01-01",
    "gueltig_bis": "2026-12-31",
    "quelle": "OAAT Bulletin",
}

def test_parse_llm_json_response_with_trailing_text():
    raw = json.dumps(MOCK_LLM_RESPONSE) + " Hinweis"
    parsed = server.parse_llm_json_response(raw)
    # Help type checkers: this test expects a dict response
    assert isinstance(parsed, dict)
    assert parsed["identified_leistungen"][0]["lkn"] == "CA.00.0010"


def test_validate_stage1_result_with_list_of_lkn_dicts():
    raw = [
        {"lkn": "ca.00.0010", "menge": "2"},
        {"code": "AA.00.0020", "qty": 1},
    ]
    parsed = server.validate_stage1_result(raw, provider_label="TEST_S1")
    assert [item["lkn"] for item in parsed["identified_leistungen"]] == ["CA.00.0010", "AA.00.0020"]
    assert parsed["identified_leistungen"][0]["menge"] == 2
    assert parsed["identified_leistungen"][1]["menge"] == 1


def test_validate_stage1_result_with_list_of_codes():
    parsed = server.validate_stage1_result(["ca.00.0010", "AA.00.0020"], provider_label="TEST_S1")
    assert [item["lkn"] for item in parsed["identified_leistungen"]] == ["CA.00.0010", "AA.00.0020"]
    assert all(item["menge"] == 1 for item in parsed["identified_leistungen"])


def test_validate_stage1_result_with_unstructured_list_fallbacks_to_empty():
    parsed = server.validate_stage1_result(["keine verwertbare liste", None, 0], provider_label="TEST_S1")
    assert parsed["identified_leistungen"] == []
    assert parsed["extracted_info"]["seitigkeit"] == "unbekannt"


def test_analyze_billing_with_mocked_llm():
    """
    Tests the /api/analyze-billing endpoint with a mocked LLM response.
    """
    with patch('server.call_gemini_stage1', MagicMock(return_value=MOCK_LLM_RESPONSE)):
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


def test_french_context_localization():
    captured = {}

    def fake_stage1(user_input, katalog_context, model, lang, **kwargs):
        captured['context'] = katalog_context
        return MOCK_LLM_RESPONSE

    with patch('server.call_gemini_stage1', side_effect=fake_stage1):
        with server.app.test_client() as client:
            resp = client.post('/api/analyze-billing', json={'inputText': 'AA.00.0010', 'lang': 'fr'})
            assert resp.status_code == 200

    context = captured.get('context', '')
    assert 'Consultation médicale' in context
    assert 'Ärztliche Konsultation' not in context
    assert 'Consultazione medica' not in context


def test_italian_context_localization():
    captured = {}

    def fake_stage1(user_input, katalog_context, model, lang, **kwargs):
        captured['context'] = katalog_context
        return MOCK_LLM_RESPONSE

    with patch('server.call_gemini_stage1', side_effect=fake_stage1):
        with server.app.test_client() as client:
            resp = client.post('/api/analyze-billing', json={'inputText': 'AA.00.0010', 'lang': 'it'})
            assert resp.status_code == 200

    context = captured.get('context', '')
    assert 'Consultazione medica' in context
    assert 'Ärztliche Konsultation' not in context
    assert 'Consultation médicale' not in context


def test_test_example_french_muscle():
    with patch('server.call_gemini_stage1', MagicMock(return_value=MOCK_LLM_RESPONSE_FR_MUSCLE)):
        with server.app.test_client() as client:
            resp = client.post('/api/test-example', json={'id': 18, 'lang': 'fr'})
            assert resp.status_code == 200
            data = resp.get_json() or {}
            assert data.get('passed') is True
            assert data.get('result', {}).get('pauschale', {}).get('code') == 'C02.25D'

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


def test_version_endpoint():
    with server.app.test_client() as client:
        resp = client.get('/api/version')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('version') == server.APP_VERSION
        assert data.get('tarif_version') == server.TARIF_VERSION


def test_find_analogie_match_short_wrist_phrase():
    match = server._find_analogie_match("Handgelenk, Fraktur, geschlossene Reposition", "de")
    assert match is not None
    assert match.get("analogie_code") == "C08.FA.0030"


def test_analogie_is_attached_to_pauschale_even_without_stage1_lkn_match():
    stage1_result = {
        "identified_leistungen": [
            {"lkn": "C08.AA.0010", "typ": "E", "menge": 1, "beschreibung": "Dummy"},
        ],
        "extracted_info": {
            "dauer_minuten": None,
            "menge_allgemein": None,
            "alter": None,
            "geschlecht": None,
            "seitigkeit": "unbekannt",
            "anzahl_prozeduren": None,
        },
        "begruendung_llm": "test",
    }
    mapped_rule_checked = [{"lkn": "C08.AA.0010", "typ": "E", "menge": 1, "beschreibung": "Dummy"}]
    pauschale_response = {
        "type": "Pauschale",
        "details": {
            "Pauschale": "C08.50C",
            "Taxpunkte": "100",
        },
    }
    with patch("server.call_llm_stage1", MagicMock(return_value=(stage1_result, {"input_tokens": 1, "output_tokens": 1}))):
        with patch("server._build_context_for_llm", MagicMock(return_value=("", [], []))):
            with patch("server._validate_and_apply_rules", MagicMock(return_value=(mapped_rule_checked, []))):
                with patch("server._find_analogie_match", MagicMock(return_value=dict(MOCK_ANALOGIE_CANDIDATE))):
                    with patch("server._determine_final_billing", MagicMock(return_value=(dict(pauschale_response), {}))):
                        with server.app.test_client() as client:
                            resp = client.post('/api/analyze-billing', json={'inputText': 'Dummy Input', 'lang': 'de'})
                            assert resp.status_code == 200
                            data = resp.get_json() or {}
                            abrechnung = data.get("abrechnung", {})
                            details = abrechnung.get("details", {})
                            analogie = details.get("analogie", {})
                            assert abrechnung.get("type") == "Pauschale"
                            assert details.get("Pauschale") == "C08.50C"
                            assert analogie.get("analogie_code") == "C08.FA.0030"
                            assert analogie.get("reserve_code") == "C00.YY.0010"
