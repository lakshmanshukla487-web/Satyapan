"""Face detection (OpenCV YuNet, MIT/Apache) and face recognition (OpenCV SFace, Apache-2.0), loaded once per process.

Files (see scripts/download_models.py --faces), in MODEL_DIR:
  face_detection_yunet_2023mar.onnx      face_recognition_sface_2021dec.onnx
Same-person decision: cosine similarity >= FACE_COSINE_THRESHOLD (0.363 is the value published with SFace). A face swap that
copies the reference person's identity WOULD match; face match defends against a different person, not against a swap.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

from apps.signals.detector_base import DetectorError

log = logging.getLogger("satyapan.faces")
DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNISER_FILE = "face_recognition_sface_2021dec.onnx"
MAX_DETECT_SIDE = 960
CLOSE_UP_SIDE = 480    # second pass for close-ups: the padded image is shrunk to this size ...
CLOSE_UP_PAD = 0.25    # ... after adding a border of this share of the image size on every side


class FaceEngine:
    def __init__(self, model_dir: str):
        import cv2
        d = Path(model_dir)
        det, rec = d / DETECTOR_FILE, d / RECOGNISER_FILE
        if not det.is_file() or not rec.is_file():
            raise DetectorError("MODEL_NOT_DOWNLOADED")
        self.cv2 = cv2
        self._det = cv2.FaceDetectorYN.create(str(det), "", (320, 320), 0.85, 0.3, 50)
        self._rec = cv2.FaceRecognizerSF.create(str(rec), "")
        self._lock = threading.Lock()  # OpenCV DNN objects are not safe to share between threads

    def detect(self, rgb: np.ndarray) -> list[dict]:
        """Faces sorted by size (largest first): {box:(x,y,w,h) in original pixels, score, row} .

        YuNet misses faces that fill the picture (measured: 13 of 60 close-up 1024 px portraits found as-is, 60 of 60 with a border),
        and a close-up is exactly what the start photo and the eye scan ask for. So when the first pass finds nothing, the image is
        shrunk and given a border, and detection runs again; boxes and landmarks are mapped back to the original pixels."""
        h, w = rgb.shape[:2]
        out = self._detect_at(rgb, min(1.0, MAX_DETECT_SIDE / max(h, w)), 0)
        if not out:
            pad = int(max(h, w) * CLOSE_UP_PAD)
            out = self._detect_at(rgb, CLOSE_UP_SIDE / (max(h, w) + 2 * pad), pad)
        out.sort(key=lambda f: -(f["box"][2] * f["box"][3]))
        return out

    def _detect_at(self, rgb: np.ndarray, scale: float, pad: int) -> list[dict]:
        cv2 = self.cv2
        img = np.pad(rgb, ((pad, pad), (pad, pad), (0, 0)), mode="constant") if pad else rgb
        h, w = img.shape[:2]
        small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA) if scale < 1 else img
        bgr = cv2.cvtColor(np.ascontiguousarray(small), cv2.COLOR_RGB2BGR)
        with self._lock:
            self._det.setInputSize((bgr.shape[1], bgr.shape[0]))
            _, rows = self._det.detect(bgr)
        oh, ow = rgb.shape[:2]
        out = []
        for r in (rows if rows is not None else []):
            r = np.array(r, dtype=np.float32)
            r_full = r.copy()
            r_full[:14] = r[:14] / min(scale, 1.0)
            r_full[[0, 1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]] -= pad  # x, y of the box and of the 5 landmarks (w, h unchanged)
            x, y, bw, bh = (float(v) for v in r_full[:4])
            x0, y0, x1, y1 = max(0.0, x), max(0.0, y), min(float(ow), x + bw), min(float(oh), y + bh)
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue  # a "face" in the added border only
            out.append({"box": (x, y, bw, bh), "score": float(r[14]), "row": r_full})
        return out

    def embed(self, rgb: np.ndarray, face: dict) -> np.ndarray:
        cv2 = self.cv2
        bgr = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2BGR)
        with self._lock:
            aligned = self._rec.alignCrop(bgr, face["row"])
            feat = self._rec.feature(aligned)
        v = np.asarray(feat, dtype=np.float32).reshape(-1)
        return v


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, dtype=np.float64).ravel(), np.asarray(b, dtype=np.float64).ravel()
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return 0.0 if d < 1e-9 else float(np.dot(a, b) / d)


def face_quality(rgb: np.ndarray, face: dict) -> dict:
    """Size, brightness and sharpness of the face region: poor quality means 'cannot say', never 'mismatch'."""
    h, w = rgb.shape[:2]
    x, y, bw, bh = face["box"]
    x0, y0, x1, y1 = int(max(0, x)), int(max(0, y)), int(min(w, x + bw)), int(min(h, y + bh))
    roi = rgb[y0:y1, x0:x1].astype(np.float32)
    if roi.size == 0:
        return {"usable": False, "issues": ["NO_FACE_REGION"]}
    gray = roi.mean(axis=2)
    lap = gray[1:-1, 1:-1] * 4 - gray[:-2, 1:-1] - gray[2:, 1:-1] - gray[1:-1, :-2] - gray[1:-1, 2:]
    q = {"face_px": int(min(bw, bh)), "brightness": round(float(gray.mean()), 1), "sharpness": round(float(lap.var()), 1), "detector_score": round(face["score"], 3)}
    issues = []
    if min(bw, bh) < 80:
        issues.append("FACE_TOO_SMALL")
    if q["brightness"] < 45:
        issues.append("TOO_DARK")
    if q["brightness"] > 225:
        issues.append("TOO_BRIGHT")
    if q["sharpness"] < 12:
        issues.append("BLURRY")
    q["issues"], q["usable"] = issues, not issues
    return q


_engine: FaceEngine | None = None
_engine_error: str | None = None
_lock = threading.Lock()


def get_engine(model_dir: str) -> FaceEngine:
    """Load once. Raises DetectorError (sticky) if the models are missing."""
    global _engine, _engine_error
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        if _engine_error:
            raise DetectorError(_engine_error)
        try:
            _engine = FaceEngine(model_dir)
        except DetectorError as e:
            _engine_error = e.code
            raise
        except ImportError:
            _engine_error = "DEPENDENCY_MISSING"
            raise DetectorError(_engine_error)
        except Exception as e:  # noqa: BLE001
            log.warning("face engine failed to load: %s", type(e).__name__)
            _engine_error = "LOAD_FAILED"
            raise DetectorError(_engine_error)
        return _engine


def engine_or_none(model_dir: str) -> FaceEngine | None:
    try:
        return get_engine(model_dir)
    except DetectorError:
        return None


def square_face_crop(rgb: np.ndarray, model_dir: str, margin: float, min_face_px: int) -> tuple[np.ndarray | None, dict]:
    """Square crop centred on the largest face, `margin` x face size added on every side (reflect-padded where it leaves the
    frame), for the video deepfake model. -> (crop, info), or (None, info with reason FACE_ENGINE_UNAVAILABLE / NO_FACE /
    FACE_TOO_SMALL) when the frame must not be scored."""
    eng = engine_or_none(model_dir)
    if eng is None:
        return None, {"crop": "none", "reason": "FACE_ENGINE_UNAVAILABLE"}
    faces = eng.detect(rgb)
    if not faces:
        return None, {"crop": "none", "reason": "NO_FACE"}
    x, y, w, h = faces[0]["box"]
    face_px = int(round(max(w, h)))
    info = {"crop": "face_square", "faces_in_frame": len(faces), "face_px": face_px, "margin": margin}
    if face_px < min_face_px:
        return None, {**info, "crop": "none", "reason": "FACE_TOO_SMALL"}
    H, W = rgb.shape[:2]
    side = int(round(face_px * (1 + 2 * margin)))
    x0, y0 = int(round(x + w / 2 - side / 2)), int(round(y + h / 2 - side / 2))
    pad = max(0, -x0, -y0, x0 + side - W, y0 + side - H)
    if pad:
        rgb = np.pad(rgb, ((pad, pad), (pad, pad), (0, 0)), mode="reflect" if pad < min(H, W) else "edge")
    return rgb[y0 + pad:y0 + pad + side, x0 + pad:x0 + pad + side], info
