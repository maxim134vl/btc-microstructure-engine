"""S4.1 command-relay prototype package.

Design: docs/design/S41_COMMAND_RELAY_PROTOTYPE.md
"""

from .contract import (
    FORBIDDEN,
    KINEMATICS,
    MODES,
    PROTOTYPE_ID,
    PROTOTYPE_ROOT,
    VALID_INTENTS,
    assert_not_production_target,
)

__all__ = [
    "FORBIDDEN",
    "KINEMATICS",
    "MODES",
    "PROTOTYPE_ID",
    "PROTOTYPE_ROOT",
    "VALID_INTENTS",
    "assert_not_production_target",
]
