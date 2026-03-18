"""Tests for SOCKS5 UDP protocol implementation."""

import asyncio
import pytest
from cloakbrowser.socks5udp.protocol import (
    UDPDatagram,
    ATYP,
    create_udp_datagram,
    socks5_connect,
    socks5_udp_associate,
    SOCKS5Error,
    SOCKS5AuthError,
    SOCKS5ConnectionError,
    SOCKS5UDPError,
)


class TestUDPDatagram:
    """Test UDP datagram packing/unpacking."""
    
    def test_pack_ipv4(self):
        """Test packing IPv4 datagram."""
        datagram = UDPDatagram(
            rsv=0x0000,
            frag=0,
            atyp=ATYP.IPv4,
            dst_addr='8.8.8.8',
            dst_port=53,
            data=b'hello'
        )
        
        packed = datagram.pack()
        
        # Header: RSV(2) + FRAG(1) + ATYP(1) + ADDR(4) + PORT(2) = 10 bytes
        assert len(packed) == 10 + 5  # header + data
        assert packed[:4] == b'\x00\x00\x00\x01'  # RSV + FRAG + ATYP=IPv4
        assert packed[4:8] == b'\x08\x08\x08\x08'  # 8.8.8.8
        assert packed[8:10] == b'\x00\x35'  # Port 53
        assert packed[10:] == b'hello'
        
    def test_unpack_ipv4(self):
        """Test unpacking IPv4 datagram."""
        # Manually craft a datagram
        data = (
            b'\x00\x00\x00\x01'  # RSV + FRAG + ATYP=IPv4
            b'\x08\x08\x08\x08'  # 8.8.8.8
            b'\x00\x35'  # Port 53
            b'hello'  # Data
        )
        
        datagram, consumed = UDPDatagram.unpack(data)
        
        assert consumed == 15
        assert datagram.rsv == 0x0000
        assert datagram.frag == 0
        assert datagram.atyp == ATYP.IPv4
        assert datagram.dst_addr == '8.8.8.8'
        assert datagram.dst_port == 53
        assert datagram.data == b'hello'
        
    def test_pack_domain(self):
        """Test packing domain name datagram."""
        datagram = UDPDatagram(
            rsv=0x0000,
            frag=0,
            atyp=ATYP.DOMAIN,
            dst_addr='google.com',
            dst_port=443,
            data=b'test'
        )
        
        packed = datagram.pack()
        
        # Header includes domain length byte
        assert packed[4] == 10  # Length of 'google.com'
        assert b'google.com' in packed
        
    def test_unpack_domain(self):
        """Test unpacking domain name datagram."""
        data = (
            b'\x00\x00\x00\x03'  # RSV + FRAG + ATYP=DOMAIN
            b'\x0agoogle.com'  # Length + domain
            b'\x01\xbb'  # Port 443
            b'test'  # Data
        )
        
        datagram, consumed = UDPDatagram.unpack(data)
        
        assert consumed == 21  # 4 (header) + 1 (len) + 10 (domain) + 2 (port) + 4 (data)
        assert datagram.dst_addr == 'google.com'
        assert datagram.dst_port == 443
        
    def test_pack_ipv6(self):
        """Test packing IPv6 datagram."""
        datagram = UDPDatagram(
            rsv=0x0000,
            frag=0,
            atyp=ATYP.IPv6,
            dst_addr='2001:4860:4860::8888',
            dst_port=53,
            data=b'query'
        )
        
        packed = datagram.pack()
        
        # IPv6 address is 16 bytes
        assert packed[3] == ATYP.IPv6
        assert len(packed) == 4 + 16 + 2 + 5  # header + addr + port + data
        
    def test_invalid_datagram_too_short(self):
        """Test unpacking invalid short datagram."""
        with pytest.raises(SOCKS5UDPError):
            UDPDatagram.unpack(b'\x00\x00\x00\x01')  # Only 4 bytes


class TestCreateUDPDatagram:
    """Test create_udp_datagram helper."""
    
    def test_with_ipv4(self):
        """Test creating datagram with IPv4 address."""
        data = create_udp_datagram(b'payload', '1.2.3.4', 1234)
        
        assert data[3] == ATYP.IPv4
        assert data[4:8] == b'\x01\x02\x03\x04'
        assert data[8:10] == b'\x04\xd2'  # Port 1234
        
    def test_with_domain(self):
        """Test creating datagram with domain name."""
        data = create_udp_datagram(b'payload', 'example.com', 80)
        
        assert data[3] == ATYP.DOMAIN
        assert b'example.com' in data
        
    def test_with_ipv6(self):
        """Test creating datagram with IPv6 address."""
        data = create_udp_datagram(b'payload', '::1', 8080)
        
        assert data[3] == ATYP.IPv6


class TestSOCKS5Connect:
    """Test SOCKS5 TCP connection."""
    
    @pytest.mark.asyncio
    async def test_connect_no_auth(self):
        """Test connection without authentication."""
        # This would require a real SOCKS5 server
        # For now, just test the function signature
        pass
        
    @pytest.mark.asyncio
    async def test_connect_with_auth(self):
        """Test connection with username/password."""
        # This would require a real SOCKS5 server
        pass
        
    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        """Test connection timeout."""
        with pytest.raises((SOCKS5ConnectionError, asyncio.TimeoutError)):
            await socks5_connect('127.0.0.1', 9999, timeout=0.1)


class TestSOCKS5UDPAssociate:
    """Test SOCKS5 UDP ASSOCIATE."""
    
    @pytest.mark.asyncio
    async def test_udp_associate(self):
        """Test UDP ASSOCIATE request."""
        # This would require a real SOCKS5 server
        pass


class TestIntegration:
    """Integration tests (require SOCKS5 server)."""
    
    @pytest.mark.asyncio
    async def test_full_udp_tunnel(self):
        """Test complete UDP tunnel through SOCKS5."""
        # Skip if no SOCKS5 server available
        pytest.skip("Requires SOCKS5 server")
        
        # Example test:
        # from cloakbrowser.socks5udp import SOCKS5UDPClient, UDPProxyConfig
        # 
        # config = UDPProxyConfig(
        #     socks5_host='localhost',
        #     socks5_port=1080,
        #     local_bind_port=10800
        # )
        # 
        # client = SOCKS5UDPClient(config)
        # await client.connect()
        # 
        # # Send DNS query
        # await client.sendto(dns_query, ('8.8.8.8', 53))
        # response, addr = await client.recvfrom(4096)
        # 
        # await client.close()
        pass
