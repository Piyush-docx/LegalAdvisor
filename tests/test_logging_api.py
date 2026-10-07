from fastapi.testclient import TestClient
import pytest
from src.api import app
from src.db import get_db

client = TestClient(app)

def test_admin_logs_endpoint_forbidden():
    # Attempt without token
    response = client.get("/admin/logs")
    assert response.status_code == 401
    
    # Attempt with normal user
    # Send OTP
    client.post("/auth/send-otp", json={"email": "normal@example.com"})
    conn = get_db()
    with conn:
        code = conn.execute("SELECT otp_code FROM otps WHERE email='normal@example.com' ORDER BY id DESC LIMIT 1").fetchone()[0]
        
    verify_res = client.post("/auth/verify-otp", json={"email": "normal@example.com", "otp": code})
    token = verify_res.json()["token"]
    
    response2 = client.get("/admin/logs", headers={"Authorization": f"Bearer {token}"})
    assert response2.status_code == 403


def test_admin_logs_endpoint_success(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com, super@example.com")
    
    # Login as admin
    client.post("/auth/send-otp", json={"email": "admin@example.com"})
    conn = get_db()
    with conn:
        code = conn.execute("SELECT otp_code FROM otps WHERE email='admin@example.com' ORDER BY id DESC LIMIT 1").fetchone()[0]
        
    verify_res = client.post("/auth/verify-otp", json={"email": "admin@example.com", "otp": code})
    token = verify_res.json()["token"]
    
    response = client.get("/admin/logs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    assert "logs" in data
    assert "total_queries" in data["metrics"]
