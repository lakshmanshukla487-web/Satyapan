"""Server-side speech-to-text for the 'say three words' challenge.

The browser's own speech recognition is unreliable (missing in several browsers, often silent while the camera holds the
microphone, and it sends audio to the browser vendor). The customer's page therefore records the phrase as WAV and the server
transcribes it here with Whisper, on the CPU, in memory only.

Like the detectors, the model is loaded ONCE (at server start when PRELOAD_MODELS=true, else on first use) from MODEL_DIR/speech
or the Hugging Face cache, and never downloaded while the server runs: `python scripts/download_models.py --speech`. A failed load
is remembered and reported, not retried per request."""
import logging
import threading
from pathlib import Path

import numpy as np

from apps.core.runtime import get_runtime

log = logging.getLogger("satyapan.speech")
SAMPLE_RATE = 16_000
MIN_RMS = 1e-3  # quieter than this is silence: Whisper is not run (it invents text on silence)

_lock = threading.Lock()
_model = None  # (processor, model) once loaded
_error: str | None = None


def load() -> str | None:
    """Load the model once. -> None when ready, otherwise an error code (DISABLED, DEPENDENCY_MISSING, MODEL_NOT_DOWNLOADED, ...)."""
    global _model, _error
    with _lock:
        if _model is not None or _error is not None:
            return _error
        cfg = get_runtime().settings
        if not cfg.enable_speech_check:
            _error = "DISABLED"
            return _error
        try:
            import torch
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
        except ImportError:
            _error = "DEPENDENCY_MISSING"
            return _error
        local = Path(cfg.model_dir) / "speech"
        src, kw = (str(local), {}) if local.is_dir() else (cfg.speech_model_repo, {"local_files_only": True})  # never download at runtime
        try:
            proc = WhisperProcessor.from_pretrained(src, **kw)
            model = WhisperForConditionalGeneration.from_pretrained(src, **kw).to("cpu").eval()
        except OSError:
            _error = "MODEL_NOT_DOWNLOADED"
            log.warning("speech model %s not found: run `python scripts/download_models.py --speech`", src)
            return _error
        except Exception as e:  # noqa: BLE001 - a broken model must not break the challenge, only make it unavailable
            _error = "LOAD_FAILED"
            log.error("speech model failed to load: %s: %s", type(e).__name__, e)
            return _error
        torch.set_grad_enabled(False)
        model.generation_config.forced_decoder_ids = model.config.forced_decoder_ids = None  # language and task go to generate() instead
        _model = (proc, model)
        return None


def _resample(wave: np.ndarray, sr: int) -> np.ndarray:
    if sr == SAMPLE_RATE or len(wave) == 0:
        return wave.astype(np.float32)
    n = int(round(len(wave) * SAMPLE_RATE / sr))
    return np.interp(np.linspace(0, len(wave) - 1, n), np.arange(len(wave)), wave).astype(np.float32)


def transcribe(wave: np.ndarray, sr: int) -> tuple[str | None, str]:
    """-> (text, status). status is 'ok' (text may be empty), 'silent', or the load error code (text None)."""
    err = load()
    if err:
        return None, err
    wave = _resample(np.asarray(wave, dtype=np.float32), sr)
    if len(wave) == 0 or float(np.sqrt(np.mean(wave**2))) < MIN_RMS:
        return "", "silent"
    import torch
    proc, model = _model
    inp = proc(wave, sampling_rate=SAMPLE_RATE, return_tensors="pt", return_attention_mask=True)
    with torch.inference_mode():
        ids = model.generate(inp.input_features, attention_mask=inp.attention_mask, language="en", task="transcribe", max_new_tokens=48)
    return proc.batch_decode(ids, skip_special_tokens=True)[0].strip(), "ok"
