"""Everything the officer review console shows, in ONE response.

The console used to load every session through five separate requests (session, analysis, challenges, evidence, documents),
i.e. 5 x N requests per refresh, and it refreshed on every officer-feed event (one per frame upload of every live customer).
That alone exceeded the per-address rate limit within seconds. This endpoint returns the same information with a bounded
number of database queries."""
from __future__ import annotations

import hashlib

from django.db.models import Max, Q
from django.utils import timezone

from apps.challenges.models import Challenge
from apps.challenges.serializers import ChallengeSerializer
from apps.core.cache import cache_get, cache_set
from apps.decision_engine.services import _decision_version, current_decision
from apps.documents.models import DocumentCheck, KycDocument
from apps.evidence.models import EvidenceEvent
from apps.signals.models import DetectorSignal
from apps.signals.registry import ALL as ALL_DETECTORS
from apps.verification import services as ss
from apps.verification.models import VerificationSession

SETTLED_DECISION_TTL = 60  # seconds a decision of a session that is not running is reused (nothing changes it any more)


def _tier(s: VerificationSession) -> tuple[str, str]:
    """(risk level, one-line summary). Final sessions use the stored outcome; others the current decision (cached)."""
    if s.final_risk_level:
        return s.final_risk_level, s.summary or ""
    if s.status == "running":
        d = current_decision(s)  # cached for a few seconds inside current_decision
        return d["risk_level"], d.get("summary", "")
    key = f"dash:{s.id}:{hashlib.md5(_decision_version(s).encode()).hexdigest()[:16]}"
    hit = cache_get(key)
    if hit is None:
        d = current_decision(s)
        hit = (d["risk_level"], d.get("summary", ""))
        cache_set(key, hit, SETTLED_DECISION_TTL)
    return tuple(hit)  # type: ignore[return-value]


def _signals_ok(ids: list) -> dict:
    """Per session: how many detectors' LATEST (non-superseded) result is usable."""
    latest = (DetectorSignal.objects.filter(session_id__in=ids).values("session_id", "detector_name").annotate(t=Max("created_at")))
    cond = Q()
    for row in latest:
        cond |= Q(session_id=row["session_id"], detector_name=row["detector_name"], created_at=row["t"])
    out: dict = {}
    if not latest:
        return out
    for r in DetectorSignal.objects.filter(cond).values("session_id", "detector_name", "status", "details"):
        if r["status"] == "ok" and not (r["details"] or {}).get("superseded") and r["detector_name"] in ALL_DETECTORS:
            out[r["session_id"]] = out.get(r["session_id"], 0) + 1
    return out


def pending_challenges() -> list[dict]:
    rows = (Challenge.objects.filter(status="awaiting_approval", approval_status="pending", session__status="running", expires_at__gt=timezone.now())
            .select_related("session__owner").order_by("issued_at")[:50])
    return [{"challenge": dict(ChallengeSerializer(c).data), "session": {"id": str(c.session_id), "customer": c.session.owner.username if c.session.owner else None}}
            for c in rows]


def officer_dashboard(limit: int = 50) -> dict:
    # Requests nobody answered in time expire lazily when read; do it here so the queue never shows dead requests.
    for old in VerificationSession.objects.filter(approval_status="pending").exclude(status__in=("cancelled", "terminated", "completed", "failed"))[:50]:
        ss.expire_if_stale(old)
    qs = VerificationSession.objects.select_related("owner").order_by("-created_at")
    sessions = list(qs[:limit])
    ids = [s.id for s in sessions]
    checks = {c.session_id: c.status for c in DocumentCheck.objects.filter(session_id__in=ids)}
    with_docs = set(KycDocument.objects.filter(session_id__in=ids).values_list("session_id", flat=True))
    ok_counts = _signals_ok(ids)
    items = []
    for s in sessions:
        tier, summary = _tier(s)
        items.append({
            "id": str(s.id), "customer": s.owner.username if s.owner else None, "status": s.status, "approval_status": s.approval_status,
            "created_at": s.created_at, "started_at": s.started_at, "completed_at": s.completed_at, "final_risk_level": s.final_risk_level,
            "termination_reason": s.termination_reason, "challenge_auto_approve": s.challenge_auto_approve,
            "tier": tier, "summary": summary,
            "documents_status": checks.get(s.id) or ("not_checked" if s.id in with_docs else "not_submitted"),
            "signals_ok": ok_counts.get(s.id, 0), "signals_total": len(ALL_DETECTORS),
        })
    activity = [{"session_id": str(e.session_id), "seq": e.seq, "event_type": e.event_type, "timestamp": e.timestamp}
                for e in EvidenceEvent.objects.filter(session_id__in=ids).order_by("-timestamp")[:8]]
    requests = [{"id": str(s.id), "customer": s.owner.username if s.owner else None, "created_at": s.created_at}
                for s in VerificationSession.objects.select_related("owner").filter(approval_status="pending").exclude(
                    status__in=("cancelled", "terminated", "completed", "failed")).order_by("created_at")[:50]]
    return {"sessions": items, "total": qs.count(), "pending_approvals": pending_challenges(), "pending_requests": requests, "activity": activity,
            "generated_at": timezone.now()}
