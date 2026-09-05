from __future__ import annotations

import gc
import threading
import time
from typing import Set

import tornado.web

from .handlers import route_specs

_MOUNTED: Set[int] = set()
_LOCK = threading.Lock()


def _looks_like_streamlit(app: tornado.web.Application) -> bool:
    try:
        text = repr(app.default_router.rules) + repr(app.wildcard_router.rules)
    except Exception:
        return False
    return "streamlit" in text.lower() or "_stcore" in text.lower()


def mount_api_routes() -> int:
    """Mount API routes on the live Streamlit Tornado application.

    This is safe to call on every Streamlit script rerun. Returns the number of
    newly patched Application objects.
    """
    mounted = 0
    with _LOCK:
        for obj in gc.get_objects():
            try:
                if not isinstance(obj, tornado.web.Application):
                    continue
            except Exception:
                continue
            app_id = id(obj)
            if app_id in _MOUNTED or not _looks_like_streamlit(obj):
                continue
            try:
                # add_handlers creates a host rule before Tornado's final wildcard
                # host rule, so these exact API paths take precedence over the
                # Streamlit frontend catch-all without changing normal UI routes.
                obj.add_handlers(r".*$", route_specs())
                _MOUNTED.add(app_id)
                mounted += 1
            except Exception:
                continue
    return mounted


def mount_with_short_retry() -> None:
    if mount_api_routes() > 0:
        return

    def worker() -> None:
        for _ in range(20):
            time.sleep(0.25)
            if mount_api_routes() > 0:
                return

    thread = threading.Thread(target=worker, name="appservice-route-mounter", daemon=True)
    thread.start()
