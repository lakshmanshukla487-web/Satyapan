from rest_framework import serializers

from apps.signals.serializers import SignalSerializer


class ReasonSerializer(serializers.Serializer):  # documentation only
    code = serializers.CharField()
    severity = serializers.ChoiceField(choices=["indicator", "missing", "note", "ok"])
    category = serializers.CharField()
    title = serializers.CharField()
    detail = serializers.CharField()
    evidence = serializers.DictField()


class DecisionSerializer(serializers.Serializer):  # documentation only (output is built by the engine)
    risk_level = serializers.CharField()
    summary = serializers.CharField()
    headline = serializers.CharField()
    rule = serializers.CharField()
    rule_text = serializers.CharField()
    reasons = serializers.ListField(child=serializers.CharField())
    reason_details = ReasonSerializer(many=True)
    indicators = serializers.ListField(child=serializers.CharField())
    signal_summary = serializers.ListField(child=serializers.DictField())
    challenge_summary = serializers.DictField()
    next_steps = serializers.ListField(child=serializers.CharField())
    supporting_signals = serializers.ListField(child=serializers.DictField())
    unavailable_detectors = serializers.ListField(child=serializers.CharField())
    evidence_completeness = serializers.CharField()
    policy_version = serializers.CharField()
    human_review_required = serializers.BooleanField()
    # v3 additions (absent under the v2 policy)
    families = serializers.ListField(child=serializers.DictField(), required=False)
    coverage = serializers.DictField(allow_null=True, required=False)
    points = serializers.FloatField(required=False)
    positives = serializers.ListField(child=serializers.CharField(), required=False)
    missing_for_green = serializers.ListField(child=serializers.CharField(), required=False)
    overall_explain = serializers.CharField(required=False)


class AnalysisSerializer(serializers.Serializer):  # documentation only
    signals = SignalSerializer(many=True)
    recommendation = DecisionSerializer()
