"""
asomien/core/rate_limiter.py

Token bucket rate limiter for the NVIDIA NIM API.
Hard limit: 40 requests/minute.
Soft limit (used here): 35 requests/minute (SAFETY_CONFIG.max_llm_calls_per_hour).

This is NOT a threading-safe distributed limiter — it's a single-process
in-memory token bucket. If running multi-process, use a Redis-backed limiter.

Blueprint reference: Section 5 (NIMRateLimiter), Section 10 (SAFETY_CONFIG).
"""

from __future__ import annotations

import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)


class NIMRateLimiter:
    """
    Token bucket rate limiter for the NVIDIA NIM API.

    The NIM free tier allows 40 requests/minute. We operate at a soft cap
    of 35 req/min (SAFETY_CONFIG['max_llm_calls_per_hour'] / 60) to leave
    headroom for burst spikes.

    Usage:
        limiter = NIMRateLimiter(max_calls_per_minute=35)
        limiter.acquire()   # blocks until a token is available
        # ... make API call ...
    """

    def __init__(
        self,
        max_calls_per_minute: int = 35,
        window_seconds: float = 60.0,
    ) -> None:
        """
        Args:
            max_calls_per_minute: Maximum API calls allowed per window (default: 35, soft cap).
            window_seconds:       Duration of the rolling window in seconds (default: 60).
        """
        self.max_calls = max_calls_per_minute
        self.window = window_seconds
        self._lock = Lock()
        self._call_timestamps: list[float] = []   # monotonic timestamps of recent calls

        logger.debug(
            f"[NIMRateLimiter] initialized: {max_calls_per_minute} req/{window_seconds}s"
        )

    def _purge_old_timestamps(self, now: float) -> None:
        """Remove timestamps older than the rolling window. Must be called under lock."""
        cutoff = now - self.window
        self._call_timestamps = [t for t in self._call_timestamps if t > cutoff]

    def acquire(self, timeout: float = 120.0) -> bool:
        """
        Block until a token is available, then record the call.

        Args:
            timeout: Maximum seconds to wait before giving up (default: 120s).
                     Raises RuntimeError on timeout.

        Returns:
            True if token acquired successfully.

        Raises:
            RuntimeError: If a token cannot be acquired within timeout seconds.
        """
        deadline = time.monotonic() + timeout
        sleep_interval = 0.25   # check every 250ms

        while True:
            with self._lock:
                now = time.monotonic()
                self._purge_old_timestamps(now)

                if len(self._call_timestamps) < self.max_calls:
                    # Token available — consume it
                    self._call_timestamps.append(now)
                    remaining = self.max_calls - len(self._call_timestamps)
                    logger.debug(
                        f"[NIMRateLimiter] token acquired. remaining in window: {remaining}"
                    )
                    return True

                # No token available — calculate wait time
                oldest = self._call_timestamps[0]
                wait_needed = self.window - (now - oldest)

            # Check timeout before sleeping
            if time.monotonic() + wait_needed > deadline:
                raise RuntimeError(
                    f"[NIMRateLimiter] Timeout: could not acquire token within {timeout}s. "
                    f"Current window usage: {len(self._call_timestamps)}/{self.max_calls}"
                )

            logger.debug(
                f"[NIMRateLimiter] rate limit reached "
                f"({len(self._call_timestamps)}/{self.max_calls}). "
                f"Waiting {wait_needed:.2f}s..."
            )
            time.sleep(min(sleep_interval, max(0.01, wait_needed)))

    def get_remaining(self) -> int:
        """
        Returns the number of tokens remaining in the current window.
        Non-blocking.
        """
        with self._lock:
            now = time.monotonic()
            self._purge_old_timestamps(now)
            return max(0, self.max_calls - len(self._call_timestamps))

    def estimate_wait(self) -> float:
        """
        Estimate how many seconds until the next token is available.
        Returns 0.0 if a token is immediately available.
        """
        with self._lock:
            now = time.monotonic()
            self._purge_old_timestamps(now)

            if len(self._call_timestamps) < self.max_calls:
                return 0.0

            oldest = self._call_timestamps[0]
            return max(0.0, self.window - (now - oldest))

    @property
    def usage_in_window(self) -> int:
        """Current call count in the rolling window."""
        with self._lock:
            now = time.monotonic()
            self._purge_old_timestamps(now)
            return len(self._call_timestamps)

    def reset(self) -> None:
        """
        Clear all recorded timestamps. Useful for testing.
        Do NOT call this in production — it bypasses the rate limit.
        """
        with self._lock:
            self._call_timestamps.clear()
        logger.warning("[NIMRateLimiter] reset() called — all timestamps cleared.")
