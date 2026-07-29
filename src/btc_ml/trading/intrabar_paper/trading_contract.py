"""Full trading-contract manifest, fingerprint, and epoch clone helpers.

The active paper epoch identity JSON is NOT the full trading contract.
This module builds a normalized, fingerprintable manifest from:

  - epoch registry record
  - config/intrabar_paper_execution.json
  - hardcoded LIVE1B engine/consumer/BBO rules (explicitly snapshotted)

Clone path: deep-copy full manifest → allowlisted overrides only → new fingerprint.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import IntrabarPaperConfig, load_intrabar_paper_config
from .consumer import ENTRY_EVENTS, EXIT_EVENTS
from .economics import resolve_risk_sizing
from .epoch import PaperEpoch, load_active_epoch

MANIFEST_SCHEMA = "trading_contract_manifest_v1"
CANONICAL_SOURCE_EPOCH = "INTRABAR_RULES_V1_20260728_110636"

CLASS_EPOCH_SNAPSHOTTED = "EPOCH_SNAPSHOTTED"
CLASS_GLOBAL_RUNTIME = "GLOBAL_RUNTIME_DEPENDENCY"
CLASS_HARDCODED = "HARDCODED_RULE"
CLASS_ENVIRONMENT = "ENVIRONMENT_DEPENDENCY"
CLASS_DERIVED = "DERIVED_VALUE"
CLASS_UNKNOWN = "UNKNOWN"

FIELD_NOT_CANONICALLY_SNAPSHOTTED = "FIELD_NOT_CANONICALLY_SNAPSHOTTED"
EPOCH_CLONE_BLOCKED = "EPOCH_CLONE_BLOCKED_INCOMPLETE_SOURCE_CONTRACT"
RISK_DELTA_VIOLATION = "RISK_DELTA_CONTRACT_VIOLATION"
ZERO_DIFF_MATCH = "ZERO_DIFF_CLONE_REPLAY_MATCH"
ZERO_DIFF_DIVERGENCE = "ZERO_DIFF_CLONE_REPLAY_DIVERGENCE"
NEW_EPOCH_ACTIVATION_BLOCKED = "NEW_EPOCH_ACTIVATION_BLOCKED"
SLEEVE2_NON_CAPITAL_DIFF = "TRD_SLEEVE2_BLOCKED_NON_CAPITAL_CONTRACT_DIFF"
SLEEVE2_SOURCE_MISMATCH = "TRD_SLEEVE2_BLOCKED_SOURCE_CONTRACT_MISMATCH"
SLEEVE2_AWAITING_FLAT = "TRD_SLEEVE2_READY_AWAITING_FLAT"
SLEEVE2_ACTIVE = "TRD_SLEEVE2_PER_TIMEFRAME_CAPITAL_ACTIVE"
SLEEVE2_FREEZE = "TRD_SLEEVE2_ACTIVATION_FREEZE_REQUIRED"
EXPECTED_SOURCE_FINGERPRINT = "a6a916a767c6cfe83e9eb4581103d422bfc1adad6a56dfbf8f867930c129cb5a"
EPOCH_PREFIX_SLEEVE2 = "PER_TF_EQUITY_1PCT_V1_"

# Capital / risk deltas that may differ between parent and derived contracts.
RISK_DELTA_ALLOWLIST = frozenset(
    {
        "capital.capital_model",
        "capital.timeframe_initial_equity_usd",
        "capital.timeframe_current_equity_source",
        "capital.risk_budget_source",
        "capital.master_initial_equity_usd",
        "capital.risk_pct_per_trade",
        "capital.max_risk_per_trade_usd",
        "position_sizing.equity_basis",
        "position_sizing.risk_percentage",
        "position_sizing.risk_cap_semantics",
        "position_sizing.max_risk_per_trade_usd",
        "position_sizing.max_risk_per_trade_pct",
        "epoch_identity.paper_epoch_id",
        "epoch_identity.epoch_id",
        "parent_epoch_id",
    }
)

# TRD-SLEEVE2 hard allowlist (stricter than EPOCH1 research clone).
SLEEVE2_CONTRACT_ALLOWLIST = frozenset(
    {
        "capital.capital_model",
        "capital.master_initial_equity_usd",
        "capital.timeframe_initial_equity_usd",
        "capital.timeframe_current_equity_source",
        "capital.risk_budget_source",
        "capital.risk_pct_per_trade",
        "position_sizing.equity_basis",
        "position_sizing.risk_cap_semantics",
    }
)

# Derived economic outcomes allowed to differ under a risk-only capital change.
RISK_DELTA_REPLAY_ALLOW_FIELDS = frozenset(
    {
        "equity_at_entry",
        "risk_amount_usd",
        "risk_budget_usd",
        "quantity",
        "entry_notional",
        "position_notional",
        "notional",
        "entry_fee_usd",
        "exit_fee_usd",
        "fees_usd",
        "entry_slippage_usd",
        "exit_slippage_usd",
        "slippage_usd",
        "gross_pnl_usd",
        "net_pnl_usd",
        "estimated_loss",
        "r_multiple",
    }
)

# Top-level keys excluded from trading-contract fingerprint.
_FINGERPRINT_EXCLUDE = frozenset(
    {
        "epoch_identity",
        "parent_epoch_id",
        "field_provenance",
        "clone_meta",
        "trading_contract_fingerprint",
    }
)

_CRITICAL_PATHS = (
    "context_consumption.accepted_event_types",
    "context_consumption.accepted_timeframes",
    "context_consumption.context_dedup_key",
    "context_consumption.episode_dedup_key",
    "entry_rules.one_position_per_timeframe",
    "entry_rules.entry_price_source",
    "position_sizing.cost_aware_stop_sizing",
    "position_sizing.max_risk_per_trade_pct",
    "protection_geometry.stop_method",
    "protection_geometry.take_method",
    "protection_geometry.risk_reward_ratio",
    "exit_rules.tp_trigger",
    "exit_rules.sl_trigger",
    "exit_rules.context_end",
    "exit_rules.context_flip",
    "market_execution.long_entry",
    "market_execution.short_entry",
    "market_execution.long_exit",
    "market_execution.short_exit",
    "costs.entry_fee_bps",
    "costs.exit_fee_bps",
    "safety.paper_only",
    "safety.real_execution_enabled",
    "capital.capital_model",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _get_path(obj: dict[str, Any], dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_path(obj: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def canonical_json(obj: Any) -> str:
    """Stable canonical JSON for hashing / diffs."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def trading_contract_fingerprint(manifest: dict[str, Any]) -> str:
    body = {k: v for k, v in manifest.items() if k not in _FINGERPRINT_EXCLUDE}
    digest = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    return digest


def _hardcoded_rules() -> dict[str, Any]:
    """Explicit snapshot of engine/consumer/BBO rules that are not in JSON config."""
    return {
        "accepted_event_types": sorted(ENTRY_EVENTS | EXIT_EVENTS),
        "entry_event_types": sorted(ENTRY_EVENTS),
        "exit_event_types": sorted(EXIT_EVENTS),
        "event_ordering": "event_monotonic_ns asc, context_event_id asc",
        "causal_cutoff_rules": (
            "ISO activated_at gate across processes; optional activated_at_monotonic_ns "
            "same-clock gate; BBO receive_monotonic_ns <= command_monotonic_ns; "
            "BBO age <= max_bbo_age_ms"
        ),
        "context_dedup_key": "{paper_epoch_id}|{context_event_id}|{timeframe}|{action}",
        "episode_dedup_key": "lifecycle_episode_id",
        "already_traded_episode_behavior": (
            "CONTEXT_START blocked with ENTRY_BLOCKED_EPISODE_ALREADY_TRADED; "
            "CONTEXT_FLIP close→open not blocked by episode lock"
        ),
        "entry_eligibility": "CONTEXT_START/FLIP with side in {LONG,SHORT}; no OBSERVE/STAND_ASIDE entry",
        "long_short_mapping": {
            "LONG_CONTEXT": "LONG",
            "SHORT_CONTEXT": "SHORT",
            "LONG": "LONG",
            "SHORT": "SHORT",
        },
        "one_position_per_timeframe": True,
        "same_direction_duplicate_handling": "ENTRY_BLOCKED_ACTIVE_POSITION",
        "flip_behavior": "exit existing if matching from_side then enter flip_to at mono+1",
        "entry_price_source": "causal BBO fill_price_for ENTRY (LONG=ask, SHORT=bid)",
        "entry_timestamp_source": "engine wall-clock utc now at fill write; command_monotonic_ns=event_monotonic_ns",
        "stop_method": "entry * (1 ∓ stop_loss_bps/10000) via stop_take_prices",
        "take_method": "entry * (1 ± take_profit_bps/10000) via stop_take_prices",
        "risk_reward_ratio": "take_profit_bps / stop_loss_bps",
        "long_geometry_validation": "stop < entry < take",
        "short_geometry_validation": "take < entry < stop",
        "tp_trigger": "LONG: bid|trade >= take; SHORT: ask|trade <= take",
        "sl_trigger": "LONG: bid|trade <= stop; SHORT: ask|trade >= stop",
        "context_end": "exit open position on CONTEXT_END for matching side",
        "context_flip": "exit then enter opposite (or to_side) on CONTEXT_FLIP",
        "opposite_direction_handling": "via CONTEXT_FLIP path only; OBSERVE tip does not exit",
        "exit_price_source": "causal BBO fill_price_for EXIT (LONG=bid, SHORT=ask); TP/SL may use local BBO",
        "exit_timestamp_source": "engine wall-clock utc now at fill/trade write",
        "long_entry": "ask",
        "short_entry": "bid",
        "long_exit": "bid",
        "short_exit": "ask",
        "trade_fallback_behavior": "aggTrade price may confirm TP/SL hit alongside BBO",
        "stale_bbo_behavior": "ENTRY_BLOCKED_NO_CAUSAL_BBO / EXIT_PENDING_NO_CAUSAL_BBO",
        "gross_net_pnl_semantics": "net = gross - fees - slippage; realized_pnl accumulates net_pnl_usd",
        "realized_net_pnl_definition": (
            "sum of closed_trade_economics.net_pnl_usd; fees and slippage already "
            "subtracted once; unrealized excluded; other-TF PnL included only under "
            "SHARED_MASTER_REALIZED_EQUITY"
        ),
        "equity_formula_shared": "equity = master_initial_equity_usd + sum(realized_net_pnl_usd)",
        "sizing_function": "btc_ml.trading.intrabar_paper.economics.resolve_risk_sizing",
        "restart_reconstruction": "rebuild open positions + traded episodes + realized_pnl from books",
        "atomic_write_behavior": "checkpoint/health write via .tmp then replace",
        "pending_command_handling": "pending_exits retried when causal BBO becomes available",
        "duplicate_command_protection": "consumer processed_keys + idempotency_key",
        "active_epoch_enforcement": "engine books rooted at books_root/{paper_epoch_id}",
        "book_tables": [
            "signals",
            "commands",
            "orders",
            "fills",
            "trades",
            "positions",
            "equity_snapshots",
            "metrics",
            "blocked",
        ],
    }


def _classify_source_fields() -> dict[str, str]:
    """Provenance of fields *before* they are folded into a full manifest."""
    return {
        "epoch_identity.paper_epoch_id": CLASS_EPOCH_SNAPSHOTTED,
        "epoch_identity.created_at": CLASS_EPOCH_SNAPSHOTTED,
        "epoch_identity.activated_at": CLASS_EPOCH_SNAPSHOTTED,
        "epoch_identity.initial_equity_usd": CLASS_EPOCH_SNAPSHOTTED,
        "epoch_identity.rule_contract_version": CLASS_EPOCH_SNAPSHOTTED,
        "epoch_identity.paper_only": CLASS_GLOBAL_RUNTIME,
        "epoch_identity.real_execution": CLASS_GLOBAL_RUNTIME,
        "execution_config.*": CLASS_GLOBAL_RUNTIME,
        "context_consumption.*": CLASS_HARDCODED,
        "entry_rules.*": CLASS_HARDCODED,
        "protection_geometry.stop_loss_bps": CLASS_GLOBAL_RUNTIME,
        "protection_geometry.take_profit_bps": CLASS_GLOBAL_RUNTIME,
        "exit_rules.*": CLASS_HARDCODED,
        "market_execution.*": CLASS_HARDCODED,
        "costs.*": CLASS_GLOBAL_RUNTIME,
        "capital.capital_model": CLASS_DERIVED,
        "state_and_persistence.books_root": CLASS_GLOBAL_RUNTIME,
        "state_and_persistence.context_journal_root": CLASS_GLOBAL_RUNTIME,
    }


def build_trading_contract_manifest(
    source_epoch_id: str,
    *,
    repo_root: Path | None = None,
    cfg: IntrabarPaperConfig | None = None,
    epoch: PaperEpoch | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    """Build the full normalized trading contract for an epoch."""
    root = repo_root or _repo_root()
    config = cfg or load_intrabar_paper_config(repo_root=root)
    if epoch is None:
        epoch_path = config.epochs_root / f"{source_epoch_id}.json"
        if not epoch_path.exists():
            raise FileNotFoundError(f"epoch record missing: {epoch_path}")
        epoch = PaperEpoch.from_dict(json.loads(epoch_path.read_text(encoding="utf-8")))
    if epoch.paper_epoch_id != source_epoch_id:
        raise ValueError(
            f"epoch id mismatch: record={epoch.paper_epoch_id} requested={source_epoch_id}"
        )

    hc = _hardcoded_rules()
    rr = float(config.take_profit_bps) / float(config.stop_loss_bps) if config.stop_loss_bps else None

    # Relative path strings for reproducibility (not absolute host paths).
    ctx_journal_rel = "data/cognition/intrabar_context_events"
    books_rel = "data/trading/intrabar_paper"
    epochs_rel = "data/trading/paper_epochs"
    raw = dict(config.raw)
    if "context_journal_root" in raw:
        ctx_journal_rel = str(raw["context_journal_root"])
    if "books_root" in raw:
        books_rel = str(raw["books_root"])
    if "epochs_root" in raw:
        epochs_rel = str(raw["epochs_root"])

    incomplete: list[str] = []
    # Fields that historically were NOT in the epoch JSON snapshot.
    if "trading_contract_manifest" not in (epoch.to_dict()):
        # Expected for legacy epochs — we fold live config + hardcoded rules in.
        pass

    # Align position_sizing risk_cap text with capital.risk_budget_source at build time.
    capital = {
        "capital_model": "SHARED_MASTER_REALIZED_EQUITY",
        "master_initial_equity_usd": float(epoch.initial_equity_usd),
        "timeframe_initial_equity_usd": None,
        "timeframe_current_equity_source": (
            "master_initial_equity_usd + sum(realized_net_pnl_usd across all timeframes)"
        ),
        "risk_budget_source": (
            "min(equity * max_risk_per_trade_pct/100, max_risk_per_trade_usd)"
        ),
        "risk_pct_per_trade": {
            "M15": float(config.max_risk_per_trade_pct),
            "M30": float(config.max_risk_per_trade_pct),
            "H1": float(config.max_risk_per_trade_pct),
            "H4": float(config.max_risk_per_trade_pct),
        },
        "max_risk_per_trade_usd": float(config.max_risk_per_trade_usd),
        "max_risk_per_trade_pct": float(config.max_risk_per_trade_pct),
    }

    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "parent_epoch_id": None,
        "epoch_identity": {
            "epoch_id": epoch.paper_epoch_id,
            "paper_epoch_id": epoch.paper_epoch_id,
            "epoch_created_at": epoch.created_at,
            "epoch_activated_at": epoch.activated_at,
            "model_version": epoch.rule_contract_version,
            "execution_version": "intrabar_paper_engine_v1",
            "config_schema_version": config.schema_version,
            "source_commit": source_commit,
            "paper_only": bool(config.paper_only),
            "real_execution": bool(config.real_execution_enabled),
            "rule_contract_version": epoch.rule_contract_version,
            "initial_equity_usd": float(epoch.initial_equity_usd),
        },
        "context_consumption": {
            "context_journal_path": ctx_journal_rel,
            "accepted_event_types": hc["accepted_event_types"],
            "entry_event_types": hc["entry_event_types"],
            "exit_event_types": hc["exit_event_types"],
            "accepted_timeframes": list(config.timeframes),
            "event_ordering": hc["event_ordering"],
            "causal_cutoff_rules": hc["causal_cutoff_rules"],
            "epoch_filtering": "books and consumer checkpoint scoped to paper_epoch_id",
            "context_dedup_key": hc["context_dedup_key"],
            "episode_dedup_key": hc["episode_dedup_key"],
            "already_traded_episode_behavior": hc["already_traded_episode_behavior"],
        },
        "entry_rules": {
            "entry_eligibility": hc["entry_eligibility"],
            "long_short_mapping": hc["long_short_mapping"],
            "one_position_per_timeframe": hc["one_position_per_timeframe"],
            "max_open_positions_per_timeframe": int(config.max_open_positions_per_timeframe),
            "same_direction_duplicate_handling": hc["same_direction_duplicate_handling"],
            "flip_behavior": hc["flip_behavior"],
            "entry_price_source": hc["entry_price_source"],
            "entry_timestamp_source": hc["entry_timestamp_source"],
        },
        "position_sizing": {
            "equity_basis": "SHARED_MASTER_REALIZED_EQUITY",
            "risk_percentage": float(config.max_risk_per_trade_pct),
            "max_risk_per_trade_pct": float(config.max_risk_per_trade_pct),
            "max_risk_per_trade_usd": float(config.max_risk_per_trade_usd),
            "risk_cap_semantics": (
                "min(equity * max_risk_per_trade_pct/100, max_risk_per_trade_usd)"
            ),
            "stop_distance": "abs(entry - stop) by side",
            "entry_fee": "entry_notional * entry_fee_bps/10000",
            "exit_fee": "stop_notional * exit_fee_bps/10000 (sizing path)",
            "slippage": (
                "entry * entry_slippage_bps + stop * stop_exit_slippage_bps in per-btc cost"
            ),
            "rounding": "IEEE float division qty = risk_amount / per_btc_cost; no floor",
            "quantity_precision": "full float64; no exchange lot-size rounding",
            "minimum_quantity": None,
            "maximum_quantity_or_notional": None,
            "cost_aware_stop_sizing": bool(config.cost_aware_stop_sizing),
            "fixed_notional": bool(config.fixed_notional),
            "sizing_function": hc["sizing_function"],
        },
        "protection_geometry": {
            "stop_method": hc["stop_method"],
            "take_method": hc["take_method"],
            "stop_loss_bps": float(config.stop_loss_bps),
            "take_profit_bps": float(config.take_profit_bps),
            "risk_reward_ratio": rr,
            "long_geometry_validation": hc["long_geometry_validation"],
            "short_geometry_validation": hc["short_geometry_validation"],
        },
        "exit_rules": {
            "tp_trigger": hc["tp_trigger"],
            "sl_trigger": hc["sl_trigger"],
            "context_end": hc["context_end"],
            "context_flip": hc["context_flip"],
            "opposite_direction_handling": hc["opposite_direction_handling"],
            "exit_price_source": hc["exit_price_source"],
            "exit_timestamp_source": hc["exit_timestamp_source"],
        },
        "market_execution": {
            "long_entry": hc["long_entry"],
            "short_entry": hc["short_entry"],
            "long_exit": hc["long_exit"],
            "short_exit": hc["short_exit"],
            "trade_fallback_behavior": hc["trade_fallback_behavior"],
            "stale_bbo_behavior": hc["stale_bbo_behavior"],
            "max_bbo_age_ms": float(config.max_bbo_age_ms),
        },
        "costs": {
            "entry_fee_bps": float(config.entry_fee_bps),
            "exit_fee_bps": float(config.exit_fee_bps),
            "entry_slippage_bps": float(config.entry_slippage_bps),
            "exit_slippage_bps": float(config.exit_slippage_bps),
            "stop_exit_slippage_bps": float(config.stop_exit_slippage_bps),
            "slippage_model": "bps of notional; stop exits use stop_exit_slippage_bps",
            "gross_net_pnl_semantics": hc["gross_net_pnl_semantics"],
            "realized_net_pnl_definition": hc["realized_net_pnl_definition"],
            "economics_source": config.economics_source,
        },
        "state_and_persistence": {
            "signals_path": f"{books_rel}/{{paper_epoch_id}}/books/signals.jsonl",
            "commands_path": f"{books_rel}/{{paper_epoch_id}}/books/commands.jsonl",
            "orders_path": f"{books_rel}/{{paper_epoch_id}}/books/orders.jsonl",
            "fills_path": f"{books_rel}/{{paper_epoch_id}}/books/fills.jsonl",
            "positions_path": f"{books_rel}/{{paper_epoch_id}}/books/positions.jsonl",
            "trades_path": f"{books_rel}/{{paper_epoch_id}}/books/trades.jsonl",
            "checkpoint_path": f"{books_rel}/{{paper_epoch_id}}/context_consumer_checkpoint.json",
            "epochs_root": epochs_rel,
            "books_root": books_rel,
            "book_tables": hc["book_tables"],
            "restart_reconstruction": hc["restart_reconstruction"],
            "atomic_write_behavior": hc["atomic_write_behavior"],
        },
        "safety": {
            "paper_only": bool(config.paper_only),
            "real_execution_enabled": bool(config.real_execution_enabled),
            "real_execution_guard": "load_intrabar_paper_config rejects real_execution_enabled=true",
            "pending_command_handling": hc["pending_command_handling"],
            "duplicate_command_protection": hc["duplicate_command_protection"],
            "active_epoch_enforcement": hc["active_epoch_enforcement"],
        },
        "capital": capital,
        "execution_config_snapshot": {
            "schema_version": config.schema_version,
            "rule_contract_version": config.rule_contract_version,
            "paper_only": bool(config.paper_only),
            "real_execution_enabled": bool(config.real_execution_enabled),
            "initial_equity_usd": float(config.initial_equity_usd),
            "max_risk_per_trade_pct": float(config.max_risk_per_trade_pct),
            "max_risk_per_trade_usd": float(config.max_risk_per_trade_usd),
            "cost_aware_stop_sizing": bool(config.cost_aware_stop_sizing),
            "fixed_notional": bool(config.fixed_notional),
            "stop_loss_bps": float(config.stop_loss_bps),
            "take_profit_bps": float(config.take_profit_bps),
            "entry_fee_bps": float(config.entry_fee_bps),
            "exit_fee_bps": float(config.exit_fee_bps),
            "entry_slippage_bps": float(config.entry_slippage_bps),
            "exit_slippage_bps": float(config.exit_slippage_bps),
            "stop_exit_slippage_bps": float(config.stop_exit_slippage_bps),
            "max_bbo_age_ms": float(config.max_bbo_age_ms),
            "max_open_positions_per_timeframe": int(config.max_open_positions_per_timeframe),
            "timeframes": list(config.timeframes),
            "context_journal_root": ctx_journal_rel,
            "books_root": books_rel,
            "epochs_root": epochs_rel,
            "economics_source": config.economics_source,
        },
        "field_provenance": _classify_source_fields(),
        "legacy_epoch_gaps": {
            "note": (
                "Pre-TRD-EPOCH1 epoch JSON only persisted identity + initial_equity; "
                "execution config and hardcoded engine rules were global/runtime."
            ),
            "not_in_epoch_json_before_clone": [
                "execution_config_snapshot",
                "context_consumption",
                "entry_rules",
                "protection_geometry",
                "exit_rules",
                "market_execution",
                "costs",
                "capital",
                "trading_contract_fingerprint",
            ],
        },
    }

    # Mark optional absences explicitly (do not silently default).
    for key, val in (
        ("position_sizing.minimum_quantity", manifest["position_sizing"]["minimum_quantity"]),
        (
            "position_sizing.maximum_quantity_or_notional",
            manifest["position_sizing"]["maximum_quantity_or_notional"],
        ),
    ):
        if val is None:
            # Not used by engine — recorded as explicit null, not UNKNOWN.
            pass

    critical_unknown = [
        p for p in _CRITICAL_PATHS if _get_path(manifest, p) in (None, FIELD_NOT_CANONICALLY_SNAPSHOTTED)
    ]
    if critical_unknown:
        incomplete.extend(critical_unknown)
    manifest["completeness"] = {
        "critical_unknown": incomplete,
        "status": "COMPLETE" if not incomplete else "INCOMPLETE",
    }
    fp = trading_contract_fingerprint(manifest)
    manifest["trading_contract_fingerprint"] = fp
    return manifest


def assert_manifest_complete(manifest: dict[str, Any]) -> None:
    status = (manifest.get("completeness") or {}).get("status")
    unknown = (manifest.get("completeness") or {}).get("critical_unknown") or []
    if status != "COMPLETE" or unknown:
        raise RuntimeError(
            f"{EPOCH_CLONE_BLOCKED}: critical fields incomplete: {unknown}"
        )


def flatten_manifest_diff(a: dict[str, Any], b: dict[str, Any], *, prefix: str = "") -> dict[str, Any]:
    """Return dotted-path → {from, to} for trading-significant differences."""
    skip = _FINGERPRINT_EXCLUDE | {"completeness", "legacy_epoch_gaps", "clone_meta"}
    out: dict[str, Any] = {}
    keys = sorted(set(a.keys()) | set(b.keys()))
    for key in keys:
        if not prefix and key in skip:
            continue
        path = f"{prefix}.{key}" if prefix else key
        va = a.get(key)
        vb = b.get(key)
        if isinstance(va, dict) and isinstance(vb, dict):
            out.update(flatten_manifest_diff(va, vb, prefix=path))
        elif va != vb:
            out[path] = {"from": va, "to": vb}
    return out


def validate_risk_only_diff(diff: dict[str, Any]) -> None:
    """Raise RISK_DELTA_CONTRACT_VIOLATION if non-allowlisted fields differ."""
    bad = sorted(k for k in diff if k not in RISK_DELTA_ALLOWLIST)
    if bad:
        raise RuntimeError(f"{RISK_DELTA_VIOLATION}: non-allowlisted diffs: {bad}")


def validate_sleeve2_contract_diff(diff: dict[str, Any]) -> None:
    """Raise if any non-capital sleeve2 field changed."""
    bad = sorted(k for k in diff if k not in SLEEVE2_CONTRACT_ALLOWLIST)
    if bad:
        raise RuntimeError(f"{SLEEVE2_NON_CAPITAL_DIFF}: {bad}")


@dataclass
class CloneResult:
    source_epoch_id: str
    new_epoch_id: str
    parent_epoch_id: str
    manifest: dict[str, Any]
    fingerprint: str
    source_fingerprint: str
    diff: dict[str, Any]
    output_path: Path


def clone_trading_epoch_contract(
    source_epoch_id: str,
    new_epoch_id: str,
    allowed_overrides: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
    output_root: Path | None = None,
    register_epoch: bool = False,
    source_manifest: dict[str, Any] | None = None,
) -> CloneResult:
    """Deep-clone a full trading contract; apply only allowlisted overrides.

    register_epoch must remain False for TRD-EPOCH1 (no production activation).
    """
    if register_epoch:
        raise RuntimeError("register_epoch=True is forbidden in TRD-EPOCH1 clone path")

    root = repo_root or _repo_root()
    overrides = dict(allowed_overrides or {})
    source = source_manifest or build_trading_contract_manifest(source_epoch_id, repo_root=root)
    assert_manifest_complete(source)
    source_fp = str(source.get("trading_contract_fingerprint") or trading_contract_fingerprint(source))

    cloned = copy.deepcopy(source)
    # Drop clone-meta / completeness before applying identity + overrides.
    cloned.pop("clone_meta", None)

    bare_capital = {
        "capital_model",
        "timeframe_initial_equity_usd",
        "timeframe_current_equity_source",
        "risk_budget_source",
        "master_initial_equity_usd",
        "risk_pct_per_trade",
        "max_risk_per_trade_usd",
    }
    for path, value in overrides.items():
        dotted = path if "." in path else f"capital.{path}"
        allowed = (
            dotted in RISK_DELTA_ALLOWLIST
            or path in RISK_DELTA_ALLOWLIST
            or path in bare_capital
            or dotted in SLEEVE2_CONTRACT_ALLOWLIST
        )
        if not allowed:
            raise RuntimeError(f"{RISK_DELTA_VIOLATION}: override not allowlisted: {path}")
        _set_path(cloned, dotted, value)

    # Sync derived position_sizing fields only when capital overrides are applied.
    cap = cloned.get("capital") or {}
    override_keys = set(overrides.keys())

    def _overrode(*names: str) -> bool:
        return any(n in override_keys or f"capital.{n}" in override_keys for n in names)

    if _overrode("capital_model") and "capital_model" in cap:
        if "position_sizing.equity_basis" not in override_keys:
            cloned["position_sizing"]["equity_basis"] = cap["capital_model"]
    if (
        _overrode("risk_budget_source")
        and "risk_budget_source" in cap
        and "position_sizing.risk_cap_semantics" not in override_keys
    ):
        # EPOCH1 research clones may mirror formula into risk_cap_semantics.
        # SLEEVE2 sets an explicit PER_TIMEFRAME_CURRENT_EQUITY_PERCENT instead.
        if str(cap.get("capital_model")) != "PER_TIMEFRAME_REALIZED_EQUITY":
            cloned["position_sizing"]["risk_cap_semantics"] = cap["risk_budget_source"]
        else:
            cloned["position_sizing"]["risk_cap_semantics"] = "PER_TIMEFRAME_CURRENT_EQUITY_PERCENT"
    if _overrode("risk_pct_per_trade") and isinstance(cap.get("risk_pct_per_trade"), dict):
        pcts = [float(v) for v in cap["risk_pct_per_trade"].values()]
        if pcts and len(set(pcts)) == 1:
            cloned["position_sizing"]["risk_percentage"] = pcts[0]
            cloned["position_sizing"]["max_risk_per_trade_pct"] = pcts[0]
    if _overrode("max_risk_per_trade_usd"):
        cloned["position_sizing"]["max_risk_per_trade_usd"] = cap.get("max_risk_per_trade_usd")
    if _overrode("master_initial_equity_usd") and cap.get("master_initial_equity_usd") is not None:
        cloned["epoch_identity"]["initial_equity_usd"] = float(cap["master_initial_equity_usd"])
    if _overrode("timeframe_initial_equity_usd") and isinstance(
        cap.get("timeframe_initial_equity_usd"), dict
    ):
        vals = [float(v) for v in cap["timeframe_initial_equity_usd"].values()]
        if vals and cap.get("master_initial_equity_usd") is None and len(set(vals)) == 1:
            cloned["epoch_identity"]["initial_equity_usd"] = vals[0]

    cloned["parent_epoch_id"] = source_epoch_id
    cloned["epoch_identity"] = dict(cloned.get("epoch_identity") or {})
    cloned["epoch_identity"]["epoch_id"] = new_epoch_id
    cloned["epoch_identity"]["paper_epoch_id"] = new_epoch_id
    cloned["epoch_identity"]["epoch_created_at"] = _utc_now()
    cloned["epoch_identity"]["epoch_activated_at"] = None

    # Recompute completeness + fingerprint after overrides.
    critical_unknown = [
        p for p in _CRITICAL_PATHS if _get_path(cloned, p) in (None, FIELD_NOT_CANONICALLY_SNAPSHOTTED)
    ]
    cloned["completeness"] = {
        "critical_unknown": critical_unknown,
        "status": "COMPLETE" if not critical_unknown else "INCOMPLETE",
    }
    assert_manifest_complete(cloned)
    fp = trading_contract_fingerprint(cloned)
    cloned["trading_contract_fingerprint"] = fp
    cloned["clone_meta"] = {
        "cloned_at": _utc_now(),
        "source_epoch_id": source_epoch_id,
        "source_fingerprint": source_fp,
        "register_epoch": False,
    }

    diff = flatten_manifest_diff(source, cloned)
    # Identity / parent changes always appear; strip them from "trading" zero-diff check.
    trading_diff = {
        k: v
        for k, v in diff.items()
        if k
        not in {
            "parent_epoch_id",
            "epoch_identity.epoch_id",
            "epoch_identity.paper_epoch_id",
            "epoch_identity.epoch_created_at",
            "epoch_identity.epoch_activated_at",
            "epoch_identity.initial_equity_usd",
        }
        and not k.startswith("clone_meta")
    }

    out_root = Path(output_root) if output_root is not None else (root / "tmp" / "trading_contract_clones")
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / f"{new_epoch_id}.trading_contract.json"
    payload = {
        "trading_contract_manifest": cloned,
        "trading_contract_fingerprint": fp,
        "parent_epoch_id": source_epoch_id,
        "paper_epoch_id": new_epoch_id,
        "manifest_diff": trading_diff,
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return CloneResult(
        source_epoch_id=source_epoch_id,
        new_epoch_id=new_epoch_id,
        parent_epoch_id=source_epoch_id,
        manifest=cloned,
        fingerprint=fp,
        source_fingerprint=source_fp,
        diff=trading_diff,
        output_path=out_path,
    )


def risk_delta_overrides_per_tf_equity(
    *,
    initial_equity_usd: float = 100_000.0,
    risk_pct: float = 1.0,
    timeframes: Iterable[str] = ("M15", "M30", "H1", "H4"),
) -> dict[str, Any]:
    """EPOCH1 research clone overrides (may null the USD risk cap)."""
    tfs = list(timeframes)
    return {
        "capital_model": "PER_TIMEFRAME_REALIZED_EQUITY",
        "timeframe_initial_equity_usd": {tf: float(initial_equity_usd) for tf in tfs},
        "timeframe_current_equity_source": (
            "timeframe_initial_equity_usd[tf] + cumulative_realized_net_pnl_usd[tf]"
        ),
        "risk_budget_source": "current_equity_usd[tf] * risk_pct_per_trade[tf] / 100",
        "master_initial_equity_usd": None,
        "risk_pct_per_trade": {tf: float(risk_pct) for tf in tfs},
        "max_risk_per_trade_usd": None,
    }


def sleeve2_capital_overrides(
    *,
    sleeve_initial_equity_usd: float = 100_000.0,
    risk_pct: float = 1.0,
    timeframes: Iterable[str] = ("M15", "M30", "H1", "H4"),
) -> dict[str, Any]:
    """Production sleeve activation overrides (strict SLEEVE2 allowlist)."""
    tfs = list(timeframes)
    master = float(sleeve_initial_equity_usd) * len(tfs)
    return {
        "capital_model": "PER_TIMEFRAME_REALIZED_EQUITY",
        "master_initial_equity_usd": master,
        "timeframe_initial_equity_usd": {tf: float(sleeve_initial_equity_usd) for tf in tfs},
        "timeframe_current_equity_source": (
            "timeframe_initial_equity_usd[tf] + cumulative_realized_net_pnl_usd[tf]"
        ),
        "risk_budget_source": "current_equity_usd[tf] * risk_pct_per_trade[tf] / 100",
        "risk_pct_per_trade": {tf: float(risk_pct) for tf in tfs},
        "position_sizing.equity_basis": "PER_TIMEFRAME_REALIZED_EQUITY",
        "position_sizing.risk_cap_semantics": "PER_TIMEFRAME_CURRENT_EQUITY_PERCENT",
    }


def assert_source_fingerprint(manifest: dict[str, Any]) -> str:
    fp = str(manifest.get("trading_contract_fingerprint") or trading_contract_fingerprint(manifest))
    if fp != EXPECTED_SOURCE_FINGERPRINT:
        raise RuntimeError(
            f"{SLEEVE2_SOURCE_MISMATCH}: got={fp} expected={EXPECTED_SOURCE_FINGERPRINT}"
        )
    return fp


def compute_risk_budget_usd(
    manifest: dict[str, Any],
    *,
    timeframe: str,
    current_equity_usd: float | None = None,
) -> float:
    """Compute risk budget for a TF under the contract's capital model."""
    cap = manifest.get("capital") or {}
    model = str(cap.get("capital_model") or "")
    tf = str(timeframe).upper()
    if model == "PER_TIMEFRAME_REALIZED_EQUITY":
        initials = cap.get("timeframe_initial_equity_usd") or {}
        eq = float(
            current_equity_usd
            if current_equity_usd is not None
            else initials.get(tf) or initials.get(timeframe) or 0.0
        )
        pcts = cap.get("risk_pct_per_trade") or {}
        pct = float(pcts.get(tf) or pcts.get(timeframe) or 0.0)
        return eq * (pct / 100.0)
    # Shared master model
    eq = float(
        current_equity_usd
        if current_equity_usd is not None
        else cap.get("master_initial_equity_usd")
        or manifest.get("epoch_identity", {}).get("initial_equity_usd")
        or 0.0
    )
    pct = float(cap.get("max_risk_per_trade_pct") or 0.0)
    cap_usd = cap.get("max_risk_per_trade_usd")
    risk_pct = eq * (pct / 100.0)
    if cap_usd is None:
        return risk_pct
    return min(risk_pct, float(cap_usd))


def current_equity_usd_for_timeframe(
    *,
    initial_equity_usd: float,
    cumulative_realized_net_pnl_usd: float,
) -> float:
    """Proven realized-equity semantics (fees already netted once in net_pnl)."""
    return float(initial_equity_usd) + float(cumulative_realized_net_pnl_usd)


def config_from_manifest(
    manifest: dict[str, Any],
    *,
    repo_root: Path,
) -> IntrabarPaperConfig:
    """Materialize IntrabarPaperConfig from a full contract manifest."""
    snap = dict(manifest.get("execution_config_snapshot") or {})
    # Write a temporary config file so load path stays canonical.
    cfg_dir = repo_root / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    # Prefer in-memory construction without mutating production config.
    path = repo_root / "config" / "_tmp_trading_contract_execution.json"
    # Fill required keys from snapshot.
    required_defaults = {
        "schema_version": snap.get("schema_version", "intrabar_paper_execution_v1"),
        "rule_contract_version": snap.get("rule_contract_version", "INTRABAR_RULES_V1"),
        "paper_only": bool(snap.get("paper_only", True)),
        "real_execution_enabled": bool(snap.get("real_execution_enabled", False)),
        "initial_equity_usd": float(snap["initial_equity_usd"]),
        "max_risk_per_trade_pct": float(snap.get("max_risk_per_trade_pct") or 1.0),
        "max_risk_per_trade_usd": float(
            snap["max_risk_per_trade_usd"]
            if snap.get("max_risk_per_trade_usd") is not None
            else 1e18
        ),
        "cost_aware_stop_sizing": bool(snap["cost_aware_stop_sizing"]),
        "fixed_notional": bool(snap["fixed_notional"]),
        "stop_loss_bps": float(snap["stop_loss_bps"]),
        "take_profit_bps": float(snap["take_profit_bps"]),
        "entry_fee_bps": float(snap["entry_fee_bps"]),
        "exit_fee_bps": float(snap["exit_fee_bps"]),
        "entry_slippage_bps": float(snap["entry_slippage_bps"]),
        "exit_slippage_bps": float(snap["exit_slippage_bps"]),
        "stop_exit_slippage_bps": float(snap["stop_exit_slippage_bps"]),
        "max_bbo_age_ms": float(snap["max_bbo_age_ms"]),
        "max_open_positions_per_timeframe": int(snap["max_open_positions_per_timeframe"]),
        "timeframes": list(snap["timeframes"]),
        "context_journal_root": str(snap["context_journal_root"]),
        "books_root": str(snap["books_root"]),
        "epochs_root": str(snap["epochs_root"]),
        "economics_source": str(snap.get("economics_source") or "canonical_paper_trade_economics_v1"),
    }
    path.write_text(json.dumps(required_defaults, indent=2) + "\n", encoding="utf-8")
    return load_intrabar_paper_config(path, repo_root=repo_root)


def size_with_contract(
    *,
    cfg: IntrabarPaperConfig,
    manifest: dict[str, Any],
    side: str,
    entry_price: float,
    timeframe: str,
    current_equity_usd: float | None = None,
):
    """Canonical sizing path; derived contracts pass risk_budget_usd only."""
    budget = compute_risk_budget_usd(
        manifest, timeframe=timeframe, current_equity_usd=current_equity_usd
    )
    return resolve_risk_sizing(
        cfg=cfg,
        side=side,
        entry_price=entry_price,
        equity_usd=current_equity_usd,
        risk_budget_usd=budget,
    )


# --- Isolated replay helpers -------------------------------------------------

_ID_KEYS = frozenset(
    {
        "signal_id",
        "command_id",
        "order_id",
        "fill_id",
        "position_id",
        "trade_id",
        "paper_epoch_id",
    }
)


def normalize_book_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip generated IDs / wall-clock ts for structural comparison."""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        norm = {}
        for k, v in sorted(row.items()):
            if k in _ID_KEYS or k in {"ts", "opened_at", "closed_at", "exit_ts", "entry_ts"}:
                continue
            if k.endswith("_ts") or k.endswith("_at"):
                continue
            if k.endswith("_id") and k not in {
                "context_event_id",
                "lifecycle_episode_id",
                "entry_context_event_id",
                "book_update_id",
                "trigger_event_id",
            }:
                continue
            norm[k] = v
        norm["_ordinal"] = i
        out.append(norm)
    return out


def compare_replay_books(
    left: dict[str, list[dict[str, Any]]],
    right: dict[str, list[dict[str, Any]]],
    *,
    allow_quantity_fields: bool = False,
) -> dict[str, Any]:
    """Compare normalized book tables. Returns status + divergences."""
    divergences: dict[str, Any] = {}
    for table in sorted(set(left) | set(right)):
        a = normalize_book_rows(left.get(table) or [])
        b = normalize_book_rows(right.get(table) or [])
        if len(a) != len(b):
            divergences[table] = {"len_left": len(a), "len_right": len(b)}
            continue
        for i, (ra, rb) in enumerate(zip(a, b)):
            keys = sorted(set(ra) | set(rb))
            row_diff = {}
            for k in keys:
                if k == "_ordinal":
                    continue
                va, vb = ra.get(k), rb.get(k)
                if va == vb:
                    continue
                if allow_quantity_fields and k in RISK_DELTA_REPLAY_ALLOW_FIELDS:
                    continue
                # Float tolerance
                if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                    if abs(float(va) - float(vb)) < 1e-9:
                        continue
                row_diff[k] = {"from": va, "to": vb}
            if row_diff:
                divergences[f"{table}[{i}]"] = row_diff
    if divergences:
        return {"status": ZERO_DIFF_DIVERGENCE, "divergences": divergences}
    return {"status": ZERO_DIFF_MATCH, "divergences": {}}


@dataclass
class ActivationGateResult:
    allowed: bool
    status: str
    reasons: list[str]
    open_positions: int
    pending_commands: int
    pending_orders: int
    pending_fills: int
    live1b_running: bool | None
    source_fingerprint_ok: bool | None
    risk_only_diff_ok: bool | None


def inspect_epoch_open_state(
    *,
    paper_epoch_id: str,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    root = repo_root or _repo_root()
    books = root / "data" / "trading" / "intrabar_paper" / paper_epoch_id / "books"
    from .books import EpochBooks

    eb = EpochBooks(books, paper_epoch_id=paper_epoch_id)
    opens = eb.open_positions()
    # Pending artifacts: engine does not persist pending queues; treat non-FILLED
    # orders as pending if present.
    pending_orders = [
        o for o in eb.read_all("orders") if str(o.get("status") or "").upper() not in {"FILLED", "CANCELLED", "DONE"}
    ]
    return {
        "open_positions": opens,
        "open_position_count": len(opens),
        "pending_orders": pending_orders,
        "pending_order_count": len(pending_orders),
        "signals_count": eb.count("signals"),
        "commands_count": eb.count("commands"),
        "fills_count": eb.count("fills"),
        "trades_count": eb.count("trades"),
    }


def check_new_epoch_activation_gate(
    *,
    source_epoch_id: str,
    source_fingerprint: str | None = None,
    expected_source_fingerprint: str | None = None,
    risk_only_diff: dict[str, Any] | None = None,
    live1b_running: bool | None = None,
    pending_commands: int = 0,
    pending_fills: int = 0,
    repo_root: Path | None = None,
) -> ActivationGateResult:
    """Future activation gate — never activates; only evaluates readiness."""
    root = repo_root or _repo_root()
    reasons: list[str] = []
    state = inspect_epoch_open_state(paper_epoch_id=source_epoch_id, repo_root=root)
    open_n = int(state["open_position_count"])
    pending_orders = int(state["pending_order_count"])
    if open_n > 0:
        reasons.append(f"active open positions = {open_n}")
    if pending_commands > 0:
        reasons.append(f"pending commands = {pending_commands}")
    if pending_orders > 0:
        reasons.append(f"pending orders = {pending_orders}")
    if pending_fills > 0:
        reasons.append(f"pending fills = {pending_fills}")
    if live1b_running is True:
        reasons.append("LIVE1B still running")
    elif live1b_running is None:
        reasons.append("LIVE1B stopped status unverified")

    fp_ok: bool | None = None
    if expected_source_fingerprint is not None:
        fp_ok = source_fingerprint == expected_source_fingerprint
        if not fp_ok:
            reasons.append("source contract fingerprint mismatch")

    risk_ok: bool | None = None
    if risk_only_diff is not None:
        try:
            validate_risk_only_diff(risk_only_diff)
            risk_ok = True
        except RuntimeError as exc:
            risk_ok = False
            reasons.append(str(exc))

    # Always require persisted new manifest — caller must pass risk_only_diff
    # verification separately; gate blocks if any reason present.
    allowed = not reasons
    return ActivationGateResult(
        allowed=allowed,
        status="OK" if allowed else NEW_EPOCH_ACTIVATION_BLOCKED,
        reasons=reasons,
        open_positions=open_n,
        pending_commands=pending_commands,
        pending_orders=pending_orders,
        pending_fills=pending_fills,
        live1b_running=live1b_running,
        source_fingerprint_ok=fp_ok,
        risk_only_diff_ok=risk_ok,
    )


def prepare_new_epoch_activation_plan(
    *,
    source_epoch_id: str,
    new_epoch_id: str,
    clone: CloneResult,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Machine-readable future activation plan (do not execute)."""
    gate = check_new_epoch_activation_gate(
        source_epoch_id=source_epoch_id,
        source_fingerprint=clone.source_fingerprint,
        expected_source_fingerprint=clone.source_fingerprint,
        risk_only_diff=clone.diff,
        live1b_running=None,
        repo_root=repo_root,
    )
    return {
        "command": "ACTIVATE_NEW_PAPER_EPOCH",
        "status": gate.status,
        "allowed": gate.allowed,
        "source_epoch_id": source_epoch_id,
        "new_epoch_id": new_epoch_id,
        "parent_epoch_id": clone.parent_epoch_id,
        "source_fingerprint": clone.source_fingerprint,
        "new_fingerprint": clone.fingerprint,
        "manifest_path": str(clone.output_path),
        "requirements": [
            "active open positions = 0",
            "pending commands = 0",
            "pending orders = 0",
            "pending fills = 0",
            "LIVE1B stopped through controller",
            "source contract fingerprint verified",
            "risk-only diff verified",
            "new full epoch manifest persisted",
        ],
        "blocking_reasons": gate.reasons,
        "next_steps_if_allowed": [
            "create new epoch record with full trading_contract_manifest",
            "start LIVE1B against new epoch",
        ],
    }


def active_epoch_unchanged(*, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    cfg = load_intrabar_paper_config(repo_root=root)
    active = load_active_epoch(cfg.epochs_root)
    return {
        "active_paper_epoch_id": active.paper_epoch_id if active else None,
        "expected": CANONICAL_SOURCE_EPOCH,
        "unchanged": bool(active and active.paper_epoch_id == CANONICAL_SOURCE_EPOCH),
    }
