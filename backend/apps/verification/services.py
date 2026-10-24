import uuid
from datetime import timedelta

from django.utils import timezone

from apps.core.errors import AppError
from apps.core.runtime import get_runtime
from apps.verification.models import VerificationSession

ALLOWED = {
    "start": {"ready"},
    "complete": {"running"},
    "cancel": {"created", "awaiting_consent", "ready", "running"},
    "terminate": {"created", "awaiting_consent", "ready", "running"},  # officer override
}


APPROVAL_OK = ("not_required", "approved")


def expire_if_stale(s: VerificationSession) -> VerificationSession:
    """A request nobody approved in time expires (lazily, whenever it is read) so the officer queue cannot fill with dead requests."""
    if s.approval_status == "pending":
        ttl = get_runtime().settings.session_approval_timeout_seconds
        if timezone.now() - s.created_at > timedelta(seconds=ttl):
            VerificationSession.objects.filter(pk=s.pk, approval_status="pending").update(approval_status="expired", status="cancelled")
            s.refresh_from_db()
    return s


def require_approved(s: VerificationSession) -> None:
    """Nothing happens in a session until an officer has approved the customer's request for it."""
    expire_if_stale(s)
    if s.approval_status in APPROVAL_OK:
        return
    messages = {
        "pending": ("APPROVAL_PENDING", "Your request is waiting for an officer to approve it. You can continue once it is approved.", 403),
        "rejected": ("APPROVAL_REJECTED", "This request was not approved. Please contact support or request a new verification.", 403),
        "expired": ("APPROVAL_EXPIRED", "This request expired before an officer could review it. Please request a new verification.", 403),
    }
    code, msg, status = messages.get(s.approval_status, ("APPROVAL_PENDING", "Waiting for officer approval.", 403))
    raise AppError(code, msg, status)


def get_or_404(session_id: str) -> VerificationSession:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise AppError("SESSION_NOT_FOUND", "The requested session was not found.", 404)
    s = VerificationSession.objects.filter(pk=sid).first()
    if s is None:
        raise AppError("SESSION_NOT_FOUND", "The requested session was not found.", 404)
    return s


def get_visible(session_id: str, user) -> VerificationSession:
    """Officers can read any session; customers only their own (others look like they do not exist)."""
    s = get_or_404(session_id)
    if not user.is_officer and s.owner_id != user.id:
        raise AppError("SESSION_NOT_FOUND", "The requested session was not found.", 404)
    return s


def get_owned(session_id: str, user) -> VerificationSession:
    """For actions that run a verification: only the customer who owns the session."""
    if user.is_officer:
        raise AppError("FORBIDDEN", "Officers review sessions; they cannot operate a customer's verification.", 403)
    return get_visible(session_id, user)


def require_consent(s: VerificationSession) -> None:
    require_approved(s)
    if not s.consent_given:
        raise AppError("CONSENT_REQUIRED", "Explicit consent is required before any media processing.", 403)


def require_state(s: VerificationSession, action: str) -> None:
    if s.status not in ALLOWED[action]:
        raise AppError("INVALID_STATE_TRANSITION", f"Cannot {action} a session in state '{s.status}'.", 409)


def require_running(s: VerificationSession) -> None:
    require_consent(s)
    if s.status != "running":
        raise AppError("INVALID_STATE_TRANSITION", f"Session must be running (current state '{s.status}').", 409)


def require_documents_checked(s: VerificationSession) -> None:
    """The live camera/microphone step may only start after the KYC documents were submitted and checked."""
    if not get_runtime().settings.require_documents:
        return
    from apps.documents.models import DocumentCheck  # lazy: documents depends on this app
    check = DocumentCheck.objects.filter(session=s).first()
    if check is None or check.status == "needs_correction":
        raise AppError("DOCUMENTS_REQUIRED", "Upload and submit your documents before the live check can start.", 409)
