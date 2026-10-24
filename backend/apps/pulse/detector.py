import numpy as np

from apps.pulse.logic import analyze_rgb
from apps.signals.detector_base import BaseDetector


class PulseDetector(BaseDetector):
    """Family 5. Input: (rgb array (N, 3), fps). Supporting evidence only: no score, never an indicator."""
    name, signal_type, model_id, score_kind = "pulse", "pulse", "pos-rppg", "rule_based"
    expected = False

    def load(self) -> None:
        pass

    def _infer(self, media, metadata):
        rgb, fps = media
        r = analyze_rgb(np.asarray(rgb, dtype=float), float(fps), self.settings.pulse_min_snr_db)
        details = {k: r[k] for k in ("quality", "bpm", "snr_db", "duration_s", "mean_brightness")}
        if r["quality"] != "good":
            return self.result("low_quality", error_code="POOR_PULSE_QUALITY", details={**details, "quality_reasons": r["quality_reasons"], "supports": False})
        notes = [] if r["pulse_present"] else ["No pulse signal was found in good-quality video. Pulse is corroboration only, so this is not counted as suspicious."]
        return self.result("ok", None, label="pulse found" if r["pulse_present"] else "no pulse found", details={**details, "supports": r["pulse_present"], "notes": notes})
