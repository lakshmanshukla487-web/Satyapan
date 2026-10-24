"""Builds the set of detectors from settings. Each evidence family contributes its own detector class."""
from apps.signals.detector_base import BaseDetector

ALL = ("audio", "vit", "xception", "landmarks", "facematch", "eyescan", "syncnet", "integrity", "pulse", "provenance")


class DetectorRegistry:
    def __init__(self, settings, detectors: dict[str, BaseDetector] | None = None):
        s = settings
        self._s = settings
        if detectors is None:
            # Imported here: every family app imports apps.signals.detector_base, so this must not run at import time.
            from apps.avsync.detector import SyncNetDetector
            from apps.biometrics.detectors import EyeScanDetector, FaceMatchDetector
            from apps.integrity.detector import IntegrityDetector
            from apps.provenance.detector import ProvenanceDetector
            from apps.pulse.detector import PulseDetector
            from apps.visual.detectors import LandmarkDetector, ViTDetector, XceptionDetector
            from apps.voice.detector import AudioDetector
            detectors = {n: d for n, d, on in [
                ("audio", AudioDetector(s), s.enable_audio_detector),
                ("vit", ViTDetector(s), s.enable_vit_detector),
                ("xception", XceptionDetector(s), s.enable_xception_detector),
                ("landmarks", LandmarkDetector(s), s.enable_mediapipe),
                ("facematch", FaceMatchDetector(s), s.enable_facematch),
                ("eyescan", EyeScanDetector(s), s.enable_eyescan and s.enable_mediapipe),
                ("syncnet", SyncNetDetector(s), s.enable_syncnet),
                ("integrity", IntegrityDetector(s), s.enable_integrity),
                ("pulse", PulseDetector(s), s.enable_pulse),
                ("provenance", ProvenanceDetector(s), s.enable_provenance)] if on}
        self._d: dict[str, BaseDetector] = detectors

    def get(self, name: str) -> BaseDetector | None:
        return self._d.get(name)

    def enabled_names(self, expected_only: bool = True) -> list[str]:
        """Detectors the policy should expect evidence from. Optional families (expected = False) are left out: they
        count when their data arrives and are never reported as missing when it does not."""
        return [n for n, d in self._d.items() if d.expected or not expected_only]

    def warm_up(self) -> dict[str, str]:
        """Load every detector's model now (once, on the CPU). Returns {name: 'loaded' | error code}. Detectors that
        fail stay failed (sticky) and are reported as unavailable; the server still starts."""
        import logging
        import time
        log = logging.getLogger("satyapan.runtime")
        device = getattr(self._s, "inference_device", "cpu")
        try:
            import torch
            n = int(getattr(self._s, "torch_threads", 0) or 0)
            if n > 0:
                torch.set_num_threads(n)
        except ImportError:
            log.warning("PyTorch is not installed: model detectors will report DEPENDENCY_MISSING")
        if device != "cpu":
            log.warning("INFERENCE_DEVICE=%s: this build is designed and tested for the CPU", device)
        out: dict[str, str] = {}
        for name, d in self._d.items():
            t0 = time.perf_counter()
            ok = d.ensure_loaded()
            out[name] = "loaded" if ok else (d._error or "UNAVAILABLE")
            log.info("model %-10s %-9s %.1fs", name, out[name], time.perf_counter() - t0)
        return out

    def status(self) -> list[dict]:
        return [self._d[n].health() if n in self._d else {"name": n, "state": "disabled"} for n in ALL]
