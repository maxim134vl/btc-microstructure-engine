"""Binance KZ / Portfolio Margin constants. Live PAPI is the only trade host."""

from __future__ import annotations

PAPI_REST_URL = "https://papi.binance.com"
FAPI_REST_URL = "https://fapi.binance.com"
PAPI_USER_WS_URL = "wss://fstream.binance.com/pm/ws"
FAPI_PUBLIC_WS_URL = "wss://fstream.binance.com"

SCHEMA_VERSION = "binance_kz_execution_v1"
CURSOR_SCHEMA_VERSION = "s41_binance_kz_command_cursor_v1"
ALLOWED_NETWORKS = ("live",)
ALLOWED_ACCOUNT_MODES = ("portfolio_margin",)
SYMBOL = "BTCUSDT"
ALLOWED_TIMEFRAMES = ("M15",)
LEVERAGE = 2
LEVERAGE_CAP = 2
RISK_PCT = 1.0
MIN_UNIMMR_OPEN = 2.0
KILL_UNIMMR = 1.5
BINANCE_LIQ_UNIMMR = 1.05
RECV_WINDOW_MS = 5000
MAX_CLOCK_SKEW_MS = 1000
MAX_BBO_AGE_MS = 2000.0
CATBOOST_CLIP_LO = 0.5
CATBOOST_CLIP_HI = 1.5

ENV_LIVE_ENABLED = "BINANCE_KZ_LIVE_ENABLED"
ENV_API_KEY = "BINANCE_KZ_API_KEY"
ENV_API_SECRET = "BINANCE_KZ_API_SECRET"
ENV_ED25519_KEY_PATH = "BINANCE_KZ_ED25519_KEY_PATH"

PAPER_FORBIDDEN_BINANCE_KZ_ENV = (
    ENV_API_KEY,
    ENV_API_SECRET,
    ENV_ED25519_KEY_PATH,
    ENV_LIVE_ENABLED,
)

UNKNOWN_ORDER_MESSAGE = "Unknown error, please check your request or try again later."

PAPI_ALLOWED = frozenset(
    {
        ("GET", "/papi/v1/account"),
        ("GET", "/papi/v1/balance"),
        ("GET", "/papi/v1/um/account"),
        ("GET", "/papi/v2/um/account"),
        ("GET", "/papi/v1/um/positionRisk"),
        ("GET", "/papi/v1/um/leverageBracket"),
        ("POST", "/papi/v1/um/leverage"),
        ("POST", "/papi/v1/um/order"),
        ("GET", "/papi/v1/um/order"),
        ("DELETE", "/papi/v1/um/order"),
        ("DELETE", "/papi/v1/um/allOpenOrders"),
        ("GET", "/papi/v1/um/openOrders"),
        ("GET", "/papi/v1/um/userTrades"),
        ("POST", "/papi/v1/listenKey"),
        ("PUT", "/papi/v1/listenKey"),
        ("DELETE", "/papi/v1/listenKey"),
    }
)

FAPI_PUBLIC_ALLOWED = frozenset(
    {
        ("GET", "/fapi/v1/ping"),
        ("GET", "/fapi/v1/time"),
        ("GET", "/fapi/v1/exchangeInfo"),
        ("GET", "/fapi/v1/premiumIndex"),
        ("GET", "/fapi/v1/ticker/bookTicker"),
    }
)

FORBIDDEN_PATH_MARKERS = (
    "/sapi",
    "/withdraw",
    "/capital",
    "/universalTransfer",
    "/papi/v1/cm/",
    "/papi/v1/margin",
    "batchOrders",
    "/fapi/v1/order",
    "/fapi/v1/leverage",
    "/fapi/v1/listenKey",
    "/fapi/v2/account",
    "/fapi/v2/positionRisk",
)
