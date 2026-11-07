from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "ops" / "s41_persist_volume_entry_source.py"
spec = importlib.util.spec_from_file_location("s41_persist_volume_entry_source", MODULE_PATH)
assert spec and spec.loader
_mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = _mod
spec.loader.exec_module(_mod)
persist = _mod.persist


def test_persist_patches_overlay_activation_cursor_without_new_epoch(tmp_path: Path):
    data = tmp_path / "data"
    epoch_id = "PER_TF_EQUITY_1PCT_V1_VPS_20260907_095442"
    overlay = data / "deployment" / "intrabar_paper_execution.overlay.json"
    activation = data / "trading" / "manager" / "activation.json"
    active = data / "trading" / "paper_epochs" / "active.json"
    cursor = data / "trading" / "intrabar_paper" / epoch_id / "s41_command_cursor.json"
    overlay.parent.mkdir(parents=True)
    activation.parent.mkdir(parents=True)
    active.parent.mkdir(parents=True)
    cursor.parent.mkdir(parents=True)
    overlay.write_text(
        json.dumps(
            {
                "entry_source": "context_journal",
                "s41_consume_commands_after": "2026-09-07T09:54:42.626102Z",
                "paper_only": True,
                "real_execution_enabled": False,
                "initial_equity_usd": 400000.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    activation.write_text(
        json.dumps(
            {
                "execution_owner": "LIVE1B_INTRABAR_PAPER",
                "paper_only": True,
                "execution_enabled": False,
                "hybrid": {
                    "enabled": True,
                    "entry_source": "context_journal",
                    "note": "S4.1 is not entry authority",
                    "position_source": "live1b_epoch_books",
                    "consume_commands_after": "2026-09-07T09:54:42.626102Z",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    active.write_text(
        json.dumps(
            {
                "paper_epoch_id": epoch_id,
                "epoch_status": "ACTIVE",
                "paper_only": True,
                "real_execution_enabled": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cursor.write_text(
        json.dumps(
            {
                "consume_after": "2026-09-07T09:54:42.626102Z",
                "processed_command_ids": ["TF_CMD_OLD"],
                "schema_version": "s41_live1b_command_cursor_v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = persist(
        data_root=data,
        consume_after="2026-09-11T22:30:00Z",
        expected_epoch_id=epoch_id,
    )
    assert report["created_or_activated_epoch"] is False
    assert report["epoch_id"] == epoch_id
    assert json.loads(overlay.read_text())["entry_source"] == "s41_command_bus"
    assert json.loads(overlay.read_text())["s41_consume_commands_after"] == "2026-09-11T22:30:00Z"
    assert json.loads(activation.read_text())["hybrid"]["entry_source"] == "s41_command_bus"
    assert "S4.1 is not entry authority" not in json.loads(activation.read_text())["hybrid"]["note"]
    stored = json.loads(cursor.read_text())
    assert stored["consume_after"] == "2026-09-11T22:30:00Z"
    assert stored["processed_command_ids"] == ["TF_CMD_OLD"]
    assert json.loads(active.read_text())["paper_epoch_id"] == epoch_id
    assert json.loads(active.read_text())["epoch_status"] == "ACTIVE"


def test_persist_refuses_wrong_epoch(tmp_path: Path):
    data = tmp_path / "data"
    overlay = data / "deployment" / "intrabar_paper_execution.overlay.json"
    activation = data / "trading" / "manager" / "activation.json"
    active = data / "trading" / "paper_epochs" / "active.json"
    overlay.parent.mkdir(parents=True)
    activation.parent.mkdir(parents=True)
    active.parent.mkdir(parents=True)
    overlay.write_text(
        json.dumps({"entry_source": "context_journal", "paper_only": True, "real_execution_enabled": False})
        + "\n",
        encoding="utf-8",
    )
    activation.write_text(json.dumps({"hybrid": {}}) + "\n", encoding="utf-8")
    active.write_text(
        json.dumps(
            {
                "paper_epoch_id": "OTHER_EPOCH",
                "epoch_status": "ACTIVE",
                "paper_only": True,
                "real_execution_enabled": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        persist(data_root=data, consume_after="2026-09-11T22:30:00Z", expected_epoch_id="PER_TF_EQUITY_1PCT_V1_VPS_20260907_095442")
    except RuntimeError as exc:
        assert "refusing epoch_id" in str(exc)
    else:
        raise AssertionError("expected refusal")
    assert json.loads(overlay.read_text())["entry_source"] == "context_journal"


def test_first_s41_consume_after_raises_stale_cursor_floor(tmp_path: Path):
    import importlib.util

    path = ROOT / "scripts" / "live" / "run_intrabar_paper_manager.py"
    spec = importlib.util.spec_from_file_location("run_intrabar_paper_manager", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cursor = tmp_path / "s41_command_cursor.json"
    cursor.write_text(
        json.dumps({"consume_after": "2026-09-07T09:54:42.626102Z", "processed_command_ids": []})
        + "\n",
        encoding="utf-8",
    )
    assert (
        mod._first_s41_consume_after("2026-09-11T22:36:35Z", cursor) == "2026-09-11T22:36:35Z"
    )
    missing = tmp_path / "missing_cursor.json"
    bumped = mod._first_s41_consume_after("2026-09-07T09:54:42.626102Z", missing)
    assert bumped >= "2026-09-11"
