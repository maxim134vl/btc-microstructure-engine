"""Explicit environment attachment, with no epoch creation or source discovery.

The controller publishes commands; the separately locked paper process consumes
that bus. A synchronous TradingApplication is available for isolated acceptance.
No constructor here starts a service, market connection or background worker.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from btc_ml.trading.command_bus import CommandBus, CommandBusPaths
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.epoch import load_active_epoch
from btc_ml.trading.intrabar_paper.financial_authority_runtime import (
    activate, checked_path, configure_financial_authority, configure_isolated_financial_authority,
)
from btc_ml.trading.portfolio_risk import PortfolioRiskCoordinator
from btc_ml.trading.timeframe_manager import TimeframeManager, load_feed
from btc_ml.trading.timeframe_state_adapter import load_sources
from btc_ml.trend import ContextTrendIntegration


def configure_environment(repo_root: Path, *, config_path: Path | None = None,
                          environ: Mapping[str, str] | None = None, isolated_test_only: bool = False):
    """Validate the pinned descriptor BEFORE any engine/financial writer exists."""
    env = os.environ if environ is None else environ
    names = ('BTC_ML_FINANCIAL_ROOT', 'BTC_ML_FINANCIAL_DESCRIPTOR',
             'BTC_ML_FINANCIAL_DESCRIPTOR_SHA256')
    if any(not env.get(name) for name in names):
        raise RuntimeError('EXPLICIT_FINANCIAL_ENVIRONMENT_REQUIRED')
    root = checked_path(env[names[0]])
    if not root.is_dir():
        raise RuntimeError('EXISTING_FINANCIAL_EPOCH_ROOT_REQUIRED')
    if type(isolated_test_only) is not bool:raise RuntimeError('ISOLATION_MODE_TYPE_CONFLICT')
    register=configure_isolated_financial_authority if isolated_test_only else configure_financial_authority
    register(root, Path(env[names[1]]), env[names[2]])
    authority = activate(root)
    repo = checked_path(repo_root)
    configured_repo = checked_path(authority.config.get('repo_root',
        str(Path(authority.config['case_root']) / 'app')))
    if configured_repo != repo:
        raise RuntimeError('LAUNCHER_FINANCIAL_REPOSITORY_MISMATCH')
    observation = checked_path(authority.config['observation_config_path'], existing=True)
    if config_path is not None and checked_path(config_path, existing=True) != observation:
        raise RuntimeError('LAUNCHER_OBSERVATION_CONFIG_MISMATCH')
    cfg = load_intrabar_paper_config(observation, repo_root=repo)
    epoch = load_active_epoch(cfg.epochs_root)
    if epoch is None or epoch.epoch_status != 'ACTIVE':
        raise RuntimeError('EXISTING_ACTIVE_EPOCH_REQUIRED')
    if root != (cfg.books_root / epoch.paper_epoch_id).resolve():
        raise RuntimeError('LAUNCHER_FINANCIAL_EPOCH_MISMATCH')
    if cfg.real_execution_enabled or not cfg.paper_only:
        raise RuntimeError('REAL_EXECUTION_FORBIDDEN')
    if cfg.entry_source != 's41_command_bus':
        raise RuntimeError('UNIFIED_S41_ENTRY_SOURCE_REQUIRED')
    from btc_ml.runtime.paper_financial_policy import inspect_paper_financial_policy
    inspect_paper_financial_policy(cfg, epoch.paper_epoch_id, env)
    return cfg, epoch


def command_bus(repo_root: Path) -> CommandBus:
    from btc_ml.trading.command_bus import ROOT as source_repo
    production = CommandBusPaths.production()
    return CommandBus(CommandBusPaths(*(Path(repo_root) / getattr(production, key).relative_to(source_repo)
        for key in ('memory', 'latest', 'manager_state', 'portfolio_summary'))))


def load_own_inputs(repo_root: Path):
    root = Path(repo_root)
    import pandas as pd
    sources = load_sources(
        availability_path=root / 'data/cognition/multi_timeframe_availability_memory.parquet',
        lifecycle_path=root / 'data/cognition/market_context_lifecycle_memory.parquet',
        synthesis_path=root / 'data/cognition/multi_timeframe_synthesis.parquet',
    )
    life = sources.lifecycle
    # Final precedes lifecycle activation. Never offer a row with a missing own
    # Final dependency; keep independent TFs and the persisted history intact.
    if len(life) and 'timeframe' in life and 'timestamp' in life:
        keep = pd.Series(False, index=life.index)
        for tf in ('M15', 'M30', 'H1', 'H4'):
            prefix = '' if tf == 'M15' else f'timeframes/{tf}/'
            path = root / f'data/cognition/{prefix}final_market_context_memory.parquet'
            if not path.is_file():
                continue
            final = pd.read_parquet(path)
            if 'timestamp' not in final:
                continue
            if 'timeframe' in final:
                final = final.loc[final.timeframe == tf]
            elif tf != 'M15':
                continue
            own = life.timeframe.eq(tf)
            keep |= own & pd.to_datetime(life.timestamp, utc=True).isin(
                pd.to_datetime(final.timestamp, utc=True))
        sources.lifecycle = life.loc[keep].copy()
    else:
        # Shared unscoped history is not independent four-TF authority.
        sources.lifecycle = life.iloc[:0].copy()
    return sources, load_feed(root / 'data/live/live_market_feed.parquet')


def _same_implementation_bytes(recorded: Mapping[str, str], current: Mapping[str, str]) -> bool:
    """Authenticate an unchanged source set after repository relocation.

    Original absolute paths remain in immutable journal config and its hash.
    Never rewrite/repin that config. Only one complete module directory with
    exactly the current filenames and byte hashes can match; renamed/different
    modules, partial sets and mixed source directories are rejected.
    """
    def normalized(values):
        if not isinstance(values, dict) or not values:
            return None
        paths = [Path(key) for key in values]
        if any(not path.is_absolute() for path in paths):
            return None
        if len({path.parent for path in paths}) != 1:
            return None
        names = {path.name: values[str(path)] for path in paths}
        if len(names) != len(values):
            return None
        return names
    left, right = normalized(recorded), normalized(current)
    return left is not None and right is not None and left == right


def load_trend(environ: Mapping[str, str] | None = None, *, paper_bookkeeping: bool = False, paper_ingestion: bool = False) -> ContextTrendIntegration:
    """Read explicitly pinned existing REAL_CANDIDATE ledgers; never initialize.

    Missing ledgers remain COMMITTED_TREND_LINEAGE_UNAVAILABLE / NO_ENTRY, not a
    fabricated phase. Fixture authority cannot enter an authentic runtime path.
    """
    if paper_bookkeeping and paper_ingestion:
        raise RuntimeError("SEPARATE_PAPER_SOURCE_AND_BOOKKEEPING_ROLES_REQUIRED")
    env = os.environ if environ is None else environ
    path, pin = env.get('BTC_ML_TREND_DESCRIPTOR'), env.get('BTC_ML_TREND_DESCRIPTOR_SHA256')
    if path is None and pin is None:
        return ContextTrendIntegration()
    if not path or not pin:
        raise RuntimeError('EXPLICIT_TREND_DESCRIPTOR_REQUIRED')
    raw = checked_path(path, existing=True).read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise RuntimeError('TREND_DESCRIPTOR_PIN_CONFLICT')
    descriptor = json.loads(raw)
    if descriptor.get('schema') != 'existing_trend_sources_v1':
        raise RuntimeError('TREND_DESCRIPTOR_SCHEMA_CONFLICT')
    from btc_ml.trend.trend_journal import Journal, Blocked, digest
    from btc_ml.trend.trend_research_system import ResearchSystem, implementation_hashes
    from btc_ml.trend.trend_scope_sessions import verify

    class ReadOnlyJournal(Journal):
        @contextmanager
        def lock(self):
            self.load()
            yield self
        def append(self, *args, **kwargs):
            raise Blocked('RUNTIME_TREND_READ_ONLY')
        def stage(self, *args, **kwargs):
            raise Blocked('RUNTIME_TREND_READ_ONLY')

    class PaperBookkeepingJournal(ReadOnlyJournal):
        # The original journal/flock/validator is the sole owner. This role may
        # apply native R2 outcomes only; it cannot ingest or rewrite C_E.
        @contextmanager
        def lock(self):
            with Journal.lock(self):
                yield self
        def append(self, boundary, action, *args, **kwargs):
            if boundary != 'C_P' or action.get('kind') != 'R2_BOOKKEEPING':
                raise Blocked('PAPER_BOOKKEEPING_ROLE_ONLY')
            return Journal.append(self, boundary, action, *args, **kwargs)
        def stage(self, name, payload, fault):
            if fault is not None:
                raise Blocked('RUNTIME_TREND_FAULT_INJECTION_FORBIDDEN')

    class PaperSourceJournal(PaperBookkeepingJournal):
        # Same native writer lock and C_E/C_P validators. This producer may
        # ingest verified observations and drain native PROJECTs, never apply
        # execution outcomes (those belong to PaperBookkeepingJournal).
        def append(self, boundary, action, *args, **kwargs):
            if not ((boundary == 'C_E' and action.get('kind') in
                     {'RETAINED_CANARY_SOURCE', 'INGEST', 'DUPLICATE',
                      'SOURCE_CONFLICT', 'PREPARE_BRIDGE', 'WATERMARK'})
                    or (boundary == 'C_P' and action.get('kind') == 'PROJECT')):
                raise Blocked('PAPER_SOURCE_ROLE_ONLY')
            return Journal.append(self, boundary, action, *args, **kwargs)

    systems = {}
    for tf, source in descriptor['sources'].items():
        if tf not in ('M15', 'M30', 'H1', 'H4'):
            raise RuntimeError('TREND_OWN_TIMEFRAME_REQUIRED')
        ledger = checked_path(source['journal_root'])
        if not ledger.is_dir() or not (ledger / 'records/00000001.json').is_file():
            raise RuntimeError('EXISTING_TREND_HISTORY_REQUIRED')
        journal = object.__new__(ReadOnlyJournal)
        journal.path = ledger
        journal.state, journal.records = None, []
        state = journal.load()
        if state is None or journal.interrupted:
            raise RuntimeError('TREND_INTERRUPTED_OR_MISSING_HISTORY')
        if state['config'].get('mode') != 'REAL_CANDIDATE':
            raise RuntimeError('FIXTURE_TREND_AUTHORITY_FORBIDDEN')
        if digest(state['config']) != source['config_sha256']:
            raise RuntimeError('TREND_SOURCE_CONFIG_PIN_CONFLICT')
        if not _same_implementation_bytes(state['config'].get('implementation_sha'), implementation_hashes()):
            raise RuntimeError('TREND_IMPLEMENTATION_VERSION_MISMATCH')
        if paper_ingestion and not state['config'].get('paper_permission'):
            raise Blocked('PAPER_PERMISSION_REQUIRED')
        if (paper_bookkeeping or paper_ingestion) and state['config'].get('paper_permission'):
            from btc_ml.trend.real_scope_proof import paper_permission
            from datetime import datetime, timezone
            permission = paper_permission(state['config'], datetime.now(timezone.utc).isoformat())
            if permission['evidence_level'] != 'OBSERVED':
                raise Blocked('TEST_ONLY_PAPER_RUNTIME_FORBIDDEN')
            writer = object.__new__(PaperSourceJournal if paper_ingestion else PaperBookkeepingJournal)
            writer.path, writer.state, writer.records = ledger, None, []
            writer.device_path, writer.device = ledger, ledger.stat().st_dev
            writer.load()
            journal = writer
        system = object.__new__(ResearchSystem)
        system.j, system.authority = journal, None
        verify(system)
        systems[tf] = system
    return ContextTrendIntegration(systems)


def configured_manager(repo_root: Path, *, environ: Mapping[str, str] | None = None):
    cfg, _epoch = configure_environment(repo_root, environ=environ)
    manager = TimeframeManager(bus=command_bus(repo_root), books={},
        risk=PortfolioRiskCoordinator.load(Path(repo_root) / 'config/timeframe_trader_risk.json'),
        repo_root=Path(repo_root), trend_integration=load_trend(environ))
    # Keep the existing production anti-saw filter and its approved config.
    from btc_ml.trading.anti_saw_path_density import PathDensitySawFilter
    manager.saw_filter = PathDensitySawFilter(cfg.raw)
    if not manager._use_live1b_position_views(Path(repo_root)):
        raise RuntimeError('EXISTING_LIVE1B_POSITION_AUTHORITY_REQUIRED')
    return manager


def load_paper_trend(repo_root: Path, *, environ: Mapping[str, str] | None = None):
    """Optional explicit PAPER binding; Trend failure must not suppress CLOSE.

    Missing descriptor keeps the original consumer/default deny. A broken
    supplied descriptor returns an empty native binding, so OPEN fails closed
    while protective exits and Financial recovery remain available.
    """
    env = os.environ if environ is None else environ
    if not env.get('BTC_ML_TREND_DESCRIPTOR') and not env.get('BTC_ML_TREND_DESCRIPTOR_SHA256'):
        return None
    try:
        integration = load_trend(env, paper_bookkeeping=True)
        if not any(integration.paper_enabled(tf) for tf in ('M15','M30','H1','H4')):
            return None
        integration.attach_context_publication(repo_root)
        return integration
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
        import logging
        logging.getLogger(__name__).error('PAPER Trend binding unavailable; OPEN blocked, protective exits preserved: %s', exc)
        return ContextTrendIntegration()


def refresh_paper_sources(*, environ: Mapping[str, str] | None = None, cutoff: str):
    """Existing retained recorder -> native ingest_canary -> C_E/native PROJECT.

    Does not capture market data, create a journal/owner, grant trust, manufacture
    a descriptor, or issue commands. Missing explicit working bindings keep OPEN
    unavailable. The supplied cutoff is the manager's actual processing snapshot.
    """
    env = os.environ if environ is None else environ
    if not env.get('BTC_ML_TREND_DESCRIPTOR') and not env.get('BTC_ML_TREND_DESCRIPTOR_SHA256'):
        return {'status': 'WAITING', 'reason': 'EXPLICIT_TREND_DESCRIPTOR_REQUIRED', 'sources': []}
    integration = load_trend(env, paper_ingestion=True)
    from btc_ml.trend.real_scope_proof import read_retained_canary, trust_from_config, verify_paper_context_baseline
    from btc_ml.trend.trend_evidence import RawOccurrence
    results, seen = [], set()
    for tf, system in integration._systems.items():
        ledger = system.j.path.resolve()
        if ledger in seen: continue
        seen.add(ledger)
        state = system.state
        config = state['config']
        capture_id = config.get('paper_capture_id')
        if not capture_id:
            raise RuntimeError('PAPER_CONTEXT_OR_CAPTURE_BINDING_REQUIRED')
        capture = read_retained_canary(trust_from_config(config), capture_id=capture_id, cutoff=cutoff)
        # The configured initial predecessor/baseline are original retained
        # observations, not new DRA constituents. Validate their actual receipt
        # before excluding only that immutable pre-scope prefix.
        for own_tf in config['timeframes']:
            verify_paper_context_baseline(config, own_tf, cutoff)
        pending = []
        for delivery in capture['deliveries']:
            raw = RawOccurrence.from_dict(delivery['packet'])
            old = state['raw'].get(raw.trade.source_key)
            if old is None and config.get('predecessor') is not None and raw.trade.native_id <= config['predecessor']:
                continue
            if old is None or old['trade']['payload_sha'] != raw.trade.payload_sha:
                pending.append(delivery['delivery_id'])
        if pending:
            result = system.ingest_canary(capture_id, cutoff, delivery_ids=pending)
        else:
            # Still recover a native prepared PROJECT if a prior source call
            # stopped after C_E and before C_P. No duplicate raw events are sent.
            result = {'status': 'INPUT_UNCHANGED', 'r2_results': system.drain()}
        results.append({'timeframe': tf, 'journal': str(ledger), 'result': result})
    return {'status': 'CHECKED', 'sources': results}
