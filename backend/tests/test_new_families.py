"""Evidence families 1 (integrity), 5 (pulse), 6 (provenance) through the API, and the security hardening."""
import numpy as np

from tests.conftest import running_session

S = "/api/v1/sessions"


def test_integrity_probe_hard_indicator_raises_amber(make_client):
    from apps.integrity.detector import IntegrityDetector
    c = make_client(lambda s: {"integrity": IntegrityDetector(s)})
    sid = running_session(c)
    r = c.post(f"{S}/{sid}/analysis/integrity", json={"camera_label": "OBS Virtual Camera", "frame_rate": 30, "intervals_ms": [33.333] * 100})
    assert r.status_code == 200 and r.json() == {"received": True, "detectors": [{"name": "integrity", "status": "ok"}]}   # no score for the customer
    rec = c.officer.get(f"{S}/{sid}/analysis").json()["recommendation"]
    assert rec["risk_level"] == "AMBER" and "integrity" in rec["indicators"]
    assert any(x["code"] == "SIGNAL_FLAGGED" and "rule-based" in x["detail"] for x in rec["reason_details"])


def test_integrity_virtual_camera_name_is_an_indicator_even_with_natural_timing(make_client):
    from apps.integrity.detector import IntegrityDetector
    c = make_client(lambda s: {"integrity": IntegrityDetector(s)})
    sid = running_session(c)
    rng = np.random.default_rng(3)
    c.post(f"{S}/{sid}/analysis/integrity", json={"camera_label": "DroidCam Virtual", "frame_rate": 30, "intervals_ms": list(33.3 + rng.normal(0, 2.5, 100))})
    rec = c.officer.get(f"{S}/{sid}/analysis").json()["recommendation"]
    assert "integrity" in rec["indicators"] and rec["risk_level"] == "AMBER"


def test_integrity_real_hardware_camera_is_not_flagged(make_client):
    from apps.integrity.detector import IntegrityDetector
    c = make_client(lambda s: {"integrity": IntegrityDetector(s)})
    sid = running_session(c)
    rng = np.random.default_rng(4)
    r = c.post(f"{S}/{sid}/analysis/integrity", json={"camera_label": "Logitech HD Webcam C920 (046d:082d)", "frame_rate": 30,
                                                     "capabilities": ["focusMode", "exposureMode", "zoom", "brightness"], "intervals_ms": list(33.3 + rng.normal(0, 2.5, 100))})
    assert r.status_code == 200
    rec = c.officer.get(f"{S}/{sid}/analysis").json()["recommendation"]
    assert "integrity" not in rec["indicators"]


def test_integrity_input_is_validated(make_client):
    from apps.integrity.detector import IntegrityDetector
    c = make_client(lambda s: {"integrity": IntegrityDetector(s)})
    sid = running_session(c)
    assert c.post(f"{S}/{sid}/analysis/integrity", json={"intervals_ms": [1.0] * 1000}).status_code == 422
    assert c.post(f"{S}/{sid}/analysis/integrity", json={"camera_label": "x" * 500}).status_code == 422
    assert c.officer.post(f"{S}/{sid}/analysis/integrity", json={}).status_code == 403


def _rgb(amp, seconds=14, fps=30, hz=1.2):
    rng, t = np.random.default_rng(1), np.arange(seconds * fps) / fps
    x = np.array([180.0, 140.0, 120.0])[None, :] * np.ones((len(t), 3))
    wave = amp * np.sin(2 * np.pi * hz * t)
    x[:, 0] += 0.3 * wave
    x[:, 1] += wave
    x[:, 2] += 0.5 * wave
    return (x + rng.normal(0, 0.15, x.shape)).tolist()


def test_pulse_supports_but_never_accuses(make_client):
    from apps.pulse.detector import PulseDetector
    c = make_client(lambda s: {"pulse": PulseDetector(s)})
    sid = running_session(c)
    r = c.post(f"{S}/{sid}/analysis/pulse", json={"fps": 30, "rgb": _rgb(0.6)})
    assert r.status_code == 200 and r.json()["detectors"] == [{"name": "pulse", "status": "ok"}]
    rec = c.officer.get(f"{S}/{sid}/analysis").json()["recommendation"]
    assert rec["indicators"] == [] and any(x["code"] == "SIGNAL_SUPPORTS" and x["category"] == "pulse" for x in rec["reason_details"])
    # no pulse in good video: a note, never an indicator
    c.post(f"{S}/{sid}/analysis/pulse", json={"fps": 30, "rgb": _rgb(0.0)})
    sid2 = running_session(c)
    c.post(f"{S}/{sid2}/analysis/pulse", json={"fps": 30, "rgb": _rgb(0.0)})
    rec2 = c.officer.get(f"{S}/{sid2}/analysis").json()["recommendation"]
    assert rec2["indicators"] == [] and rec2["risk_level"] == "GREY"


def test_pulse_poor_quality_is_low_quality_not_suspicious(make_client):
    from apps.pulse.detector import PulseDetector
    c = make_client(lambda s: {"pulse": PulseDetector(s)})
    sid = running_session(c)
    c.post(f"{S}/{sid}/analysis/pulse", json={"fps": 30, "rgb": _rgb(0.6)[:100]})
    rec = c.officer.get(f"{S}/{sid}/analysis").json()["recommendation"]
    assert rec["indicators"] == [] and any(x["code"] == "LOW_QUALITY_INPUT" for x in rec["reason_details"])
    assert c.post(f"{S}/{sid}/analysis/pulse", json={"fps": 30, "rgb": [[1, 2, 3]] * 10}).status_code == 422
    assert c.post(f"{S}/{sid}/analysis/pulse", json={"fps": 30, "rgb": [[1, 2, 999]] * 100}).status_code == 422


# ---------------------------------------------------------------- hardening

def test_security_headers_on_every_response(client):
    for r in (client.get("/health"), client.get("/api/v1/auth/me"), client.get("/api/v1/sessions/not-a-uuid")):
        assert r["X-Content-Type-Options"] == "nosniff" and r["X-Frame-Options"] == "DENY"
        assert "default-src 'none'" in r["Content-Security-Policy"] and r["Cache-Control"] == "no-store"
        assert "camera=(self)" in r["Permissions-Policy"] and r["Referrer-Policy"] == "same-origin"


def test_logout_revokes_every_token_of_the_user(client):
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").json() == {"signed_out": True}
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.officer.get("/api/v1/auth/me").status_code == 200           # other users are unaffected


def test_sign_in_and_sign_out_are_audited(client):
    from apps.core.models import AuditLog
    client._c.credentials()
    client.post("/api/v1/auth/login", json={"username": "alice", "password": "correct-horse-9"})
    assert AuditLog.objects.filter(action="auth.login", actor__username="alice").exists()


def test_challenge_measurements_are_bounded(client):
    sid = running_session(client)
    ch = client.post(f"{S}/{sid}/challenges").json()
    url = f"{S}/{sid}/challenges/{ch['id']}/result"
    assert client.post(url, json={"measured": {f"k{i}": 1 for i in range(30)}}).status_code == 422
    assert client.post(url, json={"measured": {"spoken_text": "x" * 501}}).status_code == 422
    assert client.post(url, json={"measured": {"k" * 41: 1}}).status_code == 422


def test_api_docs_route_map_is_not_published_in_production(settings):
    import importlib
    import satyapan.urls as u
    settings.EXPOSE_API_DOCS = False
    importlib.reload(u)
    assert not any(getattr(p.pattern, "_route", "") in ("docs", "openapi.json") for p in u.urlpatterns)
    settings.EXPOSE_API_DOCS = True
    importlib.reload(u)
    assert any(getattr(p.pattern, "_route", "") == "docs" for p in u.urlpatterns)
