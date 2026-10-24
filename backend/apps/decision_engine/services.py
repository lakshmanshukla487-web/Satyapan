import hashlib
from statistics import median

from django.db.models import Count, Max
from django.utils import timezone

from apps.biometrics.models import Observation
from apps.challenges.models import Challenge
from apps.core.cache import cache_get, cache_set
from apps.core.runtime import get_runtime
from apps.decision_engine.engine import decide
from apps.decision_engine.engine_v3 import FAMILIES, decide_v3
from apps.signals.models import DetectorSignal
from apps.signals.serializers import SignalSerializer
from apps.verification.models import VerificationSession


def _current(rows):
    """Leave out results of a document file the customer replaced or removed (marked superseded; kept only as history)."""
    return [r for r in rows if not (r.details or {}).get("superseded")]


def latest_signals(session_id) -> list[DetectorSignal]:
    rows = _current(DetectorSignal.objects.filter(session_id=session_id).order_by("created_at"))
    return list({r.detector_name: r for r in rows}.values())


def aggregate_signals(session_id) -> list[dict]:
    """One entry per detector built from EVERY sample received in the session, so a single noisy frame or clip
    (or a bad final sample) cannot decide the outcome. score = median of the usable scores."""
    groups: dict[str, list[DetectorSignal]] = {}
    for r in _current(DetectorSignal.objects.filter(session_id=session_id).order_by("created_at")):
        groups.setdefault(r.detector_name, []).append(r)
    out = []
    for name, rows in groups.items():
        scores = [r.score for r in rows if r.status == "ok" and r.score is not None]
        oks = [r for r in rows if r.status == "ok"]
        bad = [r for r in rows if r.status != "ok"]
        status = "ok" if oks else ("low_quality" if any(r.status == "low_quality" for r in bad) else ("error" if any(r.status == "error" for r in bad) else "unavailable"))
        thr = next((r.threshold for r in reversed(rows) if r.threshold is not None), None)  # a low-quality last sample has no threshold
        out.append({"detector_name": name, "signal_type": rows[-1].signal_type, "status": status, "score": median(scores) if scores else None, "threshold": thr,
                    "n_samples": len(rows), "n_usable": len(scores), "max_score": max(scores) if scores else None,
                    "n_flagged": sum(1 for x in scores if thr is not None and x >= thr), "error_code": next((r.error_code for r in reversed(bad) if r.error_code), None),
                    # added with the new evidence families (legacy detectors leave these empty)
                    "score_kind": (rows[-1].details or {}).get("score_kind"),
                    "supports": any(bool((r.details or {}).get("supports")) for r in oks),
                    "notes": sorted({n for r in oks for n in (r.details or {}).get("notes", [])})})
    return out


# ---------------------------------------------------------------------------------------------------------------------------
# policy v3 inputs

def _cfg_dict(cfg) -> dict:
    return {"min_challenges": cfg.min_challenges_answered, "min_session_seconds": cfg.min_session_seconds, "min_positive_families": cfg.min_positive_families,
            "min_coverage": cfg.min_coverage, "coverage_window_s": cfg.coverage_window_s, "max_challenge_gap_s": cfg.max_challenge_gap_s,
            "liveness_needs_server": cfg.liveness_needs_server, "face_threshold": cfg.face_cosine_threshold, "min_usable": cfg.min_usable_signals}


def collect_inputs(s: VerificationSession) -> dict:
    from apps.biometrics import services as bio
    from apps.documents.models import DocumentCheck
    from apps.documents.services import reasons_for_session
    rt = get_runtime()
    cfg = rt.settings
    t0 = s.started_at or s.created_at
    end = s.completed_at or timezone.now()
    duration = (end - t0).total_seconds() if s.started_at else None
    rows = _current(DetectorSignal.objects.filter(session_id=s.id).order_by("created_at"))
    by_det: dict[str, list[DetectorSignal]] = {}
    for r in rows:
        by_det.setdefault(r.detector_name, []).append(r)

    def series(det: str, clear_label: str | None = None) -> list[dict]:
        out = []
        for r in by_det.get(det, []):
            ok = r.status == "ok" and r.score is not None
            flag = bool(ok and r.threshold is not None and r.score >= r.threshold)
            label = (r.details or {}).get("label")
            clear = bool(ok and not flag and (clear_label is None or label == clear_label))
            out.append({"t": (r.created_at - t0).total_seconds(), "ok": ok, "score": r.score, "thr": r.threshold, "flag": flag, "clear": clear, "code": r.error_code,
                        "sim": (r.details or {}).get("similarity")})
        return out

    samples = {fid: series(spec["det"], {"lipsync": "in_sync", "iris": "match"}.get(fid)) for fid, spec in FAMILIES.items()}
    cams, ips = [], []
    for r in by_det.get("integrity", []):
        chk = (r.details or {}).get("checks") or {}
        if chk.get("camera"):
            cams.append(chk["camera"])
        if chk.get("ip"):
            ips.append(chk["ip"])
    chs = []
    for c in Challenge.objects.filter(session=s).order_by("created_at", "sequence"):
        chs.append({"seq": c.sequence, "type": c.challenge_type, "status": c.status, "result": c.result, "verification": c.verification,
                    "t_gen": (c.created_at - t0).total_seconds(), "t_issue": (c.issued_at - t0).total_seconds(),
                    "t_answer": (c.answered_at - t0).total_seconds() if c.answered_at else None,
                    "latency_ms": int((c.answered_at - c.issued_at).total_seconds() * 1000) if c.answered_at else None,
                    "never_released": c.status == "expired" and c.approval_status in ("pending", "regenerated")})   # the customer never saw it
    check = DocumentCheck.objects.filter(session=s).first()
    ref = bio.get_reference(s)
    net_ips = [o.data.get("ip") for o in Observation.objects.filter(session=s, kind="net").order_by("created_at") if o.data.get("ip")]
    enabled = rt.registry.enabled_names()
    agg = aggregate_signals(s.id)
    unavailable = sorted(n for n in enabled if n not in by_det or all(x.status in ("unavailable", "error") for x in by_det[n]))
    return {
        "cfg": _cfg_dict(cfg), "policy_version": s.policy_version, "duration_s": duration, "samples": samples, "camera_checks": cams, "ip_checks": ips, "challenges": chs,
        "documents": {"status": check.status if check else "not_submitted"}, "document_reasons": reasons_for_session(s),
        "reference": {"uploaded": ref is not None, "face": bool(ref and ref.face_embedding), "iris": bio.iris_enrolled(s)},
        "identity_required": bool(cfg.enable_facematch and rt.registry.get("facematch") is not None), "net_ips": net_ips,
        "video_times": [x["t"] for x in samples["video"] if x["ok"]], "audio_times": [x["t"] for x in samples["voice"] if x["ok"]],
        "enabled": enabled, "unavailable": unavailable,
        "signal_summary": [{k: a.get(k) for k in ("detector_name", "signal_type", "status", "score", "threshold", "n_samples", "n_usable", "max_score", "n_flagged", "error_code")}
                           | {"flagged": bool(a["threshold"] is not None and a["score"] is not None and a["score"] >= a["threshold"])} for a in agg],
    }


def _decision_version(s: VerificationSession) -> str:
    last = DetectorSignal.objects.filter(session_id=s.id).order_by("-created_at").values_list("created_at", flat=True).first()
    n_ch = Challenge.objects.filter(session=s).count()
    n_done = Challenge.objects.filter(session=s, status="answered").count()
    from apps.documents.models import DocumentCheck, KycDocument  # lazy: documents depends on this app
    doc = DocumentCheck.objects.filter(session=s).values_list("status", "checked_at").first()
    docs = KycDocument.objects.filter(session=s).aggregate(n=Count("id"), t=Max("updated_at"))
    return f"{s.status}:{s.approval_status}:{last}:{n_ch}:{n_done}:{doc}:{docs['n']}:{docs['t']}"


def current_decision(s: VerificationSession, fresh: bool = False) -> dict:
    rt = get_runtime()
    if s.policy_version.startswith("v3") and rt.settings.decision_policy == "v3":
        key = f"dec:{s.id}:{hashlib.md5(_decision_version(s).encode()).hexdigest()[:16]}"
        if not fresh and s.status == "running":
            hit = cache_get(key)  # shared between server processes with Redis; officers' polls and uploads do not recompute the same thing
            if hit is not None:
                return hit
        out = decide_v3(collect_inputs(s))
        if s.status == "running":
            cache_set(key, out, 3)
        return out
    from apps.documents.services import reasons_for_session  # lazy: documents depends on this app's inputs
    chs = [{"result": c.result, "type": c.challenge_type, "reason": c.reason, "measured": c.measured}
           for c in Challenge.objects.filter(session=s).order_by("issued_at")]
    return decide(aggregate_signals(s.id), chs, rt.registry.enabled_names(), policy_version=s.policy_version, min_usable=rt.settings.min_usable_signals,
                  extra_reasons=reasons_for_session(s))


def build_analysis(s: VerificationSession) -> dict:
    return {"signals": SignalSerializer(latest_signals(s.id), many=True).data, "recommendation": current_decision(s)}
