import threading
from pathlib import Path

import numpy as np
from PIL import Image

from apps.signals.detector_base import BaseDetector, DetectorError, StubDetector
from apps.signals.hf import HFClassifier


class ViTDetector(HFClassifier):
    """Video deepfake detection on single frames (the 'video' model). Default: prithivMLmods/Deep-Fake-Detector-v2-Model, a
    ViT-base image classifier (Apache-2.0, free for commercial use; labels Realism / Deepfake). Change it with VIDEO_MODEL_REPO
    (any transformers image classifier with a real/fake label map) or put a copy in MODEL_DIR/video.

    The frame is first cropped to the largest face (+30 % margin) with the OpenCV face detector, because the classifier was
    trained on face images. Scores of single frames are noisy, so the decision engine judges many frames over time, never one.
    Accuracy on unseen generators is limited and NOT validated for this deployment."""
    name, signal_type = "vit", "visual_deepfake"
    local_dirname, kind = "video", "image"

    def __init__(self, settings):
        super().__init__(settings)
        self.repo = settings.video_model_repo

    def fake_index_override(self):
        i = self.settings.video_fake_label_index
        return i if i >= 0 else None

    @property
    def threshold(self):
        return self.settings.video_flag_threshold

    def _inputs(self, media):
        return self._proc(images=media, return_tensors="pt")

    def _infer(self, media, metadata):
        from apps.biometrics.faces import crop_face
        crop, info = crop_face(np.asarray(media), self.settings.model_dir)
        out = super()._infer(Image.fromarray(np.ascontiguousarray(crop)), metadata)
        out["details"].update(info)
        return out


class XceptionDetector(StubDetector):
    """Not integrated (weight format and preprocessing were never inspected), so it never produces a score."""
    name, signal_type, model_id, reason = "xception", "visual_deepfake", "Arman176/Xception5o", "NOT_INTEGRATED"


class LandmarkDetector(BaseDetector):
    """MediaPipe Face Landmarker (478 points incl. iris). Reports the server's OWN measurements of the face in each frame: head
    turn, eye openness, mouth opening, closeness. It produces no spoof score: landmarks alone prove nothing about authenticity.
    Needs MODEL_DIR/face_landmarker.task."""
    name, signal_type, model_id, score_kind = "landmarks", "landmarks", "mediapipe/face_landmarker", "heuristic_measurement"

    def load(self) -> None:
        import mediapipe as mp  # noqa: F401
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision
        path = Path(self.settings.model_dir) / "face_landmarker.task"
        if not path.is_file():
            raise DetectorError("MODEL_NOT_DOWNLOADED")
        opts = vision.FaceLandmarkerOptions(base_options=mpp.BaseOptions(model_asset_path=str(path)), num_faces=2)
        self._lm = vision.FaceLandmarker.create_from_options(opts)
        self._infer_lock = threading.Lock()

    def landmarks(self, rgb) -> tuple[int, np.ndarray | None]:
        """(number of faces, (478,3) array of the first face or None). Thread-safe; requires ensure_loaded()."""
        import mediapipe as mp
        arr = np.ascontiguousarray(np.asarray(rgb, dtype=np.uint8))
        with self._infer_lock:
            res = self._lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=arr))
        n = len(res.face_landmarks)
        if n == 0:
            return 0, None
        return n, np.array([[p.x, p.y, p.z] for p in res.face_landmarks[0]], dtype=np.float64)

    def _infer(self, media, metadata):
        from apps.biometrics import geometry
        arr = np.asarray(media)
        n, lm = self.landmarks(arr)
        if n != 1:
            return self.result("low_quality", error_code="NO_FACE" if n == 0 else "MULTIPLE_FACES", details={"face_count": n})
        h, w = arr.shape[:2]
        m = geometry.measure(lm, w, h)
        if not m.get("ok"):
            return self.result("low_quality", error_code="NO_FACE", details={"face_count": n})
        m.pop("ok", None)
        return self.result("ok", None, details={"face_count": 1, "landmark_count": len(lm), "face_area_fraction": round(m["face_w_frac"] * m["face_h_frac"], 3), "pose": m})
