"""Tests for market context shadow chain orchestrator."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "research" / "build_market_context_shadow_chain.py"

spec = importlib.util.spec_from_file_location("build_market_context_shadow_chain", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["build_market_context_shadow_chain"] = mod
spec.loader.exec_module(mod)


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_chain_calls_steps_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    called: list[str] = []

    def fake_runner(cmd):
        called.append(Path(cmd[1]).name)

    # Point ROOT-derived paths into tmp and create minimal valid outputs after each "run".
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "STATUS_PATH", tmp_path / "data" / "cognition" / "market_context_shadow_chain_status.json")
    monkeypatch.setattr(mod, "PYTHON", Path(sys.executable))

    scripts = []
    outputs_by_step = []
    for step in mod.CHAIN_STEPS:
        script = tmp_path / "scripts" / step["script"].name
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("print('ok')\n", encoding="utf-8")
        scripts.append(script)
        outs = []
        for out in step["outputs"]:
            # rebuild relative under tmp
            rel = Path(*out.parts[-len(out.relative_to(ROOT).parts) :]) if False else None
            # Use original relative path from repo root
            try:
                rel_path = out.relative_to(ROOT)
            except ValueError:
                rel_path = Path(out.name)
            target = tmp_path / rel_path
            outs.append(target)
        outputs_by_step.append(outs)

    # Rebuild CHAIN_STEPS with tmp paths
    new_steps = []
    for step, script, outs in zip(mod.CHAIN_STEPS, scripts, outputs_by_step):
        new_steps.append({"name": step["name"], "script": script, "outputs": outs})
    monkeypatch.setattr(mod, "CHAIN_STEPS", new_steps)

    # Pre-create artifacts so inspect passes when skip is false but runner doesn't create files.
    # We'll create them inside a wrapper runner.
    def runner_with_artifacts(cmd):
        name = Path(cmd[1]).name
        called.append(name)
        # Find step and write dummy artifacts
        for step in new_steps:
            if step["script"].name == name:
                for out in step["outputs"]:
                    if out.suffix == ".parquet":
                        if "episodes" in out.name and "lifecycle" in out.name:
                            _write_parquet(
                                out,
                                [
                                    {
                                        "episode_id": 1,
                                        "active_market_context": "SHORT_CONTEXT",
                                        "start_time": pd.Timestamp("2026-07-10 01:00:00", tz="UTC"),
                                        "end_time": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                                        "bars_count": 10,
                                        "challenged_bars_count": 6,
                                        "action_allowed_any": False,
                                        "shadow_only": True,
                                    }
                                ],
                            )
                        elif "lifecycle_memory" in out.name:
                            _write_parquet(
                                out,
                                [
                                    {
                                        "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                                        "active_market_context": "SHORT_CONTEXT",
                                        "lifecycle_state": "CHALLENGED",
                                        "active_context_age_bars": 52,
                                        "action_allowed": False,
                                        "raw_market_context": "OBSERVE",
                                        "shadow_only": True,
                                    }
                                ],
                            )
                        elif "final_market_context_memory" in out.name:
                            _write_parquet(
                                out,
                                [
                                    {
                                        "timestamp": pd.Timestamp("2026-07-10 11:00:00", tz="UTC"),
                                        "market_context": "LONG_CONTEXT",
                                        "action_allowed": False,
                                        "shadow_only": True,
                                    },
                                    {
                                        "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                                        "market_context": "OBSERVE",
                                        "action_allowed": False,
                                        "shadow_only": True,
                                    },
                                    {
                                        "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                                        "market_context": "SHORT_CONTEXT",
                                        "action_allowed": False,
                                        "shadow_only": True,
                                    },
                                ],
                            )
                        else:
                            _write_parquet(
                                out,
                                [
                                    {
                                        "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                                        "shadow_only": True,
                                        "action_allowed": False,
                                    }
                                ],
                            )
                    else:
                        if out.name == "lifecycle_latest.json":
                            _write_json(
                                out,
                                {
                                    "timestamp": "2026-07-10T12:00:00Z",
                                    "active_market_context": "SHORT_CONTEXT",
                                    "lifecycle_state": "CHALLENGED",
                                    "active_context_age_bars": 52,
                                    "action_allowed": False,
                                    "open_episode_challenge_ratio": 0.6,
                                },
                            )
                        elif out.name == "lifecycle_candles.json":
                            _write_json(
                                out,
                                {
                                    "rows": [
                                        {
                                            "timestamp": "2026-07-10T12:00:00Z",
                                            "time": 1,
                                            "open": 1,
                                            "high": 1,
                                            "low": 1,
                                            "close": 1,
                                        }
                                    ]
                                },
                            )
                        else:
                            _write_json(
                                out,
                                [
                                    {
                                        "episode_id": 1,
                                        "context": "SHORT_CONTEXT",
                                        "start_time": "2026-07-10T01:00:00Z",
                                        "end_time": "2026-07-10T12:00:00Z",
                                    }
                                ],
                            )

    # Patch path lists used by validate_cross_checks
    cognition = tmp_path / "data" / "cognition"
    visual = tmp_path / "apps" / "context_visualizer" / "public" / "data"
    monkeypatch.setattr(
        mod,
        "SHADOW_PARQUET_LAYERS",
        [
            cognition / "auction_episode_memory.parquet",
            cognition / "cognitive_market_state_memory.parquet",
            cognition / "final_market_context_memory.parquet",
            cognition / "market_context_lifecycle_memory.parquet",
            cognition / "market_context_lifecycle_episodes.parquet",
        ],
    )
    monkeypatch.setattr(
        mod,
        "VISUAL_JSON_PATHS",
        [
            visual / "lifecycle_candles.json",
            visual / "lifecycle_context_episodes.json",
            visual / "lifecycle_latest.json",
        ],
    )

    # Also need raw episodes fewer check: write many raw episodes file OR rely on memory count.
    # Memory has 3 context changes -> raw count 3, lifecycle episodes 1 -> OK.
    # final_ts >= life_ts: both 12:00 OK.

    # Fix final memory timestamps so final >= lifecycle (equal)
    # Already equal at 12:00.

    result = mod.run_shadow_chain(runner=runner_with_artifacts)
    assert called == [
        "build_auction_episode_memory.py",
        "build_cognitive_market_state_memory.py",
        "build_final_market_context_memory.py",
        "build_market_context_lifecycle_memory.py",
        "extend_live_lifecycle_independent_timeframes.py",
        "generate_lifecycle_context_data.py",
    ]
    assert result.status == "PASS"


def test_missing_artifact_fails():
    missing = ROOT / "data" / "cognition" / "__missing_shadow_artifact__.parquet"
    with pytest.raises(mod.ChainError, match="missing artifact"):
        mod.inspect_artifact(missing)


def test_empty_artifact_fails(tmp_path: Path):
    path = tmp_path / "empty.parquet"
    _write_parquet(path, [])
    # empty dataframe still writes a file with 0 rows
    with pytest.raises(mod.ChainError, match="empty artifact"):
        mod.inspect_artifact(path)


def test_latest_lifecycle_matches_visual_latest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cognition = tmp_path / "data" / "cognition"
    visual = tmp_path / "apps" / "context_visualizer" / "public" / "data"
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(
        mod,
        "SHADOW_PARQUET_LAYERS",
        [
            cognition / "auction_episode_memory.parquet",
            cognition / "cognitive_market_state_memory.parquet",
            cognition / "final_market_context_memory.parquet",
            cognition / "market_context_lifecycle_memory.parquet",
            cognition / "market_context_lifecycle_episodes.parquet",
        ],
    )
    monkeypatch.setattr(
        mod,
        "VISUAL_JSON_PATHS",
        [
            visual / "lifecycle_candles.json",
            visual / "lifecycle_context_episodes.json",
            visual / "lifecycle_latest.json",
        ],
    )

    for name in [
        "auction_episode_memory.parquet",
        "cognitive_market_state_memory.parquet",
    ]:
        _write_parquet(
            cognition / name,
            [{"timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"), "shadow_only": True, "action_allowed": False}],
        )

    _write_parquet(
        cognition / "final_market_context_memory.parquet",
        [
            {"timestamp": pd.Timestamp("2026-07-10 10:00:00", tz="UTC"), "market_context": "LONG_CONTEXT", "action_allowed": False, "shadow_only": True},
            {"timestamp": pd.Timestamp("2026-07-10 11:00:00", tz="UTC"), "market_context": "OBSERVE", "action_allowed": False, "shadow_only": True},
            {"timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"), "market_context": "SHORT_CONTEXT", "action_allowed": False, "shadow_only": True},
        ],
    )
    _write_parquet(
        cognition / "market_context_lifecycle_memory.parquet",
        [
            {
                "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "CHALLENGED",
                "active_context_age_bars": 52,
                "action_allowed": False,
                "raw_market_context": "OBSERVE",
                "shadow_only": True,
            }
        ],
    )
    _write_parquet(
        cognition / "market_context_lifecycle_episodes.parquet",
        [
            {
                "episode_id": 1,
                "active_market_context": "SHORT_CONTEXT",
                "start_time": pd.Timestamp("2026-07-10 01:00:00", tz="UTC"),
                "end_time": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                "action_allowed_any": False,
                "shadow_only": True,
            }
        ],
    )
    _write_json(
        visual / "lifecycle_latest.json",
        {
            "timestamp": "2026-07-10T12:00:00Z",
            "active_market_context": "SHORT_CONTEXT",
            "lifecycle_state": "CHALLENGED",
            "active_context_age_bars": 52,
            "action_allowed": False,
            "open_episode_challenge_ratio": 0.75,
        },
    )
    _write_json(visual / "lifecycle_candles.json", {"rows": [{"timestamp": "2026-07-10T12:00:00Z"}]})
    _write_json(visual / "lifecycle_context_episodes.json", [{"episode_id": 1, "end_time": "2026-07-10T12:00:00Z"}])

    checks, latest, raw_count, life_count = mod.validate_cross_checks()
    assert checks["visual_latest_matches_lifecycle_memory"] is True
    assert latest["active_market_context"] == "SHORT_CONTEXT"
    assert latest["lifecycle_state"] == "CHALLENGED"
    assert latest["active_context_age_bars"] == 52
    assert latest["action_allowed"] is False
    assert life_count == 1
    assert raw_count >= 3


def test_failed_short_reprice_forbidden_in_outputs(tmp_path: Path):
    path = tmp_path / "bad.parquet"
    _write_parquet(
        path,
        [
            {
                "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                "reason": "FAILED_SHORT_REPRICE",
                "shadow_only": True,
            }
        ],
    )
    hits = mod._parquet_forbidden_hits(path)
    assert "FAILED_SHORT_REPRICE" in hits


def test_visual_json_forbids_arbitration_fields():
    payload = {"active_market_context": "SHORT_CONTEXT", "raw_chosen_context": "SHORT", "calibrated_context": "OBSERVE"}
    hits = mod._contains_forbidden(payload)
    assert "raw_chosen_context" in hits
    assert "calibrated_context" in hits


def test_action_allowed_must_remain_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cognition = tmp_path / "data" / "cognition"
    visual = tmp_path / "apps" / "context_visualizer" / "public" / "data"
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(
        mod,
        "SHADOW_PARQUET_LAYERS",
        [
            cognition / "auction_episode_memory.parquet",
            cognition / "cognitive_market_state_memory.parquet",
            cognition / "final_market_context_memory.parquet",
            cognition / "market_context_lifecycle_memory.parquet",
            cognition / "market_context_lifecycle_episodes.parquet",
        ],
    )
    monkeypatch.setattr(
        mod,
        "VISUAL_JSON_PATHS",
        [
            visual / "lifecycle_candles.json",
            visual / "lifecycle_context_episodes.json",
            visual / "lifecycle_latest.json",
        ],
    )

    for name in [
        "auction_episode_memory.parquet",
        "cognitive_market_state_memory.parquet",
    ]:
        _write_parquet(
            cognition / name,
            [{"timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"), "shadow_only": True, "action_allowed": False}],
        )
    _write_parquet(
        cognition / "final_market_context_memory.parquet",
        [
            {"timestamp": pd.Timestamp("2026-07-10 11:00:00", tz="UTC"), "market_context": "LONG_CONTEXT", "action_allowed": False, "shadow_only": True},
            {"timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"), "market_context": "SHORT_CONTEXT", "action_allowed": True, "shadow_only": True},
        ],
    )
    _write_parquet(
        cognition / "market_context_lifecycle_memory.parquet",
        [
            {
                "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "ACTIVE",
                "active_context_age_bars": 1,
                "action_allowed": False,
                "raw_market_context": "SHORT_CONTEXT",
                "shadow_only": True,
            }
        ],
    )
    _write_parquet(
        cognition / "market_context_lifecycle_episodes.parquet",
        [{"episode_id": 1, "active_market_context": "SHORT_CONTEXT", "start_time": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"), "end_time": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"), "action_allowed_any": False, "shadow_only": True}],
    )
    _write_json(
        visual / "lifecycle_latest.json",
        {
            "timestamp": "2026-07-10T12:00:00Z",
            "active_market_context": "SHORT_CONTEXT",
            "lifecycle_state": "ACTIVE",
            "active_context_age_bars": 1,
            "action_allowed": False,
        },
    )
    _write_json(visual / "lifecycle_candles.json", {"rows": [{"timestamp": "2026-07-10T12:00:00Z"}]})
    _write_json(visual / "lifecycle_context_episodes.json", [{"episode_id": 1, "end_time": "2026-07-10T12:00:00Z"}])

    with pytest.raises(mod.ChainError, match="action_allowed"):
        mod.validate_cross_checks()


def test_status_json_contains_required_fields(tmp_path: Path):
    result = mod.ChainResult(
        status="PASS",
        artifacts=[{"path": "x", "rows": 1}],
        latest_context={"active_market_context": "SHORT_CONTEXT"},
        raw_episodes_count=10,
        lifecycle_episodes_count=2,
        checks={"action_allowed_false": True},
        shadow_only=True,
    )
    path = mod.write_status(result, path=tmp_path / "status.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    for field in mod.REQUIRED_STATUS_FIELDS:
        assert field in payload
    assert payload["shadow_only"] is True
    assert payload["status"] == "PASS"


PRODUCTION_EROFS = (
    "step failed (generate_lifecycle_context_data.py): Traceback (most recent call last):\n"
    "  File \"/app/apps/context_visualizer/generate_lifecycle_context_data.py\", line 777, in main\n"
    "    write_json(CANDLES_OUT, {\"source\": \"live_market_feed\", \"rows\": candle_rows})\n"
    "OSError: [Errno 30] Read-only file system: "
    "'/app/apps/context_visualizer/public/data/lifecycle_candles.json.tmp'"
)


def _write_parquet_cognition(cognition: Path) -> None:
    ts = pd.Timestamp("2026-07-10 12:00:00", tz="UTC")
    for name in ("auction_episode_memory.parquet", "cognitive_market_state_memory.parquet"):
        _write_parquet(
            cognition / name,
            [{"timestamp": ts, "shadow_only": True, "action_allowed": False}],
        )
    _write_parquet(
        cognition / "final_market_context_memory.parquet",
        [
            {"timestamp": pd.Timestamp("2026-07-10 11:00:00", tz="UTC"), "market_context": "LONG_CONTEXT", "action_allowed": False, "shadow_only": True},
            {"timestamp": pd.Timestamp("2026-07-10 11:30:00", tz="UTC"), "market_context": "OBSERVE", "action_allowed": False, "shadow_only": True},
            {"timestamp": ts, "market_context": "SHORT_CONTEXT", "action_allowed": False, "shadow_only": True},
        ],
    )
    _write_parquet(
        cognition / "market_context_lifecycle_memory.parquet",
        [
            {
                "timestamp": ts,
                "active_market_context": "SHORT_CONTEXT",
                "lifecycle_state": "CHALLENGED",
                "active_context_age_bars": 52,
                "action_allowed": False,
                "raw_market_context": "OBSERVE",
                "shadow_only": True,
            }
        ],
    )
    _write_parquet(
        cognition / "market_context_lifecycle_episodes.parquet",
        [
            {
                "episode_id": 1,
                "active_market_context": "SHORT_CONTEXT",
                "start_time": pd.Timestamp("2026-07-10 01:00:00", tz="UTC"),
                "end_time": ts,
                "action_allowed_any": False,
                "shadow_only": True,
            }
        ],
    )


def _patch_tmp_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "STATUS_PATH", tmp_path / "data" / "cognition" / "market_context_shadow_chain_status.json")
    monkeypatch.setattr(mod, "PYTHON", Path(sys.executable))
    cognition = tmp_path / "data" / "cognition"
    visual = tmp_path / "apps" / "context_visualizer" / "public" / "data"
    monkeypatch.setattr(
        mod,
        "SHADOW_PARQUET_LAYERS",
        [
            cognition / "auction_episode_memory.parquet",
            cognition / "cognitive_market_state_memory.parquet",
            cognition / "final_market_context_memory.parquet",
            cognition / "market_context_lifecycle_memory.parquet",
            cognition / "market_context_lifecycle_episodes.parquet",
        ],
    )
    monkeypatch.setattr(
        mod,
        "VISUAL_JSON_PATHS",
        [
            visual / "lifecycle_candles.json",
            visual / "lifecycle_context_episodes.json",
            visual / "lifecycle_latest.json",
        ],
    )
    new_steps = []
    for step in mod.CHAIN_STEPS:
        script = tmp_path / "scripts" / step["script"].name
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("print('ok')\n", encoding="utf-8")
        outs = []
        for out in step["outputs"]:
            rel_path = out.relative_to(ROOT)
            outs.append(tmp_path / rel_path)
        new_steps.append({"name": step["name"], "script": script, "outputs": outs})
    monkeypatch.setattr(mod, "CHAIN_STEPS", new_steps)
    return new_steps


def _write_step_artifacts(step: dict) -> None:
    for out in step["outputs"]:
        if out.suffix == ".parquet":
            if "episodes" in out.name and "lifecycle" in out.name:
                _write_parquet(
                    out,
                    [
                        {
                            "episode_id": 1,
                            "active_market_context": "SHORT_CONTEXT",
                            "start_time": pd.Timestamp("2026-07-10 01:00:00", tz="UTC"),
                            "end_time": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                            "bars_count": 10,
                            "challenged_bars_count": 6,
                            "action_allowed_any": False,
                            "shadow_only": True,
                        }
                    ],
                )
            elif "lifecycle_memory" in out.name:
                _write_parquet(
                    out,
                    [
                        {
                            "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                            "active_market_context": "SHORT_CONTEXT",
                            "lifecycle_state": "CHALLENGED",
                            "active_context_age_bars": 52,
                            "action_allowed": False,
                            "raw_market_context": "OBSERVE",
                            "shadow_only": True,
                        }
                    ],
                )
            elif "final_market_context_memory" in out.name:
                _write_parquet(
                    out,
                    [
                        {
                            "timestamp": pd.Timestamp("2026-07-10 11:00:00", tz="UTC"),
                            "market_context": "LONG_CONTEXT",
                            "action_allowed": False,
                            "shadow_only": True,
                        },
                        {
                            "timestamp": pd.Timestamp("2026-07-10 11:30:00", tz="UTC"),
                            "market_context": "OBSERVE",
                            "action_allowed": False,
                            "shadow_only": True,
                        },
                        {
                            "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                            "market_context": "SHORT_CONTEXT",
                            "action_allowed": False,
                            "shadow_only": True,
                        },
                    ],
                )
            else:
                _write_parquet(
                    out,
                    [
                        {
                            "timestamp": pd.Timestamp("2026-07-10 12:00:00", tz="UTC"),
                            "shadow_only": True,
                            "action_allowed": False,
                        }
                    ],
                )
        elif out.name == "lifecycle_latest.json":
            _write_json(
                out,
                {
                    "timestamp": "2026-07-10T12:00:00Z",
                    "active_market_context": "SHORT_CONTEXT",
                    "lifecycle_state": "CHALLENGED",
                    "active_context_age_bars": 52,
                    "action_allowed": False,
                    "open_episode_challenge_ratio": 0.6,
                },
            )
        elif out.name == "lifecycle_candles.json":
            _write_json(out, {"rows": [{"timestamp": "2026-07-10T12:00:00Z", "open": 1, "high": 1, "low": 1, "close": 1}]})
        else:
            _write_json(
                out,
                [{"episode_id": 1, "context": "SHORT_CONTEXT", "start_time": "2026-07-10T01:00:00Z", "end_time": "2026-07-10T12:00:00Z"}],
            )


def test_readonly_visual_error_matches_vps_erofs():
    assert mod.is_readonly_visual_output_error(PRODUCTION_EROFS) is True
    assert mod.is_readonly_visual_output_error("[Errno 30] Read-only file system") is True
    assert mod.is_readonly_visual_output_error("step failed (generate_lifecycle_context_data.py): boom") is False
    assert mod.is_readonly_visual_output_error("Permission denied") is False


def test_readonly_visual_step_does_not_fail_parquet_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    new_steps = _patch_tmp_chain(tmp_path, monkeypatch)
    called: list[str] = []

    def runner(cmd):
        name = Path(cmd[1]).name
        called.append(name)
        if name == "generate_lifecycle_context_data.py":
            raise mod.ChainError(PRODUCTION_EROFS)
        for step in new_steps:
            if step["script"].name == name:
                _write_step_artifacts(step)

    result = mod.run_shadow_chain(runner=runner)
    assert called == [
        "build_auction_episode_memory.py",
        "build_cognitive_market_state_memory.py",
        "build_final_market_context_memory.py",
        "build_market_context_lifecycle_memory.py",
        "extend_live_lifecycle_independent_timeframes.py",
        "generate_lifecycle_context_data.py",
    ]
    assert result.status == "PASS"
    assert result.visual_data_skipped is True
    assert "[Errno 30]" in (result.visual_skip_reason or "")
    assert result.error is None
    parquet_paths = {item["path"] for item in result.artifacts}
    assert any("market_context_lifecycle_memory.parquet" in p for p in parquet_paths)
    assert not any(p.endswith(".json") for p in parquet_paths)
    payload = result.to_status_dict()
    assert payload["status"] == "PASS"
    assert payload["visual_data_skipped"] is True
    assert payload["shadow_only"] is True


def test_visual_step_non_erofs_failure_still_fails_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    new_steps = _patch_tmp_chain(tmp_path, monkeypatch)

    def runner(cmd):
        name = Path(cmd[1]).name
        if name == "generate_lifecycle_context_data.py":
            raise mod.ChainError("step failed (generate_lifecycle_context_data.py): boom")
        for step in new_steps:
            if step["script"].name == name:
                _write_step_artifacts(step)

    result = mod.run_shadow_chain(runner=runner)
    assert result.status == "FAIL"
    assert result.visual_data_skipped is False
    assert "boom" in (result.error or "")


def test_parquet_step_failure_still_fails_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_tmp_chain(tmp_path, monkeypatch)

    def runner(cmd):
        name = Path(cmd[1]).name
        if name == "build_market_context_lifecycle_memory.py":
            raise mod.ChainError("step failed (build_market_context_lifecycle_memory.py): parquet boom")
        for step in mod.CHAIN_STEPS:
            if step["script"].name == name:
                _write_step_artifacts(step)

    result = mod.run_shadow_chain(runner=runner)
    assert result.status == "FAIL"
    assert result.visual_data_skipped is False
    assert "parquet boom" in (result.error or "")


def test_validate_cross_checks_without_visual_keeps_parquet_guards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cognition = tmp_path / "data" / "cognition"
    _patch_tmp_chain(tmp_path, monkeypatch)
    _write_parquet_cognition(cognition)
    checks, latest, raw_count, life_count = mod.validate_cross_checks(require_visual=False)
    assert "visual_latest_matches_lifecycle_memory" not in checks
    assert checks["action_allowed_false"] is True
    assert checks["no_failed_short_reprice"] is True
    assert latest["active_market_context"] == "SHORT_CONTEXT"
    assert latest["challenge_ratio"] is None
    assert life_count == 1
    assert raw_count >= 3


def test_writable_visual_mismatch_still_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cognition = tmp_path / "data" / "cognition"
    visual = tmp_path / "apps" / "context_visualizer" / "public" / "data"
    _patch_tmp_chain(tmp_path, monkeypatch)
    _write_parquet_cognition(cognition)
    _write_json(
        visual / "lifecycle_latest.json",
        {
            "timestamp": "2026-07-10T12:00:00Z",
            "active_market_context": "LONG_CONTEXT",
            "lifecycle_state": "ACTIVE",
            "active_context_age_bars": 1,
            "action_allowed": False,
        },
    )
    _write_json(visual / "lifecycle_candles.json", {"rows": [{"timestamp": "2026-07-10T12:00:00Z"}]})
    _write_json(visual / "lifecycle_context_episodes.json", [{"episode_id": 1, "end_time": "2026-07-10T12:00:00Z"}])
    with pytest.raises(mod.ChainError, match="lifecycle visual latest mismatch"):
        mod.validate_cross_checks(require_visual=True)


def test_validate_cross_checks_uses_m15_when_higher_tf_shares_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cognition = tmp_path / "data" / "cognition"
    _patch_tmp_chain(tmp_path, monkeypatch)
    _write_parquet_cognition(cognition)
    life = pd.read_parquet(cognition / "market_context_lifecycle_memory.parquet")
    extra = life.iloc[[0]].copy()
    extra["timeframe"] = "H4"
    extra["active_market_context"] = "LONG_CONTEXT"
    extra["timestamp"] = pd.Timestamp("2026-07-10 16:00:00", tz="UTC")
    m15 = life.copy()
    m15["timeframe"] = "M15"
    mixed = pd.concat([m15, extra], ignore_index=True)
    mixed.to_parquet(cognition / "market_context_lifecycle_memory.parquet", index=False)
    ep = pd.read_parquet(cognition / "market_context_lifecycle_episodes.parquet")
    ep["timeframe"] = "M15"
    ep.to_parquet(cognition / "market_context_lifecycle_episodes.parquet", index=False)
    checks, latest, raw_count, life_count = mod.validate_cross_checks(require_visual=False)
    assert latest["active_market_context"] == "SHORT_CONTEXT"
    assert life_count == 1
    assert checks["action_allowed_false"] is True


def test_independent_tf_step_failure_still_fails_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_tmp_chain(tmp_path, monkeypatch)

    def runner(cmd):
        name = Path(cmd[1]).name
        if name == "extend_live_lifecycle_independent_timeframes.py":
            raise mod.ChainError("step failed (extend_live_lifecycle_independent_timeframes.py): extend boom")
        for step in mod.CHAIN_STEPS:
            if step["script"].name == name:
                _write_step_artifacts(step)

    result = mod.run_shadow_chain(runner=runner)
    assert result.status == "FAIL"
    assert result.visual_data_skipped is False
    assert "extend boom" in (result.error or "")

