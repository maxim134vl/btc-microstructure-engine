#!/usr/bin/env python3
"""Manual live context refresh — once mode (shadow-only).

Logic:
  1. Read latest timestamp from live_market_feed.parquet
  2. Read latest timestamp from market_context_lifecycle_memory.parquet
  3. If lifecycle lags live_feed:
       - run build_market_context_shadow_chain.py
       - on success run append_context_decision_log.py
  4. If lifecycle already fresh:
       - run append_context_decision_log.py only
  5. Write status JSON + log file

Does NOT:
  - change model / auction / cognitive / final / lifecycle logic
  - change live feed / runtime-stack
  - start dashboard or visual server
  - enable execution / create orders

This is a manual once-mode refresh for technical lag catch-up only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

LIVE_FEED = ROOT / "data" / "live" / "live_market_feed.parquet"
LIFECYCLE_PATH = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
SHADOW_CHAIN_SCRIPT = ROOT / "scripts" / "research" / "build_market_context_shadow_chain.py"
DECISION_LOGGER_SCRIPT = ROOT / "scripts" / "live" / "append_context_decision_log.py"
STATUS_PATH = ROOT / "data" / "live" / "live_context_refresh_status.json"
LOG_PATH = ROOT / "logs" / "live_context_refresh.log"

# Shadow chain may rewrite tip/history; after rebuild we restore immutable production
# prefix and keep only newly observed timestamps (Patch 2A / 2A.1 FINAL contract).
SHADOW_PREFIX_PRESERVE = (
    (ROOT / "data" / "cognition" / "auction_episode_memory.parquet", "timestamp"),
    (ROOT / "data" / "cognition" / "cognitive_market_state_memory.parquet", "timestamp"),
    (ROOT / "data" / "cognition" / "final_market_context_memory.parquet", "timestamp"),
    (ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet", "timestamp"),
    (ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet", "end_time"),
)

REFRESH_VERSION = "live_context_refresh_once_v1_tail_merge"


class RefreshError(RuntimeError):
    """Safe failure for missing sources / failed rebuild."""


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso(ts: Any) -> str | None:
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return None
    parsed = pd.to_datetime(ts, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).isoformat().replace("+00:00", "Z")


def latest_parquet_timestamp(path: Path, col: str = "timestamp") -> pd.Timestamp | None:
    if not path.exists():
        raise RefreshError(f"Missing required artifact: {path}")
    frame = pd.read_parquet(path, columns=[col] if col else None)
    if col not in frame.columns or len(frame) == 0:
        return None
    series = pd.to_datetime(frame[col], utc=True, errors="coerce").dropna()
    if len(series) == 0:
        return None
    return pd.Timestamp(series.max())


def lag_seconds(live_ts: pd.Timestamp | None, life_ts: pd.Timestamp | None) -> float | None:
    if live_ts is None or life_ts is None:
        return None
    return round((pd.Timestamp(live_ts) - pd.Timestamp(life_ts)).total_seconds(), 3)


def lifecycle_is_stale(live_ts: pd.Timestamp | None, life_ts: pd.Timestamp | None) -> bool:
    if live_ts is None or life_ts is None:
        return True
    return pd.Timestamp(life_ts) < pd.Timestamp(live_ts)


def append_log(message: str, *, log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().isoformat().replace("+00:00", "Z")
    line = f"[{stamp}] {message}\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def write_status(payload: dict[str, Any], *, status_path: Path = STATUS_PATH) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = status_path.with_suffix(status_path.suffix + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, status_path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def tail_merge_existing_wins(prod: pd.DataFrame, cand: pd.DataFrame, ts_col: str) -> pd.DataFrame:
    """Preserve immutable production prefix; append only candidate rows after prod tip."""
    if prod is None or len(prod) == 0:
        return cand.copy()
    if cand is None or len(cand) == 0:
        return prod.copy()
    prod_ts = pd.to_datetime(prod[ts_col], utc=True, errors="coerce")
    cand_ts = pd.to_datetime(cand[ts_col], utc=True, errors="coerce")
    prod_tip = prod_ts.max()
    if pd.isna(prod_tip):
        return cand.copy()
    tail = cand.loc[cand_ts > prod_tip].copy()
    if len(tail) == 0:
        return prod.copy()
    for col in prod.columns:
        if col not in tail.columns:
            tail[col] = None
    tail = tail[list(prod.columns)]
    out = pd.concat([prod, tail], ignore_index=True, sort=False)
    out = out.drop_duplicates(subset=[ts_col], keep="first")
    out["_sort"] = pd.to_datetime(out[ts_col], utc=True, errors="coerce")
    out = out.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)
    return out


def snapshot_prefix_datasets(
    datasets: tuple[tuple[Path, str], ...] = SHADOW_PREFIX_PRESERVE,
) -> dict[str, dict[str, Any]]:
    """Read production datasets before shadow rewrite."""
    snaps: dict[str, dict[str, Any]] = {}
    for path, ts_col in datasets:
        key = str(path)
        if not path.exists():
            snaps[key] = {"path": path, "ts_col": ts_col, "frame": None, "tip": None, "rows": 0}
            continue
        frame = pd.read_parquet(path)
        tip = None
        if ts_col in frame.columns and len(frame):
            series = pd.to_datetime(frame[ts_col], utc=True, errors="coerce").dropna()
            if len(series):
                tip = pd.Timestamp(series.max())
        snaps[key] = {
            "path": path,
            "ts_col": ts_col,
            "frame": frame,
            "tip": tip,
            "rows": int(len(frame)),
        }
    return snaps


def restore_prefix_after_shadow(
    snapshots: dict[str, dict[str, Any]],
    *,
    log_path: Path = LOG_PATH,
) -> dict[str, Any]:
    """After shadow rewrite: existing production rows always win; append new tip only."""
    report: dict[str, Any] = {"restored": [], "skipped": []}
    for key, snap in snapshots.items():
        path: Path = snap["path"]
        ts_col: str = snap["ts_col"]
        prod = snap["frame"]
        if prod is None or not path.exists():
            report["skipped"].append({"path": key, "reason": "missing_before_or_after"})
            continue
        cand = pd.read_parquet(path)
        merged = tail_merge_existing_wins(prod, cand, ts_col)
        # Safety: prefix row count through prior tip must match snapshot.
        prior_tip = snap["tip"]
        if prior_tip is not None:
            p_ts = pd.to_datetime(prod[ts_col], utc=True, errors="coerce")
            m_ts = pd.to_datetime(merged[ts_col], utc=True, errors="coerce")
            p_pref = prod.loc[p_ts <= prior_tip]
            m_pref = merged.loc[m_ts <= prior_tip]
            if len(p_pref) != len(m_pref):
                raise RefreshError(
                    f"prefix row count changed after tail_merge for {path.name}: "
                    f"{len(p_pref)} -> {len(m_pref)}"
                )
        _write_parquet_atomic(merged, path)
        new_tip = latest_parquet_timestamp(path, col=ts_col)
        entry = {
            "path": key,
            "rows_before": int(snap["rows"]),
            "rows_after": int(len(merged)),
            "added": int(len(merged) - snap["rows"]),
            "tip_before": _iso(prior_tip),
            "tip_after": _iso(new_tip),
        }
        report["restored"].append(entry)
        append_log(
            f"PREFIX_PRESERVE {path.name} added={entry['added']} "
            f"tip {_iso(prior_tip)} -> {_iso(new_tip)}",
            log_path=log_path,
        )
    return report


def run_python_script(script: Path, *, cwd: Path = ROOT, timeout_s: int = 600) -> dict[str, Any]:
    if not script.exists():
        raise RefreshError(f"Missing script: {script}")
    python = Path(sys.executable)
    started = _utc_now()
    proc = subprocess.run(
        [str(python), str(script)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    ended = _utc_now()
    return {
        "script": str(script),
        "returncode": int(proc.returncode),
        "ok": proc.returncode == 0,
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "ended_at_utc": ended.isoformat().replace("+00:00", "Z"),
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def run_refresh_once(
    *,
    live_path: Path = LIVE_FEED,
    lifecycle_path: Path = LIFECYCLE_PATH,
    shadow_script: Path = SHADOW_CHAIN_SCRIPT,
    decision_script: Path = DECISION_LOGGER_SCRIPT,
    status_path: Path = STATUS_PATH,
    log_path: Path = LOG_PATH,
    force_rebuild: bool = False,
    skip_rebuild: bool = False,
    run_script=run_python_script,
) -> dict[str, Any]:
    started = _utc_now()
    append_log("START live_context_refresh_once", log_path=log_path)

    live_ts = latest_parquet_timestamp(live_path)
    life_ts = latest_parquet_timestamp(lifecycle_path)
    lag = lag_seconds(live_ts, life_ts)
    was_stale = lifecycle_is_stale(live_ts, life_ts)
    needs_rebuild = bool(force_rebuild or (was_stale and not skip_rebuild))

    append_log(
        f"live_latest={_iso(live_ts)} lifecycle_latest={_iso(life_ts)} "
        f"lag_seconds={lag} stale={was_stale} needs_rebuild={needs_rebuild}",
        log_path=log_path,
    )

    shadow_result: dict[str, Any] | None = None
    decision_result: dict[str, Any] | None = None
    prefix_report: dict[str, Any] | None = None
    status = "OK"
    error: str | None = None

    try:
        if needs_rebuild:
            snapshots = snapshot_prefix_datasets()
            append_log(
                f"SNAPSHOT prefix datasets n={len(snapshots)} "
                f"lifecycle_tip={_iso(snapshots.get(str(lifecycle_path), {}).get('tip'))}",
                log_path=log_path,
            )
            append_log("RUN build_market_context_shadow_chain.py", log_path=log_path)
            shadow_result = run_script(shadow_script)
            if not shadow_result["ok"]:
                raise RefreshError(
                    f"Shadow chain rebuild failed (rc={shadow_result['returncode']}): "
                    f"{shadow_result.get('stderr_tail') or shadow_result.get('stdout_tail')}"
                )
            append_log("PASS shadow chain rebuild", log_path=log_path)
            prefix_report = restore_prefix_after_shadow(snapshots, log_path=log_path)
            append_log("PASS prefix preserve (existing rows win)", log_path=log_path)
            # Re-read lifecycle after rebuild + prefix restore.
            life_ts = latest_parquet_timestamp(lifecycle_path)
            lag = lag_seconds(live_ts, life_ts)
            append_log(
                f"AFTER rebuild+prefix lifecycle_latest={_iso(life_ts)} lag_seconds={lag} "
                f"stale={lifecycle_is_stale(live_ts, life_ts)}",
                log_path=log_path,
            )
        else:
            append_log("SKIP shadow chain rebuild (lifecycle already fresh)", log_path=log_path)

        append_log("RUN append_context_decision_log.py", log_path=log_path)
        decision_result = run_script(decision_script)
        if not decision_result["ok"]:
            raise RefreshError(
                f"Decision logger failed (rc={decision_result['returncode']}): "
                f"{decision_result.get('stderr_tail') or decision_result.get('stdout_tail')}"
            )
        append_log(
            f"PASS decision logger stdout_tail={decision_result.get('stdout_tail', '')[-500:]}",
            log_path=log_path,
        )
    except Exception as exc:  # noqa: BLE001 — once-mode orchestrator must capture and persist status
        status = "ERROR"
        error = str(exc)
        append_log(f"ERROR {error}", log_path=log_path)

    ended = _utc_now()
    payload = {
        "refresh_version": REFRESH_VERSION,
        "mode": "once",
        "status": status,
        "started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "ended_at_utc": ended.isoformat().replace("+00:00", "Z"),
        "live_feed_latest_timestamp": _iso(live_ts),
        "lifecycle_latest_timestamp": _iso(life_ts),
        "live_to_lifecycle_lag_seconds": lag,
        "lifecycle_was_stale": bool(was_stale),
        "lifecycle_still_stale_after": bool(lifecycle_is_stale(live_ts, life_ts)),
        "shadow_chain_rebuild_ran": bool(needs_rebuild and shadow_result is not None),
        "shadow_chain_rebuild_ok": None if shadow_result is None else bool(shadow_result.get("ok")),
        "prefix_preserve_ran": prefix_report is not None,
        "prefix_preserve": prefix_report,
        "decision_logger_ran": decision_result is not None,
        "decision_logger_ok": None if decision_result is None else bool(decision_result.get("ok")),
        "execution_enabled": False,
        "orders_created": False,
        "paper_orders_created": False,
        "action_allowed": False,
        "shadow_only": True,
        "visual_server_started": False,
        "dashboard_started": False,
        "runtime_stack_modified": False,
        "error": error,
        "shadow_result": shadow_result,
        "decision_result": {
            k: decision_result.get(k)
            for k in ("script", "returncode", "ok", "started_at_utc", "ended_at_utc", "stdout_tail")
        }
        if decision_result
        else None,
        "note": (
            "Manual once-mode live context refresh. Shadow-only. "
            "Does not enable execution and must not be used to place orders."
        ),
    }
    write_status(payload, status_path=status_path)
    append_log(f"END status={status}", log_path=log_path)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual live context refresh once-mode (shadow-only)")
    parser.add_argument("--force-rebuild", action="store_true", help="Always run shadow chain rebuild")
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="Never run shadow chain rebuild (decision logger only)",
    )
    parser.add_argument("--status-path", type=Path, default=STATUS_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    args = parser.parse_args(argv)

    if args.force_rebuild and args.skip_rebuild:
        print("ERROR: --force-rebuild and --skip-rebuild are mutually exclusive", file=sys.stderr)
        return 2

    payload = run_refresh_once(
        status_path=args.status_path,
        log_path=args.log_path,
        force_rebuild=bool(args.force_rebuild),
        skip_rebuild=bool(args.skip_rebuild),
    )
    print("======== LIVE CONTEXT REFRESH ONCE (shadow-only) ========")
    for key in (
        "status",
        "live_feed_latest_timestamp",
        "lifecycle_latest_timestamp",
        "live_to_lifecycle_lag_seconds",
        "shadow_chain_rebuild_ran",
        "shadow_chain_rebuild_ok",
        "decision_logger_ran",
        "decision_logger_ok",
        "execution_enabled",
        "error",
    ):
        print(f"{key}: {payload.get(key)}")
    print(f"status_json: {args.status_path}")
    print(f"log_file: {args.log_path}")
    print(
        "NOTE: Manual once-mode refresh. Shadow-only. "
        "Does not enable execution and must not be used to place orders."
    )
    return 0 if payload.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
