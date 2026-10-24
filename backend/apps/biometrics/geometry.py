"""Face geometry from MediaPipe's 478-point face mesh: head turn, eye openness, mouth opening, closeness, iris circles.

Pure numpy, no MediaPipe import, so it is unit-tested with synthetic landmark arrays. Input: array (478, 3) with x and y
normalised to 0..1 (image width / height) and z in the same scale as x (MediaPipe convention), plus the image size.

Sign convention (documented because it decides whether "turn LEFT" passes): yaw is positive when the person turns their
head toward THEIR OWN RIGHT, measured on the raw (un-mirrored) camera image. In that image the person's right is on the
image's left, so the nose tip moves toward smaller x.
"""
from __future__ import annotations

import math

import numpy as np

# MediaPipe indices
NOSE_TIP = 1
EYE_OUTER_RIGHT, EYE_OUTER_LEFT = 33, 263          # outer corners; "right/left" are the PERSON's right and left
RIGHT_EYE_EAR = (33, 160, 158, 133, 153, 144)      # p1 outer, p2 upper, p3 upper, p4 inner, p5 lower, p6 lower
LEFT_EYE_EAR = (362, 385, 387, 263, 373, 380)      # p1 inner, p2, p3 upper, p4 outer, p5, p6 lower
RIGHT_IRIS_CENTER, RIGHT_IRIS_RING = 468, (469, 470, 471, 472)
LEFT_IRIS_CENTER, LEFT_IRIS_RING = 473, (474, 475, 476, 477)
MOUTH_UP, MOUTH_DOWN, MOUTH_LEFT, MOUTH_RIGHT = 13, 14, 78, 308
NOSE_PROTRUSION = 0.5  # nose tip stands out of the eye plane by about half the outer-eye-corner distance

N_LANDMARKS_MIN = 468


def _px(lm: np.ndarray, idx: int, w: int, h: int) -> np.ndarray:
    return np.array([lm[idx, 0] * w, lm[idx, 1] * h], dtype=np.float64)


def _d(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def eye_aspect_ratio(lm: np.ndarray, idx: tuple[int, ...], w: int, h: int) -> float:
    p = [_px(lm, i, w, h) for i in idx]
    horiz = _d(p[0], p[3])
    return 0.0 if horiz < 1e-6 else (_d(p[1], p[5]) + _d(p[2], p[4])) / (2.0 * horiz)


def measure(lm: np.ndarray, w: int, h: int) -> dict:
    """Everything the checks need from one face, in plain numbers."""
    if lm is None or len(lm) < N_LANDMARKS_MIN:
        return {"ok": False}
    r_out, l_out, nose = _px(lm, EYE_OUTER_RIGHT, w, h), _px(lm, EYE_OUTER_LEFT, w, h), _px(lm, NOSE_TIP, w, h)
    eye_dist = _d(r_out, l_out)
    if eye_dist < 4:
        return {"ok": False}
    mid_x = (r_out[0] + l_out[0]) / 2.0
    offset = (mid_x - nose[0]) / eye_dist                     # > 0: nose toward the person's right
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, offset / NOSE_PROTRUSION))))
    ear_r, ear_l = eye_aspect_ratio(lm, RIGHT_EYE_EAR, w, h), eye_aspect_ratio(lm, LEFT_EYE_EAR, w, h)
    mouth_w = _d(_px(lm, MOUTH_LEFT, w, h), _px(lm, MOUTH_RIGHT, w, h))
    mar = 0.0 if mouth_w < 1e-6 else _d(_px(lm, MOUTH_UP, w, h), _px(lm, MOUTH_DOWN, w, h)) / mouth_w
    xs, ys = lm[:468, 0] * w, lm[:468, 1] * h
    out = {"ok": True, "yaw_right_deg": round(yaw, 2), "ear_right": round(ear_r, 4), "ear_left": round(ear_l, 4),
           "ear_mean": round((ear_r + ear_l) / 2.0, 4), "mar": round(mar, 4), "eye_dist_px": round(eye_dist, 1),
           "eye_dist_frac": round(eye_dist / w, 4), "face_w_frac": round(float(xs.max() - xs.min()) / w, 4),
           "face_h_frac": round(float(ys.max() - ys.min()) / h, 4),
           "face_center": [round(float(xs.mean()) / w, 4), round(float(ys.mean()) / h, 4)]}
    out["iris"] = {"right": iris_circle(lm, RIGHT_IRIS_CENTER, RIGHT_IRIS_RING, w, h), "left": iris_circle(lm, LEFT_IRIS_CENTER, LEFT_IRIS_RING, w, h)} if len(lm) >= 478 else None
    return out


def iris_circle(lm: np.ndarray, center_idx: int, ring: tuple[int, ...], w: int, h: int) -> dict:
    """Centre and radius of the iris in pixels, from MediaPipe's iris landmarks (centre + 4 ring points)."""
    c = _px(lm, center_idx, w, h)
    r = float(np.mean([_d(c, _px(lm, i, w, h)) for i in ring]))
    return {"cx": round(float(c[0]), 2), "cy": round(float(c[1]), 2), "r": round(r, 2)}


# ----------------------------------------------------------------------------------------------------------------------
# Time-series helpers (the server's own measurements from frames uploaded during a challenge)

def series_summary(samples: list[dict]) -> dict:
    """samples: [{"t": seconds, "yaw_right_deg":.., "ear_mean":.., "mar":.., ...}, ...] oldest first."""
    ok = [s for s in samples if s.get("yaw_right_deg") is not None]
    if not ok:
        return {"n": 0}
    yaw = np.array([s["yaw_right_deg"] for s in ok], dtype=float)
    ear = np.array([s.get("ear_mean", 0.0) for s in ok], dtype=float)
    mar = np.array([s.get("mar", 0.0) for s in ok], dtype=float)
    base = float(np.median(yaw[: max(1, min(3, len(yaw)))]))
    ear_hi = float(np.percentile(ear, 90)) if len(ear) else 0.0
    dips = 0
    if len(ear) >= 5 and ear_hi > 0.15:
        below = ear < 0.6 * ear_hi
        dips = int(np.sum(below[1:] & ~below[:-1]) + (1 if below[0] else 0))
    return {"n": len(ok), "yaw_baseline": round(base, 2), "yaw_min": round(float(yaw.min()), 2), "yaw_max": round(float(yaw.max()), 2),
            "turn_right_deg": round(float(yaw.max() - base), 2), "turn_left_deg": round(float(base - yaw.min()), 2),
            "ear_max": round(float(ear.max()), 4), "ear_median": round(float(np.median(ear)), 4), "ear_dips": dips,
            "mar_range": round(float(mar.max() - mar.min()), 4) if len(mar) else 0.0,
            "eye_dist_frac_max": round(float(max(s.get("eye_dist_frac", 0.0) for s in ok)), 4)}
