import pytest
from fastapi.testclient import TestClient
from main import app, ADMIN_KEY

client = TestClient(app)

def test_admin_auth_required():
    response = client.post("/api/admin/sync")
    assert response.status_code == 401

def test_admin_auth_invalid():
    response = client.post("/api/admin/sync", headers={"X-Admin-Key": "wrong"})
    assert response.status_code == 403

def test_admin_auth_valid():
    # Will fail connection to polymarket or return 200/502 depending on network, but 403 means auth failed
    response = client.post("/api/admin/sync", headers={"X-Admin-Key": ADMIN_KEY})
    assert response.status_code in [200, 502]
