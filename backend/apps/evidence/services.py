from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.challenges.models import Challenge
from apps.evidence.hashing import GENESIS, compute_hash, iso, verify_chain
from apps.evidence.models import EvidenceEvent
from apps.signals.models import DetectorSignal
from apps.verification.models import VerificationSession


def append_event(session_id, event_type: str, payload: dict) -> EvidenceEvent:
    """Append to the session's hash chain. Concurrent requests may race for the same seq; the unique
    (session, seq) constraint rejects the loser, which simply retries on top of the winner's event."""
    sid = str(session_id)
    for attempt in range(8):
        try:
            with transaction.atomic():
                last = EvidenceEvent.objects.filter(session_id=session_id).order_by("-seq").first()
                seq, prev = (1, GENESIS) if last is None else (last.seq + 1, last.event_hash)
                ts = timezone.now()
                return EvidenceEvent.objects.create(session_id=session_id, seq=seq, event_type=event_type, timestamp=ts, payload=payload, previous_hash=prev,
                                                    event_hash=compute_hash(sid, seq, event_type, iso(ts), payload, prev))
        except IntegrityError:
            if attempt == 7:
                raise
    raise RuntimeError("unreachable")


def event_dict(e: EvidenceEvent) -> dict:
    return {"seq": e.seq, "event_type": e.event_type, "timestamp": iso(e.timestamp), "payload": e.payload, "previous_hash": e.previous_hash, "event_hash": e.event_hash}


def list_events(session_id) -> list[dict]:
    return [event_dict(e) for e in EvidenceEvent.objects.filter(session_id=session_id).order_by("seq")]


def verify_stored(session_id) -> dict:
    return verify_chain(str(session_id), list_events(session_id))


LIMITS = "Scores are uncalibrated model outputs or heuristic measurements, not probabilities of fraud."


def build_packet(s: VerificationSession, decision: dict) -> dict:
    """Default export excludes raw media, tokens and unnecessary personal data."""
    from apps.documents.services import document_summary  # lazy: documents depends on evidence
    sid = str(s.id)
    ch = Challenge.objects.filter(session=s).order_by("issued_at")
    sg = DetectorSignal.objects.filter(session=s).order_by("created_at")
    events = list_events(s.id)
    return {"packet_version": "1", "generated_at": iso(timezone.now()), "session": {"id": sid, "status": s.status, "created_at": iso(s.created_at),
            "started_at": iso(s.started_at) if s.started_at else None, "completed_at": iso(s.completed_at) if s.completed_at else None},
            "consent": {"given": s.consent_given, "timestamp": iso(s.consent_timestamp) if s.consent_timestamp else None},
            "challenges": [{"id": str(c.id), "type": c.challenge_type, "text": c.challenge_text, "issued_at": iso(c.issued_at), "status": c.status, "result": c.result} for c in ch],
            "signals": [{"detector": x.detector_name, "signal_type": x.signal_type, "status": x.status, "score": x.score, "threshold": x.threshold,
                         "model_id": (x.details or {}).get("model_id"), "score_kind": (x.details or {}).get("score_kind"), "error_code": x.error_code,
                         "created_at": iso(x.created_at), "superseded": bool((x.details or {}).get("superseded")), "limitations": LIMITS} for x in sg],
            "documents": document_summary(s),
            "unavailable_detectors": decision["unavailable_detectors"], "recommendation": decision, "policy_version": s.policy_version,
            "hash_chain": {"algorithm": "SHA-256", "genesis": GENESIS, "events": events, "verification": verify_chain(sid, events)},
            "disclaimer": "Decision-support only. A human officer makes the final decision. A hash chain is not legally certified or tamper-proof evidence."}
