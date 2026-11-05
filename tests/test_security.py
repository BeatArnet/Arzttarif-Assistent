"""Regression tests for public routes and request validation."""

import pytest

import server


@pytest.fixture
def client():
    return server.app.test_client()


@pytest.mark.parametrize("path", [
    "/config.ini", "/config.runtime.json", "/.env", "/.git/config",
    "/server.py", "/feedback_local.json", "/data/synonyms.json",
    "/data/vektor_index.faiss", "/brick_quiz/excel_to_json.py",
])
def test_internal_files_are_not_public(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", [
    "/", "/calculator.js", "/translations.json", "/data/beispiele.json",
    "/data/DIGNITAETEN.json", "/favicon.ico",
])
def test_frontend_assets_remain_public(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("payload", [[], {"inputText": 123},
                                     {"inputText": "test", "icd": None}])
def test_invalid_billing_payload_returns_400(client, payload):
    assert client.post("/api/analyze-billing", json=payload).status_code == 400


def test_large_request_is_rejected(client):
    response = client.post("/api/analyze-billing", json={"inputText": "x" * (1024 * 1024)})
    assert response.status_code == 413
