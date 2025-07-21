import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import server


def test_icd_endpoint_basic():
    with server.app.test_client() as client:
        resp = client.get('/api/icd', query_string={'q': 'T93.3', 'lang': 'de'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert any(item.get('code') == 'T93.3' for item in data)

def test_icd_search_by_table():
    with server.app.test_client() as client:
        resp = client.get('/api/icd', query_string={'q': 'Cap09', 'lang': 'de'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert all('Cap09' in item.get('tabelle') for item in data)
