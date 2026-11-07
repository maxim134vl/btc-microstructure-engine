"""Portfolio Margin user-data stream helpers. Stage-1 does not open a socket."""

from __future__ import annotations

from .constants import PAPI_USER_WS_URL


def user_stream_url(listen_key: str, *, base: str = PAPI_USER_WS_URL) -> str:
    key = str(listen_key or "").strip()
    if not key:
        raise ValueError("listen_key required")
    return f"{base.rstrip('/')}/{key}"
