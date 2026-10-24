import json

import numpy as np
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.accounts.auth import IsCustomer
from apps.avsync import pipeline
from apps.biometrics import faces
from apps.core.errors import AppError
from apps.core.media import decode_audio, decode_image, resample
from apps.core.runtime import get_runtime
from apps.core.validation import read_limited
from apps.signals.services import finish_upload, run_detectors
from apps.verification.services import get_owned, require_running

MAX_FRAMES = 90
CLIP_SCHEMA = {"multipart/form-data": {"type": "object", "properties": {
    "frames": {"type": "array", "items": {"type": "string", "format": "binary"}}, "times": {"type": "string", "description": "JSON array of seconds, one per frame, measured from the first audio sample"},
    "audio": {"type": "string", "format": "binary"}}}}


@extend_schema(tags=["analysis"], request=CLIP_SCHEMA, responses={200: dict})
@api_view(["POST"])
@permission_classes([IsCustomer])
@parser_classes([MultiPartParser])
def avsync(request, session_id):
    """Family 3, lip sync: 2-4 s of speech as JPEG frames (+ their timestamps) and a WAV of the same moment. SyncNet checks that
    the voice matches the lip movement. Everything is decoded in memory and discarded."""
    s = get_owned(session_id, request.user)
    require_running(s)
    cfg = get_runtime().settings
    files, audio_file = request.FILES.getlist("frames")[:MAX_FRAMES], request.FILES.get("audio")
    if len(files) < 20 or audio_file is None:
        raise AppError("VALIDATION_ERROR", "Send at least 20 frames, their timestamps and the audio.", 422)
    try:
        times = [float(x) for x in json.loads(request.POST.get("times", "[]"))]
    except (ValueError, TypeError):
        raise AppError("VALIDATION_ERROR", "times must be a JSON array of numbers.", 422)
    if len(times) != len(files) or any(b < a for a, b in zip(times, times[1:])):
        raise AppError("VALIDATION_ERROR", "times must have one increasing value per frame.", 422)
    wave, sr = decode_audio(read_limited(audio_file, cfg.max_upload_mb), cfg.max_audio_seconds)
    wave16 = resample(wave, sr, 16000)
    warnings: list[str] = []
    media = None
    frames = [np.asarray(decode_image(read_limited(f, 2), cfg.max_image_dimension)) for f in files]
    keep = [i for i, t in enumerate(times) if t >= 0]
    frames, times = [frames[i] for i in keep], [times[i] for i in keep]
    duration = min(len(wave16) / 16000.0, (times[-1] if times else 0.0))
    eng = faces.engine_or_none(cfg.model_dir)
    if len(frames) < 20 or duration < 1.6:
        warnings.append("CLIP_TOO_SHORT")
    elif pipeline.speech_fraction(wave16) < 0.25:
        warnings.append("NO_SPEECH")
    elif eng is None:
        warnings.append("FACE_ENGINE_UNAVAILABLE")
    else:
        idx = pipeline.resample_to_grid(times, len(frames), duration)
        grid = [frames[i] for i in idx]
        crops, info = pipeline.crop_faces(grid, eng.detect)
        if crops is None:
            warnings.append("NO_FACE")
        else:
            media = {"frames": crops, "wave": wave16[: int(len(crops) * 640)]}
    sigs = run_detectors(s, ["syncnet"], media, warnings)
    return Response(finish_upload(s, sigs))
