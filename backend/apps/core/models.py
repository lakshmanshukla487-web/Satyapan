import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    """Who did what, when, from where. Written for sign-ins, sign-outs, officer actions and officer reads of sensitive
    data (documents, report, evidence). Never contains media, passwords, tokens or full ID numbers."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor_role = models.CharField(max_length=10, blank=True, default="")
    action = models.CharField(max_length=60, db_index=True)
    session_id = models.UUIDField(null=True, blank=True, db_index=True)
    ip = models.CharField(max_length=64, blank=True, default="")
    request_id = models.CharField(max_length=40, blank=True, default="")
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
