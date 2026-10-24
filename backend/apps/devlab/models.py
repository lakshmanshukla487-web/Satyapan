"""Developer model test lab: offline test jobs and their results.

Completely separate from customer verification: no foreign key to a verification session, no detector signal, no evidence
event, no audit of a customer, no WebSocket publication. Rows are owned by the developer who created them and are deleted
after DEVLAB_RETENTION_HOURS (manage.py devlab_cleanup, also run automatically)."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class DevTestJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devlab_jobs")
    name = models.CharField(max_length=120, blank=True, default="")
    source = models.CharField(max_length=10, default="upload")  # upload | dataset
    dataset = models.CharField(max_length=80, blank=True, default="")
    # draft (accepting uploads) | queued | running | completed | cancelled | failed
    status = models.CharField(max_length=12, default="draft", db_index=True)
    options = models.JSONField(default=dict, blank=True)  # {aggregation, video_frames, score_low_quality}
    total_items = models.PositiveIntegerField(default=0)
    total_bytes = models.BigIntegerField(default=0)
    cancel_requested = models.BooleanField(default=False)
    error = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)  # the worker's last sign of life (a stale one = interrupted)


class DevTestItem(models.Model):
    """One test file and the result of running its media type's detector on it. Only fields the real detector produced are
    filled in: score, prediction and model label stay empty when the model was unavailable or failed."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(DevTestJob, on_delete=models.CASCADE, related_name="items")
    index = models.PositiveIntegerField(default=0)
    filename = models.CharField(max_length=255)
    media_type = models.CharField(max_length=8)                        # image | video | audio
    file_format = models.CharField(max_length=10, blank=True, default="")  # jpeg png wav flac ogg mp3 m4a mp4 mov webm avi
    size_bytes = models.BigIntegerField(default=0)
    label = models.CharField(max_length=8, blank=True, default="")       # ground truth: real | fake | "" (unlabelled)
    stored_path = models.CharField(max_length=500, blank=True, default="")  # temporary upload, or a path inside the dataset folder
    owns_file = models.BooleanField(default=True)                        # True: a temporary upload, deleted after use
    # queued | running | done | low_quality | unavailable | error | cancelled
    status = models.CharField(max_length=12, default="queued", db_index=True)
    detector = models.CharField(max_length=40, blank=True, default="")
    model_id = models.CharField(max_length=200, blank=True, default="")
    model_version = models.CharField(max_length=80, blank=True, default="")
    score = models.FloatField(null=True, blank=True)
    score_kind = models.CharField(max_length=40, blank=True, default="")
    threshold = models.FloatField(null=True, blank=True)
    prediction = models.CharField(max_length=8, blank=True, default="")  # fake | real (score compared with the detector threshold)
    model_label = models.CharField(max_length=60, blank=True, default="")  # the model's own top label
    duration_ms = models.FloatField(null=True, blank=True)
    frames_analyzed = models.PositiveIntegerField(null=True, blank=True)
    segments_analyzed = models.PositiveIntegerField(null=True, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    error_code = models.CharField(max_length=60, blank=True, default="")
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["index"]
        indexes = [models.Index(fields=["job", "index"], name="devlab_item_job_idx")]
