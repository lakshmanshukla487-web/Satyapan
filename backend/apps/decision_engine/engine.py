"""Deterministic demo policy (demo-v2). Thresholds are configurable, NOT validated or calibrated.

Inputs are per-detector AGGREGATES over every sample received in the session (not just the latest one), and the
list of challenge results. Rules, in order:
  1. Indicators = distinct categories among: flagged audio, flagged visual, flagged sync, challenge failure.
     A detector is flagged when its MEDIAN score over the session is >= its threshold, so one noisy frame or clip
     cannot decide the outcome. Scores are uncalibrated model outputs.
     A challenge counts as an indicator only when more challenges failed than passed. Failed attempts that are
     outweighed by passes are recorded as a note only (client-side measurements are heuristic).
  2. >= 2 independent indicators -> RED.   3. exactly 1 -> AMBER.
  4. else fewer than `min_usable` evidence sources -> GREY (insufficient evidence). An evidence source is a usable
     spoof-type detector category (audio, visual, sync) or passed challenge-response (client-reported liveness).
  5. else no challenge measured as passed -> GREY (challenge-response evidence is missing).
  6. else GREEN (consistent with authenticity; not a guarantee).
Missing, unavailable or low-quality signals are never counted as suspicious. Every outcome carries structured
reasons (`reason_details`) saying exactly why. Output always requires human review.

Additions in the Django refactor (they only act when their data exists, so older sessions decide exactly as before):
  * pipeline_integrity is a rule-based category: a hard indicator only for a virtual-camera signature PLUS a timing anomaly.
  * pulse and provenance are SUPPORTING evidence: they can add to the evidence-source count and add notes, never an indicator.
  * `extra_reasons` (from the KYC document cross-check) are appended as given; severity "indicator" counts as one category."""
from collections import Counter

CATEGORY = {"audio_spoof": "audio", "visual_deepfake": "visual", "av_sync": "sync", "pipeline_integrity": "integrity"}
SUPPORT_TYPES = {"pulse": "pulse", "provenance": "provenance"}  # corroborate only; never an indicator
CATEGORY_LABEL = {"audio": "audio", "visual": "visual", "sync": "audio-video sync", "challenge": "challenge-response", "integrity": "pipeline integrity",
                  "pulse": "pulse", "provenance": "provenance", "documents": "document cross-check"}
DETECTOR_LABEL = {"audio": "Audio anti-spoofing", "vit": "Visual deepfake classifier (ViT)", "xception": "Visual classifier (Xception)",
                  "landmarks": "Face landmarks", "syncnet": "Audio-video sync (SyncNet)", "integrity": "Pipeline integrity (virtual-camera probe)",
                  "pulse": "Pulse (rPPG)", "provenance": "Document provenance"}
SUMMARY = {"RED": "Multiple independent signals indicate elevated risk. Manual review is required.",
           "AMBER": "One signal requires additional human review.",
           "GREY": "Insufficient or inconclusive evidence. No conclusion can be drawn.",
           "GREEN": "Available evidence is consistent with authenticity. This is not a guarantee."}
RULES = {"R2": "Two or more independent indicators were raised.", "R3": "Exactly one indicator was raised.",
         "R4": "Fewer usable evidence sources than the policy minimum.", "R5": "No challenge-response check was measured as passed.",
         "R6": "No indicator raised, enough usable evidence, and at least one challenge passed."}
# What an error / quality code means in plain language, for the officer.
CODE_HINT = {"MODEL_NOT_DOWNLOADED": "model weights are not installed on the server (run scripts/download_models.py)",
             "DEPENDENCY_MISSING": "a required Python package is not installed (see requirements-ml.txt)",
             "NOT_INTEGRATED": "this detector is a placeholder and is not implemented",
             "LOAD_FAILED": "the model failed to load", "INFERENCE_FAILED": "the model failed while analysing the sample",
             "OUT_OF_MEMORY": "the server ran out of memory analysing the sample", "LABEL_MAPPING_UNKNOWN": "the model's label map is ambiguous, so no score was trusted",
             "SILENT_AUDIO": "the audio was silent", "SHORT_AUDIO": "the audio clip was too short", "SMALL_IMAGE": "the video frame was too small",
             "DARK_IMAGE": "the video frame was too dark", "NO_FACE": "no face was found in the frame", "MULTIPLE_FACES": "more than one face was in the frame",
             "NO_PROBE_DATA": "the browser sent no camera label or frame timings", "POOR_PULSE_QUALITY": "the face video was too short, too dark or too still for a pulse reading",
             "DOCUMENT_IMAGE_TOO_SMALL": "the document image was too small to analyse"}


def _reason(code: str, severity: str, category: str, title: str, detail: str, evidence: dict | None = None) -> dict:
    """severity: indicator (counted toward the level) | note (worth knowing, not counted) | missing (evidence gap) | ok (supports authenticity)."""
    return {"code": code, "severity": severity, "category": category, "title": title, "detail": detail, "evidence": evidence or {}}


def _hint(code: str | None) -> str:
    return CODE_HINT.get(code or "", code or "unknown reason")


def _challenge_reasons(challenges: list[dict]) -> tuple[list[dict], bool, dict]:
    passed = [c for c in challenges if c.get("result") == "passed"]
    failed = [c for c in challenges if c.get("result") == "failed"]
    unmeasured = [c for c in challenges if c.get("result") in (None, "unavailable")]
    counts = {"total": len(challenges), "passed": len(passed), "failed": len(failed), "unmeasured": len(unmeasured)}
    out: list[dict] = []

    def why(c: dict) -> str:
        return f"{c.get('type') or 'challenge'}: {c.get('reason') or 'did not match the request'}"

    indicator = False
    # Failures only count when they outweigh passes. Browser-side blink/head/speech measurements are noisy, so a customer
    # who passes as often as they fail (the UI replaces a failed attempt with a fresh one) is not flagged for it.
    if failed and len(failed) > len(passed):
        indicator = True
        out.append(_reason("CHALLENGE_FAILED", "indicator", "challenge", "Challenge-response failed",
                           f"{len(failed)} of {len(passed) + len(failed)} measured challenge(s) failed. " + " | ".join(why(c) for c in failed)
                           + " (client-reported measurement, not verified by the server).", {**counts}))
    elif failed:
        out.append(_reason("CHALLENGE_FAILED_ISOLATED", "note", "challenge", "Failed attempt(s) outweighed by passes",
                           f"{len(failed)} attempt(s) failed but {len(passed)} passed, so it is not counted as an indicator. " + " | ".join(why(c) for c in failed), {**counts}))
    if passed and not indicator:
        out.append(_reason("CHALLENGE_PASSED", "ok", "challenge", "Challenge-response passed",
                           f"{len(passed)} challenge(s) passed" + ("".join([": ", "; ".join(str(c["reason"]) for c in passed if c.get("reason"))]) if any(c.get("reason") for c in passed) else "")
                           + " (client-reported measurement, not verified by the server).", {**counts}))
    if unmeasured:
        details = " | ".join(why(c) for c in unmeasured if c.get("reason"))
        out.append(_reason("CHALLENGE_UNMEASURED", "missing", "challenge", "Challenge could not be measured",
                           f"{len(unmeasured)} challenge(s) have no measurement (not treated as suspicious)." + (f" {details}" if details else ""), {**counts}))
    return out, indicator, counts


def _label(name: str) -> str:
    return DETECTOR_LABEL.get(name, name)


def decide(signals: list[dict], challenges: list[dict], enabled: list[str], *, policy_version: str = "demo-v2", min_usable: int = 2,
           extra_reasons: list[dict] | None = None) -> dict:
    by_det = {s["detector_name"]: s for s in signals}
    usable = [s for s in signals if s["status"] == "ok" and s.get("score") is not None and s["signal_type"] in CATEGORY]
    flagged = [s for s in usable if s.get("threshold") is not None and s["score"] >= s["threshold"]]
    clear = [s for s in usable if s not in flagged]
    indicators = {CATEGORY[s["signal_type"]] for s in flagged}
    details: list[dict] = []

    for s in flagged:
        n = s.get("n_samples")
        extra = f" across {n} sample(s) (highest {s.get('max_score', s['score']):.2f}, {s.get('n_flagged', 1)} at or above the threshold)" if n else ""
        if s.get("score_kind") == "rule_based":
            why = "A rule-based check raised this indicator: " + (" ".join(s.get("notes") or []) or "its rule was met") + " It is a heuristic over client-reported data, not a probability of fraud."
        else:
            why = f"Median score {s['score']:.2f}{extra} met the demo threshold {s['threshold']:.2f}. This is an uncalibrated model output, not a probability of fraud."
        details.append(_reason("SIGNAL_FLAGGED", "indicator", CATEGORY[s["signal_type"]], f"{_label(s['detector_name'])} flagged",
                               why,
                               {"detector": s["detector_name"], "score": s["score"], "threshold": s["threshold"], "n_samples": n}))
    for s in clear:
        n, thr = s.get("n_samples"), s.get("threshold")
        text = f"Median score {s['score']:.2f}" + (f" across {n} sample(s)" if n else "") + (f" is below the demo threshold {thr:.2f}." if thr is not None else ".")
        if s.get("score_kind") == "rule_based":
            text = "The rule-based check did not raise an indicator."
        details.append(_reason("SIGNAL_CLEAR", "ok", CATEGORY[s["signal_type"]], f"{_label(s['detector_name'])} within range", text,
                               {"detector": s["detector_name"], "score": s["score"], "threshold": thr, "n_samples": n}))

    ch_details, ch_indicator, ch_counts = _challenge_reasons(challenges)
    details += ch_details
    if ch_indicator:
        indicators.add("challenge")

    # Supporting evidence (pulse, provenance): corroborates or adds a note, never raises an indicator.
    support = [s for s in signals if s["status"] == "ok" and s["signal_type"] in SUPPORT_TYPES]
    for s in support:
        cat = SUPPORT_TYPES[s["signal_type"]]
        if s.get("supports"):
            details.append(_reason("SIGNAL_SUPPORTS", "ok", cat, f"{_label(s['detector_name'])} supports authenticity",
                                   "Evidence consistent with authenticity (corroboration only, not proof).", {"detector": s["detector_name"]}))
    # Notes any detector attached to its own result (for example "virtual-camera name seen, timing looked normal").
    for s in signals:
        for text in s.get("notes") or []:
            details.append(_reason("SIGNAL_NOTE", "note", CATEGORY.get(s["signal_type"]) or SUPPORT_TYPES.get(s["signal_type"], "coverage"),
                                   f"{_label(s['detector_name'])}: note", text, {"detector": s["detector_name"]}))
    for r in extra_reasons or []:  # KYC document cross-check (already formed, with severity)
        details.append(r)
        if r["severity"] == "indicator":
            indicators.add(r["category"])

    # Coverage gaps: say precisely why each enabled detector contributed nothing.
    unavailable = sorted(n for n in enabled if n not in by_det or by_det[n]["status"] in ("unavailable", "error"))
    low_q = sorted(n for n, s in by_det.items() if s["status"] == "low_quality")
    for n in unavailable:
        s = by_det.get(n)
        if s is None:
            details.append(_reason("NO_SAMPLES", "missing", "coverage", f"{_label(n)}: nothing received",
                                   "No sample reached this detector before the session ended (not treated as suspicious). The customer may have finished very quickly or an upload failed.", {"detector": n}))
        else:
            details.append(_reason("DETECTOR_UNAVAILABLE", "missing", "coverage", f"{_label(n)}: unavailable",
                                   f"Could not be evaluated: {_hint(s.get('error_code'))} (not treated as suspicious).", {"detector": n, "error_code": s.get("error_code")}))
    for n in low_q:
        s = by_det[n]
        details.append(_reason("LOW_QUALITY_INPUT", "missing", "coverage", f"{_label(n)}: poor input quality",
                               f"All {s.get('n_samples') or 'received'} sample(s) were unusable: {_hint(s.get('error_code'))} (not treated as suspicious).", {"detector": n, "error_code": s.get("error_code")}))
    for s in usable:  # some, but not all, samples were unusable
        if s.get("n_samples") and s.get("n_usable") is not None and s["n_samples"] > s["n_usable"]:
            details.append(_reason("PARTIAL_QUALITY", "note", "coverage", f"{_label(s['detector_name'])}: some samples ignored",
                                   f"{s['n_samples'] - s['n_usable']} of {s['n_samples']} sample(s) were unusable and ignored.", {"detector": s["detector_name"]}))

    cats = {CATEGORY[s["signal_type"]] for s in usable}
    support_cats = {SUPPORT_TYPES[s["signal_type"]] for s in support if s.get("supports")}
    liveness = ch_counts["passed"] >= 1
    sources = len(cats | support_cats) + (1 if liveness else 0)

    if len(indicators) >= 2:
        level, rule = "RED", "R2"
    elif len(indicators) == 1:
        level, rule = "AMBER", "R3"
    elif sources < min_usable:
        level, rule = "GREY", "R4"
        have = ", ".join(sorted(cats | support_cats) + (["challenge-response"] if liveness else [])) or "none"
        details.append(_reason("INSUFFICIENT_EVIDENCE", "missing", "coverage", "Not enough usable evidence",
                               f"Only {sources} usable evidence source(s) ({have}); at least {min_usable} are needed.", {"sources": sources, "required": min_usable}))
    elif not liveness:
        level, rule = "GREY", "R5"
        details.append(_reason("NO_CHALLENGE_PASSED", "missing", "challenge", "Liveness evidence missing",
                               "No challenge-response check was measured as passed, so liveness evidence is missing.", {**ch_counts}))
    else:
        level, rule = "GREEN", "R6"

    completeness = "insufficient" if sources < min_usable else ("partial" if unavailable or low_q or not liveness else "complete")
    order = {"indicator": 0, "missing": 1, "note": 2, "ok": 3}
    details.sort(key=lambda r: order[r["severity"]])  # stable: keeps detector order inside each group
    if level in ("RED", "AMBER"):
        cause = "Raised: " + ", ".join(CATEGORY_LABEL.get(i, i) for i in sorted(indicators)) + "."
    elif level == "GREY":
        cause = next(r["detail"] for r in details if r["code"] in ("INSUFFICIENT_EVIDENCE", "NO_CHALLENGE_PASSED"))
    else:
        cause = "No detector or challenge raised a concern." + ("" if cats else " No ML detector contributed, so this rests on the challenge-response checks alone (see coverage gaps).")
    return {"risk_level": level, "summary": SUMMARY[level], "headline": f"{level}: {cause}", "rule": rule, "rule_text": RULES[rule],
            "reasons": [r["detail"] for r in details], "reason_details": details,
            "supporting_signals": [{"detector": s["detector_name"], "score": s["score"], "threshold": s["threshold"]} for s in flagged],
            "indicators": sorted(indicators), "unavailable_detectors": unavailable, "evidence_completeness": completeness,
            "signal_summary": [{k: s.get(k) for k in ("detector_name", "signal_type", "status", "score", "threshold", "n_samples", "n_usable", "max_score", "n_flagged", "error_code")} | {"flagged": s in flagged} for s in signals],
            "challenge_summary": ch_counts, "next_steps": _next_steps(level, details), "policy_version": policy_version, "human_review_required": True}


def _next_steps(level: str, details: list[dict]) -> list[str]:
    codes = Counter(r["code"] for r in details)
    steps = {"RED": ["Do not approve on the automated result alone. Re-verify identity through an independent channel (for example a call-back to a number already on file).",
                     "Review each raised indicator and note whether they share one cause (for example a poor camera or microphone) or are independent."],
             "AMBER": ["Review the raised indicator before deciding; one signal alone is not conclusive.", "If still unsure, ask the customer to run a fresh verification in good light and a quiet room."],
             "GREY": ["No conclusion can be drawn. Do not treat GREY as either safe or suspicious.", "Ask the customer to repeat verification once the gaps listed in this report are fixed."],
             "GREEN": ["Automated checks found nothing concerning. Apply your normal review; this is not a guarantee."]}[level][:]
    if codes["DETECTOR_UNAVAILABLE"]:
        steps.append("A detector was unavailable on the server. If this repeats for every session, fix the server setup (model download, dependencies) instead of re-testing customers.")
    if codes["NO_SAMPLES"]:
        steps.append("A detector received no samples. Check that the session lasted long enough and that uploads succeeded.")
    if codes["LOW_QUALITY_INPUT"]:
        steps.append("Poor camera or microphone input limited the analysis. Ask for better lighting, a quieter room and a single face in frame.")
    if codes["CHALLENGE_UNMEASURED"]:
        steps.append("Some challenges were not measured (camera, face detection or speech recognition problem, or skipped).")
    if codes["NAME_MISMATCH"] or codes["DOB_MISMATCH"] or codes["YOB_MISMATCH"]:
        steps.append("The uploaded documents disagree with each other on name or date of birth. Compare them side by side and ask the customer to explain before approving.")
    if codes["ID_REUSED_BY_OTHER_CUSTOMER"]:
        steps.append("An ID number on these documents was also used by a different customer account. Check for a duplicate or impersonation attempt.")
    if codes["CHALLENGE_FAILED"] or codes["CHALLENGE_FAILED_ISOLATED"]:
        steps.append("Challenge measurements come from the customer's browser and are heuristic. Treat failures as a prompt for review, not proof of fraud.")
    return steps
