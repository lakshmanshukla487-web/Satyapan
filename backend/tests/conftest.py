import io
import math
import struct
import wave

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from satyapan.conf import AppSettings
from apps.signals.detector_base import BaseDetector, DetectorError
from apps.signals.registry import DetectorRegistry
from apps.core.runtime import Runtime, set_runtime


class MockDetector(BaseDetector):
    """Returns canned output; no ML dependencies. fail_load simulates a missing model."""
    def __init__(self, settings, name, signal_type, score=None, thr=0.7, fail_load=None):
        super().__init__(settings)
        self.name, self.signal_type, self._score, self._thr, self._fail = name, signal_type, score, thr, fail_load

    @property
    def threshold(self):
        return self._thr

    def load(self):
        if self._fail:
            raise DetectorError(self._fail)

    def _infer(self, media, metadata):
        return self.result("ok", self._score, label="mock")


def make_settings(**kw) -> AppSettings:
    # The product defaults turn the document gate and the officer-approval gate ON; the pre-existing tests exercise the
    # flows without them, and tests/test_documents.py / tests/test_approval_workflow.py turn them on explicitly.
    # v4 gates (officer approval before a session, the v3 policy, model preload) are also OFF by default here; their own
    # test files turn them on explicitly.
    return AppSettings(**{"rate_limit_per_minute": 10000, "rate_limit_user_per_minute": 10000, "rate_limit_media_per_minute": 10000,
                          "rate_limit_ip_ceiling_per_minute": 100000, "require_documents": False, "require_challenge_approval": False,
                          "require_session_approval": False, "decision_policy": "v2", "preload_models": False, "enable_ip_check": False, **kw})


class Client:
    """Thin wrapper over DRF's APIClient with the call style these tests use: post(url, json=..., files=...).
    `client` is signed in as a customer; `client.officer` is the same service signed in as an officer."""
    def __init__(self, token=None):
        self._c = APIClient()
        self.token = token
        if token:
            self._c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def get(self, url):
        return self._c.get(url)

    def post(self, url, json=None, files=None, fields=None):
        if files:
            name, data, ctype = files["file"]
            return self._c.post(url, {"file": SimpleUploadedFile(name, data, ctype), **(fields or {})}, format="multipart")
        if json is not None:
            return self._c.post(url, json, format="json")
        return self._c.post(url)


@pytest.fixture(autouse=True)
def _reset_runtime(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast hashing in tests
    yield
    set_runtime(None)


def ensure_user(username, role="customer", password="correct-horse-9"):
    from apps.accounts.models import User
    u, _ = User.objects.get_or_create(username=username, defaults={"role": role})
    u.role = role
    u.set_password(password)
    u.save()
    return u


def client_for(user) -> Client:
    from apps.accounts.auth import issue_token
    return Client(issue_token(user)[0])


@pytest.fixture
def make_client(db):
    def _make(detectors=None, **kw):
        s = make_settings(**kw)
        set_runtime(Runtime.build(s, DetectorRegistry(s, detectors(s) if detectors else {})))
        c = client_for(ensure_user("alice", "customer"))
        c.officer = client_for(ensure_user("olivia", "officer"))
        return c
    return _make


@pytest.fixture
def client(make_client):
    return make_client(lambda s: {"audio": MockDetector(s, "audio", "audio_spoof", 0.1), "vit": MockDetector(s, "vit", "visual_deepfake", 0.1)})


def running_session(c):
    sid = c.post("/api/v1/sessions").json()["id"]
    assert c.post(f"/api/v1/sessions/{sid}/consent", json={"granted": True}).status_code == 200
    assert c.post(f"/api/v1/sessions/{sid}/start").status_code == 200
    return sid


GOOD_MEASUREMENT = {"head_left": {"head_yaw_deg": -30}, "head_right": {"head_yaw_deg": 30}, "blink": {"blink_count": 2}}


def answer_challenge(c, sid, kind, measured=None):
    """The officer runs a challenge of a chosen type, the customer answers it. The customer is never told the outcome, so it is
    read back through the officer's view. -> the officer's view of the answered challenge."""
    r = c.officer.post(f"/api/v1/sessions/{sid}/challenges/issue", json={"type": kind})
    assert r.status_code == 201, r.content
    ch = r.json()
    if measured is None:
        measured = {"spoken_text": ch["challenge_text"].removeprefix("Say aloud: ")} if kind == "phrase" else GOOD_MEASUREMENT[kind]
    a = c.post(f"/api/v1/sessions/{sid}/challenges/{ch['id']}/result", json={"measured": measured})
    assert a.status_code == 200, a.content
    assert "result" not in a.json()  # hidden from the customer
    return next(x for x in c.officer.get(f"/api/v1/sessions/{sid}/challenges").json() if x["id"] == ch["id"])


def pass_challenge(c, sid, kind="blink"):
    assert answer_challenge(c, sid, kind)["result"] == "passed"


def wav_bytes(seconds=2.0, silent=False, sr=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", 0 if silent else int(8000 * math.sin(i / 20))) for i in range(int(sr * seconds))))
    return buf.getvalue()


def png_bytes(size=(128, 128), color=(120, 120, 120)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()
