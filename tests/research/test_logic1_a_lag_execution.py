"""Step 2: A_LAG is execution, not a chase trainer. Holdout stays sealed."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_step2_config_forbids_chase_trainer_and_seals_holdout():
    cfg = json.loads((ROOT / "config/research/logic1_a_lag_execution.json").read_text(encoding="utf-8"))
    assert cfg["stage"] == 2
    assert cfg["holdout"] == "SEALED"
    forbidden = " ".join(cfg["forbidden"])
    assert "train_logic1_chase_optuna.py" in forbidden
    assert "train_hybrid_trade_sizing_catboost.py" in forbidden
    assert "Train a chase allow/block gate on the lagged Hybrid tick book" in cfg["what_we_do_not_do"]
    assert "do not wait one M15 bar to confirm an OPEN" in cfg["what_live_must_do"]
    assert not (ROOT / "scripts/research/train_logic1_chase_optuna.py").exists()


def test_production_execution_is_s41_hold0():
    live = json.loads((ROOT / "config/intrabar_paper_execution.json").read_text(encoding="utf-8"))
    assert live["entry_source"] == "s41_command_bus"
    src = (ROOT / "scripts/research/build_market_context_lifecycle_memory.py").read_text(encoding="utf-8")
    assert "MIN_ACTIVE_CONTEXT_HOLD_BARS = 0" in src
    tm = (ROOT / "src/btc_ml/trading/timeframe_manager.py").read_text(encoding="utf-8")
    assert "ANTI_SAW_ENABLED = False" in tm


def test_engine_does_not_import_catboost_for_a_lag():
    src = (ROOT / "src/btc_ml/trading/intrabar_paper/engine.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
    assert "catboost" not in imported
    assert "one-shot per episode" in src
    assert "do not re-open a chase" in src
