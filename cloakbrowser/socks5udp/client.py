"""SOCKS5 UDP Client for tunneling QUIC/WebRTC traffic.

This module provides an async UDP client that tunnels traffic through
SOCKS5 UDP ASSOCIATE proxies.
"""

import asyncio
import logging
import socket
from typing import Dict, Optional, Tuple, Callable, Any
from dataclasses import dataclass

from .protocol import (
    socks5_connect,
    socks5_udp_associate,
    create_udp_datagram,
    UDPDatagram,
    SOCKS5Error,
    SOCKS5ConnectionError,
    SOCKS5UDPError,
)

logger = logging.getLogger("cloakbrowser.socks5udp")


@dataclass
class UDPProxyConfig:
    """Configuration for SOCKS5 UDP proxy."""
    socks5_host: str
    socks5_port: int
    username: Optional[str] = None
    password: Optional[str] = None
    local_bind_host: str = '127.0.0.1'
    local_bind_port: int = 10800
    timeout: float = 30.0
    max_connections: int = 100


class SOCKS5UDPClient:
    """Async SOCKS5 UDP client for tunneling UDP traffic.
    
    This client establishes a UDP ASSOCIATE connection to a SOCKS5 proxy
    and provides a local UDP socket that forwards traffic through the proxy.
    
    Usage:
        client = SOCKS5UDPClient(config)
        await client.connect()
        
        # Send UDP packet
        await client.sendto(b'hello', ('8.8.8.8', 53))
        
        # Receive UDP packet
        data, addr = await client.recvfrom(4096)
        
        await client.close()
    """
    
    def __init__(self, config: UDPProxyConfig):
        self.config = config
        self._local_socket: Optional[asyncio.DatagramTransport] = None
        self._protocol: Optional['_UDPProtocol'] = None
        self._relay_addr: Optional[str] = None
        self._relay_port: Optional[int] = None
        self._tcp_writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._connection_map: Dict[Tuple[str, int], asyncio.Queue] = {}
        
    async def connect(self) -> None:
        """Establish connection to SOCKS5 proxy and set up UDP relay.
        
        Raises:
            SOCKS5ConnectionError: If connection to proxy fails
            SOCKS5UDPError: If UDP ASSOCIATE fails
        """
        logger.info(f"Connecting to SOCKS5 proxy at {self.config.socks5_host}:{self.config.socks5_port}")
        
        # Step 1: Establish TCP connection and authenticate
        reader, writer = await socks5_connect(
            self.config.socks5_host,
            self.config.socks5_port,
            self.config.username,
            self.config.password,
            self.config.timeout
        )
        
        # Step 2: Send UDP ASSOCIATE request
        self._relay_addr, self._relay_port = await socks5_udp_associate(
            reader,
            writer,
            self.config.local_bind_host,
            0,  # Let OS assign port
            self.config.timeout
        )
        
        logger.info(f"UDP relay established at {self._relay_addr}:{self._relay_port}")
        
        # Keep TCP connection open (required by SOCKS5 spec)
        self._tcp_writer = writer
        
        # Step 3: Create local UDP socket
        self._protocol = _UDPProtocol(self)
        
        loop = asyncio.get_event_loop()
        self._local_socket, _ = await loop.create_datagram_endpoint(
            lambda: self._protocol,
            local_addr=(self.config.local_bind_host, self.config.local_bind_port)
        )
        
        local_addr = self._local_socket.get_extra_info('sockname')
        logger.info(f"Local UDP socket bound to {local_addr}")
        
        self._connected = True
        
    async def sendto(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Send UDP packet through SOCKS5 proxy.
        
        Args:
            data: Payload data
            addr: Destination (host, port) tuple
            
        Raises:
            SOCKS5UDPError: If send fails
        """
        if not self._connected:
            raise SOCKS5UDPError("Not connected")
        
        if not self._relay_addr or not self._relay_port:
            raise SOCKS5UDPError("No UDP relay endpoint")
        
        # Wrap data in SOCKS5 UDP datagram
        datagram = create_udp_datagram(data, addr[0], addr[1])
        
        # Send to relay
        self._local_socket.sendto(datagram, (self._relay_addr, self._relay_port))
        logger.debug(f"Sent {len(data)} bytes to {addr[0]}:{addr[1]}")
        
    async def recvfrom(self, bufsize: int = 65535) -> Tuple[bytes, Tuple[str, int]]:
        """Receive UDP packet from SOCKS5 proxy.
        
        Args:
            bufsize: Maximum buffer size
            
        Returns:
            Tuple of (data, (host, port))
            
        Raises:
            SOCKS5UDPError: If receive fails
        """
        if not self._connected or not self._protocol:
            raise SOCKS5UDPError("Not connected")
        
        # Wait for data from protocol
        data, addr = await self._protocol.recv(bufsize)
        return data, addr
        
    async def close(self) -> None:
        """Close all connections."""
        self._connected = False
        
        if self._local_socket:
            self._local_socket.close()
            self._local_socket = None
            
        if self._tcp_writer:
            self._tcp_writer.close()
            try:
                await self._tcp_writer.wait_closed()
            except:
                pass
            self._tcp_writer = None
            
        if self._protocol:
            await self._protocol.close()
            self._protocol = None
            
        logger.info("SOCKS5 UDP client closed")
        
    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected
        
    @property
    def local_address(self) -> Optional[Tuple[str, int]]:
        """Get local socket address."""
        if self._local_socket:
            return self._local_socket.get_extra_info('sockname')
        return None


class _UDPProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for receiving packets from SOCKS5 relay."""
    
    def __init__(self, client: SOCKS5UDPClient):
        self.client = client
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        self._closed = False
        
    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        """Called when connection is established."""
        logger.debug("UDP connection made")
        
    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Called when UDP datagram is received from relay."""
        try:
            # Unwrap SOCKS5 UDP datagram
            datagram, _ = UDPDatagram.unpack(data)
            
            # Put in queue for recvfrom
            self._receive_queue.put_nowait((datagram.data, (datagram.dst_addr, datagram.dst_port)))
            
            logger.debug(f"Received {len(datagram.data)} bytes from {datagram.dst_addr}:{datagram.dst_port}")
            
        except Exception as e:
            logger.error(f"Error unpacking UDP datagram: {e}")
            
    def error_received(self, exc: Exception) -> None:
        """Called when an error is received."""
        logger.error(f"UDP error: {exc}")
        
    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Called when connection is lost."""
        logger.info(f"UDP connection lost: {exc}")
        self._closed = True
        
    async def recv(self, bufsize: int = 65535) -> Tuple[bytes, Tuple[str, int]]:
        """Wait for incoming data."""
        return await self._receive_queue.get()
        
    async def close(self) -> None:
        """Close protocol."""
        self._closed = True
        # Clear queue
        while not self._receive_queue.empty():
            try:
                self._receive_queue.get_nowait()
            except:
                pass


async def create_udp_tunnel(
    socks5_url: str,
    local_port: int = 10800
) -> SOCKS5UDPClient:
    """Convenience function to create a SOCKS5 UDP tunnel.
    
    Args:
        socks5_url: SOCKS5 proxy URL (e.g., 'socks5://user:pass@host:port')
        local_port: Local port to bind UDP socket
        
    Returns:
        Connected SOCKS5UDPClient instance
    """
    from urllib.parse import urlparse
    
    parsed = urlparse(socks5_url)
    
    config = UDPProxyConfig(
        socks5_host=parsed.hostname or '127.0.0.1',
        socks5_port=parsed.port or 1080,
        username=parsed.username,
        password=parsed.password,
        local_bind_port=local_port
    )
    
    client = SOCKS5UDPClient(config)
    await client.connect()
    
    return client
