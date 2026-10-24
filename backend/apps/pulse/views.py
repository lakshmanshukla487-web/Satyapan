import numpy as np
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsCustomer
from apps.pulse.serializers import PulseTraceIn
from apps.signals.serializers import UploadReceivedOut
from apps.signals.services import finish_upload, run_detectors
from apps.verification.services import get_owned, require_running


@extend_schema(tags=["analysis"], request=PulseTraceIn, responses=UploadReceivedOut)
@api_view(["POST"])
@permission_classes([IsCustomer])
def pulse(request, session_id):
    """Family 5: a skin-colour trace over time (not video). The server runs POS to look for a pulse; supporting evidence only."""
    body = PulseTraceIn(data=request.data)
    body.is_valid(raise_exception=True)
    s = get_owned(session_id, request.user)
    require_running(s)
    media = (np.asarray(body.validated_data["rgb"], dtype=float), body.validated_data["fps"])
    sigs = run_detectors(s, ["pulse"], media, [])
    return Response(finish_upload(s, sigs))
