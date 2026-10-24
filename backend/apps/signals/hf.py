from pathlib import Path

from apps.signals.detector_base import BaseDetector, DetectorError, resolve_fake_index


class HFClassifier(BaseDetector):
    """A Hugging Face transformers classifier (PyTorch), loaded ONCE on the CPU and then used for inference only.

    Loading order: MODEL_DIR/<local_dirname> if that folder exists, otherwise the Hugging Face cache for `repo`
    (offline: nothing is ever downloaded while the server runs). Loading is STRICT: if any weight in the checkpoint is
    missing or has the wrong shape the detector reports unavailable (WEIGHTS_INCOMPLETE) instead of silently running with
    randomly initialised layers, which would produce confident but meaningless scores."""
    repo = ""
    local_dirname = ""
    kind = "image"  # or "audio"

    @property
    def model_id(self):  # type: ignore[override]
        return self.repo

    def fake_index_override(self) -> int | None:
        return None

    def load(self) -> None:
        import torch
        from transformers import AutoFeatureExtractor, AutoImageProcessor, AutoModelForAudioClassification, AutoModelForImageClassification

        torch.set_grad_enabled(False)
        local = Path(self.settings.model_dir) / self.local_dirname
        src, kw = (str(local), {}) if local.is_dir() else (self.repo, {"local_files_only": True})  # never download at runtime
        try:
            if self.kind == "audio":
                self._proc = AutoFeatureExtractor.from_pretrained(src, **kw)
                model, info = AutoModelForAudioClassification.from_pretrained(src, output_loading_info=True, **kw)
            else:
                self._proc = AutoImageProcessor.from_pretrained(src, **kw)
                model, info = AutoModelForImageClassification.from_pretrained(src, output_loading_info=True, **kw)
        except OSError as e:
            raise DetectorError("MODEL_NOT_DOWNLOADED") from e
        if info.get("missing_keys") or info.get("mismatched_keys"):
            self.load_problem = {"missing": list(info.get("missing_keys", []))[:10], "mismatched": [str(x) for x in info.get("mismatched_keys", [])][:10]}
            raise DetectorError("WEIGHTS_INCOMPLETE")
        self._model = model.to("cpu").eval()  # loaded once, on the CPU
        override = self.fake_index_override()
        self._fake_idx = override if override is not None else resolve_fake_index(self._model.config.id2label)

    def _inputs(self, media):
        raise NotImplementedError

    def _infer(self, media, metadata):
        import torch
        inputs = {k: v.to("cpu") for k, v in self._inputs(media).items()}
        with torch.inference_mode():
            logits = self._model(**inputs).logits[0]
        probs = torch.softmax(logits, -1).tolist()
        id2label = self._model.config.id2label
        labels = [str(id2label[i]) for i in range(len(probs))]
        details = {"softmax_by_label": dict(zip(labels, probs)), "predicted_label": labels[max(range(len(probs)), key=probs.__getitem__)],
                   "fake_class_index": self._fake_idx, "raw_logits": [round(x, 4) for x in logits.tolist()]}
        if self._fake_idx is None:  # label map ambiguous: refuse to pick a class
            return self.result("error", error_code="LABEL_MAPPING_UNKNOWN", details=details)
        return self.result("ok", probs[self._fake_idx], label=details["predicted_label"], details=details)
