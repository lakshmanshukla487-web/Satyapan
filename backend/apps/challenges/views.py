import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsCustomer, IsOfficer
from apps.challenges import services as cs
from apps.challenges.models import Challenge
from apps.challenges.serializers import ChallengeChoiceIn, ChallengeResultIn, ChallengeSerializer, CustomerChallengeSerializer
from apps.core.audit import audit
from apps.core.errors import AppError
from apps.core.runtime import get_runtime
from apps.evidence.services import append_event
from apps.realtime.events import publish, publish_customer
from apps.verification.services import get_or_404, get_owned, get_visible, require_running


def _officer_data(c: Challenge, s) -> dict:
    return {**dict(ChallengeSerializer(c).data), "customer": s.owner.username if s.owner else None}


def _pending_or_404(s, challenge_id: str) -> Challenge:
    try:
        cid = uuid.UUID(challenge_id)
    except ValueError:
        raise AppError("CHALLENGE_NOT_FOUND", "The requested challenge was not found.", 404)
    c = Challenge.objects.filter(pk=cid, session=s).first()
    if c is None:
        raise AppError("CHALLENGE_NOT_FOUND", "The requested challenge was not found.", 404)
    if c.status != "awaiting_approval" or c.approval_status != "pending" or c.expires_at <= timezone.now():
        raise AppError("CHALLENGE_NOT_PENDING", "This challenge is not waiting for approval.", 409)
    return c


def _release(c: Challenge, s, officer) -> None:
    cs.release(c, officer, get_runtime().settings.challenge_ttl_seconds)


@extend_schema(methods=["POST"], tags=["challenges"], request=None, responses={201: CustomerChallengeSerializer})
@extend_schema(methods=["GET"], tags=["challenges"], responses=ChallengeSerializer(many=True))
@api_view(["GET", "POST"])
def challenges(request, session_id):
    if request.method == "GET":  # officers (any session) and customers (own sessions) may read
        s = get_visible(session_id, request.user)
        ser = ChallengeSerializer if request.user.is_officer else CustomerChallengeSerializer
        return Response(ser(Challenge.objects.filter(session=s).order_by("issued_at"), many=True).data)
    if request.user.is_officer:
        raise AppError("FORBIDDEN", "Officers review sessions; they cannot operate a customer's verification.", 403)
    s = get_owned(session_id, request.user)
    require_running(s)
    cfg = get_runtime().settings
    # Challenges continue for the WHOLE session (not a fixed number): the browser asks for the next one whenever the previous is
    # finished. If one is still open, that same one is returned, so a double click or a retry never piles challenges up.
    cs.expire_stale(s)
    open_c = Challenge.objects.filter(session=s, status__in=("awaiting_approval", "issued"), expires_at__gt=timezone.now()).order_by("-issued_at").first()
    if open_c is not None:
        return Response(CustomerChallengeSerializer(open_c).data, status=200)
    from apps.biometrics.services import iris_enrolled  # lazy: biometrics depends on challenges
    with transaction.atomic():
        seq = Challenge.objects.filter(session=s).count() + 1
        kind = cs.pick_kind(s.id, iris_enrolled(s))
        needs_officer = cfg.require_challenge_approval and not s.challenge_auto_approve
        if needs_officer:
            c = cs.issue(s.id, cfg.challenge_ttl_seconds, kind=kind, require_approval=True, approval_timeout=cfg.challenge_approval_timeout_seconds, sequence=seq)
            c.save()
            append_event(s.id, "challenge.generated", {"challenge_id": str(c.id), "type": c.challenge_type, "sequence": seq})
        else:
            c = cs.issue(s.id, cfg.challenge_ttl_seconds, kind=kind, sequence=seq)
            c.approval_status = "approved" if cfg.require_challenge_approval else "not_required"
            c.save()
            append_event(s.id, "challenge.issued", {"challenge_id": str(c.id), "type": c.challenge_type, "sequence": seq, "auto": True})
    if needs_officer:
        publish(s.id, "challenge.pending", _officer_data(c, s))
    else:
        publish(s.id, "challenge.issued", _officer_data(c, s))
    return Response(CustomerChallengeSerializer(c).data, status=201)


@extend_schema(tags=["challenges"], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsCustomer])
def challenge_current(request, session_id):
    """Polling fallback for the customer if the WebSocket drops: the newest challenge that still needs an answer
    (hidden while it waits for the officer, in full once released)."""
    s = get_owned(session_id, request.user)
    c = Challenge.objects.filter(session=s, status__in=("awaiting_approval", "issued"), expires_at__gt=timezone.now()).order_by("-issued_at").first()
    return Response({"challenge": CustomerChallengeSerializer(c).data if c else None})


@extend_schema(tags=["challenges"], request=ChallengeResultIn, responses=ChallengeSerializer)
@api_view(["POST"])
@permission_classes([IsCustomer])
def challenge_result(request, session_id, challenge_id):
    body = ChallengeResultIn(data=request.data)
    body.is_valid(raise_exception=True)
    s = get_owned(session_id, request.user)
    require_running(s)
    not_found = AppError("CHALLENGE_NOT_FOUND", "The requested challenge was not found.", 404)
    try:
        cid = uuid.UUID(challenge_id)
    except ValueError:
        raise not_found
    c = Challenge.objects.filter(pk=cid, session=s).first()  # ownership check
    if c is None:
        raise not_found
    if c.status == "answered":
        raise AppError("CHALLENGE_ALREADY_ANSWERED", "This challenge already has a result.", 409)
    if c.status == "awaiting_approval":
        raise AppError("CHALLENGE_NOT_APPROVED", "This check has not been released by the reviewing officer yet.", 409)
    if c.status == "expired" or c.expires_at <= timezone.now():
        if c.status != "expired":
            with transaction.atomic():
                c.status, c.result = "expired", None
                c.save()
                append_event(s.id, "challenge.expired", {"challenge_id": str(c.id), "type": c.challenge_type, "sequence": c.sequence})
        raise AppError("CHALLENGE_EXPIRED", "This challenge has expired. Issue a new one.", 410)
    if c.challenge_type == "eye_scan":
        raise AppError("USE_EYE_SCAN_ENDPOINT", "The eye scan is finished by sending close-up frames to the eye-scan endpoint.", 409)
    from apps.biometrics.services import pose_summary  # lazy: biometrics depends on challenges
    result, detail = cs.evaluate(c, body.validated_data["measured"], pose_summary(s, c))
    cs.record_result(s, c, result, detail, body.validated_data["measured"])
    return Response(CustomerChallengeSerializer(c).data)  # the customer is never told whether a challenge passed


# ---------------------------------------------------------------- officer approval workflow

@extend_schema(tags=["officer"], request=None, responses=ChallengeSerializer)
@api_view(["POST"])
@permission_classes([IsOfficer])
def challenge_approve(request, session_id, challenge_id):
    """Release a pending challenge: from now on the customer sees it."""
    s = get_or_404(session_id)
    require_running(s)
    c = _pending_or_404(s, challenge_id)
    with transaction.atomic():
        _release(c, s, request.user)
        append_event(s.id, "challenge.approved", {"challenge_id": str(c.id), "type": c.challenge_type, "officer_id": request.user.pk})
    audit(request, "officer.approve_challenge", session_id=s.id, challenge_id=str(c.id))
    publish(s.id, "challenge.approved", _officer_data(c, s))
    publish_customer(s.id, "challenge.released", dict(CustomerChallengeSerializer(c).data))  # the first time the customer receives the content
    return Response(ChallengeSerializer(c).data)


@extend_schema(tags=["officer"], request=ChallengeChoiceIn, responses=ChallengeSerializer)
@api_view(["POST"])
@permission_classes([IsOfficer])
def challenge_regenerate(request, session_id, challenge_id):
    """Reject the generated challenge and create a fresh hidden one (optionally of a type the officer chooses)."""
    body = ChallengeChoiceIn(data=request.data or {})
    body.is_valid(raise_exception=True)
    s = get_or_404(session_id)
    require_running(s)
    old = _pending_or_404(s, challenge_id)
    cfg = get_runtime().settings
    with transaction.atomic():
        old.status, old.approval_status = "expired", "regenerated"
        old.save()
        new = cs.issue(s.id, cfg.challenge_ttl_seconds, kind=body.validated_data.get("type"), require_approval=True, approval_timeout=cfg.challenge_approval_timeout_seconds, sequence=old.sequence)
        new.save()
        append_event(s.id, "challenge.regenerated", {"old_challenge_id": str(old.id), "challenge_id": str(new.id), "type": new.challenge_type, "officer_id": request.user.pk})
    audit(request, "officer.regenerate_challenge", session_id=s.id, challenge_id=str(old.id))
    publish(s.id, "challenge.pending", _officer_data(new, s))
    return Response(ChallengeSerializer(new).data, status=201)


@extend_schema(tags=["officer"], request=ChallengeChoiceIn, responses={201: ChallengeSerializer})
@api_view(["POST"])
@permission_classes([IsOfficer])
def challenge_issue(request, session_id):
    """The officer runs a check right now ("Run challenge"): created and released in one step, so no extra approval is needed."""
    body = ChallengeChoiceIn(data=request.data or {})
    body.is_valid(raise_exception=True)
    s = get_or_404(session_id)
    require_running(s)
    cfg = get_runtime().settings
    with transaction.atomic():
        cs.expire_stale(s)
        c = cs.issue(s.id, cfg.challenge_ttl_seconds, kind=body.validated_data.get("type"), sequence=Challenge.objects.filter(session=s).count() + 1)
        c.approval_status, c.approved_by, c.approved_at = "approved", request.user, timezone.now()
        c.save()
        append_event(s.id, "challenge.officer_issued", {"challenge_id": str(c.id), "type": c.challenge_type, "officer_id": request.user.pk})
    audit(request, "officer.issue_challenge", session_id=s.id, challenge_id=str(c.id))
    publish(s.id, "challenge.issued", _officer_data(c, s))
    publish_customer(s.id, "challenge.released", dict(CustomerChallengeSerializer(c).data))
    return Response(ChallengeSerializer(c).data, status=201)


@extend_schema(tags=["officer"], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsOfficer])
def pending_approvals(request):
    """Every challenge waiting for an officer, across running sessions (oldest first)."""
    rows = (Challenge.objects.filter(status="awaiting_approval", approval_status="pending", session__status="running", expires_at__gt=timezone.now())
            .select_related("session__owner").order_by("issued_at")[:50])
    return Response({"items": [{"challenge": dict(ChallengeSerializer(c).data), "session": {"id": str(c.session_id), "customer": c.session.owner.username if c.session.owner else None}} for c in rows]})
