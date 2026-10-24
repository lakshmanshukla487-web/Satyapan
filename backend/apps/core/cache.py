"""Shared cache, rate limiting and back-pressure. Works in-process with no Redis; uses Redis when REDIS_URL is set.

Nothing here may ever take the API down: every cache call is wrapped, and a failing Redis degrades to "no cache" (reads
miss, writes are skipped, the rate limiter fails open) with a warning in the log.
"""
import hashlib
import logging
import threading
import time

from django.core.cache import cache

log = logging.getLogger("satyapan.cache")


def cache_get(key: str, default=None):
    try:
        return cache.get(key, default)
    except Exception as e:  # noqa: BLE001
        log.warning("cache get failed: %s", type(e).__name__)
        return default


def cache_set(key: str, value, ttl: int = 300) -> bool:
    try:
        cache.set(key, value, ttl)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("cache set failed: %s", type(e).__name__)
        return False


def cache_add(key: str, value, ttl: int) -> bool:
    """True if the key did not exist and was created (a cheap cross-process 'only one of us gets to do this')."""
    try:
        return bool(cache.add(key, value, ttl))
    except Exception as e:  # noqa: BLE001
        log.warning("cache add failed: %s", type(e).__name__)
        return True  # fail open: do the work


def cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception as e:  # noqa: BLE001
        log.warning("cache delete failed: %s", type(e).__name__)


def media_key(data: bytes) -> str:
    """Stable key for one uploaded sample (so an identical retry does not run the model again)."""
    return hashlib.sha256(data).hexdigest()


class CacheRateLimiter:
    """Fixed-window counter on the shared cache. Same interface as the in-memory RateLimiter. Fails open."""

    def allow(self, key: str, limit: int, window_s: int = 60) -> bool:
        bucket = int(time.time() // window_s)
        k = f"rl:{key}:{bucket}"
        try:
            cache.add(k, 0, window_s + 5)
            return int(cache.incr(k)) <= limit
        except Exception as e:  # noqa: BLE001
            log.warning("rate limiter unavailable (allowing): %s", type(e).__name__)
            return True


class InferenceGate:
    """Bounded queue in front of the model thread pool. When more than `limit` requests are already waiting for or
    running on a model, new ones are refused immediately (503) instead of building an ever longer queue that makes
    every customer's page slow. With Redis the count is shared by all server processes."""

    def __init__(self, limit: int, shared: bool):
        self.limit, self.shared = max(1, limit), shared
        self._n = 0
        self._lock = threading.Lock()

    def enter(self) -> bool:
        if self.shared:
            try:
                cache.add("inflight", 0, 120)
                n = int(cache.incr("inflight"))
                if n > self.limit:
                    cache.decr("inflight")
                    return False
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("shared gate unavailable, using local count: %s", type(e).__name__)
        with self._lock:
            if self._n >= self.limit:
                return False
            self._n += 1
            return True

    def leave(self) -> None:
        if self.shared:
            try:
                if int(cache.get("inflight", 0)) > 0:
                    cache.decr("inflight")
                return
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._n = max(0, self._n - 1)
