# Proxy & Network Stealth

CloakBrowser provides robust proxy and network-layer masking: full traffic routing, WebRTC exit IP spoofing, GeoIP location matching, and automated proxy timing/cache header stripping.

---

## 1. Preemptive Proxy Authentication (The Stealth Advantage)

Standard Playwright routes proxies using CDP authentication interceptors. When a page requests a resource, Playwright intercepts it and responds with credentials. Advanced bot-detection systems flag this CDP intercept pattern instantly, and it frequently fails on Google authentication portals.

CloakBrowser bypasses this entirely:
- **SOCKS5 Proxies**: Routed natively inside Chrome's network engine, with inline credentials.
- **HTTP/HTTPS Proxies**: Re-routes inline credentials directly into the binary's `--proxy-server` command-line flag on compatible platforms. Chrome sends the `Proxy-Authorization` header preemptively, avoiding the detectable 407 challenge-response loop.

### Supported Formats:
```python
from cloakbrowser import launch

# HTTP Proxy with credentials
browser = launch(proxy="http://user:pass@proxy.example.com:8080")

# SOCKS5 Proxy with credentials (UDP Associate tunnels through native Chrome)
browser = launch(proxy="socks5://user:pass@socks-proxy.example.com:1080")

# Dict compatibility (Auto-converted internally into stealth inline format)
browser = launch(proxy={
    "server": "http://proxy.example.com:8080",
    "username": "user",
    "password": "pass",
})
```

---

## 2. WebRTC IP Spoofing

WebRTC (Web Real-Time Communication) can leak your real, underlying local or ISP IP address even when all standard traffic is routed through a proxy.

CloakBrowser implements binary WebRTC ICE candidate interceptors. You can configure WebRTC IP spoofing manually or let it resolve automatically:

```python
# 1. Automatic Resolution: Fetches your proxy exit IP and feeds it to WebRTC.
# (Performs a single, proxied HTTP check to AWS checkip or ipify)
browser = launch(
    proxy="http://user:pass@proxy:8080",
    args=["--fingerprint-webrtc-ip=auto"]
)

# 2. Manual Configuration: Explicitly specify the IP to return.
# (Zero network overhead)
browser = launch(
    proxy="http://user:pass@proxy:8080",
    args=["--fingerprint-webrtc-ip=203.0.113.19"]
)
```

---

## 3. GeoIP Auto-Matching (Timezone & Locale)

Residential and rotating proxies constantly change locations. If your proxy IP is in London, but your browser's language is set to `zh-CN` and the timezone is `Asia/Shanghai`, bot fingerprinters (like FingerprintJS and DataDome) will flag the location mismatch.

CloakBrowser solves this with the `geoip` argument:

```python
# Requires: pip install cloakbrowser[geoip]
browser = launch(
    proxy="http://user:pass@my-rotating-proxy:8080",
    geoip=True,  # Auto-adjusts timezone + locale to match proxy exit IP
)
```
*How it works*: On startup, the launcher contacts the proxy, retrieves the geolocation of the exit IP, maps it to IANA database timezone/locale structures, and configures the Chromium binary's internal clock and localization variables. It also automatically sets the `--fingerprint-webrtc-ip` candidate to the proxy IP at zero extra network cost.

If you don't want the GeoIP network lookup overhead, configure timezone and locale manually:
```python
browser = launch(
    proxy="http://user:pass@proxy:8080",
    timezone="Europe/London",
    locale="en-GB",
)
```

---

## 4. Proxy Signal Stripping

In addition to routing and IP spoofing, CloakBrowser's custom Chromium binary strips specific network signatures that flag proxy environments:
- **DNS Lookup Timing**: Standard proxied requests show inconsistent DNS response timing signatures. CloakBrowser normalizes and zeroes out internal DNS resolution latency metrics.
- **TCP & SSL Handshake Timings**: Timing values are normalized to match standard native Windows/macOS Chrome profiles.
- **Header Leaks**: Strips `Proxy-Connection` headers and proxy-specific caching protocols.
