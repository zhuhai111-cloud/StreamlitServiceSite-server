from __future__ import annotations

import asyncio
import hmac
import struct
from dataclasses import dataclass

import tornado.websocket

from .network_policy import AddressRejected, open_allowed_connection
from .settings import SETTINGS
from .state import STATE

FRAME_OPEN = 1
FRAME_OPEN_OK = 2
FRAME_OPEN_FAIL = 3
FRAME_DATA = 4
FRAME_CLOSE = 5

HEADER_SIZE = 5


@dataclass
class LogicalStream:
    stream_id: int
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    outgoing: asyncio.Queue[bytes | None]
    read_task: asyncio.Task | None = None
    write_task: asyncio.Task | None = None
    closed: bool = False


class ServiceChannelHandler(tornado.websocket.WebSocketHandler):
    def initialize(self) -> None:
        self._send_lock = asyncio.Lock()
        self._streams: dict[int, LogicalStream] = {}
        self._registered = False
        self._closing = False

    def check_origin(self, origin: str) -> bool:
        return True

    def prepare(self) -> None:
        if not SETTINGS.service_key_configured:
            self.set_status(503)
            self.finish("Service key is not configured.")
            return
        supplied = self.request.headers.get("X-App-Key", "")
        if not hmac.compare_digest(SETTINGS.service_key, supplied):
            self.set_status(401)
            self.finish("Invalid application key.")

    async def open(self) -> None:
        self.set_nodelay(True)
        self._registered = True
        STATE.channel_opened()
        print(f"[service] CHANNEL OPEN channels={STATE.channels} streams={STATE.streams}", flush=True)

    async def on_message(self, message) -> None:
        if not isinstance(message, (bytes, bytearray, memoryview)):
            self.close(code=1003, reason="Binary messages are required.")
            return
        data = bytes(message)
        if len(data) < HEADER_SIZE:
            self.close(code=1002, reason="Invalid frame.")
            return

        frame_type = data[0]
        stream_id = struct.unpack("!I", data[1:5])[0]
        payload = data[5:]
        if stream_id == 0:
            self.close(code=1002, reason="Invalid stream id.")
            return

        if frame_type == FRAME_OPEN:
            asyncio.create_task(self._handle_open(stream_id, payload))
        elif frame_type == FRAME_DATA:
            await self._handle_data(stream_id, payload)
        elif frame_type == FRAME_CLOSE:
            await self._close_stream(stream_id, notify=False)
        else:
            self.close(code=1002, reason="Unknown frame type.")

    def on_close(self) -> None:
        if self._registered:
            self._registered = False
            STATE.channel_closed()
        if not self._closing:
            self._closing = True
            try:
                asyncio.get_running_loop().create_task(self._close_all())
            except RuntimeError:
                pass
        print(f"[service] CHANNEL CLOSE channels={STATE.channels} streams={STATE.streams}", flush=True)

    async def _handle_open(self, stream_id: int, payload: bytes) -> None:
        if stream_id in self._streams:
            await self._send_frame(FRAME_OPEN_FAIL, stream_id, b"Duplicate stream id.")
            return
        if len(payload) < 4:
            await self._send_frame(FRAME_OPEN_FAIL, stream_id, b"Invalid open request.")
            return

        port, host_length = struct.unpack("!HH", payload[:4])
        if host_length < 1 or len(payload) != 4 + host_length:
            await self._send_frame(FRAME_OPEN_FAIL, stream_id, b"Invalid open request.")
            return
        try:
            host = payload[4:].decode("utf-8")
        except UnicodeDecodeError:
            await self._send_frame(FRAME_OPEN_FAIL, stream_id, b"Invalid host name.")
            return

        if not STATE.try_open_stream(SETTINGS.max_active_streams):
            await self._send_frame(FRAME_OPEN_FAIL, stream_id, b"Service stream capacity reached.")
            return

        counted = True
        try:
            reader, writer, _ip_text = await open_allowed_connection(host, port)
            stream = LogicalStream(
                stream_id=stream_id,
                reader=reader,
                writer=writer,
                outgoing=asyncio.Queue(maxsize=256),
            )
            self._streams[stream_id] = stream
            stream.write_task = asyncio.create_task(self._pump_to_target(stream))
            stream.read_task = asyncio.create_task(self._pump_from_target(stream))
            await self._send_frame(FRAME_OPEN_OK, stream_id)
            print(
                f"[service] STREAM OPEN {host}:{port} id={stream_id} "
                f"channels={STATE.channels} streams={STATE.streams}",
                flush=True,
            )
            counted = False
        except AddressRejected as ex:
            await self._send_frame(FRAME_OPEN_FAIL, stream_id, str(ex).encode("utf-8", "replace")[:1024])
        except Exception as ex:
            await self._send_frame(FRAME_OPEN_FAIL, stream_id, str(ex).encode("utf-8", "replace")[:1024])
        finally:
            if counted:
                STATE.stream_closed()

    async def _handle_data(self, stream_id: int, payload: bytes) -> None:
        stream = self._streams.get(stream_id)
        if stream is None or stream.closed:
            await self._send_frame(FRAME_CLOSE, stream_id)
            return
        if not payload:
            return
        if len(payload) > SETTINGS.frame_payload_bytes:
            await self._close_stream(stream_id, notify=True)
            return
        try:
            stream.outgoing.put_nowait(payload)
        except asyncio.QueueFull:
            await self._close_stream(stream_id, notify=True)

    async def _pump_to_target(self, stream: LogicalStream) -> None:
        try:
            while not stream.closed:
                data = await stream.outgoing.get()
                if data is None:
                    return
                stream.writer.write(data)
                await stream.writer.drain()
        except Exception:
            pass
        finally:
            await self._close_stream(stream.stream_id, notify=True)

    async def _pump_from_target(self, stream: LogicalStream) -> None:
        try:
            while not stream.closed:
                data = await stream.reader.read(SETTINGS.frame_payload_bytes)
                if not data:
                    return
                await self._send_frame(FRAME_DATA, stream.stream_id, data)
        except Exception:
            pass
        finally:
            await self._close_stream(stream.stream_id, notify=True)

    async def _send_frame(self, frame_type: int, stream_id: int, payload: bytes = b"") -> None:
        if self.ws_connection is None or self._closing:
            return
        frame = bytes((frame_type,)) + struct.pack("!I", stream_id) + payload
        try:
            async with self._send_lock:
                if self.ws_connection is not None and not self._closing:
                    await self.write_message(frame, binary=True)
        except Exception:
            pass

    async def _close_stream(self, stream_id: int, notify: bool) -> None:
        stream = self._streams.pop(stream_id, None)
        if stream is None:
            return
        if stream.closed:
            return
        stream.closed = True
        STATE.stream_closed()

        try:
            stream.outgoing.put_nowait(None)
        except asyncio.QueueFull:
            pass

        current = asyncio.current_task()
        for task in (stream.read_task, stream.write_task):
            if task is not None and task is not current and not task.done():
                task.cancel()

        try:
            stream.writer.close()
            await stream.writer.wait_closed()
        except Exception:
            pass

        if notify:
            await self._send_frame(FRAME_CLOSE, stream_id)
        print(
            f"[service] STREAM CLOSE id={stream_id} channels={STATE.channels} streams={STATE.streams}",
            flush=True,
        )

    async def _close_all(self) -> None:
        ids = list(self._streams.keys())
        for stream_id in ids:
            await self._close_stream(stream_id, notify=False)
