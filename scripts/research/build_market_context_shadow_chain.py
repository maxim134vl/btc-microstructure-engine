#!/usr/bin/env python3
"""Reproduce the restored market-context shadow chain end-to-end.

Shadow-only orchestration. Not pipeline. Not execution. Not a trade signal.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / "venv" / "bin" / "python"
STATUS_PATH = ROOT / "data" / "cognition" / "market_context_shadow_chain_status.json"
SANDBOX_URL = "http://127.0.0.1:8765/"

FORBIDDEN_TOKENS = (
    "FAILED_SHORT_REPRICE",
    "raw_chosen_context",
    "calibrated_context",
)

CHAIN_STEPS: list[dict[str, Any]] = [
    {
        "name": "auction_episode_memory",
        "script": ROOT / "scripts" / "research" / "build_auction_episode_memory.py",
        "outputs": [ROOT / "data" / "cognition" / "auction_episode_memory.parquet"],
    },
    {
        "name": "cognitive_market_state_memory",
        "script": ROOT / "scripts" / "research" / "build_cognitive_market_state_memory.py",
        "outputs": [ROOT / "data" / "cognition" / "cognitive_market_state_memory.parquet"],
    },
    {
        "name": "final_market_context_memory",
        "script": ROOT / "scripts" / "research" / "build_final_market_context_memory.py",
        "outputs": [ROOT / "data" / "cognition" / "final_market_context_memory.parquet"],
    },
    {
        "name": "market_context_lifecycle_memory",
        "script": ROOT / "scripts" / "research" / "build_market_context_lifecycle_memory.py",
        "outputs": [
            ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet",
            ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet",
        ],
    },
    {
        "name": "lifecycle_visual_data",
        "script": ROOT
        / "sandbox"
        / "market_state_context_visualizer"
        / "generate_lifecycle_context_data.py",
        "outputs": [
            ROOT
            / "sandbox"
            / "market_state_context_visualizer"
            / "public"
            / "data"
            / "lifecycle_candles.json",
            ROOT
            / "sandbox"
            / "market_state_context_visualizer"
            / "public"
            / "data"
            / "lifecycle_context_episodes.json",
            ROOT
            / "sandbox"
            / "market_state_context_visualizer"
            / "public"
            / "data"
            / "lifecycle_latest.json",
        ],
    },
]

SHADOW_PARQUET_LAYERS = [
    ROOT / "data" / "cognition" / "auction_episode_memory.parquet",
    ROOT / "data" / "cognition" / "cognitive_market_state_memory.parquet",
    ROOT / "data" / "cognition" / "final_market_context_memory.parquet",
    ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet",
    ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet",
]

VISUAL_JSON_PATHS = [
    ROOT
    / "sandbox"
    / "market_state_context_visualizer"
    / "public"
    / "data"
    / "lifecycle_candles.json",
    ROOT
    / "sandbox"
    / "market_state_context_visualizer"
    / "public"
    / "data"
    / "lifecycle_context_episodes.json",
    ROOT
    / "sandbox"
    / "market_state_context_visualizer"
    / "public"
    / "data"
    / "lifecycle_latest.json",
]

REQUIRED_STATUS_FIELDS = [
    "generated_at",
    "status",
    "artifacts",
    "latest_context",
    "raw_episodes_count",
    "lifecycle_episodes_count",
    "checks",
    "shadow_only",
]


class ChainError(RuntimeError):
    """Raised when a shadow-chain step or check fails."""


@dataclass
class ArtifactInfo:
    path: str
    rows: int
    latest_timestamp: str | None
    shadow_only_ok: bool
    kind: str


@dataclass
class ChainResult:
    status: str = "FAIL"
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    latest_context: dict[str, Any] = field(default_factory=dict)
    raw_episodes_count: int | None = None
    lifecycle_episodes_count: int | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    shadow_only: bool = True
    error: str | None = None
    steps_run: list[str] = field(default_factory=list)

    def to_status_dict(self) -> dict[str, Any]:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": self.status,
            "artifacts": self.artifacts,
            "latest_context": self.latest_context,
            "raw_episodes_count": self.raw_episodes_count,
            "lifecycle_episodes_count": self.lifecycle_episodes_count,
            "checks": self.checks,
            "shadow_only": True,
            "sandbox_url": SANDBOX_URL,
            "steps_run": self.steps_run,
        }
        if self.error:
            payload["error"] = self.error
        return payload


def _iso_ts(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _to_utc(value: Any) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _contains_forbidden(payload: Any) -> list[str]:
    blob = json.dumps(payload, ensure_ascii=False, default=str)
    return [token for token in FORBIDDEN_TOKENS if token in blob]


def _parquet_forbidden_hits(path: Path) -> list[str]:
    frame = pd.read_parquet(path)
    hits: list[str] = []
    # Scan values + column names for forbidden tokens.
    chunks = [" ".join(map(str, frame.columns))]
    for col in frame.columns:
        series = frame[col]
        dtype = str(series.dtype)
        if dtype.startswith(("int", "float", "bool", "datetime", "timedelta")):
            continue
        # astype(str) can still leave non-str in edge cases; force map(str).
        chunks.append(" ".join(map(str, series.head(5000).tolist())))
    blob = " ".join(chunks)
    for token in FORBIDDEN_TOKENS:
        if token in blob:
            hits.append(token)
    return hits


def inspect_artifact(path: Path) -> ArtifactInfo:
    if not path.exists():
        raise ChainError(f"missing artifact: {path}")

    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
        if len(frame) <= 0:
            raise ChainError(f"empty artifact: {path}")
        latest_ts = None
        for col in ("timestamp", "end_time", "start_time"):
            if col in frame.columns:
                latest_ts = _iso_ts(frame[col].iloc[-1])
                if latest_ts:
                    break
        if not latest_ts:
            raise ChainError(f"latest timestamp empty: {path}")
        shadow_ok = True
        if "shadow_only" in frame.columns:
            shadow_ok = bool(frame["shadow_only"].astype(bool).all())
            if not shadow_ok:
                raise ChainError(f"shadow_only must be True in {path}")
        return ArtifactInfo(
            path=str(path.relative_to(ROOT)),
            rows=int(len(frame)),
            latest_timestamp=latest_ts,
            shadow_only_ok=shadow_ok,
            kind="parquet",
        )

    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            rows = len(payload)
            latest_ts = None
            if rows == 0:
                raise ChainError(f"empty artifact: {path}")
            last = payload[-1]
            if isinstance(last, dict):
                latest_ts = last.get("end_time") or last.get("timestamp") or last.get("start_time")
        elif isinstance(payload, dict):
            if "rows" in payload and isinstance(payload["rows"], list):
                rows = len(payload["rows"])
                if rows == 0:
                    raise ChainError(f"empty artifact: {path}")
                last = payload["rows"][-1]
                latest_ts = last.get("timestamp") if isinstance(last, dict) else None
            else:
                rows = 1
                latest_ts = payload.get("timestamp")
                if latest_ts is None and not payload:
                    raise ChainError(f"empty artifact: {path}")
        else:
            raise ChainError(f"unsupported json artifact shape: {path}")
        if not latest_ts:
            # lifecycle_context_episodes always has end_time; candles have timestamp;
            # latest has timestamp. Fail if still empty.
            raise ChainError(f"latest timestamp empty: {path}")
        return ArtifactInfo(
            path=str(path.relative_to(ROOT)),
            rows=int(rows),
            latest_timestamp=str(latest_ts),
            shadow_only_ok=True,
            kind="json",
        )

    raise ChainError(f"unsupported artifact type: {path}")


def count_raw_context_episodes(final_memory: pd.DataFrame) -> int:
    """Count contiguous market_context runs — same idea as final_market_context_episodes."""
    if final_memory is None or len(final_memory) == 0 or "market_context" not in final_memory.columns:
        return 0
    work = final_memory.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True, errors="coerce")
    work = work.dropna(subset=["timestamp"]).sort_values("timestamp")
    ctx = work["market_context"].astype(str)
    changed = ctx != ctx.shift(1)
    changed.iloc[0] = True
    return int(changed.sum())


def run_step(script: Path, *, runner: Any = None) -> None:
    if not script.exists():
        raise ChainError(f"missing step script: {script}")
    python = PYTHON if PYTHON.exists() else Path(sys.executable)
    cmd = [str(python), str(script)]
    if runner is None:
        completed = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise ChainError(f"step failed ({script.name}): {detail or f'exit {completed.returncode}'}")
        if completed.stdout:
            print(completed.stdout.rstrip())
        if completed.stderr:
            print(completed.stderr.rstrip(), file=sys.stderr)
        return
    runner(cmd)


def validate_cross_checks() -> tuple[dict[str, bool], dict[str, Any], int, int]:
    checks: dict[str, bool] = {}
    final_path = ROOT / "data" / "cognition" / "final_market_context_memory.parquet"
    life_mem_path = ROOT / "data" / "cognition" / "market_context_lifecycle_memory.parquet"
    life_ep_path = ROOT / "data" / "cognition" / "market_context_lifecycle_episodes.parquet"
    visual_latest_path = (
        ROOT
        / "sandbox"
        / "market_state_context_visualizer"
        / "public"
        / "data"
        / "lifecycle_latest.json"
    )

    final_df = pd.read_parquet(final_path)
    life_df = pd.read_parquet(life_mem_path)
    life_ep_df = pd.read_parquet(life_ep_path)
    visual_latest = json.loads(visual_latest_path.read_text(encoding="utf-8"))

    final_ts = _to_utc(final_df["timestamp"].iloc[-1])
    life_ts = _to_utc(life_df["timestamp"].iloc[-1])
    if final_ts is None or life_ts is None:
        raise ChainError("timestamp comparison failed: empty latest timestamp")
    # final must match or not be older than lifecycle (lifecycle derived from final).
    checks["final_ts_not_older_than_lifecycle"] = final_ts >= life_ts
    if not checks["final_ts_not_older_than_lifecycle"]:
        raise ChainError(
            f"final_market_context latest ({final_ts}) is older than lifecycle ({life_ts})"
        )

    life_latest = life_df.iloc[-1]
    expected = {
        "active_market_context": str(life_latest["active_market_context"]),
        "lifecycle_state": str(life_latest["lifecycle_state"]),
        "active_context_age_bars": int(life_latest["active_context_age_bars"]),
        "action_allowed": bool(life_latest["action_allowed"]),
    }
    actual = {
        "active_market_context": str(visual_latest.get("active_market_context")),
        "lifecycle_state": str(visual_latest.get("lifecycle_state")),
        "active_context_age_bars": int(visual_latest.get("active_context_age_bars") or 0),
        "action_allowed": bool(visual_latest.get("action_allowed")),
    }
    checks["visual_latest_matches_lifecycle_memory"] = expected == actual
    if not checks["visual_latest_matches_lifecycle_memory"]:
        raise ChainError(f"lifecycle visual latest mismatch: expected={expected} actual={actual}")

    # Raw episode count from current final memory (contiguous market_context runs).
    # Equivalent to rebuilding final_market_context_episodes without adding it to the chain.
    raw_episodes_count = count_raw_context_episodes(final_df)
    lifecycle_episodes_count = int(len(life_ep_df))
    checks["lifecycle_episodes_fewer_than_raw"] = lifecycle_episodes_count < raw_episodes_count
    if not checks["lifecycle_episodes_fewer_than_raw"]:
        raise ChainError(
            f"lifecycle episodes ({lifecycle_episodes_count}) not fewer than raw ({raw_episodes_count})"
        )

    # action_allowed False across new shadow layers that carry the field.
    action_ok = True
    for path in SHADOW_PARQUET_LAYERS:
        frame = pd.read_parquet(path)
        if "action_allowed" in frame.columns and bool(frame["action_allowed"].astype(bool).any()):
            action_ok = False
            break
        if "action_allowed_any" in frame.columns and bool(frame["action_allowed_any"].astype(bool).any()):
            action_ok = False
            break
    if visual_latest.get("action_allowed") is True:
        action_ok = False
    checks["action_allowed_false"] = action_ok
    if not action_ok:
        raise ChainError("action_allowed must remain False in shadow layers")

    # Forbidden tokens in parquet shadow outputs.
    forbidden_hits: list[str] = []
    for path in SHADOW_PARQUET_LAYERS:
        forbidden_hits.extend(_parquet_forbidden_hits(path))
    checks["no_failed_short_reprice"] = "FAILED_SHORT_REPRICE" not in forbidden_hits
    if not checks["no_failed_short_reprice"]:
        raise ChainError("FAILED_SHORT_REPRICE found in shadow parquet outputs")

    # Visual JSON must not contain arbitration / chosen / calibrated fields.
    visual_forbidden: list[str] = []
    for path in VISUAL_JSON_PATHS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        visual_forbidden.extend(_contains_forbidden(payload))
    checks["visual_no_arbitration_fields"] = (
        "raw_chosen_context" not in visual_forbidden
        and "calibrated_context" not in visual_forbidden
    )
    if not checks["visual_no_arbitration_fields"]:
        raise ChainError(
            f"lifecycle visual json contains forbidden fields: {sorted(set(visual_forbidden))}"
        )
    checks["visual_no_failed_short_reprice"] = "FAILED_SHORT_REPRICE" not in visual_forbidden
    if not checks["visual_no_failed_short_reprice"]:
        raise ChainError("FAILED_SHORT_REPRICE found in lifecycle visual json")

    latest_context = {
        "timestamp": _iso_ts(life_latest["timestamp"]),
        "active_market_context": expected["active_market_context"],
        "lifecycle_state": expected["lifecycle_state"],
        "active_context_age_bars": expected["active_context_age_bars"],
        "action_allowed": expected["action_allowed"],
        "challenge_ratio": visual_latest.get("open_episode_challenge_ratio"),
        "raw_market_context": str(life_latest.get("raw_market_context")),
    }
    return checks, latest_context, raw_episodes_count, lifecycle_episodes_count


def write_status(result: ChainResult, path: Path = STATUS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = result.to_status_dict()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def run_shadow_chain(*, runner: Any = None, skip_steps: bool = False) -> ChainResult:
    """Run the full shadow chain. `runner` injectable for tests."""
    result = ChainResult(status="FAIL", shadow_only=True)
    artifacts: list[dict[str, Any]] = []

    try:
        for step in CHAIN_STEPS:
            name = step["name"]
            script: Path = step["script"]
            outputs: list[Path] = step["outputs"]
            print(f"\n=== step: {name} ===")
            if not skip_steps:
                run_step(script, runner=runner)
            result.steps_run.append(name)
            for output in outputs:
                info = inspect_artifact(output)
                artifacts.append(
                    {
                        "step": name,
                        "path": info.path,
                        "rows": info.rows,
                        "latest_timestamp": info.latest_timestamp,
                        "shadow_only_ok": info.shadow_only_ok,
                        "kind": info.kind,
                    }
                )
                print(
                    f"ok artifact {info.path}: rows={info.rows} "
                    f"latest={info.latest_timestamp} shadow_only_ok={info.shadow_only_ok}"
                )

        checks, latest_context, raw_count, life_count = validate_cross_checks()
        result.artifacts = artifacts
        result.checks = checks
        result.latest_context = latest_context
        result.raw_episodes_count = raw_count
        result.lifecycle_episodes_count = life_count
        result.status = "PASS"
        return result
    except Exception as exc:
        result.artifacts = artifacts
        result.error = str(exc)
        result.status = "FAIL"
        return result


def print_summary(result: ChainResult) -> None:
    print("\n======== MARKET CONTEXT SHADOW CHAIN ========")
    print(f"chain status: {result.status}")
    if result.error:
        print(f"error: {result.error}")
    print("rows per artifact:")
    for item in result.artifacts:
        print(
            f"  - {item['path']}: rows={item['rows']} latest={item['latest_timestamp']}"
        )
    latest = result.latest_context or {}
    print(f"latest active_market_context: {latest.get('active_market_context', '—')}")
    print(f"latest lifecycle_state: {latest.get('lifecycle_state', '—')}")
    print(f"latest active_context_age_bars: {latest.get('active_context_age_bars', '—')}")
    print(f"latest challenge_ratio from visual latest: {latest.get('challenge_ratio', '—')}")
    print(f"raw episodes count: {result.raw_episodes_count}")
    print(f"lifecycle episodes count: {result.lifecycle_episodes_count}")
    print(f"output sandbox URL: {SANDBOX_URL}")
    print(f"status json: {STATUS_PATH}")


def main() -> int:
    result = run_shadow_chain()
    write_status(result)
    print_summary(result)
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
