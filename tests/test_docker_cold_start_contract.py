import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_runtime():
    spec = importlib.util.spec_from_file_location("docker_model_runtime", ROOT / "scripts/docker/model_runtime.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProcess:
    pid = 4242

    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode


class FakeClock:
    def __init__(self, hook=None):
        self.now = 0.0
        self.hook = hook

    def monotonic(self):
        return self.now

    def sleep(self, _seconds):
        self.now += 10.0
        if self.hook:
            self.hook(self.now)


def configure_recovery(mod, tmp_path, monkeypatch, hook=None):
    health = tmp_path / "data/runtime/intrabar_paper_health.json"
    checkpoint = tmp_path / "checkpoint.json"
    health.parent.mkdir(parents=True)
    checkpoint.write_text(json.dumps({"last_processed_wal_offset": 0, "last_processed_agg_trade_id": 0}))
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "RUN", tmp_path / "run")
    monkeypatch.setattr(mod, "STATUS", tmp_path / "run/status.json")
    monkeypatch.setattr(mod, "STOP", False)
    monkeypatch.setattr(mod, "live1b_checkpoint_path", lambda: checkpoint)
    clock = FakeClock(hook)
    monkeypatch.setattr(mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(mod.time, "sleep", clock.sleep)
    return health, checkpoint, clock


def healthy_payload(pid=4242, **state_overrides):
    state = {
        "state": "HEALTHY", "unresolved_gap": False,
        "book_ticker_stream_fresh": True, "agg_trade_stream_fresh": True,
        "entry_allowed": True, "wal_write_failures": 0,
        **state_overrides,
    }
    return {
        "pid": pid, "updated_at": datetime.now(timezone.utc).isoformat(),
        "paper_only": True, "real_execution_enabled": False,
        "manager_status": "CONNECTED", "execution_market": {"state": state},
    }


def test_compose_cold_start_contract():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    services = compose["services"]
    assert {"model-runtime", "dashboard-api", "dashboard-ui", "context-refresher", "trade-chart"} <= set(services)
    assert services["dashboard-api"]["depends_on"]["model-runtime"]["condition"] == "service_healthy"
    assert services["dashboard-ui"]["depends_on"]["dashboard-api"]["condition"] == "service_healthy"
    env = services["model-runtime"]["environment"]
    assert env["PAPER_ONLY"] == "true"
    assert env["REAL_EXECUTION"] == "false"
    assert ".:/app" in services["model-runtime"]["volumes"]
    assert ".:/app:ro" in services["dashboard-api"]["volumes"]
    assert services["model-runtime"]["restart"] == "on-failure:3"
    assert services["model-runtime"]["mem_limit"] == "2g"
    assert services["model-runtime"]["memswap_limit"] == "2g"
    assert services["model-runtime"]["healthcheck"]["start_period"] == "3660s"


def test_context_refresher_uses_writable_run_for_runtime_artifacts():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    service = compose["services"]["context-refresher"]
    assert ".:/app:ro" in service["volumes"]
    assert "./run:/app/run" in service["volumes"]
    assert service["environment"] == {
        "CONTEXT_REFRESHER_PID_PATH": "/app/run/runtime_context_visual_refresher.pid",
        "CONTEXT_REFRESHER_LOCK_PATH": "/app/run/runtime_context_visual_refresher.lock",
    }

    source = (ROOT / "scripts/live/run_market_context_visual_refresher.py").read_text()
    assert 'os.environ.get("CONTEXT_REFRESHER_PID_PATH", ROOT / "runtime_context_visual_refresher.pid")' in source
    assert 'os.environ.get("CONTEXT_REFRESHER_LOCK_PATH", ROOT / "runtime_context_visual_refresher.lock")' in source


def test_runtime_contains_required_components_and_preserves_trading_state():
    source = (ROOT / "scripts/docker/model_runtime.py").read_text()
    for required in (
        "intrabar_feed_supervisor.py", "run.py", "run_intrabar_cognition_service.py",
        "run_intrabar_paper_manager.py", "intrabar_process_supervisor.py", "run_shadow_stp_be33.py",
    ):
        assert required in source
    assert "paper_epochs" not in source
    assert "execution_market_wal" not in source
    assert "intrabar_supervision_state.json" in source
    assert source.index("wait_stp_recovery(stp)") < source.index('log("model_runtime_ready"')


def test_stp_runner_polls_before_advertising_running_health():
    source = (ROOT / "scripts/live/run_shadow_stp_be33.py").read_text()
    assert source.index("initial = engine.poll_once()") < source.index('"STP_BE33_STARTED"')


def test_runtime_image_does_not_install_notebook_or_training_stack():
    requirements = (ROOT / "docker/requirements-runtime.txt").read_text().lower()
    for excluded in ("jupyter", "notebook", "streamlit", "torch", "xgboost"):
        assert excluded not in requirements


def test_start_wrapper_refuses_duplicate_host_runtime_and_checks_safety_flags():
    wrapper = (ROOT / "scripts/btc-ml-stack").read_text()
    assert "pgrep -f" in wrapper
    assert 'cfg.get("paper_only") is True' in wrapper
    assert 'cfg.get("real_execution_enabled") is False' in wrapper


def test_synthetic_long_recovery_over_180_seconds_progresses_then_ready(tmp_path, monkeypatch):
    mod = load_runtime()
    paths = {}

    def advance(now):
        checkpoint = paths["checkpoint"]
        checkpoint.write_text(json.dumps({
            "last_processed_wal_offset": int(now),
            "last_processed_agg_trade_id": int(now),
        }))
        if now >= 190:
            paths["health"].write_text(json.dumps(healthy_payload()))

    health, checkpoint, clock = configure_recovery(mod, tmp_path, monkeypatch, advance)
    paths.update(health=health, checkpoint=checkpoint)
    monkeypatch.setattr(mod, "LIVE1B_INITIAL_GRACE_S", 180)
    monkeypatch.setattr(mod, "LIVE1B_STALL_TIMEOUT_S", 30)
    monkeypatch.setattr(mod, "LIVE1B_HARD_TIMEOUT_S", 400)
    assert mod.wait_live1b_recovery(FakeProcess()) == (True, "healthy")
    assert clock.now >= 190
    assert json.loads(mod.STATUS.read_text())["component_state"]["live1b"] == "HEALTHY"


def test_stalled_recovery_fails_after_bounded_timeout(tmp_path, monkeypatch):
    mod = load_runtime()
    configure_recovery(mod, tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "LIVE1B_INITIAL_GRACE_S", 20)
    monkeypatch.setattr(mod, "LIVE1B_STALL_TIMEOUT_S", 20)
    monkeypatch.setattr(mod, "LIVE1B_HARD_TIMEOUT_S", 100)
    assert mod.wait_live1b_recovery(FakeProcess()) == (False, "recovery_stalled")


def test_live1b_crash_fails_closed(tmp_path, monkeypatch):
    mod = load_runtime()
    configure_recovery(mod, tmp_path, monkeypatch)
    assert mod.wait_live1b_recovery(FakeProcess(returncode=9)) == (False, "process_exited")


def test_corrupted_recovery_state_fails_closed(tmp_path, monkeypatch):
    mod = load_runtime()
    configure_recovery(mod, tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "live1b_checkpoint_path", lambda: (_ for _ in ()).throw(ValueError("corrupt")))
    assert mod.wait_live1b_recovery(FakeProcess()) == (False, "corrupted_recovery_state")


def test_live1b_safety_violations_fail_closed(tmp_path, monkeypatch):
    mod = load_runtime()
    health, _checkpoint, _clock = configure_recovery(mod, tmp_path, monkeypatch)
    payload = healthy_payload()
    payload["paper_only"] = False
    health.write_text(json.dumps(payload))
    assert mod.wait_live1b_recovery(FakeProcess()) == (False, "paper_only_not_true")
    payload = healthy_payload()
    payload["real_execution_enabled"] = True
    health.write_text(json.dumps(payload))
    assert mod.wait_live1b_recovery(FakeProcess()) == (False, "real_execution_enabled_not_false")
    payload = healthy_payload(wal_write_failures=1)
    health.write_text(json.dumps(payload))
    assert mod.wait_live1b_recovery(FakeProcess()) == (False, "wal_write_failure")


def test_normal_fast_startup_is_ready(tmp_path, monkeypatch):
    mod = load_runtime()
    health, _checkpoint, clock = configure_recovery(mod, tmp_path, monkeypatch)
    health.write_text(json.dumps(healthy_payload()))
    assert mod.wait_live1b_recovery(FakeProcess()) == (True, "healthy")
    assert clock.now == 0


def configure_stp(mod, tmp_path, monkeypatch, health_payload=None):
    epoch = "EPOCH"
    health = tmp_path / "data/trading/shadow_structural_protection/stp_be33/epochs" / epoch / "health.json"
    health.parent.mkdir(parents=True)
    (tmp_path / "data/trading/paper_epochs").mkdir(parents=True)
    (tmp_path / "data/trading/paper_epochs/active.json").write_text(json.dumps({"paper_epoch_id": epoch}))
    (tmp_path / "config").mkdir()
    (tmp_path / "config/intrabar_paper_execution.json").write_text(json.dumps({"epochs_root": "data/trading/paper_epochs"}))
    manifest = tmp_path / "data/trading/shadow_structural_protection/stp_be33/policy_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"policy_fingerprint": "FP"}))
    if health_payload is not None:
        health.write_text(json.dumps(health_payload))
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "RUN", tmp_path / "run")
    monkeypatch.setattr(mod, "STATUS", tmp_path / "run/status.json")
    monkeypatch.setattr(mod, "STOP", False)
    clock = FakeClock()
    monkeypatch.setattr(mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(mod.time, "sleep", clock.sleep)
    monkeypatch.setattr(mod, "STP_INITIAL_GRACE_S", 20)
    monkeypatch.setattr(mod, "STP_STALL_TIMEOUT_S", 20)
    monkeypatch.setattr(mod, "STP_HARD_TIMEOUT_S", 60)
    return health, clock


def stp_payload(pid=4242, **overrides):
    return {
        "pid": pid, "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "STP_BE33_RUNNING_SHADOW_ONLY", "paper_epoch_id": "EPOCH",
        "policy_fingerprint": "FP", "canonical_write_capability": False,
        "live1b_command_capability": False, "real_execution_capability": False,
        **overrides,
    }


def test_ready_cannot_be_emitted_before_stp_ready(tmp_path, monkeypatch):
    mod = load_runtime()
    _health, clock = configure_stp(mod, tmp_path, monkeypatch)
    assert mod.wait_stp_recovery(FakeProcess()) == (False, "stp_recovery_stalled")
    assert clock.now >= 20
    assert json.loads(mod.STATUS.read_text())["state"] == "STARTING"


def test_stale_precutover_stp_health_does_not_count(tmp_path, monkeypatch):
    mod = load_runtime()
    configure_stp(mod, tmp_path, monkeypatch, stp_payload(updated_at="2026-01-01T00:00:00Z"))
    assert mod.wait_stp_recovery(FakeProcess()) == (False, "stp_recovery_stalled")


def test_stp_current_pid_mismatch_fails_readiness(tmp_path, monkeypatch):
    mod = load_runtime()
    configure_stp(mod, tmp_path, monkeypatch, stp_payload(pid=9999))
    assert mod.wait_stp_recovery(FakeProcess()) == (False, "stp_recovery_stalled")


def test_stp_current_pid_and_binding_are_ready(tmp_path, monkeypatch):
    mod = load_runtime()
    _health, clock = configure_stp(mod, tmp_path, monkeypatch, stp_payload())
    assert mod.wait_stp_recovery(FakeProcess()) == (True, "healthy")
    assert clock.now == 0


def test_persisted_restart_storm_metadata_is_archived_without_touching_execution_state(tmp_path, monkeypatch):
    mod = load_runtime()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "RUN", tmp_path / "run")
    monkeypatch.setattr(mod, "BOOT", tmp_path / "run/docker_boot.json")
    monkeypatch.setattr(mod, "STATUS", tmp_path / "run/docker_model_runtime_status.json")
    supervision = tmp_path / "data/runtime/intrabar_supervision_state.json"
    execution = tmp_path / "data/trading/paper_epochs/active.json"
    positions = tmp_path / "data/trading/positions.jsonl"
    supervision.parent.mkdir(parents=True)
    execution.parent.mkdir(parents=True)
    positions.parent.mkdir(parents=True, exist_ok=True)
    supervision.write_text('{"block_reason":"RESTART_STORM_BLOCKED"}')
    execution.write_text('{"paper_epoch_id":"EPOCH"}')
    positions.write_text('{"status":"OPEN"}\n')
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (execution, positions)}
    mod.fresh_boot_state()
    assert not supervision.exists()
    assert list(supervision.parent.glob("intrabar_supervision_state.pre_docker_boot.*.json"))
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (execution, positions)}
