from __future__ import annotations

import inspect

from .channel_handler import ServiceChannelHandler

_PATCH_FLAG = "_appservice_channel_v2_patched"


def patch_streamlit_channel_endpoint() -> bool:
    """Let Channel v2 share Streamlit's existing WebSocket endpoint.

    Streamlit Community Cloud forwards its built-in ``/_stcore/stream`` WebSocket
    reliably, while arbitrary application WebSocket paths are handled by the
    Cloud front door.  A request that carries ``X-App-Key`` is therefore treated
    as an application service channel; ordinary Streamlit browser connections
    continue to use the original handler unchanged.
    """
    try:
        from streamlit.web.server.browser_websocket_handler import BrowserWebSocketHandler
    except Exception:
        return False

    if getattr(BrowserWebSocketHandler, _PATCH_FLAG, False):
        return True

    original_initialize = BrowserWebSocketHandler.initialize
    original_prepare = BrowserWebSocketHandler.prepare
    original_open = BrowserWebSocketHandler.open
    original_on_message = BrowserWebSocketHandler.on_message
    original_on_close = BrowserWebSocketHandler.on_close
    original_check_origin = BrowserWebSocketHandler.check_origin
    original_select_subprotocol = BrowserWebSocketHandler.select_subprotocol

    def is_service(self) -> bool:
        return bool(getattr(self, "_appservice_channel_mode", False))

    def initialize(self, *args, **kwargs):
        original_initialize(self, *args, **kwargs)
        self._appservice_channel_mode = "X-App-Key" in self.request.headers
        if self._appservice_channel_mode:
            ServiceChannelHandler.initialize(self)

    def prepare(self):
        if is_service(self):
            return ServiceChannelHandler.prepare(self)
        return original_prepare(self)

    async def open_connection(self, *args, **kwargs):
        if is_service(self):
            return await ServiceChannelHandler.open(self)
        value = original_open(self, *args, **kwargs)
        if inspect.isawaitable(value):
            return await value
        return value

    async def on_message(self, message):
        if is_service(self):
            return await ServiceChannelHandler.on_message(self, message)
        value = original_on_message(self, message)
        if inspect.isawaitable(value):
            return await value
        return value

    def on_close(self):
        if is_service(self):
            return ServiceChannelHandler.on_close(self)
        return original_on_close(self)

    def check_origin(self, origin: str) -> bool:
        if is_service(self):
            return True
        return original_check_origin(self, origin)

    def select_subprotocol(self, subprotocols):
        if is_service(self):
            return subprotocols[0] if subprotocols else None
        return original_select_subprotocol(self, subprotocols)

    BrowserWebSocketHandler.initialize = initialize
    BrowserWebSocketHandler.prepare = prepare
    BrowserWebSocketHandler.open = open_connection
    BrowserWebSocketHandler.on_message = on_message
    BrowserWebSocketHandler.on_close = on_close
    BrowserWebSocketHandler.check_origin = check_origin
    BrowserWebSocketHandler.select_subprotocol = select_subprotocol

    # ServiceChannelHandler's message loop calls these helpers through ``self``.
    # Attach them to Streamlit's existing WebSocket handler so the same live
    # Tornado WebSocket instance can carry the multiplexed logical streams.
    for name in (
        "_handle_open",
        "_handle_data",
        "_pump_to_target",
        "_pump_from_target",
        "_send_frame",
        "_close_stream",
        "_close_all",
    ):
        setattr(BrowserWebSocketHandler, name, getattr(ServiceChannelHandler, name))

    setattr(BrowserWebSocketHandler, _PATCH_FLAG, True)
    print("[service] STREAM ENDPOINT READY", flush=True)
    return True
