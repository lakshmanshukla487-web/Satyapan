"""WebSocket event publishing through the Channels layer. Safe to call from synchronous views.

Three audiences, three groups, so nobody receives more than they should:
  session.<id>   officers watching one session (full detail, including risk)
  officers       the officer-wide feed (dashboard: new sessions, pending approvals, terminations)
  customer.<id>  the customer who owns the session (released challenges, status, termination; never risk data)
"""
import logging
from datetime import datetime, timezone
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

log = logging.getLogger("satyapan")

EVENTS = ("session.status", "challenge.pending", "challenge.approved", "challenge.released", "challenge.issued", "challenge.result",
          "detector.started", "detector.completed", "detector.unavailable", "signal.updated", "risk.updated", "analysis.completed",
          "document.uploaded", "documents.checked", "session.terminated", "session.requested", "session.approved", "session.rejected",
          "biometric.updated", "rtc.signal", "call.request", "call.accept", "call.decline", "call.end", "chat.message", "error")
OFFICERS_GROUP = "officers"
# Events the officer-wide feed also receives (the dashboard reloads on them).
FEED_EVENTS = frozenset({"session.requested", "session.status", "challenge.pending", "challenge.approved", "session.terminated", "documents.checked", "document.uploaded", "risk.updated"})


def group_name(session_id) -> str:
    return f"session.{session_id}"


def customer_group(session_id) -> str:
    return f"customer.{session_id}"


def envelope(event: str, session_id, data: dict[str, Any]) -> dict:
    return {"event": event, "session_id": str(session_id), "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "data": data}


def _send(group: str, handler: str, message: dict) -> None:
    try:
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(group, {"type": handler, "message": message})
    except Exception as e:  # a broken socket must not break an API call
        log.warning("event publish failed: %s", type(e).__name__)


def publish(session_id, event: str, data: dict[str, Any]) -> None:
    """Officer audience: this session's watchers, plus the officer feed for the events the dashboard cares about."""
    msg = envelope(event, session_id, data)
    _send(group_name(session_id), "session.event", msg)
    if event in FEED_EVENTS:
        _send(OFFICERS_GROUP, "feed.event", msg)


def publish_customer(session_id, event: str, data: dict[str, Any]) -> None:
    """Customer audience: only what the customer may see. Never put risk levels, scores or reasons in here."""
    _send(customer_group(session_id), "customer.event", envelope(event, session_id, data))
