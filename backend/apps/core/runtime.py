"""Per-process singletons: settings, detector registry, bounded inference pool, rate limiter and back-pressure gate.

Created lazily on first use (and eagerly at server start, see ``warm_up`` and satyapan/asgi.py). Tests replace them with
``set_runtime(Runtime.build(settings, registry))``.
"""
import logging
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings as django_settings

from satyapan.conf import AppSettings

log = logging.getLogger("satyapan.runtime")


class RateLimiter:
    """In-memory sliding window per key. Used when no Redis is configured (single server process)."""

    _PRUNE_EVERY = 5000  # calls between sweeps that drop idle keys (otherwise every address / account ever seen stays in memory)

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._calls = 0

    def hit(self, key: str, limit: int, window_s: int = 60) -> tuple[bool, int]:
        """Count one request. -> (allowed, seconds until the next request would be allowed; 0 when allowed)."""
        now = time.monotonic()
        with self._lock:
            self._calls += 1
            if self._calls % self._PRUNE_EVERY == 0:
                for k in [k for k, q in self._hits.items() if not q or now - q[-1] > window_s]:
                    del self._hits[k]
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= max(0, limit):
                retry = int(window_s - (now - q[0])) + 1 if q else window_s
                return False, max(1, min(window_s, retry))
            q.append(now)
            return True, 0

    def allow(self, key: str, limit: int, window_s: int = 60) -> bool:
        return self.hit(key, limit, window_s)[0]


class Runtime:
    def __init__(self, settings: AppSettings, registry: "DetectorRegistry"):  # noqa: F821
        from apps.core.cache import CacheRateLimiter, InferenceGate
        self.settings = settings
        self.registry = registry
        self.pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_inferences, thread_name_prefix="infer")
        self.shared = bool(settings.redis_url)  # Redis configured: limiter, cache and back-pressure are shared across processes
        self.limiter = CacheRateLimiter() if self.shared else RateLimiter()
        self.gate = InferenceGate(settings.inference_queue_limit, shared=self.shared)
        # All origins that are permitted to connect (HTTP CORS + WebSocket).
        self.allowed_origins: frozenset[str] = getattr(django_settings, "SATYAPAN_ALLOWED_ORIGINS", frozenset([settings.frontend_origin]))

    @property
    def risk_publish_interval(self) -> float:
        """Minimum seconds between live risk-score broadcasts for one session (protects the DB and the sockets)."""
        v = self.settings.risk_publish_interval_seconds
        return v if v >= 0 else (2.0 if self.shared else 0.0)

    @classmethod
    def build(cls, settings: AppSettings, registry=None) -> "Runtime":
        if registry is None:
            # Imported here, not at module level: the registry imports every evidence-family app, and those apps
            # import this module.
            from apps.signals.registry import DetectorRegistry
            registry = DetectorRegistry(settings)
        return cls(settings, registry)


_runtime: Runtime | None = None
_lock = threading.Lock()


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        with _lock:
            if _runtime is None:
                _runtime = Runtime.build(django_settings.SATYAPAN)
    return _runtime


def set_runtime(rt: Runtime | None) -> None:
    global _runtime
    old, _runtime = _runtime, rt
    if old is not None:
        old.pool.shutdown(wait=False, cancel_futures=True)


def warm_up() -> dict:
    """Load every enabled model ONCE, on the CPU, now. After this only inference runs: detectors keep their loaded
    model and never reload (a failed load is remembered and reported as 'unavailable', not retried per request).
    Safe to call more than once. Never raises: a missing model must not stop the server, it just shows as unavailable."""
    rt = get_runtime()
    if not rt.settings.preload_models:
        log.info("PRELOAD_MODELS=false: models load on first use")
        return {}
    try:
        out = rt.registry.warm_up()
    except Exception as e:  # noqa: BLE001
        log.error("model warm-up failed: %s: %s", type(e).__name__, e)
        return {}
    from apps.challenges.speech import load as load_speech  # lazy: challenges imports this module
    out["speech"] = load_speech() or "loaded"
    log.info("model %-10s %s", "speech", out["speech"])
    return out
