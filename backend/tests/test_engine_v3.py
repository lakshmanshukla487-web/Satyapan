"""Decision policy v3 (pure functions): families, bluff resistance and the RED / AMBER / GREEN / GREY verdict."""
import copy

from apps.decision_engine import engine_v3 as e

CFG = {"min_challenges": 3, "min_session_seconds": 90, "min_positive_families": 3, "min_coverage": 0.6, "coverage_window_s": 15,
       "max_challenge_gap_s": 120, "liveness_needs_server": True, "face_threshold": 0.363, "min_usable": 2}


def smp(n, flagged=0, clear=True, ok=True, score=None, t0=0.0, step=5.0, code=None, sim=None):
    """n samples; the last `flagged` are flagged (a late switch to a fake looks like this)."""
    out = []
    for i in range(n):
        bad = i >= n - flagged
        out.append({"t": t0 + i * step, "ok": ok, "score": (0.9 if bad else 0.1) if score is None else score, "thr": 0.7, "flag": bad if ok else False,
                    "clear": (clear and not bad) if ok else False, "code": code if not ok else None, "sim": sim})
    return out


def ch(kind="blink", result="passed", ver="server_confirmed", lat=4000, status="answered", seq=1, t=10.0):
    return {"seq": seq, "type": kind, "status": status, "result": result if status == "answered" else None, "verification": ver, "t_gen": t, "t_issue": t,
            "t_answer": t + lat / 1000, "latency_ms": lat if status == "answered" else None}


def good_challenges():
    return [ch("blink", seq=1, t=10, lat=4000), ch("head_left", seq=2, t=40, lat=5200, ver="weak"), ch("phrase", seq=3, t=70, lat=3100, ver="client_only"), ch("head_right", seq=4, t=100, lat=6400)]


def good_input(**over):
    inp = {"cfg": CFG, "duration_s": 120.0, "identity_required": True, "reference": {"uploaded": True, "iris": False},
           "samples": {"voice": smp(4), "video": smp(8, step=10), "lipsync": [], "face": smp(6, sim=0.7), "iris": []},
           "challenges": good_challenges(), "camera_checks": [{"risk": 0.0, "flags": [], "klass": "hardware", "label": "Integrated Camera"}],
           "ip_checks": [{"risk": 0.0, "flags": [], "reputation_sources_available": True, "ip": "93.184.216.34"}], "net_ips": ["93.184.216.34"],
           "documents": {"status": "accepted"}, "document_reasons": [], "video_times": [i * 10.0 for i in range(12)], "audio_times": [5.0, 40.0, 80.0, 110.0],
           "enabled": ["audio", "vit", "facematch"], "unavailable": []}
    inp.update(over)
    return inp


def level(inp):
    return e.decide_v3(inp)["risk_level"]


def codes(res):
    return {r["code"] for r in res["reason_details"]}


# ---------------------------------------------------------------- one model family

def test_family_without_data_is_grey_not_suspicious_and_not_safe():
    r = e.judge_samples("voice", [])
    assert r["status"] == "grey" and r["why"] == "no_samples" and not r["positive"]
    r = e.judge_samples("voice", smp(1))
    assert r["status"] == "grey" and r["why"] == "too_few_usable"      # one good sample never clears a family


def test_unusable_samples_are_grey_and_the_problem_is_named():
    r = e.judge_samples("video", smp(6, ok=False, code="NO_FACE"))
    assert r["status"] == "grey" and "NO_FACE" in r["reasons"][0]["detail"]


def test_clear_samples_make_a_family_positive():
    r = e.judge_samples("video", smp(8))
    assert r["status"] == "green" and r["positive"] and r["flagged"] == 0


def test_one_bad_sample_never_condemns_a_family():
    r = e.judge_samples("voice", smp(1, flagged=1) + smp(1))
    assert r["status"] != "red"
    r = e.judge_samples("video", smp(3, flagged=1))        # below the minimum number of samples for video
    assert r["status"] == "grey"


def test_flagged_fraction_decides_amber_and_red():
    assert e.judge_samples("voice", smp(8, flagged=2))["status"] == "amber"      # a quarter flagged: worth a look
    assert e.judge_samples("voice", smp(4, flagged=3))["status"] == "red"        # most flagged, repeatedly
    assert e.judge_samples("video", smp(10, flagged=1))["status"] != "red"


def test_switching_to_a_fake_halfway_is_caught_by_the_recent_window():
    # ten clean samples, then the attacker swaps in a fake: the average still looks fine, the latest samples do not
    r = e.judge_samples("video", smp(15, flagged=5))
    assert r["status"] == "red"


def test_middle_scores_are_inconclusive_not_green():
    mid = [{"t": i, "ok": True, "score": 0.5, "thr": 0.7, "flag": False, "clear": False, "code": None, "sim": None} for i in range(6)]
    r = e.judge_samples("voice", mid)
    assert r["status"] == "grey" and r["why"] == "inconclusive"


def test_identity_drift_over_a_long_session():
    steady = [{"t": i * 10.0, "ok": True, "sim": 0.7} for i in range(10)]
    assert e.judge_identity_drift(steady)["drop"] < 0.05
    falling = [{"t": i * 10.0, "ok": True, "sim": 0.7 - i * 0.05} for i in range(10)]
    d = e.judge_identity_drift(falling)
    assert d["drop"] >= 0.35 and d["last_mean"] < d["first_mean"]
    assert e.judge_identity_drift(steady[:5]) is None


# ---------------------------------------------------------------- liveness

def test_liveness_green_needs_a_server_confirmed_pass():
    r, st = e.judge_challenges(good_challenges(), 120, CFG)
    assert r["status"] == "green" and st["server_confirmed_passes"] == 2 and st["passed"] == 4
    browser_only = [ch(ver="client_only", seq=i, t=i * 10) for i in range(1, 5)]
    r, st = e.judge_challenges(browser_only, 120, CFG)
    assert r["status"] == "grey" and "server's own frames" in r["reasons"][0]["detail"] and st["client_only_passes"] == 4   # all passes rest on the browser's word


def test_liveness_server_requirement_can_be_switched_off():
    r, _ = e.judge_challenges([ch(ver="client_only", seq=i) for i in range(1, 5)], 120, {**CFG, "liveness_needs_server": False})
    assert r["status"] == "green"


def test_liveness_too_few_challenges_is_grey():
    r, _ = e.judge_challenges(good_challenges()[:2], 120, CFG)
    assert r["status"] == "grey"


def test_browser_reports_contradicted_by_the_server_are_tampering():
    one = good_challenges() + [ch(result="failed", ver="mismatch", seq=5)]
    assert e.judge_challenges(one, 120, CFG)[0]["status"] == "amber"
    two = one + [ch(result="failed", ver="mismatch", seq=6)]
    r, st = e.judge_challenges(two, 120, CFG)
    assert r["status"] == "red" and st["tampering_mismatches"] == 2 and r["reasons"][0]["code"] == "CHALLENGE_TAMPERING"


def test_failed_and_ignored_challenges():
    failing = [ch(result="failed", ver="server_confirmed", seq=i) for i in range(1, 5)] + [ch(seq=5)]
    assert e.judge_challenges(failing, 120, CFG)[0]["status"] == "red"
    some = [ch(seq=1), ch(seq=2), ch(seq=3), ch(result="failed", seq=4)]
    assert e.judge_challenges(some, 120, CFG)[0]["status"] in ("amber", "green")
    ignored = [ch(seq=1), ch(status="expired", seq=2), ch(status="expired", seq=3), ch(status="expired", seq=4)]
    assert e.judge_challenges(ignored, 120, CFG)[0]["status"] == "amber"


def test_challenges_that_never_reached_the_customer_are_not_held_against_them():
    chs = good_challenges() + [ch(status="awaiting_approval", seq=5), {**ch(status="expired", seq=6), "never_released": True}]
    r, st = e.judge_challenges(chs, 120, CFG)
    assert st["issued"] == 4 and st["missed"] == 0 and r["status"] == "green"


# ---------------------------------------------------------------- session behaviour

def test_behaviour_needs_enough_session_length():
    st = e.judge_challenges(good_challenges(), 60, CFG)[1]
    r = e.judge_behaviour(good_challenges(), st, 60, [], None, False, CFG)
    assert r["status"] == "grey" and r["reasons"][0]["code"] == "SESSION_TOO_SHORT"


def test_behaviour_flags_robotic_timing_gaps_and_ip_change():
    st = e.judge_challenges(good_challenges(), 120, CFG)[1]
    assert e.judge_behaviour(good_challenges(), st, 120, ["1.1.1.1"], None, False, CFG)["status"] == "green"
    robot = [ch(seq=i, t=10 + i * 20, lat=300) for i in range(1, 6)]
    r = e.judge_behaviour(robot, st, 130, [], None, False, CFG)
    assert r["status"] == "amber" and {"RESPONSES_TOO_FAST", "RESPONSES_TOO_UNIFORM"} <= {x["code"] for x in r["reasons"]}
    gap = [ch(seq=1, t=5), ch(seq=2, t=10)]
    assert "CHALLENGE_GAP" in {x["code"] for x in e.judge_behaviour(gap, st, 400, [], None, False, CFG)["reasons"]}   # the challenge loop stopped
    assert "NO_CHALLENGES" in {x["code"] for x in e.judge_behaviour([], st, 200, [], None, False, CFG)["reasons"]}
    r = e.judge_behaviour(good_challenges(), st, 120, ["1.1.1.1", "9.9.9.9"], None, False, CFG)
    assert r["status"] == "amber" and "IP_CHANGED" in {x["code"] for x in r["reasons"]}


def test_behaviour_flags_a_performance_collapse():
    first = [ch(seq=i, t=i * 10) for i in range(1, 4)]
    second = [ch(result="failed", seq=i, t=i * 10, lat=3000 + i * 111) for i in range(4, 7)]
    st = e.judge_challenges(first + second, 120, CFG)[1]
    r = e.judge_behaviour(first + second, st, 120, [], None, False, CFG)
    assert "PERFORMANCE_DROP" in {x["code"] for x in r["reasons"]}


def test_media_coverage_windows():
    full = e.judge_media_coverage([i * 5.0 for i in range(24)], [], 120, CFG)
    assert full["fraction"] == 1.0 and full["windows"] == 8
    gappy = e.judge_media_coverage([1.0, 2.0, 100.0], [], 120, CFG)
    assert gappy["fraction"] < 0.3
    assert e.judge_media_coverage([], [], 30, CFG) is None


# ---------------------------------------------------------------- camera, network, documents

def test_camera_levels():
    assert e.judge_camera([])["status"] == "grey"
    assert e.judge_camera([{"risk": None}])["status"] == "grey"
    assert e.judge_camera([{"risk": 0.8, "flags": ["virtual_camera"], "klass": "virtual", "label": "OBS Virtual Camera"}])["status"] == "red"
    assert e.judge_camera([{"risk": 0.25, "flags": ["virtual_driver_installed"], "klass": "hardware"}])["status"] == "amber"
    hw = e.judge_camera([{"risk": 0.0, "flags": [], "klass": "hardware"}])
    assert hw["status"] == "green" and hw["positive"]
    unk = e.judge_camera([{"risk": 0.0, "flags": [], "klass": "unknown"}])
    assert unk["status"] == "green" and not unk["positive"]        # no virtual sign is not proof of a real camera


def test_network_levels():
    assert e.judge_network([])["status"] == "grey"
    assert e.judge_network([{"risk": None, "error_code": "IP_NOT_PUBLIC"}])["status"] == "grey"
    assert e.judge_network([{"risk": 0.85, "flags": ["vpn"]}])["status"] == "red"
    assert e.judge_network([{"risk": 0.6, "flags": ["ip_changed"]}])["status"] == "amber"
    assert e.judge_network([{"risk": 0.0, "flags": [], "reputation_sources_available": True}])["positive"] is True
    assert e.judge_network([{"risk": 0.0, "flags": [], "reputation_sources_available": False}])["positive"] is False   # unchecked is not proof


def test_documents_levels():
    assert e.judge_documents({"status": "not_submitted"}, [])["status"] == "grey"
    assert e.judge_documents({"status": "accepted"}, [])["status"] == "green"
    bad = {"code": "DOCUMENT_FACE_MISMATCH", "severity": "indicator"}
    other = {"code": "DOC_X", "severity": "indicator"}
    assert e.judge_documents({"status": "flagged"}, [other])["status"] == "amber"
    assert e.judge_documents({"status": "flagged"}, [bad, other])["status"] == "red"


# ---------------------------------------------------------------- the whole verdict

def test_everything_good_is_green_and_explains_itself():
    r = e.decide_v3(good_input())
    assert r["risk_level"] == "GREEN" and r["rule"] == "R6" and r["missing_for_green"] == []
    assert len(r["positives"]) >= 3 and r["human_review_required"] is True
    assert "not a guarantee" in r["overall_explain"]
    assert {f["id"] for f in r["families"]} == {"voice", "video", "lipsync", "face", "iris", "liveness", "camera", "network", "documents", "behaviour"}
    assert all(f["explain"] for f in r["families"])


def test_no_evidence_is_never_green():
    r = e.decide_v3(good_input(samples={}, challenges=[], video_times=[], audio_times=[], camera_checks=[], ip_checks=[], documents={}, net_ips=[]))
    assert r["risk_level"] in ("GREY", "AMBER") and r["risk_level"] != "GREEN"


def test_short_session_cannot_be_green():
    r = e.decide_v3(good_input(duration_s=45.0, video_times=[i * 5.0 for i in range(9)]))
    assert r["risk_level"] == "GREY" and any("session length" in m for m in r["missing_for_green"])


def test_missing_start_photo_match_blocks_green():
    inp = good_input()
    inp["samples"]["face"] = []
    r = e.decide_v3(inp)
    assert r["risk_level"] == "GREY" and any("face match" in m for m in r["missing_for_green"])


def test_browser_only_liveness_blocks_green():
    inp = good_input(challenges=[ch(ver="client_only", seq=i, t=i * 25, lat=3000 + i * 400) for i in range(1, 5)])
    r = e.decide_v3(inp)
    assert r["risk_level"] == "GREY" and any("verified liveness" in m for m in r["missing_for_green"])


def test_media_that_stops_arriving_blocks_green():
    r = e.decide_v3(good_input(video_times=[1.0, 2.0, 3.0]))
    assert r["risk_level"] in ("GREY", "AMBER") and any("most of the session" in m for m in r["missing_for_green"])
    assert "MEDIA_GAPS" in codes(r)


def test_a_virtual_camera_forces_red_even_if_everything_else_is_perfect():
    r = e.decide_v3(good_input(camera_checks=[{"risk": 0.8, "flags": ["virtual_camera"], "klass": "virtual", "label": "OBS Virtual Camera"}]))
    assert r["risk_level"] == "RED" and "CAMERA_VIRTUAL" in codes(r) and any("physical webcam" in s for s in r["next_steps"])


def test_a_cloned_voice_forces_red():
    inp = good_input()
    inp["samples"]["voice"] = smp(4, flagged=3)
    assert level(inp) == "RED"


def test_a_different_face_forces_red():
    inp = good_input()
    inp["samples"]["face"] = smp(6, flagged=5, sim=0.1)
    r = e.decide_v3(inp)
    assert r["risk_level"] == "RED" and "identity" in r["indicators"]


def test_a_vpn_is_amber_not_red_on_its_own():
    r = e.decide_v3(good_input(ip_checks=[{"risk": 0.85, "flags": ["vpn"], "reputation_sources_available": True, "ip": "5.6.7.8"}]))
    assert r["risk_level"] == "AMBER" and "NETWORK_RED" in codes(r)


def test_iris_mismatch_alone_is_amber_but_with_a_face_concern_it_is_red():
    inp = good_input(reference={"uploaded": True, "iris": True})
    inp["samples"]["iris"] = smp(2, flagged=2)
    assert level(inp) == "AMBER"
    inp["samples"]["face"] = smp(6, flagged=2, sim=0.3)       # a quarter of the face samples also disagree
    assert level(inp) == "RED"


def test_unenrolled_iris_is_not_reported_as_missing():
    r = e.decide_v3(good_input())
    iris = next(f for f in r["families"] if f["id"] == "iris")
    assert iris["status"] == "grey" and iris["reasons"] == []


def test_tampered_challenges_force_red_through_points():
    inp = good_input()
    inp["challenges"] = good_challenges() + [ch(result="failed", ver="mismatch", seq=5, t=105), ch(result="failed", ver="mismatch", seq=6, t=110)]
    inp["samples"]["voice"] = smp(8, flagged=2)    # amber (2 points, hard) + red liveness (2 points) = 4
    assert level(inp) == "RED"


def test_input_is_not_modified():
    inp = good_input()
    before = copy.deepcopy(inp)
    e.decide_v3(inp)
    assert inp == before


def test_next_steps_always_include_a_human_review_hint():
    for lvl_input in (good_input(), good_input(duration_s=10.0)):
        assert e.decide_v3(lvl_input)["next_steps"]
