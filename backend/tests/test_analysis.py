import numpy as np

from tests.conftest import MockDetector, pass_challenge, png_bytes, running_session, wav_bytes


def up(c, sid, kind, data, name="x"):
    return c.post(f"/api/v1/sessions/{sid}/analysis/{kind}", files={"file": (name, data, "application/octet-stream")})


def test_missing_file_field_is_validation_error(client):
    sid = running_session(client)
    r = client.post(f"/api/v1/sessions/{sid}/analysis/audio")
    assert r.status_code in (415, 422)  # no multipart body at all
    r = client._c.post(f"/api/v1/sessions/{sid}/analysis/audio", {"other": "x"}, format="multipart")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_and_oversized_uploads(make_client):
    c = make_client(lambda s: {"audio": MockDetector(s, "audio", "audio_spoof", 0.1)}, max_upload_mb=1)
    sid = running_session(c)
    r = up(c, sid, "audio", b"this is not audio", "evil.wav")  # wrong content despite .wav name
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_MEDIA"
    assert up(c, sid, "frame", b"GIF89a....").status_code == 415
    assert up(c, sid, "audio", b"RIFF" + b"\0" * (1024 * 1024 + 8)).json()["error"]["code"] == "FILE_TOO_LARGE"
    assert up(c, sid, "audio", b"RIFFxxxxWAVEgarbage").json()["error"]["code"] == "INVALID_MEDIA"
    assert up(c, sid, "audio", wav_bytes(3)).status_code == 200
    c2 = make_client(max_audio_seconds=1)
    assert up(c2, running_session(c2), "audio", wav_bytes(3)).json()["error"]["code"] == "AUDIO_TOO_LONG"


def test_silent_audio_is_low_quality_not_suspicious(client):
    sid = running_session(client)
    assert up(client, sid, "audio", wav_bytes(2, silent=True)).status_code == 200
    r = client.officer.get(f"/api/v1/sessions/{sid}/analysis").json()
    s = r["signals"][0]
    assert s["status"] == "low_quality" and s["error_code"] == "SILENT_AUDIO" and s["score"] is None
    assert r["recommendation"]["risk_level"] == "GREY"


def test_upload_requires_consent_and_running(client):
    sid = client.post("/api/v1/sessions").json()["id"]
    assert up(client, sid, "audio", wav_bytes()).status_code == 403


def test_green_amber_red_via_mock_detectors(make_client):
    def mk(a, v):
        return lambda s: {"audio": MockDetector(s, "audio", "audio_spoof", a), "vit": MockDetector(s, "vit", "visual_deepfake", v)}
    for a, v, level in [(0.1, 0.1, "GREEN"), (0.9, 0.1, "AMBER"), (0.9, 0.9, "RED")]:
        c = make_client(mk(a, v))
        sid = running_session(c)
        up(c, sid, "audio", wav_bytes())
        up(c, sid, "frame", png_bytes())
        pass_challenge(c, sid)
        out = c.officer.post(f"/api/v1/sessions/{sid}/analysis/session").json()
        assert out["recommendation"]["risk_level"] == level
        assert c.officer.get(f"/api/v1/sessions/{sid}/analysis").json()["recommendation"]["risk_level"] == level
        assert "final_risk_level" not in c.post(f"/api/v1/sessions/{sid}/complete").json()  # the customer never sees the outcome
        assert c.officer.get(f"/api/v1/sessions/{sid}").json()["final_risk_level"] == level


def test_clean_detectors_without_measured_challenge_are_not_green(client):
    sid = running_session(client)
    up(client, sid, "audio", wav_bytes()), up(client, sid, "frame", png_bytes())
    rec = client.officer.post(f"/api/v1/sessions/{sid}/analysis/session").json()["recommendation"]
    assert rec["risk_level"] == "GREY" and any("challenge" in r.lower() for r in rec["reasons"])


def test_unavailable_detector_reported_explicitly(make_client):
    c = make_client(lambda s: {"audio": MockDetector(s, "audio", "audio_spoof", 0.1), "vit": MockDetector(s, "vit", "visual_deepfake", fail_load="MODEL_NOT_DOWNLOADED")})
    sid = running_session(c)
    up(c, sid, "audio", wav_bytes())
    ack = up(c, sid, "frame", png_bytes()).json()
    assert {"name": "vit", "status": "unavailable"} in ack["detectors"]  # the customer learns the check was not possible, nothing more
    r = c.officer.get(f"/api/v1/sessions/{sid}/analysis").json()
    vit = next(s for s in r["signals"] if s["detector_name"] == "vit")
    assert vit["status"] == "unavailable" and vit["error_code"] == "MODEL_NOT_DOWNLOADED" and vit["score"] is None
    rec = r["recommendation"]
    assert rec["risk_level"] == "GREY" and "vit" in rec["unavailable_detectors"]


def test_missing_ml_dependencies_or_weights_do_not_crash(tmp_path):
    from apps.signals.registry import DetectorRegistry
    from tests.conftest import make_settings
    reg = DetectorRegistry(make_settings(model_dir=str(tmp_path), enable_xception_detector=True, enable_syncnet=True))
    for name in ("audio", "vit", "landmarks", "xception", "syncnet"):
        out = reg.get(name).analyze(np.zeros(16000, dtype="float32"))
        assert out["status"] == "unavailable" and out["score"] is None and out["error_code"]
    states = {d["name"]: d["state"] for d in reg.status()}
    assert states["xception"] == "unavailable" and states["syncnet"] == "unavailable"


def test_label_mapping_never_guessed():
    from apps.signals.detector_base import resolve_fake_index
    assert resolve_fake_index({0: "Fake", 1: "Real"}) == 0 and resolve_fake_index({0: "real", 1: "fake"}) == 1
    assert resolve_fake_index({0: "LABEL_0", 1: "LABEL_1"}) is None


def test_threshold_survives_a_low_quality_last_sample(client):
    """A detector's threshold must come from any sample that has one, not only the last (a low-quality sample has none)."""
    from apps.signals.models import DetectorSignal
    from apps.decision_engine.services import aggregate_signals
    sid = running_session(client)
    for status, score, thr in [("ok", 0.9, 0.7), ("ok", 0.95, 0.7), ("low_quality", None, None)]:
        DetectorSignal.objects.create(session_id=sid, detector_name="audio", signal_type="audio_spoof", status=status, score=score, threshold=thr)
    (agg,) = aggregate_signals(sid)
    assert agg["threshold"] == 0.7 and agg["score"] >= 0.9 and agg["n_flagged"] == 2
