#!/usr/bin/env python3
"""Persist S4.1 as LIVE1B entry_source on an existing data volume.

Patches overlay, manager activation hybrid, and the epoch S4.1 cursor floor.
Does not create or activate an epoch. Does not run bootstrap.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path


EPOCH_ID = "PER_TF_EQUITY_1PCT_V1_VPS_20260907_095442"
HYBRID_NOTE = (
    "S4.1 TimeframeManager is entry authority; LIVE1B books/BBO/TP/SL; "
    "journal observe-only"
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return payload


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _own_like(path: Path, *, uid: int, gid: int, mode: int) -> None:
    try:
        os.chown(path, uid, gid)
    except PermissionError:
        pass
    os.chmod(path, mode)


def persist(*, data_root: Path, consume_after: str, expected_epoch_id: str) -> dict:
    data_root = data_root.resolve()
    overlay_path = data_root / "deployment" / "intrabar_paper_execution.overlay.json"
    activation_path = data_root / "trading" / "manager" / "activation.json"
    active_path = data_root / "trading" / "paper_epochs" / "active.json"
    if not overlay_path.is_file():
        raise FileNotFoundError(f"missing overlay: {overlay_path}")
    if not activation_path.is_file():
        raise FileNotFoundError(f"missing activation: {activation_path}")
    if not active_path.is_file():
        raise FileNotFoundError(f"missing active epoch: {active_path}")

    overlay = _read_json(overlay_path)
    activation = _read_json(activation_path)
    active = _read_json(active_path)

    epoch_id = str(active.get("paper_epoch_id") or "")
    if epoch_id != expected_epoch_id:
        raise RuntimeError(f"refusing epoch_id={epoch_id!r} expected={expected_epoch_id!r}")
    if str(active.get("epoch_status") or "") != "ACTIVE":
        raise RuntimeError(f"refusing epoch_status={active.get('epoch_status')!r}")
    if overlay.get("paper_only") is not True:
        raise RuntimeError("overlay paper_only is not true")
    if overlay.get("real_execution_enabled") is not False:
        raise RuntimeError("overlay real_execution_enabled must be false")
    if active.get("paper_only") is not True or active.get("real_execution_enabled") is not False:
        raise RuntimeError("active epoch is not paper-only")

    cursor_path = (
        data_root / "trading" / "intrabar_paper" / epoch_id / "s41_command_cursor.json"
    )
    overlay_owner = overlay_path.stat()
    activation_owner = activation_path.stat()
    cursor_owner = cursor_path.stat() if cursor_path.is_file() else cursor_path.parent.stat()
    cursor = _read_json(cursor_path) if cursor_path.is_file() else {
        "processed_command_ids": [],
        "schema_version": "s41_live1b_command_cursor_v1",
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = data_root / "archive" / f"s41_persist_entry_source_{stamp}"
    archive.mkdir(parents=True, exist_ok=True)
    shutil.copy2(overlay_path, archive / "intrabar_paper_execution.overlay.json")
    shutil.copy2(activation_path, archive / "activation.json")
    shutil.copy2(active_path, archive / "active.json")
    if cursor_path.is_file():
        shutil.copy2(cursor_path, archive / "s41_command_cursor.json")

    overlay["entry_source"] = "s41_command_bus"
    overlay["s41_consume_commands_after"] = consume_after
    overlay["paper_only"] = True
    overlay["real_execution_enabled"] = False

    hybrid = dict(activation.get("hybrid") or {})
    hybrid.update(
        {
            "enabled": True,
            "position_source": hybrid.get("position_source") or "live1b_epoch_books",
            "entry_source": "s41_command_bus",
            "consume_commands_after": consume_after,
            "cutover_at": consume_after,
            "note": HYBRID_NOTE,
        }
    )
    activation["hybrid"] = hybrid
    activation["execution_owner"] = "LIVE1B_INTRABAR_PAPER"
    activation["paper_only"] = True
    activation["execution_enabled"] = False

    processed = [str(x) for x in (cursor.get("processed_command_ids") or []) if str(x).strip()]
    cursor = {
        "consume_after": consume_after,
        "processed_command_ids": processed,
        "schema_version": "s41_live1b_command_cursor_v1",
        "updated_at": consume_after,
    }

    _write_json(overlay_path, overlay)
    _write_json(activation_path, activation)
    _write_json(cursor_path, cursor)
    _own_like(
        overlay_path,
        uid=overlay_owner.st_uid,
        gid=overlay_owner.st_gid,
        mode=stat.S_IMODE(overlay_owner.st_mode) or 0o644,
    )
    _own_like(
        activation_path,
        uid=activation_owner.st_uid,
        gid=activation_owner.st_gid,
        mode=stat.S_IMODE(activation_owner.st_mode) or 0o644,
    )
    _own_like(
        cursor_path,
        uid=cursor_owner.st_uid,
        gid=cursor_owner.st_gid,
        mode=stat.S_IMODE(cursor_owner.st_mode) or 0o644,
    )

    report = {
        "status": "APPLIED",
        "epoch_id": epoch_id,
        "consume_after": consume_after,
        "archive": str(archive),
        "overlay_entry_source": overlay["entry_source"],
        "activation_entry_source": hybrid["entry_source"],
        "cursor_consume_after": cursor["consume_after"],
        "cursor_processed_n": len(processed),
        "created_or_activated_epoch": False,
        "paper_only": True,
        "real_execution_enabled": False,
    }
    (archive / "persist_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--consume-after", default=None)
    ap.add_argument("--expected-epoch-id", default=EPOCH_ID)
    args = ap.parse_args(argv)
    try:
        report = persist(
            data_root=args.data_root,
            consume_after=str(args.consume_after or _utc()),
            expected_epoch_id=str(args.expected_epoch_id),
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "FAILED", "error": f"{type(exc).__name__}:{exc}"}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
