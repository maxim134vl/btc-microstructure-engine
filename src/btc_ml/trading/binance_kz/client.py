"""PAPI whitelist HTTP client. POST /papi/v1/um/order is never retried."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.request import Request

from .constants import (
    FAPI_PUBLIC_ALLOWED,
    FAPI_REST_URL,
    FORBIDDEN_PATH_MARKERS,
    LEVERAGE,
    PAPI_ALLOWED,
    PAPI_REST_URL,
    RECV_WINDOW_MS,
    SYMBOL,
    UNKNOWN_ORDER_MESSAGE,
)
from .signing import signed_query


class EndpointForbidden(RuntimeError):
    """Path is not on the Binance KZ whitelist."""


class IpBannedError(RuntimeError):
    """HTTP 418 — IP auto-banned. Kill, do not retry."""


class OrderUnknownError(RuntimeError):
    """HTTP 503 unknown on POST order. Do not retry POST. Reconcile by clientOrderId."""

    def __init__(self, message: str, *, client_order_id: str | None = None) -> None:
        super().__init__(message)
        self.client_order_id = client_order_id


class PortfolioMarginExchange(Protocol):
    def server_time_ms(self) -> int: ...
    def book_ticker(self, symbol: str) -> dict[str, Any]: ...
    def account(self) -> dict[str, Any]: ...
    def um_position_risk(self, symbol: str) -> list[dict[str, Any]]: ...
    def set_um_leverage(self, symbol: str, leverage: int) -> dict[str, Any]: ...
    def place_um_order(self, params: dict[str, Any]) -> dict[str, Any]: ...
    def get_um_order(self, *, orig_client_order_id: str, symbol: str = SYMBOL) -> dict[str, Any]: ...
    def cancel_um_order(self, *, orig_client_order_id: str, symbol: str = SYMBOL) -> dict[str, Any]: ...
    def cancel_all_um_orders(self, symbol: str = SYMBOL) -> Any: ...


def assert_allowed(method: str, path: str) -> None:
    method_u = str(method).upper()
    path_n = path.split("?", 1)[0]
    lowered = path_n.lower()
    for marker in FORBIDDEN_PATH_MARKERS:
        if marker.lower() in lowered:
            raise EndpointForbidden(f"forbidden endpoint {method_u} {path_n}")
    if (method_u, path_n) in PAPI_ALLOWED or (method_u, path_n) in FAPI_PUBLIC_ALLOWED:
        return
    raise EndpointForbidden(f"endpoint not on whitelist {method_u} {path_n}")


def is_unknown_order_status(status: int, body: str) -> bool:
    if int(status) != 503:
        return False
    return UNKNOWN_ORDER_MESSAGE.lower() in str(body or "").lower()


def host_for_path(path: str, *, papi_url: str = PAPI_REST_URL, fapi_url: str = FAPI_REST_URL) -> str:
    if path.startswith("/papi/"):
        return papi_url.rstrip("/")
    if path.startswith("/fapi/"):
        return fapi_url.rstrip("/")
    raise EndpointForbidden(f"unknown host for {path}")


@dataclass
class FakePapiClient:
    """In-memory Portfolio Margin stand-in. Never touches the network."""

    uni_mmr: float = 9.5
    equity_usd: float = 165_000.0
    bid: float = 77_000.0
    ask: float = 77_001.0
    mark: float = 77_000.5
    server_time: int = 1_700_000_000_000
    leverage: int = 2
    positions: dict[str, float] = field(default_factory=dict)
    resting: list[dict[str, Any]] = field(default_factory=list)
    posts: list[dict[str, Any]] = field(default_factory=list)
    gets: list[dict[str, Any]] = field(default_factory=list)
    next_order_id: int = 1000
    fail_next_unknown: bool = False
    unknown_actually_accepted: bool = True
    auto_borrow: bool = False
    accepted: dict[str, dict[str, Any]] = field(default_factory=dict)

    def server_time_ms(self) -> int:
        return int(self.server_time)

    def book_ticker(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "bidPrice": str(self.bid), "askPrice": str(self.ask)}

    def account(self) -> dict[str, Any]:
        return {
            "uniMMR": str(self.uni_mmr),
            "actualEquity": str(self.equity_usd),
            "accountEquity": str(self.equity_usd),
            "autoBorrow": self.auto_borrow,
        }

    def um_position_risk(self, symbol: str) -> list[dict[str, Any]]:
        qty = float(self.positions.get(symbol, 0.0))
        if abs(qty) < 1e-12:
            return [{"symbol": symbol, "positionAmt": "0", "leverage": str(self.leverage)}]
        return [
            {
                "symbol": symbol,
                "positionAmt": str(qty),
                "leverage": str(self.leverage),
                "entryPrice": str(self.mark),
                "markPrice": str(self.mark),
            }
        ]

    def set_um_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        if int(leverage) != LEVERAGE:
            raise ValueError(f"leverage must be {LEVERAGE}")
        self.leverage = int(leverage)
        return {"leverage": self.leverage, "symbol": symbol}

    def _fill_result(self, params: dict[str, Any], *, filled: bool) -> dict[str, Any]:
        oid = self.next_order_id
        self.next_order_id += 1
        cid = str(params.get("newClientOrderId") or params.get("origClientOrderId") or "")
        side = str(params.get("side") or "BUY").upper()
        qty = float(params.get("quantity") or 0.0)
        fallback_px = self.ask if side == "BUY" else self.bid
        px = float(params.get("price") or fallback_px)
        status = "FILLED" if filled else "NEW"
        row = {
            "orderId": oid,
            "clientOrderId": cid,
            "symbol": params.get("symbol") or SYMBOL,
            "side": side,
            "type": params.get("type"),
            "status": status,
            "origQty": str(qty),
            "executedQty": str(qty if filled else 0.0),
            "avgPrice": str(px if filled else 0.0),
            "reduceOnly": params.get("reduceOnly") == "true",
            "closePosition": params.get("closePosition") == "true",
        }
        self.accepted[cid] = row
        if filled and params.get("type") in {"LIMIT", "MARKET"}:
            current = float(self.positions.get(SYMBOL, 0.0))
            if params.get("reduceOnly") == "true":
                if current > 0:
                    self.positions[SYMBOL] = max(0.0, current - qty)
                elif current < 0:
                    self.positions[SYMBOL] = min(0.0, current + qty)
                else:
                    self.positions[SYMBOL] = 0.0
            else:
                signed = qty if side == "BUY" else -qty
                self.positions[SYMBOL] = current + signed
        else:
            self.resting.append(row)
        return row

    def place_um_order(self, params: dict[str, Any]) -> dict[str, Any]:
        self.posts.append(dict(params))
        cid = str(params.get("newClientOrderId") or "")
        filled = str(params.get("type") or "") in {"LIMIT", "MARKET"}
        if self.fail_next_unknown:
            self.fail_next_unknown = False
            if self.unknown_actually_accepted:
                self._fill_result(params, filled=filled)
            raise OrderUnknownError(UNKNOWN_ORDER_MESSAGE, client_order_id=cid)
        return self._fill_result(params, filled=filled)

    def get_um_order(self, *, orig_client_order_id: str, symbol: str = SYMBOL) -> dict[str, Any]:
        _ = symbol
        self.gets.append({"origClientOrderId": orig_client_order_id})
        if orig_client_order_id in self.accepted:
            return dict(self.accepted[orig_client_order_id])
        raise RuntimeError("order not found")

    def cancel_um_order(self, *, orig_client_order_id: str, symbol: str = SYMBOL) -> dict[str, Any]:
        _ = symbol
        row = self.accepted.get(orig_client_order_id) or {"clientOrderId": orig_client_order_id, "status": "CANCELED"}
        row = dict(row)
        row["status"] = "CANCELED"
        self.resting = [r for r in self.resting if r.get("clientOrderId") != orig_client_order_id]
        return row

    def cancel_all_um_orders(self, symbol: str = SYMBOL) -> list[dict[str, Any]]:
        _ = symbol
        out = list(self.resting)
        self.resting = []
        return out


class RecordingTransport:
    """Test double for urllib. Records calls; never opens a socket."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: Request, *, timeout: float) -> tuple[int, dict[str, str], str]:
        _ = timeout
        parsed = urllib.parse.urlparse(request.full_url)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        body = b""
        if request.data:
            body = request.data if isinstance(request.data, bytes) else bytes(request.data)
        self.calls.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "path": path,
                "query": {k: v[0] if v else "" for k, v in query.items()},
                "body": body.decode("utf-8") if body else "",
                "headers": dict(request.header_items()),
            }
        )
        return self.handler(request.get_method(), path, self.calls[-1])


class LivePapiClient:
    """Signed PAPI + public fapi. Refuses to construct unless live is armed."""

    def __init__(
        self,
        *,
        api_key: str,
        hmac_secret: str | None = None,
        ed25519_pem: bytes | None = None,
        papi_url: str = PAPI_REST_URL,
        fapi_url: str = FAPI_REST_URL,
        armed: bool = False,
        transport: Any | None = None,
        recv_window_ms: int = RECV_WINDOW_MS,
    ) -> None:
        if not armed:
            raise RuntimeError("LivePapiClient refused: real execution is not armed")
        if not api_key:
            raise RuntimeError("api_key required")
        if hmac_secret is None and ed25519_pem is None:
            raise RuntimeError("signing material required")
        self.api_key = api_key
        self.hmac_secret = hmac_secret
        self.ed25519_pem = ed25519_pem
        self.papi_url = papi_url.rstrip("/")
        self.fapi_url = fapi_url.rstrip("/")
        self.transport = transport
        self.recv_window_ms = int(recv_window_ms)
        self.post_order_attempts = 0

    def _now_ms(self) -> int:
        import time

        return int(time.time() * 1000)

    def _open(self, request: Request, *, timeout: float) -> tuple[int, dict[str, str], str]:
        if self.transport is not None:
            return self.transport(request, timeout=timeout)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                headers = {str(k): str(v) for k, v in resp.headers.items()}
                return int(resp.status), headers, body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            headers = {str(k): str(v) for k, v in (exc.headers.items() if exc.headers else [])}
            return int(exc.code), headers, body

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        timeout: float = 15.0,
    ) -> Any:
        method_u = method.upper()
        assert_allowed(method_u, path)
        params = dict(params or {})
        host = host_for_path(path, papi_url=self.papi_url, fapi_url=self.fapi_url)
        if signed:
            query = signed_query(
                params,
                timestamp_ms=self._now_ms(),
                recv_window_ms=self.recv_window_ms,
                hmac_secret=self.hmac_secret,
                ed25519_pem=self.ed25519_pem,
            )
        else:
            from .signing import encode_params

            query = encode_params(params)
        url = f"{host}{path}"
        headers = {"X-MBX-APIKEY": self.api_key, "Accept": "application/json"}
        if method_u in {"POST", "PUT", "DELETE"} and query:
            request = Request(url, data=query.encode("utf-8"), headers=headers, method=method_u)
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        else:
            full = f"{url}?{query}" if query else url
            request = Request(full, headers=headers, method=method_u)
        if method_u == "POST" and path == "/papi/v1/um/order":
            self.post_order_attempts += 1
        status, _headers, body = self._open(request, timeout=timeout)
        if status == 418:
            raise IpBannedError("HTTP 418 IP banned")
        if method_u == "POST" and path == "/papi/v1/um/order" and is_unknown_order_status(status, body):
            raise OrderUnknownError(UNKNOWN_ORDER_MESSAGE, client_order_id=str(params.get("newClientOrderId") or None))
        if status >= 400:
            raise RuntimeError(f"binance HTTP {status}: {body[:300]}")
        if not body:
            return {}
        return json.loads(body)

    def server_time_ms(self) -> int:
        payload = self.request("GET", "/fapi/v1/time", signed=False)
        return int(payload["serverTime"])

    def book_ticker(self, symbol: str) -> dict[str, Any]:
        payload = self.request("GET", "/fapi/v1/ticker/bookTicker", params={"symbol": symbol}, signed=False)
        return payload if isinstance(payload, dict) else {}

    def account(self) -> dict[str, Any]:
        payload = self.request("GET", "/papi/v1/account", signed=True)
        return payload if isinstance(payload, dict) else {}

    def um_position_risk(self, symbol: str) -> list[dict[str, Any]]:
        payload = self.request("GET", "/papi/v1/um/positionRisk", params={"symbol": symbol}, signed=True)
        return payload if isinstance(payload, list) else []

    def set_um_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        if int(leverage) != LEVERAGE:
            raise ValueError(f"refusing leverage={leverage}")
        payload = self.request(
            "POST",
            "/papi/v1/um/leverage",
            params={"symbol": symbol, "leverage": int(leverage)},
            signed=True,
        )
        return payload if isinstance(payload, dict) else {}

    def place_um_order(self, params: dict[str, Any]) -> dict[str, Any]:
        payload = self.request("POST", "/papi/v1/um/order", params=params, signed=True)
        return payload if isinstance(payload, dict) else {}

    def get_um_order(self, *, orig_client_order_id: str, symbol: str = SYMBOL) -> dict[str, Any]:
        payload = self.request(
            "GET",
            "/papi/v1/um/order",
            params={"symbol": symbol, "origClientOrderId": orig_client_order_id},
            signed=True,
        )
        return payload if isinstance(payload, dict) else {}

    def cancel_um_order(self, *, orig_client_order_id: str, symbol: str = SYMBOL) -> dict[str, Any]:
        payload = self.request(
            "DELETE",
            "/papi/v1/um/order",
            params={"symbol": symbol, "origClientOrderId": orig_client_order_id},
            signed=True,
        )
        return payload if isinstance(payload, dict) else {}

    def cancel_all_um_orders(self, symbol: str = SYMBOL) -> Any:
        return self.request("DELETE", "/papi/v1/um/allOpenOrders", params={"symbol": symbol}, signed=True)
