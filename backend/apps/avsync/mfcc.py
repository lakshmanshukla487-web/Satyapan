"""MFCC features identical to python_speech_features.mfcc(...) with its defaults, which is what SyncNet was trained on:
25 ms frames every 10 ms, 26 mel filters, 512-point FFT, 13 coefficients, pre-emphasis 0.97, lifter 22, first coefficient
replaced by the log frame energy, rectangular window, input in 16-bit integer scale."""
import numpy as np
from scipy.fft import dct

SR, WINLEN, WINSTEP, NUMCEP, NFILT, NFFT, PREEMPH, LIFTER = 16000, 0.025, 0.01, 13, 26, 512, 0.97, 22


def _hz2mel(hz):
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel2hz(mel):
    return 700.0 * (10 ** (mel / 2595.0) - 1.0)


def filterbank(nfilt=NFILT, nfft=NFFT, sr=SR, low=0.0, high=None) -> np.ndarray:
    high = high or sr / 2
    pts = np.linspace(_hz2mel(low), _hz2mel(high), nfilt + 2)
    bins = np.floor((nfft + 1) * _mel2hz(pts) / sr).astype(int)
    fb = np.zeros((nfilt, nfft // 2 + 1))
    for j in range(nfilt):
        for i in range(bins[j], bins[j + 1]):
            fb[j, i] = (i - bins[j]) / (bins[j + 1] - bins[j])
        for i in range(bins[j + 1], bins[j + 2]):
            fb[j, i] = (bins[j + 2] - i) / (bins[j + 2] - bins[j + 1])
    return fb


_FB = filterbank()
_LIFT = 1 + (LIFTER / 2.0) * np.sin(np.pi * np.arange(NUMCEP) / LIFTER)


def mfcc(wave16k: np.ndarray) -> np.ndarray:
    """wave16k: float32 in -1..1 at 16 kHz. Returns (13, T) like SyncNet's `zip(*mfcc)` stack (T = 100 per second)."""
    sig = np.asarray(wave16k, dtype=np.float64) * 32767.0
    sig = np.append(sig[0], sig[1:] - PREEMPH * sig[:-1]) if len(sig) > 1 else sig
    flen, fstep = int(round(WINLEN * SR)), int(round(WINSTEP * SR))
    slen = len(sig)
    n = 1 if slen <= flen else 1 + int(np.ceil((slen - flen) / fstep))
    pad = int((n - 1) * fstep + flen)
    padded = np.concatenate([sig, np.zeros(pad - slen)])
    idx = np.tile(np.arange(flen), (n, 1)) + np.tile(np.arange(0, n * fstep, fstep), (flen, 1)).T
    frames = padded[idx.astype(np.int32)]
    pspec = (1.0 / NFFT) * np.square(np.abs(np.fft.rfft(frames, NFFT)))
    energy = pspec.sum(axis=1)
    energy = np.where(energy == 0, np.finfo(float).eps, energy)
    feat = pspec @ _FB.T
    feat = np.where(feat == 0, np.finfo(float).eps, feat)
    ceps = dct(np.log(feat), type=2, axis=1, norm="ortho")[:, :NUMCEP] * _LIFT
    ceps[:, 0] = np.log(energy)
    return ceps.T.astype(np.float32)
