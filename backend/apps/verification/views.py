from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsCustomer, IsOfficer
from apps.challenges.models import Challenge
from apps.core.audit import audit
from apps.core.errors import AppError
from apps.core.runtime import get_runtime
from apps.decision_engine.services import current_decision
from apps.evidence.services import append_event
from apps.realtime.events import publish, publish_customer
from apps.reports.services import build_report, digest
from apps.verification import services as ss
from apps.verification.models import VerificationSession
from apps.verification.serializers import ApproveIn, AutoApproveIn, ConsentIn, CustomerSessionSerializer, SessionPageSerializer, SessionSerializer, TerminateIn

STATUSES = {"created", "awaiting_consent", "ready", "running", "completed", "cancelled", "failed", "terminated"}
APPROVALS = {"not_required", "pending", "approved", "rejected", "expired"}

NEUTRAL_END_MESSAGE = "This verification has ended. We will complete it another way. You do not need to do anything else here."


def serializer_for(user):
    return SessionSerializer if user.is_officer else CustomerSessionSerializer


def push(s: VerificationSession) -> None:
    """Status change: officers get the full picture, the customer only the status (never the risk level)."""
    publish(s.id, "session.status", {"status": s.status, "final_risk_level": s.final_risk_level, "approval_status": s.approval_status})
    publish_customer(s.id, "session.status", {"status": s.status, "approval_status": s.approval_status})


def _int_param(request, name: str, default: int, lo: int, hi: int | None = None) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        v = int(raw)
    except ValueError:
        raise AppError("VALIDATION_ERROR", f"{name} must be an integer.", 422)
    if v < lo or (hi is not None and v > hi):
        raise AppError("VALIDATION_ERROR", f"{name} is out of range.", 422)
    return v


@extend_schema(methods=["GET"], tags=["sessions"], parameters=[OpenApiParameter("status", str), OpenApiParameter("approval", str), OpenApiParameter("limit", int), OpenApiParameter("offset", int)], responses=SessionPageSerializer)
@extend_schema(methods=["POST"], tags=["sessions"], request=None, responses={201: CustomerSessionSerializer})
@api_view(["GET", "POST"])
def sessions(request):
    ser = serializer_for(request.user)
    if request.method == "POST":
        if request.user.role != "customer":  # officers and developer accounts never run a customer verification
            raise AppError("FORBIDDEN", "Only customers can start a verification.", 403)
        cfg = get_runtime().settings
        open_requests = VerificationSession.objects.filter(owner=request.user, approval_status="pending").exclude(status__in=("cancelled", "terminated", "completed", "failed"))
        for old in open_requests[:20]:
            ss.expire_if_stale(old)
        if VerificationSession.objects.filter(owner=request.user, approval_status="pending").exclude(status__in=("cancelled", "terminated", "completed", "failed")).count() >= 3:
            raise AppError("TOO_MANY_PENDING", "You already have verification requests waiting for approval. Please wait for an officer.", 429)
        with transaction.atomic():
            s = VerificationSession.objects.create(
                owner=request.user, status="awaiting_consent", policy_version=cfg.policy_version,
                approval_status="pending" if cfg.require_session_approval else "not_required",
                challenge_auto_approve=bool(cfg.challenge_auto_approve_default))
            append_event(s.id, "session.created", {"policy_version": s.policy_version, "approval_status": s.approval_status})
            if s.approval_status == "pending":
                append_event(s.id, "session.approval_requested", {})
        push(s)
        if s.approval_status == "pending":
            publish(s.id, "session.requested", {"customer": request.user.username, "created_at": s.created_at.isoformat()})
        return Response(ser(s).data, status=201)
    status = request.query_params.get("status")
    if status is not None and status not in STATUSES:
        raise AppError("VALIDATION_ERROR", f"status must be one of {sorted(STATUSES)}.", 422)
    limit, offset = _int_param(request, "limit", 20, 1, 100), _int_param(request, "offset", 0, 0)
    qs = VerificationSession.objects.select_related("owner")
    if not request.user.is_officer:
        qs = qs.filter(owner=request.user)  # customers only ever see their own sessions
    if status:
        qs = qs.filter(status=status)
    approval = request.query_params.get("approval")
    if approval is not None:
        if approval not in APPROVALS:
            raise AppError("VALIDATION_ERROR", f"approval must be one of {sorted(APPROVALS)}.", 422)
        qs = qs.filter(approval_status=approval)
    items = qs.order_by("-created_at")[offset:offset + limit]
    return Response({"items": ser(items, many=True).data, "total": qs.count(), "limit": limit, "offset": offset})


@extend_schema(tags=["sessions"], operation_id="get_session", responses=SessionSerializer)
@api_view(["GET"])
def session_detail(request, session_id):
    s = ss.expire_if_stale(ss.get_visible(session_id, request.user))
    return Response(serializer_for(request.user)(s).data)


@extend_schema(tags=["consent"], request=ConsentIn, responses=CustomerSessionSerializer)
@api_view(["POST"])
@permission_classes([IsCustomer])
def consent(request, session_id):
    body = ConsentIn(data=request.data)
    body.is_valid(raise_exception=True)
    s = ss.get_owned(session_id, request.user)
    if s.status in ("completed", "cancelled", "failed", "terminated"):
        if s.approval_status in ("rejected", "expired"):
            ss.require_approved(s)  # says why, in words the customer can act on
        raise AppError("INVALID_STATE_TRANSITION", f"Cannot change consent for a session in state '{s.status}'.", 409)
    if body.validated_data["granted"]:
        ss.require_approved(s)  # the officer must approve the request first
    with transaction.atomic():
        if body.validated_data["granted"]:
            s.consent_given, s.consent_timestamp = True, timezone.now()
            if s.status in ("created", "awaiting_consent"):
                s.status = "ready"
            append_event(s.id, "consent.recorded", {})
        else:  # withdrawal: stop processing. No raw media is ever stored, so there is nothing to delete.
            s.consent_given, s.status = False, "cancelled"
            append_event(s.id, "consent.withdrawn", {"media_retained": False})
        s.save()
    push(s)
    return Response(CustomerSessionSerializer(s).data)


@extend_schema(tags=["sessions"], request=None, responses=CustomerSessionSerializer)
@api_view(["POST"])
@permission_classes([IsCustomer])
def start(request, session_id):
    s = ss.get_owned(session_id, request.user)
    ss.require_approved(s)
    ss.require_consent(s)
    ss.require_state(s, "start")
    ss.require_documents_checked(s)  # documents first, then the camera and microphone
    from apps.integrity.services import observe_ip  # lazy: integrity depends on biometrics/verification
    with transaction.atomic():
        s.status, s.started_at = "running", timezone.now()
        s.save()
        append_event(s.id, "session.started", {})
        observe_ip(request, s, "start")
    push(s)
    return Response(CustomerSessionSerializer(s).data)


@extend_schema(tags=["sessions"], request=None, responses=CustomerSessionSerializer)
@api_view(["POST"])
@permission_classes([IsCustomer])
def complete(request, session_id):
    s = ss.get_owned(session_id, request.user)
    ss.require_state(s, "complete")
    from apps.integrity.services import observe_ip
    observe_ip(request, s, "complete")
    _finalize(s)
    return Response(CustomerSessionSerializer(s).data)


@extend_schema(tags=["officer"], request=None, responses=SessionSerializer)
@api_view(["POST"])
@permission_classes([IsOfficer])
def finish(request, session_id):
    """Officer: the live check is over. Completes a running session exactly like the customer's own completion; the customer's
    page sees the neutral 'completed' status on its socket and closes the camera."""
    s = ss.get_or_404(session_id)
    ss.require_state(s, "complete")
    _finalize(s, officer_id=request.user.pk)
    audit(request, "officer.finish_session", session_id=s.id)
    return Response(SessionSerializer(s).data)


def _finalize(s: VerificationSession, officer_id: int | None = None) -> None:
    d = current_decision(s, fresh=True)
    with transaction.atomic():
        s.status, s.completed_at, s.final_risk_level, s.summary = "completed", timezone.now(), d["risk_level"], d["summary"]
        s.save()
        Challenge.objects.filter(session=s, status__in=("awaiting_approval", "issued")).update(status="expired")
        data = {"risk_level": d["risk_level"], "reasons": d["reasons"], "rule": d["rule"], "policy_version": s.policy_version}
        append_event(s.id, "session.completed", data if officer_id is None else {**data, "officer_id": officer_id})
        s.report = build_report(s, d)  # frozen summary for the officer; its hash goes into the evidence chain
        s.save(update_fields=["report"])
        append_event(s.id, "report.generated", {"risk_level": d["risk_level"], "report_sha256": digest(s.report)})
    publish(s.id, "risk.updated", d)
    publish(s.id, "analysis.completed", {"risk_level": d["risk_level"]})
    push(s)


@extend_schema(tags=["sessions"], request=None, responses=CustomerSessionSerializer)
@api_view(["POST"])
@permission_classes([IsCustomer])
def cancel(request, session_id):
    s = ss.get_owned(session_id, request.user)
    ss.require_state(s, "cancel")
    with transaction.atomic():
        s.status = "cancelled"
        s.save()
        append_event(s.id, "session.cancelled", {"media_retained": False})
    push(s)
    return Response(CustomerSessionSerializer(s).data)


@extend_schema(tags=["officer"], request=TerminateIn, responses=SessionSerializer)
@api_view(["POST"])
@permission_classes([IsOfficer])
def terminate(request, session_id):
    """Officer override: end the session at any time. Evidence and a frozen report are kept; the customer is told,
    in neutral words, that the check ends here (no accusation)."""
    body = TerminateIn(data=request.data or {})
    body.is_valid(raise_exception=True)
    reason = (body.validated_data.get("reason") or "").strip() or "Ended by the reviewing officer."
    s = ss.get_or_404(session_id)
    ss.require_state(s, "terminate")
    d = current_decision(s, fresh=True)
    now = timezone.now()
    with transaction.atomic():
        s.status, s.completed_at, s.terminated_at, s.terminated_by, s.termination_reason = "terminated", now, now, request.user, reason
        s.final_risk_level, s.summary = d["risk_level"], d["summary"]
        s.save()
        Challenge.objects.filter(session=s, status__in=("awaiting_approval", "issued")).update(status="expired")
        append_event(s.id, "session.terminated", {"officer_id": request.user.pk, "reason": reason, "risk_level": d["risk_level"]})
        s.report = build_report(s, d)
        s.save(update_fields=["report"])
        append_event(s.id, "report.generated", {"risk_level": d["risk_level"], "report_sha256": digest(s.report)})
    audit(request, "officer.terminate_session", session_id=s.id, reason=reason)
    publish(s.id, "session.terminated", {"reason": reason, "officer": request.user.username})
    publish_customer(s.id, "session.terminated", {"message": NEUTRAL_END_MESSAGE})
    push(s)
    return Response(SessionSerializer(s).data)


@extend_schema(tags=["officer"], request=ApproveIn, responses=SessionSerializer)
@api_view(["POST"])
@permission_classes([IsOfficer])
def approve(request, session_id):
    """Officer releases the customer's request. Only after this can the customer give consent, upload documents and start."""
    body = ApproveIn(data=request.data or {})
    body.is_valid(raise_exception=True)
    s = ss.expire_if_stale(ss.get_or_404(session_id))
    if s.approval_status != "pending":
        raise AppError("INVALID_STATE_TRANSITION", f"This request is '{s.approval_status}', not waiting for approval.", 409)
    note = (body.validated_data.get("note") or "").strip()
    with transaction.atomic():
        n = VerificationSession.objects.filter(pk=s.pk, approval_status="pending").update(
            approval_status="approved", approved_by=request.user, approved_at=timezone.now(), approval_note=note)
        if n != 1:  # another officer got there first
            raise AppError("INVALID_STATE_TRANSITION", "Another officer already handled this request.", 409)
        append_event(s.id, "session.approved", {"officer_id": request.user.pk})
    s.refresh_from_db()
    audit(request, "officer.approve_session", session_id=s.id)
    push(s)
    publish_customer(s.id, "session.approved", {"message": "An officer approved your request. You can start your verification."})
    return Response(SessionSerializer(s).data)


@extend_schema(tags=["officer"], request=TerminateIn, responses=SessionSerializer)
@api_view(["POST"])
@permission_classes([IsOfficer])
def reject(request, session_id):
    """Officer declines the request. The customer sees a neutral message; the reason stays with the officers."""
    body = TerminateIn(data=request.data or {})
    body.is_valid(raise_exception=True)
    reason = (body.validated_data.get("reason") or "").strip() or "Request not approved."
    s = ss.expire_if_stale(ss.get_or_404(session_id))
    if s.approval_status != "pending":
        raise AppError("INVALID_STATE_TRANSITION", f"This request is '{s.approval_status}', not waiting for approval.", 409)
    with transaction.atomic():
        n = VerificationSession.objects.filter(pk=s.pk, approval_status="pending").update(
            approval_status="rejected", status="cancelled", approved_by=request.user, approved_at=timezone.now(), approval_note=reason)
        if n != 1:
            raise AppError("INVALID_STATE_TRANSITION", "Another officer already handled this request.", 409)
        append_event(s.id, "session.rejected", {"officer_id": request.user.pk, "reason": reason})
    s.refresh_from_db()
    audit(request, "officer.reject_session", session_id=s.id, reason=reason)
    push(s)
    publish_customer(s.id, "session.rejected", {"message": "Your request was not approved. We will contact you about the next step."})
    return Response(SessionSerializer(s).data)


@extend_schema(tags=["officer"], request=AutoApproveIn, responses=SessionSerializer)
@api_view(["POST"])
@permission_classes([IsOfficer])
def auto_approve(request, session_id):
    """Officer switch: release every following challenge of this session automatically (no click per challenge)."""
    body = AutoApproveIn(data=request.data)
    body.is_valid(raise_exception=True)
    s = ss.get_or_404(session_id)
    if s.status in ("completed", "cancelled", "failed", "terminated"):
        raise AppError("INVALID_STATE_TRANSITION", f"Cannot change a session in state '{s.status}'.", 409)
    enabled = body.validated_data["enabled"]
    with transaction.atomic():
        s.challenge_auto_approve = enabled
        s.save(update_fields=["challenge_auto_approve", "updated_at"])
        append_event(s.id, "challenge.auto_approve_changed", {"enabled": enabled, "officer_id": request.user.pk})
    if enabled and s.status == "running":  # challenges already waiting for a click are released now
        from apps.challenges import services as cs
        from apps.challenges.serializers import CustomerChallengeSerializer
        for c in Challenge.objects.filter(session=s, status="awaiting_approval", approval_status="pending", expires_at__gt=timezone.now()):
            cs.release(c, request.user, get_runtime().settings.challenge_ttl_seconds)
            append_event(s.id, "challenge.approved", {"challenge_id": str(c.id), "type": c.challenge_type, "officer_id": request.user.pk, "auto": True})
            publish_customer(s.id, "challenge.released", dict(CustomerChallengeSerializer(c).data))
    audit(request, "officer.auto_approve_challenges", session_id=s.id, enabled=enabled)
    publish(s.id, "session.status", {"status": s.status, "final_risk_level": s.final_risk_level, "approval_status": s.approval_status, "challenge_auto_approve": enabled})
    return Response(SessionSerializer(s).data)


@extend_schema(tags=["officer"], parameters=[OpenApiParameter("limit", int)], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsOfficer])
def officer_dashboard(request):
    """The review console in one request: recent sessions with their current colour, document status and usable-signal count,
    the challenge approval queue, the customers asking to start, and the latest activity."""
    from apps.verification.dashboard import officer_dashboard as build  # lazy: reads several apps
    return Response(build(_int_param(request, "limit", 50, 1, 100)))
