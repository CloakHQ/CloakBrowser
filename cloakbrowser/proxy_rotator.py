"""Proxy rotation for cloakbrowser.

Provides ProxyRotator — a thread-safe proxy pool with multiple rotation
strategies, health tracking, and automatic failover.

Usage:
    from cloakbrowser import ProxyRotator, launch

    rotator = ProxyRotator([
        "http://user:pass@proxy1:8080",
        "http://user:pass@proxy2:8080",
        "http://user:pass@proxy3:8080",
    ])

    # Each call picks the next proxy
    browser = launch(proxy=rotator.next())
    page = browser.new_page()
    page.goto("https://example.com")
    browser.close()

    # Or use the context manager for auto-rotation per page
    with rotator.session() as proxy:
        browser = launch(proxy=proxy)
        ...
"""

from __future__ import annotations

import logging
import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Sequence
from urllib.parse import urlparse

logger = logging.getLogger("cloakbrowser.proxy_rotator")


class Strategy(Enum):
    """Proxy rotation strategies."""
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"
    LEAST_FAILURES = "least_failures"


@dataclass
class _ProxyState:
    """Internal tracking state for a single proxy."""
    url: str
    use_count: int = 0
    fail_count: int = 0
    consecutive_fails: int = 0
    last_used: float = 0.0
    last_failed: float = 0.0
    cooldown_until: float = 0.0

    @property
    def is_available(self) -> bool:
        """Check if this proxy is available (not in cooldown)."""
        return time.monotonic() >= self.cooldown_until

    def record_use(self) -> None:
        self.use_count += 1
        self.last_used = time.monotonic()

    def record_success(self) -> None:
        self.consecutive_fails = 0
        self.cooldown_until = 0.0

    def record_failure(self, cooldown: float, max_consecutive: int) -> None:
        self.fail_count += 1
        self.consecutive_fails += 1
        self.last_failed = time.monotonic()
        if self.consecutive_fails >= max_consecutive:
            self.cooldown_until = time.monotonic() + cooldown
            logger.info(
                "Proxy %s placed on cooldown for %.0fs (%d consecutive failures)",
                _mask_proxy(self.url), cooldown, self.consecutive_fails,
            )


class ProxyRotator:
    """Thread-safe proxy rotator with health tracking.

    Args:
        proxies: List of proxy URLs or Playwright proxy dicts.
            Strings: 'http://user:pass@host:port', 'socks5://host:port'.
            Dicts: {"server": "...", "username": "...", "password": "..."}.
        strategy: Rotation strategy (default: round_robin).
            - round_robin: Cycle through proxies in order.
            - random: Pick a random proxy each time.
            - least_used: Pick the proxy with the fewest uses.
            - least_failures: Pick the proxy with the fewest failures.
        cooldown: Seconds to sideline a proxy after max consecutive failures
            (default: 300 = 5 minutes).
        max_failures: Number of consecutive failures before cooldown
            (default: 3).
        sticky_count: Number of requests to stick with the same proxy
            before rotating (default: 1 = rotate every request).

    Example:
        >>> rotator = ProxyRotator([
        ...     "http://user:pass@proxy1:8080",
        ...     "http://user:pass@proxy2:8080",
        ... ], strategy="round_robin")
        >>> proxy = rotator.next()
        >>> rotator.report_success(proxy)
    """

    def __init__(
        self,
        proxies: Sequence[str | dict],
        strategy: str | Strategy = Strategy.ROUND_ROBIN,
        cooldown: float = 300.0,
        max_failures: int = 3,
        sticky_count: int = 1,
    ) -> None:
        if not proxies:
            raise ValueError("proxies list must not be empty")

        self._strategy = Strategy(strategy) if isinstance(strategy, str) else strategy
        self._cooldown = cooldown
        self._max_failures = max_failures
        self._sticky_count = max(1, sticky_count)
        self._lock = threading.Lock()
        self._rr_index = 0
        self._sticky_counter = 0
        self._sticky_current: str | dict | None = None

        # Normalize: store original proxy value, track by canonical URL key
        self._proxies: list[str | dict] = list(proxies)
        self._states: dict[str, _ProxyState] = {}
        for p in self._proxies:
            self._validate_proxy(p)
            key = self._proxy_key(p)
            if key not in self._states:
                self._states[key] = _ProxyState(url=key)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_proxy(proxy: str | dict) -> None:
        """Raise if proxy uses unsupported configuration.

        Chromium does not support SOCKS5 proxy authentication.
        This catches the issue early instead of failing at launch time.
        """
        if isinstance(proxy, dict):
            server = proxy.get("server", "")
            has_auth = bool(proxy.get("username") or proxy.get("password"))
            if server.startswith("socks5://") and has_auth:
                raise ValueError(
                    "SOCKS5 with authentication is not supported by Chromium. "
                    "Use the HTTP port of the same proxy, or a local SOCKS5 relay."
                )
        else:
            if proxy.startswith("socks5://") and "@" in proxy:
                raise ValueError(
                    "SOCKS5 with authentication is not supported by Chromium. "
                    "Use the HTTP port of the same proxy, or a local SOCKS5 relay."
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def next(self) -> str | dict:
        """Return the next proxy according to the rotation strategy.

        Returns the proxy in its original format (string or dict).
        Raises RuntimeError if all proxies are in cooldown.
        """
        with self._lock:
            # Sticky: keep returning the same proxy for `sticky_count` requests
            if (
                self._sticky_current is not None
                and self._sticky_counter < self._sticky_count
            ):
                key = self._proxy_key(self._sticky_current)
                state = self._states.get(key)
                if state and state.is_available:
                    self._sticky_counter += 1
                    state.record_use()
                    logger.debug("Sticky proxy %s (use %d/%d)", _mask_proxy(key), self._sticky_counter, self._sticky_count)
                    return self._sticky_current

            # Select next proxy
            proxy = self._select()
            key = self._proxy_key(proxy)
            self._states[key].record_use()

            # Reset sticky tracking
            self._sticky_current = proxy
            self._sticky_counter = 1

            logger.debug("Selected proxy %s (strategy=%s)", _mask_proxy(key), self._strategy.value)
            return proxy

    def current(self) -> str | dict | None:
        """Return the currently sticky proxy, or None if not set.

        Useful for calling report_success()/report_failure() after using
        the rotator with launch(proxy=rotator).
        """
        with self._lock:
            return self._sticky_current

    def report_success(self, proxy: str | dict) -> None:
        """Report that a proxy request succeeded. Resets failure counters."""
        key = self._proxy_key(proxy)
        with self._lock:
            if key in self._states:
                self._states[key].record_success()

    def report_failure(self, proxy: str | dict) -> None:
        """Report that a proxy request failed. May trigger cooldown."""
        key = self._proxy_key(proxy)
        with self._lock:
            if key in self._states:
                self._states[key].record_failure(self._cooldown, self._max_failures)
                # If current sticky proxy failed, force rotation
                if (
                    self._sticky_current is not None
                    and self._proxy_key(self._sticky_current) == key
                ):
                    self._sticky_current = None
                    self._sticky_counter = 0

    @contextmanager
    def session(self) -> Iterator[str | dict]:
        """Context manager that yields a proxy and auto-reports success/failure.

        Usage:
            with rotator.session() as proxy:
                browser = launch(proxy=proxy)
                page = browser.new_page()
                page.goto("https://example.com")
                browser.close()
        """
        proxy = self.next()
        try:
            yield proxy
            self.report_success(proxy)
        except Exception:
            self.report_failure(proxy)
            raise

    def stats(self) -> list[dict]:
        """Return usage statistics for all proxies.

        Returns a list of dicts with keys:
            proxy, use_count, fail_count, consecutive_fails, available
        """
        with self._lock:
            result = []
            for p in self._proxies:
                key = self._proxy_key(p)
                state = self._states[key]
                # Deduplicate (same key may appear if list has duplicates)
                if any(r["proxy"] == _mask_proxy(key) for r in result):
                    continue
                result.append({
                    "proxy": _mask_proxy(key),
                    "use_count": state.use_count,
                    "fail_count": state.fail_count,
                    "consecutive_fails": state.consecutive_fails,
                    "available": state.is_available,
                })
            return result

    def reset(self) -> None:
        """Reset all proxy states (counters, cooldowns)."""
        with self._lock:
            for state in self._states.values():
                state.use_count = 0
                state.fail_count = 0
                state.consecutive_fails = 0
                state.last_used = 0.0
                state.last_failed = 0.0
                state.cooldown_until = 0.0
            self._rr_index = 0
            self._sticky_counter = 0
            self._sticky_current = None

    def add(self, proxy: str | dict) -> None:
        """Add a proxy to the pool at runtime."""
        self._validate_proxy(proxy)
        key = self._proxy_key(proxy)
        with self._lock:
            self._proxies.append(proxy)
            if key not in self._states:
                self._states[key] = _ProxyState(url=key)

    def remove(self, proxy: str | dict) -> None:
        """Remove a proxy from the pool at runtime.

        Raises ValueError if the proxy is not in the pool or would leave
        the pool empty.
        """
        key = self._proxy_key(proxy)
        with self._lock:
            # Build filtered list without modifying _proxies yet
            filtered = [p for p in self._proxies if self._proxy_key(p) != key]
            if len(filtered) == len(self._proxies):
                raise ValueError(f"Proxy not in pool: {_mask_proxy(key)}")
            if not filtered:
                raise ValueError("Cannot remove last proxy — pool would be empty")
            # Safe to apply now — both checks passed
            self._proxies = filtered
            self._states.pop(key, None)
            # Clamp round-robin index to new pool size
            if self._rr_index >= len(self._proxies):
                self._rr_index = 0
            # Clear sticky if it was the removed proxy
            if (
                self._sticky_current is not None
                and self._proxy_key(self._sticky_current) == key
            ):
                self._sticky_current = None
                self._sticky_counter = 0

    @property
    def available_count(self) -> int:
        """Number of proxies currently available (not in cooldown)."""
        with self._lock:
            return sum(1 for s in self._states.values() if s.is_available)

    def __len__(self) -> int:
        with self._lock:
            return len(self._proxies)

    def __repr__(self) -> str:
        return (
            f"ProxyRotator(proxies={len(self._proxies)}, "
            f"strategy={self._strategy.value}, "
            f"available={self.available_count})"
        )

    # ------------------------------------------------------------------
    # Internal selection logic
    # ------------------------------------------------------------------

    def _get_available(self) -> list[tuple[int, str | dict]]:
        """Return list of (index, proxy) for proxies not in cooldown."""
        available = []
        for i, p in enumerate(self._proxies):
            key = self._proxy_key(p)
            if self._states[key].is_available:
                available.append((i, p))
        return available

    def _select(self) -> str | dict:
        """Select next proxy based on strategy. Lock must be held by caller."""
        available = self._get_available()
        if not available:
            raise RuntimeError(
                f"All {len(self._proxies)} proxies are in cooldown. "
                f"Wait {self._cooldown:.0f}s or call reset()."
            )

        if self._strategy == Strategy.ROUND_ROBIN:
            return self._select_round_robin(available)
        elif self._strategy == Strategy.RANDOM:
            return self._select_random(available)
        elif self._strategy == Strategy.LEAST_USED:
            return self._select_least_used(available)
        elif self._strategy == Strategy.LEAST_FAILURES:
            return self._select_least_failures(available)
        else:
            raise ValueError(f"Unknown strategy: {self._strategy}")

    def _select_round_robin(self, available: list[tuple[int, str | dict]]) -> str | dict:
        """Round-robin: pick the next proxy in order, skipping unavailable ones."""
        n = len(self._proxies)
        for _ in range(n):
            idx = self._rr_index % n
            self._rr_index = (self._rr_index + 1) % n
            proxy = self._proxies[idx]
            key = self._proxy_key(proxy)
            if self._states[key].is_available:
                return proxy
        # Fallback to first available
        return available[0][1]

    def _select_random(self, available: list[tuple[int, str | dict]]) -> str | dict:
        """Random: pick a random available proxy."""
        _, proxy = random.choice(available)
        return proxy

    def _select_least_used(self, available: list[tuple[int, str | dict]]) -> str | dict:
        """Least-used: pick the proxy with the fewest total uses."""
        return min(
            available,
            key=lambda item: self._states[self._proxy_key(item[1])].use_count,
        )[1]

    def _select_least_failures(self, available: list[tuple[int, str | dict]]) -> str | dict:
        """Least-failures: pick the proxy with the fewest total failures."""
        return min(
            available,
            key=lambda item: self._states[self._proxy_key(item[1])].fail_count,
        )[1]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _proxy_key(proxy: str | dict) -> str:
        """Canonical string key for a proxy (for dedup/tracking).

        For dict proxies, combines server + username into a unique key.
        Uses '||' separator to avoid ambiguity with URL '@' characters.
        """
        if isinstance(proxy, dict):
            server = proxy.get("server", "")
            username = proxy.get("username", "")
            return f"{server}||{username}" if username else server
        return proxy

    # ------------------------------------------------------------------
    # Async helpers (convenience wrappers — the class itself is sync-safe)
    # ------------------------------------------------------------------

    async def next_async(self) -> str | dict:
        """Async wrapper for next(). Same logic, just awaitable."""
        return self.next()

    async def report_success_async(self, proxy: str | dict) -> None:
        """Async wrapper for report_success()."""
        self.report_success(proxy)

    async def report_failure_async(self, proxy: str | dict) -> None:
        """Async wrapper for report_failure()."""
        self.report_failure(proxy)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _mask_proxy(url: str) -> str:
    """Mask credentials in a proxy URL for logging.

    Handles both plain proxy URLs and internal dict-key format
    ('server||username').  Also handles bare proxy strings without
    a scheme (e.g. 'user:pass@host:port').
    """
    # Internal dict-key format: "http://server:port||username"
    if "||" in url:
        server, _ = url.split("||", 1)
        return f"{server}||***"
    try:
        # Bare format: "user:pass@host:port" — no scheme.
        # urlparse needs a scheme to extract credentials correctly.
        normalized = url
        if "@" in url and "://" not in url:
            normalized = f"http://{url}"
        parsed = urlparse(normalized)
        if parsed.username:
            host = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port else ""
            # Return masked version using the *original* scheme if present,
            # otherwise omit scheme to keep the bare format recognizable.
            if "://" in url:
                return f"{parsed.scheme}://***:***@{host}{port}"
            return f"***:***@{host}{port}"
        return url
    except Exception:
        return "***"
