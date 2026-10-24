import uuid

from django.db import models
from django.utils import timezone


class EvidenceEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey("verification.VerificationSession", on_delete=models.CASCADE, related_name="evidence_events")
    seq = models.IntegerField()
    event_type = models.CharField(max_length=40)
    timestamp = models.DateTimeField()
    payload = models.JSONField(default=dict)
    previous_hash = models.CharField(max_length=64)
    event_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "seq"], name="uniq_evidence_session_seq")]
