from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsOfficer
from apps.decision_engine.serializers import AnalysisSerializer
from apps.decision_engine.services import build_analysis
from apps.evidence.services import append_event
from apps.realtime.events import publish
from apps.verification.services import get_or_404, require_running


@extend_schema(tags=["analysis"], request=None, responses=AnalysisSerializer)
@api_view(["POST"])
@permission_classes([IsOfficer])
def session_analysis(request, session_id):
    s = get_or_404(session_id)
    require_running(s)
    out = build_analysis(s)
    append_event(s.id, "analysis.snapshot", {"risk_level": out["recommendation"]["risk_level"]})
    publish(s.id, "risk.updated", out["recommendation"])
    publish(s.id, "analysis.completed", {"risk_level": out["recommendation"]["risk_level"]})
    return Response(out)


@extend_schema(tags=["analysis"], responses=AnalysisSerializer)
@api_view(["GET"])
@permission_classes([IsOfficer])
def get_analysis(request, session_id):
    return Response(build_analysis(get_or_404(session_id)))
