"""Turns an uploaded clip (JPEG frames with timestamps + 16 kHz audio) into what SyncNet expects: 25 fps 224x224 BGR face crops
and a matching waveform. Crop geometry follows the reference implementation (crop scale 0.4 around the detected face, shifted
down so the chin and lips are inside)."""
from __future__ import annotations

import numpy as np

FPS = 25
CROP_SCALE = 0.4
MIN_FACE_COVERAGE = 0.7   # share of grid frames in which a face was found (directly or by interpolation of neighbours)


def resample_to_grid(times: list[float], n_frames: int, duration: float) -> np.ndarray:
    """Index of the nearest uploaded frame for every 40 ms step of the clip."""
    grid = np.arange(0.0, duration, 1.0 / FPS)
    t = np.asarray(times[:n_frames], dtype=np.float64)
    idx = np.abs(t[None, :] - grid[:, None]).argmin(axis=1)
    return idx


def _box_track(boxes: list, n: int) -> tuple[np.ndarray, float]:
    """Fill gaps (None) by linear interpolation and smooth with a short moving average. -> (n,3) of x,y,half-size, coverage."""
    arr = np.full((n, 3), np.nan)
    for i, b in enumerate(boxes):
        if b is not None:
            x, y, w, h = b
            arr[i] = (x + w / 2.0, y + h / 2.0, max(w, h) / 2.0)
    have = ~np.isnan(arr[:, 0])
    coverage = float(have.mean()) if n else 0.0
    if have.sum() < 2:
        return arr, coverage
    xs = np.arange(n)
    for c in range(3):
        arr[:, c] = np.interp(xs, xs[have], arr[have, c])
    k = 5
    pad = np.pad(arr, ((k // 2, k // 2), (0, 0)), mode="edge")
    arr = np.stack([np.convolve(pad[:, c], np.ones(k) / k, mode="valid") for c in range(3)], axis=1)
    return arr, coverage


def crop_faces(frames_rgb: list[np.ndarray], detect, stride: int = 3) -> tuple[list[np.ndarray] | None, dict]:
    """frames_rgb: the 25 fps grid frames. detect(rgb) -> list of {'box':(x,y,w,h)}. Returns BGR 224x224 crops (or None)."""
    import cv2
    n = len(frames_rgb)
    boxes: list = [None] * n
    for i in range(0, n, stride):
        faces = detect(frames_rgb[i])
        if faces:
            x, y, w, h = faces[0]["box"]
            boxes[i] = (x, y - 0.1 * h, w, h * 1.15)  # the detector box starts at the brows: add the forehead and chin
    track, coverage = _box_track(boxes, n)
    info = {"face_coverage": round(coverage, 3), "frames": n}
    if coverage < MIN_FACE_COVERAGE or np.isnan(track).any():
        return None, info
    crops = []
    for rgb, (cx, cy, bs) in zip(frames_rgb, track):
        bsi = int(bs * (1 + 2 * CROP_SCALE))
        padded = np.pad(rgb, ((bsi, bsi), (bsi, bsi), (0, 0)), mode="constant", constant_values=110)
        my, mx = cy + bsi, cx + bsi
        face = padded[int(my - bs):int(my + bs * (1 + 2 * CROP_SCALE)), int(mx - bs * (1 + CROP_SCALE)):int(mx + bs * (1 + CROP_SCALE))]
        if face.size == 0:
            return None, info
        crops.append(cv2.cvtColor(cv2.resize(face, (224, 224)), cv2.COLOR_RGB2BGR))
    return crops, info


def speech_fraction(wave16k: np.ndarray) -> float:
    """Share of 40 ms steps that are clearly louder than the quiet floor of the clip (no speech => sync is undefined)."""
    step = 640
    n = len(wave16k) // step
    if n < 5:
        return 0.0
    e = np.sqrt((wave16k[: n * step].reshape(n, step) ** 2).mean(axis=1))
    floor = max(float(np.percentile(e, 10)), 1e-4)
    return float(np.mean(e > max(3 * floor, 0.01)))
