import logging
import re
import uuid

from django.http import JsonResponse

from apps.core.runtime import get_runtime

security_log = logging.getLogger("satyapan.security")

# Media uploads fire automatically during a live session (a frame every 3 s, a dense frame series every ~0.45 s while a head
# turn or blink is measured, audio every 6 s, lip-sync clips, eye-scan frames) and the developer lab uploads test files one by
# one. They are counted in a separate, larger per-account bucket so they can never starve ordinary API calls (and the other way
# round). Inference itself is protected separately by the bounded model queue (503 SERVER_BUSY).
_MEDIA_PATH = re.compile(r"/(analysis/(audio|frame|avsync)|challenges/[^/]+/(eye-scan|phrase)|devlab/jobs/[^/]+/items)$")
_BEARER = re.compile(r"^\s*bearer\s+(\S+)\s*$", re.I)


def _account(request):
    """The account id of a correctly signed, unexpired bearer token (no database access), else None."""
    m = _BEARER.match(request.META.get("HTTP_AUTHORIZATION", ""))
    if not m:
        return None
    from apps.accounts.auth import token_uid  # lazy: accounts imports DRF
    return token_uid(m.group(1))


class RequestIdRateLimitMiddleware:
    """Assigns a request id (X-Request-ID) and applies the request rate limits.

    Buckets (all per minute, see AppSettings):
    * signed in (valid token): ``user:<id>`` for API calls (RATE_LIMIT_USER_PER_MINUTE) and ``media:<id>`` for media uploads
      (RATE_LIMIT_MEDIA_PER_MINUTE). Customers behind one shared LAN / NAT address therefore no longer share one bucket.
    * not signed in (no or invalid token): ``anon:<address>`` (RATE_LIMIT_PER_MINUTE). Sign-in and sign-up keep their own,
      much stricter per-address / per-username throttles in apps/accounts/views.py.
    * every request also counts toward ``ip:<address>`` (RATE_LIMIT_IP_CEILING_PER_MINUTE): one address cannot flood the server
      with many accounts.

    A refused request gets 429 RATE_LIMITED with a Retry-After header, the same error envelope as every other error, and the
    request id. Nothing behind the middleware runs, so a throttled request can never create a session, challenge or document.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        refused = self._check(request)
        resp = refused if refused is not None else self.get_response(request)
        resp["X-Request-ID"] = request.request_id
        return resp

    def _check(self, request):
        from apps.core.audit import client_ip  # lazy: audit imports models
        rt = get_runtime()
        cfg = rt.settings
        ip = client_ip(request)
        uid = _account(request)
        if uid is not None:
            media = bool(_MEDIA_PATH.search(request.path))
            scope, key, limit = ("media", f"media:{uid}", cfg.rate_limit_media_per_minute) if media else ("user", f"user:{uid}", cfg.rate_limit_user_per_minute)
        else:
            scope, key, limit = "anonymous", f"anon:{ip}", cfg.rate_limit_per_minute
        ok, retry = rt.limiter.hit(key, limit)
        if ok:
            ok, retry = rt.limiter.hit(f"ip:{ip}", cfg.rate_limit_ip_ceiling_per_minute)
            scope = scope if ok else "address"
        if ok:
            return None
        security_log.warning("rate limited scope=%s path=%s request_id=%s", scope, request.path, request.request_id)
        resp = JsonResponse({"error": {"code": "RATE_LIMITED", "message": f"Too many requests. Please wait {retry} s and try again.",
                                       "request_id": request.request_id, "retry_after": retry, "scope": scope}}, status=429)
        resp["Retry-After"] = str(retry)
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
