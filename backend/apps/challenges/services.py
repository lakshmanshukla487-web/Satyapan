import random
import re
import secrets
from datetime import timedelta
from difflib import SequenceMatcher

from django.db import transaction
from django.utils import timezone

from apps.challenges.models import Challenge
from apps.evidence.services import append_event
from apps.realtime.events import publish

# India-related words. Single, widely known words that speech recognition (en-IN) usually gets right. Avoid words with
# several common spellings (e.g. Calcutta/Kolkata, Bombay/Mumbai) because the spelling heard would not match.
WORDS = ["Delhi", "Mumbai", "Kerala", "Punjab", "Diwali", "Holi", "Chai", "Cricket", "Mango", "Lotus", "Ganga", "Himalaya",
         "Bollywood", "Samosa", "Sitar", "Yoga", "Jaipur", "Chennai", "Goa", "Monsoon", "Namaste", "Rajasthan", "Tabla", "Lassi",
         "Rangoli", "Peacock", "Bengal", "Tiranga"]
_rng = random.SystemRandom()


KINDS = ("head_left", "head_right", "blink", "phrase", "eye_scan")
EYE_SCAN_MIN_TTL = 45  # positioning close to the camera takes longer than a head turn


def pick_kind(session_id, iris_enrolled: bool) -> str:
    """Next challenge type. Random, but never the same type twice in a row, and the iris scan is scheduled early (second
    challenge) and then about every fifth one, when a usable reference iris exists."""
    done = list(Challenge.objects.filter(session_id=session_id).order_by("sequence", "issued_at").values_list("challenge_type", flat=True))
    n = len(done)
    if iris_enrolled and (n == 1 or (n >= 5 and "eye_scan" not in done[-4:])):
        return "eye_scan"
    pool = [k for k in KINDS if k != "eye_scan" and (not done or k != done[-1])]
    return secrets.choice(pool)


def issue(session_id: str, ttl: int, *, kind: str | None = None, require_approval: bool = False, approval_timeout: int = 300, sequence: int = 0) -> Challenge:
    """Create (not save) a challenge. With require_approval the challenge starts hidden from the customer
    (status awaiting_approval) and only becomes visible once an officer approves it; its lifetime then restarts."""
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown challenge kind {kind!r}")
    kind = kind or secrets.choice([k for k in KINDS if k != "eye_scan"])
    text = {"head_left": "Turn your head slowly to the left", "head_right": "Turn your head slowly to the right", "blink": "Blink twice",
            "phrase": "Say aloud: " + " ".join(_rng.sample(WORDS, 3)),
            "eye_scan": "Move close to the camera, open your eyes wide and hold still for three seconds"}[kind]
    if kind == "eye_scan":
        ttl = max(ttl, EYE_SCAN_MIN_TTL)
    now = timezone.now()
    if require_approval:
        return Challenge(session_id=session_id, challenge_type=kind, challenge_text=text, issued_at=now, expires_at=now + timedelta(seconds=approval_timeout),
                         status="awaiting_approval", approval_status="pending", sequence=sequence)
    return Challenge(session_id=session_id, challenge_type=kind, challenge_text=text, issued_at=now, expires_at=now + timedelta(seconds=ttl), sequence=sequence)


def _norm(t: str) -> str:
    return re.sub(r"[^a-z ]", "", t.lower()).strip()


YAW_REQUIRED_DEG = 15  # a turn of at least this many degrees (relative to where the head started) counts
BLINKS_REQUIRED = 2
PHRASE_MIN_MATCH = 2 / 3  # share of the requested words that must be heard
WORD_SIMILARITY = 0.8  # tolerates speech-to-text variants such as harbor / harbour


def _phrase_match(expected: str, said: str) -> tuple[int, int, list[str]]:
    """Count how many requested words were heard. Browser speech recognition often changes spelling or adds
    punctuation, so an exact string match would fail people who did speak the phrase correctly."""
    want, heard = _norm(expected).split(), _norm(said).split()
    missing = [w for w in want if not any(SequenceMatcher(None, w, h).ratio() >= WORD_SIMILARITY for h in heard)]
    return len(want) - len(missing), len(want), missing


SERVER_TURN_OK = 12      # degrees the server must see in its own frames to confirm a head turn
SERVER_TURN_NONE = 6     # below this the server saw (almost) no head turn
SERVER_MIN_FRAMES = 3
MOUTH_MOVE_MIN = 0.04    # change in mouth opening (relative to mouth width) that shows the lips moved


def evaluate(c: Challenge, m: dict, server: dict | None = None) -> tuple[str, dict]:
    """Result of one challenge: (passed | failed | unavailable, detail). detail["reason"] is a plain-language explanation and
    detail["verification"] says how well it is backed up (server_confirmed | weak | client_only | mismatch).

    The browser's own measurement (m) can be faked by someone controlling the browser, so it is cross-checked against what the
    SERVER measured on the frames uploaded during the challenge (server = geometry.series_summary of those frames)."""
    result, detail = _evaluate_client(c, m)
    detail["verification"] = "client_only"
    if not server or server.get("n", 0) < SERVER_MIN_FRAMES:
        return result, detail
    detail["server"] = {k: server.get(k) for k in ("n", "turn_left_deg", "turn_right_deg", "ear_dips", "mar_range")}
    kind = c.challenge_type
    if kind in ("head_left", "head_right"):
        turn = server["turn_left_deg"] if kind == "head_left" else server["turn_right_deg"]
        wrong = server["turn_right_deg"] if kind == "head_left" else server["turn_left_deg"]
        if turn >= SERVER_TURN_OK:
            detail.update(verification="server_confirmed", reason=f"The server's own frames show a head turn of about {turn:.0f} degrees the requested way.")
            return "passed", detail
        if turn < SERVER_TURN_NONE and result == "passed":
            detail.update(verification="mismatch", reason=f"The browser reported a head turn, but the server's frames show only about {max(turn, 0):.0f} degrees. The report is not trusted.")
            return "failed", detail
        if turn < SERVER_TURN_NONE:
            detail["verification"] = "server_confirmed"
            if wrong >= SERVER_TURN_OK:
                detail["reason"] += f" The server saw the head turn about {wrong:.0f} degrees the other way."
            return result, detail
        detail["verification"] = "weak"   # 6..12 degrees: neither confirmed nor contradicted
        return result, detail
    if kind == "blink" and server.get("n", 0) >= 6:
        detail["verification"] = "weak" if server.get("ear_dips", 0) >= 1 else "client_only"
    elif kind == "phrase" and server.get("mar_range", 0) >= MOUTH_MOVE_MIN:
        detail["verification"] = "weak"
    return result, detail


def _evaluate_client(c: Challenge, m: dict) -> tuple[str, dict]:
    detail: dict = {"source": "client_reported_unverified", "measured": m}

    def out(result: str, reason: str) -> tuple[str, dict]:
        detail["reason"] = reason
        return result, detail

    if c.challenge_type in ("head_left", "head_right"):
        yaw = m.get("head_yaw_deg")
        side = "left" if c.challenge_type == "head_left" else "right"
        if not isinstance(yaw, (int, float)):
            return out("unavailable", "No head-turn measurement was received (no face detected in time, or the step was skipped).")
        turned = -yaw if side == "left" else yaw  # positive = turned the requested way
        if turned >= YAW_REQUIRED_DEG:
            return out("passed", f"Head turned about {turned:.0f} degrees to the {side} (at least {YAW_REQUIRED_DEG} required).")
        if turned <= -YAW_REQUIRED_DEG:
            return out("failed", f"Head turned about {-turned:.0f} degrees to the wrong side (asked for {side}). If this happens on every head-turn challenge, the camera preview may be mirrored.")
        return out("failed", f"Head turned only {max(turned, 0):.0f} degrees to the {side}; at least {YAW_REQUIRED_DEG} are required.")
    if c.challenge_type == "blink":
        n = m.get("blink_count")
        if not isinstance(n, (int, float)):
            return out("unavailable", "No blink measurement was received (no face detected in time, or the step was skipped).")
        if n >= BLINKS_REQUIRED:
            return out("passed", f"{int(n)} blinks counted ({BLINKS_REQUIRED} required).")
        return out("failed", f"{int(n)} blink(s) counted; {BLINKS_REQUIRED} are required.")
    said = m.get("spoken_text")
    if not isinstance(said, str):
        return out("unavailable", "No speech was recognised (microphone silent, browser has no speech recognition, or the step was skipped).")
    expected = c.challenge_text.removeprefix("Say aloud:")
    ok_words, total, missing = _phrase_match(expected, said)
    if total and ok_words / total >= PHRASE_MIN_MATCH:
        return out("passed", f"Heard {ok_words} of {total} requested words.")
    return out("failed", f"Heard only {ok_words} of {total} requested words (missing: {', '.join(missing) or 'none'}).")


def record_result(s, c: Challenge, result: str, detail: dict, measured: dict) -> Challenge:
    """The one place a challenge becomes 'answered': stores the outcome, appends it to the evidence chain and tells the officers."""
    now = timezone.now()
    with transaction.atomic():
        c.result, c.status, c.measured, c.reason = result, "answered", measured, detail["reason"][:300]
        c.verification, c.answered_at = detail.get("verification", "client_only"), now
        c.save()
        ev = {k: v for k, v in detail.items() if k != "measured"}
        append_event(s.id, "challenge.result", {"challenge_id": str(c.id), "type": c.challenge_type, "result": c.result, "sequence": c.sequence,
                                                "latency_ms": int((now - c.issued_at).total_seconds() * 1000), **ev})
    publish(s.id, "challenge.result", {"challenge_id": str(c.id), "result": c.result, "type": c.challenge_type, "verification": c.verification, "sequence": c.sequence})
    return c


def release(c: Challenge, officer, ttl: int) -> Challenge:
    """The one place a challenge becomes visible to the customer. The clock restarts here, so the customer always gets the full
    time window no matter how long the officer took. officer=None means released automatically (auto-approve)."""
    now = timezone.now()
    c.status, c.approval_status, c.approved_by, c.approved_at = "issued", "approved", officer, now
    life = max(ttl, EYE_SCAN_MIN_TTL) if c.challenge_type == "eye_scan" else ttl
    c.issued_at, c.expires_at = now, now + timedelta(seconds=life)
    c.save()
    return c


def expire_stale(s) -> int:
    """Challenges nobody answered in time are closed as 'expired' (a MISSED challenge, counted in the session analysis)."""
    n = 0
    for c in Challenge.objects.filter(session=s, status__in=("awaiting_approval", "issued"), expires_at__lte=timezone.now()):
        was_released = c.status == "issued"
        c.status = "expired"
        c.save(update_fields=["status"])
        append_event(s.id, "challenge.expired" if was_released else "challenge.unapproved_expired", {"challenge_id": str(c.id), "type": c.challenge_type, "sequence": c.sequence})
        n += 1
    return n
