import threading
from pathlib import Path

import numpy as np
from PIL import Image

from apps.signals.detector_base import BaseDetector, DetectorError, StubDetector
from apps.signals.hf import HFClassifier


class ViTDetector(HFClassifier):
    """Face deepfake classifier on single video frames. Default model: prithivMLmods/Deep-Fake-Detector-v2-Model, a ViT-base image
    classifier (Apache-2.0; labels Realism=0 / Deepfake=1) fine-tuned on ~140k face crops (the OpenForensics-based "Deepfake and real
    images" set). Its published 92 % accuracy is on a random split of that same pool, NOT on unseen data: see
    docs/VIDEO_DEEPFAKE_MODEL.md for what it achieves on independent datasets, and scripts/eval_video_model.py to measure it.

    Preprocessing follows the training data (square face crops, squashed to 224x224):
      1. the largest face is found (OpenCV YuNet); a frame without a usable face is NOT scored (low_quality NO_FACE /
         FACE_TOO_SMALL), because the model has never seen anything but faces and its score on a whole room means nothing;
      2. a SQUARE crop centred on the face, VIDEO_CROP_MARGIN of the face size added on every side (reflect-padded at the edges);
      3. optionally the mirrored crop as well (VIDEO_TTA_FLIP): both are classified in one batch and the probabilities averaged.
    score = probability of the 'Deepfake' class. Single frames are noisy: the decision engine judges many frames over time."""
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

    def load(self) -> None:
        """Runs ONCE, at server start (warm_up): the ViT weights, the face detector every crop depends on, and one dummy inference
        so PyTorch's one-off setup is not paid by the first customer frame. After this only _infer runs."""
        import torch
        from apps.biometrics.faces import get_engine
        super().load()
        get_engine(self.settings.model_dir)  # raises DetectorError (MODEL_NOT_DOWNLOADED) without the YuNet file: no crop, no score
        with torch.inference_mode():
            self._model(**self._inputs([Image.new("RGB", (224, 224))] * (2 if self.settings.video_tta_flip else 1)))

    def _inputs(self, media):
        return self._proc(images=media, return_tensors="pt")

    def _infer(self, media, metadata):
        import torch
        from apps.biometrics.faces import square_face_crop
        cfg = self.settings
        crop, info = square_face_crop(np.asarray(media), cfg.model_dir, cfg.video_crop_margin, cfg.video_min_face_px)
        if crop is None:
            return self.result("low_quality", error_code=info["reason"], details=info)
        views = [Image.fromarray(np.ascontiguousarray(crop))]
        if cfg.video_tta_flip:
            views.append(views[0].transpose(Image.FLIP_LEFT_RIGHT))
        if self._fake_idx is None:  # label map ambiguous: refuse to pick a class
            return self.result("error", error_code="LABEL_MAPPING_UNKNOWN", details=info)
        inputs = {k: v.to("cpu") for k, v in self._inputs(views).items()}
        with torch.inference_mode():
            probs = torch.softmax(self._model(**inputs).logits, -1)[:, self._fake_idx].tolist()
        score = float(sum(probs) / len(probs))
        label = self._model.config.id2label[self._fake_idx] if score >= 0.5 else next(str(v) for k, v in self._model.config.id2label.items() if int(k) != self._fake_idx)
        info.update(view_scores=[round(p, 4) for p in probs], tta_flip=cfg.video_tta_flip)
        return self.result("ok", score, label=str(label), details=info)


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
