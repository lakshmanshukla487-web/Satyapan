from rest_framework import serializers

from apps.signals.models import DetectorSignal


class SignalSerializer(serializers.ModelSerializer):
    session_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = DetectorSignal
        fields = ["id", "session_id", "detector_name", "signal_type", "status", "score", "confidence", "threshold", "details", "error_code", "created_at"]


class UploadReceivedOut(serializers.Serializer):  # documentation only
    received = serializers.BooleanField()
    detectors = serializers.ListField(child=serializers.DictField())
