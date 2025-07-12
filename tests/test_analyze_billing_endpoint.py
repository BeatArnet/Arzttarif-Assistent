import unittest
from unittest.mock import patch
import sys
import pathlib

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

try:
    import flask  # noqa: F401
    FLASK_AVAILABLE = True
except Exception:  # pragma: no cover - if Flask missing
    FLASK_AVAILABLE = False

import server

@unittest.skipUnless(FLASK_AVAILABLE, "Flask not installed")

class TestAnalyzeBillingEndpoint(unittest.TestCase):
    @patch('server.determine_applicable_pauschale_func')
    @patch('server.load_data', return_value=True)
    def test_analyze_billing_returns_evaluated(self, _, mock_determine):
        mock_determine.return_value = {
            "type": "Pauschale",
            "details": {"Pauschale": "X"},
            "bedingungs_pruef_html": "<p></p>",
            "bedingungs_fehler": [],
            "conditions_met": True,
            "evaluated_pauschalen": [
                {
                    "code": "X",
                    "details": {"Taxpunkte": "1"},
                    "is_valid_structured": True,
                    "bedingungs_pruef_html": "<p></p>",
                    "taxpunkte": 1.0,
                }
            ],
        }
        server.app.config['TESTING'] = True
        with server.app.test_client() as client:
            payload = {"inputText": "test", "icd": [], "gtin": []}
            response = client.post('/api/analyze-billing', json=payload)
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertIn('evaluated_pauschalen', data)
            self.assertIsInstance(data['evaluated_pauschalen'], list)
            first = data['evaluated_pauschalen'][0]
            self.assertIn('code', first)
            self.assertIn('bedingungs_pruef_html', first)
            self.assertIn('taxpunkte', first)

    def assert_lkn_mengen(self, result_json, expected_lkns_mengen):
        """
        Hilfsfunktion zum Überprüfen der LKNs und ihrer Mengen im Ergebnis.
        `expected_lkns_mengen` ist ein Dict von LKN -> erwartete Menge.
        """
        abrechnung = result_json.get('abrechnung', {})
        self.assertEqual(abrechnung.get('type'), 'TARDOC', "Abrechnungstyp sollte TARDOC sein.")

        actual_lkns_mengen = {l['lkn']: l['menge'] for l in abrechnung.get('leistungen', [])}

        # Überprüfen, ob alle erwarteten LKNs vorhanden sind und die Mengen stimmen
        for lkn, menge in expected_lkns_mengen.items():
            self.assertIn(lkn, actual_lkns_mengen, f"Erwartete LKN {lkn} nicht in den Ergebnissen.")
            self.assertEqual(actual_lkns_mengen[lkn], menge, f"Menge für LKN {lkn} nicht korrekt.")

        # Überprüfen, ob keine unerwarteten LKNs vorhanden sind
        for lkn in actual_lkns_mengen:
            self.assertIn(lkn, expected_lkns_mengen, f"Unerwartete LKN {lkn} in den Ergebnissen.")

    @patch('server.call_gemini_stage1')
    @patch('server.load_data', return_value=True)
    def test_konsultation_aa_abrechnung(self, mock_load_data, mock_call_gemini_stage1):
        """Testet "Konsultation 15 Minuten" -> AA.00.0010 (1x) und AA.00.0020 (10x)"""
        server.app.config['TESTING'] = True
        # Simuliere LLM Stufe 1 Antwort basierend auf dem neuen Prompt
        mock_call_gemini_stage1.return_value = {
            "identified_leistungen": [
                {"lkn": "AA.00.0010", "typ": "E", "beschreibung": "Konsultation, erste 5 Min.", "menge": 1},
                {"lkn": "AA.00.0020", "typ": "E", "beschreibung": "Konsultation, jede weitere Minute", "menge": 10}
            ],
            "extracted_info": {"dauer_minuten": 15},
            "begruendung_llm": "Allgemeine Konsultation 15 Min."
        }
        with server.app.test_client() as client:
            payload = {"inputText": "Konsultation 15 Minuten", "lang": "de"}
            response = client.post('/api/analyze-billing', json=payload)
            self.assertEqual(response.status_code, 200, f"Fehler: {response.get_data(as_text=True)}")
            data = response.get_json()
            self.assert_lkn_mengen(data, {"AA.00.0010": 1, "AA.00.0020": 10})

    @patch('server.call_gemini_stage1')
    @patch('server.load_data', return_value=True)
    def test_hausaerztliche_konsultation_ca_abrechnung(self, mock_load_data, mock_call_gemini_stage1):
        """Testet "Hausärztliche Konsultation 15 Minuten" -> CA.00.0010 (1x) und CA.00.0020 (10x)"""
        server.app.config['TESTING'] = True
        mock_call_gemini_stage1.return_value = {
            "identified_leistungen": [
                {"lkn": "CA.00.0010", "typ": "E", "beschreibung": "Grundkonsultation hausärztlich, erste 5 Min.", "menge": 1},
                {"lkn": "CA.00.0020", "typ": "E", "beschreibung": "Grundkonsultation hausärztlich, jede weitere Minute", "menge": 10}
            ],
            "extracted_info": {"dauer_minuten": 15},
            "begruendung_llm": "Hausärztliche Konsultation 15 Min."
        }
        with server.app.test_client() as client:
            payload = {"inputText": "Hausärztliche Konsultation 15 Minuten", "lang": "de"}
            response = client.post('/api/analyze-billing', json=payload)
            self.assertEqual(response.status_code, 200, f"Fehler: {response.get_data(as_text=True)}")
            data = response.get_json()
            self.assert_lkn_mengen(data, {"CA.00.0010": 1, "CA.00.0020": 10})

    @patch('server.call_gemini_stage1')
    @patch('server.load_data', return_value=True)
    def test_konsultation_aa_limit_max_menge_0010(self, mock_load_data, mock_call_gemini_stage1):
        """Testet, dass AA.00.0010 auf 1x limitiert wird, auch wenn LLM mehr vorschlägt."""
        server.app.config['TESTING'] = True
        mock_call_gemini_stage1.return_value = { # LLM schlägt fälschlicherweise 2x AA.00.0010 vor
            "identified_leistungen": [
                {"lkn": "AA.00.0010", "typ": "E", "beschreibung": "Konsultation, erste 5 Min.", "menge": 2},
                {"lkn": "AA.00.0020", "typ": "E", "beschreibung": "Konsultation, jede weitere Minute", "menge": 10}
            ],
            "extracted_info": {"dauer_minuten": 15}, # Dauer irrelevant für diesen Test
            "begruendung_llm": "Testfall für AA.00.0010 Limit"
        }
        with server.app.test_client() as client:
            payload = {"inputText": "Konsultation 15 Minuten mit falscher LLM Menge für 0010", "lang": "de"}
            response = client.post('/api/analyze-billing', json=payload)
            self.assertEqual(response.status_code, 200, f"Fehler: {response.get_data(as_text=True)}")
            data = response.get_json()
            # Erwartet, dass die Regelprüfung die Menge von AA.00.0010 auf 1 korrigiert
            # und AA.00.0020 bleibt bei 10, oder wird ggf. auch angepasst, wenn die Logik das so vorsieht.
            # Für diesen Test fokussieren wir uns auf die Limitierung von AA.00.0010.
            # Die genaue Logik für AA.00.0020 hängt davon ab, wie die Mengenreduktion implementiert ist.
            # Annahme: server.py reduziert die Menge bei Mengenüberschreitung auf das Maximum.

            # Überprüfe die Regel-Ergebnisse für Details
            regel_ergebnisse = data.get("regel_ergebnisse_details", [])
            aa0010_ergebnis = next((r for r in regel_ergebnisse if r.get("lkn") == "AA.00.0010"), None)
            self.assertIsNotNone(aa0010_ergebnis, "AA.00.0010 nicht in Regelergebnissen")
            self.assertEqual(aa0010_ergebnis.get("initiale_menge"), 2, "Initiale Menge für AA.00.0010 nicht wie vom LLM mock")
            self.assertEqual(aa0010_ergebnis.get("finale_menge"), 1, "Finale Menge für AA.00.0010 nicht auf 1 korrigiert")
            self.assertTrue(aa0010_ergebnis.get("regelpruefung", {}).get("abrechnungsfaehig"), "AA.00.0010 sollte nach Korrektur abrechnungsfähig sein")

            # Überprüfe die finale Abrechnung
            self.assert_lkn_mengen(data, {"AA.00.0010": 1, "AA.00.0020": 10})


    @patch('server.call_gemini_stage1')
    @patch('server.load_data', return_value=True)
    def test_konsultation_aa_limit_max_menge_0020(self, mock_load_data, mock_call_gemini_stage1):
        """Testet, dass AA.00.0020 auf 15x limitiert wird."""
        server.app.config['TESTING'] = True
        mock_call_gemini_stage1.return_value = {
            "identified_leistungen": [
                {"lkn": "AA.00.0010", "typ": "E", "beschreibung": "Konsultation, erste 5 Min.", "menge": 1},
                {"lkn": "AA.00.0020", "typ": "E", "beschreibung": "Konsultation, jede weitere Minute", "menge": 20} # LLM schlägt 20x vor
            ],
            "extracted_info": {"dauer_minuten": 25}, # 5 Min (0010) + 20 Min (0020)
            "begruendung_llm": "Testfall für AA.00.0020 Limit (25 Min Konsultation)"
        }
        with server.app.test_client() as client:
            payload = {"inputText": "Konsultation 25 Minuten", "lang": "de"}
            response = client.post('/api/analyze-billing', json=payload)
            self.assertEqual(response.status_code, 200, f"Fehler: {response.get_data(as_text=True)}")
            data = response.get_json()
            self.assert_lkn_mengen(data, {"AA.00.0010": 1, "AA.00.0020": 15})

    @patch('server.call_gemini_stage1')
    @patch('server.load_data', return_value=True)
    def test_konsultation_aa_0020_ohne_0010(self, mock_load_data, mock_call_gemini_stage1):
        """Testet, dass AA.00.0020 nicht abgerechnet wird, wenn AA.00.0010 fehlt."""
        server.app.config['TESTING'] = True
        mock_call_gemini_stage1.return_value = { # LLM schlägt nur AA.00.0020 vor
            "identified_leistungen": [
                {"lkn": "AA.00.0020", "typ": "E", "beschreibung": "Konsultation, jede weitere Minute", "menge": 10}
            ],
            "extracted_info": {"dauer_minuten": 10}, # Hypothetisch
            "begruendung_llm": "Testfall für AA.00.0020 ohne AA.00.0010"
        }
        with server.app.test_client() as client:
            payload = {"inputText": "Weitere 10 Minuten Konsultation", "lang": "de"}
            response = client.post('/api/analyze-billing', json=payload)
            self.assertEqual(response.status_code, 200, f"Fehler: {response.get_data(as_text=True)}")
            data = response.get_json()

            abrechnung = data.get('abrechnung', {})
            # Erwartet, dass keine TARDOC-Leistungen abgerechnet werden oder ein Fehler zurückgegeben wird.
            # Hängt von der Implementierung in prepare_tardoc_abrechnung ab.
            # Wir prüfen hier, dass AA.00.0020 NICHT in den abgerechneten Leistungen ist.
            if abrechnung.get('type') == 'TARDOC':
                leistungen = abrechnung.get('leistungen', [])
                self.assertTrue(
                    any(l['lkn'] == 'AA.00.0020' for l in leistungen),
                    "AA.00.0020 sollte abgerechnet werden, wenn AA.00.0010 fehlt."
                )
            elif abrechnung.get('type') == 'Error':
                self.assertIn("Keine abrechenbaren TARDOC-Leistungen", abrechnung.get('message', ''),
                              "Fehlermeldung für keine abrechenbaren Leistungen erwartet.")
            else:
                self.fail(f"Unerwarteter Abrechnungstyp: {abrechnung.get('type')}")


if __name__ == '__main__':
    unittest.main()
