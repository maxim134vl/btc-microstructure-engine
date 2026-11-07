"""S4.1 command-relay prototype contract (design constants only).

See docs/design/S41_COMMAND_RELAY_PROTOTYPE.md.

This package must not write production manager / LIVE1B paths.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

PROTOTYPE_ID = "S41_COMMAND_RELAY_V1"
PROTOTYPE_SCHEMA = "s41_command_relay_prototype_v1"

# Isolated research tree — never production manager paths.
PROTOTYPE_ROOT = ROOT / "data" / "research" / "s41_command_relay_prototype"
PROTOTYPE_COMMAND_MEMORY = PROTOTYPE_ROOT / "command_memory.parquet"
PROTOTYPE_MANAGER_STATE = PROTOTYPE_ROOT / "manager_state.json"
PROTOTYPE_LATEST = PROTOTYPE_ROOT / "manager_latest.json"
PROTOTYPE_PORTFOLIO = PROTOTYPE_ROOT / "portfolio_summary.json"
PROTOTYPE_BOOKS = PROTOTYPE_ROOT / "books"
PROTOTYPE_REPORTS = PROTOTYPE_ROOT / "reports"

# Forbidden write targets (assert in runners).
PRODUCTION_COMMAND_MEMORY = (
    ROOT / "data" / "trading" / "manager" / "timeframe_command_memory.parquet"
)
LIVE1B_EPOCHS_ROOT = ROOT / "data" / "trading" / "intrabar_paper"

VALID_INTENTS = ("OPEN_LONG", "OPEN_SHORT", "HOLD", "CLOSE", "NO_ACTION")
SUPPORTED_TIMEFRAMES = ("M15", "M30", "H1", "H4")

MODES = ("DRY_RUN", "SHADOW", "CANDIDATE_PAPER", "CUTOVER")

# Kinematic invariant (human-readable).
KINEMATICS = (
    "context/state @ TF clock → Manager intent → TimeframeTrader(TF) book"
)

FORBIDDEN = (
    "CONTEXT_* journal event must not directly open/close positions in this prototype",
    "no writes to production timeframe_command_memory",
    "no writes to LIVE1B epoch books",
    "execution_enabled must remain false",
)


def assert_not_production_target(path: Path) -> None:
    resolved = path.resolve()
    prod = PRODUCTION_COMMAND_MEMORY.resolve()
    live1b = LIVE1B_EPOCHS_ROOT.resolve()
    if resolved == prod or prod in resolved.parents:
        raise RuntimeError(f"{PROTOTYPE_ID} refused production command path: {path}")
    if live1b == resolved or live1b in resolved.parents:
        raise RuntimeError(f"{PROTOTYPE_ID} refused LIVE1B path: {path}")
