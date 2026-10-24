from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.accounts.auth import IsCustomer
from apps.core.media import audio_warnings, decode_audio
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
def audio(request, session_id):
    """Family 4, voice anti-spoof: a short audio clip, decoded in memory only."""
    s = get_owned(session_id, request.user)
    require_running(s)
    cfg = get_runtime().settings
    wave, sr = decode_audio(read_upload(request, cfg.max_upload_mb), cfg.max_audio_seconds)
    sigs = run_detectors(s, ["audio"], (wave, sr), audio_warnings(wave, sr))
    return Response(finish_upload(s, sigs))
