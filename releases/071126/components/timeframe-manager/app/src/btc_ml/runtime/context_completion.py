"""Existing own-TF context publication after the unchanged analytical pipeline.

Opt-in launcher configuration, analytical writes only, same lock as the context
refresh daemon. This hook does not construct PAPER or emit trading commands.
"""
from pathlib import Path
import importlib.util
import os
import sys


def complete_contexts(repo_root: Path) -> dict:
    root = Path(repo_root).resolve()
    script = root / 'scripts/live/run_context_refresh_daemon.py'
    for directory in (root, root / 'src', root / 'scripts/live'):
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location('canonical_context_completion', script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    lock = root / 'data/runtime/context_refresh_daemon.lock'
    if not module.acquire_lock(lock, pid=os.getpid()):
        return {'result': 'SKIPPED', 'reason': 'CONTEXT_WRITER_ALREADY_ACTIVE'}
    try:
        return module.run_cycle(cycle_id='canonical-post-analysis')
    finally:
        module.release_lock(lock)
