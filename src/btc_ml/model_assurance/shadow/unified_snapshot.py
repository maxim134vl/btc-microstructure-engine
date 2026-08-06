"""Unified Shadow Model contract: ACTIVE canonical + EQCORR + STP2.1 (read-only).

SHADOW-MODEL1 — observational overlay snapshot. Does not start processes, rewrite
journals, recompute policies, or enable enforcement.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from btc_ml.model_assurance.registry import read_active_runtime
from btc_ml.model_assurance.toxic_box.common import (
    atomic_write_json,
    canonical_json,
    load_json,
    parse_ts,
    read_jsonl,
    sha256_text,
    utc_now_iso,
)

SNAPSHOT_VERSION = "unified_shadow_model_v1"
SCHEMA_STATUS_OK = "SHADOW_MODEL_ACTIVE_EQCORR_STP21_UNIFIED"

PROMOTION_INELIGIBILITY_REASON = "NO_PROMOTABLE_CANDIDATE_MODEL"
HISTORICAL_STP11_MANIFEST = "e300d491fe470df4df754369ebbaedac25e66505950b555e76d0579467f7115b"

# Evidence remains insufficient below this independent canonical episode count.
MIN_EPISODES_FOR_DESCRIPTIVE = 30
# Shadow health freshness for operational CURRENT.
DEFAULT_STALE_AFTER_SECONDS = 300.0


class ShadowModelBlocker(Exception):
    """Raised when the unified contract cannot be built."""

    def __init__(
        self,
        status: str,
        *,
        field: str,
        source_path: str,
        expected: Any,
        actual: Any,
        minimum_required_fix: str,
    ) -> None:
        super().__init__(status)
        self.status = status
        self.payload = {
            "status": status,
            "missing_or_conflicting_field": field,
            "source_path": source_path,
            "expected": expected,
            "actual": actual,
            "minimum_required_fix": minimum_required_fix,
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def unified_paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance" / "shadow"
    active_epoch = root / "data" / "trading" / "paper_epochs" / "active.json"
    active = load_json(active_epoch) or {}
    epoch_id = str(active.get("paper_epoch_id") or "").strip()

    eqcorr_base = root / "data" / "trading" / "shadow_economic_correlation"
    stp_base = root / "data" / "trading" / "shadow_structural_protection"
    eqcorr_dir = eqcorr_base / "epochs" / epoch_id if epoch_id else eqcorr_base
    stp_dir = stp_base / "epochs" / epoch_id if epoch_id else stp_base

    return {
        "root": root,
        "base": base,
        "snapshots": base / "snapshots",
        "latest": base / "latest" / "current.json",
        "comparisons_dir": base / "comparisons",
        "model7_comparisons": base / "comparisons" / "active_shadow_comparisons.jsonl",
        "model7_summary": base / "snapshots" / "latest_summary.json",
        "active_epoch": active_epoch,
        "eqcorr_dir": eqcorr_dir,
        "stp_dir": stp_dir,
        "live1a_pid": root / "run" / "intrabar_cognition.pid",
        "live1b_pid": root / "run" / "intrabar_paper_manager.pid",
        "eqcorr_pid": root / "run" / "shadow_economic_correlation.pid",
        "stp_pid": root / "run" / "shadow_structural_protection.pid",
        "live1a_health": root / "data" / "runtime" / "intrabar_cognition_health.json",
        "live1b_health": root / "data" / "runtime" / "intrabar_paper_health.json",
        "trd_outcome2_dir": root / "output" / "audits" / "trd_outcome2",
    }


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _process_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _age_seconds(ts: str | None, *, now: datetime | None = None) -> float | None:
    stamp = parse_ts(ts)
    if stamp is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - stamp).total_seconds())


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _books(repo: Path, epoch: str) -> Path:
    return repo / "data" / "trading" / "intrabar_paper" / epoch / "books"


def _closed_trades(repo: Path, epoch: str) -> list[dict[str, Any]]:
    path = _books(repo, epoch) / "trades.jsonl"
    rows = read_jsonl(path)
    out = [t for t in rows if str(t.get("paper_epoch_id") or epoch) == epoch]
    out.sort(key=lambda t: str(t.get("exit_ts") or t.get("closed_at") or ""))
    return out


def _open_positions(repo: Path, epoch: str) -> list[dict[str, Any]]:
    path = _books(repo, epoch) / "positions.jsonl"
    latest: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        pid = str(row.get("position_id") or "")
        if not pid:
            continue
        latest[pid] = row
    return [p for p in latest.values() if str(p.get("status") or "").upper() == "OPEN"]


def _context_event_count(repo: Path) -> int:
    path = repo / "data" / "runtime" / "context_events.jsonl"
    if not path.exists():
        # common alternate
        alt = repo / "data" / "trading" / "intrabar_cognition" / "context_events.jsonl"
        path = alt if alt.exists() else path
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            n += 1
    return n


def _latest_trd_outcome2(paths: dict[str, Path]) -> dict[str, Any] | None:
    d = paths["trd_outcome2_dir"]
    if not d.exists():
        return None
    files = sorted(d.glob("trd_outcome2_*.json"))
    if not files:
        return None
    return load_json(files[-1])


def _match_baseline_trade(
    rows: list[dict[str, Any]],
    *,
    trade: dict[str, Any],
    policy_id: str | None = None,
    manifest_fp: str | None = None,
    require_baseline_name: bool = True,
) -> list[dict[str, Any]]:
    tid = str(trade.get("trade_id") or "")
    pid = str(trade.get("position_id") or "")
    hits = []
    for row in rows:
        if manifest_fp and str(row.get("policy_manifest_fingerprint") or "") != manifest_fp:
            continue
        pol = str(row.get("policy_id") or "")
        if policy_id and pol != policy_id:
            continue
        if require_baseline_name and "BASELINE" not in pol.upper():
            continue
        if tid and str(row.get("trade_id") or "") == tid:
            hits.append(row)
            continue
        if pid and (
            pid in str(row.get("candidate_id") or "")
            or str(row.get("virtual_position_id") or "").endswith(f"_{pid}")
            or str(row.get("position_id") or "") == pid
        ):
            hits.append(row)
    return hits


def _process_block(
    *,
    name: str,
    pid_path: Path,
    health: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    pid = _read_pid(pid_path)
    alive = _process_alive(pid)
    updated = None if health is None else (health.get("updated_at") or health.get("last_cycle_at"))
    return {
        "name": name,
        "pid": pid,
        "status": "UP" if alive else "DOWN",
        "health": None if health is None else health.get("status"),
        "last_cycle_timestamp": updated,
        "freshness_seconds": _age_seconds(str(updated) if updated else None, now=now),
    }


def _build_active_model(
    *,
    root: Path,
    paths: dict[str, Path],
    epoch: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    active = read_active_runtime(repo_root=root)
    if not active or not active.get("model_id"):
        raise ShadowModelBlocker(
            "SHADOW_MODEL_BLOCKED_ACTIVE_IDENTITY",
            field="model_id",
            source_path=_rel(paths["root"] / "data/model_assurance/registry/active/active_model.json", root),
            expected="registered ACTIVE model_id",
            actual=None,
            minimum_required_fix="Register ACTIVE runtime identity via Model Registry",
        )
    live1a_h = load_json(paths["live1a_health"])
    live1b_h = load_json(paths["live1b_health"])
    live1a = _process_block(name="LIVE1A", pid_path=paths["live1a_pid"], health=live1a_h, now=now)
    live1b = _process_block(name="LIVE1B", pid_path=paths["live1b_pid"], health=live1b_h, now=now)
    paper_epoch_id = str(epoch.get("paper_epoch_id") or "")
    trading_fp = str(epoch.get("trading_contract_fingerprint") or "")
    return {
        "model_id": active.get("model_id"),
        "model_version": active.get("model_version"),
        "model_role": active.get("model_role") or "ACTIVE",
        "model_type": active.get("model_type"),
        "cognition_version": active.get("cognition_version"),
        "rule_contract_version": active.get("rule_contract_version"),
        "trading_contract_fingerprint": trading_fp,
        "feature_schema_version": active.get("feature_schema_version"),
        "data_schema_version": active.get("data_schema_version"),
        "source_commit": active.get("source_commit"),
        "runtime_fingerprint": active.get("runtime_fingerprint"),
        "registry_paper_epoch_id": active.get("paper_epoch_id"),
        "paper_epoch_id": paper_epoch_id,
        "activated_at": epoch.get("activated_at") or active.get("paper_epoch_activated_at"),
        "processes": {"LIVE1A": live1a, "LIVE1B": live1b},
        "runtime_status": "OK" if live1a["status"] == "UP" and live1b["status"] == "UP" else "DEGRADED",
        "last_decision_timestamp": (live1b_h or {}).get("last_decision_timestamp")
        or (live1b_h or {}).get("updated_at"),
        "last_context_event_timestamp": (live1a_h or {}).get("last_context_event_timestamp")
        or (live1a_h or {}).get("updated_at"),
        "paper_only": bool(epoch.get("paper_only", active.get("paper_only", True))),
        "real_execution": bool(epoch.get("real_execution", active.get("real_execution", False))),
    }


def _eqcorr_component(
    *,
    root: Path,
    paths: dict[str, Path],
    epoch_id: str,
    trading_fp: str,
    closed_trades: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    d = paths["eqcorr_dir"]
    health = load_json(d / "health.json")
    manifest = load_json(d / "policy_manifest.json") or {}
    ck = load_json(d / "checkpoint.json") or {}
    if health is None:
        raise ShadowModelBlocker(
            "SHADOW_MODEL_BLOCKED_EQCORR_IDENTITY",
            field="health.json",
            source_path=_rel(d / "health.json", root),
            expected="EQCORR health present",
            actual=None,
            minimum_required_fix="Ensure EQCORR shadow process has written health.json",
        )
    fp = (
        manifest.get("shadow_policy_manifest_fingerprint")
        or health.get("shadow_policy_manifest_fingerprint")
        or ck.get("shadow_policy_manifest_fingerprint")
    )
    source_epoch = str(health.get("source_epoch_id") or manifest.get("source_epoch_id") or "")
    source_fp = str(
        health.get("source_contract_fingerprint")
        or manifest.get("source_contract_fingerprint")
        or ""
    )
    if source_epoch and source_epoch != epoch_id:
        raise ShadowModelBlocker(
            "SHADOW_MODEL_VERSION_CONFLICT",
            field="source_epoch_id",
            source_path=_rel(d / "health.json", root),
            expected=epoch_id,
            actual=source_epoch,
            minimum_required_fix="Align EQCORR to the active paper epoch",
        )
    if source_fp and source_fp != trading_fp:
        raise ShadowModelBlocker(
            "SHADOW_MODEL_VERSION_CONFLICT",
            field="source_contract_fingerprint",
            source_path=_rel(d / "health.json", root),
            expected=trading_fp,
            actual=source_fp,
            minimum_required_fix="Align EQCORR trading contract fingerprint to active epoch",
        )
    if not fp and not source_fp:
        raise ShadowModelBlocker(
            "SHADOW_MODEL_BLOCKED_EQCORR_IDENTITY",
            field="shadow_policy_manifest_fingerprint",
            source_path=_rel(d / "policy_manifest.json", root),
            expected="non-empty EQCORR manifest fingerprint",
            actual=fp,
            minimum_required_fix="Write EQCORR policy_manifest fingerprint from runtime",
        )

    vtrades = read_jsonl(d / "virtual_trades.jsonl")
    vpos = read_jsonl(d / "virtual_positions.jsonl")
    candidates = read_jsonl(d / "candidate_snapshots.jsonl")
    policy_ids = list(manifest.get("policy_ids") or [])
    if not policy_ids:
        policy_ids = sorted({str(r.get("policy_id")) for r in read_jsonl(d / "policy_decisions.jsonl") if r.get("policy_id")})

    attached = 0
    pending_ids: list[str] = []
    for trade in closed_trades:
        hits = _match_baseline_trade(vtrades, trade=trade, require_baseline_name=True)
        if hits:
            attached += 1
        else:
            pending_ids.append(str(trade.get("trade_id")))

    latest_vpos: dict[str, dict[str, Any]] = {}
    for row in vpos:
        key = f"{row.get('policy_id')}|{row.get('virtual_position_id')}"
        latest_vpos[key] = row
    open_n = sum(1 for r in latest_vpos.values() if str(r.get("status") or "").upper() == "OPEN")
    closed_n = sum(1 for r in latest_vpos.values() if str(r.get("status") or "").upper() == "CLOSED")

    proc = _process_block(name="EQCORR", pid_path=paths["eqcorr_pid"], health=health, now=now)
    latest_cand = candidates[-1] if candidates else {}
    latest_trade_row = vtrades[-1] if vtrades else {}
    return {
        "shadow_component_id": "EQCORR",
        "shadow_role": "SHADOW",
        "shadow_subject_type": "RISK_POLICY_OVERLAY",
        "version": health.get("eqcorr1_status") or health.get("status") or "SHADOW_EQCORR1",
        "manifest_fingerprint": fp or source_fp,
        "source_commit": manifest.get("source_commit") or health.get("source_commit"),
        "paper_epoch_id": source_epoch or epoch_id,
        "trading_contract_fingerprint": source_fp or trading_fp,
        "mode": health.get("mode") or manifest.get("mode") or "OBSERVE_ONLY",
        "read_only": bool(health.get("read_only", True)),
        "enforcement_enabled": bool(health.get("enforcement_enabled", False)),
        "process_pid": proc["pid"],
        "process_status": proc["status"],
        "health_status": health.get("status"),
        "last_cycle_timestamp": health.get("updated_at"),
        "freshness_seconds": proc["freshness_seconds"],
        "policy_ids": policy_ids,
        "policy_count": len(policy_ids),
        "eligible_canonical_candidates": int(health.get("candidate_count") or len(candidates)),
        "processed_candidates": int(health.get("candidate_count") or len({c.get("candidate_id") for c in candidates})),
        "eligible_closed_trades": len(closed_trades),
        "baseline_outcomes_attached": attached,
        "baseline_outcomes_pending": len(pending_ids),
        "baseline_pending_trade_ids": pending_ids,
        "baseline_divergence_count": int(health.get("baseline_divergence_count") or 0),
        "open_virtual_positions": int(health.get("open_virtual_positions") or open_n),
        "closed_virtual_positions": closed_n,
        "valid_outcome_count": int(health.get("closed_outcome_count") or len(vtrades)),
        "invalidated_manifest_count": 0,
        "excluded_outcome_count": 0,
        "latest_candidate_id": latest_cand.get("candidate_id"),
        "latest_canonical_trade_id": latest_trade_row.get("trade_id"),
        "latest_outcome_timestamp": latest_trade_row.get("exit_timestamp")
        or health.get("last_trade_close_timestamp"),
    }


def _policy_family(policy_id: str) -> str:
    pid = str(policy_id or "")
    if pid == "BASELINE_CANONICAL" or pid.startswith("BASELINE"):
        return "BASELINE"
    if pid.startswith("STRUCTURAL_SL_CANONICAL_TP"):
        return "STRUCTURAL_SL_ONLY"
    if pid.startswith("CANONICAL_SL_STRUCTURAL_TP"):
        return "STRUCTURAL_TP_ONLY"
    if pid.startswith("STRUCTURAL_SL_STRUCTURAL_TP"):
        return "FULL_STRUCTURAL"
    return "OTHER"


def _stp_component(
    *,
    root: Path,
    paths: dict[str, Path],
    epoch_id: str,
    trading_fp: str,
    closed_trades: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    d = paths["stp_dir"]
    health = load_json(d / "health.json")
    manifest = load_json(d / "policy_manifest.json") or {}
    ck = load_json(d / "checkpoint.json") or {}
    if health is None:
        raise ShadowModelBlocker(
            "SHADOW_MODEL_BLOCKED_STP_IDENTITY",
            field="health.json",
            source_path=_rel(d / "health.json", root),
            expected="STP2.1 health present",
            actual=None,
            minimum_required_fix="Ensure STP2.1 shadow process has written health.json",
        )
    fp = str(
        health.get("policy_manifest_fingerprint")
        or ck.get("active_policy_manifest_fingerprint")
        or manifest.get("policy_manifest_fingerprint")
        or ""
    )
    if not fp:
        raise ShadowModelBlocker(
            "SHADOW_MODEL_BLOCKED_STP_IDENTITY",
            field="policy_manifest_fingerprint",
            source_path=_rel(d / "health.json", root),
            expected="active STP2.1 manifest fingerprint",
            actual=None,
            minimum_required_fix="Resolve active STP2.1 fingerprint from health/manifest",
        )
    if fp == HISTORICAL_STP11_MANIFEST:
        raise ShadowModelBlocker(
            "SHADOW_MODEL_HISTORICAL_CONTAMINATION",
            field="policy_manifest_fingerprint",
            source_path=_rel(d / "health.json", root),
            expected="active STP2.1 manifest (not historical STP1.1)",
            actual=fp,
            minimum_required_fix="Activate STP2.1 manifest; exclude e300d491…",
        )
    source_epoch = str(health.get("source_epoch_id") or manifest.get("source_epoch_id") or "")
    source_fp = str(
        health.get("source_contract_fingerprint")
        or manifest.get("source_trading_contract_fingerprint")
        or ""
    )
    if source_epoch and source_epoch != epoch_id:
        raise ShadowModelBlocker(
            "SHADOW_MODEL_VERSION_CONFLICT",
            field="source_epoch_id",
            source_path=_rel(d / "health.json", root),
            expected=epoch_id,
            actual=source_epoch,
            minimum_required_fix="Align STP2.1 to the active paper epoch",
        )
    if source_fp and source_fp != trading_fp:
        raise ShadowModelBlocker(
            "SHADOW_MODEL_VERSION_CONFLICT",
            field="source_contract_fingerprint",
            source_path=_rel(d / "health.json", root),
            expected=trading_fp,
            actual=source_fp,
            minimum_required_fix="Align STP2.1 trading fingerprint to active epoch",
        )

    invalidated = set(health.get("invalidated_manifest_fingerprints") or []) | set(
        ck.get("invalidated_manifest_fingerprints") or []
    )
    invalidated.add(HISTORICAL_STP11_MANIFEST)

    vtrades_all = read_jsonl(d / "virtual_trades.jsonl")
    vpos_all = read_jsonl(d / "virtual_positions.jsonl")
    # Current-only: active manifest, exclude invalidated
    vtrades = [
        r
        for r in vtrades_all
        if str(r.get("policy_manifest_fingerprint") or "") == fp
        and str(r.get("policy_manifest_fingerprint") or "") not in invalidated
    ]
    vpos = [
        r
        for r in vpos_all
        if str(r.get("policy_manifest_fingerprint") or "") == fp
        and not r.get("invalidated")
        and r.get("research_valid") is not False
    ]
    candidates = [
        c
        for c in read_jsonl(d / "candidate_snapshots.jsonl")
        if str(c.get("policy_manifest_fingerprint") or "") == fp
    ]
    decisions = [
        drow
        for drow in read_jsonl(d / "policy_decisions.jsonl")
        if str(drow.get("policy_manifest_fingerprint") or "") == fp and not drow.get("record_type")
    ]
    policy_ids = sorted({str(drow.get("policy_id")) for drow in decisions if drow.get("policy_id")})
    families = sorted({_policy_family(pid) for pid in policy_ids})

    attached = 0
    pending_ids: list[str] = []
    structural_attached = 0
    structural_pending = 0
    for trade in closed_trades:
        base_hits = _match_baseline_trade(
            vtrades, trade=trade, policy_id="BASELINE_CANONICAL", manifest_fp=fp, require_baseline_name=False
        )
        if base_hits:
            attached += 1
        else:
            pending_ids.append(str(trade.get("trade_id")))
        struct_hits = [
            r
            for r in vtrades
            if _policy_family(str(r.get("policy_id"))) != "BASELINE"
            and (
                str(r.get("trade_id") or "") == str(trade.get("trade_id") or "")
                or str(trade.get("position_id") or "") in str(r.get("candidate_id") or "")
            )
        ]
        if struct_hits:
            structural_attached += 1
        else:
            structural_pending += 1

    latest_vpos: dict[str, dict[str, Any]] = {}
    for row in vpos:
        key = f"{row.get('policy_id')}|{row.get('virtual_position_id')}"
        latest_vpos[key] = row
    open_n = sum(1 for r in latest_vpos.values() if str(r.get("status") or "").upper() == "OPEN")
    closed_n = sum(1 for r in latest_vpos.values() if str(r.get("status") or "").upper() == "CLOSED")
    excluded_pos = sum(1 for r in vpos_all if r.get("invalidated") or str(r.get("policy_manifest_fingerprint") or "") in invalidated)
    excluded_out = sum(
        1
        for r in vtrades_all
        if str(r.get("policy_manifest_fingerprint") or "") in invalidated
        or str(r.get("policy_manifest_fingerprint") or "") != fp
    )

    proc = _process_block(name="STP2.1", pid_path=paths["stp_pid"], health=health, now=now)
    latest_cand = candidates[-1] if candidates else {}
    latest_trade_row = vtrades[-1] if vtrades else {}
    return {
        "shadow_component_id": "STP2.1",
        "shadow_role": "SHADOW",
        "shadow_subject_type": "EXIT_POLICY_OVERLAY",
        "version": health.get("stp_generation")
        or manifest.get("generation")
        or manifest.get("shadow_model_version")
        or "SHADOW_STP2_1",
        "manifest_fingerprint": fp,
        "source_commit": manifest.get("source_commit") or health.get("source_commit"),
        "paper_epoch_id": source_epoch or epoch_id,
        "trading_contract_fingerprint": source_fp or trading_fp,
        "mode": health.get("mode") or "OBSERVE_ONLY",
        "read_only": bool(health.get("read_only", True)),
        "enforcement_enabled": bool(health.get("enforcement_enabled", False)),
        "process_pid": proc["pid"],
        "process_status": proc["status"],
        "health_status": health.get("status"),
        "last_cycle_timestamp": health.get("updated_at"),
        "freshness_seconds": proc["freshness_seconds"],
        "policy_ids": policy_ids,
        "policy_families": families,
        "policy_count": len(policy_ids),
        "eligible_canonical_candidates": int(health.get("candidate_count") or len(candidates)),
        "processed_candidates": len({c.get("candidate_id") for c in candidates}),
        "eligible_closed_trades": len(closed_trades),
        "baseline_outcomes_attached": attached,
        "baseline_outcomes_pending": len(pending_ids),
        "baseline_pending_trade_ids": pending_ids,
        "baseline_divergence_count": int(health.get("baseline_divergence_count") or 0),
        "structural_outcomes_attached": structural_attached,
        "structural_outcomes_pending": structural_pending,
        "open_virtual_positions": int(health.get("virtual_positions_open_valid") or open_n),
        "closed_virtual_positions": int(health.get("virtual_trades_closed") or closed_n),
        "valid_outcome_count": len(vtrades),
        "invalidated_manifest_count": len(invalidated),
        "excluded_position_count": excluded_pos,
        "excluded_outcome_count": excluded_out,
        "latest_candidate_id": latest_cand.get("candidate_id"),
        "latest_canonical_trade_id": latest_trade_row.get("trade_id"),
        "latest_outcome_timestamp": latest_trade_row.get("exit_timestamp"),
    }


def _classify_statuses(
    *,
    eqcorr: dict[str, Any],
    stp: dict[str, Any],
    episode_count: int,
    stale_after: float,
) -> tuple[str, str]:
    # Evidence first — never promote small samples
    if episode_count <= 0:
        evidence = "NO_ELIGIBLE_EPISODES"
    elif episode_count < MIN_EPISODES_FOR_DESCRIPTIVE:
        evidence = "INSUFFICIENT_SAMPLE"
    else:
        evidence = "DESCRIPTIVE_COMPARISON_AVAILABLE"

    eq_up = eqcorr.get("process_status") == "UP"
    stp_up = stp.get("process_status") == "UP"
    eq_fresh = (eqcorr.get("freshness_seconds") is not None) and float(eqcorr["freshness_seconds"]) <= stale_after
    stp_fresh = (stp.get("freshness_seconds") is not None) and float(stp["freshness_seconds"]) <= stale_after
    pending = int(eqcorr.get("baseline_outcomes_pending") or 0) + int(stp.get("baseline_outcomes_pending") or 0)
    div = int(eqcorr.get("baseline_divergence_count") or 0) + int(stp.get("baseline_divergence_count") or 0)

    if div > 0:
        return "SHADOW_FAILED", evidence
    if not eq_up or not stp_up:
        # Process down is operational degradation, not missing sample
        if eqcorr.get("process_pid") is None and stp.get("process_pid") is None:
            return "SHADOW_MISSING_DATA", evidence
        return "SHADOW_STALE", evidence
    if not eq_fresh or not stp_fresh:
        return "SHADOW_STALE", evidence
    if pending > 0:
        return "SHADOW_COLLECTING", evidence
    # Fully caught up — CURRENT even when evidence is still insufficient
    return "SHADOW_CURRENT", evidence


def build_unified_shadow_model_snapshot(
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    source_commit: str | None = None,
) -> dict[str, Any]:
    root = repo_root or _repo_root()
    paths = unified_paths(root)
    current = now or datetime.now(timezone.utc)
    created_at = current.isoformat().replace("+00:00", "Z")

    epoch = load_json(paths["active_epoch"])
    if not epoch or not epoch.get("paper_epoch_id"):
        raise ShadowModelBlocker(
            "SHADOW_MODEL_BLOCKED_ACTIVE_IDENTITY",
            field="paper_epoch_id",
            source_path=_rel(paths["active_epoch"], root),
            expected="active paper epoch",
            actual=None,
            minimum_required_fix="Ensure data/trading/paper_epochs/active.json exists",
        )
    epoch_id = str(epoch["paper_epoch_id"])
    trading_fp = str(epoch.get("trading_contract_fingerprint") or "")
    if not trading_fp:
        raise ShadowModelBlocker(
            "SHADOW_MODEL_BLOCKED_ACTIVE_IDENTITY",
            field="trading_contract_fingerprint",
            source_path=_rel(paths["active_epoch"], root),
            expected="non-empty trading_contract_fingerprint",
            actual=None,
            minimum_required_fix="Active epoch must carry trading_contract_fingerprint",
        )

    active_model = _build_active_model(root=root, paths=paths, epoch=epoch, now=current)
    closed = _closed_trades(root, epoch_id)
    opens = _open_positions(root, epoch_id)
    eqcorr = _eqcorr_component(
        root=root, paths=paths, epoch_id=epoch_id, trading_fp=trading_fp, closed_trades=closed, now=current
    )
    stp = _stp_component(
        root=root, paths=paths, epoch_id=epoch_id, trading_fp=trading_fp, closed_trades=closed, now=current
    )

    fully = 0
    last_fully_id = None
    last_fully_ts = None
    for trade in closed:
        tid = str(trade.get("trade_id") or "")
        eq_ok = tid not in set(eqcorr.get("baseline_pending_trade_ids") or [])
        stp_ok = tid not in set(stp.get("baseline_pending_trade_ids") or [])
        if eq_ok and stp_ok:
            fully += 1
            last_fully_id = tid
            last_fully_ts = trade.get("exit_ts") or trade.get("closed_at")

    total_closed = len(closed)
    coverage_ratio = (fully / total_closed) if total_closed else None
    episode_count = total_closed  # canonical closed trades as market episodes
    virtual_variant_count = int(eqcorr.get("valid_outcome_count") or 0) + int(stp.get("valid_outcome_count") or 0)

    operational, evidence = _classify_statuses(
        eqcorr=eqcorr, stp=stp, episode_count=episode_count, stale_after=stale_after_seconds
    )

    # Historical MODEL-7 prediction comparisons are separate from current overlays
    hist_rows = read_jsonl(paths["model7_comparisons"]) if paths["model7_comparisons"].exists() else []
    historical_separation = {
        "historical_shadow_evaluations_count": len(hist_rows),
        "current_eqcorr_outcomes_count": int(eqcorr.get("valid_outcome_count") or 0),
        "current_stp_outcomes_count": int(stp.get("valid_outcome_count") or 0),
        "historical_source_paths": [
            _rel(paths["model7_comparisons"], root),
            _rel(paths["model7_summary"], root),
        ],
        "current_source_paths": [
            _rel(paths["eqcorr_dir"], root),
            _rel(paths["stp_dir"], root),
            _rel(paths["active_epoch"], root),
        ],
        "historical_in_current_status": False,
    }

    trd2 = _latest_trd_outcome2(paths)
    source_files = {
        "active_epoch": _rel(paths["active_epoch"], root),
        "eqcorr_health": _rel(paths["eqcorr_dir"] / "health.json", root),
        "eqcorr_manifest": _rel(paths["eqcorr_dir"] / "policy_manifest.json", root),
        "stp_health": _rel(paths["stp_dir"] / "health.json", root),
        "stp_manifest": _rel(paths["stp_dir"] / "policy_manifest.json", root),
        "trd_outcome2": _rel(paths["trd_outcome2_dir"] / (sorted(paths["trd_outcome2_dir"].glob("trd_outcome2_*.json"))[-1].name), root)
        if paths["trd_outcome2_dir"].exists() and list(paths["trd_outcome2_dir"].glob("trd_outcome2_*.json"))
        else None,
    }
    source_hashes = {
        "active_epoch": _file_sha256(paths["active_epoch"]),
        "eqcorr_health": _file_sha256(paths["eqcorr_dir"] / "health.json"),
        "eqcorr_manifest": _file_sha256(paths["eqcorr_dir"] / "policy_manifest.json"),
        "stp_health": _file_sha256(paths["stp_dir"] / "health.json"),
        "stp_manifest": _file_sha256(paths["stp_dir"] / "policy_manifest.json"),
    }

    commit = source_commit
    if not commit:
        try:
            import subprocess

            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=str(root), text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:
            commit = active_model.get("source_commit")

    causal_cutoff = (
        stp.get("latest_outcome_timestamp")
        or eqcorr.get("latest_outcome_timestamp")
        or last_fully_ts
        or created_at
    )

    # Deterministic core (exclude wall-clock created_at / snapshot_id)
    core = {
        "snapshot_version": SNAPSHOT_VERSION,
        "causal_cutoff": causal_cutoff,
        "source_commit": commit,
        "active_model": active_model,
        "shadow_components": {"EQCORR": eqcorr, "STP2.1": stp},
        "coverage": {
            "active_epoch_id": epoch_id,
            "canonical_context_events_total": _context_event_count(root),
            "canonical_candidates_total": max(
                int(eqcorr.get("eligible_canonical_candidates") or 0),
                int(stp.get("eligible_canonical_candidates") or 0),
            ),
            "canonical_positions_open": len(opens),
            "canonical_trades_closed": total_closed,
            "eqcorr_candidates_processed": int(eqcorr.get("processed_candidates") or 0),
            "eqcorr_closed_trades_covered": int(eqcorr.get("baseline_outcomes_attached") or 0),
            "eqcorr_closed_trades_pending": int(eqcorr.get("baseline_outcomes_pending") or 0),
            "stp_candidates_processed": int(stp.get("processed_candidates") or 0),
            "stp_closed_trades_covered": int(stp.get("baseline_outcomes_attached") or 0),
            "stp_closed_trades_pending": int(stp.get("baseline_outcomes_pending") or 0),
            "cross_layer_fully_covered_closed_trades": fully,
            "cross_layer_total_closed_trades": total_closed,
            "coverage_ratio": coverage_ratio,
            "last_fully_covered_trade_id": last_fully_id,
            "last_fully_covered_timestamp": last_fully_ts,
        },
        "comparisons": {
            "eqcorr_baseline_divergence_count": int(eqcorr.get("baseline_divergence_count") or 0),
            "stp_baseline_divergence_count": int(stp.get("baseline_divergence_count") or 0),
            "eqcorr_pending_baseline_outcomes": int(eqcorr.get("baseline_outcomes_pending") or 0),
            "stp_pending_baseline_outcomes": int(stp.get("baseline_outcomes_pending") or 0),
            "eqcorr_policy_outcomes_available": int(eqcorr.get("valid_outcome_count") or 0),
            "stp_policy_outcomes_available": int(stp.get("valid_outcome_count") or 0),
            "sample_unit": "CANONICAL_MARKET_EPISODE",
            "independent_canonical_episode_count": episode_count,
            "virtual_variant_count": virtual_variant_count,
            "economic_comparison_status": "INSUFFICIENT_SAMPLE"
            if episode_count < MIN_EPISODES_FOR_DESCRIPTIVE
            else "DESCRIPTIVE_ONLY",
        },
        "historical_separation": historical_separation,
        "runtime_safety": {
            "paper_only": bool(active_model.get("paper_only", True)),
            "real_execution": bool(active_model.get("real_execution", False)),
            "enforcement_enabled": False,
            "eqcorr_enforcement_enabled": bool(eqcorr.get("enforcement_enabled", False)),
            "stp_enforcement_enabled": bool(stp.get("enforcement_enabled", False)),
            "runtime_impact": "NONE",
            "command_bus_writes": False,
        },
        "source_hashes": source_hashes,
        "trd_outcome2_status": None if trd2 is None else trd2.get("status"),
        "operational_status": operational,
        "evidence_status": evidence,
        "promotion_eligible": False,
        "promotion_ineligibility_reason": PROMOTION_INELIGIBILITY_REASON,
    }
    content_hash = sha256_text(canonical_json(core))
    snapshot_id = f"USM_{content_hash[:24]}"

    snapshot = {
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "content_hash": content_hash,
        "shadow_status": operational,
        "source_files": source_files,
        **core,
    }
    # Final top-level status for success criterion
    if (
        operational in {"SHADOW_CURRENT", "SHADOW_COLLECTING"}
        and eqcorr.get("manifest_fingerprint")
        and stp.get("manifest_fingerprint")
        and stp.get("manifest_fingerprint") != HISTORICAL_STP11_MANIFEST
        and not snapshot["promotion_eligible"]
        and historical_separation["historical_in_current_status"] is False
    ):
        snapshot["status"] = SCHEMA_STATUS_OK
    else:
        snapshot["status"] = operational
    return snapshot


def persist_unified_snapshot(
    snapshot: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Write immutable snapshot (idempotent) + latest derived view."""
    root = repo_root or _repo_root()
    paths = unified_paths(root)
    paths["snapshots"].mkdir(parents=True, exist_ok=True)
    paths["latest"].parent.mkdir(parents=True, exist_ok=True)

    snap_path = paths["snapshots"] / f"{snapshot['snapshot_id']}.json"
    wrote_immutable = False
    if snap_path.exists():
        existing = load_json(snap_path) or {}
        if existing.get("content_hash") == snapshot.get("content_hash"):
            wrote_immutable = False
        else:
            atomic_write_json(snap_path, snapshot)
            wrote_immutable = True
    else:
        atomic_write_json(snap_path, snapshot)
        wrote_immutable = True

    latest_view = {
        "status": snapshot.get("status"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "content_hash": snapshot.get("content_hash"),
        "created_at": snapshot.get("created_at"),
        "updated_at": utc_now_iso(),
        "operational_status": snapshot.get("operational_status"),
        "evidence_status": snapshot.get("evidence_status"),
        "promotion_eligible": snapshot.get("promotion_eligible"),
        "promotion_ineligibility_reason": snapshot.get("promotion_ineligibility_reason"),
        "runtime_impact": (snapshot.get("runtime_safety") or {}).get("runtime_impact"),
        "active_model": snapshot.get("active_model"),
        "shadow_components": snapshot.get("shadow_components"),
        "coverage": snapshot.get("coverage"),
        "comparisons": snapshot.get("comparisons"),
        "historical_separation": snapshot.get("historical_separation"),
        "runtime_safety": snapshot.get("runtime_safety"),
        "immutable_snapshot_path": _rel(snap_path, root),
        "source_commit": snapshot.get("source_commit"),
        "causal_cutoff": snapshot.get("causal_cutoff"),
    }
    atomic_write_json(paths["latest"], latest_view)
    return {
        "status": snapshot.get("status"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "immutable_path": str(snap_path),
        "latest_path": str(paths["latest"]),
        "wrote_immutable": wrote_immutable,
    }


def load_latest_unified_shadow(*, repo_root: Path | None = None) -> dict[str, Any] | None:
    return load_json(unified_paths(repo_root)["latest"])
