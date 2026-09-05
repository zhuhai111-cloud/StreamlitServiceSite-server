from __future__ import annotations

import hmac
import json
from datetime import datetime, timezone

import tornado.web

from .channel_handler import ServiceChannelHandler
from .settings import SETTINGS
from .state import STATE

API_PREFIX = r"/api/service/v2"
CLOUD_PREFIX = r"/_stcore/appservice/v2"


class ApiHandler(tornado.web.RequestHandler):
    def set_default_headers(self) -> None:
        self.set_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.set_header("Pragma", "no-cache")
        self.set_header("X-Content-Type-Options", "nosniff")

    def check_xsrf_cookie(self) -> None:
        return

    def prepare(self) -> None:
        if not SETTINGS.service_key_configured:
            self._finish_json(503, {"error": "Server API key is not configured."})
            return
        supplied = self.request.headers.get("X-App-Key", "")
        if not hmac.compare_digest(SETTINGS.service_key, supplied):
            self._finish_json(401, {"error": "Invalid application key."})

    def _finish_json(self, status: int, value: object) -> None:
        if self._finished:
            return
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.finish(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


class HealthHandler(ApiHandler):
    async def get(self) -> None:
        self._finish_json(
            200,
            {
                "status": "ok",
                "mode": "service-channel-v2",
                "apiPrefix": "/api/service/v2",
                "cloudApiPrefix": "/_stcore/appservice/v2",
                "activeChannels": STATE.channels,
                "activeStreams": STATE.streams,
                "maxStreams": SETTINGS.max_active_streams,
                "targetPorts": "1-65535",
                "utc": datetime.now(timezone.utc).isoformat(),
            },
        )


def route_specs():
    return [
        (API_PREFIX + r"/health/?", HealthHandler),
        (API_PREFIX + r"/channel/?", ServiceChannelHandler),
        (CLOUD_PREFIX + r"/health/?", HealthHandler),
        (CLOUD_PREFIX + r"/channel/?", ServiceChannelHandler),
    ]
