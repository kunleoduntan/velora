"""Outbound connections for webhooks that cannot be turned against the server's own network (SSRF).

Two things make that true, and both are needed:
  1. EVERY address the name resolves to is checked, including the IPv4 address hidden inside an IPv6 one (NAT64 `64:ff9b::7f00:1` is 127.0.0.1; `2002:a9fe:a9fe::` is the cloud
     metadata address). `ipaddress.is_global` alone accepts NAT64.
  2. The connection is made to the address that was CHECKED, not to the name. Checking a name and then letting the HTTP library resolve it again lets an attacker's DNS server
     answer with a public address for the check and 127.0.0.1 for the connection (DNS rebinding). TLS still verifies the certificate against the original hostname.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket


class UnsafeTarget(ValueError):
    """The address is not one an outbound webhook may reach. str() is a plain reason."""


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _ipv4_inside(ip):
    """The IPv4 address carried by an IPv6 TRANSLATION address (IPv4-mapped, or NAT64 as DNS64 synthesises for IPv4-only hosts), else None. Those addresses are reachable exactly
    as far as the IPv4 inside them, so that is what must be judged: Python marks the whole ranges 'reserved', which would wrongly refuse every IPv4-only host on an IPv6-only network."""
    if ip.version != 6:
        return None
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _internal(candidate) -> bool:
    return (not candidate.is_global or candidate.is_private or candidate.is_loopback or candidate.is_link_local or candidate.is_reserved or candidate.is_multicast
            or candidate.is_unspecified)


def blocked_reason(address: str) -> str | None:
    """Why this address may not be contacted, or None if it is an ordinary public address."""
    ip = ipaddress.ip_address(address)
    inner = _ipv4_inside(ip)
    if inner is not None:
        return f"{address} contains the private/internal address {inner}" if _internal(inner) else None
    if _internal(ip):
        return f"{address} is a private/internal address"
    for hidden in ([ip.sixtofour] if ip.version == 6 and ip.sixtofour else []) + list(ip.teredo or () if ip.version == 6 else ()):
        if _internal(hidden):
            return f"{address} contains the private/internal address {hidden}"
    return None


def resolve(host: str, port: int, allow_private: bool = False) -> list[str]:
    """The addresses to connect to. Every one is validated: a single bad answer refuses the whole name (an attacker could otherwise hide one among public ones)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise UnsafeTarget(f"cannot resolve {host}") from None
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise UnsafeTarget(f"cannot resolve {host}")
    if not allow_private:
        for address in addresses:
            reason = blocked_reason(address)
            if reason:
                raise UnsafeTarget(f"{host} resolves to a private/internal address ({reason})")
    return addresses


class PinnedHTTPConnection(http.client.HTTPConnection):
    """Connects to `pinned_ip`, whatever the hostname would resolve to now."""

    def __init__(self, host, port=None, *, pinned_ip, **kw):
        super().__init__(host, port, **kw)
        self._pinned_ip = pinned_ip

    def connect(self):
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """As above, over TLS: the certificate is verified against the ORIGINAL hostname (SNI and name checking use `self.host`)."""

    def __init__(self, host, port=None, *, pinned_ip, **kw):
        super().__init__(host, port, **kw)
        self._pinned_ip = pinned_ip

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
