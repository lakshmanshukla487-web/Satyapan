from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.auth import issue_token
from apps.accounts.serializers import AuthOut, LoginIn, RegisterIn, UserSerializer
from apps.core.audit import audit, client_ip, security_log
from apps.core.errors import AppError
from apps.core.runtime import get_runtime

WINDOW_S = 300


def _auth_response(user, status=200):
    token, expires = issue_token(user)
    return Response({"token": token, "expires_at": expires, "user": UserSerializer(user).data}, status=status)


@extend_schema(tags=["auth"], request=LoginIn, responses=AuthOut, auth=[])
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def login(request):
    body = LoginIn(data=request.data)
    body.is_valid(raise_exception=True)
    username = body.validated_data["username"].strip().lower()
    rt = get_runtime()
    if not rt.limiter.allow(f"login:{client_ip(request)}:{username}", rt.settings.login_max_attempts, WINDOW_S):
        security_log.warning("login throttled ip=%s", client_ip(request))
        raise AppError("RATE_LIMITED", "Too many sign-in attempts. Try again in a few minutes.", 429)
    user = authenticate(request, username=username, password=body.validated_data["password"])
    if user is None:  # same message whether the username or the password was wrong
        security_log.warning("login failed ip=%s", client_ip(request))
        raise AppError("INVALID_CREDENTIALS", "Invalid username or password.", 401)
    audit(request, "auth.login", actor=user)
    return _auth_response(user)


@extend_schema(tags=["auth"], request=RegisterIn, responses={201: AuthOut}, auth=[])
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    """Self-service sign-up. Always creates a customer; officer accounts are created by an administrator."""
    rt = get_runtime()
    if not rt.settings.allow_registration:
        raise AppError("REGISTRATION_DISABLED", "Self-registration is disabled. Contact an administrator.", 403)
    if not rt.limiter.allow(f"register:{client_ip(request)}", rt.settings.login_max_attempts, WINDOW_S):
        raise AppError("RATE_LIMITED", "Too many attempts. Try again in a few minutes.", 429)
    body = RegisterIn(data=request.data)
    body.is_valid(raise_exception=True)
    username, password = body.validated_data["username"].lower(), body.validated_data["password"]
    User = get_user_model()
    taken = AppError("USERNAME_TAKEN", "That username is already taken.", 409)
    if User.objects.filter(username__iexact=username).exists():
        raise taken
    candidate = User(username=username, role="customer")
    try:
        validate_password(password, candidate)
    except DjangoValidationError as e:
        raise AppError("WEAK_PASSWORD", " ".join(e.messages), 422)
    try:
        with transaction.atomic():
            user = User.objects.create_user(username=username, password=password, role="customer")
    except IntegrityError:  # two sign-ups with the same name at the same moment
        raise taken
    audit(request, "auth.register", actor=user)
    return _auth_response(user, status=201)


@extend_schema(tags=["auth"], responses=UserSerializer)
@api_view(["GET"])
def me(request):
    return Response(UserSerializer(request.user).data)


@extend_schema(tags=["auth"], request=None, responses={200: dict})
@api_view(["POST"])
def logout(request):
    """Server-side sign-out: bumps token_epoch, so this token AND every other token of the user stops working."""
    user = request.user
    get_user_model().objects.filter(pk=user.pk).update(token_epoch=F("token_epoch") + 1)
    audit(request, "auth.logout")
    return Response({"signed_out": True})
