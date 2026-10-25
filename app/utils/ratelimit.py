import threading
import time
from collections import defaultdict, deque

from app import config


class FailureLimiter:
    """
    Blocks a key (e.g. client address + username) after too many recent failures, to slow password guessing.

    State is in memory and per process: it resets on restart and is not shared between workers. That is
    enough to make online guessing impractical on a single server; put a shared store behind it to scale out.
    """

    def __init__(self):
        self._failures = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, key, now):
        """Failures of `key` inside the lockout window. Keys with none left are forgotten, so memory stays bounded."""
        failures = self._failures.get(key)
        if failures is None:
            return ()
        while failures and now - failures[0] > config.LOGIN_LOCKOUT_SECONDS:
            failures.popleft()
        if not failures:
            del self._failures[key]
            return ()
        return failures

    def blocked(self, key):
        with self._lock:
            return len(self._recent(key, time.monotonic())) >= config.LOGIN_MAX_FAILURES

    def record_failure(self, key):
        with self._lock:
            now = time.monotonic()
            self._recent(key, now)
            self._failures[key].append(now)

    def reset(self, key):
        with self._lock:
            self._failures.pop(key, None)

    def clear(self):
        with self._lock:
            self._failures.clear()


login_limiter = FailureLimiter()
