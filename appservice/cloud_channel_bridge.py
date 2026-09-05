from __future__ import annotations

import hmac
import inspect

from .channel_handler import ServiceChannelHandler
from .settings import SETTINGS

_PATCH_FLAG = "_appservice_channel_v2_patched"


def patch_streamlit_channel_endpoint() -> bool:
    """Let Channel v2 share Streamlit's existing WebSocket endpoint.

    Streamlit Community Cloud reliably forwards its built-in ``/_stcore/stream``
    WebSocket. Requests marked with ``?appservice=v2`` are handled as service
    channels while ordinary Streamlit browser sockets keep their original
    behavior unchanged.
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

    def requested_service_mode(self) -> bool:
        try:
            if self.get_query_argument("appservice", "") == "v2":
                return True
        except Exception:
            pass
        return "X-App-Key" in self.request.headers

    def supplied_service_key(self) -> str:
        value = self.request.headers.get("X-App-Key", "")
        if value:
            return value
        protocols = self.request.headers.get("Sec-WebSocket-Protocol", "")
        parts = [part.strip() for part in protocols.split(",") if part.strip()]
        if len(parts) >= 2 and parts[0] == "appservice-v2":
            return parts[1]
        return ""

    def is_service(self) -> bool:
        return bool(getattr(self, "_appservice_channel_mode", False))

    def initialize(self, *args, **kwargs):
        original_initialize(self, *args, **kwargs)
        self._appservice_channel_mode = requested_service_mode(self)
        if self._appservice_channel_mode:
            ServiceChannelHandler.initialize(self)

    def prepare(self):
        if is_service(self):
            if not SETTINGS.service_key_configured:
                self.set_status(503)
                self.finish("Service key is not configured.")
                return None
            supplied = supplied_service_key(self)
            if not hmac.compare_digest(SETTINGS.service_key, supplied):
                self.set_status(401)
                self.finish("Invalid application key.")
                return None
            return None
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
            if "appservice-v2" in subprotocols:
                return "appservice-v2"
            return subprotocols[0] if subprotocols else None
        return original_select_subprotocol(self, subprotocols)

    BrowserWebSocketHandler.initialize = initialize
    BrowserWebSocketHandler.prepare = prepare
    BrowserWebSocketHandler.open = open_connection
    BrowserWebSocketHandler.on_message = on_message
    BrowserWebSocketHandler.on_close = on_close
    BrowserWebSocketHandler.check_origin = check_origin
    BrowserWebSocketHandler.select_subprotocol = select_subprotocol

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
