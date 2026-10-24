"""The face deepfake detector's preprocessing: square face crop, frames that must not be scored, flip averaging. No model weights
needed: the face engine, image processor and classifier are replaced by small fakes."""
import numpy as np
import pytest
from PIL import Image

from apps.biometrics import faces
from tests.conftest import make_settings


class FakeEngine:
    def __init__(self, boxes):
        self.boxes = boxes

    def detect(self, rgb):
        return [{"box": b, "score": 0.9} for b in self.boxes]


@pytest.fixture
def engine(monkeypatch):
    def use(boxes):
        monkeypatch.setattr(faces, "engine_or_none", lambda model_dir: FakeEngine(boxes))
    return use


def test_square_crop_is_centred_on_the_face(engine):
    engine([(200, 100, 100, 120)])  # x, y, w, h: face 120 px tall
    rgb = np.zeros((480, 640, 3), np.uint8)
    crop, info = faces.square_face_crop(rgb, "", margin=0.25, min_face_px=64)
    assert crop.shape == (180, 180, 3) and info["face_px"] == 120 and info["crop"] == "face_square"


def test_crop_at_the_frame_edge_is_padded_not_shifted(engine):
    engine([(0, 0, 100, 100)])
    rgb = np.random.default_rng(0).integers(0, 255, (480, 640, 3), np.uint8)
    crop, _ = faces.square_face_crop(rgb, "", margin=0.5, min_face_px=64)
    assert crop.shape == (200, 200, 3)
    assert np.array_equal(crop[50:150, 50:150], rgb[0:100, 0:100])  # the face stays in the centre of the crop


@pytest.mark.parametrize("boxes, reason", [([], "NO_FACE"), ([(10, 10, 40, 40)], "FACE_TOO_SMALL")])
def test_frames_without_a_usable_face_are_not_scored(engine, boxes, reason):
    engine(boxes)
    crop, info = faces.square_face_crop(np.zeros((480, 640, 3), np.uint8), "", margin=0.25, min_face_px=64)
    assert crop is None and info["reason"] == reason


def test_missing_face_engine_is_reported(monkeypatch):
    monkeypatch.setattr(faces, "engine_or_none", lambda model_dir: None)
    crop, info = faces.square_face_crop(np.zeros((480, 640, 3), np.uint8), "", margin=0.25, min_face_px=64)
    assert crop is None and info["reason"] == "FACE_ENGINE_UNAVAILABLE"


def _detector(flip: bool):
    """A ViTDetector whose 'model' says fake=0.8 for the image as given and 0.6 for its mirror image (told apart by a marker pixel)."""
    import torch
    from apps.visual.detectors import ViTDetector

    class Proc:
        def __call__(self, images, return_tensors):
            mark = [float(np.asarray(im)[0, 0, 0] > 128) for im in images]  # left-top pixel is white only in the original view
            return {"pixel_values": torch.tensor(mark).reshape(-1, 1)}

    class Model:
        config = type("C", (), {"id2label": {0: "Realism", 1: "Deepfake"}})()

        def __call__(self, pixel_values):
            p = torch.where(pixel_values[:, 0] > 0.5, torch.tensor(0.8), torch.tensor(0.6))
            return type("O", (), {"logits": torch.log(torch.stack([1 - p, p], 1))})()

    d = ViTDetector(make_settings(video_tta_flip=flip, video_crop_margin=0.25, video_min_face_px=64))
    d._proc, d._model, d._fake_idx, d._loaded = Proc(), Model(), 1, True
    return d


def _frame():
    rgb = np.zeros((480, 640, 3), np.uint8)
    rgb[100 - 30, 200 - 30] = 255  # the top-left pixel of the crop of the face box below (margin 0.25 of 120 px = 30)
    return Image.fromarray(rgb)


@pytest.mark.parametrize("flip, expected", [(False, 0.8), (True, 0.7)])
def test_flip_averaging(engine, flip, expected):
    engine([(200, 100, 120, 120)])
    r = _detector(flip).analyze(_frame())
    assert r["status"] == "ok" and r["score"] == pytest.approx(expected, abs=1e-4) and r["label"] == "Deepfake"
    assert len(r["details"]["view_scores"]) == (2 if flip else 1)


def test_detector_refuses_a_frame_without_a_face(engine):
    engine([])
    r = _detector(True).analyze(_frame())
    assert r["status"] == "low_quality" and r["error_code"] == "NO_FACE" and r["score"] is None
