"""Developer model test lab API. Every endpoint requires a developer account (IsDeveloper): customers and officers get 403,
anonymous requests 401. Nothing here touches customer sessions, signals, evidence, challenges or WebSockets."""
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.auth import IsDeveloper
from apps.core.errors import AppError
from apps.core.runtime import get_runtime
from apps.core.uploads import read_upload
from apps.devlab import datasets, models_info, services
from apps.devlab.models import DevTestItem

UPLOAD_SCHEMA = {"multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}, "label": {"type": "string", "enum": ["", "real", "fake"]}}, "required": ["file"]}}


def _enabled():
    if not get_runtime().settings.enable_devlab:
        raise AppError("FEATURE_DISABLED", "The developer test lab is switched off on this server (ENABLE_DEVLAB).", 404)


@extend_schema(tags=["devlab"], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsDeveloper])
def models(request):
    """Detector health for offline testing: enabled, loaded, weights on disk, dependencies, thresholds and score meaning."""
    _enabled()
    return Response(models_info.status(get_runtime()))


@extend_schema(tags=["devlab"], request=None, responses={200: dict})
@api_view(["POST"])
@permission_classes([IsDeveloper])
def model_check(request, name):
    """Try to load one detector now (when PRELOAD_MODELS=false it otherwise loads on first use). A failed load is remembered
    by the detector until the server restarts, exactly as in the live pipeline."""
    _enabled()
    if name not in models_info.LISTED:
        raise AppError("UNKNOWN_DETECTOR", "Unknown detector.", 404)
    det = get_runtime().registry.get(name)
    if det is not None:
        det.ensure_loaded()
    return Response(models_info.status(get_runtime()))


@extend_schema(tags=["devlab"], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsDeveloper])
def dataset_list(request):
    _enabled()
    return Response(datasets.list_datasets(get_runtime().settings))


@extend_schema(methods=["GET"], tags=["devlab"], responses={200: dict})
@extend_schema(methods=["POST"], tags=["devlab"], request=dict, responses={201: dict})
@api_view(["GET", "POST"])
@permission_classes([IsDeveloper])
def jobs(request):
    """GET: your recent test jobs. POST: a new job. {"source": "upload"} starts a draft you add files to;
    {"source": "dataset", "dataset": name, "media_types": [...], "limit": n} queues a job over a local dataset at once.
    Options: aggregation (median | mean | top_quarter, for videos), video_frames (1-64), score_low_quality (bool)."""
    _enabled()
    if request.method == "GET":
        return Response({"items": services.list_jobs(request.user), "usage": services.usage(request.user)})
    body = request.data if isinstance(request.data, dict) else {}
    job = services.create_job(request.user, body)
    return Response(services.job_row(job), status=201)


@extend_schema(tags=["devlab"], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsDeveloper])
def job_detail(request, job_id):
    """A job with every item's result, dataset-level summary and (when labels exist) evaluation metrics."""
    _enabled()
    return Response(services.job_detail(services.get_job(request.user, job_id)))


@extend_schema(tags=["devlab"], request=UPLOAD_SCHEMA, responses={201: dict})
@api_view(["POST"])
@permission_classes([IsDeveloper])
@parser_classes([MultiPartParser, FormParser])
def job_items(request, job_id):
    """Add one test file to a draft job (one request per file keeps every request within the upload size limit). The type is
    taken from the file's content; the extension must agree; length and dimensions are checked before it is accepted."""
    _enabled()
    job = services.get_job(request.user, job_id)
    data = read_upload(request, get_runtime().settings.max_upload_mb)
    f = request.FILES.get("file")
    label = str(request.POST.get("label") or "").strip().lower()
    it = services.add_upload(job, getattr(f, "name", "") or "", data, label)
    return Response(services.item_row(it), status=201)


@extend_schema(tags=["devlab"], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsDeveloper])
def item_detail(request, job_id, item_id):
    _enabled()
    job = services.get_job(request.user, job_id)
    it = DevTestItem.objects.filter(job=job, pk=item_id).first() if _is_uuid(item_id) else None
    if it is None:
        raise AppError("ITEM_NOT_FOUND", "The test item was not found.", 404)
    return Response(services.item_row(it, full=True))


def _is_uuid(v) -> bool:
    import uuid
    try:
        uuid.UUID(str(v))
        return True
    except ValueError:
        return False


@extend_schema(tags=["devlab"], request=None, responses={200: dict})
@api_view(["POST"])
@permission_classes([IsDeveloper])
def job_start(request, job_id):
    _enabled()
    return Response(services.job_row(services.start(services.get_job(request.user, job_id))))


@extend_schema(tags=["devlab"], request=None, responses={200: dict})
@api_view(["POST"])
@permission_classes([IsDeveloper])
def job_cancel(request, job_id):
    """Stop a job: the item in progress finishes or stops at the next frame, the rest are marked cancelled, temporary files are deleted."""
    _enabled()
    return Response(services.job_row(services.cancel(services.get_job(request.user, job_id))))


@extend_schema(tags=["devlab"], request=None, responses={200: dict})
@api_view(["POST"])
@permission_classes([IsDeveloper])
def job_delete(request, job_id):
    _enabled()
    services.delete(services.get_job(request.user, job_id))
    return Response({"deleted": True})


@extend_schema(tags=["devlab"], responses={200: dict})
@api_view(["GET"])
@permission_classes([IsDeveloper])
def job_export(request, job_id):
    """?format=csv (default) or json. Contains results only, never the media."""
    _enabled()
    job = services.get_job(request.user, job_id)
    fmt = request.query_params.get("format", "csv")
    name = f"satyapan-devlab-{str(job.id)[:8]}"
    if fmt == "json":
        import json

        from django.core.serializers.json import DjangoJSONEncoder
        body = json.dumps(services.job_detail(job), cls=DjangoJSONEncoder, indent=2)
        resp = HttpResponse(body, content_type="application/json")
        resp["Content-Disposition"] = f'attachment; filename="{name}.json"'
        return resp
    if fmt != "csv":
        raise AppError("VALIDATION_ERROR", "format must be csv or json.", 422)
    resp = HttpResponse(services.export_csv(job), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{name}.csv"'
    return resp
