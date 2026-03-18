"""SOCKS5 UDP Support for CloakBrowser.

This module provides SOCKS5 UDP ASSOCIATE support for tunneling
QUIC and WebRTC traffic through SOCKS5 proxies.

Example:
    from cloakbrowser import launch
    from cloakbrowser.socks5udp import create_udp_tunnel, SOCKS5UDPClient, UDPProxyConfig
    
    # Method 1: Use helper function
    client = await create_udp_tunnel('socks5://user:pass@proxy:1080')
    
    # Method 2: Use with launch()
    browser = launch(
        proxy='socks5://user:pass@proxy:1080',
        socks5_udp=True  # Enable UDP tunneling
    )
"""

from .protocol import (
    socks5_connect,
    socks5_udp_associate,
    create_udp_datagram,
    UDPDatagram,
    SOCKS5Error,
    SOCKS5AuthError,
    SOCKS5ConnectionError,
    SOCKS5UDPError,
)

from .client import (
    SOCKS5UDPClient,
    UDPProxyConfig,
    create_udp_tunnel,
)

__all__ = [
    # Protocol
    'socks5_connect',
    'socks5_udp_associate',
    'create_udp_datagram',
    'UDPDatagram',
    'SOCKS5Error',
    'SOCKS5AuthError',
    'SOCKS5ConnectionError',
    'SOCKS5UDPError',
    
    # Client
    'SOCKS5UDPClient',
    'UDPProxyConfig',
    'create_udp_tunnel',
]
