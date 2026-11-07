"""Read-only container attachment validation before PID files or financial writers.

No descriptor discovery, ledger initialization, migration, or REAL authority.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from typing import Mapping
from btc_ml.runtime.financial_trend_environment import configure_environment, load_trend
from btc_ml.trading.intrabar_paper.financial_authority_runtime import activate, checked_path


def inspect_attachment(repo_root: Path, environ: Mapping[str, str] | None = None,
                       *, role: str = 'timeframe-manager', isolated_test_only: bool = False) -> dict:
    if role not in ('timeframe-manager', 'paper-manager'):
        raise RuntimeError('EXISTING_FINANCIAL_SERVICE_ROLE_REQUIRED')
    env = os.environ if environ is None else environ
    if not env.get('BTC_ML_FINANCIAL_ANCHOR'):
        raise RuntimeError('EXPLICIT_INDEPENDENT_ANCHOR_REQUIRED')
    anchor = checked_path(env['BTC_ML_FINANCIAL_ANCHOR'], existing=True)
    if role == 'timeframe-manager':
        cfg, epoch, financial_policy = configure_environment(repo_root, environ=env, isolated_test_only=isolated_test_only, cooperative_financial_preflight=True, return_financial_policy=True)
    else:
        cfg, epoch = configure_environment(repo_root, environ=env,isolated_test_only=isolated_test_only)
    authority = activate(Path(env['BTC_ML_FINANCIAL_ROOT']))
    if anchor != checked_path(authority.config['independent_anchor_path'], existing=True):
        raise RuntimeError('CONTAINER_ANCHOR_DESCRIPTOR_MISMATCH')
    from btc_ml.trading.intrabar_paper.execution_commit import verify_committed_head
    # Read-only native proof: path equality alone is not anchor authentication.
    if role == 'timeframe-manager' and financial_policy.get('verified_head_sha256'):
        import hashlib
        from btc_ml.trading.intrabar_paper import cold_forward_guard as cold, execution_commit as ec
        with cold.locked(__import__('btc_ml.trading.intrabar_paper.financial_authority_runtime',fromlist=['case_root']).case_root(), blocking=True) as lock:
            head_path=authority.root/'execution_commits_v1/head.json'
            pending=authority.root/'execution_commits_v1/pending.json'
            expected=financial_policy['verified_head_sha256']
            import fcntl
            while True:
                if pending.exists():raise RuntimeError('PAPER_FINANCIAL_RECOVERY_REQUIRED')
                if hashlib.sha256(head_path.read_bytes()).hexdigest()!=expected:
                    # The full proof, including every intermediate receipt and
                    # document, must reach the current head before accepting it.
                    verified_head=cold.verify_committed_head_cooperative(authority.root,epoch.paper_epoch_id,lock)
                    expected=hashlib.sha256(head_path.read_bytes()).hexdigest()
                    financial_policy['verified_head_sha256']=expected
                    financial_policy['verified_generation']=verified_head['publication']['generation']
                before=head_path.read_bytes();failure=None
                fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
                try:
                    try:verified_head=ec._verify_committed_head_raw(authority.root,epoch.paper_epoch_id)
                    except Exception as exc:failure=exc
                finally:fcntl.flock(lock.fileno(),fcntl.LOCK_SH)
                if pending.exists():raise RuntimeError('PAPER_FINANCIAL_RECOVERY_REQUIRED')
                after=head_path.read_bytes()
                if after!=before:continue
                if failure is not None:raise failure
                if hashlib.sha256(after).hexdigest()!=expected:continue
                break
    else:
        verified_head=verify_committed_head(authority.root,epoch.paper_epoch_id)
    # Paper consumes the controller envelope and revalidates OPEN admission.
    # Missing Trend must not stop its independent protective exit processor.
    trend = load_trend(env) if role == 'timeframe-manager' else None
    from btc_ml.runtime.paper_financial_policy import inspect_paper_financial_policy
    if role != 'timeframe-manager':
        financial_policy = inspect_paper_financial_policy(cfg, epoch.paper_epoch_id, env)
    return {'status': 'ATTACHMENT_VALIDATED_NOT_RUNTIME_ADMISSION',
            'epoch': epoch.paper_epoch_id, 'financial_root': str(authority.root),
            'anchor': str(anchor), 'entry_source': cfg.entry_source,
            'trend_sources': sorted(trend._systems) if trend is not None else None,
            'trend_reader_owner': 'timeframe-manager', 'service_role': role,
            'real_economic_authority': 'NOT_PROVEN',
            'entry_authorization': 'NOT_AUTHORIZED / POLICY_NOT_APPROVED',
            'isolated_test_only': isolated_test_only,
            'verified_generation': verified_head['publication']['generation'],
            'paper_financial_policy': financial_policy,
            'historical_independent_anchor': 'NOT_PROVEN'}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--role', choices=('timeframe-manager', 'paper-manager'), default='timeframe-manager')
    args = parser.parse_args()
    try:
        result = inspect_attachment(Path(os.environ.get('BTC_ML_REPO_ROOT', '/app')), role=args.role)
    except Exception as exc:
        print(json.dumps({'status': 'BLOCKED_BEFORE_WRITER', 'reason': str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
