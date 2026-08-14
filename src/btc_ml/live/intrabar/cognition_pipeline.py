"""Orchestrate provisional intrabar cognition for one causal cutoff."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import pandas as pd

from btc_ml.cognition.volume_localization_engine_v1 import localize_bar
from btc_ml.cognition.volume_response_evaluate import evaluate_response_row
from btc_ml.live.intrabar.context_event_journal import ContextEventJournal
from btc_ml.live.intrabar.event_time_lifecycle import (
    detect_context_transition,
    step_event_time_lifecycle,
)
from btc_ml.live.intrabar.partial_bar_state import TIMEFRAMES, PartialBarStateEngine
from btc_ml.live.intrabar.provisional_synthesis import synthesize_provisional_state
from btc_ml.live.intrabar.structure_geometry import compute_geometry_fields
from btc_ml.trading.timeframe_state_adapter import resolve_timeframe_state, TimeframeSources

MODEL_VERSION = "live1a_canonical_intrabar_v1"
MAX_GEOMETRY_HISTORY_ROWS = 256


class IntrabarCognitionEngine:
    def __init__(
        self,
        *,
        context_journal: ContextEventJournal,
        localization_history: Optional[pd.DataFrame] = None,
        geometry_history: Optional[pd.DataFrame] = None,
        reactions_history: Optional[pd.DataFrame] = None,
    ):
        self.bars = PartialBarStateEngine()
        self.journal = context_journal
        self.localization_history = localization_history if localization_history is not None else pd.DataFrame()
        # Per-TF completed-bar geometry. Shared legacy frame (if provided) seeds every TF
        # for tests; live service starts empty and accumulates closed bars only.
        seed = geometry_history if geometry_history is not None else pd.DataFrame()
        self.geometry_by_tf: dict[str, pd.DataFrame] = {
            tf: (seed.copy() if len(seed) else pd.DataFrame()) for tf in TIMEFRAMES
        }
        self.geometry_history = seed  # backward-compat alias (not used for TF prev_close)
        self.reactions_history = reactions_history if reactions_history is not None else pd.DataFrame()
        self.lifecycle_prev: dict[str, dict[str, Any] | None] = {tf: None for tf in TIMEFRAMES}
        self.prior_auction_by_tf: dict[str, str] = {tf: "UNKNOWN" for tf in TIMEFRAMES}
        self.last_eval: dict[str, dict[str, Any]] = {}
        self.last_context_event: dict[str, dict[str, Any]] = {}
        self.event_counts = {"CONTEXT_START": 0, "CONTEXT_END": 0, "CONTEXT_FLIP": 0}
        self.bbo: dict[str, Any] = {}
        self._active_episode: dict[str, str] = {}
        self._episode_seq = 0
        self.errors: list[str] = []

    def _append_closed_bars(self, closed: list[dict[str, Any]]) -> None:
        """Retain completed bars per timeframe for causal prev_close / FT / RV."""
        for row in closed:
            tf = str(row.get("timeframe") or "")
            if tf not in self.geometry_by_tf:
                continue
            high = float(row.get("high") if row.get("high") is not None else row.get("high_so_far") or 0.0)
            low = float(row.get("low") if row.get("low") is not None else row.get("low_so_far") or 0.0)
            close = float(row.get("close") if row.get("close") is not None else row.get("last") or 0.0)
            add = pd.DataFrame(
                [
                    {
                        "timestamp": row.get("bar_open_timestamp"),
                        "open": float(row.get("open") or 0.0),
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": float(row.get("volume") if row.get("volume") is not None else row.get("volume_so_far") or 0.0),
                        "delta": float(row.get("delta") or 0.0),
                        "spread": high - low,
                        "timeframe": tf,
                        "estimated_local_volume": float(
                            row.get("volume") if row.get("volume") is not None else row.get("volume_so_far") or 0.0
                        ),
                    }
                ]
            )
            frame = self.geometry_by_tf[tf]
            merged = pd.concat([frame, add], ignore_index=True) if len(frame) else add
            self.geometry_by_tf[tf] = merged.tail(MAX_GEOMETRY_HISTORY_ROWS).reset_index(drop=True)

    def on_book_ticker(self, event: Mapping[str, Any]) -> None:
        self.bbo = {
            "best_bid": event.get("best_bid_price"),
            "best_ask": event.get("best_ask_price"),
            "book_update_id": event.get("update_id"),
            "bbo_receive_monotonic_ns": event.get("local_receive_monotonic_ns"),
            "bbo_receive_timestamp": event.get("local_receive_timestamp"),
            "connection_session_id": event.get("connection_session_id"),
            "reconnect_generation": event.get("reconnect_generation"),
        }

    def on_agg_trade(self, event: Mapping[str, Any]) -> list[dict[str, Any]]:
        closed = self.bars.update_agg_trade(event)
        # Closed bars must land in TF geometry before the next provisional eval,
        # otherwise prev_close/FT stay UNKNOWN forever and CONTEXT_START cannot fire.
        self._append_closed_bars(closed)
        emitted: list[dict[str, Any]] = []
        for tf in TIMEFRAMES:
            try:
                ev = self._evaluate_timeframe(tf, event)
                if ev is not None:
                    emitted.append(ev)
            except Exception as exc:  # noqa: BLE001 — keep service alive
                self.errors.append(f"{tf}:{type(exc).__name__}:{exc}")
                self.errors = self.errors[-50:]
        return emitted

    def _evaluate_timeframe(self, timeframe: str, trade: Mapping[str, Any]) -> Optional[dict[str, Any]]:
        bar = self.bars.bars.get(timeframe)
        if bar is None:
            return None
        geometry_history = self.geometry_by_tf.get(timeframe)
        if geometry_history is None:
            geometry_history = pd.DataFrame()
        geom = compute_geometry_fields(
            bar.open,
            bar.high_so_far,
            bar.low_so_far,
            bar.last,
            recent_spreads=list(geometry_history["spread"].tail(20))
            if len(geometry_history) and "spread" in geometry_history.columns
            else None,
        )
        structure = {
            "timestamp": bar.bar_open_timestamp,
            "open": bar.open,
            "high": bar.high_so_far,
            "low": bar.low_so_far,
            "close": bar.last,
            "volume": bar.volume_so_far,
            "delta": bar.delta,
            **geom,
        }
        loc = localize_bar(
            pd.Series(structure),
            is_closed=False,
            causal_cutoff_timestamp=bar.causal_cutoff_timestamp,
            causal_cutoff_monotonic_ns=bar.causal_cutoff_monotonic_ns,
        )
        response = evaluate_response_row(
            loc,
            structure_row=structure,
            geometry_row=geom,
            classification_row={"volume_class": "unknown"},
            reaction_row=None,
            localization_history=self.localization_history,
            geometry_history=geometry_history,
            reactions_history=self.reactions_history,
            causal_cutoff=bar.causal_cutoff_timestamp,
            live_v1=True,
            localization_join_status="EXACT_FRESH_MATCH",
        )
        prev_close = None
        if len(geometry_history) and "close" in geometry_history.columns:
            prev_close = float(geometry_history.iloc[-1]["close"])
        prior_auction = self.prior_auction_by_tf.get(timeframe) or "UNKNOWN"
        synth = synthesize_provisional_state(
            structure_row=structure,
            response_row=response,
            causal_cutoff=bar.causal_cutoff_timestamp,
            prev_close=prev_close,
            prior_auction_episode=prior_auction,
        )
        self.prior_auction_by_tf[timeframe] = str(synth.get("auction_episode") or "UNKNOWN")
        life = step_event_time_lifecycle(
            timeframe=timeframe,
            provisional_context=synth,
            timestamp=bar.causal_cutoff_timestamp or trade.get("local_receive_timestamp"),
            prev=self.lifecycle_prev[timeframe],
            active_started_at=(self.lifecycle_prev[timeframe] or {}).get("active_context_started_at")
            if self.lifecycle_prev[timeframe]
            else None,
        )
        transition = detect_context_transition(self.lifecycle_prev[timeframe], life)
        state = resolve_timeframe_state(
            timeframe=timeframe,
            evaluation_timestamp=bar.causal_cutoff_timestamp,
            sources=TimeframeSources(),
            allow_provisional=True,
            evaluation_mode="PROVISIONAL_INTRABAR",
            provisional_lifecycle=life,
            causal_cutoff_timestamp=bar.causal_cutoff_timestamp,
            causal_cutoff_monotonic_ns=bar.causal_cutoff_monotonic_ns,
            model_version=MODEL_VERSION,
        )
        self.last_eval[timeframe] = {
            "structure": structure,
            "localization": loc,
            "response": response,
            "synthesis": synth,
            "lifecycle": life,
            "state": state,
            "prev_close": prev_close,
            "geometry_history_rows": int(len(geometry_history)),
        }
        self.lifecycle_prev[timeframe] = life
        if transition is None:
            return None

        # Episode id: stable while directional active; new on START
        if transition["event_type"] == "CONTEXT_START":
            self._episode_seq += 1
            self._active_episode[timeframe] = f"{timeframe}:prov:{self._episode_seq}"
        episode_id = self._active_episode.get(timeframe) or f"{timeframe}:prov:0"
        if transition["event_type"] == "CONTEXT_END":
            self._active_episode.pop(timeframe, None)

        mono = int(bar.causal_cutoff_monotonic_ns or trade.get("local_receive_monotonic_ns") or 0)
        bbo_mono = self.bbo.get("bbo_receive_monotonic_ns")
        # Future BBO cannot attach: only if bbo_mono <= event mono
        if bbo_mono is not None and int(bbo_mono) > mono:
            bbo_fields = {
                "best_bid": None,
                "best_ask": None,
                "book_update_id": None,
                "bbo_receive_monotonic_ns": None,
                "bbo_age_ms": None,
            }
        else:
            age_ms = None
            if bbo_mono is not None:
                age_ms = max(0.0, (mono - int(bbo_mono)) / 1_000_000.0)
            bbo_fields = {
                "best_bid": self.bbo.get("best_bid"),
                "best_ask": self.bbo.get("best_ask"),
                "book_update_id": self.bbo.get("book_update_id"),
                "bbo_receive_monotonic_ns": bbo_mono,
                "bbo_age_ms": age_ms,
            }

        event_timestamp = str(bar.causal_cutoff_timestamp or trade.get("local_receive_timestamp"))
        event = self.journal.build_event(
            timeframe=timeframe,
            event_type=transition["event_type"],
            previous_context=transition["previous_context"],
            new_context=transition["new_context"],
            event_timestamp=event_timestamp,
            event_monotonic_ns=mono,
            context_event_price=str(trade.get("price")),
            last_trade_id=bar.last_trade_id,
            last_trade_timestamp=bar.last_trade_timestamp,
            connection_session_id=trade.get("connection_session_id") or self.bbo.get("connection_session_id"),
            reconnect_generation=trade.get("reconnect_generation")
            if trade.get("reconnect_generation") is not None
            else self.bbo.get("reconnect_generation"),
            causal_cutoff_timestamp=bar.causal_cutoff_timestamp,
            causal_cutoff_monotonic_ns=bar.causal_cutoff_monotonic_ns,
            model_version=MODEL_VERSION,
            lifecycle_episode_id=episode_id,
            evidence={"synthesis": synth.get("decision_evidence"), "lifecycle_phase": life.get("lifecycle_state")},
            decision_available_at=event_timestamp,
            context_origin_timestamp=event_timestamp,
            evaluation_mode="PROVISIONAL_INTRABAR",
            extra_metadata={
                "delivery_mode": "LIVE",
                "context_occurrence_timestamp": event_timestamp,
            },
            **bbo_fields,
        )
        if self.journal.append(event):
            self.event_counts[transition["event_type"]] = self.event_counts.get(transition["event_type"], 0) + 1
            self.last_context_event[timeframe] = event
            return event
        return None
