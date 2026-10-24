import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class VerificationSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The customer who ran the session. SET_NULL: deleting an account must not delete the audit trail.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="verification_sessions")
    # awaiting_consent | ready | running | completed | cancelled | failed | terminated
    status = models.CharField(max_length=20, default="awaiting_consent", db_index=True)
    consent_given = models.BooleanField(default=False)
    consent_timestamp = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    final_risk_level = models.CharField(max_length=5, null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    policy_version = models.CharField(max_length=32, default="demo-v2")
    # Officer summary report, frozen when the session completes (see apps/reports/services.py).
    report = models.JSONField(null=True, blank=True)
    # Officer override: set when an officer ends the session.
    terminated_at = models.DateTimeField(null=True, blank=True)
    terminated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    termination_reason = models.CharField(max_length=200, blank=True, default="")
    # Officer approval of the REQUEST to verify: not_required | pending | approved | rejected | expired.
    # Until it is "approved" (or not_required) the customer cannot give consent, upload anything or start.
    approval_status = models.CharField(max_length=12, default="not_required", db_index=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.CharField(max_length=200, blank=True, default="")  # officer's private note; never shown to the customer
    # Per-session switch the officer can flip: challenges keep coming for the whole session; when True they are released
    # automatically instead of waiting for the officer's click each time.
    challenge_auto_approve = models.BooleanField(default=False)
