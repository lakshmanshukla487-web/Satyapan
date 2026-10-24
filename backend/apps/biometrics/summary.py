"""Plain data about the identity checks of one session, for the officer screen and the report."""
from statistics import median

from apps.biometrics import services as bs
from apps.biometrics.models import Observation
from apps.signals.models import DetectorSignal


def face_match_series(s) -> list[dict]:
    rows = DetectorSignal.objects.filter(session=s, detector_name="facematch").order_by("created_at")
    t0 = s.started_at or s.created_at
    out = []
    for r in rows:
        sim = (r.details or {}).get("similarity")
        out.append({"t": round((r.created_at - t0).total_seconds(), 1), "status": r.status, "similarity": sim, "error_code": r.error_code})
    return out


def summarise(s) -> dict:
    ref = bs.get_reference(s)
    series = face_match_series(s)
    sims = [x["similarity"] for x in series if x["status"] == "ok" and x["similarity"] is not None]
    thr = None
    from apps.core.runtime import get_runtime
    thr = get_runtime().settings.face_cosine_threshold
    iris = [{"challenge_id": str(o.challenge_id), "hamming_distance": o.value, "verdict": o.data.get("verdict"), "readings": o.data.get("readings"),
             "at": o.created_at} for o in Observation.objects.filter(session=s, kind="iris_match")]
    return {
        "reference_photo": {"uploaded": ref is not None, "face_embedding": bool(ref and ref.face_embedding), "iris_usable": bs.iris_enrolled(s),
                            "issues": (ref.quality or {}).get("issues", []) if ref else []},
        "face_match": {"samples": len(series), "usable": len(sims), "median_similarity": round(median(sims), 4) if sims else None,
                       "min_similarity": round(min(sims), 4) if sims else None, "threshold": thr,
                       "fraction_below_threshold": round(sum(1 for x in sims if x < thr) / len(sims), 3) if sims else None, "series": series[-60:]},
        "iris_scans": iris,
        "document_faces": bs.document_face_results(s),
    }
