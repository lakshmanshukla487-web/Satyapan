"""Iris pattern encoding and matching (a classical Daugman-style pipeline), pure numpy/scipy.

HONESTY NOTE (also shown in the report): this compares the texture of the IRIS, the coloured ring around the pupil, from
ordinary visible-light webcam / phone photos. It is not a retina scan (the retina is at the back of the eye and cannot be
imaged by a camera) and it is not as reliable as near-infrared iris hardware. A match is supporting evidence; a clear
mismatch with good image quality is an indicator; poor quality is reported as "not enough detail", never as a failure.

Pipeline: iris circle (from MediaPipe iris landmarks) -> polar unwrap of the ring between 50 % and 95 % of the iris radius ->
use only the left and right sectors (the top and bottom are hidden by eyelids) -> mask out reflections -> local contrast
normalisation -> 2 log-Gabor filters along the angle -> 2 phase bits per sample -> fractional Hamming distance with a
small rotation search.
"""
from __future__ import annotations

import base64

import numpy as np
from scipy.ndimage import binary_erosion, map_coordinates, uniform_filter1d

N_R, N_T = 12, 96            # radial rings x angular samples
R_IN, R_OUT = 0.50, 0.95     # fraction of the iris radius that is sampled (skips the pupil edge and the limbus)
WAVELENGTHS = (12.0, 24.0)   # in angular samples
SECTOR_HALF_DEG = 50         # keep +-50 degrees around the horizontal axis (both sides)
MAX_SHIFT = 8                # +-8 samples = +-30 degrees of head tilt
MIN_BITS = 600               # fewer comparable bits than this => no verdict


def _sector_mask() -> np.ndarray:
    ang = (np.arange(N_T) + 0.5) * 360.0 / N_T
    d_right = np.minimum(ang, 360 - ang)
    d_left = np.abs(ang - 180)
    return (d_right <= SECTOR_HALF_DEG) | (d_left <= SECTOR_HALF_DEG)


SECTORS = _sector_mask()


def to_gray(rgb: np.ndarray) -> np.ndarray:
    """Red channel: melanin reflects red light best, so dark irises show most texture there (visible-light imaging)."""
    a = np.asarray(rgb)
    g = a[..., 0] if a.ndim == 3 else a
    return g.astype(np.float32)


def unwrap(gray: np.ndarray, cx: float, cy: float, r: float) -> tuple[np.ndarray, np.ndarray]:
    """Polar image (N_R x N_T) and validity mask (True = usable pixel)."""
    rr = (R_IN + (R_OUT - R_IN) * (np.arange(N_R) + 0.5) / N_R) * r
    th = 2 * np.pi * (np.arange(N_T) + 0.5) / N_T
    xs = cx + rr[:, None] * np.cos(th)[None, :]
    ys = cy - rr[:, None] * np.sin(th)[None, :]
    h, w = gray.shape
    inside = (xs >= 1) & (xs <= w - 2) & (ys >= 1) & (ys <= h - 2)
    pol = map_coordinates(gray, [ys, xs], order=1, mode="nearest")
    mask = inside & SECTORS[None, :] & (pol < 245)  # bright specular reflections carry no pattern
    return pol.astype(np.float32), mask


def normalise(pol: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Remove illumination: subtract each ring's mean and divide by its spread, over valid samples only."""
    out = np.zeros_like(pol)
    for i in range(pol.shape[0]):
        m = mask[i]
        if m.sum() < 8:
            continue
        v = pol[i, m]
        sd = float(v.std())
        out[i] = (pol[i] - float(v.mean())) / (sd if sd > 1e-3 else 1.0)
    return out


def _log_gabor(n: int, wavelength: float, sigma_ratio: float = 0.55) -> np.ndarray:
    f = np.fft.fftfreq(n)
    f0 = 1.0 / wavelength
    g = np.zeros(n)
    pos = f > 0
    g[pos] = np.exp(-(np.log(f[pos] / f0) ** 2) / (2 * np.log(sigma_ratio) ** 2))  # one-sided: analytic (complex) response
    return g


_FILTERS = [_log_gabor(N_T, w) for w in WAVELENGTHS]


def encode(pol: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """-> code bits (N_R, N_T, 4) uint8 and mask bits (N_R, N_T, 4) uint8."""
    norm = normalise(pol, mask)
    spec = np.fft.fft(norm, axis=1)
    bits, mbits = [], []
    # masked samples must not leak into neighbours: erode the mask a little along the angle
    safe = binary_erosion(mask, structure=np.ones((1, 5), bool), border_value=0)
    for g in _FILTERS:
        resp = np.fft.ifft(spec * g[None, :], axis=1)
        bits += [resp.real > 0, resp.imag > 0]
        mbits += [safe, safe]
    return np.stack(bits, axis=-1).astype(np.uint8), np.stack(mbits, axis=-1).astype(np.uint8)


def hamming(c1, m1, c2, m2, max_shift: int = MAX_SHIFT) -> tuple[float, int]:
    """Smallest fractional Hamming distance over small rotations, and how many bits were compared."""
    best, best_n = 1.0, 0
    for s in range(-max_shift, max_shift + 1):
        c2s, m2s = np.roll(c2, s, axis=1), np.roll(m2, s, axis=1)
        valid = (m1 & m2s).astype(bool)
        n = int(valid.sum())
        if n < MIN_BITS:
            continue
        hd = float(((c1 ^ c2s)[valid]).sum()) / n
        if hd < best:
            best, best_n = hd, n
    return (best, best_n) if best_n else (1.0, 0)


def quality(gray: np.ndarray, cx: float, cy: float, r: float, mask: np.ndarray) -> dict:
    """Is there enough detail to say anything? diameter in pixels, sharpness, usable share of the iris."""
    h, w = gray.shape
    x0, x1 = int(max(0, cx - r)), int(min(w, cx + r + 1))
    y0, y1 = int(max(0, cy - r)), int(min(h, cy + r + 1))
    roi = gray[y0:y1, x0:x1]
    if roi.size < 64:
        return {"diameter_px": round(2 * r, 1), "sharpness": 0.0, "usable_fraction": 0.0, "score": 0.0}
    lap = roi[1:-1, 1:-1] * 4 - roi[:-2, 1:-1] - roi[2:, 1:-1] - roi[1:-1, :-2] - roi[1:-1, 2:]
    sharp = float(lap.var())
    usable = float(mask[:, SECTORS].mean()) if SECTORS.any() else 0.0
    diam = 2 * r
    score = min(1.0, diam / 60.0) * min(1.0, usable / 0.7) * min(1.0, sharp / 40.0)
    return {"diameter_px": round(diam, 1), "sharpness": round(sharp, 1), "usable_fraction": round(usable, 3), "score": round(score, 3)}


MIN_DIAMETER_PX = 36.0
MIN_QUALITY_SCORE = 0.25


def enrol_eye(rgb: np.ndarray, circle: dict) -> dict | None:
    """Template for one eye, or None when the image is not good enough (reason in the returned dict's 'quality')."""
    gray = to_gray(rgb)
    pol, mask = unwrap(gray, circle["cx"], circle["cy"], circle["r"])
    q = quality(gray, circle["cx"], circle["cy"], circle["r"], mask)
    q["usable"] = bool(q["diameter_px"] >= MIN_DIAMETER_PX and q["score"] >= MIN_QUALITY_SCORE)
    code, m = encode(pol, mask)
    return {"code": code, "mask": m, "quality": q}


# ---- storage -------------------------------------------------------------------------------------------------------

def pack(t: dict) -> dict:
    return {"code": base64.b64encode(np.packbits(t["code"]).tobytes()).decode(), "mask": base64.b64encode(np.packbits(t["mask"]).tobytes()).decode(),
            "shape": list(t["code"].shape), "quality": t["quality"]}


def unpack(d: dict) -> dict:
    shape = tuple(d["shape"])
    n = int(np.prod(shape))

    def un(s):
        return np.unpackbits(np.frombuffer(base64.b64decode(s), dtype=np.uint8))[:n].reshape(shape)
    return {"code": un(d["code"]), "mask": un(d["mask"]), "quality": d["quality"]}


def compare(ref: dict, probe: dict) -> dict:
    hd, n = hamming(ref["code"], ref["mask"], probe["code"], probe["mask"])
    return {"hd": round(hd, 4), "bits": n}
