"""Canonical collector registry — standalone ingress processes."""

from __future__ import annotations

COLLECTOR_STALE_SECONDS = 120
COLLECTOR_CRITICAL_SECONDS = 300

# Collectors are NOT part of run.py pipeline; they are long-lived standalone processes.
COLLECTORS = [
    {
        "name": "binance_live_feed",
        "script": "live_binance_feed_v2.py",
        "required": True,
        "kind": "websocket",
        "output_parquet": "live_market_feed.parquet",
        "description": "Binance kline WS → live_market_feed.parquet",
    },
    {
        "name": "multi_exchange",
        "script": "collectors/multi_exchange_collector.py",
        "required": False,
        "kind": "rest",
        "output_parquet": "multi_exchange_flow.parquet",
        "description": "REST multi-exchange flow snapshots",
    },
    {
        "name": "orderbook",
        "script": "collectors/orderbook_collector.py",
        "required": False,
        "kind": "rest",
        "output_path": "datasets/orderbook",
        "description": "Orderbook REST collector",
    },
    {
        "name": "oi",
        "script": "collectors/oi_collector.py",
        "required": False,
        "kind": "rest",
        "output_path": "datasets/oi",
        "description": "Open interest REST collector",
    },
    {
        "name": "liquidation",
        "script": "collectors/liquidation_collector.py",
        "required": False,
        "kind": "rest",
        "output_path": "datasets/liquidation",
        "description": "Liquidation event collector",
    },
]

REQUIRED_COLLECTORS = [c["name"] for c in COLLECTORS if c.get("required")]
