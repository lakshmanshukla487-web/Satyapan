import json

from asgiref.testing import ApplicationCommunicator

from satyapan.asgi import application


def test_unknown_url_and_method_use_error_envelope(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    r = client._c.delete("/api/v1/sessions")
    assert r.status_code == 405 and r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_invalid_bodies_are_422(client):
    sid = client.post("/api/v1/sessions").json()["id"]
    r = client.post(f"/api/v1/sessions/{sid}/consent", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = client._c.post(f"/api/v1/sessions/{sid}/consent", "{not json", content_type="application/json")
    assert r.status_code == 422
    assert client.get("/api/v1/sessions?limit=0").status_code == 422
    assert client.get("/api/v1/sessions?limit=abc").status_code == 422


def test_cors_and_request_id_headers(client):
    r = client._c.get("/health", HTTP_ORIGIN="http://localhost:5173")
    assert r["Access-Control-Allow-Origin"] == "http://localhost:5173" and r["X-Request-ID"]
    r = client._c.get("/health", HTTP_ORIGIN="http://evil.example")
    assert "Access-Control-Allow-Origin" not in r


def test_openapi_schema_and_docs_render(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200 and "/api/v1/sessions/{session_id}/analysis/audio" in json.loads(r.content)["paths"]
    assert client._c.get("/docs", HTTP_ACCEPT="text/html").status_code == 200


async def test_oversized_body_rejected_before_django_reads_it():
    from tests.conftest import make_settings
    from apps.core.runtime import Runtime, set_runtime
    set_runtime(Runtime.build(make_settings(max_upload_mb=1)))
    scope = {"type": "http", "method": "POST", "path": "/api/v1/sessions/x/analysis/audio", "headers": [(b"content-length", str(50 * 1024 * 1024).encode())],
             "query_string": b"", "client": ("1.2.3.4", 1), "server": ("testserver", 80), "scheme": "http", "http_version": "1.1"}
    comm = ApplicationCommunicator(application, scope)
    await comm.send_input({"type": "http.request", "body": b"", "more_body": False})
    start = await comm.receive_output(2)
    body = await comm.receive_output(2)
    assert start["status"] == 413 and json.loads(body["body"])["error"]["code"] == "FILE_TOO_LARGE"
