import sys, os, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import server


def test_chop_endpoint_basic():
    with server.app.test_client() as client:
        resp = client.get('/api/chop', query_string={'q': 'Z00'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert any(item.get('code') == 'Z00.12.00' for item in data)
        # Ensure freitext_payload is included in each result
        assert all('freitext_payload' in item for item in data)
