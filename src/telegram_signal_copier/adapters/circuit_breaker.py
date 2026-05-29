"""Per-provider circuit breaker for AI provider health management."""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Tracks failure state for a set of named AI providers.

    Each provider entry is a dict (from ``OpenAIClient.providers``) that is
    mutated in-place so existing ``OpenAIClient`` code continues to work
    without structural changes.

    Args:
        base_cooldown_seconds: Starting cooldown duration.
        max_cooldown_seconds: Cap for exponential back-off.
    """

    def __init__(
        self,
        base_cooldown_seconds: int = 60,
        max_cooldown_seconds: int = 3600,
    ) -> None:
        self._base = max(1, base_cooldown_seconds)
        self._max = max(1, max_cooldown_seconds)

    # ------------------------------------------------------------------
    def is_open(self, provider: dict[str, Any]) -> bool:
        """Return ``True`` when the provider should be skipped (circuit open)."""
        now = time.time()
        if provider.get("disabled_until", 0.0) > now:
            return True
        if provider.get("trip_until", 0.0) > now:
            return True
        return False

    def record_success(self, provider: dict[str, Any]) -> None:
        """Reset failure counters after a successful call."""
        provider["failure_count"] = 0
        provider["hard_fail_count"] = 0
        provider["trip_until"] = 0.0
        provider["disabled_until"] = 0.0
        provider["disabled_reason"] = ""

    def record_failure(
        self,
        provider: dict[str, Any],
        exc: Exception,
        kind: str = "network",
    ) -> None:
        """Increment failure counters and calculate the next trip deadline."""
        now = time.time()
        provider["failure_count"] = provider.get("failure_count", 0) + 1
        provider["last_failure"] = now

        if kind == "rate_limit":
            cooldown = min(
                self._max,
                int(self._base * (1.5 ** (provider["failure_count"] - 1))),
            )
        else:
            cooldown = min(
                self._max,
                int(max(5, self._base // 2) * (1.3 ** (provider["failure_count"] - 1))),
            )

        provider["trip_until"] = now + cooldown
        logger.debug(
            "Provider %s tripped for %ds after %s: %s",
            provider.get("name", "unnamed"),
            cooldown,
            kind,
            exc,
        )

    def record_hard_failure(
        self,
        provider: dict[str, Any],
        http_code: int,
        detail: str,
    ) -> None:
        """Handle non-retriable HTTP errors (4xx).  Disable provider after 3 repeats."""
        provider["hard_fail_count"] = provider.get("hard_fail_count", 0) + 1
        provider["failure_count"] = provider.get("failure_count", 0) + 1
        provider["last_failure"] = time.time()
        if provider["hard_fail_count"] >= 3 and http_code in {400, 401, 403, 404, 422}:
            provider["disabled_until"] = time.time() + 600
            provider["disabled_reason"] = f"repeated_http_{http_code}"
            logger.warning(
                "Provider %s disabled for 10 min after %d hard failures (HTTP %d): %s",
                provider.get("name", "unnamed"),
                provider["hard_fail_count"],
                http_code,
                detail,
            )
