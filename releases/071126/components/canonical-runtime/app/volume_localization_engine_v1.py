"""Root entrypoint shim for volume_localization_engine_v1 (Phase 4A candidate)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_MODULE_PATH = _ROOT / "src" / "btc_ml" / "cognition" / "volume_localization_engine_v1.py"
_SPEC = importlib.util.spec_from_file_location(
    "btc_ml_cognition_volume_localization_engine_v1",
    _MODULE_PATH,
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

# Re-export public API for tests / imports.
derive_rejection_flags = _MOD.derive_rejection_flags
localize_bar = _MOD.localize_bar
build_localization_frame = _MOD.build_localization_frame
resolve_localization_for_structure = _MOD.resolve_localization_for_structure
run = _MOD.run
ALGORITHM_VERSION = _MOD.ALGORITHM_VERSION
OUTPUT_PARQUET = _MOD.OUTPUT_PARQUET
SOURCE_PARQUET = _MOD.SOURCE_PARQUET

if __name__ == "__main__":
    code = run(write=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(code))
