"""Live VPS paper book for the Kronos OPEN overlay.

Reads the currently running LIVE1B epoch, not ETLL_HYBRID_TICK archive.
Kronos-mini stays a gate on already-executed S4.1 OPENs.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from btc_ml.research.logic1_kronos_open_prior import (
    LOOKBACK_BARS,
    attach_kronos_features,
    is_atomic_flip,
    is_forming_context,
)
from btc_ml.research.logic1_kronos_runtime import (
    cloud_for_closed_bar,
    lookback_ohlcv,
)

ROOT = Path(__file__).resolve().parents[3]
LIVE_EPOCH_ID = "PER_TF_EQUITY_1PCT_V1_VPS_20260907_095442"
LIVE_CONTAINER = "btcml-vps-paper-manager-1"
DEFAULT_SNAPSHOT = ROOT / "data/research/kronos/live_epoch_snapshot"
KLINES_DIR = ROOT / "data/research/kronos/klines"
DOCKER_BOOKS = f"/app/data/trading/intrabar_paper/{LIVE_EPOCH_ID}/books"
DOCKER_COMMANDS = "/app/data/trading/manager/timeframe_command_memory.parquet"
BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"
KLINE_INTERVALS = {"M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h"}
KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]
INSTANT_PROTECTIVE_SEC = 120.0
PROTECTIVE_EXITS = {"SL", "STOP_LOSS", "STOP", "TP", "TAKE_PROFIT"}


def _is_void_row(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or row.get("void_status") or "").upper()
    return status == "VOID" or status.startswith("VOID_")


def _counts_toward_performance(row: dict[str, Any]) -> bool:
    if row.get("statistics_included") is False:
        return False
    if _is_void_row(row):
        return False
    status = str(row.get("status") or "").upper()
    return status in {"CLOSED", "CLOSE", ""}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def parse_reason_codes(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [text]
    if isinstance(parsed, list):
        return [str(x) for x in parsed]
    return [str(parsed)]


def utc_ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def snapshot_live_epoch(
    dest: Path | None = None,
    *,
    container: str = LIVE_CONTAINER,
) -> Path:
    """Copy the running paper books + S4.1 command bus. WAL is not copied."""
    out = Path(dest or DEFAULT_SNAPSHOT)
    (out / "books").mkdir(parents=True, exist_ok=True)
    (out / "manager").mkdir(parents=True, exist_ok=True)
    copies = {
        f"{container}:{DOCKER_BOOKS}/positions.jsonl": out / "books" / "positions.jsonl",
        f"{container}:{DOCKER_BOOKS}/trades.jsonl": out / "books" / "trades.jsonl",
        f"{container}:{DOCKER_COMMANDS}": out / "manager" / "timeframe_command_memory.parquet",
    }
    for src, dst in copies.items():
        dst.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["docker", "cp", src, str(dst)], check=True)
    meta = {
        "paper_epoch_id": LIVE_EPOCH_ID,
        "container": container,
        "copied_at": pd.Timestamp.now(tz="UTC").isoformat().replace("+00:00", "Z"),
        "source": "running_vps_stack_not_etll_archive",
    }
    (out / "snapshot_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return out


def _open_rows(positions: list[dict[str, Any]]) -> pd.DataFrame:
    opens: dict[str, dict[str, Any]] = {}
    for row in positions:
        if str(row.get("status") or "").upper() != "OPEN":
            continue
        if _is_void_row(row):
            continue
        pid = str(row.get("position_id") or "")
        if pid and pid not in opens:
            opens[pid] = row
    return pd.DataFrame(list(opens.values()))


def build_live_open_events(snapshot: Path) -> pd.DataFrame:
    """One row per eligible closed LIVE1B trade joined to its S4.1 OPEN command."""
    books = Path(snapshot) / "books"
    positions = _open_rows(read_jsonl(books / "positions.jsonl"))
    trades = pd.DataFrame(
        [
            row
            for row in read_jsonl(books / "trades.jsonl")
            if _counts_toward_performance(row)
        ]
    )
    if positions.empty or trades.empty:
        return pd.DataFrame()
    positions["position_id"] = positions["position_id"].astype(str)
    trades["position_id"] = trades["position_id"].astype(str)
    pos_keep = [
        "position_id",
        "timeframe",
        "side",
        "manager_command_id",
        "lifecycle_episode_id",
        "entry_price",
        "opened_at",
        "execution_timestamp",
        "entry_source",
        "risk_amount_usd",
        "stop_loss_price",
        "context_occurrence_timestamp",
    ]
    events = trades.merge(
        positions[[c for c in pos_keep if c in positions.columns]],
        on="position_id",
        how="inner",
        suffixes=("_trade", ""),
    )
    cmd_path = Path(snapshot) / "manager" / "timeframe_command_memory.parquet"
    cmds = pd.read_parquet(cmd_path)
    cmds = cmds.loc[cmds["intent"].astype(str).str.upper().isin({"OPEN_LONG", "OPEN_SHORT"})].copy()
    cmd_keep = [
        "command_id",
        "intent",
        "timeframe",
        "lifecycle_phase",
        "timeframe_state",
        "reason_codes",
        "source_bar_open",
        "source_bar_close",
        "evaluation_timestamp",
        "context_origin_price",
        "context_started_at",
        "created_at",
        "lifecycle_episode_id",
    ]
    cmds = cmds[[c for c in cmd_keep if c in cmds.columns]]
    events["manager_command_id"] = events["manager_command_id"].astype(str)
    cmds["command_id"] = cmds["command_id"].astype(str)
    events = events.merge(
        cmds,
        left_on="manager_command_id",
        right_on="command_id",
        how="left",
        suffixes=("", "_cmd"),
    )
    if "timeframe_cmd" in events.columns:
        events["timeframe"] = events["timeframe"].fillna(events["timeframe_cmd"])
    risk = pd.to_numeric(events.get("risk_amount_usd"), errors="coerce").replace(0, np.nan)
    events["R"] = pd.to_numeric(events.get("net_pnl_usd"), errors="coerce") / risk
    events["side"] = events["side"].astype(str).str.upper()
    events["entry_ts"] = utc_ts(events.get("opened_at", events.get("execution_timestamp")))
    exit_raw = events["exit_ts"] if "exit_ts" in events.columns else events.get("execution_timestamp")
    events["exit_ts"] = utc_ts(exit_raw)
    events["hold_seconds"] = (events["exit_ts"] - events["entry_ts"]).dt.total_seconds()
    exits = events.get("exit_reason", pd.Series([""] * len(events))).astype(str).str.upper()
    events["instant_protective_bug"] = (
        events["hold_seconds"].fillna(1e9).to_numpy() < INSTANT_PROTECTIVE_SEC
    ) & exits.isin(PROTECTIVE_EXITS).to_numpy()
    events["reason_codes"] = events.get("reason_codes", pd.Series([[]] * len(events))).map(parse_reason_codes)
    events["atomic_flip"] = [is_atomic_flip(r) for r in events["reason_codes"]]
    events["forming"] = [is_forming_context(r) for r in events["reason_codes"]]
    events["source_bar_close_ts"] = utc_ts(events.get("source_bar_close"))
    events["paper_epoch_id"] = LIVE_EPOCH_ID
    if "entry_source" in events.columns:
        events = events.loc[events["entry_source"].astype(str) == "s41_command_bus"]
    return events.reset_index(drop=True)


def scoring_frame(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events
    return events.loc[~events["instant_protective_bug"].fillna(False)].reset_index(drop=True)


def _request_klines(params: dict[str, Any], retries: int = 8) -> list[list[Any]]:
    url = f"{BINANCE_URL}?{urllib.parse.urlencode(params)}"
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": "btc-ml-kronos-live/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"klines failed: {last}")


def download_klines(
    timeframe: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    dest_dir: Path | None = None,
) -> pd.DataFrame:
    tf = str(timeframe).upper()
    interval = KLINE_INTERVALS[tf]
    out_dir = Path(dest_dir or KLINES_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"BTCUSDT_{interval}.parquet"
    cursor = int(pd.Timestamp(start).timestamp() * 1000)
    end_ms = int(pd.Timestamp(end).timestamp() * 1000)
    rows: list[list[Any]] = []
    while cursor <= end_ms:
        payload = _request_klines(
            {
                "symbol": "BTCUSDT",
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        if not payload:
            break
        rows.extend(payload)
        last_open = int(payload[-1][0])
        nxt = last_open + 1
        if nxt <= cursor:
            break
        cursor = nxt
        if len(payload) < 1000:
            break
    frame = pd.DataFrame(rows, columns=KLINE_COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["open_time"], utc=True, unit="ms")
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    frame = frame.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
    keep = frame[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    keep.to_parquet(path, index=False)
    return keep


def load_klines(timeframe: str, dest_dir: Path | None = None) -> pd.DataFrame:
    tf = str(timeframe).upper()
    path = Path(dest_dir or KLINES_DIR) / f"BTCUSDT_{KLINE_INTERVALS[tf]}.parquet"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


def attach_live_kronos_clouds(
    events: pd.DataFrame,
    bars_by_tf: dict[str, pd.DataFrame],
    predictor: Any,
    *,
    lookback_bars: int = LOOKBACK_BARS,
    n_paths: int = 8,
) -> pd.DataFrame:
    clouds: list[dict[str, Any] | None] = []
    for row in events.itertuples(index=False):
        if bool(getattr(row, "forming", False)):
            clouds.append(None)
            continue
        tf = str(getattr(row, "timeframe")).upper()
        cutoff = getattr(row, "source_bar_close_ts", None)
        bars = bars_by_tf.get(tf)
        if bars is None or bars.empty or pd.isna(cutoff):
            clouds.append(None)
            continue
        try:
            cloud = cloud_for_closed_bar(
                bars,
                source_bar_close=cutoff,
                timeframe=tf,
                predictor=predictor,
                lookback_bars=lookback_bars,
                n_paths=n_paths,
            )
        except Exception:
            clouds.append(None)
            continue
        clouds.append(cloud)
    return attach_kronos_features(events, clouds)


def lookback_ok(bars: pd.DataFrame, cutoff: Any, timeframe: str, lookback_bars: int = LOOKBACK_BARS) -> bool:
    window = lookback_ohlcv(
        bars, source_bar_close=cutoff, timeframe=timeframe, lookback_bars=lookback_bars
    )
    return len(window) >= min(int(lookback_bars), 64)
