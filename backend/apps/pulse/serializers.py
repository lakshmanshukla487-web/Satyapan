from rest_framework import serializers


class PulseTraceIn(serializers.Serializer):
    """Mean R, G, B (0-255) of a skin region for each video frame, measured in the browser."""
    fps = serializers.FloatField(min_value=5, max_value=60)
    rgb = serializers.ListField(child=serializers.ListField(child=serializers.FloatField(min_value=0, max_value=255), min_length=3, max_length=3),
                                min_length=60, max_length=2400)
