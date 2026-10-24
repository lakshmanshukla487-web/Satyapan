"""Regression tests for the face- and iris-matching failures found on real photos: close-up faces the detector missed, the start
photo failing with 'database is locked', eye-measurement problems discarding a good face reference, sideways phone photos, and
iris verdicts given on irises too small to carry a usable pattern."""
import io

import numpy as np
import pytest
from PIL import Image

from apps.biometrics import faces
from apps.biometrics.detectors import EyeScanDetector
from apps.biometrics.services import analyse_reference
from apps.core.errors import AppError
from apps.core.media import decode_image
from apps.signals.registry import DetectorRegistry
from tests.conftest import make_settings, running_session
from tests.test_biometrics_api import GOOD_EYES, GOOD_FACE, StubEyes, StubFace, photo
from tests.test_biometrics_logic import _template


# ---- face detector: second pass for close-ups ---------------------------------------------------------------------------------

class FakeYuNet:
    """Finds a 'face' only when it is small in the image it is given (YuNet's real failure mode on close-ups)."""
    def __init__(self, face_frac_max=0.5):
        self.size, self.calls, self.face_frac_max = None, [], face_frac_max

    def setInputSize(self, size):
        self.size = size

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        self.calls.append((w, h))
        ys, xs = np.nonzero(bgr[..., 0] > 200)  # the bright square is the "face"
        if not len(xs):
            return None, None
        x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        if (x1 - x0) / w > self.face_frac_max:
            return None, None
        lms = [x0 + 0.3 * (x1 - x0), y0 + 0.4 * (y1 - y0), x0 + 0.7 * (x1 - x0), y0 + 0.4 * (y1 - y0), (x0 + x1) / 2, (y0 + y1) / 2,
               x0 + 0.35 * (x1 - x0), y0 + 0.8 * (y1 - y0), x0 + 0.65 * (x1 - x0), y0 + 0.8 * (y1 - y0)]
        return None, np.array([[x0, y0, x1 - x0, y1 - y0, *lms, 0.95]], np.float32)


def _engine(det):
    import cv2
    import threading
    e = faces.FaceEngine.__new__(faces.FaceEngine)
    e.cv2, e._det, e._lock = cv2, det, threading.Lock()
    return e


def test_a_face_filling_the_picture_is_found_and_mapped_back():
    rgb = np.zeros((1000, 1000, 3), np.uint8)
    rgb[100:900, 150:850] = 255  # a face 70 % of the image wide: the first pass misses it
    det = FakeYuNet()
    found = _engine(det).detect(rgb)
    assert len(det.calls) == 2 and found
    x, y, w, h = found[0]["box"]
    assert abs(x - 150) < 6 and abs(y - 100) < 6 and abs(w - 700) < 8 and abs(h - 800) < 8  # original pixels, border removed
    row = found[0]["row"]
    assert abs(row[4] - (150 + 0.3 * 700)) < 6 and abs(row[5] - (100 + 0.4 * 800)) < 6  # landmarks mapped back too


def test_a_normal_face_needs_one_pass_only():
    rgb = np.zeros((480, 640, 3), np.uint8)
    rgb[150:300, 250:370] = 255
    det = FakeYuNet()
    assert _engine(det).detect(rgb) and len(det.calls) == 1


# ---- start photo ------------------------------------------------------------------------------------------------------------

def test_analysing_the_start_photo_never_touches_the_database():
    """It runs in the inference worker pool; a database write there waited for the request's SQLite lock ('database is locked').
    No django_db mark: pytest-django raises if this function makes any query."""
    s = make_settings()
    rt = type("RT", (), {"registry": DetectorRegistry(s, {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, GOOD_EYES)})})()
    out = analyse_reference(rt, np.zeros((256, 256, 3), np.uint8))
    assert out["accepted"] and out["face_check"] == "ok" and out["iris_check"] == "ok" and out["_embedding"]


def test_eyes_the_landmark_model_cannot_measure_do_not_discard_a_good_face(make_client):
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, {"face": None, "n_faces": 0, "eyes": {}})})
    body = photo(c, running_session(c)).json()
    assert body["accepted"] is True and body["face_check"] == "ok" and body["iris_check"] == "problem"
    assert "EYES_NOT_FOUND" in body["issues"] and not body["blocking"]


def test_without_a_usable_face_missing_eyes_still_block(make_client):
    c = make_client(lambda s: {"facematch": StubFace(s, {"ok": False, "code": "NO_FACE", "face_count": 0}),
                               "eyescan": StubEyes(s, {"face": None, "n_faces": 0, "eyes": {}})})
    body = photo(c, running_session(c)).json()
    assert body["accepted"] is False and "NO_FACE" in body["blocking"]


# ---- phone photos ----------------------------------------------------------------------------------------------------------

def test_phone_photo_rotation_is_applied():
    im = Image.new("RGB", (400, 300))
    exif = im.getexif()
    exif[0x0112] = 6  # "rotate 90 degrees clockwise to display"
    b = io.BytesIO()
    im.save(b, "JPEG", exif=exif)
    assert decode_image(b.getvalue(), 4096).size == (300, 400)


def test_a_large_phone_jpeg_is_shrunk_not_refused():
    b = io.BytesIO()
    Image.new("RGB", (6000, 4500)).save(b, "JPEG", quality=60)
    assert max(decode_image(b.getvalue(), 4096).size) == 4096


def test_other_oversized_formats_are_still_refused_before_decoding():
    b = io.BytesIO()
    Image.new("RGB", (5000, 50)).save(b, "PNG")
    with pytest.raises(AppError) as e:
        decode_image(b.getvalue(), 4096)
    assert e.value.code == "IMAGE_TOO_LARGE"


# ---- iris verdicts need enough detail -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("min_px, verdict", [(20.0, "match"), (500.0, "uncertain")])
def test_iris_verdict_only_when_the_iris_is_big_enough(min_px, verdict):
    d = EyeScanDetector(make_settings(iris_min_verdict_px=min_px))
    ref = {"right": _template(1), "left": _template(2)}
    d.template_from_frame = lambda rgb: {"face": {"eye_dist_frac": 0.3, "ear_mean": 0.3}, "n_faces": 1,
                                         "eyes": {"right": _template(1, noise=3.0), "left": _template(2, noise=3.0)}}
    d._loaded = True
    from apps.biometrics import iris
    r = d.analyze({"frames": [np.zeros((10, 10, 3), np.uint8)] * 2, "ref": {k: iris.pack(v) for k, v in ref.items()}})
    assert r["status"] == "ok" and r["details"]["verdict"] == verdict
    if verdict == "uncertain":
        assert r["details"]["why"] == "IRIS_TOO_SMALL_FOR_VERDICT" and r["score"] <= 0.6  # never reaches the flag threshold
