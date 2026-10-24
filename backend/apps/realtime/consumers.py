import json
import time
import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from apps.accounts.auth import WS_SUBPROTOCOL, user_from_token
from apps.core.runtime import get_runtime
from apps.realtime.events import OFFICERS_GROUP, customer_group, envelope, group_name
from apps.realtime.relay import MAX_FRAME, Bucket, clean_message
from apps.verification.models import VerificationSession


class _AuthedConsumer(AsyncJsonWebsocketConsumer):
    """Shared connection checks. Browsers cannot set headers on WebSockets, so the token travels as a subprotocol:
    new WebSocket(url, ["satyapan.v1", token]). It never appears in the URL or in access logs.

    Close codes: 4401 not signed in, 4403 wrong origin or wrong role, 4404 unknown session."""
    group: str | None = None
    role: str = "officer"

    async def _authenticate(self):
        origin = next((v.decode() for k, v in self.scope["headers"] if k == b"origin"), None)
        # A browser always sends Origin. Outside development a missing Origin is refused too (A05/A01).
        if (origin is not None and origin not in get_runtime().allowed_origins) or (origin is None and not settings.DEBUG):
            await self.close(code=4403)
            return None
        token = next((p for p in self.scope.get("subprotocols", []) if p != WS_SUBPROTOCOL), None)
        user = await database_sync_to_async(user_from_token)(token) if token else None
        if user is None:
            await self.close(code=4401)
            return None
        if user.role != self.role:
            await self.close(code=4403)
            return None
        return user

    async def disconnect(self, code):
        if self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)

    # --- live call + chat relay (officer <-> customer of ONE session) ---
    relay_target: str | None = None  # "customer" or "session": the group the cleaned message is forwarded to
    sender_role: str = ""
    session_id: str | None = None
    _bucket: Bucket | None = None
    _running_checked: float = 0.0
    _running: bool = False

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        """Only call / chat messages are accepted, and only while the session is running. Anything else is ignored."""
        if not self.relay_target or not self.session_id or not text_data or len(text_data) > MAX_FRAME or not get_runtime().settings.enable_live_call:
            return
        if self._bucket is None:
            self._bucket = Bucket()
        if not self._bucket.take():
            return
        try:
            cleaned = clean_message(json.loads(text_data))
        except ValueError:
            return
        if cleaned is None:
            return
        ev, data = cleaned
        now = time.monotonic()
        if now - self._running_checked > 3.0:  # a ~3 s cache keeps ICE bursts off the database
            self._running = await self._is_running()
            self._running_checked = now
        if not self._running:
            await self.send_json(envelope("error", self.session_id, {"code": "SESSION_NOT_RUNNING", "message": "Live call and chat are only available while the session is running."}))
            return
        data = {**data, "from": self.sender_role}
        msg = envelope(ev, self.session_id, data)
        if self.relay_target == "customer":
            await self.channel_layer.group_send(customer_group(self.session_id), {"type": "customer.event", "message": msg})
        else:
            await self.channel_layer.group_send(group_name(self.session_id), {"type": "session.event", "message": msg})

    @database_sync_to_async
    def _is_running(self) -> bool:
        return VerificationSession.objects.filter(pk=self.session_id, status="running").exists()


class SessionConsumer(_AuthedConsumer):
    """ws://host/ws/sessions/<id>. Officers only (events carry risk signals). A socket only receives events for its own session."""
    role = "officer"

    async def connect(self):
        raw_id = self.scope["url_route"]["kwargs"]["session_id"]
        if await self._authenticate() is None:
            return
        snap = await self._snapshot(raw_id)
        if snap is None:  # unknown or malformed id
            await self.close(code=4404)
            return
        session_id, data = snap
        self.session_id, self.relay_target, self.sender_role = session_id, "customer", "officer"
        self.group = group_name(session_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept(subprotocol=WS_SUBPROTOCOL)
        await self.send_json(envelope("session.status", session_id, data))

    async def session_event(self, event):
        await self.send_json(event["message"])

    @database_sync_to_async
    def _snapshot(self, raw_id: str):
        try:
            sid = uuid.UUID(raw_id)
        except ValueError:
            return None
        s = VerificationSession.objects.filter(pk=sid).first()
        return None if s is None else (str(s.id), {"status": s.status, "final_risk_level": s.final_risk_level})


class OfficerFeedConsumer(_AuthedConsumer):
    """ws://host/ws/officer/feed. Officers only. Dashboard-level events across all sessions (pending approvals etc.)."""
    role = "officer"

    async def connect(self):
        if await self._authenticate() is None:
            return
        self.group = OFFICERS_GROUP
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept(subprotocol=WS_SUBPROTOCOL)

    async def feed_event(self, event):
        await self.send_json(event["message"])


class CustomerConsumer(_AuthedConsumer):
    """ws://host/ws/customer/<id>. Only the customer who owns the session. Receives released challenges, the neutral
    status and the neutral end-of-session message; never risk data."""
    role = "customer"

    async def connect(self):
        raw_id = self.scope["url_route"]["kwargs"]["session_id"]
        user = await self._authenticate()
        if user is None:
            return
        snap = await self._owned_status(raw_id, user.pk)
        if snap is None:  # unknown id or somebody else's session
            await self.close(code=4404)
            return
        session_id, status = snap
        self.session_id, self.relay_target, self.sender_role = session_id, "session", "customer"
        self.group = customer_group(session_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept(subprotocol=WS_SUBPROTOCOL)
        await self.send_json(envelope("session.status", session_id, {"status": status}))

    async def customer_event(self, event):
        await self.send_json(event["message"])

    @database_sync_to_async
    def _owned_status(self, raw_id: str, user_id: int):
        try:
            sid = uuid.UUID(raw_id)
        except ValueError:
            return None
        s = VerificationSession.objects.filter(pk=sid, owner_id=user_id).first()
        return None if s is None else (str(s.id), s.status)
