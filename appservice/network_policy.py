from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Iterable, Tuple

from .settings import SETTINGS


class AddressRejected(Exception):
    pass


def _is_allowed_ip(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    if SETTINGS.allow_private_addresses:
        return not ip.is_unspecified and not ip.is_multicast
    return not (
        ip.is_unspecified
        or ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
    )


def _resolve_allowed(host: str, port: int):
    host = (host or "").strip()
    if not host:
        raise AddressRejected("Host is required.")
    if port < 1 or port > 65535:
        raise AddressRejected("Port is invalid.")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as ex:
        raise AddressRejected(f"Target host could not be resolved: {ex}") from ex

    result = []
    seen = set()
    for family, socktype, proto, _canonname, sockaddr in infos:
        ip_text = sockaddr[0]
        key = (family, ip_text)
        if key in seen:
            continue
        seen.add(key)
        if _is_allowed_ip(ip_text):
            result.append((family, socktype, proto, sockaddr, ip_text))

    if not result:
        raise AddressRejected("Target host did not resolve to an allowed IP address.")
    return result


async def open_allowed_connection(host: str, port: int):
    infos = await asyncio.to_thread(_resolve_allowed, host, port)
    loop = asyncio.get_running_loop()
    last_error: BaseException | None = None

    for family, socktype, proto, sockaddr, ip_text in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setblocking(False)
            await asyncio.wait_for(
                loop.sock_connect(sock, sockaddr),
                timeout=SETTINGS.connect_timeout_seconds,
            )
            reader, writer = await asyncio.open_connection(sock=sock)
            return reader, writer, ip_text
        except BaseException as ex:
            last_error = ex
            try:
                sock.close()
            except OSError:
                pass

    if last_error is not None:
        raise OSError(f"Unable to connect to target: {last_error}") from last_error
    raise OSError("Unable to connect to target.")
