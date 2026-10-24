import uuid

from django.conf import settings
from django.http import JsonResponse

from apps.core.runtime import get_runtime

# Media upload paths are excluded from the general rate limit because they fire automatically and frequently during
# an active session (frame every 3 s, audio every 6 s). They still consume quota from a separate, higher-capacity bucket.
_MEDIA_SUFFIXES = ("/analysis/audio", "/analysis/frame", "/analysis/avsync", "/eye-scan", "/rtc/config")


class RequestIdRateLimitMiddleware:
    """Assigns a request id (X-Request-ID) and applies the in-memory per-IP rate limit.

    Two buckets are maintained per IP:
    - *general*  - all endpoints except media uploads, capped at ``rate_limit_per_minute``.
    - *media*    - frame and audio upload endpoints, capped at 10x the general limit.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        rt = get_runtime()
        limit = rt.settings.rate_limit_per_minute
        is_media = any(request.path.endswith(sfx) for sfx in _MEDIA_SUFFIXES)
        bucket_key = ("media:" if is_media else "api:") + (request.META.get("REMOTE_ADDR") or "unknown")
        effective_limit = limit * 10 if is_media else limit
        if not rt.limiter.allow(bucket_key, effective_limit):
            resp = JsonResponse({"error": {"code": "RATE_LIMITED", "message": "Too many requests. Try again shortly.", "request_id": request.request_id}}, status=429)
        else:
            resp = self.get_response(request)
        resp["X-Request-ID"] = request.request_id
        return resp


# A05: this is a JSON API, so the CSP can be as strict as it gets. The Swagger page (development / opt-in only)
# needs scripts and styles from a CDN, so /docs gets no CSP.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


class SecurityHeadersMiddleware:
    """Adds hardening headers to every response, including errors and 429s."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resp = self.get_response(request)
        if request.path != "/docs":
            resp.setdefault("Content-Security-Policy", _API_CSP)
        resp.setdefault("X-Content-Type-Options", "nosniff")
        resp.setdefault("X-Frame-Options", "DENY")
        resp.setdefault("Referrer-Policy", "same-origin")
        resp.setdefault("Cross-Origin-Resource-Policy", "same-site")
        resp.setdefault("Permissions-Policy", "camera=(self), microphone=(self), geolocation=(), payment=(), usb=()")
        if request.path != "/docs":
            resp.setdefault("Cache-Control", "no-store")  # A02: tokens, documents' summaries and risk data must not be cached
            resp.setdefault("Pragma", "no-cache")
        return resp
