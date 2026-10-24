from rest_framework import serializers

from apps.accounts.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "role"]


class LoginIn(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class RegisterIn(serializers.Serializer):
    username = serializers.RegexField(r"^[A-Za-z0-9_.-]{3,30}$", error_messages={"invalid": "Username must be 3-30 letters, digits, dots, dashes or underscores."})
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class AuthOut(serializers.Serializer):  # documentation only
    token = serializers.CharField()
    expires_at = serializers.DateTimeField()
    user = UserSerializer()
