"""Family 5, pulse (remote photoplethysmography) with the POS algorithm (Wang et al., IEEE TBME 2017).

Input: the mean R, G, B of a skin region of the face for every video frame (computed in the browser) and the frame
rate. This is SUPPORTING evidence only: published work shows high-quality deepfakes can inherit a valid pulse from
the driving video, and a missing pulse can be plain bad light. So it can corroborate, never accuse.
"""
import numpy as np
from scipy import signal

BAND_HZ = (0.7, 4.0)   # 42 - 240 beats per minute
MIN_SECONDS = 10.0
MIN_FPS = 10.0
MIN_BRIGHTNESS = 40.0  # mean pixel value (0-255) of the sampled skin region
MIN_VARIATION = 0.05   # temporal std of the green channel; a frozen picture has none


def pos_signal(rgb: np.ndarray, fps: float, win_s: float = 1.6) -> np.ndarray:
    """Plane-Orthogonal-to-Skin pulse signal. rgb: (N, 3)."""
    n, win = rgb.shape[0], int(round(win_s * fps))
    if n < win + 1:
        raise ValueError("trace shorter than one POS window")
    h = np.zeros(n)
    proj = np.array([[0.0, 1.0, -1.0], [-2.0, 1.0, 1.0]])
    for t in range(0, n - win + 1):
        c = rgb[t:t + win].T                       # 3 x win
        mean = c.mean(axis=1, keepdims=True)
        if np.any(mean <= 1e-6):
            continue
        s = proj @ (c / mean)                      # 2 x win
        sd1 = s[1].std()
        if sd1 < 1e-12:
            continue
        p = s[0] + (s[0].std() / sd1) * s[1]
        h[t:t + win] += p - p.mean()
    return h


def analyze_rgb(rgb: np.ndarray, fps: float, min_snr_db: float = 2.0) -> dict:
    """Returns {quality: good|poor, quality_reasons, pulse_present, bpm, snr_db, duration_s, mean_brightness}."""
    rgb = np.asarray(rgb, dtype=float)
    n = rgb.shape[0]
    duration = n / fps if fps else 0.0
    brightness = float(rgb.mean()) if n else 0.0
    reasons = []
    if fps < MIN_FPS:
        reasons.append("frame rate too low")
    if duration < MIN_SECONDS:
        reasons.append(f"clip shorter than {MIN_SECONDS:.0f} s")
    if brightness < MIN_BRIGHTNESS:
        reasons.append("face region too dark")
    if n and float(rgb[:, 1].std()) < MIN_VARIATION:
        reasons.append("picture is too still")
    out = {"quality": "good" if not reasons else "poor", "quality_reasons": reasons, "pulse_present": False, "bpm": None, "snr_db": None,
           "duration_s": round(duration, 1), "mean_brightness": round(brightness, 1)}
    if reasons:
        return out
    h = pos_signal(rgb, fps)
    b, a = signal.butter(3, [BAND_HZ[0] / (fps / 2), BAND_HZ[1] / (fps / 2)], btype="band")
    h = signal.filtfilt(b, a, h)
    nfft = 1 << int(np.ceil(np.log2(max(n, 2) * 8)))
    freqs, power = signal.periodogram(h, fs=fps, nfft=nfft, detrend=False)
    band = (freqs >= BAND_HZ[0]) & (freqs <= BAND_HZ[1])
    if not band.any() or power[band].sum() <= 0:
        return out
    peak = freqs[band][np.argmax(power[band])]
    near = (np.abs(freqs - peak) <= 0.1) | (np.abs(freqs - 2 * peak) <= 0.1)   # the fundamental and its first harmonic
    sig_p = power[band & near].sum()
    noise_p = power[band & ~near].sum()
    snr_db = 10 * np.log10(sig_p / noise_p) if noise_p > 0 and sig_p > 0 else (60.0 if sig_p > 0 else -60.0)
    out.update({"bpm": round(float(peak) * 60, 1), "snr_db": round(float(snr_db), 1)})
    out["pulse_present"] = bool(snr_db >= min_snr_db and 42 <= peak * 60 <= 180)
    return out
