from tests.conftest import running_session


def test_create_get_unknown(client):
    s = client.post("/api/v1/sessions")
    assert s.status_code == 201 and s.json()["status"] == "awaiting_consent"
    sid = s.json()["id"]
    assert client.get(f"/api/v1/sessions/{sid}").json()["id"] == sid
    for bad in ("00000000-0000-4000-8000-000000000000", "not-a-uuid"):
        r = client.get(f"/api/v1/sessions/{bad}")
        assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND" and r.json()["error"]["request_id"]


def test_consent_required_and_transitions(client):
    sid = client.post("/api/v1/sessions").json()["id"]
    assert client.post(f"/api/v1/sessions/{sid}/start").json()["error"]["code"] == "CONSENT_REQUIRED"
    assert client.officer.post(f"/api/v1/sessions/{sid}/analysis/session").status_code == 403
    assert client.post(f"/api/v1/sessions/{sid}/consent", json={"granted": True}).json()["status"] == "ready"
    assert client.post(f"/api/v1/sessions/{sid}/complete").status_code == 409
    assert client.post(f"/api/v1/sessions/{sid}/start").json()["status"] == "running"
    assert client.post(f"/api/v1/sessions/{sid}/start").status_code == 409
    assert client.post(f"/api/v1/sessions/{sid}/complete").json()["status"] == "completed"
    assert client.post(f"/api/v1/sessions/{sid}/cancel").status_code == 409


def test_consent_withdrawal_cancels(client):
    sid = running_session(client)
    r = client.post(f"/api/v1/sessions/{sid}/consent", json={"granted": False}).json()
    assert r["status"] == "cancelled" and r["consent_given"] is False
    assert client.officer.post(f"/api/v1/sessions/{sid}/analysis/session").status_code == 403


def test_list_pagination_filter(client):
    for _ in range(3):
        client.post("/api/v1/sessions")
    assert client.get("/api/v1/sessions?limit=2").json()["total"] == 3
    assert len(client.get("/api/v1/sessions?limit=2").json()["items"]) == 2
    assert client.get("/api/v1/sessions?status=running").json()["total"] == 0
    assert client.get("/api/v1/sessions?status=bogus").status_code == 422


def test_rate_limit(make_client):
    c = make_client(rate_limit_per_minute=2)
    c.get("/health"), c.get("/health")
    assert c.get("/health").status_code == 429
