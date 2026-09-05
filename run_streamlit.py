from __future__ import annotations

import os
from pathlib import Path

from streamlit import config as _config
from streamlit.web import bootstrap
from streamlit.web.server.server import Server

_ORIGINAL_CREATE_APP = Server._create_app


def _create_app_with_service_routes(self: Server):
    # Delay importing the service package until Streamlit has loaded the app's
    # config/secrets path. This keeps secrets.toml and environment handling
    # identical between local and hosted deployments.
    from appservice.handlers import route_specs

    app = _ORIGINAL_CREATE_APP(self)
    # Add the service API to the very same Tornado app and listening port used by
    # Streamlit. Normal Streamlit UI, websocket, static and health paths remain
    # unchanged because this API uses its own /api/service/v1 namespace.
    app.add_handlers(r".*$", route_specs())
    return app


def main() -> None:
    app_path = str(Path(__file__).with_name("app.py").resolve())
    port = int(os.environ.get("PORT", os.environ.get("STREAMLIT_SERVER_PORT", "8501")))

    flag_options = {
        "server_address": "0.0.0.0",
        "server_port": port,
        "server_headless": True,
    }
    _config._main_script_path = app_path
    bootstrap.load_config_options(flag_options=flag_options)

    # app.py keeps a runtime-mount fallback for ordinary `streamlit run app.py`,
    # but the supported launcher pre-mounts routes before the port starts.
    os.environ["APP_ROUTES_READY"] = "1"
    Server._create_app = _create_app_with_service_routes
    bootstrap.run(app_path, False, [], flag_options)


if __name__ == "__main__":
    main()
