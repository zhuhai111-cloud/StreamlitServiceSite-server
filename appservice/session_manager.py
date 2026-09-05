from __future__ import annotations

import ipaddress
import select
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from .settings import SETTINGS


class SessionError(Exception):
    pass


class RejectedTarget(SessionError):
    pass


class SessionNotFound(SessionError):
    pass


@dataclass
class TcpSession:
    id: str
    sock: socket.socket
    target_host: str
    target_port: int
    target_ip: str
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    receive_lock: threading.Lock = field(default_factory=threading.Lock)
    close_lock: threading.Lock = field(default_factory=threading.Lock)
    closed: bool = False

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def close(self) -> None:
        with self.close_lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, TcpSession] = {}
        self._lock = threading.RLock()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="appservice-session-cleaner",
            daemon=True,
        )
        self._cleanup_thread.start()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _is_allowed_ip(self, text: str) -> bool:
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

    def _resolve_allowed(self, host: str, port: int):
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as ex:
            raise RejectedTarget(f"Target host could not be resolved: {ex}") from ex

        result = []
        seen = set()
        for family, socktype, proto, canonname, sockaddr in infos:
            ip_text = sockaddr[0]
            key = (family, ip_text)
            if key in seen:
                continue
            seen.add(key)
            if self._is_allowed_ip(ip_text):
                result.append((family, socktype, proto, sockaddr, ip_text))

        if not result:
            raise RejectedTarget("Target host did not resolve to an allowed IP address.")
        return result

    def open(self, host: str, port: int) -> TcpSession:
        host = (host or "").strip()
        if not host:
            raise RejectedTarget("Host is required.")
        if port < 1 or port > 65535:
            raise RejectedTarget("Port is invalid.")
        with self._lock:
            if len(self._sessions) >= SETTINGS.max_concurrent_sessions:
                raise SessionError("Server has reached the maximum number of active sessions.")

        last_error: Optional[BaseException] = None
        for family, socktype, proto, sockaddr, ip_text in self._resolve_allowed(host, port):
            sock = socket.socket(family, socktype, proto)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(SETTINGS.connect_timeout_seconds)
                sock.connect(sockaddr)
                sock.settimeout(30.0)
                session = TcpSession(
                    id=uuid.uuid4().hex,
                    sock=sock,
                    target_host=host,
                    target_port=port,
                    target_ip=ip_text,
                )
                with self._lock:
                    if len(self._sessions) >= SETTINGS.max_concurrent_sessions:
                        session.close()
                        raise SessionError("Server has reached the maximum number of active sessions.")
                    self._sessions[session.id] = session
                    active = len(self._sessions)
                print(f"[service] OPEN {host}:{port} active={active}", flush=True)
                return session
            except BaseException as ex:
                last_error = ex
                try:
                    sock.close()
                except OSError:
                    pass

        if isinstance(last_error, SessionError):
            raise last_error
        if last_error is not None:
            raise SessionError(f"Unable to connect to target: {last_error}") from last_error
        raise SessionError("Unable to connect to target.")

    def get(self, session_id: str) -> TcpSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None or session.closed:
            raise SessionNotFound("Session not found or expired.")
        return session

    def remove(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.close()
        with self._lock:
            active = len(self._sessions)
        print(f"[service] CLOSE {session.target_host}:{session.target_port} active={active}", flush=True)
        return True

    def send(self, session_id: str, data: bytes) -> int:
        session = self.get(session_id)
        if len(data) > SETTINGS.max_send_bytes:
            raise SessionError("Request block is too large.")
        if not data:
            return 0
        try:
            with session.send_lock:
                if session.closed:
                    raise SessionNotFound("Session not found or expired.")
                session.sock.sendall(data)
                session.touch()
                return len(data)
        except (OSError, socket.timeout) as ex:
            self.remove(session_id)
            raise SessionError(f"Target send failed: {ex}") from ex

    def receive(self, session_id: str, wait_seconds: float, max_bytes: int) -> Tuple[str, bytes]:
        session = self.get(session_id)
        wait_seconds = max(0.0, min(float(wait_seconds), float(SETTINGS.max_long_poll_seconds)))
        max_bytes = max(1024, min(int(max_bytes), SETTINGS.max_receive_bytes))
        try:
            with session.receive_lock:
                if session.closed:
                    return "closed", b""
                readable, _, exceptional = select.select([session.sock], [], [session.sock], wait_seconds)
                if exceptional:
                    self.remove(session_id)
                    return "closed", b""
                if not readable:
                    return "idle", b""
                data = session.sock.recv(max_bytes)
                if not data:
                    self.remove(session_id)
                    return "closed", b""
                session.touch()
                return "data", data
        except (OSError, socket.timeout, ValueError):
            self.remove(session_id)
            return "closed", b""

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(15.0)
            cutoff = time.monotonic() - SETTINGS.session_idle_timeout_seconds
            stale = []
            with self._lock:
                for sid, session in self._sessions.items():
                    if session.last_activity < cutoff:
                        stale.append(sid)
            for sid in stale:
                self.remove(sid)


MANAGER = SessionManager()
