from apps.decision_engine.engine import decide


def sig(name, stype, score, thr=0.7, status="ok"):
    return {"detector_name": name, "signal_type": stype, "status": status, "score": score, "threshold": thr}


A, V = ("audio", "audio_spoof"), ("vit", "visual_deepfake")
EN = ["audio", "vit"]


def test_green():
    d = decide([sig(*A, 0.1), sig(*V, 0.2)], [{"result": "passed"}], EN)
    assert d["risk_level"] == "GREEN" and d["human_review_required"] is True and d["evidence_completeness"] == "complete"


def test_amber_single_flag():
    assert decide([sig(*A, 0.9), sig(*V, 0.2)], [], EN)["risk_level"] == "AMBER"


def test_amber_not_red_from_single_uncalibrated_detector():
    d = decide([sig(*A, 0.999)], [], EN)
    assert d["risk_level"] == "AMBER"


def test_red_two_independent():
    d = decide([sig(*A, 0.9), sig(*V, 0.8)], [], EN)
    assert d["risk_level"] == "RED" and len(d["supporting_signals"]) == 2


def test_red_flag_plus_failed_challenge():
    assert decide([sig(*A, 0.9)], [{"result": "failed"}], EN)["risk_level"] == "RED"


def test_two_visual_models_count_once():
    s = [sig("vit", "visual_deepfake", 0.9), sig("xception", "visual_deepfake", 0.9)]
    assert decide(s, [], ["vit", "xception"])["risk_level"] == "AMBER"


def test_grey_insufficient_and_missing_not_suspicious():
    d = decide([sig(*A, 0.1), sig("vit", "visual_deepfake", None, status="unavailable")], [], EN)
    assert d["risk_level"] == "GREY" and d["unavailable_detectors"] == ["vit"] and d["evidence_completeness"] == "insufficient"
    assert decide([], [], EN)["risk_level"] == "GREY"


def test_low_quality_not_suspicious():
    d = decide([sig(*A, None, status="low_quality"), sig(*V, None, status="low_quality")], [], EN)
    assert d["risk_level"] == "GREY"


def test_unmeasured_challenge_is_not_failure_but_blocks_green():
    d = decide([sig(*A, 0.1), sig(*V, 0.1)], [{"result": "unavailable"}, {"result": None}], EN)
    assert d["risk_level"] == "GREY" and d["evidence_completeness"] == "partial" and not d["supporting_signals"]


def test_optional_unavailable_detector_gives_partial_green():
    d = decide([sig(*A, 0.1), sig(*V, 0.1)], [{"result": "passed"}], EN + ["syncnet"])
    assert d["risk_level"] == "GREEN" and d["evidence_completeness"] == "partial" and d["unavailable_detectors"] == ["syncnet"]


# ---- challenge failures must outweigh passes to count (client-side measurements are noisy) -------------------------
def test_failures_outweighed_by_passes_are_not_an_indicator():
    ch = [{"result": "failed"}, {"result": "failed"}, {"result": "passed"}, {"result": "passed"}, {"result": "passed"}]
    d = decide([sig(*A, 0.1), sig(*V, 0.1)], ch, EN)
    assert d["risk_level"] == "GREEN" and "challenge" not in d["indicators"]
    assert any(r["code"] == "CHALLENGE_FAILED_ISOLATED" for r in d["reason_details"])


def test_failures_outnumbering_passes_still_flag():
    d = decide([sig(*A, 0.1), sig(*V, 0.1)], [{"result": "failed"}, {"result": "failed"}, {"result": "passed"}], EN)
    assert d["risk_level"] == "AMBER" and d["indicators"] == ["challenge"]


def test_challenge_only_green_says_no_detector_contributed():
    d = decide([], [{"result": "passed"}, {"result": "passed"}], EN, min_usable=1)
    assert d["risk_level"] == "GREEN" and "challenge-response checks alone" in d["headline"]
