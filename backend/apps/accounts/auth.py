"""Bearer-token authentication and role permissions.

Tokens are signed (HMAC with SECRET_KEY) and expire; nothing is stored server-side. A token stops working when the
user is deactivated, changes their password, or signs out (token_epoch). Characters used are valid in HTTP headers and
WebSocket subprotocol names, which is how browsers send the token for WebSockets (they cannot set an Authorization header).
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import signing
from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from apps.core.runtime import get_runtime

SALT = "satyapan.auth.v1"
WS_SUBPROTOCOL = "satyapan.v1"


def _signer() -> signing.TimestampSigner:
    return signing.TimestampSigner(salt=SALT, sep=".")


def _fingerprint(user) -> str:
    return user.password[-12:]  # changes when the password changes, invalidating older tokens


def token_ttl() -> timedelta:
    return timedelta(minutes=get_runtime().settings.auth_token_ttl_minutes)


def issue_token(user) -> tuple[str, "timezone.datetime"]:
    token = _signer().sign_object({"uid": user.pk, "pw": _fingerprint(user), "ep": user.token_epoch}, compress=False)
    return token, timezone.now() + token_ttl()


def token_uid(token: str):
    """The account id inside a correctly signed, unexpired token, WITHOUT a database lookup (used by the rate limiter to give
    every signed-in account its own bucket). A forged token fails the signature check, so nobody can pick another account's
    bucket; revocation is still enforced by the authentication class on the actual request."""
    try:
        data = _signer().unsign_object(token, max_age=token_ttl())
        uid = data["uid"]
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None
    return uid if isinstance(uid, int) else None


def user_from_token(token: str):
    """Return the active user for a valid, unexpired, un-revoked token, else None."""
    try:
        data = _signer().unsign_object(token, max_age=token_ttl())
        user = get_user_model().objects.filter(pk=data["uid"], is_active=True).first()
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None
    if user is None or user.password[-12:] != data.get("pw") or user.token_epoch != data.get("ep", 0):
        return None
    return user


class BearerTokenAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Bearer realm="satyapan"'

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None  # anonymous: the permission class decides
        if len(parts) != 2:
            raise AuthenticationFailed("Invalid authorization header.")
        user = user_from_token(parts[1].decode("ascii", "ignore"))
        if user is None:
            raise AuthenticationFailed("Your session has expired or is invalid. Please sign in again.")
        return user, parts[1].decode()


class _HasRole(BasePermission):
    role = ""
    message = "You do not have access to this resource."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.role == self.role)


class IsOfficer(_HasRole):
    role = "officer"
    message = "This resource is only available to officers."


class IsCustomer(_HasRole):
    role = "customer"
    message = "This action is only available to customers."


class IsDeveloper(_HasRole):
    """Developer model test lab. Developer accounts are only created by an administrator (manage.py create_developer)."""
    role = "developer"
    message = "This resource is only available to developer accounts."


class BearerScheme(OpenApiAuthenticationExtension):  # documents the scheme in /docs
    target_class = "apps.accounts.auth.BearerTokenAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer"}
