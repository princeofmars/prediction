import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from main import app, ADMIN_KEY

client = TestClient(app)

def test_admin_auth_required():
    response = client.post("/api/admin/sync")
    assert response.status_code == 401

def test_admin_auth_invalid():
    response = client.post("/api/admin/sync", headers={"X-Admin-Key": "wrong"})
    assert response.status_code == 403

@patch('main.sync_markets_logic')
def test_admin_auth_valid_mocked(mock_sync):
    # Mock network call to isolate auth test
    mock_sync.return_value = 5 
    response = client.post("/api/admin/sync", headers={"X-Admin-Key": ADMIN_KEY})
    assert response.status_code == 200
    assert response.json()["added"] == 5

def test_agent_prediction_unauthorized():
    # Attempt to post a prediction without an X-Agent-Key header
    payload = {
        "market_id": 1,
        "probability_yes": 0.5,
        "confidence_score": 0.9,
        "reasoning": "Test reasoning"
    }
    response = client.post("/predictions", json=payload)
    assert response.status_code == 401
    assert "Missing Agent API Key" in response.json()["detail"]
