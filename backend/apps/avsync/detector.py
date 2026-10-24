"""Lip-sync check: does the voice match the movement of the lips? (SyncNet, PyTorch, CPU, loaded once.)

score is 'how out of sync': 0 = clearly in sync (SyncNet confidence at or above SYNCNET_MIN_CONFIDENCE), 0.75 = confidence at
SYNCNET_BAD_CONFIDENCE (no audio/lip relation found), 1 = worse. An offset larger than SYNCNET_MAX_OFFSET_FRAMES with a clear
sync peak also raises the score (audio and video are related but shifted: typical of a separately injected voice or video).
Both numbers are research-model outputs, not calibrated probabilities."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from apps.avsync import mfcc as mfcc_mod
from apps.signals.detector_base import BaseDetector, DetectorError

VSHIFT = 15
MIN_FRAMES = 40       # 1.6 s
BATCH = 8


class SyncNetDetector(BaseDetector):
    name, signal_type, score_kind = "syncnet", "av_sync", "out_of_sync_score"
    model_id = "syncnet_v2 (VGG-M, Chung & Zisserman) - research weights"

    @property
    def threshold(self):
        s = self.settings
        return round((s.syncnet_min_confidence - s.syncnet_bad_confidence) / s.syncnet_min_confidence, 3)

    def load(self) -> None:
        """Runs ONCE, at server start (warm_up): checkpoint, strict layer check, and one dummy pass through both branches so
        PyTorch's one-off setup is not paid by the first customer clip. After this only _infer runs; a failure is remembered."""
        import torch
        from apps.avsync.syncnet_model import SyncNetS
        path = Path(self.settings.model_dir) / self.settings.syncnet_checkpoint
        if not path.is_file():
            raise DetectorError("MODEL_NOT_DOWNLOADED")
        torch.set_grad_enabled(False)
        model = SyncNetS()
        state = torch.load(str(path), map_location="cpu", weights_only=True)
        if isinstance(state, dict) and "state_dict" in state:
            state = state["state_dict"]
        state = {k.removeprefix("module.").removeprefix("S."): v for k, v in state.items()}
        res = model.load_state_dict(state, strict=False)
        if res.missing_keys or res.unexpected_keys:
            self.load_problem = {"missing": res.missing_keys[:10], "unexpected": res.unexpected_keys[:10]}
            raise DetectorError("CHECKPOINT_MISMATCH")
        self._model = model.eval()
        with torch.inference_mode():
            self._model.forward_lip(torch.zeros(1, 3, 5, 224, 224))
            self._model.forward_aud(torch.zeros(1, 1, 13, 20))

    # media = {"frames": [BGR uint8 224x224 x N at 25 fps], "wave": float32 mono 16 kHz}
    def _infer(self, media, metadata):
        import torch
        s = self.settings
        frames, wave = media["frames"], np.asarray(media["wave"], dtype=np.float32)
        n = min(len(frames), len(wave) // 640)
        if n < MIN_FRAMES:
            return self.result("low_quality", error_code="CLIP_TOO_SHORT", details={"frames": n, "needed": MIN_FRAMES})
        mf = mfcc_mod.mfcc(wave[: n * 640])                                  # (13, T)
        cct = torch.from_numpy(mf).unsqueeze(0).unsqueeze(0)                   # 1 x 1 x 13 x T
        vid = torch.from_numpy(np.stack(frames[:n], axis=0).astype(np.float32))  # N x 224 x 224 x 3
        vid = vid.permute(3, 0, 1, 2).unsqueeze(0)                             # 1 x 3 x N x 224 x 224
        last = n - 5
        lip, aud = [], []
        with torch.inference_mode():  # grad mode is per thread: the one set in load() does not reach the request threads
            for i in range(0, last, BATCH):
                ids = range(i, min(last, i + BATCH))
                lip.append(self._model.forward_lip(torch.cat([vid[:, :, v:v + 5] for v in ids], 0)))
                aud.append(self._model.forward_aud(torch.cat([cct[:, :, :, v * 4:v * 4 + 20] for v in ids], 0)))
            lip, aud = torch.cat(lip, 0), torch.cat(aud, 0)
        if lip.shape[0] < 5 or aud.shape[0] != lip.shape[0]:
            return self.result("low_quality", error_code="CLIP_TOO_SHORT", details={"windows": int(lip.shape[0])})
        win = VSHIFT * 2 + 1
        aud_p = torch.nn.functional.pad(aud, (0, 0, VSHIFT, VSHIFT))
        dists = torch.stack([torch.nn.functional.pairwise_distance(lip[i:i + 1].repeat(win, 1), aud_p[i:i + win]) for i in range(lip.shape[0])], 1)
        mean_d = dists.mean(1)
        minval, minidx = mean_d.min(0)
        offset = VSHIFT - int(minidx)
        conf = float(mean_d.median() - minval)
        score = float(np.clip((s.syncnet_min_confidence - conf) / s.syncnet_min_confidence, 0.0, 1.0))
        shifted = abs(offset) > s.syncnet_max_offset_frames and conf >= s.syncnet_bad_confidence * 2
        if shifted:
            score = max(score, 0.8)
        verdict = "in_sync" if (conf >= s.syncnet_min_confidence and not shifted) else ("shifted" if shifted else ("no_relation" if conf <= s.syncnet_bad_confidence else "weak_sync"))
        return self.result("ok", round(score, 4), label=verdict, details={
            "confidence": round(conf, 3), "offset_frames": offset, "offset_ms": offset * 40, "min_distance": round(float(minval), 3),
            "median_distance": round(float(mean_d.median()), 3), "windows": int(lip.shape[0]), "clip_seconds": round(n / 25, 2), "verdict": verdict})
