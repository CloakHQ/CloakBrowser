"""SOCKS5 UDP Protocol Implementation (RFC 1928).

This module implements the SOCKS5 UDP ASSOCIATE protocol for tunneling
UDP traffic (QUIC, WebRTC) through SOCKS5 proxies.

References:
    - RFC 1928: https://datatracker.ietf.org/doc/html/rfc1928
    - RFC 1929: Authentication methods
"""

import asyncio
import socket
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Tuple


class ATYP(IntEnum):
    """Address type constants."""
    IPv4 = 0x01
    DOMAIN = 0x03
    IPv6 = 0x04


class SOCKS5Error(Exception):
    """Base exception for SOCKS5 errors."""
    pass


class SOCKS5AuthError(SOCKS5Error):
    """Authentication failed."""
    pass


class SOCKS5ConnectionError(SOCKS5Error):
    """Connection failed."""
    pass


class SOCKS5UDPError(SOCKS5Error):
    """UDP operation failed."""
    pass


@dataclass
class UDPDatagram:
    """SOCKS5 UDP datagram structure."""
    rsv: int  # Reserved (2 bytes, must be 0x0000)
    frag: int  # Fragment number (1 byte)
    atyp: int  # Address type (1 byte)
    dst_addr: str  # Destination address
    dst_port: int  # Destination port
    data: bytes  # Payload data

    def pack(self) -> bytes:
        """Pack datagram to bytes."""
        # Pack address based on type
        if self.atyp == ATYP.IPv4:
            addr_bytes = socket.inet_aton(self.dst_addr)
        elif self.atyp == ATYP.IPv6:
            addr_bytes = socket.inet_pton(socket.AF_INET6, self.dst_addr)
        elif self.atyp == ATYP.DOMAIN:
            addr_bytes = struct.pack('B', len(self.dst_addr)) + self.dst_addr.encode()
        else:
            raise SOCKS5UDPError(f"Invalid address type: {self.atyp}")
        
        # Build header: RSV (2) + FRAG (1) + ATYP (1) + ADDR + PORT (2)
        header = struct.pack('!HBB', self.rsv, self.frag, self.atyp)
        port_bytes = struct.pack('!H', self.dst_port)
        
        return header + addr_bytes + port_bytes + self.data

    @classmethod
    def unpack(cls, data: bytes) -> Tuple['UDPDatagram', int]:
        """Unpack datagram from bytes. Returns (datagram, bytes_consumed)."""
        if len(data) < 10:
            raise SOCKS5UDPError("Datagram too short")
        
        rsv, frag, atyp = struct.unpack('!HBB', data[:4])
        offset = 4
        
        # Parse address
        if atyp == ATYP.IPv4:
            dst_addr = socket.inet_ntoa(data[offset:offset+4])
            offset += 4
        elif atyp == ATYP.IPv6:
            dst_addr = socket.inet_ntop(socket.AF_INET6, data[offset:offset+16])
            offset += 16
        elif atyp == ATYP.DOMAIN:
            addr_len = data[offset]
            offset += 1
            dst_addr = data[offset:offset+addr_len].decode()
            offset += addr_len
        else:
            raise SOCKS5UDPError(f"Invalid address type: {atyp}")
        
        # Parse port
        dst_port = struct.unpack('!H', data[offset:offset+2])[0]
        offset += 2
        
        # Remaining data is payload
        payload = data[offset:]
        
        datagram = cls(
            rsv=rsv,
            frag=frag,
            atyp=atyp,
            dst_addr=dst_addr,
            dst_port=dst_port,
            data=payload
        )
        
        return datagram, offset + len(payload)


async def socks5_connect(
    host: str,
    port: int,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: float = 10.0
) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Establish TCP connection to SOCKS5 server and authenticate.
    
    Args:
        host: SOCKS5 server hostname
        port: SOCKS5 server port
        username: Optional username for authentication
        password: Optional password for authentication
        timeout: Connection timeout in seconds
        
    Returns:
        Tuple of (reader, writer) for the connected stream
        
    Raises:
        SOCKS5ConnectionError: If connection fails
        SOCKS5AuthError: If authentication fails
    """
    # Connect to SOCKS5 server
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
        raise SOCKS5ConnectionError(f"Failed to connect to {host}:{port}: {e}")
    
    try:
        # Send greeting
        if username and password:
            # Username/password authentication
            greeting = struct.pack('!BBB', 0x05, 0x01, 0x02)  # VER=5, NMETHODS=1, METHODS=0x02
        else:
            # No authentication
            greeting = struct.pack('!BBB', 0x05, 0x01, 0x00)  # VER=5, NMETHODS=1, METHODS=0x00
        
        writer.write(greeting)
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        
        # Read server response
        response = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
        ver, method = struct.unpack('!BB', response)
        
        if ver != 0x05:
            raise SOCKS5ConnectionError(f"Invalid SOCKS version: {ver}")
        
        if method == 0xFF:
            raise SOCKS5AuthError("No acceptable authentication method")
        
        # Authenticate if required
        if method == 0x02 and username and password:
            # Send username/password
            auth_bytes = (
                struct.pack('!BB', 0x01, len(username)) +
                username.encode() +
                struct.pack('!B', len(password)) +
                password.encode()
            )
            writer.write(auth_bytes)
            await asyncio.wait_for(writer.drain(), timeout=timeout)
            
            # Read auth response
            auth_response = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
            auth_ver, auth_status = struct.unpack('!BB', auth_response)
            
            if auth_ver != 0x01:
                raise SOCKS5AuthError(f"Invalid auth version: {auth_ver}")
            
            if auth_status != 0x00:
                raise SOCKS5AuthError(f"Authentication failed: status={auth_status}")
        elif method != 0x00:
            raise SOCKS5AuthError(f"Unsupported authentication method: {method}")
        
        return reader, writer
        
    except Exception as e:
        writer.close()
        try:
            await writer.wait_closed()
        except:
            pass
        if isinstance(e, SOCKS5Error):
            raise
        raise SOCKS5ConnectionError(f"Connection error: {e}")


async def socks5_udp_associate(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    bind_addr: str = '0.0.0.0',
    bind_port: int = 0,
    timeout: float = 10.0
) -> Tuple[str, int]:
    """Send UDP ASSOCIATE request to SOCKS5 server.
    
    Args:
        reader: Stream reader from socks5_connect
        writer: Stream writer from socks5_connect
        bind_addr: Local address to bind UDP socket (default: 0.0.0.0)
        bind_port: Local port to bind UDP socket (default: 0 = auto)
        timeout: Timeout in seconds
        
    Returns:
        Tuple of (relay_host, relay_port) for UDP relay
        
    Raises:
        SOCKS5UDPError: If UDP ASSOCIATE fails
    """
    # Build UDP ASSOCIATE request
    # Using bind_addr:bind_port as the client endpoint (usually 0.0.0.0:0)
    try:
        addr_bytes = socket.inet_aton(bind_addr)
        atyp = ATYP.IPv4
    except OSError:
        try:
            addr_bytes = socket.inet_pton(socket.AF_INET6, bind_addr)
            atyp = ATYP.IPv6
        except OSError:
            raise SOCKS5UDPError(f"Invalid bind address: {bind_addr}")
    
    request = (
        struct.pack('!BBBB', 0x05, 0x03, 0x00, atyp) +  # VER, CMD=UDP ASSOCIATE, RSV, ATYP
        addr_bytes +
        struct.pack('!H', bind_port)
    )
    
    writer.write(request)
    await asyncio.wait_for(writer.drain(), timeout=timeout)
    
    # Read response (at least 10 bytes for IPv4)
    response = await asyncio.wait_for(reader.readexactly(10), timeout=timeout)
    
    ver, rep, rsv, atyp = struct.unpack('!BBBB', response[:4])
    
    if ver != 0x05:
        raise SOCKS5UDPError(f"Invalid SOCKS version in response: {ver}")
    
    if rep != 0x00:
        error_messages = {
            0x01: "General SOCKS server failure",
            0x02: "Connection not allowed by ruleset",
            0x03: "Network unreachable",
            0x04: "Host unreachable",
            0x05: "Connection refused",
            0x06: "TTL expired",
            0x07: "Command not supported",
            0x08: "Address type not supported",
        }
        raise SOCKS5UDPError(f"UDP ASSOCIATE failed: {error_messages.get(rep, f'Unknown error {rep}')}")
    
    # Parse relay address
    offset = 4
    if atyp == ATYP.IPv4:
        relay_addr = socket.inet_ntoa(response[offset:offset+4])
        offset += 4
    elif atyp == ATYP.IPv6:
        relay_addr = socket.inet_ntop(socket.AF_INET6, response[offset:offset+16])
        offset += 16
    elif atyp == ATYP.DOMAIN:
        addr_len = response[offset]
        offset += 1
        relay_addr = response[offset:offset+addr_len].decode()
        offset += addr_len
    else:
        raise SOCKS5UDPError(f"Invalid address type in response: {atyp}")
    
    relay_port = struct.unpack('!H', response[offset:offset+2])[0]
    
    return relay_addr, relay_port


def create_udp_datagram(
    data: bytes,
    dst_addr: str,
    dst_port: int,
    frag: int = 0
) -> bytes:
    """Create a SOCKS5 UDP datagram.
    
    Args:
        data: Payload data
        dst_addr: Destination address
        dst_port: Destination port
        frag: Fragment number (default 0)
        
    Returns:
        Packed UDP datagram
    """
    try:
        # Try IPv4
        socket.inet_aton(dst_addr)
        atyp = ATYP.IPv4
    except OSError:
        try:
            # Try IPv6
            socket.inet_pton(socket.AF_INET6, dst_addr)
            atyp = ATYP.IPv6
        except OSError:
            # Domain name
            atyp = ATYP.DOMAIN
    
    datagram = UDPDatagram(
        rsv=0x0000,
        frag=frag,
        atyp=atyp,
        dst_addr=dst_addr,
        dst_port=dst_port,
        data=data
    )
    
    return datagram.pack()
