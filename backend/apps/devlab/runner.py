"""Runs developer test jobs through the REAL detectors, on a separate execution path from live customer sessions.

* Same detector objects (loaded once at server start) and same preprocessing as the live pipeline; nothing is mocked. A detector
  that is disabled, missing weights or failing reports that state on every item; no score is ever invented.
* Results go only to the devlab tables. Nothing here writes a detector signal, an evidence event, a challenge, a session, an
  audit record about a customer, or publishes on a WebSocket.
* Resource limits: one job at a time per process (DEVLAB_MAX_CONCURRENT_JOBS), one inference at a time per job, through the
  same bounded model pool and back-pressure gate as live traffic, while always leaving DEVLAB_LIVE_RESERVE queue slots to
  live sessions (the lab waits instead of pushing a customer into SERVER_BUSY).
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from django.db import close_old_connections, connections
from django.utils import timezone

from apps.core.errors import AppError
from apps.core.runtime import get_runtime
from apps.devlab import media as M
from apps.devlab.models import DevTestItem, DevTestJob
from apps.devlab.models_info import DETECTOR_FOR, model_version

log = logging.getLogger("satyapan.devlab")
AGGREGATIONS = ("median", "mean", "top_quarter")
GATE_WAIT_S = 180          # longest wait for a free model slot before an item is reported SERVER_BUSY
INFERENCE_TIMEOUT_S = 600
STALE_AFTER = timedelta(minutes=10)

_executor: ThreadPoolExecutor | None = None
_scheduled: set[str] = set()
_lock = threading.Lock()


class _Cancelled(Exception):
    pass


def _get_executor(workers: int) -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="devlab")
        return _executor


def schedule(job_id) -> None:
    """Hand a queued job to this process's worker (or run it now, in tests). Safe to call twice: the job is claimed atomically."""
    cfg = get_runtime().settings
    jid = str(job_id)
    if cfg.devlab_run_inline:
        run_job(jid)
        return
    with _lock:
        if jid in _scheduled:
            return
        _scheduled.add(jid)
    _get_executor(cfg.devlab_max_concurrent_jobs).submit(_thread_main, jid)


def is_scheduled(job_id) -> bool:
    with _lock:
        return str(job_id) in _scheduled


def _thread_main(job_id: str) -> None:
    close_old_connections()
    try:
        run_job(job_id)
    except Exception as e:  # noqa: BLE001  (never let a worker die silently)
        log.error("devlab job %s crashed: %s", job_id, type(e).__name__, exc_info=e)
        DevTestJob.objects.filter(pk=job_id, status__in=("queued", "running")).update(status="failed", error="Internal error while running the job.", finished_at=timezone.now())
        _cancel_remaining(job_id)
    finally:
        with _lock:
            _scheduled.discard(job_id)
        connections.close_all()  # a worker thread must not keep database connections open


def _cancelled(job_id: str) -> bool:
    return DevTestJob.objects.filter(pk=job_id, cancel_requested=True).exists()


def _cancel_remaining(job_id: str) -> None:
    for it in DevTestItem.objects.filter(job_id=job_id, status__in=("queued", "running")):
        delete_owned_file(it)
        DevTestItem.objects.filter(pk=it.pk).update(status="cancelled", finished_at=timezone.now(), stored_path="" if it.owns_file else it.stored_path)


def delete_owned_file(it: DevTestItem) -> None:
    """Temporary uploads are deleted as soon as they are no longer needed. Dataset files are never touched."""
    if it.owns_file and it.stored_path:
        try:
            Path(it.stored_path).unlink(missing_ok=True)
        except OSError as e:
            log.warning("devlab could not delete a temporary file: %s", type(e).__name__)


def run_job(job_id: str) -> None:
    now = timezone.now()
    if DevTestJob.objects.filter(pk=job_id, status="queued").update(status="running", started_at=now, heartbeat_at=now) != 1:
        return  # cancelled meanwhile, or another worker claimed it
    job = DevTestJob.objects.get(pk=job_id)
    rt = get_runtime()
    stopped = False
    for it in DevTestItem.objects.filter(job_id=job_id, status="queued").order_by("index"):
        if _cancelled(job_id):
            stopped = True
            break
        DevTestItem.objects.filter(pk=it.pk).update(status="running")
        t0 = time.perf_counter()
        try:
            out = process_item(rt, job, it, lambda: _cancelled(job_id))
        except _Cancelled:
            out, stopped = {"status": "cancelled"}, True
        except AppError as e:
            out = {"status": "error", "error_code": e.code, "details": {"message": e.message}}
        except MemoryError:
            out = {"status": "error", "error_code": "OUT_OF_MEMORY"}
        except Exception as e:  # noqa: BLE001
            log.warning("devlab item failed: %s", type(e).__name__)
            out = {"status": "error", "error_code": "INTERNAL_ERROR"}
        finally:
            delete_owned_file(it)
        out.setdefault("duration_ms", round((time.perf_counter() - t0) * 1000, 1))
        fields = {k: v for k, v in out.items() if k in _ITEM_FIELDS}
        if it.owns_file:
            fields["stored_path"] = ""
        DevTestItem.objects.filter(pk=it.pk).update(finished_at=timezone.now(), **fields)
        DevTestJob.objects.filter(pk=job_id).update(heartbeat_at=timezone.now())
        if stopped:
            break
    if stopped or _cancelled(job_id):
        _cancel_remaining(job_id)
        DevTestJob.objects.filter(pk=job_id).update(status="cancelled", finished_at=timezone.now())
    else:
        DevTestJob.objects.filter(pk=job_id, status="running").update(status="completed", finished_at=timezone.now())


_ITEM_FIELDS = {"status", "detector", "model_id", "model_version", "score", "score_kind", "threshold", "prediction", "model_label", "duration_ms",
                "frames_analyzed", "segments_analyzed", "warnings", "error_code", "details"}


def recover_stale(owner=None) -> None:
    """Jobs whose worker died (server restart) are closed as failed; queued jobs this process does not know about are picked up
    again (a job is claimed atomically, so two processes can never run it twice)."""
    qs = DevTestJob.objects.all() if owner is None else DevTestJob.objects.filter(owner=owner)
    limit = timezone.now() - STALE_AFTER
    for job in qs.filter(status="running", heartbeat_at__lt=limit):
        if DevTestJob.objects.filter(pk=job.pk, status="running", heartbeat_at__lt=limit).update(
                status="failed", error="The job was interrupted (the server restarted or the worker stopped).", finished_at=timezone.now()):
            _cancel_remaining(str(job.pk))
    for job in qs.filter(status="queued", created_at__lt=timezone.now() - timedelta(seconds=60)):
        if not is_scheduled(job.pk):
            schedule(job.pk)


# ---- one item ------------------------------------------------------------------------------------------------------------------

def _path(cfg, job: DevTestJob, it: DevTestItem) -> Path:
    if it.owns_file:
        p = Path(it.stored_path)
        if not it.stored_path or not p.is_file():
            raise AppError("FILE_MISSING", "The uploaded test file is no longer available.", 410)
        return p
    from apps.devlab.datasets import resolve_file
    return resolve_file(cfg, job.dataset, it.stored_path)


def _infer(rt, det, sample, should_stop):
    deadline = time.monotonic() + GATE_WAIT_S
    while not rt.gate.enter(reserve=rt.settings.devlab_live_reserve):
        if should_stop():
            raise _Cancelled
        if time.monotonic() > deadline:
            raise AppError("SERVER_BUSY", "The models stayed busy with live sessions; try the job again later.", 503)
        time.sleep(0.25)
    try:
        return rt.pool.submit(det.analyze, sample, None).result(timeout=INFERENCE_TIMEOUT_S)
    finally:
        rt.gate.leave()


def _prediction(score, threshold) -> str:
    if score is None or threshold is None:
        return ""
    return "fake" if score >= threshold else "real"


def _from_result(res: dict, warnings: list[str]) -> dict:
    """Map a detector result to item fields. Only what the detector produced is copied."""
    status = {"ok": "done", "low_quality": "low_quality", "unavailable": "unavailable"}.get(res["status"], "error")
    out = {"status": status, "warnings": warnings, "error_code": res.get("error_code") or "", "details": dict(res.get("details") or {}),
           "score_kind": res.get("score_kind") or "", "threshold": res.get("threshold"), "model_id": res.get("model_id") or ""}
    out["details"].pop("raw_logits", None)
    if status == "done" and res.get("score") is not None:
        out.update(score=float(res["score"]), prediction=_prediction(float(res["score"]), res.get("threshold")), model_label=str(res.get("label") or "")[:60])
        if res.get("threshold") is None:
            out["warnings"] = warnings + ["NO_THRESHOLD_CONFIGURED"]
    elif status == "done":  # ran but produced no score (measurement-only detectors): not a prediction
        out.update(status="error", error_code="NO_SCORE")
    return out


def _aggregate(scores: list[float], how: str) -> float:
    if how == "mean":
        return sum(scores) / len(scores)
    if how == "top_quarter":  # the same "worst quarter" statistic the live policy reports for a family
        k = max(1, -(-len(scores) // 4))
        return sum(sorted(scores, reverse=True)[:k]) / k
    return float(statistics.median(scores))


def process_item(rt, job: DevTestJob, it: DevTestItem, should_stop) -> dict:
    cfg = rt.settings
    opts = job.options or {}
    name = DETECTOR_FOR[it.media_type]
    det = rt.registry.get(name)
    base = {"detector": name, "model_version": model_version(cfg, name)}
    if det is None:
        return {**base, "status": "unavailable", "error_code": "DETECTOR_DISABLED", "details": {"message": f"The '{name}' detector is switched off in the server settings."}}
    base.update(model_id=det.model_id or "", score_kind=det.score_kind, threshold=det.threshold)
    if not det.ensure_loaded():  # report the real reason (missing weights, incomplete weights, missing dependency) for every item
        return {**base, "status": "unavailable", "error_code": det._error or "UNAVAILABLE", "details": {"load_problem": getattr(det, "load_problem", None)}}
    path = _path(cfg, job, it)
    score_lq = bool(opts.get("score_low_quality"))
    if it.media_type == M.IMAGE:
        from apps.core.media import image_warnings
        img = M.image_from_bytes(path.read_bytes(), cfg.max_image_dimension)
        warnings = image_warnings(img)
        if warnings and not score_lq:
            return {**base, "status": "low_quality", "warnings": warnings, "error_code": warnings[0]}
        return {**base, **_from_result(_infer(rt, det, img, should_stop), warnings), "frames_analyzed": 1}
    if it.media_type == M.AUDIO:
        from apps.core.media import audio_warnings
        wave, sr = M.load_audio(path, it.file_format, cfg.devlab_max_audio_seconds)
        warnings = audio_warnings(wave, sr)
        if warnings and not score_lq:
            return {**base, "status": "low_quality", "warnings": warnings, "error_code": warnings[0]}
        out = {**base, **_from_result(_infer(rt, det, (wave, sr), should_stop), warnings)}
        out["segments_analyzed"] = (out.get("details") or {}).get("windows")
        out["details"] = {**out.get("details", {}), "sample_rate_in": sr, "duration_s": round(len(wave) / sr, 2) if sr else None}
        return out
    return _process_video(rt, det, base, path, opts, should_stop)


def _process_video(rt, det, base: dict, path: Path, opts: dict, should_stop) -> dict:
    from apps.core.media import image_warnings
    cfg = rt.settings
    how = opts.get("aggregation") if opts.get("aggregation") in AGGREGATIONS else "median"
    n = int(opts.get("video_frames") or cfg.devlab_video_frames)
    frames, info = M.sample_video_frames(path, n, cfg.devlab_max_video_seconds, cfg.max_image_dimension, should_stop)
    per_frame, scores, skipped, errors = [], [], 0, []
    threshold = det.threshold
    for f in frames:
        if should_stop():
            raise _Cancelled
        img = M.to_pil(f["rgb"])
        fw = image_warnings(img)
        row = {"index": f["index"], "time_s": f["time_s"]}
        if fw and not opts.get("score_low_quality"):
            skipped += 1
            per_frame.append({**row, "status": "low_quality", "warnings": fw})
            continue
        res = _infer(rt, det, img, should_stop)
        if res["status"] == "unavailable":  # the model cannot run at all: the whole video is unavailable, not "partly scored"
            return {**base, "status": "unavailable", "error_code": res.get("error_code") or "UNAVAILABLE", "details": {"video": info}}
        d = res.get("details") or {}
        row.update(status=res["status"], score=res.get("score"), label=res.get("label"), crop=d.get("crop"), crop_reason=d.get("reason"), inference_ms=res.get("inference_ms"))
        if res["status"] == "ok" and res.get("score") is not None:
            scores.append(float(res["score"]))
        elif res.get("error_code"):
            errors.append(res["error_code"])
        per_frame.append(row)
    warnings = []
    if skipped:
        warnings.append(f"LOW_QUALITY_FRAMES:{skipped}")
    no_face = sum(1 for r in per_frame if r.get("crop") == "none")
    if no_face:
        warnings.append(f"NO_FACE_CROP_FRAMES:{no_face}")
    if errors:
        warnings.append(f"FRAME_ERRORS:{len(errors)}")
    stats = {"aggregation": how, "frames_scored": len(scores), "frames_skipped_low_quality": skipped, "frame_errors": sorted(set(errors)),
             "video": info, "frames": per_frame}
    if not scores:
        status = "low_quality" if skipped and not errors else "error"
        return {**base, "status": status, "error_code": "NO_SCORABLE_FRAMES" if status == "low_quality" else (errors[0] if errors else "NO_SCORE"),
                "warnings": warnings, "frames_analyzed": 0, "details": stats}
    score = _aggregate(scores, how)
    stats.update(mean=round(sum(scores) / len(scores), 4), median=round(float(statistics.median(scores)), 4), min=round(min(scores), 4), max=round(max(scores), 4),
                 top_quarter_mean=round(_aggregate(scores, "top_quarter"), 4),
                 flagged_fraction=round(sum(1 for s in scores if threshold is not None and s >= threshold) / len(scores), 4) if threshold is not None else None)
    return {**base, "status": "done", "score": round(score, 6), "prediction": _prediction(score, threshold), "model_label": "",
            "warnings": warnings + ([] if threshold is not None else ["NO_THRESHOLD_CONFIGURED"]), "frames_analyzed": len(scores), "details": stats}
