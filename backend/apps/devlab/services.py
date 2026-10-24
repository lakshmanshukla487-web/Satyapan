"""Developer test jobs: creation, uploads into isolated temporary storage, start / cancel / delete, results, export, cleanup."""
from __future__ import annotations

import csv
import io
import logging
import os
import shutil
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.core.errors import AppError
from apps.core.runtime import get_runtime
from apps.devlab import datasets, media as M, metrics, runner
from apps.devlab.models import DevTestItem, DevTestJob

log = logging.getLogger("satyapan.devlab")
ACTIVE = ("queued", "running")
FINISHED = ("completed", "cancelled", "failed")
DRAFT_TTL = timedelta(hours=2)
_last_cleanup = 0.0
_cleanup_lock = threading.Lock()


# ---- storage ---------------------------------------------------------------------------------------------------------------------

def storage_root(cfg) -> Path:
    p = Path(cfg.devlab_storage_dir)
    if not p.is_absolute():
        from satyapan.conf import BASE_DIR
        p = BASE_DIR / p
    return p


def _job_dir(cfg, job_id) -> Path:
    d = storage_root(cfg) / "jobs" / str(uuid.UUID(str(job_id)))
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # never overwrite, never readable by other users
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _remove_job_files(cfg, job_id) -> None:
    d = storage_root(cfg) / "jobs" / str(job_id)
    if d.is_dir() and not d.is_symlink():
        shutil.rmtree(d, ignore_errors=True)


# ---- jobs ------------------------------------------------------------------------------------------------------------------------

def _options(raw: dict, cfg) -> dict:
    agg = raw.get("aggregation") or "median"
    if agg not in runner.AGGREGATIONS:
        raise AppError("VALIDATION_ERROR", f"aggregation must be one of {list(runner.AGGREGATIONS)}.", 422)
    try:
        frames = int(raw.get("video_frames") or cfg.devlab_video_frames)
    except (TypeError, ValueError):
        raise AppError("VALIDATION_ERROR", "video_frames must be an integer.", 422)
    if not 1 <= frames <= M.MAX_FRAMES_CAP:
        raise AppError("VALIDATION_ERROR", f"video_frames must be between 1 and {M.MAX_FRAMES_CAP}.", 422)
    return {"aggregation": agg, "video_frames": frames, "score_low_quality": bool(raw.get("score_low_quality"))}


def _check_active_limit(user, cfg) -> None:
    if DevTestJob.objects.filter(owner=user, status__in=ACTIVE).count() >= cfg.devlab_max_active_jobs:
        raise AppError("TOO_MANY_ACTIVE_JOBS", f"You already have {cfg.devlab_max_active_jobs} test jobs waiting or running. Wait for one to finish or cancel it.", 409)


def create_job(user, body: dict) -> DevTestJob:
    cfg = get_runtime().settings
    maybe_cleanup()
    opts = _options(body, cfg)
    name = str(body.get("name") or "").strip()[:120]
    source = body.get("source") or "upload"
    if source == "upload":
        if DevTestJob.objects.filter(owner=user, status="draft").count() >= 5:
            raise AppError("TOO_MANY_DRAFTS", "You have several unfinished uploads. Start or delete them first.", 409)
        return DevTestJob.objects.create(owner=user, name=name or "Uploaded test files", source="upload", status="draft", options=opts)
    if source != "dataset":
        raise AppError("VALIDATION_ERROR", "source must be 'upload' or 'dataset'.", 422)
    _check_active_limit(user, cfg)
    ds = str(body.get("dataset") or "")
    types = {t for t in (body.get("media_types") or []) if t in (M.IMAGE, M.AUDIO, M.VIDEO)} or None
    try:
        limit = min(int(body.get("limit") or cfg.devlab_max_items_per_job), cfg.devlab_max_items_per_job)
    except (TypeError, ValueError):
        raise AppError("VALIDATION_ERROR", "limit must be an integer.", 422)
    files = datasets.scan(cfg, ds, types, limit=max(1, limit))
    if not files:
        raise AppError("DATASET_EMPTY", "The dataset has no supported files for the chosen media types.", 422)
    with transaction.atomic():
        job = DevTestJob.objects.create(owner=user, name=name or f"Dataset {ds}", source="dataset", dataset=ds, status="queued", options=opts,
                                        total_items=len(files), total_bytes=sum(f["size"] for f in files))
        DevTestItem.objects.bulk_create([DevTestItem(job=job, index=i, filename=M.safe_filename(f["rel"]), media_type=f["media_type"],
                                                     file_format=Path(f["rel"]).suffix.lower().lstrip(".")[:10], size_bytes=f["size"], label=f["label"],
                                                     stored_path=f["rel"], owns_file=False) for i, f in enumerate(files)])
    runner.schedule(job.id)
    return job


def get_job(user, job_id) -> DevTestJob:
    try:
        jid = uuid.UUID(str(job_id))
    except ValueError:
        raise AppError("JOB_NOT_FOUND", "The test job was not found.", 404)
    job = DevTestJob.objects.filter(pk=jid, owner=user).first()  # developers only ever see their own jobs
    if job is None:
        raise AppError("JOB_NOT_FOUND", "The test job was not found.", 404)
    return job


def add_upload(job: DevTestJob, filename: str, data: bytes, label: str) -> DevTestItem:
    cfg = get_runtime().settings
    if job.status != "draft":
        raise AppError("JOB_NOT_EDITABLE", "Files can only be added before the job starts.", 409)
    if label not in ("", "real", "fake"):
        raise AppError("VALIDATION_ERROR", "label must be 'real', 'fake' or empty.", 422)
    name = M.safe_filename(filename)
    media, fmt = M.identify(name, data[:64])
    if job.total_items >= cfg.devlab_max_items_per_job:
        raise AppError("JOB_FULL", f"A job holds at most {cfg.devlab_max_items_per_job} files.", 409)
    if job.total_bytes + len(data) > cfg.devlab_max_job_mb * 1024 * 1024:
        raise AppError("JOB_TOO_LARGE", f"A job holds at most {cfg.devlab_max_job_mb} MB of files.", 413)
    item_id = uuid.uuid4()
    path = _job_dir(cfg, job.id) / f"{item_id.hex}.{fmt}"  # the client's file name is never used as a path
    _write_private(path, data)
    try:
        info = M.probe(path, media, fmt, cfg)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    with transaction.atomic():
        locked = DevTestJob.objects.select_for_update().get(pk=job.pk)
        if locked.status != "draft":
            path.unlink(missing_ok=True)
            raise AppError("JOB_NOT_EDITABLE", "Files can only be added before the job starts.", 409)
        it = DevTestItem.objects.create(id=item_id, job=locked, index=locked.total_items, filename=name, media_type=media, file_format=fmt, size_bytes=len(data),
                                        label=label, stored_path=str(path), owns_file=True, details={"probe": info})
        DevTestJob.objects.filter(pk=job.pk).update(total_items=locked.total_items + 1, total_bytes=locked.total_bytes + len(data))
    return it


def start(job: DevTestJob) -> DevTestJob:
    cfg = get_runtime().settings
    if job.status != "draft":
        raise AppError("JOB_NOT_EDITABLE", "This job has already been started.", 409)
    if not DevTestItem.objects.filter(job=job).exists():
        raise AppError("JOB_EMPTY", "Add at least one file before starting.", 422)
    _check_active_limit(job.owner, cfg)
    if DevTestJob.objects.filter(pk=job.pk, status="draft").update(status="queued") != 1:
        raise AppError("JOB_NOT_EDITABLE", "This job has already been started.", 409)
    runner.schedule(job.id)
    job.refresh_from_db()
    return job


def cancel(job: DevTestJob) -> DevTestJob:
    if job.status in FINISHED:
        return job
    DevTestJob.objects.filter(pk=job.pk).update(cancel_requested=True)
    if job.status in ("draft", "queued"):  # nothing is running: close it now
        if DevTestJob.objects.filter(pk=job.pk, status__in=("draft", "queued")).update(status="cancelled", finished_at=timezone.now()):
            runner._cancel_remaining(str(job.pk))
            _remove_job_files(get_runtime().settings, job.pk)
    job.refresh_from_db()
    return job


def delete(job: DevTestJob) -> None:
    if job.status == "running":
        raise AppError("JOB_RUNNING", "Cancel the job first; it can be deleted once it has stopped.", 409)
    if job.status == "queued":
        cancel(job)
    _remove_job_files(get_runtime().settings, job.pk)
    job.delete()


def maybe_cleanup(force: bool = False) -> dict:
    """Delete expired jobs and their files (finished > DEVLAB_RETENTION_HOURS, unstarted drafts > 2 h) and orphaned folders.
    Runs at most every 10 minutes per process unless forced (manage.py devlab_cleanup)."""
    global _last_cleanup
    with _cleanup_lock:
        if not force and time.monotonic() - _last_cleanup < 600:
            return {}
        _last_cleanup = time.monotonic()
    cfg = get_runtime().settings
    now = timezone.now()
    old = DevTestJob.objects.filter(status__in=FINISHED, created_at__lt=now - timedelta(hours=cfg.devlab_retention_hours))
    drafts = DevTestJob.objects.filter(status="draft", created_at__lt=now - DRAFT_TTL)
    n = 0
    for job in list(old) + list(drafts):
        _remove_job_files(cfg, job.pk)
        job.delete()
        n += 1
    orphans = 0
    jobs_dir = storage_root(cfg) / "jobs"
    if jobs_dir.is_dir():
        known = {str(x) for x in DevTestJob.objects.values_list("id", flat=True)}
        for d in jobs_dir.iterdir():
            if d.is_dir() and not d.is_symlink() and d.name not in known:
                shutil.rmtree(d, ignore_errors=True)
                orphans += 1
    if n or orphans:
        log.info("devlab cleanup removed %d job(s) and %d orphaned folder(s)", n, orphans)
    return {"jobs_removed": n, "orphan_folders_removed": orphans}


# ---- representation -------------------------------------------------------------------------------------------------------------

def item_row(it: DevTestItem, full: bool = False) -> dict:
    row = {"id": str(it.id), "index": it.index, "filename": it.filename, "media_type": it.media_type, "file_format": it.file_format, "size_bytes": it.size_bytes,
           "label": it.label, "status": it.status, "detector": it.detector, "model_id": it.model_id, "model_version": it.model_version, "score": it.score,
           "score_kind": it.score_kind, "threshold": it.threshold, "prediction": it.prediction, "model_label": it.model_label, "duration_ms": it.duration_ms,
           "frames_analyzed": it.frames_analyzed, "segments_analyzed": it.segments_analyzed, "warnings": it.warnings, "error_code": it.error_code,
           "correct": (it.prediction == it.label) if it.label in ("real", "fake") and it.prediction in ("real", "fake") else None,
           "finished_at": it.finished_at}
    if full:
        row["details"] = it.details
    return row


def job_row(job: DevTestJob) -> dict:
    counts = dict(DevTestItem.objects.filter(job=job).values_list("status").annotate(n=Count("id")))
    finished = sum(v for k, v in counts.items() if k not in ("queued", "running"))
    return {"id": str(job.id), "name": job.name, "source": job.source, "dataset": job.dataset or None, "status": job.status, "options": job.options,
            "total_items": job.total_items, "total_bytes": job.total_bytes, "finished_items": finished, "counts": counts, "cancel_requested": job.cancel_requested,
            "error": job.error or None, "created_at": job.created_at, "started_at": job.started_at, "finished_at": job.finished_at,
            "expires_at": job.created_at + (DRAFT_TTL if job.status == "draft" else timedelta(hours=get_runtime().settings.devlab_retention_hours))}


def job_detail(job: DevTestJob) -> dict:
    items = list(DevTestItem.objects.filter(job=job).order_by("index"))
    rows = [item_row(it) for it in items]
    return {"job": job_row(job), "items": rows, "summary": metrics.summary(rows), "metrics": metrics.evaluate(rows)}


def list_jobs(user) -> list[dict]:
    runner.recover_stale(owner=user)
    maybe_cleanup()
    return [job_row(j) for j in DevTestJob.objects.filter(owner=user).order_by("-created_at")[:50]]


def usage(user) -> dict:
    agg = DevTestJob.objects.filter(owner=user).aggregate(n=Count("id"), b=Sum("total_bytes"))
    return {"jobs": agg["n"] or 0, "bytes": agg["b"] or 0}


_CSV_COLUMNS = ["index", "filename", "media_type", "file_format", "size_bytes", "label", "status", "detector", "model_id", "model_version", "score",
                "score_kind", "threshold", "prediction", "model_label", "correct", "duration_ms", "frames_analyzed", "segments_analyzed", "warnings", "error_code"]


def _cell(v) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    s = "" if v is None else (";".join(map(str, v)) if isinstance(v, list) else str(v))
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s  # spreadsheet formula injection guard


def export_csv(job: DevTestJob) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_CSV_COLUMNS)
    for it in DevTestItem.objects.filter(job=job).order_by("index"):
        row = item_row(it)
        w.writerow([_cell(row[c]) for c in _CSV_COLUMNS])
    return buf.getvalue()
