import json

import numpy as np
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.accounts.auth import IsCustomer
from apps.biometrics import services as bs
from apps.biometrics.models import Observation
from apps.challenges import services as cs
from apps.challenges.models import Challenge
from apps.challenges.serializers import ChallengeSerializer
from apps.core.errors import AppError
from apps.core.media import decode_image, image_warnings
from apps.core.runtime import get_runtime
from apps.core.uploads import read_upload
from apps.core.validation import read_limited
from apps.evidence.services import append_event
from apps.signals.services import finish_upload, run_detectors
from apps.verification.services import get_owned, get_visible, require_consent, require_running

UPLOAD_SCHEMA = {"multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}, "required": ["file"]}}
MAX_EYE_FRAMES = 6


def _in_pool(rt, fn, *args):
    if not rt.gate.enter():
        raise AppError("SERVER_BUSY", "The analysis service is busy. Please try again in a moment.", 503, retry_after=2)
    try:
        return rt.pool.submit(fn, *args).result()
    finally:
        rt.gate.leave()


@extend_schema(tags=["biometrics"], request=UPLOAD_SCHEMA, responses={200: dict})
@api_view(["GET", "POST"])
@permission_classes([IsCustomer])
@parser_classes([MultiPartParser])
def reference_photo(request, session_id):
    """The close-up photo (eyes wide open) the customer uploads before the live step. Analysed in memory; only a face embedding
    and iris templates are kept. Returns what to fix when the photo is unusable."""
    s = get_owned(session_id, request.user)
    if request.method == "GET":
        ref = bs.get_reference(s)
        return Response({"uploaded": ref is not None, "face_check": "ok" if ref and ref.face_embedding else ("unavailable" if ref else None),
                         "iris_check": "ok" if bs.iris_enrolled(s) else ("low_detail" if ref else None)})
    require_consent(s)
    if s.status not in ("ready", "running"):
        raise AppError("INVALID_STATE_TRANSITION", "The photo can only be uploaded before the session ends.", 409)
    cfg = get_runtime().settings
    raw = read_upload(request, cfg.max_upload_mb)
    img = decode_image(raw, cfg.max_image_dimension)
    rt = get_runtime()
    analysed = _in_pool(rt, bs.analyse_reference, rt, np.asarray(img))  # models in the worker pool ...
    return Response(bs.save_reference(s, analysed, raw))                # ... the database write here, in the request thread


@extend_schema(tags=["biometrics"], request=UPLOAD_SCHEMA, responses={200: dict})
@api_view(["POST"])
@permission_classes([IsCustomer])
@parser_classes([MultiPartParser])
def eye_scan(request, session_id, challenge_id):
    """Finishes an 'eye_scan' challenge: 2-6 close-up frames (field name `file`, repeated). The SERVER decides the result: the
    customer was close to the camera with eyes wide open, and the iris pattern matches the enrolment photo (or does not)."""
    s = get_owned(session_id, request.user)
    require_running(s)
    c = Challenge.objects.filter(pk=challenge_id, session=s).first() if _is_uuid(challenge_id) else None
    if c is None or c.challenge_type != "eye_scan":
        raise AppError("CHALLENGE_NOT_FOUND", "The requested challenge was not found.", 404)
    if c.status == "answered":
        raise AppError("CHALLENGE_ALREADY_ANSWERED", "This challenge already has a result.", 409)
    if c.status == "awaiting_approval":
        raise AppError("CHALLENGE_NOT_APPROVED", "This check has not been released by the reviewing officer yet.", 409)
    if c.status == "expired" or c.expires_at <= timezone.now():
        raise AppError("CHALLENGE_EXPIRED", "This challenge has expired.", 410)
    cfg = get_runtime().settings
    files = request.FILES.getlist("file")[:MAX_EYE_FRAMES]
    if not files:
        raise AppError("VALIDATION_ERROR", "Send 2 to 6 close-up frames.", 422)
    frames = [np.asarray(decode_image(read_limited(f, cfg.max_upload_mb), cfg.max_image_dimension)) for f in files]
    ref = bs.get_reference(s)
    sigs = run_detectors(s, ["eyescan"], {"frames": frames, "ref": ref.iris if ref else {}}, [])
    sig = sigs[0] if sigs else None
    d = (sig.details if sig else {}) or {}
    close_ok, wide_ok = d.get("max_eye_distance_fraction", 0) >= 0.2, d.get("max_eye_openness", 0) >= 0.24
    if sig is None or sig.status in ("unavailable", "error"):
        result, reason = "unavailable", "The iris scan is not available on this server (models missing)."
    elif sig.status == "low_quality":
        why = {"NO_REFERENCE_IRIS": "no usable iris was captured in the enrolment photo",
               "IRIS_DETAIL_TOO_LOW": "the eyes were too small or blurry in the scan" + ("" if close_ok else " (not close enough to the camera)")}.get(sig.error_code or "", sig.error_code or "unknown")
        result, reason = "unavailable", f"Not enough eye detail to compare: {why}."
    elif d.get("verdict") == "mismatch":
        result, reason = "failed", f"The iris pattern differs from the enrolment photo (distance {d['hamming_distance']:.2f}; mismatch from {cfg.iris_mismatch_hd})."
    elif d.get("verdict") == "match":
        if close_ok and wide_ok:
            result, reason = "passed", f"Close-up eye scan done and the iris pattern matches the enrolment photo (distance {d['hamming_distance']:.2f})."
        else:
            result, reason = "unavailable", "The iris matched, but the customer was not close enough or did not open the eyes wide, so the scan is not counted."
    else:
        result, reason = "unavailable", f"The iris comparison was inconclusive (distance {d.get('hamming_distance', 0):.2f}); not counted for or against."
    if sig is not None and sig.status == "ok":
        Observation.objects.create(session=s, kind="iris_match", challenge_id=c.id, value=d.get("hamming_distance"), quality=d.get("frames_with_usable_iris"),
                                   data={"verdict": d.get("verdict"), "readings": d.get("readings")})
    detail = {"reason": reason, "verification": "server_only", "iris": {k: d.get(k) for k in ("verdict", "hamming_distance", "readings", "frames_with_usable_iris", "max_eye_distance_fraction", "max_eye_openness")}}
    cs.record_result(s, c, result, detail, {})
    return Response({"received": True})


def _is_uuid(v: str) -> bool:
    import uuid
    try:
        uuid.UUID(v)
        return True
    except ValueError:
        return False


@extend_schema(tags=["biometrics"], responses={200: dict})
@api_view(["GET"])
def biometrics_summary(request, session_id):
    """Officer (and the report) view of the identity checks: face match series, iris scans, document faces, reference photo status."""
    s = get_visible(session_id, request.user)
    if not request.user.is_officer:
        raise AppError("FORBIDDEN", "This resource is only available to officers.", 403)
    from apps.biometrics.summary import summarise
    return Response(summarise(s))
