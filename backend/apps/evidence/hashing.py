"""Hash chain. event_hash = SHA-256(canonical_json({session_id, seq, event_type, timestamp, payload, previous_hash})).
canonical_json = sorted keys, separators (',', ':'), UTF-8, no NaN. First event's previous_hash is 64 zeros."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

GENESIS = "0" * 64


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def compute_hash(session_id: str, seq: int, event_type: str, timestamp: str, payload: dict, previous_hash: str) -> str:
    body = {"session_id": session_id, "seq": seq, "event_type": event_type, "timestamp": timestamp, "payload": payload, "previous_hash": previous_hash}
    return hashlib.sha256(canonical_json(body)).hexdigest()


NOTE = ("Detects edits relative to a retained chain only. Does not prove authorship or trusted time, "
        "and cannot detect truncation of trailing events or a fully rewritten chain.")


def verify_chain(session_id: str, events: list[dict]) -> dict:
    prev = GENESIS
    for i, e in enumerate(events):
        reason = None
        if e["seq"] != i + 1:
            reason = "SEQUENCE_GAP"
        elif e["previous_hash"] != prev:
            reason = "PREVIOUS_HASH_MISMATCH"
        elif compute_hash(session_id, e["seq"], e["event_type"], e["timestamp"], e["payload"], e["previous_hash"]) != e["event_hash"]:
            reason = "EVENT_HASH_MISMATCH"
        if reason:
            return {"valid": False, "checked": i + 1, "first_mismatch_index": i, "first_mismatch_seq": e["seq"], "reason": reason, "note": NOTE}
        prev = e["event_hash"]
    return {"valid": True, "checked": len(events), "first_mismatch_index": None, "first_mismatch_seq": None, "reason": None, "note": NOTE}
