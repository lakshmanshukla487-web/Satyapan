"""Security hardening (OWASP Top 10). Imported after base.py by satyapan/settings/__init__.py.

Always on: nosniff, same-origin referrer policy, frame denial, strict body limits, Argon2 password hashing.
Only when APP_ENV is not "development": HTTPS redirect + HSTS, secure/HttpOnly/SameSite cookies, https-only origins,
a long random SECRET_KEY and explicit ALLOWED_HOSTS. The app itself sets no cookies and authenticates with bearer
tokens, so the cookie/CSRF settings are defence in depth for the day an admin or cookie session is added.
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .base import ALLOWED_HOSTS, CORS_ALLOWED_ORIGINS, IS_DEV, SECRET_KEY


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw in (None, "") else raw.strip().lower() in ("1", "true", "yes", "on")


# A02: Argon2 first (needs argon2-cffi, listed in requirements.txt); PBKDF2 stays so older hashes still verify.
try:
    import argon2  # noqa: F401
    _FIRST_HASHER = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
except ImportError:
    # A missing argon2-cffi used to make every sign-up and sign-in fail with HTTP 500 ("Couldn't load Argon2PasswordHasher").
    # Fall back to Django's default PBKDF2 (still strong) and say so.
    import logging as _logging
    _logging.getLogger("satyapan.security").warning("argon2-cffi is not installed: using PBKDF2 for passwords. pip install argon2-cffi")
    _FIRST_HASHER = []
PASSWORD_HASHERS = _FIRST_HASHER + [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

# A05: headers Django itself can set
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# A04/A05: bound request bodies (file uploads are bounded separately by BodyLimitMiddleware and MAX_UPLOAD_MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024  # JSON bodies (the pulse trace is the largest, about 100 KB)
DATA_UPLOAD_MAX_NUMBER_FIELDS = 200

# Cookie flags: inert today (no cookies are set) but correct if one is ever added.
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"

if not IS_DEV:
    if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("dev-only"):
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a random string of at least 50 characters.")
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured("Set ALLOWED_HOSTS to the exact host names (no '*').")
    insecure = [o for o in CORS_ALLOWED_ORIGINS if not o.startswith("https://")]
    if insecure:
        raise ImproperlyConfigured(f"FRONTEND_ORIGIN / EXTRA_ORIGINS must be https:// outside development: {insecure}")
    SECURE_SSL_REDIRECT = _flag("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = _flag("SECURE_HSTS_PRELOAD", False)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = list(CORS_ALLOWED_ORIGINS)
    if _flag("BEHIND_TLS_PROXY", False):  # only when a trusted reverse proxy terminates TLS and sets this header
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
