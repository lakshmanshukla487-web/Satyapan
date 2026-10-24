from rest_framework import serializers

from apps.decision_engine.serializers import ReasonSerializer


class ReportSerializer(serializers.Serializer):  # documentation only (output is built by services.build_report)
    report_version = serializers.CharField()
    generated_at = serializers.DateTimeField()
    session = serializers.DictField()
    outcome = serializers.DictField()
    reasons = ReasonSerializer(many=True)
    next_steps = serializers.ListField(child=serializers.CharField())
    documents = serializers.DictField()
    challenges = serializers.ListField(child=serializers.DictField())
    challenge_summary = serializers.DictField()
    families = serializers.ListField(child=serializers.DictField(), required=False)
    session_analysis = serializers.DictField(required=False)
    identity = serializers.DictField(required=False)
    network = serializers.DictField(required=False)
    plain_language = serializers.DictField(required=False)
    detectors = serializers.ListField(child=serializers.DictField())
    timeline = serializers.ListField(child=serializers.DictField())
    evidence_integrity = serializers.DictField()
    limitations = serializers.ListField(child=serializers.CharField())
    snapshot = serializers.ChoiceField(choices=["stored_at_completion", "generated_now"])
    integrity = serializers.DictField()
