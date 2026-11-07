#!/usr/bin/env python3
"""Pure paper policy decision layer (no I/O, no exchange, no ledger writes)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

INVALID_LIFECYCLE = frozenset({"INVALIDATED", "NO_ACTIVE_CONTEXT"})
FLAT_NO_TRADE_CONTEXTS = frozenset({"OBSERVE", "STAND_ASIDE", "INVALIDATED", "NO_ACTIVE_CONTEXT", ""})
DIRECTIONAL_CONTEXTS = frozenset({"LONG_CONTEXT", "SHORT_CONTEXT"})
# Non-directional predecessors plus opposite directional context (flip = new start).
CONTEXT_START_PREVIOUS_ALLOWED = frozenset(
    {
        "OBSERVE",
        "NO_ACTIVE_CONTEXT",
        "NONE",
        "INVALIDATED",
        "STAND_ASIDE",
        "",
        "LONG_CONTEXT",
        "SHORT_CONTEXT",
    }
)
LONG_INVALIDATING = frozenset(
    {"SHORT_CONTEXT", "OBSERVE", "STAND_ASIDE", "INVALIDATED", "NO_ACTIVE_CONTEXT"}
)
SHORT_INVALIDATING = frozenset(
    {"LONG_CONTEXT", "OBSERVE", "STAND_ASIDE", "INVALIDATED", "NO_ACTIVE_CONTEXT"}
)

ENTRY_BLOCKED_NO_CONTEXT_START_EVENT = "ENTRY_BLOCKED_NO_CONTEXT_START_EVENT"
ENTRY_BLOCKED_CONTEXT_EPISODE_ALREADY_TRADED = "ENTRY_BLOCKED_CONTEXT_EPISODE_ALREADY_TRADED"
ENTRY_BLOCKED_CONTEXT_STALE = "ENTRY_BLOCKED_CONTEXT_STALE"
ENTRY_BLOCKED_POSITION_ALREADY_OPEN = "ENTRY_BLOCKED_POSITION_ALREADY_OPEN"
ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT = "ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT"
ENTRY_BLOCKED_SHORT_NOT_SUPPORTED = "ENTRY_BLOCKED_SHORT_NOT_SUPPORTED"
ENTRY_BLOCKED_MISSING_CONTEXT_EPISODE_KEY = "ENTRY_BLOCKED_MISSING_CONTEXT_EPISODE_KEY"
ENTRY_BLOCKED_NO_ATOMIC_EXECUTION_PRICE = "ENTRY_BLOCKED_NO_ATOMIC_EXECUTION_PRICE"
MISSING_CONTEXT_EPISODE_KEY_PREFIX = "missing_context_episode_key"
MARKET_DATA_SNAPSHOT_UNAVAILABLE = "MARKET_DATA_SNAPSHOT_UNAVAILABLE"
EXIT_PENDING_MARKET_DATA_UNAVAILABLE = "EXIT_PENDING_MARKET_DATA_UNAVAILABLE"
PAPER_CONTEXT_POLICY_MODE_TRADE_ALL = "TRADE_ALL_DIRECTIONAL_CONTEXT_STARTS"
PAPER_CONTEXT_HOLD_MODE_UNTIL_END = "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END"
HOLD_UNTIL_DIRECTIONAL_CONTEXT_END = "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END"
ENTRY_LAYER_CANDIDATE = "CANDIDATE"
ENTRY_LAYER_ACTIVE = "ACTIVE"
ENTRY_LAYER_RAW = "RAW"
ENTRY_LAYER_CONTEXT_START_EVENT = "CONTEXT_START_EVENT"
CONTEXT_END_EVENT_LONG = "CONTEXT_END_EVENT_LONG"
CONTEXT_END_EVENT_SHORT = "CONTEXT_END_EVENT_SHORT"
CONTEXT_FLIP_LONG_TO_SHORT = "CONTEXT_FLIP_LONG_TO_SHORT"
CONTEXT_FLIP_SHORT_TO_LONG = "CONTEXT_FLIP_SHORT_TO_LONG"
CONTEXT_FLIP_START_EVENT = "CONTEXT_FLIP_START_EVENT"

EXIT_PRIORITY = (
    "RISK_EXIT",
    "HARD_STOP_LOSS",
    "TAKE_PROFIT",
    "TRAILING_STOP",
    "CONTEXT_INVALIDATION",
    "EDGE_DETERIORATION",
    "MAX_HOLDING_BARS",
    "HOLD",
)


@dataclass(frozen=True)
class PolicyEngineState:
    timestamp: str
    instrument: str
    active_market_context: str
    lifecycle_state: str
    is_stale: bool
    confidence_available: bool
    confidence: Optional[float]
    expected_edge_available: bool
    expected_edge_bps: Optional[float]
    expected_edge_basis: str
    edge_signal_pass: bool
    current_price: float
    current_open: float
    current_high: float
    current_low: float
    current_close: float
    total_roundtrip_model_cost_bps: float
    signal_eligibility_status: str = "UNKNOWN"
    signal_block_reasons: tuple[str, ...] = ()
    previous_active_market_context: Optional[str] = None
    context_episode_key: Optional[str] = None
    traded_context_episode_keys: tuple[str, ...] = ()
    lifecycle_episode_id: Optional[str] = None
    active_context_started_at: Optional[str] = None
    context_started_at: Optional[str] = None
    source_context_ts: Optional[str] = None
    # Fresh market snapshot availability (not feed-process status).
    market_snapshot_available: bool = True
    # Research start-layer fields (from lifecycle; optional).
    candidate_started_at: Optional[str] = None
    candidate_context: Optional[str] = None
    context_quality_label: Optional[str] = None
    context_confidence_label: Optional[str] = None


@dataclass(frozen=True)
class PositionState:
    position_state: str  # FLAT / LONG / SHORT
    entry_price: Optional[float] = None
    entry_ts: Optional[str] = None
    quantity: float = 0.0
    bars_in_position: int = 0
    highest_high_since_entry: Optional[float] = None
    lowest_low_since_entry: Optional[float] = None
    mfe_bps: Optional[float] = None
    mae_bps: Optional[float] = None
    unrealized_pnl_bps: Optional[float] = None
    trailing_active: bool = False
    current_trailing_stop_price: Optional[float] = None


@dataclass(frozen=True)
class RiskState:
    daily_pnl_bps: float = 0.0
    daily_loss_limit_bps: float = 200.0
    max_trades_per_day: int = 20
    trades_today: int = 0
    max_position_notional_pct: float = 1.0
    current_position_notional_pct: float = 0.0
    max_drawdown_bps: float = 500.0
    current_drawdown_bps: float = 0.0


@dataclass(frozen=True)
class PolicyParameters:
    stop_loss_bps: float
    take_profit_bps: float
    trailing_activation_bps: Optional[float]
    trailing_drawdown_bps: Optional[float]
    max_holding_bars: int
    context_exit_mode: str
    confidence_threshold: float
    expected_edge_min_bps: float
    total_roundtrip_model_cost_bps: float
    conservative_intrabar_assumption: str = "STOP_FIRST"
    fixture_only: bool = False
    selected_policy_id: str = ""
    trailing_enabled: bool = False
    # Research paper alignment modes (do not mutate cognition).
    # Defaults preserve legacy engine behavior; controller enables research modes explicitly.
    paper_context_policy_mode: str = ""
    paper_context_hold_mode: str = ""
    trade_all_qualities: bool = False
    ignore_edge_confidence_for_entry: bool = False
    ignore_edge_deterioration_for_exit: bool = False
    ignore_stop_take_in_hold_mode: bool = False
    ignore_max_holding_in_hold_mode: bool = False


@dataclass
class PolicyDecision:
    action: str
    reason: str
    should_open: bool = False
    should_hold: bool = False
    should_close: bool = False
    intended_side: Optional[str] = None
    order_side: Optional[str] = None
    position_intent: Optional[str] = None
    exit_reason: Optional[str] = None
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    trailing_stop_price: Optional[float] = None
    risk_blocked: bool = False
    risk_block_reasons: list[str] = field(default_factory=list)
    edge_blocked: bool = False
    edge_block_reasons: list[str] = field(default_factory=list)
    context_blocked: bool = False
    context_block_reasons: list[str] = field(default_factory=list)
    ambiguous_stop_take_same_bar: bool = False
    no_lookahead_safe: bool = True
    paper_signal_write_allowed: bool = False
    paper_ledger_write_allowed: bool = False
    execution_enabled: bool = False
    # When close+reverse cannot be atomic in one ledger cycle.
    reverse_entry_candidate: bool = False
    reverse_entry_side: Optional[str] = None
    reverse_entry_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_unrealized_pnl_bps(
    *,
    side: str,
    entry_price: float,
    current_price: float,
) -> float:
    if entry_price <= 0 or current_price <= 0:
        return 0.0
    if str(side).upper() == "LONG":
        return (current_price / entry_price - 1.0) * 10_000.0
    if str(side).upper() == "SHORT":
        return (entry_price / current_price - 1.0) * 10_000.0
    return 0.0


def compute_stop_price(*, side: str, entry_price: float, stop_loss_bps: float) -> float:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    frac = float(stop_loss_bps) / 10_000.0
    if str(side).upper() == "LONG":
        return entry_price * (1.0 - frac)
    if str(side).upper() == "SHORT":
        return entry_price * (1.0 + frac)
    raise ValueError(f"unsupported side: {side}")


def compute_take_profit_price(*, side: str, entry_price: float, take_profit_bps: float) -> float:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    frac = float(take_profit_bps) / 10_000.0
    if str(side).upper() == "LONG":
        return entry_price * (1.0 + frac)
    if str(side).upper() == "SHORT":
        return entry_price * (1.0 - frac)
    raise ValueError(f"unsupported side: {side}")


def compute_trailing_stop_price(
    *,
    side: str,
    highest_high_since_entry: Optional[float],
    lowest_low_since_entry: Optional[float],
    trailing_drawdown_bps: Optional[float],
) -> Optional[float]:
    if trailing_drawdown_bps is None:
        return None
    frac = float(trailing_drawdown_bps) / 10_000.0
    if str(side).upper() == "LONG":
        if highest_high_since_entry is None or highest_high_since_entry <= 0:
            return None
        return highest_high_since_entry * (1.0 - frac)
    if str(side).upper() == "SHORT":
        if lowest_low_since_entry is None or lowest_low_since_entry <= 0:
            return None
        return lowest_low_since_entry * (1.0 + frac)
    return None


def normalize_effective_context(row_or_ctx: Any) -> Optional[str]:
    """Normalize a context label from a row mapping or raw string.

    Paper research: when active is non-directional but candidate_context is
    LONG/SHORT, treat candidate as the effective directional context.
    """
    if row_or_ctx is None:
        return None
    if isinstance(row_or_ctx, Mapping):
        raw = (
            row_or_ctx.get("active_market_context")
            or row_or_ctx.get("effective_context")
            or row_or_ctx.get("context")
            or row_or_ctx.get("raw_market_context")
        )
        text = str(raw or "").strip().upper()
        if text in DIRECTIONAL_CONTEXTS:
            return text
        cand = str(row_or_ctx.get("candidate_context") or "").strip().upper()
        if cand in DIRECTIONAL_CONTEXTS:
            return cand
        if not text or text in {"NAN", "NONE", "NULL", "<NA>"}:
            return "NONE"
        if text in {"NO_ACTIVE", "NO ACTIVE CONTEXT"}:
            return "NO_ACTIVE_CONTEXT"
        return text
    text = str(row_or_ctx or "").strip().upper()
    if not text or text in {"NAN", "NONE", "NULL", "<NA>"}:
        return "NONE"
    if text in {"NO_ACTIVE", "NO ACTIVE CONTEXT"}:
        return "NO_ACTIVE_CONTEXT"
    return text


def derive_context_start_event(
    previous_context: Any,
    current_row_or_context: Any,
    row: Any = None,
) -> dict[str, Any]:
    """Priority-ordered context start detection for paper research entries."""
    if row is None and isinstance(current_row_or_context, Mapping):
        row = current_row_or_context
    if not isinstance(row, Mapping):
        row = {}
    current = normalize_effective_context(current_row_or_context)
    previous = normalize_effective_context(previous_context)
    if previous is None and row.get("previous_active_market_context") is not None:
        previous = normalize_effective_context(row.get("previous_active_market_context"))
    now = row.get("candle_timestamp") or row.get("timestamp") or row.get("source_context_ts")
    cand = row.get("candidate_started_at") or row.get("context_candidate_started_at")
    active_started = row.get("active_context_started_at") or row.get("context_active_started_at")
    episode_start = row.get("lifecycle_episode_start_time") or row.get("lifecycle_start_time")
    cand_ctx = str(row.get("candidate_context") or "").strip().upper()

    # Explicit flag on decision row.
    if row.get("context_start_event") is True and current in DIRECTIONAL_CONTEXTS:
        # Explicit flag still requires a genuine transition or start-bar match.
        if previous == current and previous in DIRECTIONAL_CONTEXTS:
            return {
                "context_start_event": False,
                "context_start_event_source": "same_context_continuation",
                "fresh": False,
            }
        return {
            "context_start_event": True,
            "context_start_event_source": str(row.get("context_start_event_source") or "decision_log.context_start_event"),
            "fresh": True,
        }
    if episode_start and now and _ts_equalish(episode_start, now) and current in DIRECTIONAL_CONTEXTS:
        if previous == current and previous in DIRECTIONAL_CONTEXTS:
            return {
                "context_start_event": False,
                "context_start_event_source": "same_context_continuation",
                "fresh": False,
            }
        return {
            "context_start_event": True,
            "context_start_event_source": "lifecycle_episode_start_time",
            "fresh": True,
        }
    if cand and now and _ts_equalish(cand, now) and (
        current in DIRECTIONAL_CONTEXTS or cand_ctx in DIRECTIONAL_CONTEXTS
    ):
        # Candidate start bar is valid only for a new directional episode, not continuation.
        if previous == current and previous in DIRECTIONAL_CONTEXTS:
            return {
                "context_start_event": False,
                "context_start_event_source": "same_context_continuation",
                "fresh": False,
            }
        return {
            "context_start_event": True,
            "context_start_event_source": "candidate_started_at",
            "fresh": True,
        }
    # Active confirmation start only when it equals now AND candidate does not predate it.
    if (
        active_started
        and now
        and _ts_equalish(active_started, now)
        and current in DIRECTIONAL_CONTEXTS
    ):
        if previous == current and previous in DIRECTIONAL_CONTEXTS:
            return {
                "context_start_event": False,
                "context_start_event_source": "same_context_continuation",
                "fresh": False,
            }
        if cand and now and (not _ts_equalish(cand, now)):
            # Candidate already started earlier — active confirmation must not move entry forward.
            return {
                "context_start_event": False,
                "context_start_event_source": "active_confirmation_after_candidate",
                "fresh": False,
            }
        return {
            "context_start_event": True,
            "context_start_event_source": "active_context_started_at",
            "fresh": True,
        }
    if is_context_start_event(previous, current):
        # Transition into directional context: still require start bar, not late presence.
        if active_started and now and not _ts_equalish(active_started, now):
            if not (cand and _ts_equalish(cand, now)):
                return {
                    "context_start_event": False,
                    "context_start_event_source": "late_presence_after_start",
                    "fresh": False,
                }
        if cand and now and not _ts_equalish(cand, now) and active_started and not _ts_equalish(active_started, now):
            return {
                "context_start_event": False,
                "context_start_event_source": "late_presence_after_start",
                "fresh": False,
            }
        age = row.get("active_context_age_bars")
        try:
            if age is not None and int(age) > 0:
                if cand and now and _ts_equalish(cand, now):
                    return {
                        "context_start_event": True,
                        "context_start_event_source": "candidate_started_at",
                        "fresh": True,
                    }
                if active_started and now and _ts_equalish(active_started, now):
                    return {
                        "context_start_event": True,
                        "context_start_event_source": "active_context_started_at",
                        "fresh": True,
                    }
                return {
                    "context_start_event": False,
                    "context_start_event_source": "mid_episode_presence",
                    "fresh": False,
                }
        except Exception:
            pass
        return {
            "context_start_event": True,
            "context_start_event_source": "previous_active_context_differs",
            "fresh": True,
        }
    return {
        "context_start_event": False,
        "context_start_event_source": None,
        "fresh": False,
    }


def is_directional_context(ctx: Any) -> bool:
    return normalize_effective_context(ctx) in DIRECTIONAL_CONTEXTS


def context_side(ctx: Any) -> Optional[str]:
    normalized = normalize_effective_context(ctx)
    if normalized == "LONG_CONTEXT":
        return "LONG"
    if normalized == "SHORT_CONTEXT":
        return "SHORT"
    return None


def is_directional_flip(previous_context: Any, current_context: Any) -> bool:
    """True for LONG_CONTEXT <-> SHORT_CONTEXT flips (new directional episode)."""
    previous = normalize_effective_context(previous_context)
    current = normalize_effective_context(current_context)
    if previous not in DIRECTIONAL_CONTEXTS or current not in DIRECTIONAL_CONTEXTS:
        return False
    return previous != current


def is_context_start_event(previous_context: Any, current_context: Any) -> bool:
    """Entry start: new directional context including OBSERVE/idle -> direction and directional flip.

    Presence of the same directional context is NOT a start.
    Directional -> OBSERVE/idle is an end event, not an entry start.
    """
    current = normalize_effective_context(current_context)
    previous = normalize_effective_context(previous_context)
    if current not in DIRECTIONAL_CONTEXTS:
        return False
    if previous == current:
        return False
    if previous is None:
        return True
    if previous in CONTEXT_START_PREVIOUS_ALLOWED:
        return True
    # Any other non-directional predecessor still counts as a start.
    return previous not in DIRECTIONAL_CONTEXTS


def context_exit_reason_for_position(position_side: Any, current_context: Any) -> Optional[str]:
    """Exit reason when open position is invalidated by current context."""
    side = str(position_side or "").upper()
    current = normalize_effective_context(current_context)
    if side == "LONG" and current != "LONG_CONTEXT":
        if current == "SHORT_CONTEXT":
            return CONTEXT_FLIP_LONG_TO_SHORT
        return CONTEXT_END_EVENT_LONG
    if side == "SHORT" and current != "SHORT_CONTEXT":
        if current == "LONG_CONTEXT":
            return CONTEXT_FLIP_SHORT_TO_LONG
        return CONTEXT_END_EVENT_SHORT
    return None


def _ts_equalish(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    try:
        import pandas as pd

        ta = pd.Timestamp(a)
        tb = pd.Timestamp(b)
        if ta.tzinfo is None:
            ta = ta.tz_localize("UTC")
        else:
            ta = ta.tz_convert("UTC")
        if tb.tzinfo is None:
            tb = tb.tz_localize("UTC")
        else:
            tb = tb.tz_convert("UTC")
        return ta == tb
    except Exception:
        return str(a)[:19] == str(b)[:19]


def resolve_research_context_start(row: Any) -> dict[str, Any]:
    """Earliest directional research start without moving entry forward on ACTIVE confirm."""
    if not isinstance(row, Mapping):
        row = {}
    candidate = row.get("candidate_started_at") or row.get("context_candidate_started_at")
    active = row.get("active_context_started_at") or row.get("context_active_started_at")
    raw = row.get("context_raw_started_at") or row.get("raw_context_started_at") or row.get("context_started_at")
    event = row.get("context_event_detected_at") or row.get("candle_timestamp") or row.get("timestamp")
    chosen = None
    layer = ENTRY_LAYER_CONTEXT_START_EVENT
    for value, lyr in (
        (candidate, ENTRY_LAYER_CANDIDATE),
        (raw, ENTRY_LAYER_RAW),
        (active, ENTRY_LAYER_ACTIVE),
        (event, ENTRY_LAYER_CONTEXT_START_EVENT),
    ):
        if value is None:
            continue
        text = str(value).strip()
        if not text or text.upper() in {"NAN", "NONE", "NULL", "<NA>"}:
            continue
        chosen = text
        layer = lyr
        break
    return {
        "context_candidate_started_at": candidate,
        "context_active_started_at": active,
        "context_raw_started_at": raw,
        "context_confirmed_at": active,
        "research_context_started_at": chosen,
        "entry_used_context_layer": layer if chosen else None,
    }


def is_fresh_context_start(previous_context: Any, current_context: Any, row: Any = None) -> bool:
    """True for genuine start bar, including directional CANDIDATE start layer."""
    derived = derive_context_start_event(previous_context, current_context, row)
    if derived.get("context_start_event_source") in {
        "decision_log.context_start_event",
        "lifecycle_episode_start_time",
        "candidate_started_at",
        "active_context_started_at",
        "previous_active_context_differs",
    }:
        return bool(derived.get("fresh"))
    if derived.get("context_start_event_source") in {
        "active_confirmation_after_candidate",
        "mid_episode_presence",
        "same_or_late_presence",
        "same_context_continuation",
        "late_presence_after_start",
    }:
        return False
    if not is_context_start_event(previous_context, current_context):
        return False
    if not isinstance(row, Mapping):
        return True
    now = row.get("candle_timestamp") or row.get("timestamp") or row.get("source_context_ts")
    cand = row.get("candidate_started_at") or row.get("context_candidate_started_at")
    life = str(row.get("lifecycle_state") or "").upper()
    # Candidate start bar is a valid research entry start (do not wait for ACTIVE).
    if cand and now and _ts_equalish(cand, now):
        return True
    if life == "CANDIDATE" and is_directional_context(current_context):
        # First candidate bar for this directional context.
        age = row.get("active_context_age_bars")
        try:
            if age is not None and int(age) == 0:
                return True
        except Exception:
            pass
        if cand and now and _ts_equalish(cand, now):
            return True
    for age_key in ("active_context_age_bars", "context_age_bars", "lifecycle_age_bars"):
        age = row.get(age_key)
        if age is None:
            continue
        try:
            if int(age) > 0:
                # Mid-episode presence is not a start, unless candidate start equals this bar.
                if cand and now and _ts_equalish(cand, now):
                    return True
                return False
        except Exception:
            continue
    started = (
        row.get("candidate_started_at")
        or row.get("active_context_started_at")
        or row.get("context_started_at")
    )
    if started and now:
        try:
            import pandas as pd

            st = pd.Timestamp(started)
            nt = pd.Timestamp(now)
            if st.tzinfo is None:
                st = st.tz_localize("UTC")
            else:
                st = st.tz_convert("UTC")
            if nt.tzinfo is None:
                nt = nt.tz_localize("UTC")
            else:
                nt = nt.tz_convert("UTC")
            if st < nt:
                return False
        except Exception:
            pass
    return True


def is_hold_until_directional_context_end(params: PolicyParameters | Mapping[str, Any] | None) -> bool:
    if params is None:
        return False
    if isinstance(params, Mapping):
        ctx_mode = str(params.get("context_exit_mode") or "")
        hold = str(params.get("paper_context_hold_mode") or "")
    else:
        ctx_mode = str(getattr(params, "context_exit_mode", "") or "")
        hold = str(getattr(params, "paper_context_hold_mode", "") or "")
    if ctx_mode.upper() == "EXIT_ON_FIRST_INVALIDATION" and not hold:
        return False
    mode = hold or ctx_mode
    return mode.upper() in {
        PAPER_CONTEXT_HOLD_MODE_UNTIL_END,
        HOLD_UNTIL_DIRECTIONAL_CONTEXT_END,
        "EXIT_AT_CONTEXT_END_ONLY",
    }


def is_trade_all_directional_starts(params: PolicyParameters | Mapping[str, Any] | None) -> bool:
    if params is None:
        return False
    if isinstance(params, Mapping):
        mode = str(params.get("paper_context_policy_mode") or "")
        if bool(params.get("ignore_edge_confidence_for_entry")):
            return True
        return mode.upper() == PAPER_CONTEXT_POLICY_MODE_TRADE_ALL
    mode = str(getattr(params, "paper_context_policy_mode", "") or "")
    if bool(getattr(params, "ignore_edge_confidence_for_entry", False)):
        return True
    return mode.upper() == PAPER_CONTEXT_POLICY_MODE_TRADE_ALL


def is_context_end_event(position_side: Any, current_context: Any) -> bool:
    side = str(position_side or "").upper()
    current = normalize_effective_context(current_context)
    if side == "LONG":
        return current != "LONG_CONTEXT"
    if side == "SHORT":
        return current != "SHORT_CONTEXT"
    return False


def _episode_key_value_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    text = str(value).strip()
    if not text:
        return None
    if text.upper() in {"NAN", "NAT", "NONE", "NULL", "<NA>"}:
        return None
    return text


def is_missing_context_episode_key(episode_key: Any) -> bool:
    return str(episode_key or "").startswith(f"{MISSING_CONTEXT_EPISODE_KEY_PREFIX}|")


def _first_episode_key_value(row: Mapping[str, Any], keys: Sequence[str]) -> tuple[str, str] | None:
    for key in keys:
        text = _episode_key_value_text(row.get(key))
        if text is not None:
            return key, text
    return None


def derive_context_episode_key(row: Any) -> str:
    """Stable episode key for one-trade-per-context memory."""
    if not isinstance(row, Mapping):
        row = {"active_market_context": row}
    ctx = normalize_effective_context(row) or "NONE"
    life = str(row.get("lifecycle_state") or "").strip().upper()
    cand_ctx = str(row.get("candidate_context") or "").strip().upper()
    candidate_directional = life == "CANDIDATE" and cand_ctx in DIRECTIONAL_CONTEXTS
    if candidate_directional:
        preferred = _first_episode_key_value(
            row,
            (
                "candidate_started_at",
                "context_candidate_started_at",
                "source_context_ts",
                "context_start_event_ts",
                "context_start_event_timestamp",
                "context_event_detected_at",
                "event_detected_at",
                "detected_at",
                "intrabar_event_detected_at",
                "candle_timestamp",
                "timestamp",
                "latest_decision_log_ts",
                "decision_available_at",
                "decision_written_at_utc",
                "signal_fields_generated_at_utc",
            ),
        )
        if preferred is not None:
            key, text = preferred
            return f"{key}:{text}|{ctx}"
    for key in (
        "lifecycle_episode_id",
        "context_episode_id",
        "episode_id",
        "active_context_started_at",
        "context_started_at",
        "source_context_ts",
    ):
        text = _episode_key_value_text(row.get(key))
        if text is None:
            continue
        if key in {"lifecycle_episode_id", "context_episode_id", "episode_id"}:
            return f"{text}|{ctx}"
        return f"{key}:{text}|{ctx}"
    fallback = _first_episode_key_value(
        row,
        (
            "context_start_event_ts",
            "context_start_event_timestamp",
            "context_event_detected_at",
            "event_detected_at",
            "detected_at",
            "intrabar_event_detected_at",
            "candle_timestamp",
            "timestamp",
            "latest_decision_log_ts",
            "decision_available_at",
            "decision_written_at_utc",
            "signal_fields_generated_at_utc",
        ),
    )
    if fallback is not None:
        key, text = fallback
        return f"fallback_{key}:{text}|{ctx}"
    return f"{MISSING_CONTEXT_EPISODE_KEY_PREFIX}|{ctx}"


def empty_traded_episode_memory() -> dict[str, Any]:
    return {"episodes": {}, "paper_only": True, "execution_enabled": False}


def is_context_episode_already_traded(memory: Mapping[str, Any] | None, episode_key: str | None) -> bool:
    if not episode_key:
        return False
    episodes = (memory or {}).get("episodes") if isinstance(memory, Mapping) else None
    if not isinstance(episodes, Mapping):
        return False
    return episode_key in episodes


def mark_context_episode_traded(
    memory: Mapping[str, Any] | None,
    *,
    episode_key: str,
    side: str,
    context: str,
    trade_id: str | None = None,
    signal_id: str | None = None,
    entry_ts: str | None = None,
) -> dict[str, Any]:
    base = empty_traded_episode_memory()
    if isinstance(memory, Mapping):
        existing = memory.get("episodes")
        if isinstance(existing, Mapping):
            base["episodes"] = dict(existing)
    if episode_key not in base["episodes"]:
        base["episodes"][episode_key] = {
            "side": str(side).upper(),
            "first_trade_id": trade_id,
            "first_signal_id": signal_id,
            "entry_ts": entry_ts,
            "context": normalize_effective_context(context) or str(context),
        }
    return base


def is_stale_or_untradable(state: PolicyEngineState) -> bool:
    return bool(state.is_stale)


def is_context_valid_for_position(
    *,
    position_state: str,
    active_market_context: str,
    lifecycle_state: str,
    context_exit_mode: str,
) -> bool:
    ctx = str(active_market_context or "").upper()
    life = str(lifecycle_state or "").upper()
    mode = str(context_exit_mode or "").upper()
    pos = str(position_state or "").upper()

    # HOLD_UNTIL_DIRECTIONAL_CONTEXT_END: keep position while same directional context.
    # CHALLENGED / questionable / weak / confidence drop do NOT invalidate.
    if mode in {
        HOLD_UNTIL_DIRECTIONAL_CONTEXT_END,
        PAPER_CONTEXT_HOLD_MODE_UNTIL_END,
        "EXIT_AT_CONTEXT_END_ONLY",
    }:
        if pos == "LONG":
            return ctx == "LONG_CONTEXT"
        if pos == "SHORT":
            return ctx == "SHORT_CONTEXT"
        return True

    if life in INVALID_LIFECYCLE:
        return False
    if mode == "EXIT_AT_CONTEXT_END_ONLY":
        return life not in INVALID_LIFECYCLE
    # EXIT_ON_FIRST_INVALIDATION (default legacy)
    if pos == "LONG":
        return ctx not in LONG_INVALIDATING
    if pos == "SHORT":
        return ctx not in SHORT_INVALIDATING
    return True


def is_edge_valid_for_entry(state: PolicyEngineState, params: PolicyParameters) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not state.confidence_available or state.confidence is None:
        reasons.append("missing_confidence")
    elif float(state.confidence) < float(params.confidence_threshold):
        reasons.append("confidence_below_threshold")
    if not state.expected_edge_available or state.expected_edge_bps is None:
        reasons.append("missing_expected_edge")
    else:
        basis = str(state.expected_edge_basis or "").upper()
        edge = float(state.expected_edge_bps)
        if basis in {"", "NET_AFTER_COST", "NET"}:
            if edge <= 0.0 or edge < float(params.expected_edge_min_bps):
                reasons.append("expected_edge_not_positive_net_after_cost")
        else:
            # Conservative: require positive net after cost when basis unknown/non-net.
            if edge <= float(params.total_roundtrip_model_cost_bps):
                reasons.append("expected_edge_not_positive_after_cost_adjustment")
    if not state.edge_signal_pass:
        reasons.append("edge_signal_pass_false")
    return (len(reasons) == 0, reasons)


def is_edge_deteriorated(state: PolicyEngineState, params: PolicyParameters) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not state.confidence_available or state.confidence is None:
        reasons.append("confidence_unavailable")
    if not state.expected_edge_available or state.expected_edge_bps is None:
        reasons.append("expected_edge_unavailable")
    elif float(state.expected_edge_bps) <= 0.0:
        reasons.append("expected_edge_bps_non_positive")
    if not state.edge_signal_pass:
        reasons.append("edge_signal_pass_false")
    # params kept for API symmetry / future threshold extensions
    _ = params
    return (len(reasons) > 0, reasons)


def evaluate_risk_block(
    state: PolicyEngineState,
    position: PositionState,
    risk: RiskState,
    *,
    intending_open: bool = False,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if float(risk.daily_pnl_bps) <= -abs(float(risk.daily_loss_limit_bps)):
        reasons.append("daily_loss_breached")
    if int(risk.trades_today) >= int(risk.max_trades_per_day):
        reasons.append("max_trades_per_day_breached")
    if float(risk.current_drawdown_bps) >= float(risk.max_drawdown_bps):
        reasons.append("max_drawdown_breached")
    if intending_open:
        if str(position.position_state).upper() != "FLAT":
            reasons.append("duplicate_active_position_attempt")
        if float(risk.current_position_notional_pct) > float(risk.max_position_notional_pct):
            reasons.append("max_position_notional_breached")
        if float(state.current_price) <= 0 or float(state.current_close) <= 0:
            reasons.append("invalid_price")
        if float(position.quantity) < 0:
            reasons.append("invalid_quantity")
    else:
        if float(risk.current_position_notional_pct) > float(risk.max_position_notional_pct) and str(
            position.position_state
        ).upper() != "FLAT":
            reasons.append("max_position_notional_breached")
        if str(position.position_state).upper() != "FLAT":
            if position.entry_price is None or float(position.entry_price) <= 0:
                reasons.append("invalid_price")
            if float(position.quantity) <= 0:
                reasons.append("invalid_quantity")
    return (len(reasons) > 0, reasons)


def _base_decision(**kwargs: Any) -> PolicyDecision:
    return PolicyDecision(
        paper_signal_write_allowed=False,
        paper_ledger_write_allowed=False,
        execution_enabled=False,
        no_lookahead_safe=True,
        **kwargs,
    )


def evaluate_entry(
    state: PolicyEngineState,
    position: PositionState,
    risk: RiskState,
    params: PolicyParameters,
) -> PolicyDecision:
    ctx = normalize_effective_context(state.active_market_context) or ""
    prev = normalize_effective_context(state.previous_active_market_context)
    life = str(state.lifecycle_state or "").upper()
    row_for_start = {
        "active_market_context": ctx,
        "lifecycle_episode_id": state.lifecycle_episode_id,
        "active_context_started_at": state.active_context_started_at,
        "context_started_at": state.context_started_at,
        "source_context_ts": state.source_context_ts,
        "timestamp": state.timestamp,
        "candle_timestamp": state.timestamp,
        "lifecycle_state": life,
        "candidate_started_at": getattr(state, "candidate_started_at", None),
        "candidate_context": getattr(state, "candidate_context", None),
        "active_context_age_bars": None,
    }
    episode_key = state.context_episode_key or derive_context_episode_key(row_for_start)

    if str(position.position_state or "").upper() != "FLAT":
        return _base_decision(
            action="BLOCKED_BY_OPEN_POSITION",
            reason=ENTRY_BLOCKED_POSITION_ALREADY_OPEN,
            context_blocked=True,
            context_block_reasons=[ENTRY_BLOCKED_POSITION_ALREADY_OPEN],
        )

    if not bool(getattr(state, "market_snapshot_available", True)):
        return _base_decision(
            action="NO_TRADE",
            reason=MARKET_DATA_SNAPSHOT_UNAVAILABLE,
            context_blocked=True,
            context_block_reasons=[MARKET_DATA_SNAPSHOT_UNAVAILABLE],
        )

    if is_stale_or_untradable(state):
        return _base_decision(
            action="BLOCKED_BY_STALE_CONTEXT",
            reason=ENTRY_BLOCKED_CONTEXT_STALE,
            context_blocked=True,
            context_block_reasons=[ENTRY_BLOCKED_CONTEXT_STALE, "is_stale"],
        )

    # CHALLENGED / CANDIDATE / WEAK / QUESTIONABLE are allowed for directional research trades.
    # Only non-directional contexts and truly terminal lifecycle block entry.
    if not is_directional_context(ctx) or ctx in FLAT_NO_TRADE_CONTEXTS:
        return _base_decision(
            action="NO_TRADE",
            reason=ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT,
            context_blocked=True,
            context_block_reasons=[ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT, f"context={ctx}", f"lifecycle={life}"],
        )
    if life in INVALID_LIFECYCLE and life != "CHALLENGED":
        return _base_decision(
            action="NO_TRADE",
            reason=ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT,
            context_blocked=True,
            context_block_reasons=[ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT, f"context={ctx}", f"lifecycle={life}"],
        )

    fresh_context_start = is_fresh_context_start(prev, ctx, row_for_start)
    paper_collection_mode = is_trade_all_directional_starts(params)
    if not fresh_context_start and not paper_collection_mode:
        return _base_decision(
            action="NO_TRADE",
            reason=ENTRY_BLOCKED_NO_CONTEXT_START_EVENT,
            context_blocked=True,
            context_block_reasons=[
                ENTRY_BLOCKED_NO_CONTEXT_START_EVENT,
                f"previous={prev}",
                f"current={ctx}",
            ],
        )

    if is_missing_context_episode_key(episode_key):
        return _base_decision(
            action="NO_TRADE",
            reason=ENTRY_BLOCKED_MISSING_CONTEXT_EPISODE_KEY,
            context_blocked=True,
            context_block_reasons=[ENTRY_BLOCKED_MISSING_CONTEXT_EPISODE_KEY, f"episode_key={episode_key}"],
        )

    traded_keys = set(state.traded_context_episode_keys or ())
    if episode_key in traded_keys or is_context_episode_already_traded(
        {"episodes": {k: {} for k in traded_keys}}, episode_key
    ):
        return _base_decision(
            action="NO_TRADE",
            reason=ENTRY_BLOCKED_CONTEXT_EPISODE_ALREADY_TRADED,
            context_blocked=True,
            context_block_reasons=[ENTRY_BLOCKED_CONTEXT_EPISODE_ALREADY_TRADED, f"episode_key={episode_key}"],
        )

    # TRADE_ALL_DIRECTIONAL_CONTEXT_STARTS: do not block on quality/confidence/edge.
    if not is_trade_all_directional_starts(params):
        edge_ok, edge_reasons = is_edge_valid_for_entry(state, params)
        if not edge_ok:
            return _base_decision(
                action="BLOCKED_BY_NO_EDGE",
                reason="edge_invalid_for_entry",
                edge_blocked=True,
                edge_block_reasons=edge_reasons,
            )

    risk_blocked, risk_reasons = evaluate_risk_block(state, position, risk, intending_open=True)
    if risk_blocked:
        return _base_decision(
            action="BLOCKED_BY_RISK",
            reason="risk_gate_failed",
            risk_blocked=True,
            risk_block_reasons=risk_reasons,
        )

    paper_entry_basis = (
        "CONTEXT_START_EVENT" if fresh_context_start else "ACTIVE_DIRECTIONAL_CONTEXT"
    )
    original_gate_reasons = (
        [] if fresh_context_start else [f"original_gate_reason={ENTRY_BLOCKED_NO_CONTEXT_START_EVENT}"]
    )

    if ctx == "LONG_CONTEXT":
        flip = is_directional_flip(prev, ctx)
        return _base_decision(
            action="OPEN_LONG",
            reason=CONTEXT_FLIP_START_EVENT
            if flip
            else ("context_start_event_long" if fresh_context_start else "active_directional_context_long"),
            should_open=True,
            intended_side="LONG",
            order_side="BUY",
            position_intent="OPEN_LONG",
            stop_price=compute_stop_price(
                side="LONG", entry_price=float(state.current_close), stop_loss_bps=params.stop_loss_bps
            ),
            take_profit_price=compute_take_profit_price(
                side="LONG", entry_price=float(state.current_close), take_profit_bps=params.take_profit_bps
            ),
            context_block_reasons=[
                f"episode_key={episode_key}",
                f"context_start_event={str(bool(fresh_context_start)).lower()}",
                f"paper_entry_basis={paper_entry_basis}",
                f"directional_flip={flip}",
                *original_gate_reasons,
            ],
        )
    if ctx == "SHORT_CONTEXT":
        flip = is_directional_flip(prev, ctx)
        return _base_decision(
            action="OPEN_SHORT",
            reason=CONTEXT_FLIP_START_EVENT
            if flip
            else ("context_start_event_short" if fresh_context_start else "active_directional_context_short"),
            should_open=True,
            intended_side="SHORT",
            order_side="SELL",
            position_intent="OPEN_SHORT",
            stop_price=compute_stop_price(
                side="SHORT", entry_price=float(state.current_close), stop_loss_bps=params.stop_loss_bps
            ),
            take_profit_price=compute_take_profit_price(
                side="SHORT", entry_price=float(state.current_close), take_profit_bps=params.take_profit_bps
            ),
            context_block_reasons=[
                f"episode_key={episode_key}",
                f"context_start_event={str(bool(fresh_context_start)).lower()}",
                f"paper_entry_basis={paper_entry_basis}",
                f"directional_flip={flip}",
                *original_gate_reasons,
            ],
        )

    return _base_decision(
        action="NO_TRADE",
        reason=ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT,
        context_blocked=True,
        context_block_reasons=[ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT, f"context={ctx}"],
    )


def _exit_levels(
    *,
    side: str,
    position: PositionState,
    params: PolicyParameters,
) -> tuple[float, float, Optional[float], bool]:
    entry = float(position.entry_price or 0.0)
    stop = compute_stop_price(side=side, entry_price=entry, stop_loss_bps=params.stop_loss_bps)
    take = compute_take_profit_price(side=side, entry_price=entry, take_profit_bps=params.take_profit_bps)
    trailing_active = bool(position.trailing_active)
    trail = position.current_trailing_stop_price
    if params.trailing_enabled and params.trailing_activation_bps is not None:
        # Activate from current excursion if MFE threshold met (current-state only).
        mfe = position.mfe_bps
        if mfe is None and position.highest_high_since_entry and position.lowest_low_since_entry:
            if side == "LONG" and entry > 0:
                mfe = (float(position.highest_high_since_entry) / entry - 1.0) * 10_000.0
            elif side == "SHORT" and entry > 0 and position.lowest_low_since_entry:
                mfe = (entry / float(position.lowest_low_since_entry) - 1.0) * 10_000.0
        if mfe is not None and float(mfe) >= float(params.trailing_activation_bps):
            trailing_active = True
            trail = compute_trailing_stop_price(
                side=side,
                highest_high_since_entry=position.highest_high_since_entry,
                lowest_low_since_entry=position.lowest_low_since_entry,
                trailing_drawdown_bps=params.trailing_drawdown_bps,
            )
    return stop, take, trail if trailing_active else None, trailing_active


def evaluate_exit(
    state: PolicyEngineState,
    position: PositionState,
    risk: RiskState,
    params: PolicyParameters,
) -> PolicyDecision:
    side = str(position.position_state).upper()
    if side not in {"LONG", "SHORT"}:
        return _base_decision(action="NO_TRADE", reason="not_in_position")

    stop, take, trail, trailing_active = _exit_levels(side=side, position=position, params=params)
    hi = float(state.current_high)
    lo = float(state.current_low)

    stop_hit = (lo <= stop) if side == "LONG" else (hi >= stop)
    take_hit = (hi >= take) if side == "LONG" else (lo <= take)
    trail_hit = False
    if trailing_active and trail is not None:
        trail_hit = (lo <= float(trail)) if side == "LONG" else (hi >= float(trail))
    ambiguous = bool(stop_hit and take_hit)

    context_valid = is_context_valid_for_position(
        position_state=side,
        active_market_context=state.active_market_context,
        lifecycle_state=state.lifecycle_state,
        context_exit_mode=(
            HOLD_UNTIL_DIRECTIONAL_CONTEXT_END
            if is_hold_until_directional_context_end(params)
            else params.context_exit_mode
        ),
    )
    edge_det, edge_reasons = is_edge_deteriorated(state, params)
    max_hold = int(position.bars_in_position) >= int(params.max_holding_bars)
    hold_mode = is_hold_until_directional_context_end(params)
    if hold_mode and bool(getattr(params, "ignore_edge_deterioration_for_exit", True)):
        edge_det = False
        edge_reasons = []
    if hold_mode and bool(getattr(params, "ignore_max_holding_in_hold_mode", True)):
        max_hold = False

    risk_blocked, risk_reasons = evaluate_risk_block(state, position, risk, intending_open=False)
    # Risk breach while in position => RISK_EXIT close
    candidates: list[str] = []
    if risk_blocked and any(
        r in risk_reasons
        for r in ("daily_loss_breached", "max_drawdown_breached", "invalid_price", "invalid_quantity")
    ):
        candidates.append("RISK_EXIT")
    # Hold-until-context-end research mode: ignore stop/take/trailing; exit on context end only.
    if not (hold_mode and bool(getattr(params, "ignore_stop_take_in_hold_mode", True))):
        if stop_hit:
            candidates.append("HARD_STOP_LOSS")
        if take_hit:
            if not (ambiguous and str(params.conservative_intrabar_assumption).upper() == "STOP_FIRST"):
                candidates.append("TAKE_PROFIT")
        if trail_hit:
            candidates.append("TRAILING_STOP")
    if not context_valid:
        candidates.append("CONTEXT_INVALIDATION")
    if edge_det:
        candidates.append("EDGE_DETERIORATION")
    if max_hold:
        candidates.append("MAX_HOLDING_BARS")

    if not candidates:
        return evaluate_hold(state, position, risk, params, stop=stop, take=take, trail=trail)

    # Conservative priority
    chosen = None
    for key in EXIT_PRIORITY:
        if key in candidates:
            chosen = key
            break
    if chosen is None:
        chosen = candidates[0]

    close_action = "CLOSE_LONG" if side == "LONG" else "CLOSE_SHORT"
    order_side = "SELL" if side == "LONG" else "BUY"
    ctx_exit = context_exit_reason_for_position(side, state.active_market_context)
    reason_map = {
        "RISK_EXIT": "risk_exit",
        "HARD_STOP_LOSS": "hard_stop_loss",
        "TAKE_PROFIT": "take_profit",
        "TRAILING_STOP": "trailing_stop",
        "CONTEXT_INVALIDATION": ctx_exit
        or (CONTEXT_END_EVENT_LONG if side == "LONG" else CONTEXT_END_EVENT_SHORT),
        "EDGE_DETERIORATION": "edge_deterioration",
        "MAX_HOLDING_BARS": "max_holding_bars",
    }
    exit_reason = chosen
    if chosen == "CONTEXT_INVALIDATION":
        exit_reason = ctx_exit or (CONTEXT_END_EVENT_LONG if side == "LONG" else CONTEXT_END_EVENT_SHORT)

    reverse_side = None
    reverse_candidate = False
    if chosen == "CONTEXT_INVALIDATION" and exit_reason in {
        CONTEXT_FLIP_LONG_TO_SHORT,
        CONTEXT_FLIP_SHORT_TO_LONG,
    }:
        reverse_candidate = True
        reverse_side = "SHORT" if exit_reason == CONTEXT_FLIP_LONG_TO_SHORT else "LONG"

    return _base_decision(
        action=close_action,
        reason=reason_map.get(chosen, chosen.lower()),
        should_close=True,
        intended_side=side,
        order_side=order_side,
        position_intent=close_action,
        exit_reason=exit_reason,
        stop_price=stop,
        take_profit_price=take,
        trailing_stop_price=trail,
        risk_blocked=bool(chosen == "RISK_EXIT"),
        risk_block_reasons=risk_reasons if chosen == "RISK_EXIT" else [],
        edge_blocked=bool(chosen == "EDGE_DETERIORATION"),
        edge_block_reasons=edge_reasons if chosen == "EDGE_DETERIORATION" else [],
        context_blocked=bool(chosen == "CONTEXT_INVALIDATION"),
        context_block_reasons=(
            [
                exit_reason,
                f"context={state.active_market_context}",
                f"lifecycle={state.lifecycle_state}",
                f"context_end_event={is_context_end_event(side, state.active_market_context)}",
                f"directional_flip={bool(reverse_candidate)}",
            ]
            if chosen == "CONTEXT_INVALIDATION"
            else []
        ),
        ambiguous_stop_take_same_bar=ambiguous,
        reverse_entry_candidate=reverse_candidate,
        reverse_entry_side=reverse_side,
        reverse_entry_reason=CONTEXT_FLIP_START_EVENT if reverse_candidate else None,
    )


def evaluate_hold(
    state: PolicyEngineState,
    position: PositionState,
    risk: RiskState,
    params: PolicyParameters,
    *,
    stop: Optional[float] = None,
    take: Optional[float] = None,
    trail: Optional[float] = None,
) -> PolicyDecision:
    _ = (state, risk)
    side = str(position.position_state).upper()
    if side == "LONG":
        if stop is None and position.entry_price:
            stop = compute_stop_price(side="LONG", entry_price=float(position.entry_price), stop_loss_bps=params.stop_loss_bps)
            take = compute_take_profit_price(
                side="LONG", entry_price=float(position.entry_price), take_profit_bps=params.take_profit_bps
            )
        return _base_decision(
            action="HOLD_LONG",
            reason="no_exit_triggered",
            should_hold=True,
            intended_side="LONG",
            position_intent="HOLD_LONG",
            stop_price=stop,
            take_profit_price=take,
            trailing_stop_price=trail,
        )
    if side == "SHORT":
        if stop is None and position.entry_price:
            stop = compute_stop_price(side="SHORT", entry_price=float(position.entry_price), stop_loss_bps=params.stop_loss_bps)
            take = compute_take_profit_price(
                side="SHORT", entry_price=float(position.entry_price), take_profit_bps=params.take_profit_bps
            )
        return _base_decision(
            action="HOLD_SHORT",
            reason="no_exit_triggered",
            should_hold=True,
            intended_side="SHORT",
            position_intent="HOLD_SHORT",
            stop_price=stop,
            take_profit_price=take,
            trailing_stop_price=trail,
        )
    return _base_decision(action="NO_TRADE", reason="flat_no_hold")


def evaluate_policy(
    state: PolicyEngineState,
    position: PositionState,
    risk: RiskState,
    params: PolicyParameters,
) -> PolicyDecision:
    pos = str(position.position_state or "FLAT").upper()
    if pos == "FLAT":
        return evaluate_entry(state, position, risk, params)
    if pos in {"LONG", "SHORT"}:
        return evaluate_exit(state, position, risk, params)
    return _base_decision(action="NO_TRADE", reason=f"unknown_position_state={pos}")


def policy_parameters_from_mapping(raw: Mapping[str, Any], *, fixture_only: bool = False) -> PolicyParameters:
    trailing_enabled = bool(raw.get("trailing_enabled", False))
    act = raw.get("trailing_activation_bps")
    dd = raw.get("trailing_drawdown_bps")
    return PolicyParameters(
        stop_loss_bps=float(raw["stop_loss_bps"]),
        take_profit_bps=float(raw["take_profit_bps"]),
        trailing_activation_bps=None if act is None or (isinstance(act, float) and act != act) else float(act),
        trailing_drawdown_bps=None if dd is None or (isinstance(dd, float) and dd != dd) else float(dd),
        max_holding_bars=int(raw["max_holding_bars"]),
        context_exit_mode=str(raw.get("context_exit_mode") or "EXIT_ON_FIRST_INVALIDATION"),
        confidence_threshold=float(raw.get("confidence_threshold", 0.0)),
        expected_edge_min_bps=float(raw.get("expected_edge_min_bps", 0.0)),
        total_roundtrip_model_cost_bps=float(raw.get("total_roundtrip_model_cost_bps", 20.0)),
        conservative_intrabar_assumption=str(raw.get("conservative_intrabar_assumption") or "STOP_FIRST"),
        fixture_only=bool(raw.get("fixture_only", fixture_only)),
        selected_policy_id=str(raw.get("selected_policy_id") or ""),
        trailing_enabled=trailing_enabled,
        paper_context_policy_mode=str(raw.get("paper_context_policy_mode") or ""),
        paper_context_hold_mode=str(raw.get("paper_context_hold_mode") or ""),
        trade_all_qualities=bool(raw.get("trade_all_qualities", False)),
        ignore_edge_confidence_for_entry=bool(raw.get("ignore_edge_confidence_for_entry", False)),
        ignore_edge_deterioration_for_exit=bool(raw.get("ignore_edge_deterioration_for_exit", False)),
        ignore_stop_take_in_hold_mode=bool(raw.get("ignore_stop_take_in_hold_mode", False)),
        ignore_max_holding_in_hold_mode=bool(raw.get("ignore_max_holding_in_hold_mode", False)),
    )


__all__ = [
    "CONTEXT_END_EVENT_LONG",
    "CONTEXT_END_EVENT_SHORT",
    "CONTEXT_FLIP_LONG_TO_SHORT",
    "CONTEXT_FLIP_SHORT_TO_LONG",
    "CONTEXT_FLIP_START_EVENT",
    "DIRECTIONAL_CONTEXTS",
    "ENTRY_BLOCKED_CONTEXT_EPISODE_ALREADY_TRADED",
    "ENTRY_BLOCKED_CONTEXT_STALE",
    "ENTRY_BLOCKED_NO_CONTEXT_START_EVENT",
    "ENTRY_BLOCKED_MISSING_CONTEXT_EPISODE_KEY",
    "ENTRY_BLOCKED_NON_DIRECTIONAL_CONTEXT",
    "ENTRY_BLOCKED_NO_ATOMIC_EXECUTION_PRICE",
    "ENTRY_BLOCKED_POSITION_ALREADY_OPEN",
    "ENTRY_BLOCKED_SHORT_NOT_SUPPORTED",
    "EXIT_PENDING_MARKET_DATA_UNAVAILABLE",
    "EXIT_PRIORITY",
    "MARKET_DATA_SNAPSHOT_UNAVAILABLE",
    "HOLD_UNTIL_DIRECTIONAL_CONTEXT_END",
    "PAPER_CONTEXT_HOLD_MODE_UNTIL_END",
    "PAPER_CONTEXT_POLICY_MODE_TRADE_ALL",
    "ENTRY_LAYER_CANDIDATE",
    "ENTRY_LAYER_ACTIVE",
    "ENTRY_LAYER_RAW",
    "ENTRY_LAYER_CONTEXT_START_EVENT",
    "is_hold_until_directional_context_end",
    "is_trade_all_directional_starts",
    "resolve_research_context_start",
    "PolicyDecision",
    "PolicyEngineState",
    "PolicyParameters",
    "PositionState",
    "RiskState",
    "compute_stop_price",
    "compute_take_profit_price",
    "compute_trailing_stop_price",
    "compute_unrealized_pnl_bps",
    "context_exit_reason_for_position",
    "context_side",
    "derive_context_episode_key",
    "empty_traded_episode_memory",
    "evaluate_entry",
    "evaluate_exit",
    "evaluate_hold",
    "evaluate_policy",
    "evaluate_risk_block",
    "is_context_end_event",
    "is_context_episode_already_traded",
    "is_context_start_event",
    "is_fresh_context_start",
    "is_missing_context_episode_key",
    "is_context_valid_for_position",
    "is_directional_context",
    "is_directional_flip",
    "is_edge_deteriorated",
    "is_edge_valid_for_entry",
    "is_stale_or_untradable",
    "mark_context_episode_traded",
    "normalize_effective_context",
    "policy_parameters_from_mapping",
]
