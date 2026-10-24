from django.db import transaction

from apps.core.cache import cache_add
from apps.core.errors import AppError
from apps.core.runtime import get_runtime
from apps.evidence.services import append_event
from apps.realtime.events import publish
from apps.signals.models import DetectorSignal
from apps.signals.serializers import SignalSerializer


def run_detectors(s, names: list[str], media, warnings: list[str], extra_details: dict | None = None) -> list[DetectorSignal]:
    """Run the named detectors on one sample and record one DetectorSignal each. Detectors that are not enabled are skipped."""
    rt, out = get_runtime(), []
    for name in names:
        det = rt.registry.get(name)
        if det is None:
            continue
        publish(s.id, "detector.started", {"detector": name})
        if warnings:  # poor input: do not run the model, do not treat as suspicious
            res = det.result("low_quality", error_code=warnings[0], details={"warnings": warnings})
        else:
            # Bounded pool + bounded queue: when the models are saturated the request is refused at once (HTTP 503, the browser
            # retries on its next tick) instead of joining an ever longer queue that would make every customer's page slow.
            if not rt.gate.enter():
                raise AppError("SERVER_BUSY", "The analysis service is busy. Please try again in a moment.", 503, retry_after=2)
            try:
                res = rt.pool.submit(det.analyze, media, None).result()
            finally:
                rt.gate.leave()
        with transaction.atomic():
            sig = DetectorSignal.objects.create(
                session_id=s.id, detector_name=name, signal_type=res["signal_type"], status=res["status"], score=res["score"], confidence=None,
                threshold=res["threshold"], error_code=res["error_code"],
                details={"label": res["label"], "score_kind": res["score_kind"], "inference_ms": res["inference_ms"], "model_id": res["model_id"],
                         **res["details"], **(extra_details or {})})
            append_event(s.id, "signal.recorded", {"detector": name, "status": sig.status, "score": sig.score, "error_code": sig.error_code})
        out.append(sig)
        publish(s.id, "detector.unavailable" if sig.status == "unavailable" else "detector.completed", {"detector": name, "status": sig.status})
        publish(s.id, "signal.updated", dict(SignalSerializer(sig).data))
    return out


def finish_upload(s, sigs) -> dict:
    """Officers watching the session get the risk update; the uploading customer only gets an acknowledgement
    (never a score, label or risk level)."""
    from apps.decision_engine.services import build_analysis  # lazy: the decision engine reads the signals stored above
    interval = get_runtime().risk_publish_interval
    # With Redis, officers get at most one live risk update per session every few seconds, however many uploads arrive.
    if interval <= 0 or cache_add(f"riskpub:{s.id}", 1, max(1, int(round(interval)))):
        publish(s.id, "risk.updated", build_analysis(s)["recommendation"])
    return {"received": True, "detectors": [{"name": x.detector_name, "status": x.status} for x in sigs]}
