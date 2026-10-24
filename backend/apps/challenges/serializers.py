import math

from rest_framework import serializers

from apps.challenges.models import Challenge
from apps.challenges.services import KINDS


class ChallengeSerializer(serializers.ModelSerializer):
    """Full view (officers, and customers once a challenge has been released)."""
    session_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Challenge
        fields = ["id", "session_id", "challenge_type", "challenge_text", "issued_at", "expires_at", "status", "result", "confidence",
                  "approval_status", "approved_at", "sequence", "verification", "answered_at", "reason"]


class CustomerChallengeSerializer(ChallengeSerializer):
    """What the customer may see. While a challenge waits for an officer it is completely hidden: no type, no text."""

    HIDDEN = ("result", "confidence", "verification", "reason", "approval_status", "approved_at")  # what a cheater could use to tune an attack

    def to_representation(self, instance):
        if instance.status == "awaiting_approval":
            return {"id": str(instance.id), "session_id": str(instance.session_id), "status": instance.status, "issued_at": instance.issued_at, "expires_at": instance.expires_at}
        data = super().to_representation(instance)
        for k in self.HIDDEN:
            data.pop(k, None)
        return data


class ChallengeResultIn(serializers.Serializer):
    """Client-reported measurements. head_yaw_deg: positive = toward the user's right."""
    measured = serializers.DictField(required=False, default=dict)

    def validate_measured(self, value):
        if len(value) > 20:
            raise serializers.ValidationError("Too many fields.")
        for k, v in value.items():
            if len(str(k)) > 40:
                raise serializers.ValidationError("Field names must be at most 40 characters.")
            if isinstance(v, bool) or not (v is None or isinstance(v, (int, float, str))):
                raise serializers.ValidationError("Values must be numbers, strings or null.")
            if isinstance(v, float) and not math.isfinite(v):
                raise serializers.ValidationError("Numbers must be finite.")
            if isinstance(v, str) and len(v) > 500:
                raise serializers.ValidationError("Text values must be at most 500 characters.")
        return value


class ChallengeChoiceIn(serializers.Serializer):
    """Officer-chosen challenge type (optional: omitted means random)."""
    type = serializers.ChoiceField(choices=list(KINDS), required=False)
