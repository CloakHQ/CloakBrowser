# SOCKS5 UDP Support Implementation Plan

## Issue #62 - $2000 Bounty
**Goal**: Implement SOCKS5 UDP ASSOCIATE support for QUIC/WebRTC proxy in CloakBrowser

## Problem Analysis

Current CloakBrowser proxy support:
- ✅ HTTP/HTTPS proxies (TCP only)
- ✅ SOCKS5 proxies (TCP CONNECT only)
- ❌ SOCKS5 UDP ASSOCIATE (RFC 1928)
- ❌ QUIC-over-SOCKS5
- ❌ WebRTC UDP through SOCKS5

## Solution Architecture

### Approach: Hybrid Proxy Wrapper

Instead of modifying Chromium source (which requires building 2GB+ Chromium), we'll create a **local SOCKS5 UDP proxy wrapper** that:

1. **Intercepts UDP traffic** from Chromium
2. **Wraps UDP packets** in SOCKS5 UDP ASSOCIATE format
3. **Forwards to upstream SOCKS5 proxy**
4. **Unwraps responses** and delivers back to Chromium

### Components

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   CloakBrowser  │────▶│  socks5-udp-wrap │────▶│  SOCKS5 Proxy   │
│   (Chromium)    │ UDP │    (Local)        │ UDP │  (Upstream)     │
│                 │     │  Port: 10800      │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

### Implementation Phases

#### Phase 1: SOCKS5 UDP Client Library (Days 1-2)
- Implement RFC 1928 SOCKS5 UDP ASSOCIATE protocol
- Handle 10-byte UDP datagram headers
- Create Python async UDP client

#### Phase 2: Local Proxy Server (Days 3-4)
- Build local UDP proxy server (port 10800)
- Forward traffic through SOCKS5 UDP ASSOCIATE
- Handle connection pooling and keepalive

#### Phase 3: Chromium Integration (Days 5-6)
- Configure Chromium to use local proxy for QUIC
- Add `--proxy-server` arguments
- Test with QUIC-enabled sites (YouTube, Google)

#### Phase 4: WebRTC Support (Days 7-8)
- Patch WebRTC socket bindings
- Route WebRTC UDP through local proxy
- Prevent IP leaks

#### Phase 5: Testing & Documentation (Days 9-10)
- QUIC connectivity tests
- WebRTC IP leak tests
- Performance benchmarks
- Documentation

## File Structure

```
cloakbrowser/
├── socks5udp/
│   ├── __init__.py
│   ├── client.py        # SOCKS5 UDP client
│   ├── server.py        # Local UDP proxy server
│   ├── protocol.py      # RFC 1928 protocol helpers
│   └── launcher.py      # Integration with launch()
├── tests/
│   └── test_socks5_udp.py
└── examples/
    └── socks5_udp_example.py
```

## Technical Details

### SOCKS5 UDP ASSOCIATE (RFC 1928)

```
UDP Request Header:
+----+------+------+----------+----------+----------+
|RSV | FRAG | ATYP | DST.ADDR | DST.PORT |   DATA   |
+----+------+------+----------+----------+----------+
| 2  |  1   |  1   | Variable |    2     | Variable |
+----+------+------+----------+----------+----------+

ATYP:
- 0x01: IPv4 address
- 0x03: Domain name
- 0x04: IPv6 address
```

### Python Implementation

```python
import asyncio
import struct

async def socks5_udp_associate(socks5_host, socks5_port, username=None, password=None):
    # 1. Connect to SOCKS5 server (TCP)
    # 2. Authenticate (if required)
    # 3. Send UDP ASSOCIATE request
    # 4. Get UDP relay address
    # 5. Send/receive UDP packets through relay
    pass
```

## Testing Strategy

### QUIC Tests
```python
from cloakbrowser import launch

browser = launch(proxy="socks5://user:pass@proxy:1080", 
                 socks5_udp=True,  # New parameter
                 args=["--enable-quic"])
page = browser.new_page()
page.goto("https://www.youtube.com")  # Uses QUIC
# Verify IP matches proxy IP, not real IP
```

### WebRTC Tests
```python
# Check for IP leaks
page.goto("https://browserleaks.com/webrtc")
# Verify no local IP addresses exposed
```

## Acceptance Criteria

- [ ] SOCKS5 UDP ASSOCIATE protocol implemented correctly
- [ ] QUIC traffic routes through SOCKS5 proxy
- [ ] WebRTC traffic routes through SOCKS5 proxy
- [ ] No IP leaks (verified via browserleaks.com)
- [ ] Performance within 20% of direct connection
- [ ] Works with authenticated SOCKS5 proxies
- [ ] Comprehensive test suite
- [ ] Documentation and examples

## Payment
**USDT-TRC20**: `TMLkvEDrjvHEUbWYU1jfqyUKmbLNZkx6T1`

## References
- [RFC 1928 - SOCKS Protocol Version 5](https://datatracker.ietf.org/doc/html/rfc1928)
- [BotBrowser UDP-over-SOCKS5 Guide](https://github.com/botswin/BotBrowser/blob/main/docs/guides/network/UDP_OVER_SOCKS5.md)
- [enetx/surf](https://github.com/enetx/surf) - Inspiration project
- [Chromium net/socket/socks*](https://chromium.googlesource.com/chromium/src/+/master/net/socket/)
