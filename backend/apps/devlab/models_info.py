"""What the test lab can honestly say about each detector: enabled, loaded, weights on disk, dependencies, and how to read its
score. Availability is taken from the detector's own load attempt, never from the mere presence of a configuration file."""
from __future__ import annotations

import hashlib
import importlib.util
from functools import lru_cache
from pathlib import Path

from apps.devlab.media import AUDIO, IMAGE, VIDEO, ffmpeg_path

# The real detector that evaluates each media type (the same objects the live pipeline uses).
DETECTOR_FOR = {IMAGE: "vit", VIDEO: "vit", AUDIO: "audio"}
LISTED = ("vit", "audio", "xception")
WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")

INFO = {
    "vit": {"label": "Face deepfake classifier (ViT)", "media": [IMAGE, VIDEO], "local_dir": "video",
            "score_meaning": "Softmax probability of the model's 'fake' class for the largest face in the image or frame (cropped with the "
                             "OpenCV face detector when it is installed, otherwise the whole frame). Uncalibrated; not a probability of fraud.",
            "video": "Videos are tested by sampling frames evenly over the whole clip and scoring each frame; the video score is the "
                     "aggregate you choose (default: median, i.e. 'fake' when at least half of the scored frames reach the threshold, "
                     "the same majority rule the live policy uses for a RED video family)."},
    "audio": {"label": "Voice anti-spoofing (fine-tuned wav2vec2)", "media": [AUDIO], "local_dir": "audio",
              "score_meaning": "Mean softmax probability of the 'fake' class over 6 s windows (3 s hop) of 16 kHz mono audio; the worst window "
                               "is reported next to it. Uncalibrated; not a probability of fraud."},
    "xception": {"label": "Alternative visual classifier (Xception)", "media": [], "local_dir": "",
                 "score_meaning": "Not integrated: it never produces a score (its weight format and preprocessing were never verified)."},
}


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def dependencies() -> dict:
    return {"torch": _has("torch"), "transformers": _has("transformers"), "opencv": _has("cv2"), "soundfile": _has("soundfile"),
            "mediapipe": _has("mediapipe"), "ffmpeg": ffmpeg_path() is not None}


def _model_dir(cfg) -> Path:
    p = Path(cfg.model_dir)
    if not p.is_absolute():
        from satyapan.conf import BASE_DIR
        p = BASE_DIR / p
    return p


def weights(cfg, name: str) -> dict:
    """Where the weights would be loaded from, and whether they are there. Same search order as apps/signals/hf.py."""
    info = INFO.get(name, {})
    if not info.get("local_dir"):
        return {"location": None, "present": False, "file": None}
    local = _model_dir(cfg) / info["local_dir"]
    if local.is_dir():
        for fn in WEIGHT_FILES:
            f = local / fn
            if f.is_file():
                st = f.stat()
                return {"location": f"MODEL_DIR/{info['local_dir']}", "present": True, "file": fn, "size_bytes": st.st_size, "config_present": (local / "config.json").is_file()}
        return {"location": f"MODEL_DIR/{info['local_dir']}", "present": False, "file": None, "config_present": (local / "config.json").is_file(),
                "hint": f"Copy model.safetensors into MODEL_DIR/{info['local_dir']}/ (a config file alone is not a model)."}
    if name == "vit":  # no local folder: the Hugging Face cache (downloaded by scripts/download_models.py --video)
        repo = cfg.video_model_repo
        hub = Path(cfg.hf_home) / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots"
        if not hub.is_absolute():
            from satyapan.conf import BASE_DIR
            hub = BASE_DIR / hub
        for snap in sorted(hub.glob("*")) if hub.is_dir() else []:
            for fn in WEIGHT_FILES:
                if (snap / fn).is_file():
                    return {"location": "HF_HOME cache", "present": True, "file": fn, "size_bytes": (snap / fn).stat().st_size}
        return {"location": "HF_HOME cache", "present": False, "file": None, "hint": "Run: python scripts/download_models.py --video"}
    return {"location": f"MODEL_DIR/{info['local_dir']}", "present": False, "file": None, "hint": f"Copy the model into MODEL_DIR/{info['local_dir']}/."}


@lru_cache(maxsize=16)
def _fingerprint(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def model_version(cfg, name: str) -> str:
    """A short fingerprint that changes when the weights file changes (name, size, modification time), so results from two
    different model versions are never mistaken for each other. Computed from file metadata (hashing a 1 GB file per call
    would be too slow)."""
    w = weights(cfg, name)
    if not w.get("present"):
        return ""
    local = _model_dir(cfg) / INFO[name]["local_dir"] / (w.get("file") or "")
    mtime = local.stat().st_mtime if local.is_file() else 0
    repo = cfg.video_model_repo if name == "vit" else ""
    key = "|".join(str(x) for x in (name, w.get("size_bytes"), mtime, repo))
    return f"{w['file']}:{_fingerprint(key)}"


def status(rt) -> dict:
    cfg = rt.settings
    out = []
    for name in LISTED:
        det = rt.registry.get(name)
        info = INFO[name]
        h = det.health() if det is not None else {"name": name, "state": "disabled", "error_code": None, "model_id": None}
        w = weights(cfg, name)
        state = h["state"]
        if det is None:
            inference = "disabled"
        elif state == "loaded":
            inference = "available"
        elif state == "unavailable":
            inference = "unavailable"
        else:
            inference = "not_loaded"  # PRELOAD_MODELS=false and nothing used it yet: it loads on first use (or fails then)
        row = {"name": name, "label": info["label"], "media_types": info["media"], "enabled": det is not None, "state": state, "inference": inference,
               "error_code": h.get("error_code"), "load_problem": h.get("load_problem"), "model_id": h.get("model_id"), "model_version": model_version(cfg, name),
               "weights": w, "threshold": getattr(det, "threshold", None) if det is not None else None,
               "score_kind": getattr(det, "score_kind", None) if det is not None else None, "score_meaning": info["score_meaning"]}
        if "video" in info:
            row["video_method"] = info["video"]
        out.append(row)
    return {"detectors": out, "dependencies": dependencies(), "detector_for_media": DETECTOR_FOR,
            "limits": {"max_upload_mb": cfg.max_upload_mb, "max_items_per_job": cfg.devlab_max_items_per_job, "max_job_mb": cfg.devlab_max_job_mb,
                       "max_video_seconds": cfg.devlab_max_video_seconds, "max_audio_seconds": cfg.devlab_max_audio_seconds,
                       "video_frames_default": cfg.devlab_video_frames, "max_video_frames": 64, "retention_hours": cfg.devlab_retention_hours,
                       "max_image_dimension": cfg.max_image_dimension},
            "preload_models": cfg.preload_models}
