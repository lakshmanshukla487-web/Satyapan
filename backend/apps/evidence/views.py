from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsOfficer
from apps.core.audit import audit
from apps.core.errors import AppError
from apps.decision_engine.services import current_decision
from apps.evidence.hashing import verify_chain
from apps.evidence.models import EvidenceEvent
from apps.evidence.services import build_packet, event_dict, list_events, verify_stored
from apps.verification.services import get_or_404


class EvidenceEventIn(serializers.Serializer):
    # trim_whitespace=False: hashed fields must be compared exactly as supplied.
    seq = serializers.IntegerField()
    event_type = serializers.CharField(allow_blank=True, trim_whitespace=False)
    timestamp = serializers.CharField(allow_blank=True, trim_whitespace=False)
    payload = serializers.DictField()
    previous_hash = serializers.CharField(allow_blank=True, trim_whitespace=False)
    event_hash = serializers.CharField(allow_blank=True, trim_whitespace=False)


class EvidenceVerifyIn(serializers.Serializer):
    events = EvidenceEventIn(many=True, required=False, allow_null=True)  # omit to verify the stored chain


class EvidenceVerifyOut(serializers.Serializer):  # documentation only
    valid = serializers.BooleanField()
    checked = serializers.IntegerField()
    first_mismatch_index = serializers.IntegerField(allow_null=True)
    first_mismatch_seq = serializers.IntegerField(allow_null=True)
    reason = serializers.CharField(allow_null=True)
    note = serializers.CharField()


@extend_schema(tags=["evidence"], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsOfficer])
def evidence(request, session_id):
    """The session's evidence chain. ?tail=N returns only the newest N events (the live workspace polls this; the full chain and
    its verification stay available without the parameter). Reading the full chain is audited; the live tail view is not, so a
    watching officer does not write an audit row every few seconds."""
    s = get_or_404(session_id)
    raw_tail = request.query_params.get("tail")
    if raw_tail is not None:
        try:
            tail = int(raw_tail)
        except ValueError:
            raise AppError("VALIDATION_ERROR", "tail must be an integer.", 422)
        if not 1 <= tail <= 500:
            raise AppError("VALIDATION_ERROR", "tail is out of range (1-500).", 422)
        rows = list(EvidenceEvent.objects.filter(session_id=s.id).order_by("-seq")[:tail])
        total = EvidenceEvent.objects.filter(session_id=s.id).count()
        return Response({"session_id": str(s.id), "events": [event_dict(e) for e in reversed(rows)], "total": total, "partial": total > len(rows)})
    audit(request, "officer.read_evidence", session_id=s.id)
    return Response({"session_id": str(s.id), "events": list_events(s.id), "verification": verify_stored(s.id)})


@extend_schema(tags=["evidence"], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsOfficer])
def export(request, session_id):
    s = get_or_404(session_id)
    audit(request, "officer.export_evidence", session_id=s.id)
    return Response(build_packet(s, current_decision(s)))


@extend_schema(tags=["evidence"], request=EvidenceVerifyIn, responses=EvidenceVerifyOut)
@api_view(["POST"])
@permission_classes([IsOfficer])
def verify(request, session_id):
    s = get_or_404(session_id)
    body = EvidenceVerifyIn(data=request.data or {})
    body.is_valid(raise_exception=True)
    events = body.validated_data.get("events")
    if events is not None:
        return Response(verify_chain(str(s.id), [dict(e) for e in events]))
    return Response(verify_stored(s.id))
