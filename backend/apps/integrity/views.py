from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.auth import IsCustomer
from apps.core.runtime import get_runtime
from apps.integrity import services as isvc
from apps.integrity.serializers import IntegrityProbeIn
from apps.signals.serializers import UploadReceivedOut
from apps.signals.services import finish_upload, run_detectors
from apps.verification.services import get_owned, require_running


@extend_schema(tags=["analysis"], request=IntegrityProbeIn, responses=UploadReceivedOut)
@api_view(["POST"])
@permission_classes([IsCustomer])
def integrity(request, session_id):
    """Family 1: the browser's camera probe PLUS the server's own look at the connection (IP / VPN / proxy). The probe is
    client-reported, so it is only ever one voice among several; the IP part is observed by the server itself."""
    body = IntegrityProbeIn(data=request.data)
    body.is_valid(raise_exception=True)
    s = get_owned(session_id, request.user)
    require_running(s)
    probe = dict(body.validated_data)
    net = isvc.assess_request(request, s, probe.get("webrtc_ips") or [])
    sigs = run_detectors(s, ["integrity"], {"probe": probe, "net": net}, [])
    return Response(finish_upload(s, sigs))
