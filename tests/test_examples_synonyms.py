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
class TestExampleSynonyms(unittest.TestCase):
    def setUp(self):
        server.app.config['TESTING'] = True

    @patch('server.perform_analysis')
    @patch('server.load_data', return_value=True)
    def test_blinddarm_example(self, _, mock_perform):
        mock_perform.return_value = {
            'abrechnung': {
                'type': 'Pauschale',
                'details': {'Pauschale': 'C06.00A'},
                'leistungen': []
            }
        }
        with server.app.test_client() as client:
            resp = client.post('/api/test-example', json={'id': 10, 'lang': 'de'})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get('passed'))

    @patch('server.perform_analysis')
    @patch('server.load_data', return_value=True)
    def test_rheuma_example(self, _, mock_perform):
        mock_perform.return_value = {
            'abrechnung': {
                'type': 'TARDOC',
                'leistungen': [
                    {'lkn': 'AA.00.0010', 'menge': 1},
                    {'lkn': 'AA.00.0020', 'menge': 15},
                    {'lkn': 'KF.05.0050', 'menge': 1},
                ]
            }
        }
        with server.app.test_client() as client:
            resp = client.post('/api/test-example', json={'id': 3, 'lang': 'de'})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get('passed'))

    @patch('server.perform_analysis')
    @patch('server.load_data', return_value=True)
    def test_warze_example(self, _, mock_perform):
        mock_perform.return_value = {
            'abrechnung': {
                'type': 'TARDOC',
                'leistungen': [
                    {'lkn': 'AA.00.0010', 'menge': 1},
                    {'lkn': 'AA.00.0020', 'menge': 5},
                    {'lkn': 'MK.05.0070', 'menge': 5},
                    {'lkn': 'AR.00.0030', 'menge': 1},
                ]
            }
        }
        with server.app.test_client() as client:
            resp = client.post('/api/test-example', json={'id': 2, 'lang': 'de'})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get('passed'))


if __name__ == '__main__':
    unittest.main()
