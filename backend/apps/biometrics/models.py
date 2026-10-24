import uuid

from django.db import models
from django.utils import timezone


class ReferencePhoto(models.Model):
    """What was learned from the close-up photo the customer uploads at the start. The photo itself is processed in memory and
    NEVER stored; only a face embedding (128 numbers) and an iris template (bit pattern) are kept, and only for this session."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField("verification.VerificationSession", on_delete=models.CASCADE, related_name="reference_photo")
    face_embedding = models.JSONField(default=list)   # [] when the face models are not installed
    iris = models.JSONField(default=dict)              # {"right": packed template, "left": packed template}
    quality = models.JSONField(default=dict)           # issues the customer can fix by retaking the photo
    file_sha256 = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)


class Observation(models.Model):
    """One server-side measurement at one moment, kept as a time series for the session analysis (kind: pose, face_match,
    iris_match, doc_face, doc_face_match, av_sync, frame)."""
    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey("verification.VerificationSession", on_delete=models.CASCADE, related_name="observations")
    kind = models.CharField(max_length=20)
    challenge_id = models.UUIDField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    value = models.FloatField(null=True, blank=True)
    quality = models.FloatField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["session", "kind", "created_at"])]
        ordering = ["created_at", "id"]
