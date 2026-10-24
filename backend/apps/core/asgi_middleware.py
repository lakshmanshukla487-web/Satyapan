"""Reject oversized request bodies before Django reads them.

Django's ASGI handler spools request bodies larger than FILE_UPLOAD_MAX_MEMORY_SIZE to a temporary file. Rejecting
early (by Content-Length, or by counting streamed bytes) keeps the promise that uploaded media never touches disk.
"""
import json
import uuid

from apps.core.runtime import get_runtime


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cfg = get_runtime().settings
        limit = (cfg.max_upload_mb + 1) * 1024 * 1024  # +1 MB multipart overhead
        headers_dict = dict(scope.get("headers", []))
        length = headers_dict.get(b"content-length", b"")
        # Resolve the CORS origin to echo back: reflect the request's Origin if allowed, else the primary.
        request_origin = headers_dict.get(b"origin", b"").decode()
        allowed = get_runtime().allowed_origins
        cors_origin = request_origin if request_origin in allowed else cfg.frontend_origin
        if length.isdigit() and int(length) > limit:
            return await self._reject(send, cors_origin, cfg)
        received, started = 0, False

        async def limited_receive():
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > limit:
                    raise BodyTooLarge
            return msg

        async def tracking_send(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await self._reject(send, cors_origin, cfg)

    @staticmethod
    async def _reject(send, cors_origin, cfg):
        body = json.dumps({"error": {"code": "FILE_TOO_LARGE", "message": f"Request exceeds the {cfg.max_upload_mb} MB limit.", "request_id": str(uuid.uuid4())}}).encode()
        await send({"type": "http.response.start", "status": 413, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
            (b"access-control-allow-origin", cors_origin.encode()), (b"x-content-type-options", b"nosniff"), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})
