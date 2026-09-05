from __future__ import annotations

import os
from dataclasses import dataclass

PLACEHOLDER_SERVICE_KEY = "CHANGE_THIS_LONG_RANDOM_KEY"


def _secret(env_name: str, default: str) -> str:
    if env_name in os.environ:
        return os.environ[env_name]
    try:
        import streamlit as st
        value = st.secrets.get(env_name, default)
        return str(value)
    except Exception:
        return default


def _bool(env_name: str, default: bool) -> bool:
    value = _secret(env_name, "true" if default else "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _int(env_name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(_secret(env_name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class Settings:
    service_key: str
    connect_timeout_seconds: int
    max_active_streams: int
    allow_private_addresses: bool
    frame_payload_bytes: int

    @property
    def service_key_configured(self) -> bool:
        return bool(self.service_key.strip()) and self.service_key != PLACEHOLDER_SERVICE_KEY


def load_settings() -> Settings:
    return Settings(
        service_key=_secret("APP_SERVICE_KEY", PLACEHOLDER_SERVICE_KEY),
        connect_timeout_seconds=_int("APP_CONNECT_TIMEOUT_SECONDS", 15, 3, 60),
        max_active_streams=_int("APP_MAX_ACTIVE_STREAMS", 1024, 16, 8192),
        allow_private_addresses=_bool("APP_ALLOW_PRIVATE_ADDRESSES", False),
        frame_payload_bytes=_int("APP_FRAME_PAYLOAD_BYTES", 32768, 4096, 131072),
    )


SETTINGS = load_settings()
