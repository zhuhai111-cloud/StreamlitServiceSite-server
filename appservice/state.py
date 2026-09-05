from __future__ import annotations

import threading


class ServiceState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._channels = 0
        self._streams = 0

    @property
    def channels(self) -> int:
        with self._lock:
            return self._channels

    @property
    def streams(self) -> int:
        with self._lock:
            return self._streams

    def channel_opened(self) -> None:
        with self._lock:
            self._channels += 1

    def channel_closed(self) -> None:
        with self._lock:
            self._channels = max(0, self._channels - 1)

    def try_open_stream(self, maximum: int) -> bool:
        with self._lock:
            if self._streams >= maximum:
                return False
            self._streams += 1
            return True

    def stream_closed(self) -> None:
        with self._lock:
            self._streams = max(0, self._streams - 1)


STATE = ServiceState()
