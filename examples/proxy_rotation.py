"""Proxy rotation example: rotate through a pool of proxies with health tracking.

Usage:
    python examples/proxy_rotation.py

Replace the proxy URLs below with your actual proxy servers.
"""

from cloakbrowser import ProxyRotator, launch

# ---- 1. Basic setup: create a rotator with multiple proxies ----
# Supported proxy formats:
#   - "http://user:pass@host:port"        — HTTP with scheme
#   - "socks5://user:pass@host:port"      — SOCKS5 with scheme
#   - "user:pass@host:port"               — bare format (auto-detected as HTTP)
#   - {"server": "http://host:port", "username": "u", "password": "p"}  — Playwright dict
rotator = ProxyRotator(
    proxies=[
        "http://user:pass@proxy1.example.com:8080",
        "http://user:pass@proxy2.example.com:8080",
        "http://user:pass@proxy3.example.com:8080",
    ],
    strategy="round_robin",  # Options: round_robin, random, least_used, least_failures
)

# ---- 2. Simple usage: get next proxy for each browser launch ----
print(f"Pool: {rotator}")
print(f"Available: {rotator.available_count}/{len(rotator)}")

for i in range(3):
    proxy = rotator.next()
    print(f"\nRequest {i + 1}: Using proxy {proxy}")

    # In real usage:
    # browser = launch(proxy=proxy)
    # page = browser.new_page()
    # page.goto("https://example.com")
    # rotator.report_success(proxy)
    # browser.close()

    # Simulate success
    rotator.report_success(proxy)


# ---- 3. Context manager: auto-reports success/failure ----
print("\n--- Context manager ---")
try:
    with rotator.session() as proxy:
        print(f"Using proxy: {proxy}")
        # browser = launch(proxy=proxy)
        # ... do work ...
        # browser.close()
except Exception as e:
    print(f"Failed: {e}")


# ---- 4. Direct integration: pass rotator to launch() ----
print("\n--- Direct integration ---")
# CloakBrowser accepts ProxyRotator directly — it calls .next() internally
# browser = launch(proxy=rotator)
# page = browser.new_page()
# page.goto("https://example.com")
# # Use current() to report success/failure for the proxy that was used
# rotator.report_success(rotator.current())
# browser.close()
print("launch(proxy=rotator) — rotator.next() is called automatically")
print("rotator.current() — returns the proxy that was last selected")


# ---- 5. Sticky sessions: reuse the same proxy for N requests ----
print("\n--- Sticky sessions (3 requests per proxy) ---")
sticky_rotator = ProxyRotator(
    proxies=[
        "http://user:pass@proxy1.example.com:8080",
        "http://user:pass@proxy2.example.com:8080",
    ],
    strategy="round_robin",
    sticky_count=3,  # Use same proxy for 3 consecutive requests
)

for i in range(6):
    proxy = sticky_rotator.next()
    print(f"  Request {i + 1}: {proxy}")


# ---- 6. Health tracking & stats ----
print("\n--- Stats ---")
for stat in rotator.stats():
    print(f"  {stat['proxy']}: uses={stat['use_count']}, fails={stat['fail_count']}, available={stat['available']}")


# ---- 7. Dynamic pool management ----
print("\n--- Dynamic pool ---")
print(f"Before: {len(rotator)} proxies")
rotator.add("http://user:pass@proxy4.example.com:8080")
print(f"After add: {len(rotator)} proxies")
rotator.remove("http://user:pass@proxy4.example.com:8080")
print(f"After remove: {len(rotator)} proxies")


print("\nDone!")
