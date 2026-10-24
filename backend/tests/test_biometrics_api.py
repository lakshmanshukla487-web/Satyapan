"""Reference photo (start of the session), face / iris checks and the eye-scan challenge, through the API with stub detectors."""
from apps.signals.detector_base import BaseDetector
from tests.conftest import MockDetector, png_bytes, running_session
from tests.test_biometrics_logic import _template

S = "/api/v1/sessions"


class StubFace(BaseDetector):
    name, signal_type = "facematch", "face_match"

    def __init__(self, settings, reference):
        super().__init__(settings)
        self.reference = reference

    def load(self):
        pass

    def embed_reference(self, rgb):
        return self.reference

    def _infer(self, media, metadata):
        return self.result("low_quality", error_code="NOT_USED")


class StubEyes(BaseDetector):
    name, signal_type = "eyescan", "iris_match"

    def __init__(self, settings, template=None, details=None, status="ok"):
        super().__init__(settings)
        self.template, self.details, self.status = template, details or {}, status

    def load(self):
        pass

    def template_from_frame(self, rgb):
        return self.template

    def _infer(self, media, metadata):
        return self.result(self.status, 0.05, label=self.details.get("verdict"), details=self.details)


GOOD_FACE = {"ok": True, "embedding": [0.1] * 128, "quality": {"issues": []}}
GOOD_EYES = {"face": {"eye_dist_frac": 0.3, "ear_mean": 0.32}, "eyes": {"left": _template(1), "right": _template(2)}}
SCAN_OK = {"verdict": "match", "hamming_distance": 0.12, "readings": 4, "frames_with_usable_iris": 3, "max_eye_distance_fraction": 0.3, "max_eye_openness": 0.3}


def photo(c, sid):
    return c.post(f"{S}/{sid}/reference-photo", files={"file": ("selfie.png", png_bytes((256, 256)), "image/png")})


def test_reference_photo_needs_consent_and_a_customer(make_client):
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE)})
    sid = c.post(S).json()["id"]
    assert photo(c, sid).status_code == 403                      # no consent yet
    sid = running_session(c)
    assert c.officer.post(f"{S}/{sid}/reference-photo", files={"file": ("a.png", png_bytes(), "image/png")}).status_code == 403


def test_good_reference_photo_is_kept_as_templates_only(make_client):
    from apps.biometrics.models import ReferencePhoto
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, GOOD_EYES)})
    sid = running_session(c)
    r = photo(c, sid)
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["accepted"] is True and body["face_check"] == "ok" and body["iris_check"] == "ok" and body["blocking"] == []
    ref = ReferencePhoto.objects.get(session_id=sid)
    assert len(ref.face_embedding) == 128 and set(ref.iris) == {"left", "right"} and len(ref.file_sha256) == 64
    assert c.get(f"{S}/{sid}/reference-photo").json() == {"uploaded": True, "face_check": "ok", "iris_check": "ok"}
    # the officer sees the identity summary; the customer never does
    assert c.get(f"{S}/{sid}/biometrics").status_code == 403
    assert c.officer.get(f"{S}/{sid}/biometrics").status_code == 200


def test_unusable_reference_photo_is_refused_with_advice(make_client):
    bad = {"ok": False, "code": "NO_FACE", "quality": {}}
    c = make_client(lambda s: {"facematch": StubFace(s, bad)})
    sid = running_session(c)
    body = photo(c, sid).json()
    assert body["accepted"] is False and "NO_FACE" in body["blocking"] and any("find your face" in m for m in body["messages"])
    assert c.get(f"{S}/{sid}/reference-photo").json()["uploaded"] is False       # nothing is kept from a refused photo


def test_squinting_photo_is_refused_for_the_iris_scan(make_client):
    squint = {"face": {"eye_dist_frac": 0.3, "ear_mean": 0.08}, "eyes": GOOD_EYES["eyes"]}
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, squint)})
    sid = running_session(c)
    body = photo(c, sid).json()
    assert body["accepted"] is False and "EYES_NOT_WIDE_OPEN" in body["blocking"]


def test_far_away_photo_is_accepted_but_told_to_come_closer(make_client):
    far = {"face": {"eye_dist_frac": 0.10, "ear_mean": 0.3}, "eyes": GOOD_EYES["eyes"]}
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, far)})
    body = photo(c, running_session(c)).json()
    assert "FACE_TOO_FAR" in body["issues"]


def test_without_models_the_photo_is_kept_and_checks_are_reported_unavailable(make_client):
    c = make_client(lambda s: {"audio": MockDetector(s, "audio", "audio_spoof", 0.1)})
    sid = running_session(c)
    body = photo(c, sid).json()
    assert body["accepted"] is True and body["face_check"] == "unavailable" and body["iris_check"] == "unavailable"


def test_reference_photo_rejects_non_images(make_client):
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE)})
    sid = running_session(c)
    r = c.post(f"{S}/{sid}/reference-photo", files={"file": ("x.png", b"this is not an image", "image/png")})
    assert r.status_code in (415, 422), r.content


def test_eye_scan_is_scheduled_when_an_iris_was_enrolled(make_client):
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, GOOD_EYES, SCAN_OK)})
    sid = running_session(c)
    photo(c, sid)
    kinds = []
    for _ in range(3):
        ch = c.post(f"{S}/{sid}/challenges").json()
        kinds.append(ch["challenge_type"])
        if ch["challenge_type"] != "eye_scan":
            c.post(f"{S}/{sid}/challenges/{ch['id']}/result", json={"measured": {}})
        else:
            break
    assert kinds[1] == "eye_scan"                                  # the second challenge is the close-up eye scan


def _scan(c, sid):
    ch = c.officer.post(f"{S}/{sid}/challenges/issue", json={"type": "eye_scan"}).json()
    r = c.post(f"{S}/{sid}/challenges/{ch['id']}/eye-scan", files={"file": ("f.png", png_bytes((256, 256)), "image/png")})
    assert r.status_code == 200, r.content
    assert r.json() == {"received": True}                          # the customer is not told the result
    return next(x for x in c.officer.get(f"{S}/{sid}/challenges").json() if x["id"] == ch["id"])


def test_eye_scan_match_passes_and_is_decided_by_the_server(make_client):
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, GOOD_EYES, SCAN_OK)})
    sid = running_session(c)
    photo(c, sid)
    done = _scan(c, sid)
    assert done["result"] == "passed" and done["verification"] == "server_only" and "matches" in done["reason"]


def test_eye_scan_mismatch_fails(make_client):
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, GOOD_EYES, {**SCAN_OK, "verdict": "mismatch", "hamming_distance": 0.47})})
    sid = running_session(c)
    photo(c, sid)
    assert _scan(c, sid)["result"] == "failed"


def test_eye_scan_not_close_enough_is_not_counted_for_or_against(make_client):
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, GOOD_EYES, {**SCAN_OK, "max_eye_distance_fraction": 0.1})})
    sid = running_session(c)
    photo(c, sid)
    assert _scan(c, sid)["result"] == "unavailable"


def test_eye_scan_inconclusive_is_unavailable(make_client):
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, GOOD_EYES, {**SCAN_OK, "verdict": "uncertain", "hamming_distance": 0.36})})
    sid = running_session(c)
    photo(c, sid)
    assert _scan(c, sid)["result"] == "unavailable"


def test_eye_scan_rules(make_client):
    c = make_client(lambda s: {"facematch": StubFace(s, GOOD_FACE), "eyescan": StubEyes(s, GOOD_EYES, SCAN_OK)})
    sid = running_session(c)
    blink = c.officer.post(f"{S}/{sid}/challenges/issue", json={"type": "blink"}).json()
    f = {"file": ("f.png", png_bytes((256, 256)), "image/png")}
    assert c.post(f"{S}/{sid}/challenges/{blink['id']}/eye-scan", files=f).status_code == 404     # only for eye-scan challenges
    assert c.post(f"{S}/{sid}/challenges/not-a-uuid/eye-scan", files=f).status_code == 404
    scan = c.officer.post(f"{S}/{sid}/challenges/issue", json={"type": "eye_scan"}).json()
    assert c.post(f"{S}/{sid}/challenges/{scan['id']}/eye-scan", files=f).status_code == 200
    assert c.post(f"{S}/{sid}/challenges/{scan['id']}/eye-scan", files=f).json()["error"]["code"] == "CHALLENGE_ALREADY_ANSWERED"
    assert c.officer.post(f"{S}/{sid}/challenges/{scan['id']}/eye-scan", files=f).status_code == 403
