"""Explicit application coordination of own cognition and financial execution.

Construction requires already configured real manager/consumer/engine objects.
No service, ledger, epoch, source producer or trading process is started here.
The canonical analytic pipeline keeps its original order and entry point.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.s41_command_consumer import S41CommandConsumer
from btc_ml.trading.timeframe_manager import TimeframeManager
from btc_ml.trading.timeframe_state_adapter import SUPPORTED_TIMEFRAMES, TimeframeSources
from btc_ml.trend import ContextTrendIntegration


class TradingApplication:
    """One explicit, synchronous application cycle; no background scheduling.

    The manager invokes ContextTrendIntegration on its own source states and
    persists original S4.1 decisions. Only afterward does the actual consumer
    inspect the same command bus and apply its original financial admission,
    quarantine, duplicate, CLOSE-before-OPEN and execution checks.
    """

    def __init__(
        self,
        *,
        manager: TimeframeManager,
        consumer: S41CommandConsumer,
        trend: ContextTrendIntegration | None = None,
    ) -> None:
        if not isinstance(manager, TimeframeManager):
            raise TypeError("ACTUAL_TIMEFRAME_MANAGER_REQUIRED")
        if not isinstance(consumer, S41CommandConsumer):
            raise TypeError("ACTUAL_S41_CONSUMER_REQUIRED")
        if not isinstance(consumer.engine, IntrabarPaperEngine):
            raise TypeError("ACTUAL_INTRABAR_FINANCIAL_ENGINE_REQUIRED")
        selected = manager.trend_integration if trend is None else trend
        if not isinstance(selected, ContextTrendIntegration):
            raise TypeError("ACTUAL_CONTEXT_TREND_INTEGRATION_REQUIRED")
        if selected is not manager.trend_integration:
            raise ValueError("MANAGER_TREND_SOURCE_MISMATCH")
        self.manager = manager
        self.consumer = consumer
        self.trend = selected
        self._epoch_id = str(consumer.engine.epoch.paper_epoch_id)
        self._engine = consumer.engine
        self._epoch_root = Path(consumer.engine.epoch_root).resolve()
        self._bus_identity = self._paths(manager.bus.paths)
        self._verify_attachment()

    @staticmethod
    def _paths(paths: Any) -> tuple[Path, ...]:
        return tuple(Path(getattr(paths, key)).resolve() for key in (
            "memory", "latest", "manager_state", "portfolio_summary"
        ))

    def _verify_attachment(self) -> None:
        """Fail closed on a different command store/engine/epoch, without writes."""
        if self._paths(self.manager.bus.paths) != self._bus_identity:
            raise ValueError("MANAGER_COMMAND_SOURCE_CHANGED")
        if self._paths(self.consumer.bus.paths) != self._bus_identity:
            raise ValueError("MANAGER_CONSUMER_COMMAND_SOURCE_MISMATCH")
        if self.consumer.engine is not self._engine:
            raise ValueError("FINANCIAL_ENGINE_CHANGED")
        engine = self._engine
        if str(engine.epoch.paper_epoch_id) != self._epoch_id:
            raise ValueError("FINANCIAL_EPOCH_CHANGED")
        if Path(engine.epoch_root).resolve() != self._epoch_root:
            raise ValueError("FINANCIAL_STATE_ROOT_CHANGED")
        if not self.manager._use_live1b_position_views(self.manager.repo_root):
            raise ValueError("LIVE1B_MANAGER_FINANCIAL_VIEW_REQUIRED")
        expected_root = (Path(self.manager.repo_root) /
                         "data/trading/intrabar_paper" / self._epoch_id).resolve()
        if expected_root != self._epoch_root:
            raise ValueError("MANAGER_ENGINE_FINANCIAL_ROOT_MISMATCH")
        if str(engine.books.paper_epoch_id) != self._epoch_id:
            raise ValueError("FINANCIAL_BOOK_EPOCH_MISMATCH")
        if not set(self.manager.timeframes).issubset(set(engine.cfg.timeframes)):
            raise ValueError("MANAGER_CONSUMER_OWN_TF_MISMATCH")
        if not set(self.manager.timeframes).issubset(set(SUPPORTED_TIMEFRAMES)):
            raise ValueError("UNSUPPORTED_MANAGER_TIMEFRAME")
        if self.manager.trend_integration is not self.trend:
            raise ValueError("MANAGER_TREND_SOURCE_CHANGED")

    @staticmethod
    def publish_cycle(manager: TimeframeManager, **arguments) -> dict:
        """Controller-only stage: original S4.1, Trend metadata and original bus."""
        if not isinstance(manager, TimeframeManager):
            raise TypeError("ACTUAL_TIMEFRAME_MANAGER_REQUIRED")
        if not manager._use_live1b_position_views(manager.repo_root):
            raise ValueError("LIVE1B_MANAGER_FINANCIAL_VIEW_REQUIRED")
        return manager.run_cycle(**arguments, persist=True)

    @staticmethod
    def consume_cycle(consumer: S41CommandConsumer, *, now: str | None = None) -> list:
        """Execution-only stage; native admission and protective exits are intact."""
        if not isinstance(consumer, S41CommandConsumer):
            raise TypeError("ACTUAL_S41_CONSUMER_REQUIRED")
        if not isinstance(consumer.engine, IntrabarPaperEngine):
            raise TypeError("ACTUAL_INTRABAR_FINANCIAL_ENGINE_REQUIRED")
        return consumer.poll(now=now)

    def run_cycle(
        self,
        *,
        evaluation_timestamp: Any,
        sources: TimeframeSources,
        feed: pd.DataFrame,
        activation_boundary: Any = None,
        decision_log_path: Path | None = None,
        decision_index: Mapping | None = None,
        now: Any = None,
        consumer_now: str | None = None,
    ) -> dict[str, Any]:
        """Consume supplied real upstream artifacts using existing application APIs.

        ``consumer_now=None`` preserves the native consumer wall clock. A caller
        may supply the existing explicit clock for an isolated historical fixture;
        exchange/source time is never invented as an original receive clock.
        """
        self._verify_attachment()
        if not isinstance(sources, TimeframeSources):
            raise TypeError("ACTUAL_OWN_TIMEFRAME_SOURCES_REQUIRED")
        if not isinstance(feed, pd.DataFrame):
            raise TypeError("ACTUAL_MARKET_FEED_FRAME_REQUIRED")
        result = self.publish_cycle(self.manager,
            evaluation_timestamp=evaluation_timestamp,
            sources=sources,
            feed=feed,
            activation_boundary=activation_boundary,
            decision_log_path=decision_log_path,
            decision_index=decision_index,
            now=now,
        )
        self._verify_attachment()
        actions = self.consume_cycle(self.consumer, now=consumer_now)
        return {
            "manager": result,
            "consumer_actions": actions,
            "paper_epoch_id": self._epoch_id,
        }

    def ingest_raw(self, timeframe: str, packet: Mapping[str, Any], cutoff: Any) -> dict:
        """Explicit original DRA source admission; no recorder or source synthesis."""
        return self.trend.ingest(timeframe, packet, cutoff)

    def bind_context(self, timeframe: str, proof: Mapping[str, Any], cutoff: Any) -> dict:
        return self.trend.bind_context(timeframe, proof, cutoff)

    def admit_scope(self, timeframe: str, request: Mapping[str, Any], cutoff: Any) -> dict:
        return self.trend.admit_scope(timeframe, request, cutoff)

    def watermark(self, timeframe: str, closed_at: Any, cutoff: Any, coverage_ref: str) -> dict:
        return self.trend.watermark(timeframe, closed_at, cutoff, coverage_ref)

    def drain_dra(self, timeframe: str) -> list:
        return self.trend.drain(timeframe)

    def bookkeeping(self, timeframe: str, request: Mapping[str, Any]) -> dict:
        return self.trend.bookkeeping(timeframe, request)
