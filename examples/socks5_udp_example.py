"""Example: Using SOCKS5 UDP for QUIC/WebRTC proxy.

This example demonstrates how to use SOCKS5 UDP ASSOCIATE support
to tunnel QUIC and WebRTC traffic through a SOCKS5 proxy.
"""

import asyncio
from cloakbrowser import launch
from cloakbrowser.socks5udp import create_udp_tunnel, SOCKS5UDPClient, UDPProxyConfig


async def example_basic_socks5_udp():
    """Basic example with SOCKS5 UDP enabled."""
    print("=== Basic SOCKS5 UDP Example ===")
    
    # Launch browser with SOCKS5 UDP support
    browser = launch(
        proxy='socks5://user:pass@proxy.example.com:1080',
        socks5_udp=True,  # Enable UDP tunneling
        socks5_udp_port=10800,  # Local UDP relay port
        headless=True,
        args=['--enable-quic']  # Enable QUIC protocol
    )
    
    page = browser.new_page()
    
    # Test QUIC-enabled site (YouTube uses QUIC)
    print("Navigating to YouTube (uses QUIC)...")
    page.goto('https://www.youtube.com')
    print(f"Title: {page.title()}")
    
    # Check for IP leaks
    print("\nChecking for IP leaks...")
    page.goto('https://browserleaks.com/webrtc')
    
    # Take screenshot
    page.screenshot(path='webrtc_test.png')
    print("Screenshot saved to webrtc_test.png")
    
    browser.close()
    print("Done!")


async def example_manual_udp_client():
    """Example using SOCKS5 UDP client directly."""
    print("=== Manual SOCKS5 UDP Client Example ===")
    
    # Create UDP tunnel
    config = UDPProxyConfig(
        socks5_host='proxy.example.com',
        socks5_port=1080,
        username='user',
        password='pass',
        local_bind_port=10800
    )
    
    client = SOCKS5UDPClient(config)
    await client.connect()
    
    print(f"Connected! Local UDP socket: {client.local_address}")
    
    # Send DNS query over SOCKS5 UDP
    dns_query = bytes([
        0x12, 0x34,  # Transaction ID
        0x01, 0x00,  # Flags: standard query
        0x00, 0x01,  # Questions: 1
        0x00, 0x00,  # Answer RRs: 0
        0x00, 0x00,  # Authority RRs: 0
        0x00, 0x00,  # Additional RRs: 0
        # Query: google.com
        0x06, ord('g'), ord('o'), ord('o'), ord('g'), ord('l'), ord('e'),
        0x03, ord('c'), ord('o'), ord('m'),
        0x00,  # Null terminator
        0x00, 0x01,  # Type: A
        0x00, 0x01,  # Class: IN
    ])
    
    print("Sending DNS query...")
    await client.sendto(dns_query, ('8.8.8.8', 53))
    
    print("Waiting for response...")
    response, addr = await client.recvfrom(4096)
    print(f"Received {len(response)} bytes from {addr}")
    
    await client.close()
    print("Client closed")


async def example_quic_test():
    """Test QUIC connectivity through SOCKS5 proxy."""
    print("=== QUIC Connectivity Test ===")
    
    browser = launch(
        proxy='socks5://user:pass@proxy.example.com:1080',
        socks5_udp=True,
        headless=True,
        args=[
            '--enable-quic',
            '--quic-version=h3-29',
        ]
    )
    
    page = browser.new_page()
    
    # Test sites that use QUIC
    quic_sites = [
        'https://www.youtube.com',
        'https://www.google.com',
        'https://www.facebook.com',
    ]
    
    for site in quic_sites:
        print(f"\nTesting {site}...")
        try:
            response = page.goto(site, wait_until='domcontentloaded')
            if response:
                print(f"  Status: {response.status}")
                print(f"  Title: {page.title()}")
        except Exception as e:
            print(f"  Error: {e}")
    
    browser.close()


def main():
    """Run examples."""
    print("SOCKS5 UDP Examples for CloakBrowser\n")
    print("Note: Replace proxy.example.com with your actual SOCKS5 proxy\n")
    
    # Uncomment to run examples:
    # asyncio.run(example_basic_socks5_udp())
    # asyncio.run(example_manual_udp_client())
    # asyncio.run(example_quic_test())
    
    print("Uncomment the example you want to run in main()")


if __name__ == '__main__':
    main()
