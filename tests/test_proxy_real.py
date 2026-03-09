"""Real proxy rotation tests — launches browsers with actual proxies.

Run: pytest tests/test_proxy_real.py -v -m slow
"""
import pytest
from cloakbrowser import ProxyRotator, launch

PROXIES = [
    "http://user:pass@proxy1.example.com:5610",
    "http://user:pass@proxy2.example.com:4586",
    "http://user:pass@proxy3.example.com:5906",
]


@pytest.mark.slow
class TestRoundRobin:
    def test_each_proxy_returns_unique_ip(self):
        rotator = ProxyRotator(proxies=PROXIES, strategy="round_robin")
        ips = []
        for i in range(3):
            proxy = rotator.next()
            browser = launch(headless=True, proxy=proxy)
            page = browser.new_page()
            page.goto("https://api.ipify.org?format=json", timeout=15000)
            ip = page.text_content("body")
            ips.append(ip)
            rotator.report_success(proxy)
            browser.close()
        assert len(set(ips)) == 3, f"Expected 3 unique IPs, got {set(ips)}"


@pytest.mark.slow
class TestSticky:
    def test_sticky_reuses_same_proxy(self):
        sticky = ProxyRotator(
            proxies=PROXIES[:2],
            strategy="round_robin",
            sticky_count=2,
        )
        ips = []
        for _ in range(4):
            proxy = sticky.next()
            browser = launch(headless=True, proxy=proxy)
            page = browser.new_page()
            page.goto("https://api.ipify.org?format=json", timeout=15000)
            ip = page.text_content("body")
            ips.append(ip)
            sticky.report_success(proxy)
            browser.close()
        assert ips[0] == ips[1], "Sticky: first 2 should match"
        assert ips[2] == ips[3], "Sticky: last 2 should match"
        assert ips[0] != ips[2], "Sticky: pairs should differ"


@pytest.mark.slow
class TestSession:
    def test_session_tracks_success(self):
        tracker = ProxyRotator(proxies=PROXIES, strategy="least_failures")
        with tracker.session() as proxy:
            browser = launch(headless=True, proxy=proxy)
            page = browser.new_page()
            page.goto("https://api.ipify.org?format=json", timeout=15000)
            ip = page.text_content("body")
            assert ip, "Should return IP"
            browser.close()
        stats = tracker.stats()
        total_fails = sum(s["fail_count"] for s in stats)
        assert total_fails == 0, "No failures expected"


class TestSocks5Validation:
    def test_socks5_with_auth_raises(self):
        with pytest.raises(ValueError, match="SOCKS5 with authentication"):
            ProxyRotator(["socks5://user:pass@host:1080"])

    def test_socks5_without_auth_accepted(self):
        r = ProxyRotator(["socks5://host:1080"])
        assert len(r) == 1

    def test_socks5_dict_with_auth_raises(self):
        with pytest.raises(ValueError, match="SOCKS5 with authentication"):
            ProxyRotator([{"server": "socks5://host:1080", "username": "u", "password": "p"}])

    def test_add_socks5_with_auth_raises(self):
        r = ProxyRotator(["http://proxy:8080"])
        with pytest.raises(ValueError, match="SOCKS5 with authentication"):
            r.add("socks5://user:pass@host:1080")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short", "-x"]))
