"""Reference photo enrolment, document-face comparison and the server-side measurement series."""
from __future__ import annotations

import hashlib

import numpy as np
from django.db import transaction

from apps.biometrics import faces, geometry, iris
from apps.biometrics.models import Observation, ReferencePhoto
from apps.evidence.services import append_event

MESSAGES = {
    "NO_FACE": "We could not find your face. Look straight at the camera in good light.",
    "MULTIPLE_FACES": "Only one person may be in the photo.",
    "FACE_TOO_SMALL": "Your face is too small in the photo. Come closer.",
    "TOO_DARK": "The photo is too dark. Face a window or a lamp.",
    "TOO_BRIGHT": "The photo is too bright. Avoid strong light behind or on your face.",
    "BLURRY": "The photo is blurry. Hold the camera steady and tap to focus.",
    "EYES_NOT_WIDE_OPEN": "Open your eyes wide (no squinting, no glasses glare) and look straight at the camera.",
    "FACE_TOO_FAR": "Come closer: your face and eyes should fill most of the picture.",
    "IRIS_DETAIL_LOW": "The eyes are not sharp enough for the eye scan later. A closer, sharper photo helps.",
    "EYES_NOT_FOUND": "Your eyes could not be measured in this photo. Look straight at the camera with your eyes wide open.",
}
BLOCKING = {"NO_FACE", "MULTIPLE_FACES", "FACE_TOO_SMALL", "TOO_DARK", "TOO_BRIGHT", "BLURRY", "EYES_NOT_WIDE_OPEN"}
MIN_EYE_DIST_FRAC = 0.16   # the outer corners of the eyes should span at least this share of the photo width
WIDE_OPEN_EAR = 0.20


def get_reference(s) -> ReferencePhoto | None:
    return ReferencePhoto.objects.filter(session=s).first()


def iris_enrolled(s) -> bool:
    ref = get_reference(s)
    return bool(ref and any((v or {}).get("quality", {}).get("usable") for v in (ref.iris or {}).values()))


def analyse_reference(rt, rgb: np.ndarray) -> dict:
    """Analyse the uploaded close-up photo, in memory. PURE computation (models only, no database access), so it can run in the
    inference worker pool: a database write from a worker thread would wait for the request's own SQLite lock and fail with
    'database is locked'. -> the result plus the private fields `_embedding`, `_iris`, `_quality` that save_reference() stores."""
    issues: list[str] = []
    embedding: list[float] = []
    quality: dict = {}
    face_state, iris_state = "unavailable", "unavailable"
    fm = rt.registry.get("facematch")
    if fm is not None and fm.ensure_loaded():
        r = fm.embed_reference(rgb)
        quality = r.get("quality", {})
        if not r["ok"]:
            issues.append(r["code"])
        else:
            issues += [i for i in quality.get("issues", [])]
            embedding = r["embedding"] if not quality.get("issues") else []
        face_state = "ok" if embedding else "problem"
    iris_packed: dict = {}
    eye_issues: list[str] = []
    es = rt.registry.get("eyescan")
    if es is not None and es.ensure_loaded():
        t = es.template_from_frame(rgb)
        f = t["face"]
        if f is None:
            eye_issues.append("EYES_NOT_FOUND" if face_state == "ok" else "NO_FACE")
            iris_state = "problem"
        else:
            quality["eye_distance_fraction"], quality["eye_openness"] = f["eye_dist_frac"], f["ear_mean"]
            if f["eye_dist_frac"] < MIN_EYE_DIST_FRAC:
                eye_issues.append("FACE_TOO_FAR")
            if f["ear_mean"] < WIDE_OPEN_EAR:
                eye_issues.append("EYES_NOT_WIDE_OPEN")  # half-closed lids cover the iris: its code would be noise, so none is kept
                iris_state = "problem"
            else:
                for side, tpl in t["eyes"].items():
                    iris_packed[side] = iris.pack(tpl)
                usable = [side for side, tpl in t["eyes"].items() if tpl["quality"]["usable"]]
                iris_state = "ok" if usable else "low_detail"
                if not usable:
                    eye_issues.append("IRIS_DETAIL_LOW")
            quality["iris"] = {side: tpl["quality"] for side, tpl in t["eyes"].items()}
    # EYES_NOT_WIDE_OPEN still blocks: the customer can fix it with one retake and the iris check needs it. EYES_NOT_FOUND (the face
    # detector found a face but the landmark model could not measure the eyes) is NOT the customer's fault, so it never blocks a
    # good face reference: face matching works and only the iris check is unavailable for this session.
    issues = list(dict.fromkeys(issues + eye_issues))
    blocking = [i for i in issues if i in BLOCKING and (face_state != "unavailable" or iris_state != "unavailable")]
    return {"accepted": not blocking, "face_check": face_state, "iris_check": iris_state, "issues": issues,
            "messages": [MESSAGES.get(i, i) for i in issues], "blocking": blocking,
            "_embedding": embedding, "_iris": iris_packed, "_quality": {**quality, "issues": issues}}


def save_reference(s, analysed: dict, raw: bytes) -> dict:
    """Store an accepted analysis (request thread only). Only the embedding and the iris templates are kept, never the photo.
    -> what the customer sees (no templates)."""
    out = {k: v for k, v in analysed.items() if not k.startswith("_")}
    if out["accepted"]:
        sha = hashlib.sha256(raw).hexdigest()
        with transaction.atomic():
            ReferencePhoto.objects.update_or_create(session=s, defaults={
                "face_embedding": analysed["_embedding"], "iris": analysed["_iris"], "quality": analysed["_quality"], "file_sha256": sha})
            append_event(s.id, "reference_photo.recorded", {"face": out["face_check"], "iris": out["iris_check"], "issues": out["issues"], "file_sha256": sha})
    return out


def enrol_reference(rt, s, rgb: np.ndarray, raw: bytes) -> dict:
    """analyse_reference + save_reference in the calling thread (scripts and tests)."""
    return save_reference(s, analyse_reference(rt, rgb), raw)


# ---- pose series --------------------------------------------------------------------------------------------------------

def record_pose(s, challenge_id, pose: dict) -> None:
    Observation.objects.create(session=s, kind="pose", challenge_id=challenge_id, value=pose.get("yaw_right_deg"), quality=pose.get("eye_dist_frac"), data=pose)


def pose_summary(s, c) -> dict:
    rows = Observation.objects.filter(session=s, kind="pose", challenge_id=c.id).order_by("created_at")
    return geometry.series_summary([r.data for r in rows])


# ---- documents: the face printed on an ID vs the customer ----------------------------------------------------------------

DOC_MATCH, DOC_MISMATCH = 0.363, 0.20   # photos on ID cards are small and printed: only a clear disagreement is an indicator


def record_document_face(rt, s, doc_type: str, rgb: np.ndarray) -> dict:
    """Find the face on a document image and keep its embedding (never the image). Replaces an earlier face of the same document type."""
    fm = rt.registry.get("facematch")
    if fm is None or not fm.ensure_loaded():
        return {"state": "unavailable"}
    found = fm._eng.detect(rgb)
    Observation.objects.filter(session=s, kind="doc_face", data__doc_type=doc_type).delete()
    if not found or min(found[0]["box"][2:]) < 28:
        return {"state": "no_face"}
    emb = fm._eng.embed(rgb, found[0]).tolist()
    Observation.objects.create(session=s, kind="doc_face", quality=float(found[0]["score"]), data={"doc_type": doc_type, "embedding": emb, "face_px": int(min(found[0]["box"][2:]))})
    return {"state": "face_found"}


def document_face_results(s) -> list[dict]:
    ref = get_reference(s)
    docs = list(Observation.objects.filter(session=s, kind="doc_face"))
    out = []
    for d in docs:
        row = {"doc_type": d.data["doc_type"], "state": "no_reference"}
        if ref is not None and ref.face_embedding:
            sim = faces.cosine(np.array(ref.face_embedding), np.array(d.data["embedding"]))
            row.update(similarity=round(sim, 4), state="match" if sim >= DOC_MATCH else ("mismatch" if sim < DOC_MISMATCH else "uncertain"))
        out.append(row)
    return out


def document_face_reasons(s) -> list[dict]:
    """Findings in the same shape as the cross-document findings, so they flow into the decision engine and the report."""
    out = []
    for r in document_face_results(s):
        t = r["doc_type"].replace("_", " ")
        if r["state"] == "mismatch":
            out.append({"code": "DOCUMENT_FACE_MISMATCH", "severity": "indicator", "category": "documents", "title": "Face on the document does not match the customer's photo",
                        "detail": f"The face printed on the {t} is clearly different from the close-up photo the customer uploaded (similarity {r['similarity']:.2f}).", "evidence": {"docs": [r["doc_type"]]}})
        elif r["state"] == "uncertain":
            out.append({"code": "DOCUMENT_FACE_UNCERTAIN", "severity": "note", "category": "documents", "title": "Document face comparison inconclusive",
                        "detail": f"The face on the {t} is a small printed photo, so the comparison with the customer's photo is inconclusive (similarity {r['similarity']:.2f}). A human should compare them.", "evidence": {"docs": [r["doc_type"]]}})
    return out
