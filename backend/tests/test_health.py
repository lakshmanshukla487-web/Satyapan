def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_and_models_status_expose_no_paths(client):
    r = client.get("/health/ready").json()
    assert r == {"ready": True, "database": "ok"}  # public probe: no detector information
    body = client.officer.get("/api/v1/models/status").content.decode()
    assert "audio" in body and "/home" not in body and "models/" not in body
