"""Live call and chat between an officer and the customer of one running session.

The server never touches the video: it only relays small signalling messages (WebRTC offer / answer / ICE candidates)
and chat text between the two sockets of ONE session. Everything is whitelisted, size-limited and rate-limited; the
customer must accept a call before anything is sent to their camera (the browser also asks for permission)."""
import time

MAX_SDP = 16_000
MAX_CAND = 1_000
MAX_CHAT = 500
MAX_FRAME = 24_000  # bytes of one WebSocket text message from a client
CALL_EVENTS = {"call.request", "call.accept", "call.decline", "call.end"}


def _s(v, n):
    return v if isinstance(v, str) and len(v) <= n else None


def clean_message(msg) -> tuple[str, dict] | None:
    """Return (event, data) built only from allowed fields, or None if the message is not acceptable."""
    if not isinstance(msg, dict):
        return None
    ev = msg.get("event")
    d = msg.get("data") if isinstance(msg.get("data"), dict) else {}
    if ev in CALL_EVENTS:
        return ev, {"reason": (_s(d.get("reason"), 120) or "")}
    if ev == "chat.message":
        text = _s(d.get("text"), MAX_CHAT)
        text = text.strip() if text else ""
        return (ev, {"text": text}) if text else None
    if ev == "rtc.signal":
        kind = d.get("kind")
        if kind in ("offer", "answer"):
            sdp = _s(d.get("sdp"), MAX_SDP)
            return (ev, {"kind": kind, "sdp": sdp}) if sdp else None
        if kind == "candidate":
            c = d.get("candidate")
            if c is None:  # end-of-candidates marker
                return ev, {"kind": "candidate", "candidate": None}
            if not isinstance(c, dict):
                return None
            line = _s(c.get("candidate"), MAX_CAND)
            if line is None:
                return None
            idx = c.get("sdpMLineIndex")
            return ev, {"kind": "candidate", "candidate": {"candidate": line, "sdpMid": _s(c.get("sdpMid"), 40), "sdpMLineIndex": idx if isinstance(idx, int) and 0 <= idx < 8 else None}}
    return None


class Bucket:
    """Token bucket: `rate` messages per second, burst `burst`."""

    def __init__(self, rate: float = 8.0, burst: int = 40):
        self.rate, self.burst, self.tokens, self.t = rate, burst, float(burst), time.monotonic()

    def take(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.t) * self.rate)
        self.t = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True
