"""Django settings for Satyapan: API + WebSockets only (no templates to render, no admin, no cookie sessions)."""
import os
import tempfile

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from satyapan.conf import BASE_DIR, AppSettings

load_dotenv(BASE_DIR / ".env")  # real environment variables take priority over .env
SATYAPAN = AppSettings.from_env()
os.environ.setdefault("HF_HOME", SATYAPAN.hf_home)

IS_DEV = SATYAPAN.app_env == "development"
DEBUG = IS_DEV
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or ("dev-only-insecure-key" if DEBUG else "")
if not SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when APP_ENV is not 'development'.")
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()]
# Interactive API docs expose every route: on in development, opt-in elsewhere.
EXPOSE_API_DOCS = IS_DEV or os.environ.get("EXPOSE_API_DOCS", "").strip().lower() in ("1", "true", "yes")

INSTALLED_APPS = [
    "daphne",  # ASGI server; also makes `manage.py runserver` ASGI-capable (WebSockets)
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "channels",
    # --- shared / platform ---
    "apps.core",            # errors, runtime, middleware, uploads, audit log, health
    "apps.accounts",        # users, bearer tokens, roles
    "apps.verification",    # the verification session and its lifecycle (+ officer terminate override)
    "apps.realtime",        # WebSocket consumers and event publishing
    "apps.signals",         # DetectorSignal storage, detector base classes, registry
    "apps.decision_engine", # deterministic policy: signals -> GREEN / AMBER / RED / GREY + reasons
    "apps.evidence",        # hash-chained evidence log, export and verification
    "apps.reports",         # officer summary report
    "apps.documents",       # KYC documents: upload, validation, cross-document verification
    # --- the evidence families ---
    "apps.integrity",       # 1. pipeline integrity (virtual-camera / frame-timing probe)
    "apps.challenges",      # 2. challenge-response (+ officer approval workflow)
    "apps.avsync",          # 3. audio-visual consistency
    "apps.voice",           # 4. voice anti-spoof
    "apps.pulse",           # 5. pulse (rPPG)
    "apps.provenance",      # 6. provenance (C2PA marker + editing/generator metadata)
    "apps.visual",          # frame-level visual deepfake classifiers + face landmarks (from the original MVP)
    "apps.biometrics",      # 7/8. identity: reference photo, face match, iris scan, face on documents
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # outermost, so 429 responses also carry CORS headers
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",  # CSP, no-store, Permissions-Policy... on every response
    "apps.core.middleware.RequestIdRateLimitMiddleware",
    "django.middleware.common.CommonMiddleware",
]

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

ROOT_URLCONF = "satyapan.urls"
ASGI_APPLICATION = "satyapan.asgi.application"
APPEND_SLASH = False  # URLs are exactly as the frontend calls them (no trailing slash)
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True, "OPTIONS": {"context_processors": []}}]

_db = dj_database_url.parse(SATYAPAN.database_url)
if _db["ENGINE"].endswith("sqlite3"):
    _db["OPTIONS"] = {"timeout": 20, "transaction_mode": "IMMEDIATE"}  # concurrent uploads write at the same time
    # Tests use a real file (not :memory:) so concurrent writers behave as in production.
    _db["TEST"] = {"NAME": os.path.join(tempfile.gettempdir(), "satyapan_test.sqlite3")}
DATABASES = {"default": _db}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

# CORS: primary frontend origin + any extra origins listed in EXTRA_ORIGINS (comma-separated).
# Also enforced for WebSockets in apps/realtime/consumers.py.
_extra_origins = [o.strip() for o in os.environ.get("EXTRA_ORIGINS", "").split(",") if o.strip()]
CORS_ALLOWED_ORIGINS = list({SATYAPAN.frontend_origin, *_extra_origins})
SATYAPAN_ALLOWED_ORIGINS: frozenset[str] = frozenset(CORS_ALLOWED_ORIGINS)
CORS_ALLOW_METHODS = ["GET", "POST", "OPTIONS"]
CORS_ALLOW_HEADERS = ["authorization", "content-type"]  # an explicit list, not the permissive default
CORS_EXPOSE_HEADERS = ["X-Request-ID"]
CORS_ALLOW_CREDENTIALS = False  # bearer tokens only; no cookies cross origins
CORS_PREFLIGHT_MAX_AGE = 600

# Uploads are decoded in memory and never written to disk: only the in-memory handler is enabled, and the
# threshold is above the upload limit so that over-limit files reach our own FILE_TOO_LARGE check.
# (Bodies far over the limit are rejected earlier still, by BodyLimitMiddleware in asgi.py.)
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.MemoryFileUploadHandler"]
FILE_UPLOAD_MAX_MEMORY_SIZE = (SATYAPAN.max_upload_mb + 1) * 1024 * 1024

# Redis is optional. Without REDIS_URL everything runs in one process (in-memory cache, channel layer and rate limiter).
# With REDIS_URL (and `pip install redis channels-redis`) the cache, rate limiter, inference back-pressure and the
# WebSocket channel layer are shared by every server process. If Redis is down the cache helpers degrade to "no cache"
# (apps/core/cache.py) instead of failing requests.
if SATYAPAN.redis_url:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [SATYAPAN.redis_url], "capacity": 1500, "expiry": 10}}}
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": SATYAPAN.redis_url,
                          "KEY_PREFIX": "satyapan", "TIMEOUT": 300, "OPTIONS": {"socket_connect_timeout": 1, "socket_timeout": 1}}}
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "satyapan", "TIMEOUT": 300}}

REST_FRAMEWORK = {
    # Every endpoint needs a bearer token unless it opts out; roles are enforced per view (see apps/accounts/auth.py).
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.auth.BearerTokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Satyapan API",
    "DESCRIPTION": "Decision-support for video KYC. Never makes a final KYC decision.",
    "VERSION": "0.3.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"satyapan.security": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
