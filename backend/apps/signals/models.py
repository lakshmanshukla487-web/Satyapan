import uuid

from django.db import models
from django.utils import timezone


class DetectorSignal(models.Model):
    """One output of one evidence-family detector for one sample (frame, clip, probe, document...)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey("verification.VerificationSession", on_delete=models.CASCADE, related_name="signals")
    detector_name = models.CharField(max_length=40)
    signal_type = models.CharField(max_length=30)  # audio_spoof | visual_deepfake | landmarks | av_sync | pipeline_integrity | pulse | provenance
    status = models.CharField(max_length=14)  # ok | low_quality | unavailable | error
    score = models.FloatField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    threshold = models.FloatField(null=True, blank=True)
    details = models.JSONField(default=dict)
    error_code = models.CharField(max_length=40, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
