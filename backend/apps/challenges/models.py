import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Challenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey("verification.VerificationSession", on_delete=models.CASCADE, related_name="challenges")
    challenge_type = models.CharField(max_length=20)
    challenge_text = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)  # when the browser asked for it (issued_at restarts when an officer releases it)
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    # awaiting_approval (hidden from the customer) | issued | answered | expired
    status = models.CharField(max_length=20, default="issued")
    result = models.CharField(max_length=12, null=True, blank=True)  # passed | failed | unavailable
    confidence = models.FloatField(null=True, blank=True)
    measured = models.JSONField(default=dict, blank=True)  # client-reported measurement (unverified)
    reason = models.CharField(max_length=300, null=True, blank=True)  # plain-language explanation of the result
    # Officer approval workflow
    approval_status = models.CharField(max_length=14, default="not_required")  # not_required | pending | approved | regenerated
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    # How strongly the result is backed up. server_confirmed: the server's own measurement on uploaded frames agrees |
    # weak: server measurement only partly agrees | client_only: only the browser's report exists | mismatch: the browser
    # reported something the server's frames contradict (treated as a tampering indicator) | server_only: decided by the
    # server alone (iris scan).
    verification = models.CharField(max_length=16, default="client_only")
    answered_at = models.DateTimeField(null=True, blank=True)
    sequence = models.PositiveIntegerField(default=0)  # 1, 2, 3 ... within the session (challenges continue until it ends)
