"""Safe in-memory decoding. Raw media is never written to disk."""
import io
from math import gcd

import numpy as np
from PIL import Image

from apps.core.errors import AppError
from apps.core.validation import sniff

Image.MAX_IMAGE_PIXELS = 25_000_000  # A04: refuse decompression bombs (4096 x 4096 is about 16.8 M pixels)


def decode_audio(data: bytes, max_seconds: int) -> tuple[np.ndarray, int]:
    import soundfile as sf
    sniff(data, "audio")
    try:
        info = sf.info(io.BytesIO(data))
        if info.duration > max_seconds:
            raise AppError("AUDIO_TOO_LONG", f"Audio exceeds the {max_seconds} s limit.", 422)
        wave, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    except AppError:
        raise
    except Exception:
        raise AppError("INVALID_MEDIA", "The audio could not be decoded.", 422)
    if wave.ndim > 1:
        wave = wave.mean(axis=1)
    return wave, int(sr)


def audio_warnings(wave: np.ndarray, sr: int) -> list[str]:
    w = []
    if len(wave) / sr < 1.0:
        w.append("SHORT_AUDIO")
    if len(wave) == 0 or float(np.sqrt(np.mean(wave**2))) < 1e-4:
        w.append("SILENT_AUDIO")
    return w


def resample(wave: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target:
        return wave
    from scipy.signal import resample_poly
    g = gcd(sr, target)
    return resample_poly(wave, target // g, sr // g).astype("float32")


def decode_image(data: bytes, max_dim: int) -> Image.Image:
    sniff(data, "image")
    try:
        img = Image.open(io.BytesIO(data))
        if max(img.size) > max_dim:
            raise AppError("IMAGE_TOO_LARGE", f"Image dimensions exceed {max_dim}px.", 422)
        img.load()
        return img.convert("RGB")
    except AppError:
        raise
    except Exception:
        raise AppError("INVALID_MEDIA", "The image could not be decoded.", 422)


def image_warnings(img: Image.Image) -> list[str]:
    w = []
    if min(img.size) < 64:
        w.append("SMALL_IMAGE")
    if float(np.asarray(img).mean()) < 20:
        w.append("DARK_IMAGE")
    return w
