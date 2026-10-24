import logging
import re
import threading
import time
from typing import Any

log = logging.getLogger("satyapan.detectors")


class DetectorError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_FAKE = re.compile(r"fake|spoof|synthetic|deepfake|generated|\bai\b", re.I)
_REAL = re.compile(r"real|bona|genuine|human|authentic|natural", re.I)


def resolve_fake_index(id2label: dict) -> int | None:
    """Pick the 'fake' class from the model's own label map. Returns None if ambiguous: never guessed."""
    fake = [int(i) for i, l in id2label.items() if _FAKE.search(str(l)) and not _REAL.search(str(l))]
    return fake[0] if len(fake) == 1 else None


class BaseDetector:
    """Normalized result: {status: ok|low_quality|unavailable|error, signal_type, score, score_kind, label,
    threshold, error_code, inference_ms, model_id, details}. score_kind says what `score` means; it is never a
    calibrated probability of fraud."""
    name = "base"
    signal_type = "unknown"
    model_id: str | None = None
    score_kind = "uncalibrated_model_score"
    # False for evidence that only exists when the client sends it (pulse, provenance, integrity): a session without it
    # is not reported as having a "missing detector".
    expected = True

    def __init__(self, settings):
        self.settings = settings
        self._loaded = False
        self._error: str | None = None
        self._lock = threading.Lock()

    @property
    def threshold(self) -> float | None:
        return None

    def load(self) -> None:
        raise DetectorError("NOT_INTEGRATED")

    def ensure_loaded(self) -> bool:
        with self._lock:
            if self._loaded:
                return True
            if self._error:
                return False
            try:
                self.load()
                self._loaded = True
            except DetectorError as e:
                self._error = e.code
            except ImportError:
                self._error = "DEPENDENCY_MISSING"
            except Exception as e:  # never crash the API; log type only
                log.warning("detector %s failed to load: %s", self.name, type(e).__name__)
                self._error = "LOAD_FAILED"
            return self._loaded

    def is_available(self) -> bool:
        return self._loaded

    def result(self, status: str, score: float | None = None, **kw: Any) -> dict:
        return {"status": status, "signal_type": self.signal_type, "score": score, "score_kind": self.score_kind, "label": kw.pop("label", None),
                "threshold": self.threshold, "error_code": kw.pop("error_code", None), "inference_ms": None, "model_id": self.model_id, "details": kw.pop("details", {})}

    def _infer(self, media: Any, metadata: dict) -> dict:
        raise NotImplementedError

    def analyze(self, media: Any, metadata: dict | None = None) -> dict:
        t0 = time.perf_counter()
        if not self.ensure_loaded():
            return self.result("unavailable", error_code=self._error)
        try:
            out = self._infer(media, metadata or {})
        except MemoryError:
            out = self.result("error", error_code="OUT_OF_MEMORY")
        except Exception as e:
            log.warning("detector %s inference failed: %s", self.name, type(e).__name__)
            out = self.result("error", error_code="INFERENCE_FAILED")
        out["inference_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return out

    def health(self) -> dict:
        state = "loaded" if self._loaded else ("unavailable" if self._error else "not_loaded")
        h = {"name": self.name, "state": state, "error_code": self._error, "model_id": self.model_id, "device": "cpu"}
        if getattr(self, "load_problem", None):
            h["load_problem"] = self.load_problem
        return h


class StubDetector(BaseDetector):
    """Placeholder for detectors whose compatibility has not been established. Never returns scores."""
    reason = "NOT_INTEGRATED"

    def load(self) -> None:
        raise DetectorError(self.reason)
