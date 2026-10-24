"""Request/response schemas. Timestamps are ISO 8601 UTC."""
from rest_framework import serializers

from apps.verification.models import VerificationSession


class SessionSerializer(serializers.ModelSerializer):
    """Officer view of a session (includes the risk outcome)."""
    customer = serializers.CharField(source="owner.username", read_only=True, default=None)

    class Meta:
        model = VerificationSession
        fields = ["id", "customer", "status", "consent_given", "consent_timestamp", "started_at", "completed_at", "created_at", "updated_at",
                  "final_risk_level", "summary", "policy_version", "terminated_at", "termination_reason",
                  "approval_status", "approved_at", "approval_note", "challenge_auto_approve"]


class CustomerSessionSerializer(serializers.ModelSerializer):
    """Customer view: never exposes the risk outcome, so a fraudster cannot tune an attack against it."""
    class Meta:
        model = VerificationSession
        fields = ["id", "status", "consent_given", "consent_timestamp", "started_at", "completed_at", "created_at", "updated_at", "policy_version", "approval_status"]


class SessionPageSerializer(serializers.Serializer):  # documentation only
    items = SessionSerializer(many=True)
    total = serializers.IntegerField()
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()


class ConsentIn(serializers.Serializer):
    granted = serializers.BooleanField()


class TerminateIn(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ApproveIn(serializers.Serializer):
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class AutoApproveIn(serializers.Serializer):
    enabled = serializers.BooleanField()
