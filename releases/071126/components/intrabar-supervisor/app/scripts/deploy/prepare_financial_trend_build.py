#!/usr/bin/env python3
"""Prepare a bounded tracked-source context; no Docker, runtime data or secrets.

Committed source is read with git show, preserving unrelated dirty user files.
Only the explicit Docker integration additions are overlaid from this checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

OVERLAYS = (
    'src/btc_ml/runtime/container_preflight.py',
    'deploy/vps/entrypoints/financial_trend_service.sh',
    'deploy/vps/docker/financial-trend.Dockerfile',
    'scripts/deploy/prepare_financial_trend_build.py',
    'runtime_dependency_guard.py', 'runtime_dependency_map.py', 'runtime_state_manager.py',
    'src/btc_ml/runtime/pipeline.py', 'microstructure_candle_engine_v1.py',
    'candle_geometry_engine_v2.py', 'volume_localization_engine_v2.py',
    'auction_convergence_engine_v1.py', 'run.py',
    'storage/path_registry.py', 'legacy_source_inputs.py', 'volume_response_engine_v1.py',
    'stage2_cognition_runtime_v1.py', 'calibration_stability.py',
    'adaptive_meta_cognition_engine_v1.py',
    'behavioral_sequence_memory_v1.py', 'behavioral_volume_observer_v1.py',
    'scripts/live/run_context_refresh_daemon.py', 'src/btc_ml/runtime/context_completion.py',
    'deploy/vps/entrypoints/context_refresh_daemon.sh',
)


def runtime_member(name):
    p = Path(name)
    if any(part.startswith('.') or part in ('data', 'venv', 'node_modules') for part in p.parts):
        return False
    return (len(p.parts) == 1 and (p.suffix == '.py' or name in ('pyproject.toml', 'README_RUNTIME.md'))
        or name.startswith(('src/', 'scripts/', 'storage/', 'config/',
                            'deploy/vps/entrypoints/', 'deploy/vps/healthchecks/')))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.output.absolute()
    if out.exists() or out.is_relative_to(root):
        raise SystemExit('NEW_NON_REPOSITORY_CONTEXT_REQUIRED')
    if shutil.disk_usage(out.parent).free < 8 * 1024**3:
        raise SystemExit('BUILD_CONTEXT_FREE_RESERVE_8GIB_REQUIRED')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', revision], cwd=root, text=True).splitlines()
    blobs = {}
    for name in names:
        if runtime_member(name):
            blobs[name] = subprocess.check_output(['git', 'show', revision + ':' + name], cwd=root)
    for name in OVERLAYS:
        blobs[name] = (root / name).read_bytes()
    if sum(map(len, blobs.values())) > 128 * 1024**2:
        raise SystemExit('BUILD_CONTEXT_MAX_128MIB')
    out.mkdir()
    for name, raw in blobs.items():
        dest = out / 'app' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    (out / 'Dockerfile').write_bytes(blobs['deploy/vps/docker/financial-trend.Dockerfile'])
    manifest = {'revision': revision, 'mode': 'COMMITTED_SOURCE_PLUS_EXPLICIT_INTEGRATION_OVERLAYS',
                'logical_bytes': sum(map(len, blobs.values())),
                'files': {k: hashlib.sha256(v).hexdigest() for k, v in sorted(blobs.items())}}
    (out / 'app/SOURCE_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (out / '.dockerignore').write_text('**/__pycache__\n**/*.pyc\n')
    print(json.dumps({'context': str(out), 'revision': revision, 'files': len(blobs), 'bytes': manifest['logical_bytes']}))


if __name__ == '__main__':
    main()
