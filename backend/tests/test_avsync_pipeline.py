"""Lip-sync clip preparation (apps/avsync/pipeline.py): the face track that turns uploaded frames into SyncNet's 224x224 crops."""
import numpy as np

from apps.avsync import pipeline


def _face_everywhere(rgb):
    return [{"box": (100.0, 80.0, 200.0, 240.0)}]


def test_a_face_in_every_frame_is_full_coverage_even_though_only_every_third_frame_is_checked():
    """Regression: coverage was measured over ALL frames while the detector only ran on every third one, so it could never exceed
    0.34 < MIN_FACE_COVERAGE and every real clip was refused as NO_FACE (lip sync never ran)."""
    frames = [np.zeros((480, 480, 3), np.uint8) for _ in range(100)]
    crops, info = pipeline.crop_faces(frames, _face_everywhere)
    assert crops is not None and len(crops) == 100 and crops[0].shape == (224, 224, 3)
    assert info["face_coverage"] == 1.0


def test_too_few_faces_is_still_refused():
    frames = [np.zeros((480, 480, 3), np.uint8) for _ in range(90)]
    calls = {"n": 0}

    def sometimes(rgb):
        calls["n"] += 1
        return _face_everywhere(rgb) if calls["n"] % 3 == 0 else []  # a face in one of three checked frames
    crops, info = pipeline.crop_faces(frames, sometimes)
    assert crops is None and info["face_coverage"] < pipeline.MIN_FACE_COVERAGE


def test_frames_are_put_on_the_25_fps_grid():
    times = [0.0, 0.033, 0.066, 0.1, 0.133]
    assert list(pipeline.resample_to_grid(times, 5, 0.16)) == [0, 1, 2, 4]  # 0, 40, 80, 120 ms -> nearest frame (120 ms: 133 is closer than 100)
