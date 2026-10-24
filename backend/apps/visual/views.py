from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from django.utils import timezone

from apps.accounts.auth import IsCustomer
from apps.biometrics import services as bio
from apps.challenges.models import Challenge
from apps.core.media import decode_image, image_warnings
from apps.core.runtime import get_runtime
from apps.core.uploads import read_upload
from apps.signals.serializers import UploadReceivedOut
from apps.signals.services import finish_upload, run_detectors
from apps.verification.services import get_owned, require_running

UPLOAD_SCHEMA = {"multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}, "required": ["file"]}}


@extend_schema(tags=["analysis"], request=UPLOAD_SCHEMA, responses=UploadReceivedOut)
@api_view(["POST"])
@permission_classes([IsCustomer])
@parser_classes([MultiPartParser])
def frame(request, session_id):
    """One video frame, decoded in memory only: video deepfake classifier + face landmarks + face match against the reference photo.

    With a `challenge_id` field the frame belongs to a challenge in progress: only the cheap checks run (landmarks, face match) and
    the server's own head-pose / eye / mouth measurement is stored, to cross-check what the browser reports for that challenge."""
    s = get_owned(session_id, request.user)
    require_running(s)
    cfg = get_runtime().settings
    img = decode_image(read_upload(request, cfg.max_upload_mb), cfg.max_image_dimension)
    warnings = image_warnings(img)
    challenge = None
    cid = request.POST.get("challenge_id")
    if cid:
        try:
            challenge = Challenge.objects.filter(pk=cid, session=s, status="issued", expires_at__gt=timezone.now()).first()
        except (ValueError, TypeError):
            challenge = None
    sigs = run_detectors(s, ["landmarks"] if challenge else ["vit", "xception", "landmarks"], img, warnings)
    ref = bio.get_reference(s)
    if ref is not None and ref.face_embedding:
        sigs += run_detectors(s, ["facematch"], {"img": img, "ref": ref.face_embedding}, warnings)
    if challenge is not None:
        for x in sigs:
            if x.detector_name == "landmarks" and x.status == "ok" and (x.details or {}).get("pose"):
                bio.record_pose(s, challenge.id, x.details["pose"])
    return Response(finish_upload(s, sigs))
