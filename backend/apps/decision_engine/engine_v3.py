"""Decision policy v3: a quality-weighted, multi-family verdict (RED / AMBER / GREEN / GREY) built to resist bluffing.

Pure functions, no Django: inputs are plain dicts (see services.collect_inputs), so every rule is unit-tested.

Each EVIDENCE FAMILY is judged from ALL its samples over the whole session, then the families are combined:

  family status   GREEN  enough good-quality samples, consistently clear
                  AMBER  something worth a human look (flags in a fifth of samples, or in the latest samples)
                  RED    strong, repeated evidence against authenticity (never from a single sample)
                  GREY   not enough usable data to judge (never treated as suspicious, never treated as safe)

  overall         RED    any HARD family is RED, or the risk points reach 3
                  AMBER  any risk point (a family is AMBER/RED) - needs review
                  GREEN  nothing raised AND every requirement for 'enough evidence' is met (below)
                  GREY   nothing raised but a requirement is missing (what exactly is listed)

Why this is hard to bluff:
  * No evidence = no GREEN. GREEN needs: minimum session length, minimum answered challenges with a good pass rate and at least
    one SERVER-confirmed one, the identity check (face) positively matching, at least three independent positive families, and
    media that kept arriving for most of the session (an attacker who stops uploading does not stay clean).
  * A single good sample never clears a family and a single bad one never condemns it (minimum sample counts per family).
  * Averages cannot hide a spoof: judged by flagged FRACTION, by the worst quarter of samples and by the latest samples (someone
    who switches to a fake half-way through is caught by the recent window).
  * Browser-reported evidence is capped: a challenge only the browser vouches for does not count as liveness proof, and a browser
    report that the server's own frames contradict is an indicator of tampering.
  * Poor input quality gives GREY for that family, never a pass and never an accusation.
  * Scores are uncalibrated model outputs; thresholds are configurable and not validated on real data.
"""
from __future__ import annotations

import math
from statistics import median

STATUS_ORDER = {"red": 3, "amber": 2, "grey": 1, "green": 0}

# id: label, detectors, minimum usable samples to judge, minimum flagged samples for RED, hard (can force RED alone), category
FAMILIES = {
    "voice":   {"label": "Voice authenticity (anti-spoof model)", "det": "audio", "min": 2, "min_red": 2, "hard": True, "cat": "audio"},
    "video":   {"label": "Face video authenticity (deepfake model)", "det": "vit", "min": 4, "min_red": 4, "hard": False, "cat": "visual"},
    "lipsync": {"label": "Lip sync (voice matches the lips)", "det": "syncnet", "min": 1, "min_red": 2, "hard": False, "cat": "sync"},
    "face":    {"label": "Face matches the photo supplied at the start", "det": "facematch", "min": 3, "min_red": 3, "hard": True, "cat": "identity"},
    # The iris code is classical and uncalibrated on visible-light photos: a mismatch alone raises AMBER; with other evidence it can reach RED.
    "iris":    {"label": "Iris scan matches the start photo", "det": "eyescan", "min": 1, "min_red": 1, "hard": False, "cat": "identity"},
}

LAYMAN = {
    "voice": {"green": "The voice sounded like a real person speaking live, not like a computer-made or replayed voice.",
              "amber": "Part of the voice sounded artificial. This can also be caused by a bad microphone or background noise, so a person should listen.",
              "red": "The voice repeatedly sounded computer-generated or cloned, not like a real person speaking.",
              "grey": "We did not hear enough clear speech to judge the voice."},
    "video": {"green": "The face video looked like a real camera picture of a real face.",
              "amber": "Some video frames looked digitally altered. Poor light or a low-quality camera can cause this, so a person should look.",
              "red": "Most of the video frames looked digitally altered or generated, like a deepfake.",
              "grey": "The video was too dark, small or unclear for us to judge the face."},
    "lipsync": {"green": "The words we heard matched the movement of the lips.",
                "amber": "The lips did not clearly match the sound. This can happen with a laggy connection, but it is also a sign of a pasted-in voice or video.",
                "red": "The sound and the lip movement did not belong together, which is typical of a faked or dubbed video.",
                "grey": "We did not get a clear clip of the person speaking, so lip sync could not be checked."},
    "face": {"green": "The person on camera looked like the person in the photo supplied at the start.",
             "amber": "The person on camera only partly resembled the start photo (light, angle or glasses can cause that). A person should compare them.",
             "red": "The person on camera did not look like the person in the start photo. It may be somebody else.",
             "grey": "We could not compare the face with the start photo (no photo, or the face was never clear enough)."},
    "iris": {"green": "The close-up eye scan matched the eyes in the start photo.",
             "amber": "The eye scan was unclear, so it neither confirmed nor ruled out that the eyes match.",
             "red": "The pattern of the coloured part of the eye (the iris) was different from the start photo.",
             "grey": "The close-up eye scan was not done, or the eyes were too small or blurry to compare."},
    "liveness": {"green": "The person did what was asked (turn the head, blink, say words) and our own check of the video agreed.",
                 "amber": "The person did not clearly do what was asked, or missed some requests.",
                 "red": "The actions reported by the browser were not seen in the video itself, or the requests were failed repeatedly.",
                 "grey": "Not enough requests were completed to be sure a live person is present."},
    "camera": {"green": "The camera looks like a real physical camera.",
               "amber": "The camera could not be confirmed as a real physical device.",
               "red": "The video appears to come from software (a virtual camera or injected video), not from a real camera.",
               "grey": "The camera could not be examined."},
    "network": {"green": "The internet connection looked like an ordinary connection and stayed the same during the session.",
                "amber": "The internet connection showed signs of a VPN, proxy or other hiding, or it changed during the session.",
                "red": "The connection comes from an anonymising service (Tor, VPN or proxy), which hides where the person really is.",
                "grey": "The connection could not be checked (for example the test was run on one computer, or no lookup list is installed)."},
    "documents": {"green": "The documents agree with each other and with the face on camera.",
                  "amber": "Something about the documents needs a closer look (see the findings).",
                  "red": "The documents contradict each other or do not match the person.",
                  "grey": "Documents were not submitted or could not be fully checked."},
    "behaviour": {"green": "The way the session went (timing, consistency, connection) looked natural over its whole length.",
                  "amber": "Something about how the session went looked odd (see the findings).",
                  "red": "The session behaved in a way that real people do not.",
                  "grey": "The session was too short to judge its pattern."},
}
OVERALL_LAYMAN = {
    "GREEN": "GREEN means: everything we were able to check looked normal, enough different checks were done, and nothing looked wrong. "
             "It is a good sign, not a guarantee. A human officer still makes the decision.",
    "AMBER": "AMBER means: at least one thing looked unusual or could not be confirmed. It does not prove a problem, but an officer should look at the "
             "items marked below before deciding, and may ask the customer to repeat the check.",
    "RED": "RED means: several checks looked wrong, or one very serious check failed (for example the face, voice or camera). Treat this as high risk. "
           "Do not approve on this result; verify the person another way. It is still a signal, not a court verdict.",
    "GREY": "GREY means: we did not get enough good information to say anything. That is neither a pass nor a warning. "
            "Ask the customer to repeat the check in good light, with a clear voice, and fix the gaps listed below.",
}


def _r(code, severity, category, title, detail, evidence=None):
    return {"code": code, "severity": severity, "category": category, "title": title, "detail": detail, "evidence": evidence or {}}


def _topk_mean(vals: list[float], frac: float = 0.25) -> float:
    if not vals:
        return 0.0
    k = max(1, math.ceil(len(vals) * frac))
    return sum(sorted(vals, reverse=True)[:k]) / k


# ---------------------------------------------------------------------------------------------------------------------------
# Model-based families

def judge_samples(spec_id: str, samples: list[dict]) -> dict:
    """samples: [{t, ok, score, thr, flag, clear, code}] oldest first. -> family result."""
    spec = FAMILIES[spec_id]
    n = len(samples)
    usable = [x for x in samples if x["ok"]]
    nu = len(usable)
    out = {"id": spec_id, "label": spec["label"], "hard": spec["hard"], "category": spec["cat"], "samples": n, "usable": nu, "reasons": [], "positive": False,
           "score": None, "flagged": 0, "quality": round(nu / n, 2) if n else 0.0}
    if n == 0:
        out.update(status="grey", why="no_samples")
        out["reasons"].append(_r(f"{spec_id.upper()}_NO_SAMPLES", "missing", spec["cat"], f"{spec['label']}: nothing received", "No sample reached this check (not treated as suspicious).", {"family": spec_id}))
        return out
    if nu < spec["min"]:
        codes = sorted({x["code"] for x in samples if x.get("code")})
        out.update(status="grey", why="too_few_usable")
        out["reasons"].append(_r(f"{spec_id.upper()}_TOO_FEW", "missing", spec["cat"], f"{spec['label']}: not enough usable samples",
                                 f"{nu} of {n} sample(s) were usable; at least {spec['min']} are needed to judge." + (f" Problems seen: {', '.join(codes)}." if codes else ""), {"family": spec_id, "codes": codes}))
        return out
    scores = [x["score"] for x in usable]
    flagged = [x for x in usable if x["flag"]]
    clear = [x for x in usable if x["clear"]]
    thr = next((x["thr"] for x in reversed(usable) if x["thr"] is not None), None)
    ff = len(flagged) / nu
    recent = usable[-5:]
    rflags = sum(1 for x in recent if x["flag"])
    top = _topk_mean(scores)
    med = median(scores)
    out.update(score=round(med, 3), flagged=len(flagged), top_quarter_mean=round(top, 3), flagged_fraction=round(ff, 3), threshold=thr)
    red = (len(flagged) >= spec["min_red"] and ff >= 0.5) or (len(recent) >= 3 and rflags >= 3 and rflags / len(recent) >= 0.8)
    amber = ff >= 0.2 or (len(recent) >= 3 and rflags / len(recent) >= 0.6) or (thr is not None and top >= thr and len(flagged) >= 1)
    if red:
        out["status"] = "red"
    elif amber:
        out["status"] = "amber"
    elif len(clear) / nu >= 0.6 and out["quality"] >= 0.4:
        out["status"] = "green"
        out["positive"] = True
    else:
        out.update(status="grey", why="inconclusive")
        out["reasons"].append(_r(f"{spec_id.upper()}_INCONCLUSIVE", "missing", spec["cat"], f"{spec['label']}: inconclusive",
                                 f"{nu} usable sample(s) but only {len(clear)} clearly confirmed authenticity and none was clearly against it.", {"family": spec_id}))
        return out
    if out["quality"] < 0.5 and out["status"] != "red":
        out["reasons"].append(_r(f"{spec_id.upper()}_PARTIAL", "note", spec["cat"], f"{spec['label']}: many samples unusable", f"Only {nu} of {n} samples were usable ({out['quality']:.0%}).", {"family": spec_id}))
    sev = "ok" if out["status"] == "green" else "indicator"
    tail = f"{len(flagged)} of {nu} usable sample(s) were flagged (median score {med:.2f}, worst quarter {top:.2f}" + (f", threshold {thr:.2f}" if thr is not None else "") + ")."
    out["reasons"].append(_r(f"{spec_id.upper()}_{out['status'].upper()}", sev, spec["cat"], f"{spec['label']}: {out['status'].upper()}", tail + " Uncalibrated model output, not a probability of fraud.",
                             {"family": spec_id, "flagged": len(flagged), "usable": nu, "median": round(med, 3), "threshold": thr}))
    return out


def judge_identity_drift(face_samples: list[dict]) -> dict | None:
    """Face similarity falling over a long session (the person changed, or a swap took over). Needs >= 8 usable samples."""
    pts = [(x["t"], x["sim"]) for x in face_samples if x["ok"] and x.get("sim") is not None]
    if len(pts) < 8:
        return None
    ts, ys = [p[0] for p in pts], [p[1] for p in pts]
    mt, my = sum(ts) / len(ts), sum(ys) / len(ys)
    den = sum((t - mt) ** 2 for t in ts)
    if den <= 0:
        return None
    slope = sum((t - mt) * (y - my) for t, y in zip(ts, ys)) / den
    span = ts[-1] - ts[0]
    drop = -slope * span
    last3 = ys[-max(3, len(ys) // 3):]
    return {"drop": round(drop, 3), "first_mean": round(sum(ys[:len(ys) // 3]) / max(1, len(ys) // 3), 3), "last_mean": round(sum(last3) / len(last3), 3), "span_s": round(span)}


# ---------------------------------------------------------------------------------------------------------------------------
# Liveness (challenges) and session behaviour

def judge_challenges(chs: list[dict], duration_s: float | None, cfg: dict) -> tuple[dict, dict]:
    """chs: [{seq, type, status, result, verification, t_gen, t_issue, t_answer, latency_ms}] -> (family result, stats)."""
    released = [c for c in chs if c["status"] != "awaiting_approval" and not (c["status"] == "expired" and c.get("never_released"))]
    answered = [c for c in released if c["status"] == "answered"]
    measured = [c for c in answered if c["result"] in ("passed", "failed")]
    passed = [c for c in measured if c["result"] == "passed"]
    failed = [c for c in measured if c["result"] == "failed"]
    missed = [c for c in released if c["status"] == "expired"]
    unavailable = [c for c in answered if c["result"] == "unavailable"]
    confirmed_pass = [c for c in passed if c["verification"] in ("server_confirmed", "server_only")]
    weak_pass = [c for c in passed if c["verification"] == "weak"]
    mismatch = [c for c in answered if c["verification"] == "mismatch"]
    rate = len(passed) / len(measured) if measured else None
    stats = {"issued": len(released), "answered": len(answered), "measured": len(measured), "passed": len(passed), "failed": len(failed), "missed": len(missed),
             "unavailable": len(unavailable), "server_confirmed_passes": len(confirmed_pass), "client_only_passes": len(passed) - len(confirmed_pass) - len(weak_pass),
             "tampering_mismatches": len(mismatch), "pass_rate": round(rate, 3) if rate is not None else None}
    out = {"id": "liveness", "label": "Liveness (asked actions)", "hard": False, "category": "challenge", "samples": len(released), "usable": len(measured), "reasons": [], "positive": False,
           "score": None, "quality": round(len(measured) / len(released), 2) if released else 0.0}
    R = out["reasons"]
    # --- hard evidence of faking
    if len(mismatch) >= 2:
        out["status"] = "red"
        R.append(_r("CHALLENGE_TAMPERING", "indicator", "challenge", "Browser reports contradicted by the server's own frames",
                    f"{len(mismatch)} challenges were reported as done by the browser, but the frames the server received show otherwise. The browser report is untrusted.", {**stats}))
    elif len(mismatch) == 1:
        out["status"] = "amber"
        R.append(_r("CHALLENGE_MISMATCH", "indicator", "challenge", "A browser report was contradicted by the server's frames",
                    "One challenge was reported as done but the server's frames did not show it. This can happen with fast movement; a repeat would show whether it is systematic.", {**stats}))
    elif len(failed) >= 3 and rate is not None and rate < 0.5:
        out["status"] = "red"
        R.append(_r("CHALLENGE_FAILED", "indicator", "challenge", "Challenge-response failed repeatedly",
                    f"{len(failed)} of {len(measured)} measured challenges failed (pass rate {rate:.0%}).", {**stats}))
    elif failed and rate is not None and rate < 0.75:
        out["status"] = "amber"
        R.append(_r("CHALLENGE_FAILED_SOME", "indicator", "challenge", "Several challenges failed", f"{len(failed)} of {len(measured)} measured challenges failed (pass rate {rate:.0%}).", {**stats}))
    elif released and len(missed) / len(released) >= 0.4 and len(released) >= 3:
        out["status"] = "amber"
        R.append(_r("CHALLENGE_MISSED", "indicator", "challenge", "Many challenges were ignored", f"{len(missed)} of {len(released)} released challenges were not answered in time.", {**stats}))
    elif len(passed) >= cfg["min_challenges"] and rate is not None and rate >= 0.75 and (len(confirmed_pass) >= 1 or not cfg["liveness_needs_server"]):
        out["status"], out["positive"] = "green", True
        R.append(_r("CHALLENGE_PASSED", "ok", "challenge", "Challenges passed", f"{len(passed)} of {len(measured)} measured challenges passed ({len(confirmed_pass)} confirmed by the server's own frames).", {**stats}))
    else:
        out["status"] = "grey"
        need = []
        if len(passed) < cfg["min_challenges"]:
            need.append(f"at least {cfg['min_challenges']} passed challenges (have {len(passed)})")
        if passed and not confirmed_pass:
            need.append("at least one challenge confirmed by the server's own frames (all passes so far rest on the browser's word)")
        R.append(_r("CHALLENGE_NOT_ENOUGH", "missing", "challenge", "Not enough verified liveness evidence", "Needed: " + "; ".join(need or ["more answered challenges"]) + ".", {**stats}))
    if unavailable and len(unavailable) >= max(2, len(answered) // 2):
        R.append(_r("CHALLENGE_UNMEASURED", "missing", "challenge", "Many challenges could not be measured", f"{len(unavailable)} challenge(s) had no usable measurement (not treated as suspicious).", {**stats}))
    return out, stats


def judge_behaviour(chs: list[dict], stats: dict, duration_s: float | None, net_ips: list[str], face_drift: dict | None, camera_ips_flag: bool, cfg: dict) -> dict:
    """Patterns that only show over the whole length of a session."""
    out = {"id": "behaviour", "label": "Session pattern over time", "hard": False, "category": "behaviour", "samples": len(chs), "usable": len(chs), "reasons": [], "positive": False, "score": None, "quality": 1.0}
    R, amber = out["reasons"], False
    if duration_s is None or duration_s < cfg["min_session_seconds"]:
        out["status"] = "grey"
        R.append(_r("SESSION_TOO_SHORT", "missing", "behaviour", "Session too short to judge its pattern",
                    f"The session lasted {int(duration_s or 0)} s; at least {cfg['min_session_seconds']} s are needed to observe a person over time.", {"duration_s": duration_s}))
        return out
    answered = [c for c in chs if c["status"] == "answered"]
    # timing: answers faster than a human can act, or suspiciously uniform
    quick = [c for c in answered if c.get("latency_ms") is not None and c["latency_ms"] < (1200 if c["type"] in ("head_left", "head_right", "phrase", "eye_scan") else 700)]
    if len(quick) >= 2 and len(quick) / max(1, len(answered)) >= 0.5:
        amber = True
        R.append(_r("RESPONSES_TOO_FAST", "indicator", "behaviour", "Answers came faster than a person can act",
                    f"{len(quick)} of {len(answered)} challenges were answered in under about a second, which looks automated.", {"fast": len(quick)}))
    lat = [c["latency_ms"] for c in answered if c.get("latency_ms") is not None]
    if len(lat) >= 5:
        m = sum(lat) / len(lat)
        sd = (sum((x - m) ** 2 for x in lat) / len(lat)) ** 0.5
        if m > 0 and sd / m < 0.05:
            amber = True
            R.append(_r("RESPONSES_TOO_UNIFORM", "indicator", "behaviour", "Answer times were almost identical", f"Response times varied by only {sd / m:.1%} across {len(lat)} challenges; people are less regular than that.", {"cv": round(sd / m, 3)}))
    # drift in performance: good first half, bad second half
    measured = [c for c in answered if c["result"] in ("passed", "failed")]
    if len(measured) >= 6:
        h = len(measured) // 2
        r1 = sum(c["result"] == "passed" for c in measured[:h]) / h
        r2 = sum(c["result"] == "passed" for c in measured[h:]) / (len(measured) - h)
        if r1 - r2 >= 0.5:
            amber = True
            R.append(_r("PERFORMANCE_DROP", "indicator", "behaviour", "Challenge performance got much worse during the session",
                        f"Pass rate fell from {r1:.0%} in the first half to {r2:.0%} in the second half (a takeover by another person or a fake can look like this).", {"first": r1, "second": r2}))
    # challenge cadence: a stretch with no challenge activity while the session ran
    times = sorted([c["t_gen"] for c in chs if c.get("t_gen") is not None])
    if duration_s and times:
        gaps = [b - a for a, b in zip([0.0] + times, times + [duration_s])]
        if max(gaps) > cfg["max_challenge_gap_s"]:
            amber = True
            R.append(_r("CHALLENGE_GAP", "indicator", "behaviour", "Long stretch without any challenge",
                        f"For {int(max(gaps))} s no challenge was running although the session was open; the challenge loop may have been stopped.", {"gap_s": round(max(gaps))}))
    elif duration_s and not times and duration_s >= cfg["min_session_seconds"]:
        amber = True
        R.append(_r("NO_CHALLENGES", "indicator", "behaviour", "No challenge ever ran", "The session lasted long enough but no challenge was issued.", {"duration_s": duration_s}))
    if len(set(net_ips)) > 1:
        amber = True
        R.append(_r("IP_CHANGED", "indicator", "behaviour", "The customer's IP address changed during the session", "Addresses seen: " + ", ".join(dict.fromkeys(net_ips)) + ".", {"ips": list(dict.fromkeys(net_ips))[:5]}))
    if face_drift and face_drift["drop"] >= 0.25 and face_drift["last_mean"] < cfg["face_threshold"] + 0.1:
        amber = True
        R.append(_r("IDENTITY_DRIFT", "indicator", "behaviour", "Face similarity fell during the session",
                    f"Similarity to the start photo fell by about {face_drift['drop']:.2f} (from {face_drift['first_mean']:.2f} to {face_drift['last_mean']:.2f}) over {face_drift['span_s']} s.", face_drift))
    out["status"] = "amber" if amber else "green"
    if not amber:
        out["positive"] = True
        R.append(_r("PATTERN_NATURAL", "ok", "behaviour", "Session pattern looked natural", f"{int(duration_s)} s long, {len(answered)} challenge(s) answered at human speed, consistent throughout.", {"duration_s": duration_s}))
    return out


def judge_media_coverage(video_times: list[float], audio_times: list[float], duration_s: float | None, cfg: dict) -> dict | None:
    """Did media keep arriving for most of the session? Gaps are where a pre-recorded or injected feed could have been swapped in unseen."""
    if not duration_s or duration_s < cfg["min_session_seconds"]:
        return None
    win = cfg["coverage_window_s"]
    n_win = max(1, int(duration_s // win))
    covered = 0
    for i in range(n_win):
        a, b = i * win, (i + 1) * win
        if any(a <= t < b for t in video_times):
            covered += 1
    frac = covered / n_win
    return {"fraction": round(frac, 2), "windows": n_win, "covered": covered, "audio_clips": len(audio_times), "video_frames": len(video_times)}


# ---------------------------------------------------------------------------------------------------------------------------
# Camera / network / documents (rule-based families)

def judge_camera(checks: list[dict]) -> dict:
    out = {"id": "camera", "label": "Camera is a real device", "hard": True, "category": "integrity", "samples": len(checks), "usable": len(checks), "reasons": [], "positive": False, "score": None, "quality": 1.0 if checks else 0.0}
    if not checks:
        out["status"] = "grey"
        out["reasons"].append(_r("CAMERA_NOT_EXAMINED", "missing", "integrity", "Camera was not examined", "The browser sent no camera information (not treated as suspicious).", {}))
        return out
    risk = max(c["risk"] for c in checks if c.get("risk") is not None) if any(c.get("risk") is not None for c in checks) else None
    if risk is None:
        out["status"] = "grey"
        out["reasons"].append(_r("CAMERA_NOT_EXAMINED", "missing", "integrity", "Camera could not be judged", "The camera information was missing or incomplete.", {}))
        return out
    worst = max(checks, key=lambda c: c.get("risk") or 0)
    out["score"] = round(risk, 3)
    flags = sorted({f for c in checks for f in c.get("flags", [])})
    if risk >= 0.5:
        out["status"] = "red"
        out["reasons"].append(_r("CAMERA_VIRTUAL", "indicator", "integrity", "Video does not come from a physical camera",
                                 "Camera check raised: " + (", ".join(f.replace("_", " ") for f in flags) or "see notes") + f" (camera '{str(worst.get('label') or '')[:60]}').", {"risk": risk, "flags": flags}))
    elif risk >= 0.25:
        out["status"] = "amber"
        out["reasons"].append(_r("CAMERA_DOUBTFUL", "indicator", "integrity", "Camera could not be confirmed as physical", "Weak signs of a non-physical camera: " + (", ".join(f.replace("_", " ") for f in flags) or "timing / missing hardware evidence") + ".", {"risk": risk, "flags": flags}))
    elif any(c.get("klass") == "hardware" for c in checks):
        out["status"], out["positive"] = "green", True
        out["reasons"].append(_r("CAMERA_HARDWARE", "ok", "integrity", "Camera looks like physical hardware", "Hardware evidence found (USB id, driver controls or built-in camera name) and no virtual-camera sign.", {"risk": risk}))
    else:
        out["status"] = "green"
        out["reasons"].append(_r("CAMERA_NO_VIRTUAL_SIGN", "ok", "integrity", "No sign of a virtual camera", "Nothing suggested a virtual camera, but nothing proved physical hardware either (so this does not count as positive proof).", {"risk": risk}))
    return out


def judge_network(checks: list[dict]) -> dict:
    out = {"id": "network", "label": "Internet connection (IP, VPN, proxy)", "hard": False, "category": "network", "samples": len(checks), "usable": 0, "reasons": [], "positive": False, "score": None, "quality": 0.0}
    usable = [c for c in checks if c.get("risk") is not None]
    out["usable"] = len(usable)
    if not usable:
        out["status"] = "grey"
        why = (checks[-1].get("error_code") if checks else None)
        out["reasons"].append(_r("NETWORK_NOT_CHECKED", "missing", "network", "Connection could not be checked",
                                 "The customer's public IP address was not available to check" + (" (the server sees a private or local address; normal when testing on one computer or behind an unconfigured reverse proxy)." if why == "IP_NOT_PUBLIC" else "."), {"code": why}))
        return out
    out["quality"] = 1.0
    risk = max(c["risk"] for c in usable)
    flags = sorted({f for c in usable for f in c.get("flags", [])})
    out["score"] = round(risk, 3)
    sources = bool(usable[-1].get("reputation_sources_available"))
    if risk >= 0.8:
        out["status"] = "red"
    elif risk >= 0.5:
        out["status"] = "amber"
    elif risk > 0:
        out["status"] = "amber"
    else:
        out["status"], out["positive"] = "green", sources
    if out["status"] in ("red", "amber"):
        out["reasons"].append(_r("NETWORK_" + ("RED" if out["status"] == "red" else "AMBER"), "indicator", "network", "Connection shows signs of hiding or relaying",
                                 "Raised: " + ", ".join(f.replace("_", " ") for f in flags) + ".", {"risk": risk, "flags": flags, "ip": usable[-1].get("ip")}))
    else:
        out["reasons"].append(_r("NETWORK_CLEAN", "ok", "network", "Connection looked ordinary",
                                 "No VPN, proxy, Tor or data-centre sign" + ("." if sources else " was found, but no reputation list or service is configured, so only WebRTC/header checks ran (this does not count as positive proof)."), {"ip": usable[-1].get("ip")}))
    return out


def judge_documents(doc: dict, extra: list[dict]) -> dict:
    """doc: {status: accepted|flagged|needs_correction|not_submitted}, extra: reasons from the document cross-check and document-face check."""
    out = {"id": "documents", "label": "Documents", "hard": False, "category": "documents", "samples": 0, "usable": 0, "reasons": list(extra), "positive": False, "score": None, "quality": 1.0}
    st = doc.get("status")
    ind = [r for r in extra if r["severity"] == "indicator"]
    face_bad = [r for r in ind if r["code"] == "DOCUMENT_FACE_MISMATCH"]
    if st in (None, "not_submitted", "not_checked", "needs_correction"):
        out["status"] = "grey"
        out["reasons"].append(_r("DOCUMENTS_NOT_VERIFIED", "missing", "documents", "Documents not verified", "No complete, checked set of documents is on record.", {"status": st}))
    elif face_bad and len(ind) >= 2:
        out["status"] = "red"
    elif ind:
        out["status"] = "amber"
    else:
        out["status"], out["positive"] = "green", True
        out["reasons"].append(_r("DOCUMENTS_CONSISTENT", "ok", "documents", "Documents consistent", "Documents were accepted and no cross-document or document-face disagreement was found.", {}))
    return out


# ---------------------------------------------------------------------------------------------------------------------------
# Combination

def combine(families: dict[str, dict], ctx: dict) -> dict:
    cfg = ctx["cfg"]
    details: list[dict] = []
    for f in families.values():
        details += f["reasons"]
    hard_red = [f for f in families.values() if f["hard"] and f["status"] == "red"]
    points, raised = 0, []
    for f in families.values():
        if f["status"] == "red":
            pts = 3 if f["hard"] else 2
        elif f["status"] == "amber":
            pts = 2 if f["hard"] else 1
        else:
            pts = 0
        if pts:
            points += pts
            raised.append(f["id"])
    # --- requirements for GREEN
    missing: list[tuple[str, str]] = []
    dur = ctx.get("duration_s")
    if dur is None or dur < cfg["min_session_seconds"]:
        missing.append(("SESSION_TOO_SHORT", f"session length {int(dur or 0)} s is below the minimum {cfg['min_session_seconds']} s"))
    live = families["liveness"]
    if live["status"] != "green":
        missing.append(("LIVENESS_MISSING", "verified liveness (enough passed challenges, at least one confirmed by the server's own frames)"))
    if ctx.get("identity_required"):
        if families["face"]["status"] != "green":
            missing.append(("IDENTITY_MISSING", "a positive face match against the start photo" + ("" if ctx.get("reference_uploaded") else " (no start photo was uploaded)")))
    positives = [f["id"] for f in families.values() if f["positive"]]
    media_pos = [i for i in ("voice", "video", "lipsync") if families[i]["positive"]]
    if len(positives) < cfg["min_positive_families"]:
        missing.append(("FEW_POSITIVE_FAMILIES", f"at least {cfg['min_positive_families']} independent checks positively confirming authenticity (have {len(positives)}: {', '.join(positives) or 'none'})"))
    if not media_pos:
        missing.append(("NO_MEDIA_AUTHENTICITY", "at least one media-authenticity check (voice, video or lip sync) that was positively clear"))
    cov = ctx.get("coverage")
    if cov is not None and cov["fraction"] < cfg["min_coverage"]:
        missing.append(("MEDIA_COVERAGE", f"media arriving through most of the session (only {cov['fraction']:.0%} of the time windows had video)"))
        details.append(_r("MEDIA_GAPS", "indicator" if cov["fraction"] < 0.3 else "note", "behaviour", "Video stopped arriving for long stretches",
                          f"Video frames arrived in {cov['covered']} of {cov['windows']} time windows. Unobserved stretches are where a swap could go unseen.", cov))
    if hard_red or points >= 3:
        level, rule = "RED", ("R2" if hard_red else "R2")
    elif points >= 1:
        level, rule = "AMBER", "R3"
    elif missing:
        level, rule = "GREY", "R4"
        details.append(_r("INSUFFICIENT_EVIDENCE", "missing", "coverage", "Not enough evidence for GREEN", "Still needed: " + "; ".join(m for _, m in missing) + ".", {"missing": [c for c, _ in missing]}))
    else:
        level, rule = "GREEN", "R6"
    unavailable = ctx.get("unavailable", [])
    completeness = "complete" if level == "GREEN" else ("insufficient" if level == "GREY" else "partial" if (missing or unavailable) else "complete")
    return {"level": level, "rule": rule, "details": details, "missing": missing, "raised": raised, "points": points, "positives": positives, "completeness": completeness}


RULES = {"R2": "A hard check failed or the risk points reached 3 (red).", "R3": "At least one family raised a concern (amber).",
         "R4": "Nothing raised, but the evidence needed for GREEN is incomplete (grey).", "R6": "Nothing raised and every requirement for enough, verified evidence was met (green)."}
SUMMARY = {"RED": "Multiple signals, or one serious signal, indicate elevated risk. Manual review is required.", "AMBER": "At least one check needs additional human review.",
           "GREY": "Insufficient or inconclusive evidence. No conclusion can be drawn.", "GREEN": "Available evidence is consistent with authenticity. This is not a guarantee."}


def decide_v3(inp: dict) -> dict:
    cfg = inp["cfg"]
    sm = inp["samples"]
    fams: dict[str, dict] = {}
    for fid in FAMILIES:
        fams[fid] = judge_samples(fid, sm.get(fid, []))
    # iris/face only matter when their evidence exists or was required
    if not inp.get("reference", {}).get("iris") and not sm.get("iris"):
        fams["iris"].update(status="grey", why="not_enrolled")
        fams["iris"]["reasons"] = []
    drift = judge_identity_drift(sm.get("face", []))
    fams["liveness"], ch_stats = judge_challenges(inp["challenges"], inp.get("duration_s"), cfg)
    net_ips = inp.get("net_ips", [])
    fams["camera"] = judge_camera(inp.get("camera_checks", []))
    fams["network"] = judge_network(inp.get("ip_checks", []))
    fams["documents"] = judge_documents(inp.get("documents", {}), inp.get("document_reasons", []))
    fams["behaviour"] = judge_behaviour(inp["challenges"], ch_stats, inp.get("duration_s"), net_ips, drift, False, cfg)
    cov = judge_media_coverage(inp.get("video_times", []), inp.get("audio_times", []), inp.get("duration_s"), cfg)
    enabled = inp.get("enabled", [])
    ctx = {"cfg": cfg, "duration_s": inp.get("duration_s"), "coverage": cov, "unavailable": inp.get("unavailable", []),
           "identity_required": bool(inp.get("identity_required")), "reference_uploaded": bool(inp.get("reference", {}).get("uploaded"))}
    res = combine(fams, ctx)
    level, details = res["level"], res["details"]
    order = {"indicator": 0, "missing": 1, "note": 2, "ok": 3}
    details.sort(key=lambda r: order[r["severity"]])
    for r in inp.get("extra_reasons", []):
        details.append(r)
    for f in fams.values():
        f["explain"] = LAYMAN.get(f["id"], {}).get(f["status"], "")
    raised_labels = [fams[i]["label"] for i in res["raised"]]
    if level in ("RED", "AMBER"):
        cause = "Raised: " + ", ".join(raised_labels) + "."
    elif level == "GREY":
        cause = "Still needed: " + "; ".join(m for _, m in res["missing"]) + "."
    else:
        cause = f"{len(res['positives'])} independent checks positively confirmed authenticity and nothing was raised."
    return {"risk_level": level, "summary": SUMMARY[level], "headline": f"{level}: {cause}", "rule": res["rule"], "rule_text": RULES[res["rule"]],
            "reasons": [r["detail"] for r in details], "reason_details": details,
            "supporting_signals": [{"detector": FAMILIES[i]["det"], "score": fams[i]["score"], "threshold": fams[i].get("threshold")} for i in res["raised"] if i in FAMILIES],
            "indicators": sorted({fams[i]["category"] for i in res["raised"]}), "unavailable_detectors": inp.get("unavailable", []), "evidence_completeness": res["completeness"],
            "signal_summary": inp.get("signal_summary", []), "challenge_summary": ch_stats,
            "families": list(fams.values()), "coverage": cov, "points": res["points"], "positives": res["positives"], "missing_for_green": [m for _, m in res["missing"]],
            "overall_explain": OVERALL_LAYMAN[level], "next_steps": next_steps_v3(level, res, fams, details), "policy_version": inp.get("policy_version", "v3"), "human_review_required": True}


def next_steps_v3(level: str, res: dict, fams: dict, details: list[dict]) -> list[str]:
    steps = {"RED": ["Do not approve on the automated result alone. Re-verify the person through an independent channel (for example a call-back to a number already on file).",
                     "Read each raised item below; note whether they share one cause (a poor camera, for example) or are independent."],
             "AMBER": ["Review the raised items before deciding; one signal alone is not conclusive.", "If still unsure, use the live video call to talk to the customer, or ask them to repeat the verification in good light."],
             "GREY": ["No conclusion can be drawn. Do not treat GREY as safe or as suspicious.", "Ask the customer to repeat verification after the gaps listed in this report are fixed."],
             "GREEN": ["Automated checks found nothing concerning. Apply your normal review; this is not a guarantee."]}[level][:]
    codes = {r["code"] for r in details}
    if "CAMERA_VIRTUAL" in codes:
        steps.append("A virtual or injected camera was suspected: ask the customer to use a physical webcam or phone camera app that the browser sees directly, and compare with the live call.")
    if "NETWORK_RED" in codes or "NETWORK_AMBER" in codes:
        steps.append("The connection looks relayed or hidden. Ask the customer to switch off any VPN or proxy and retry; compare the declared address with the network location.")
    if any(c.startswith("FACE_") for c in codes) or "DOCUMENT_FACE_MISMATCH" in codes:
        steps.append("Compare the live face, the start photo and the document photo yourself on the live call.")
    if "CHALLENGE_TAMPERING" in codes or "CHALLENGE_MISMATCH" in codes:
        steps.append("The browser claimed actions the server did not see: ask for a repeat on a different device and watch the live video.")
    return steps
