"""Application settings (everything that is not Django plumbing).

Values come from environment variables (and ``backend/.env``). Names are the upper-case form of the field,
e.g. ``AUDIO_FLAG_THRESHOLD``. Environment variables win over ``.env``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import get_type_hints

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _coerce(raw: str, typ: type):
    if typ is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return typ(raw)


@dataclass(frozen=True)
class AppSettings:
    app_env: str = "development"
    database_url: str = "sqlite:///./satyapan.db"
    frontend_origin: str = "http://localhost:5173"
    model_dir: str = "./models"
    hf_home: str = "./model_cache"
    enable_audio_detector: bool = True
    enable_vit_detector: bool = True
    enable_xception_detector: bool = False
    enable_mediapipe: bool = True
    enable_syncnet: bool = True  # audio-video (lip) sync; needs torch and the SyncNet checkpoint, otherwise reports unavailable
    inference_device: str = "cpu"
    max_upload_mb: int = 20
    max_audio_seconds: int = 15
    max_image_dimension: int = 4096
    max_concurrent_inferences: int = 2
    retain_raw_media: bool = False
    rate_limit_per_minute: int = 120
    challenge_ttl_seconds: int = 60
    policy_version: str = "v3"
    auth_token_ttl_minutes: int = 720
    allow_registration: bool = True  # customers may self-register; officers are only created by an admin command
    login_max_attempts: int = 10  # per IP + username, per 5 minutes
    # Demo thresholds: NOT scientifically validated or calibrated.
    audio_flag_threshold: float = 0.7
    vit_flag_threshold: float = 0.7
    min_usable_signals: int = 2

    # ---- added in the Django refactor -------------------------------------------------------------------------
    # Evidence families 1, 5 and 6 (new). They only add evidence when their data arrives, so they never change the
    # outcome of a session that did not send it.
    enable_integrity: bool = True
    enable_pulse: bool = True
    enable_provenance: bool = True
    pulse_min_snr_db: float = 2.0
    # Officer approval workflow: a generated challenge stays hidden from the customer until an officer releases it.
    require_challenge_approval: bool = True
    challenge_approval_timeout_seconds: int = 300  # how long a generated challenge may wait for an officer
    # KYC documents: uploaded and cross-checked before the live camera/microphone step can start.
    require_documents: bool = True
    max_document_mb: int = 8
    enable_document_ocr: bool = True  # only used if pytesseract + the Tesseract binary are installed

    # ---- v4 ---------------------------------------------------------------------------------------------------
    # Model lifecycle: every enabled model is loaded ONCE, on the CPU, when the server process starts; after that only
    # inference runs (no reloading, no lazy loading on the first request).
    preload_models: bool = True
    torch_threads: int = 0  # 0 = let PyTorch choose; set e.g. 4 on a busy shared machine
    # Redis (optional). Empty = everything stays in-process (one server process). With a URL: shared rate limiting,
    # shared cache, shared WebSocket channel layer and cross-process inference back-pressure.
    redis_url: str = ""
    inference_queue_limit: int = 8  # requests waiting for a model beyond this get a quick 503 instead of piling up
    risk_publish_interval_seconds: float = -1.0  # min gap between live risk updates per session; -1 = 2 s with Redis, 0 without
    # Session approval: a customer's request for a verification goes to an officer first.
    require_session_approval: bool = True
    session_approval_timeout_seconds: int = 1800  # a request nobody approved within this time expires; the customer asks again
    # Continuous challenges: the customer is challenged until the session ends; this sets who releases them.
    challenge_auto_approve_default: bool = False
    min_session_seconds: int = 90  # shorter sessions cannot be GREEN (not enough time to observe the customer)
    min_challenges_answered: int = 3
    min_positive_families: int = 3  # independent checks that must positively confirm authenticity before a session can be GREEN
    min_coverage: float = 0.6  # share of the session's time windows that must contain video, for GREEN
    coverage_window_s: int = 15
    max_challenge_gap_s: int = 120  # a longer stretch with no new challenge request while the session runs is reported
    liveness_needs_server: bool = True  # GREEN needs at least one challenge confirmed by the server's own frames (needs the face landmarker model)
    # Decision engine: v2 = the original demo rules, v3 = quality-weighted multi-family policy.
    decision_policy: str = "v3"
    # Video deepfake model (any image-classification checkpoint with a real/fake label map). Default: Apache-2.0 ViT.
    video_model_repo: str = "prithivMLmods/Deep-Fake-Detector-v2-Model"
    video_fake_label_index: int = -1  # only if the model's label map is ambiguous: the class index that means "fake"
    video_flag_threshold: float = 0.7
    # Audio-video sync (SyncNet, VGG-M variant)
    syncnet_checkpoint: str = "syncnet/syncnet_v2.model"  # relative to MODEL_DIR
    syncnet_min_confidence: float = 4.0  # SyncNet confidence at or above this is "in sync"
    syncnet_bad_confidence: float = 1.0  # at or below this is "no audio-video relation found"
    syncnet_max_offset_frames: int = 6  # tolerated audio/video offset (25 fps frames)
    # Face identity: reference photo vs live frames (OpenCV YuNet detector + SFace recogniser, Apache-2.0 / MIT)
    enable_facematch: bool = True
    face_cosine_threshold: float = 0.363  # published SFace same-person threshold
    # Iris ("retina") scan: iris pattern matching on close-up eye images; visible-light webcams give weak evidence.
    enable_eyescan: bool = True
    # Fractional Hamming distance. On synthetic tests: same iris 0.10-0.35, different iris 0.35-0.50 (mean 0.44). NOT
    # calibrated on real webcam data: collect genuine/impostor pairs before relying on these numbers.
    iris_match_hd: float = 0.32  # at or below this = match
    iris_mismatch_hd: float = 0.40  # at or above this = mismatch (between the two = uncertain, never a fail)
    # Pipeline integrity: IP reputation and camera classification
    enable_ip_check: bool = True
    ip_trusted_proxy_hops: int = 0  # how many reverse proxies in front of Django add X-Forwarded-For (0 = trust none)
    ip_reputation_provider: str = ""  # "", "proxycheck" or "ipqs" (needs IP_REPUTATION_API_KEY); lists in backend/data/ip are always used
    ip_reputation_api_key: str = ""
    ip_reverse_dns: bool = False
    ip_data_dir: str = "./data/ip"
    # Live call (officer sees and talks to the customer): WebRTC. STUN finds the public address; TURN relays media when a
    # direct connection is impossible (strict firewalls). Leave TURN empty for same-network or demo use.
    enable_live_call: bool = True
    stun_urls: str = "stun:stun.l.google.com:19302"  # comma separated; the BROWSER contacts these, not this server
    turn_urls: str = ""
    turn_username: str = ""
    turn_credential: str = ""

    def __post_init__(self):
        if self.retain_raw_media:
            raise ImproperlyConfigured("RETAIN_RAW_MEDIA=true is not implemented; raw media is never stored.")

    @classmethod
    def from_env(cls, **overrides) -> "AppSettings":
        hints = get_type_hints(cls)
        values = {}
        for f in fields(cls):
            raw = os.environ.get(f.name.upper())
            if raw not in (None, ""):
                values[f.name] = _coerce(raw, hints[f.name])
        values.update(overrides)
        return cls(**values)
