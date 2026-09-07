"""Targeted tests for LIVE1A/LIVE1B process supervision lifecycle."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from btc_ml.runtime.intrabar_supervision import (
    ALERT_COGNITION_PROCESS_DOWN,
    ALERT_MANAGER_PROCESS_DOWN,
    ALERT_PAPER_HEARTBEAT_STALE,
    ALERT_PAPER_RESTART_STORM,
    ProcessLifecycleState,
    RestartPolicy,
    ServiceSpec,
    ServiceRestartState,
    clear_stop_intent,
    evaluate_service,
    has_stop_intent,
    load_config,
    mark_controlled_restart,
    maybe_reset_stable_runtime,
    record_restart_attempt,
    restart_allowed,
    write_stop_intent,
)
from btc_ml.trading.intrabar_paper.config import load_intrabar_paper_config
from btc_ml.trading.intrabar_paper.engine import IntrabarPaperEngine
from btc_ml.trading.intrabar_paper.epoch import activate_epoch, create_epoch


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    src_cfg = Path(__file__).resolve().parents[2] / "config" / "intrabar_supervision.json"
    (root / "config" / "intrabar_supervision.json").write_text(src_cfg.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "run").mkdir(parents=True)
    (root / "data" / "runtime").mkdir(parents=True)
    return root


def _spec(repo: Path, name: str) -> ServiceSpec:
    return ServiceSpec.from_config(repo, name, load_config(repo))


def _write_health(path: Path, *, pid: int, updated_at: str | None = None, extra: dict | None = None) -> None:
    payload = {
        "pid": pid,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "alive": True,
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _fresh_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stale_ts() -> str:
    return "2020-01-01T00:00:00Z"


def _healthy_service(spec: ServiceSpec) -> int:
    pid = os.spawnv(os.P_NOWAIT, sys.executable, [sys.executable, "-c", "import time; time.sleep(120)"])
    spec.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    _write_health(spec.health_file, pid=pid)
    return pid


def _healthy_others(repo: Path, *names: str) -> list[int]:
    return [_healthy_service(_spec(repo, name)) for name in names]


def test_01_live1b_unexpected_death_restarts_same_epoch(repo: Path):
    from btc_ml.runtime.intrabar_supervision import IntrabarSupervisor

    spec = _spec(repo, "intrabar_paper_manager")
    others = _healthy_others(repo, "intrabar_cognition", "timeframe_manager")
    started: list[str] = []

    def start_fn(s: ServiceSpec) -> dict:
        started.append(s.name)
        pid = os.spawnv(os.P_NOWAIT, sys.executable, [sys.executable, "-c", "import time; time.sleep(60)"])
        spec.pid_file.write_text(f"{pid}\n", encoding="utf-8")
        _write_health(
            spec.health_file,
            pid=pid,
            extra={"paper_epoch_id": "PER_TF_EQUITY_1PCT_V1_20260802_155305"},
        )
        return {"ok": True}

    sup = IntrabarSupervisor.create(repo, start_fn=start_fn, stop_fn=lambda _s: {"ok": True})
    result = sup.supervise_once()
    assert started == ["intrabar_paper_manager"]
    svc = result["services"]["intrabar_paper_manager"]
    assert svc["paper_epoch_id"] == "PER_TF_EQUITY_1PCT_V1_20260802_155305"
    os.kill(others[0], signal.SIGTERM)
    os.kill(others[1], signal.SIGTERM)


def test_02_live1a_unexpected_death_restarts(repo: Path):
    from btc_ml.runtime.intrabar_supervision import IntrabarSupervisor

    spec = _spec(repo, "intrabar_cognition")
    others = _healthy_others(repo, "intrabar_paper_manager", "timeframe_manager")
    started: list[str] = []

    def start_fn(s: ServiceSpec) -> dict:
        started.append(s.name)
        pid = os.spawnv(os.P_NOWAIT, sys.executable, [sys.executable, "-c", "import time; time.sleep(60)"])
        spec.pid_file.write_text(f"{pid}\n", encoding="utf-8")
        _write_health(spec.health_file, pid=pid, extra={"service": "intrabar_cognition"})
        return {"ok": True}

    sup = IntrabarSupervisor.create(repo, start_fn=start_fn, stop_fn=lambda _s: {"ok": True})
    sup.supervise_once()
    assert started == ["intrabar_cognition"]
    os.kill(others[0], signal.SIGTERM)
    os.kill(others[1], signal.SIGTERM)


def test_03_intentional_paper_stop_not_restarted(repo: Path):
    from btc_ml.runtime.intrabar_supervision import IntrabarSupervisor

    spec = _spec(repo, "intrabar_paper_manager")
    others = _healthy_others(repo, "intrabar_cognition", "timeframe_manager")
    write_stop_intent(spec.stop_intent_file)
    started: list[str] = []

    def start_fn(s: ServiceSpec) -> dict:
        started.append(s.name)
        return {"ok": True}

    sup = IntrabarSupervisor.create(repo, start_fn=start_fn)
    snapshot = sup.supervise_once()
    assert started == []
    assert snapshot["services"]["intrabar_paper_manager"]["lifecycle_state"] == ProcessLifecycleState.STOPPED_EXPECTED.value
    os.kill(others[0], signal.SIGTERM)
    os.kill(others[1], signal.SIGTERM)


def test_04_intentional_cognition_stop_not_restarted(repo: Path):
    from btc_ml.runtime.intrabar_supervision import IntrabarSupervisor

    spec = _spec(repo, "intrabar_cognition")
    others = _healthy_others(repo, "intrabar_paper_manager", "timeframe_manager")
    write_stop_intent(spec.stop_intent_file)
    started: list[str] = []

    def start_fn(s: ServiceSpec) -> dict:
        started.append(s.name)
        return {"ok": True}

    sup = IntrabarSupervisor.create(repo, start_fn=start_fn)
    snapshot = sup.supervise_once()
    assert started == []
    assert snapshot["services"]["intrabar_cognition"]["lifecycle_state"] == ProcessLifecycleState.STOPPED_EXPECTED.value
    os.kill(others[0], signal.SIGTERM)
    os.kill(others[1], signal.SIGTERM)


def test_05_live1b_execution_degraded_does_not_restart(repo: Path):
    spec = _spec(repo, "intrabar_paper_manager")
    pid = os.getpid()
    spec.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    _write_health(
        spec.health_file,
        pid=pid,
        extra={
            "execution_market": {"state": {"state": "DEGRADED", "entry_allowed": False}},
        },
    )
    result = evaluate_service(spec, restart_entry=ServiceRestartState(), policy=RestartPolicy())
    assert result["lifecycle_state"] == ProcessLifecycleState.RUNNING_DEGRADED.value
    assert result["needs_restart"] is False


def test_05b_cognition_ws_opened_is_healthy(repo: Path):
    spec = _spec(repo, "intrabar_cognition")
    pid = os.getpid()
    spec.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    _write_health(
        spec.health_file,
        pid=pid,
        extra={
            "queue": {"enqueue_rejected": 0},
            "writer": {"write_errors": 0},
            "errors": ["ws:opened"],
        },
    )
    result = evaluate_service(spec, restart_entry=ServiceRestartState(), policy=RestartPolicy())
    assert result["lifecycle_state"] == ProcessLifecycleState.RUNNING_HEALTHY.value
    assert result["needs_restart"] is False


def test_05c_cognition_queue_reject_is_degraded(repo: Path):
    spec = _spec(repo, "intrabar_cognition")
    pid = os.getpid()
    spec.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    _write_health(
        spec.health_file,
        pid=pid,
        extra={
            "queue": {"enqueue_rejected": 3},
            "writer": {"write_errors": 0},
            "errors": ["ws:opened"],
        },
    )
    result = evaluate_service(spec, restart_entry=ServiceRestartState(), policy=RestartPolicy())
    assert result["lifecycle_state"] == ProcessLifecycleState.RUNNING_DEGRADED.value
    assert result["needs_restart"] is False


def test_06_live1b_execution_recovering_does_not_restart(repo: Path):
    spec = _spec(repo, "intrabar_paper_manager")
    pid = os.getpid()
    spec.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    _write_health(
        spec.health_file,
        pid=pid,
        extra={"execution_market": {"state": {"state": "RECOVERING"}}},
    )
    result = evaluate_service(spec, restart_entry=ServiceRestartState(), policy=RestartPolicy())
    assert result["lifecycle_state"] == ProcessLifecycleState.RUNNING_DEGRADED.value
    assert result["needs_restart"] is False


def test_07_stale_heartbeat_triggers_restart(repo: Path):
    from btc_ml.runtime.intrabar_supervision import IntrabarSupervisor

    spec = _spec(repo, "intrabar_paper_manager")
    others = _healthy_others(repo, "intrabar_cognition", "timeframe_manager")
    pid = os.spawnv(os.P_NOWAIT, sys.executable, [sys.executable, "-c", "import time; time.sleep(60)"])
    spec.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    _write_health(spec.health_file, pid=pid, updated_at=_stale_ts())
    restarted: list[str] = []

    def start_fn(s: ServiceSpec) -> dict:
        restarted.append(s.name)
        return {"ok": True}

    sup = IntrabarSupervisor.create(repo, start_fn=start_fn, stop_fn=lambda _s: {"ok": True})
    sup.supervise_once()
    assert restarted == ["intrabar_paper_manager"]
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    os.kill(others[0], signal.SIGTERM)
    os.kill(others[1], signal.SIGTERM)


def test_08_restart_storm_blocks_permanent(repo: Path):
    from btc_ml.runtime.intrabar_supervision import IntrabarSupervisor

    policy = RestartPolicy(max_attempts_in_window=2, window_seconds=600, min_delay_seconds=0)
    entry = ServiceRestartState()
    now = time.time()
    record_restart_attempt(entry, policy=policy, now=now, reason="crash")
    record_restart_attempt(entry, policy=policy, now=now + 1, reason="crash")
    allowed, reason, _ = restart_allowed(entry, policy=policy, now=now + 2)
    assert allowed is False
    assert reason == "RESTART_STORM_BLOCKED"

    spec = _spec(repo, "intrabar_paper_manager")
    result = evaluate_service(spec, restart_entry=entry, policy=policy)
    assert result["lifecycle_state"] == ProcessLifecycleState.FAILED_PERMANENT.value
    assert ALERT_PAPER_RESTART_STORM in result["alerts"]


def test_08b_foreign_fresh_health_does_not_start_second_paper_manager(repo: Path):
    spec = _spec(repo, "intrabar_paper_manager")
    _write_health(
        spec.health_file,
        pid=999999,
        extra={"execution_market": {"state": {"state": "HEALTHY"}}},
    )
    result = evaluate_service(spec, restart_entry=ServiceRestartState(), policy=RestartPolicy())
    assert result["needs_restart"] is False
    assert result["lifecycle_state"] == ProcessLifecycleState.RUNNING_HEALTHY.value
    assert "foreign" in str(result["detail"])


def test_08b_manager_down_uses_manager_alert(repo: Path):
    spec = _spec(repo, "timeframe_manager")
    result = evaluate_service(spec, restart_entry=ServiceRestartState(), policy=RestartPolicy())
    assert result["lifecycle_state"] == ProcessLifecycleState.FAILED.value
    assert ALERT_MANAGER_PROCESS_DOWN in result["alerts"]
    assert ALERT_COGNITION_PROCESS_DOWN not in result["alerts"]


def test_09_stable_runtime_resets_restart_penalty():
    policy = RestartPolicy(stable_runtime_reset_seconds=10)
    entry = ServiceRestartState(attempts=[time.time() - 5], stable_since_epoch=time.time() - 20)
    maybe_reset_stable_runtime(entry, policy=policy, now=time.time(), process_healthy=True)
    assert entry.attempts == []
    assert entry.blocked is False


def test_10_live1a_down_does_not_kill_live1b(repo: Path):
    from btc_ml.runtime.intrabar_supervision import IntrabarSupervisor

    paper_spec = _spec(repo, "intrabar_paper_manager")
    pid = os.getpid()
    paper_spec.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    _write_health(paper_spec.health_file, pid=pid, extra={"execution_market": {"state": {"state": "HEALTHY"}}})
    stopped: list[str] = []

    def stop_fn(s: ServiceSpec) -> dict:
        stopped.append(s.name)
        return {"ok": True}

    sup = IntrabarSupervisor.create(repo, stop_fn=stop_fn)
    snapshot = sup.evaluate_all()
    assert snapshot["services"]["intrabar_cognition"]["needs_restart"] is True
    assert snapshot["services"]["intrabar_paper_manager"]["needs_restart"] is False
    assert stopped == []


def test_11_live1b_down_does_not_kill_live1a(repo: Path):
    from btc_ml.runtime.intrabar_supervision import IntrabarSupervisor

    cog_spec = _spec(repo, "intrabar_cognition")
    pid = os.getpid()
    cog_spec.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    _write_health(cog_spec.health_file, pid=pid)
    stopped: list[str] = []

    def stop_fn(s: ServiceSpec) -> dict:
        stopped.append(s.name)
        return {"ok": True}

    sup = IntrabarSupervisor.create(repo, stop_fn=stop_fn)
    snapshot = sup.evaluate_all()
    assert snapshot["services"]["intrabar_paper_manager"]["needs_restart"] is True
    assert snapshot["services"]["intrabar_cognition"]["needs_restart"] is False
    assert stopped == []


def test_12_live1b_restart_preserves_epoch_positions_and_wal(repo: Path, tmp_path: Path):
    from btc_ml.runtime.intrabar_supervision import IntrabarSupervisor

    paper_repo = tmp_path / "paper_repo"
    (paper_repo / "config").mkdir(parents=True)
    cfg_src = Path(__file__).resolve().parents[2] / "config" / "intrabar_paper_execution.json"
    raw = json.loads(cfg_src.read_text(encoding="utf-8"))
    raw["books_root"] = "data/trading/intrabar_paper"
    raw["epochs_root"] = "data/trading/paper_epochs"
    raw["context_journal_root"] = "data/cognition/intrabar_context_events"
    (paper_repo / "config" / "intrabar_paper_execution.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    for rel in ("data/cognition/intrabar_context_events", "data/trading/intrabar_paper", "data/trading/paper_epochs"):
        (paper_repo / rel).mkdir(parents=True)
    cfg = load_intrabar_paper_config(repo_root=paper_repo)
    ep = activate_epoch(
        create_epoch(epochs_root=cfg.epochs_root, initial_equity_usd=cfg.initial_equity_usd, utc_stamp="SUPTEST"),
        epochs_root=cfg.epochs_root,
    )
    engine = IntrabarPaperEngine(cfg=cfg, epoch=ep, activation_monotonic_ns=1_000_000)
    epoch_id = ep.paper_epoch_id
    books = engine.books
    books.append(
        "positions",
        {
            "position_id": "pos_a8db850b3e484800",
            "timeframe": "H4",
            "status": "OPEN",
            "side": "LONG",
            "entry_price": 64452.34,
            "quantity": 1.0,
        },
    )
    books.append(
        "positions",
        {
            "position_id": "pos_ca1a44f61465480c",
            "timeframe": "M30",
            "status": "CLOSED",
            "exit_price": 64606.6674,
        },
    )
    wal_root = cfg.books_root / epoch_id / "execution_market_wal"
    wal_root.mkdir(parents=True)
    (wal_root / "events.jsonl").write_text(
        json.dumps({"wal_offset": 1, "event_type": "BOOK_TICKER"}) + "\n",
        encoding="utf-8",
    )
    (wal_root / "state.json").write_text(json.dumps({"last_offset": 1}) + "\n", encoding="utf-8")

    spec = _spec(repo, "intrabar_paper_manager")
    spec.health_file.parent.mkdir(parents=True, exist_ok=True)
    spec.pid_file.write_text("999999\n", encoding="utf-8")
    _write_health(
        spec.health_file,
        pid=999999,
        updated_at=_stale_ts(),
        extra={"paper_epoch_id": epoch_id},
    )

    def start_fn(_s: ServiceSpec) -> dict:
        return {"ok": True}

    sup = IntrabarSupervisor.create(repo, start_fn=start_fn, stop_fn=lambda _s: {"ok": True})
    sup.supervise_once()

    positions = [json.loads(line) for line in (books.root / "positions.jsonl").read_text().splitlines() if line.strip()]
    assert any(p["position_id"] == "pos_a8db850b3e484800" and p["status"] == "OPEN" for p in positions)
    assert any(p["position_id"] == "pos_ca1a44f61465480c" and p["exit_price"] == 64606.6674 for p in positions)
    assert (wal_root / "events.jsonl").exists()
    assert epoch_id.startswith("PER_TF_EQUITY") or epoch_id.endswith("SUPTEST")


def test_process_down_alert_codes(repo: Path):
    spec = _spec(repo, "intrabar_cognition")
    result = evaluate_service(spec, restart_entry=ServiceRestartState(), policy=RestartPolicy())
    assert result["lifecycle_state"] == ProcessLifecycleState.FAILED.value
    assert ALERT_COGNITION_PROCESS_DOWN in result["alerts"]

    spec2 = _spec(repo, "intrabar_paper_manager")
    pid = os.spawnv(os.P_NOWAIT, sys.executable, [sys.executable, "-c", "import time; time.sleep(30)"])
    spec2.pid_file.write_text(f"{pid}\n", encoding="utf-8")
    _write_health(spec2.health_file, pid=pid, updated_at=_stale_ts())
    result2 = evaluate_service(spec2, restart_entry=ServiceRestartState(), policy=RestartPolicy())
    assert ALERT_PAPER_HEARTBEAT_STALE in result2["alerts"]
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
