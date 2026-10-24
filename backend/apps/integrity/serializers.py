from rest_framework import serializers


class _Dev(serializers.Serializer):
    label = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")


class IntegrityProbeIn(serializers.Serializer):
    camera_label = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")
    width = serializers.IntegerField(min_value=0, max_value=8192, required=False, default=0)
    height = serializers.IntegerField(min_value=0, max_value=8192, required=False, default=0)
    frame_rate = serializers.FloatField(min_value=0, max_value=240, required=False, allow_null=True, default=None)
    intervals_ms = serializers.ListField(child=serializers.FloatField(min_value=0, max_value=5000), max_length=400, required=False, default=list)
    webdriver = serializers.BooleanField(required=False, default=False)
    # added with the IP / camera hardening
    capabilities = serializers.ListField(child=serializers.CharField(max_length=40), max_length=60, required=False, default=list)
    video_devices = serializers.ListField(child=_Dev(), max_length=12, required=False, default=list)
    native_get_user_media = serializers.BooleanField(required=False, allow_null=True, default=None)
    native_enumerate_devices = serializers.BooleanField(required=False, allow_null=True, default=None)
    device_id_present = serializers.BooleanField(required=False, allow_null=True, default=None)
    webrtc_ips = serializers.ListField(child=serializers.CharField(max_length=64), max_length=10, required=False, default=list)
    timezone = serializers.CharField(max_length=64, allow_blank=True, required=False, default="")
    tz_offset_min = serializers.IntegerField(min_value=-900, max_value=900, required=False, allow_null=True, default=None)
