import numpy as np

from apps.core.media import resample
from apps.signals.hf import HFClassifier

WINDOW_S, HOP_S = 6.0, 3.0  # clips longer than this are scored window by window


class AudioDetector(HFClassifier):
    """The team's fine-tuned wav2vec2-large-xlsr voice anti-spoof model (Wav2Vec2ForSequenceClassification, labels real=0 / fake=1,
    16 kHz mono), loaded from MODEL_DIR/audio (config.json, preprocessor_config.json, model.safetensors).

    Input: mono float32 waveform. Clips longer than 6 s are scored in 6 s windows (hop 3 s); the score is the MEAN of the windows
    and the worst window is reported next to it. score = softmax probability of the 'fake' class (uncalibrated model score)."""
    name, signal_type = "audio", "audio_spoof"
    repo, local_dirname, kind = "local/voice-spoof-wav2vec2-xlsr (fine-tuned)", "audio", "audio"

    @property
    def threshold(self):
        return self.settings.audio_flag_threshold

    def _score_window(self, w16: np.ndarray) -> float:
        import torch
        rate = self._proc.sampling_rate
        inputs = self._proc(w16, sampling_rate=rate, return_tensors="pt", padding=True)
        with torch.inference_mode():
            logits = self._model(**{k: v for k, v in inputs.items()}).logits[0]
        return float(torch.softmax(logits, -1)[self._fake_idx])

    def _infer(self, media, metadata):
        wave, sr = media
        rate = self._proc.sampling_rate
        w = resample(np.asarray(wave, dtype=np.float32), sr, rate)
        n_win, hop = int(WINDOW_S * rate), int(HOP_S * rate)
        if self._fake_idx is None:
            return self.result("error", error_code="LABEL_MAPPING_UNKNOWN", details={"id2label": {str(k): str(v) for k, v in self._model.config.id2label.items()}})
        if len(w) <= n_win:
            scores = [self._score_window(w)]
        else:
            starts = list(range(0, len(w) - n_win + 1, hop))
            if starts[-1] + n_win < len(w):
                starts.append(len(w) - n_win)
            scores = [self._score_window(w[s:s + n_win]) for s in starts]
        mean, worst = float(np.mean(scores)), float(np.max(scores))
        return self.result("ok", mean, label="fake" if mean >= 0.5 else "real",
                           details={"windows": len(scores), "worst_window": round(worst, 4), "window_scores": [round(x, 4) for x in scores[:8]],
                                    "duration_s": round(len(w) / rate, 2)})
