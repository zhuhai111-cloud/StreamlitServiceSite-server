from __future__ import annotations

import gc
import re
import threading
import time
from typing import Iterable, Set

import tornado.httpserver
import tornado.web

from .handlers import route_specs

_MOUNTED: Set[int] = set()
_LOCK = threading.Lock()


def _looks_like_streamlit(app: tornado.web.Application) -> bool:
    try:
        text = repr(app.default_router.rules) + repr(app.wildcard_router.rules)
    except Exception:
        return False
    low = text.lower()
    return any(
        token in low
        for token in (
            "browserwebsockethandler",
            "streamlit.web.server",
            "_stcore",
            "hostconfighandler",
        )
    )


def _candidate_apps() -> Iterable[tornado.web.Application]:
    """Yield live Tornado applications, including those owned by HTTPServer."""
    seen: set[int] = set()
    for obj in gc.get_objects():
        app = None
        try:
            if isinstance(obj, tornado.web.Application):
                app = obj
            elif isinstance(obj, tornado.httpserver.HTTPServer):
                callback = getattr(obj, "request_callback", None)
                if isinstance(callback, tornado.web.Application):
                    app = callback
        except Exception:
            continue

        if app is None:
            continue
        app_id = id(app)
        if app_id in seen:
            continue
        seen.add(app_id)
        yield app


def _expanded_route_specs():
    specs = list(route_specs())
    try:
        from streamlit import config

        base = str(config.get_option("server.baseUrlPath") or "").strip("/")
    except Exception:
        base = ""

    if base:
        prefix = "/" + re.escape(base)
        specs.extend((prefix + pattern, handler) for pattern, handler in route_specs())
    return specs


def mount_api_routes() -> int:
    """Mount service routes on the live Streamlit Tornado application.

    Safe to call on every Streamlit script rerun. The return value is the
    number of matching Streamlit applications that are already ready or were
    newly patched during this call.
    """
    ready = 0
    with _LOCK:
        for app in _candidate_apps():
            app_id = id(app)
            if not _looks_like_streamlit(app):
                continue
            if app_id in _MOUNTED:
                ready += 1
                continue
            try:
                app.add_handlers(r".*$", _expanded_route_specs())
                _MOUNTED.add(app_id)
                ready += 1
                print(f"[service] ROUTES READY app={app_id}", flush=True)
            except Exception as ex:
                print(f"[service] ROUTE MOUNT FAILED: {ex}", flush=True)
    return ready


def mount_with_short_retry() -> None:
    if mount_api_routes() > 0:
        return

    def worker() -> None:
        for _ in range(40):
            time.sleep(0.25)
            if mount_api_routes() > 0:
                return
        print("[service] ROUTE MOUNT NOT FOUND", flush=True)

    thread = threading.Thread(target=worker, name="appservice-route-mounter", daemon=True)
    thread.start()
