"""Audit trail + security log. Call OUTSIDE ``transaction.atomic()`` blocks (a failed insert must not poison them)."""
import logging

from apps.core.models import AuditLog

security_log = logging.getLogger("satyapan.security")


def client_ip(request) -> str:
    """The client's address. X-Forwarded-For is only believed for the number of reverse proxies configured in
    IP_TRUSTED_PROXY_HOPS (default 0: the connecting address, exactly as before), so a client cannot pick its own address."""
    meta = getattr(request, "META", {}) or {}
    try:
        from apps.core.runtime import get_runtime
        from apps.integrity.ipintel import client_ip_from_meta
        ip = client_ip_from_meta(meta, get_runtime().settings.ip_trusted_proxy_hops)[0]
    except Exception:  # noqa: BLE001  (an address problem must never fail a request)
        ip = meta.get("REMOTE_ADDR") or ""
    return (ip or "unknown")[:64]


def audit(request, action: str, session_id=None, actor=None, **detail) -> None:
    """Best effort: an audit failure is logged but never fails the request."""
    user = actor if actor is not None else getattr(request, "user", None)
    user = user if getattr(user, "is_authenticated", False) else None
    try:
        AuditLog.objects.create(
            actor=user, actor_role=getattr(user, "role", "") or "", action=action, session_id=session_id, ip=client_ip(request),
            request_id=str(getattr(getattr(request, "_request", request), "request_id", "") or "")[:40], detail=detail)
    except Exception as e:  # noqa: BLE001
        security_log.warning("audit write failed: %s", type(e).__name__)
    security_log.info("action=%s actor=%s ip=%s session=%s", action, getattr(user, "pk", None), client_ip(request), session_id)
