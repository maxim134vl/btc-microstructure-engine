from __future__ import annotations

import ast
import json
from pathlib import Path

from btc_ml.model_assurance.runtime_health import (
    mark_health_stopped,
)


def test_mark_health_stopped_persists_false(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path
        / "runtime"
        / "health.json"
    )
    path.parent.mkdir(
        parents=True
    )
    path.write_text(
        json.dumps(
            {
                "status":
                    "CURRENT",
                "alive":
                    True,
                "pid":
                    123,
                "paper_epoch_id":
                    "EPOCH",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = mark_health_stopped(
        health_path=path,
        pid=123,
    )

    persisted = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert result["alive"] is False
    assert persisted["alive"] is False
    assert persisted["pid"] == 123
    assert (
        persisted[
            "paper_epoch_id"
        ]
        == "EPOCH"
    )
    assert persisted["stopped_at"]
    assert (
        persisted["stop_reason"]
        == "PROCESS_EXIT"
    )


def test_old_process_cannot_overwrite_new_health(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path
        / "health.json"
    )
    original = {
        "status":
            "CURRENT",
        "alive":
            True,
        "pid":
            999,
        "updated_at":
            "2026-08-06T20:00:00Z",
    }
    path.write_text(
        json.dumps(original)
        + "\n",
        encoding="utf-8",
    )

    result = mark_health_stopped(
        health_path=path,
        pid=123,
    )

    persisted = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert result == original
    assert persisted == original
    assert persisted["alive"] is True
    assert persisted["pid"] == 999


def test_missing_health_gets_stopped_record(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path
        / "nested"
        / "health.json"
    )

    mark_health_stopped(
        health_path=path,
        pid=321,
        stop_reason="ONCE_COMPLETED",
    )

    persisted = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assert persisted["status"] == "STOPPED"
    assert persisted["alive"] is False
    assert persisted["pid"] == 321
    assert (
        persisted["stop_reason"]
        == "ONCE_COMPLETED"
    )


def test_every_runner_marks_health_stopped(
) -> None:
    root = Path(
        "/Users/fontecrypto/"
        "btc-ml-model-assurance-rollover"
    )
    runner_dir = (
        root
        / "scripts/model_assurance"
    )

    runners = sorted(
        runner_dir.glob(
            "run_*.py"
        )
    )

    assert len(runners) == 9

    missing = []

    for path in runners:
        source = path.read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)

        main = next(
            (
                node
                for node in tree.body
                if isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name == "main"
            ),
            None,
        )

        if main is None:
            missing.append(
                path.name
            )
            continue

        final_calls = []

        for node in ast.walk(main):
            if not (
                isinstance(
                    node,
                    ast.Try,
                )
                and node.finalbody
            ):
                continue

            for final_node in node.finalbody:
                for child in ast.walk(
                    final_node
                ):
                    if not isinstance(
                        child,
                        ast.Call,
                    ):
                        continue

                    function = child.func

                    if isinstance(
                        function,
                        ast.Name,
                    ):
                        final_calls.append(
                            function.id
                        )
                    elif isinstance(
                        function,
                        ast.Attribute,
                    ):
                        final_calls.append(
                            function.attr
                        )

        if (
            "mark_health_stopped"
            not in final_calls
        ):
            missing.append(
                path.name
            )

    assert missing == []
