"""Unit tests for proxy_rotator.py — strategies, health tracking, thread safety."""

import threading
import time
from unittest.mock import patch

import pytest

from cloakbrowser.proxy_rotator import ProxyRotator, Strategy, _mask_proxy


PROXIES = [
    "http://user:pass@proxy1:8080",
    "http://user:pass@proxy2:8080",
    "http://user:pass@proxy3:8080",
]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_empty_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            ProxyRotator([])

    def test_single_proxy(self):
        r = ProxyRotator(["http://proxy:8080"])
        assert len(r) == 1
        assert r.next() == "http://proxy:8080"

    def test_accepts_dict_proxies(self):
        r = ProxyRotator([{"server": "http://proxy:8080", "username": "u", "password": "p"}])
        assert len(r) == 1
        p = r.next()
        assert isinstance(p, dict)
        assert p["server"] == "http://proxy:8080"

    def test_strategy_string(self):
        r = ProxyRotator(PROXIES, strategy="random")
        assert r._strategy == Strategy.RANDOM

    def test_strategy_enum(self):
        r = ProxyRotator(PROXIES, strategy=Strategy.LEAST_USED)
        assert r._strategy == Strategy.LEAST_USED

    def test_repr(self):
        r = ProxyRotator(PROXIES)
        s = repr(r)
        assert "proxies=3" in s
        assert "round_robin" in s


# ---------------------------------------------------------------------------
# Round Robin
# ---------------------------------------------------------------------------


class TestRoundRobin:
    def test_cycles_through_proxies(self):
        r = ProxyRotator(PROXIES, strategy="round_robin")
        results = [r.next() for _ in range(6)]
        assert results == PROXIES + PROXIES

    def test_skips_cooled_down(self):
        r = ProxyRotator(PROXIES, strategy="round_robin", max_failures=1, cooldown=60)
        p = r.next()
        r.report_failure(p)
        results = [r.next() for _ in range(4)]
        assert PROXIES[0] not in results


# ---------------------------------------------------------------------------
# Random
# ---------------------------------------------------------------------------


class TestRandom:
    def test_returns_valid_proxy(self):
        r = ProxyRotator(PROXIES, strategy="random")
        for _ in range(20):
            assert r.next() in PROXIES

    def test_skips_cooled_down(self):
        r = ProxyRotator(PROXIES, strategy="random", max_failures=1, cooldown=60)
        r.report_failure(PROXIES[0])
        r.report_failure(PROXIES[1])
        for _ in range(10):
            assert r.next() == PROXIES[2]


# ---------------------------------------------------------------------------
# Least Used
# ---------------------------------------------------------------------------


class TestLeastUsed:
    def test_distributes_evenly(self):
        r = ProxyRotator(PROXIES, strategy="least_used")
        for _ in range(9):
            r.next()
        stats = {s["proxy"]: s["use_count"] for s in r.stats()}
        counts = list(stats.values())
        assert max(counts) - min(counts) <= 1


# ---------------------------------------------------------------------------
# Least Failures
# ---------------------------------------------------------------------------


class TestLeastFailures:
    def test_avoids_failed_proxies(self):
        r = ProxyRotator(PROXIES, strategy="least_failures")
        r.report_failure(PROXIES[0])
        r.report_failure(PROXIES[0])
        result = r.next()
        assert result in (PROXIES[1], PROXIES[2])


# ---------------------------------------------------------------------------
# Health tracking
# ---------------------------------------------------------------------------


class TestHealthTracking:
    def test_success_resets_consecutive(self):
        r = ProxyRotator(PROXIES, strategy="round_robin", max_failures=3, cooldown=60)
        proxy = PROXIES[0]
        r.report_failure(proxy)
        r.report_failure(proxy)
        r.report_success(proxy)
        key = r._proxy_key(proxy)
        assert r._states[key].consecutive_fails == 0
        assert r._states[key].is_available

    def test_cooldown_triggers(self):
        r = ProxyRotator(PROXIES, strategy="round_robin", max_failures=2, cooldown=60)
        proxy = PROXIES[0]
        r.report_failure(proxy)
        r.report_failure(proxy)
        key = r._proxy_key(proxy)
        assert not r._states[key].is_available

    def test_all_in_cooldown_raises(self):
        r = ProxyRotator(["http://p1:80", "http://p2:80"], max_failures=1, cooldown=60)
        r.report_failure("http://p1:80")
        r.report_failure("http://p2:80")
        with pytest.raises(RuntimeError, match="All.*proxies are in cooldown"):
            r.next()

    def test_cooldown_expires(self):
        r = ProxyRotator(PROXIES, max_failures=1, cooldown=0.1)
        proxy = PROXIES[0]
        r.report_failure(proxy)
        key = r._proxy_key(proxy)
        assert not r._states[key].is_available
        time.sleep(0.15)
        assert r._states[key].is_available


# ---------------------------------------------------------------------------
# Sticky count
# ---------------------------------------------------------------------------


class TestSticky:
    def test_sticky_reuses_proxy(self):
        r = ProxyRotator(PROXIES, strategy="round_robin", sticky_count=3)
        first = r.next()
        second = r.next()
        third = r.next()
        assert first == second == third
        fourth = r.next()
        assert fourth != first

    def test_sticky_resets_on_failure(self):
        r = ProxyRotator(PROXIES, strategy="round_robin", sticky_count=5)
        first = r.next()
        r.report_failure(first)
        second = r.next()
        assert r._sticky_counter == 1


# ---------------------------------------------------------------------------
# Session context manager
# ---------------------------------------------------------------------------


class TestSession:
    def test_success_path(self):
        r = ProxyRotator(PROXIES)
        with r.session() as proxy:
            assert proxy in PROXIES
        key = r._proxy_key(proxy)
        assert r._states[key].consecutive_fails == 0

    def test_failure_path(self):
        r = ProxyRotator(PROXIES)
        with pytest.raises(ValueError):
            with r.session() as proxy:
                raise ValueError("simulated error")
        key = r._proxy_key(proxy)
        assert r._states[key].fail_count == 1


# ---------------------------------------------------------------------------
# Dynamic pool management
# ---------------------------------------------------------------------------


class TestDynamicPool:
    def test_add_proxy(self):
        r = ProxyRotator(PROXIES[:2])
        assert len(r) == 2
        r.add("http://new:8080")
        assert len(r) == 3

    def test_remove_proxy(self):
        r = ProxyRotator(PROXIES)
        r.remove(PROXIES[0])
        assert len(r) == 2

    def test_remove_nonexistent_raises(self):
        r = ProxyRotator(PROXIES)
        with pytest.raises(ValueError, match="not in pool"):
            r.remove("http://nonexistent:9999")

    def test_remove_last_raises(self):
        r = ProxyRotator(["http://only:8080"])
        with pytest.raises(ValueError, match="pool would be empty"):
            r.remove("http://only:8080")


# ---------------------------------------------------------------------------
# Stats and reset
# ---------------------------------------------------------------------------


class TestStatsAndReset:
    def test_stats_structure(self):
        r = ProxyRotator(PROXIES)
        r.next()
        stats = r.stats()
        assert len(stats) == 3
        for s in stats:
            assert "proxy" in s
            assert "use_count" in s
            assert "fail_count" in s
            assert "available" in s

    def test_stats_masks_credentials(self):
        r = ProxyRotator(PROXIES)
        stats = r.stats()
        for s in stats:
            assert "pass" not in s["proxy"]

    def test_reset_clears_state(self):
        r = ProxyRotator(PROXIES)
        for _ in range(5):
            r.next()
        r.report_failure(PROXIES[0])
        r.reset()
        stats = r.stats()
        for s in stats:
            assert s["use_count"] == 0
            assert s["fail_count"] == 0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_next(self):
        r = ProxyRotator(PROXIES, strategy="round_robin")
        results = []
        errors = []

        def worker():
            try:
                for _ in range(100):
                    p = r.next()
                    results.append(p)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 1000
        assert all(p in PROXIES for p in results)


# ---------------------------------------------------------------------------
# Mask utility
# ---------------------------------------------------------------------------


class TestMaskProxy:
    def test_masks_credentials(self):
        assert "pass" not in _mask_proxy("http://user:pass@host:8080")
        assert "***" in _mask_proxy("http://user:pass@host:8080")

    def test_no_credentials_unchanged(self):
        assert _mask_proxy("http://host:8080") == "http://host:8080"

    def test_dict_key_format(self):
        r = ProxyRotator([{"server": "http://p:80", "username": "u"}])
        key = r._proxy_key({"server": "http://p:80", "username": "u"})
        assert key == "http://p:80||u"


# ---------------------------------------------------------------------------
# Available count
# ---------------------------------------------------------------------------


class TestAvailableCount:
    def test_all_available_initially(self):
        r = ProxyRotator(PROXIES)
        assert r.available_count == 3

    def test_decreases_with_cooldown(self):
        r = ProxyRotator(PROXIES, max_failures=1, cooldown=60)
        r.report_failure(PROXIES[0])
        assert r.available_count == 2


# ---------------------------------------------------------------------------
# current() method
# ---------------------------------------------------------------------------


class TestCurrent:
    def test_current_returns_none_initially(self):
        r = ProxyRotator(PROXIES)
        assert r.current() is None

    def test_current_returns_last_proxy_after_next(self):
        r = ProxyRotator(PROXIES, strategy="round_robin")
        proxy = r.next()
        assert r.current() == proxy

    def test_current_useful_for_report_after_launch(self):
        r = ProxyRotator(PROXIES, strategy="round_robin")
        proxy = r.next()
        current = r.current()
        assert current == proxy
        r.report_success(current)
        key = r._proxy_key(current)
        assert r._states[key].consecutive_fails == 0


# ---------------------------------------------------------------------------
# remove() edge cases
# ---------------------------------------------------------------------------


class TestRemoveEdgeCases:
    def test_remove_preserves_state_on_last_proxy_error(self):
        r = ProxyRotator(["http://only:8080"])
        with pytest.raises(ValueError, match="pool would be empty"):
            r.remove("http://only:8080")
        assert len(r) == 1
        assert r.next() == "http://only:8080"

    def test_remove_clamps_rr_index(self):
        r = ProxyRotator(PROXIES, strategy="round_robin")
        r.next()
        r.next()
        r.next()
        r.remove(PROXIES[0])
        proxy = r.next()
        assert proxy in (PROXIES[1], PROXIES[2])

    def test_remove_clears_sticky_for_removed_proxy(self):
        r = ProxyRotator(PROXIES, strategy="round_robin", sticky_count=5)
        first = r.next()
        r.remove(first)
        second = r.next()
        assert second != first
        assert second in PROXIES[1:]


# ---------------------------------------------------------------------------
# Mask utility — dict key format
# ---------------------------------------------------------------------------


class TestMaskDictKey:
    def test_mask_dict_key_hides_username(self):
        masked = _mask_proxy("http://proxy:8080||admin")
        assert "admin" not in masked
        assert "***" in masked
        assert "http://proxy:8080||***" == masked

    def test_mask_dict_key_no_username(self):
        assert _mask_proxy("http://proxy:8080") == "http://proxy:8080"


# ---------------------------------------------------------------------------
# Bare proxy format (user:pass@host:port without scheme)
# ---------------------------------------------------------------------------


class TestBareProxyFormat:
    def test_mask_bare_proxy_hides_credentials(self):
        masked = _mask_proxy("user:pass@proxy1.example.com:5610")
        assert "pass" not in masked
        assert "user" not in masked
        assert "***" in masked
        assert "proxy1.example.com:5610" in masked

    def test_mask_bare_proxy_no_creds(self):
        assert _mask_proxy("proxy1.example.com:5610") == "proxy1.example.com:5610"

    def test_rotator_accepts_bare_proxy(self):
        r = ProxyRotator(["user:pass@proxy1:8080"])
        proxy = r.next()
        assert proxy == "user:pass@proxy1:8080"
        assert r.current() == proxy

    def test_rotator_mixed_bare_and_scheme(self):
        r = ProxyRotator([
            "user:pass@proxy1:8080",
            "http://user:pass@proxy2:8080",
            "socks5://proxy3:15610",
        ], strategy="round_robin")
        results = [r.next() for _ in range(3)]
        assert results[0] == "user:pass@proxy1:8080"
        assert results[1] == "http://user:pass@proxy2:8080"
        assert results[2] == "socks5://proxy3:15610"

    def test_stats_masks_bare_proxy_credentials(self):
        r = ProxyRotator(["user:secret@proxy1.example.com:5610"])
        r.next()
        stats = r.stats()
        assert len(stats) == 1
        assert "secret" not in stats[0]["proxy"]
        assert "user" not in stats[0]["proxy"]


# ---------------------------------------------------------------------------
# Socks5 proxy format
# ---------------------------------------------------------------------------


class TestSocks5Format:
    """Verify SOCKS5 proxy support."""

    def test_mask_socks5_no_credentials(self):
        masked = _mask_proxy("socks5://proxy:15610")
        assert masked == "socks5://proxy:15610"

    def test_rotator_accepts_socks5_no_auth(self):
        r = ProxyRotator(["socks5://proxy:15610"])
        proxy = r.next()
        assert proxy.startswith("socks5://")
        r.report_success(proxy)
        key = r._proxy_key(proxy)
        assert r._states[key].consecutive_fails == 0

    def test_socks5_with_auth_raises(self):
        with pytest.raises(ValueError, match="SOCKS5 with authentication"):
            ProxyRotator(["socks5://user:pass@proxy:15610"])
