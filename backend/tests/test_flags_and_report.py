"""Regression tests for the flag (RED/AMBER/GREY/GREEN) fixes, per-flag reasons and the officer summary report."""
from tests.conftest import MockDetector, png_bytes, running_session, wav_bytes
from apps.challenges.services import evaluate
from apps.decision_engine.engine import decide
from apps.challenges.models import Challenge


class SeqDetector(MockDetector):
    """Returns the next score from a list on every call (the last one repeats)."""
    def __init__(self, settings, name, signal_type, scores):
        super().__init__(settings, name, signal_type, scores[0])
        self._seq = list(scores)

    def _infer(self, media, metadata):
        score = self._seq.pop(0) if len(self._seq) > 1 else self._seq[0]
        return self.result("ok", score, label="mock")


def up(c, sid, kind, data, name="x"):
    return c.post(f"/api/v1/sessions/{sid}/analysis/{kind}", files={"file": (name, data, "application/octet-stream")})


def answer(c, sid, measured, wanted="blink"):
    """The officer runs a challenge of the wanted type; the customer answers it with `measured` (and is not told the outcome)."""
    ch = c.officer.post(f"/api/v1/sessions/{sid}/challenges/issue", json={"type": wanted}).json()
    r = c.post(f"/api/v1/sessions/{sid}/challenges/{ch['id']}/result", json={"measured": measured})
    assert r.status_code == 200 and "result" not in r.json()
    return ch, next(x for x in c.officer.get(f"/api/v1/sessions/{sid}/challenges").json() if x["id"] == ch["id"])


def sig(name, stype, score, thr=0.7, status="ok", **kw):
    return {"detector_name": name, "signal_type": stype, "status": status, "score": score, "threshold": thr, **kw}


# ---- challenge evaluation: reasons and tolerance ---------------------------------------------------------------

def mk(kind, text="x"):
    return Challenge(challenge_type=kind, challenge_text=text)


def test_head_turn_reasons():
    r, d = evaluate(mk("head_left"), {"head_yaw_deg": -22})
    assert r == "passed" and "left" in d["reason"]
    r, d = evaluate(mk("head_left"), {"head_yaw_deg": -4})
    assert r == "failed" and "only 4 degrees" in d["reason"]
    r, d = evaluate(mk("head_left"), {"head_yaw_deg": 25})  # turned the wrong way: say so, and hint at a mirrored preview
    assert r == "failed" and "wrong side" in d["reason"] and "mirrored" in d["reason"]
    assert evaluate(mk("head_right"), {})[0] == "unavailable"


def test_blink_reasons():
    assert evaluate(mk("blink"), {"blink_count": 3})[0] == "passed"
    r, d = evaluate(mk("blink"), {"blink_count": 1})
    assert r == "failed" and "1 blink" in d["reason"]


def test_phrase_tolerates_speech_recognition_variants():
    c = mk("phrase", "Say aloud: harbor maple river")
    assert evaluate(c, {"spoken_text": "Harbour, maple river."})[0] == "passed"  # spelling variant + punctuation
    assert evaluate(c, {"spoken_text": "river maple"})[0] == "passed"  # 2 of 3 words heard
    r, d = evaluate(c, {"spoken_text": "hello there"})
    assert r == "failed" and "missing: harbor, maple, river" in d["reason"]


# ---- decision engine: fewer false AMBER / GREY ----------------------------------------------------------------

EN = ["audio", "vit"]
A, V = ("audio", "audio_spoof"), ("vit", "visual_deepfake")


def test_one_failed_attempt_followed_by_passes_is_not_amber():
    d = decide([sig(*A, 0.1), sig(*V, 0.1)], [{"result": "failed", "type": "blink", "reason": "1 blink"}, {"result": "passed"}, {"result": "passed"}], EN)
    assert d["risk_level"] == "GREEN"
    assert any(r["code"] == "CHALLENGE_FAILED_ISOLATED" and r["severity"] == "note" for r in d["reason_details"])


def test_repeated_or_unrecovered_challenge_failure_is_an_indicator():
    two = decide([sig(*A, 0.1), sig(*V, 0.1)], [{"result": "failed"}, {"result": "failed"}, {"result": "passed"}], EN)
    assert two["risk_level"] == "AMBER" and two["indicators"] == ["challenge"]
    only = decide([sig(*A, 0.1), sig(*V, 0.1)], [{"result": "failed", "reason": "turned only 4 degrees"}], EN)
    assert only["risk_level"] == "AMBER" and "turned only 4 degrees" in only["reasons"][0]


def test_passed_challenge_counts_as_evidence_so_one_missing_model_is_not_grey():
    d = decide([sig(*A, 0.1), sig("vit", "visual_deepfake", None, status="unavailable", error_code="MODEL_NOT_DOWNLOADED")], [{"result": "passed"}], EN)
    assert d["risk_level"] == "GREEN" and d["evidence_completeness"] == "partial"
    assert any(r["code"] == "DETECTOR_UNAVAILABLE" and "not installed" in r["detail"] for r in d["reason_details"])


def test_every_grey_says_why():
    none = decide([], [], EN)
    assert none["risk_level"] == "GREY" and {r["code"] for r in none["reason_details"]} >= {"NO_SAMPLES", "INSUFFICIENT_EVIDENCE"}
    assert none["headline"].startswith("GREY: ") and none["next_steps"]
    lowq = decide([sig(*A, None, status="low_quality", error_code="SILENT_AUDIO"), sig(*V, 0.1)], [{"result": "passed"}], EN)
    assert any(r["code"] == "LOW_QUALITY_INPUT" and "silent" in r["detail"] for r in lowq["reason_details"])
    nopass = decide([sig(*A, 0.1), sig(*V, 0.1)], [{"result": "unavailable"}], EN)
    assert nopass["risk_level"] == "GREY" and nopass["rule"] == "R5" and any(r["code"] == "NO_CHALLENGE_PASSED" for r in nopass["reason_details"])


def test_every_flag_has_a_structured_reason():
    d = decide([sig(*A, 0.9, n_samples=3, max_score=0.95, n_flagged=3), sig(*V, 0.8)], [{"result": "passed"}], EN)
    assert d["risk_level"] == "RED" and d["rule"] == "R2" and d["indicators"] == ["audio", "visual"]
    flagged = [r for r in d["reason_details"] if r["severity"] == "indicator"]
    assert len(flagged) == 2 and all({"code", "title", "detail", "evidence"} <= set(r) for r in flagged)
    assert "3 sample(s)" in flagged[0]["detail"] and d["reasons"] == [r["detail"] for r in d["reason_details"]]


# ---- end to end: aggregation over the whole session --------------------------------------------------------------

def test_one_noisy_sample_does_not_flag_a_detector(make_client):
    c = make_client(lambda s: {"audio": SeqDetector(s, "audio", "audio_spoof", [0.1]), "vit": SeqDetector(s, "vit", "visual_deepfake", [0.1, 0.95, 0.1])})
    sid = running_session(c)
    up(c, sid, "audio", wav_bytes())
    for _ in range(3):  # one of three frames is a wild outlier
        up(c, sid, "frame", png_bytes())
    answer(c, sid, {"blink_count": 2}, "blink")
    rec = c.officer.get(f"/api/v1/sessions/{sid}/analysis").json()["recommendation"]
    assert rec["risk_level"] == "GREEN"
    vit = next(x for x in rec["signal_summary"] if x["detector_name"] == "vit")
    assert vit["n_samples"] == 3 and vit["max_score"] == 0.95 and vit["score"] == 0.1


def test_bad_last_sample_does_not_erase_earlier_good_ones(client):
    sid = running_session(client)
    up(client, sid, "audio", wav_bytes())
    up(client, sid, "audio", wav_bytes(2, silent=True))  # latest clip is silent
    up(client, sid, "frame", png_bytes())
    answer(client, sid, {"blink_count": 2}, "blink")
    rec = client.officer.get(f"/api/v1/sessions/{sid}/analysis").json()["recommendation"]
    assert rec["risk_level"] == "GREEN"
    assert any(r["code"] == "PARTIAL_QUALITY" for r in rec["reason_details"])


def test_sustained_flag_is_still_flagged(make_client):
    c = make_client(lambda s: {"audio": SeqDetector(s, "audio", "audio_spoof", [0.9, 0.85, 0.2]), "vit": SeqDetector(s, "vit", "visual_deepfake", [0.1])})
    sid = running_session(c)
    for _ in range(3):
        up(c, sid, "audio", wav_bytes())
    up(c, sid, "frame", png_bytes())
    answer(c, sid, {"blink_count": 2}, "blink")
    rec = c.officer.get(f"/api/v1/sessions/{sid}/analysis").json()["recommendation"]
    assert rec["risk_level"] == "AMBER" and rec["indicators"] == ["audio"]


# ---- officer summary report --------------------------------------------------------------------------------------

def _finished(c, measured, wanted="blink"):
    sid = running_session(c)
    up(c, sid, "audio", wav_bytes()), up(c, sid, "frame", png_bytes())
    answer(c, sid, measured, wanted)
    assert c.post(f"/api/v1/sessions/{sid}/complete").status_code == 200
    return sid


def test_report_is_stored_on_completion_and_matches_the_chain(client):
    sid = _finished(client, {"blink_count": 2})
    r = client.officer.get(f"/api/v1/sessions/{sid}/report").json()
    assert r["snapshot"] == "stored_at_completion" and r["outcome"]["risk_level"] == "GREEN" and r["outcome"]["human_review_required"] is True
    assert r["session"]["id"] == sid and r["session"]["customer"] == "alice" and r["session"]["duration_seconds"] is not None
    assert r["integrity"]["matches_evidence_chain"] is True and r["evidence_integrity"]["chain_valid"] is True
    assert [d["detector"] for d in r["detectors"]] == ["audio", "vit"] and all(d["samples"] == 1 for d in r["detectors"])
    won = next(c for c in r["challenges"] if c["result"] == "passed")
    assert won["type"] == "blink" and won["measured"] == {"blink_count": 2} and "2 blinks" in won["reason"]
    assert r["reasons"] and r["next_steps"] and r["limitations"] and any(t["event"] == "Session completed" for t in r["timeline"])
    assert client.officer.get(f"/api/v1/sessions/{sid}/evidence").json()["verification"]["valid"] is True
    text = str(r).lower()
    assert "token" not in text and "waveform" not in text


def test_report_explains_a_flag(client):
    sid = _finished(client, {"blink_count": 0})  # a single failed challenge and nothing else passed
    r = client.officer.get(f"/api/v1/sessions/{sid}/report").json()
    assert r["outcome"]["risk_level"] == "AMBER" and r["outcome"]["indicators"] == ["challenge"] and r["outcome"]["rule"] == "R3"
    why = next(x for x in r["reasons"] if x["code"] == "CHALLENGE_FAILED")
    assert why["severity"] == "indicator" and "0 blink" in why["detail"]
    assert r["outcome"]["headline"].startswith("AMBER: Raised: challenge-response")


def test_tampered_report_is_detected(client):
    from apps.verification.models import VerificationSession
    sid = _finished(client, {"blink_count": 2})
    s = VerificationSession.objects.get(pk=sid)
    s.report["outcome"]["risk_level"] = "RED"
    s.save()
    assert client.officer.get(f"/api/v1/sessions/{sid}/report").json()["integrity"]["matches_evidence_chain"] is False


def test_report_for_unfinished_session_is_live_and_access_controlled(client):
    sid = running_session(client)
    r = client.officer.get(f"/api/v1/sessions/{sid}/report").json()
    assert r["snapshot"] == "generated_now" and r["outcome"]["risk_level"] == "GREY" and r["integrity"]["matches_evidence_chain"] is None
    assert client.get(f"/api/v1/sessions/{sid}/report").status_code == 403  # customers never see the report
    assert client.officer.get("/api/v1/sessions/not-a-uuid/report").status_code == 404
