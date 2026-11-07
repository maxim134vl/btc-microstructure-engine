"""PAPER current-snapshot financial admission, never strategy or REAL permission.

FMIN06 owner authority is separate from immutable FMIN04 metadata permission.
No books constructor, recovery, discovery, financial write or historical claim.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from typing import Mapping

from btc_ml.trading.intrabar_paper import financial_authority_runtime as runtime


def _require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def inspect_paper_financial_policy(cfg, epoch: str, environ: Mapping[str, str], *, cooperative: bool = False) -> dict:
    names = ('BTC_ML_PAPER_FINANCIAL_POLICY', 'BTC_ML_PAPER_FINANCIAL_POLICY_SHA256')
    supplied = [environ.get(key) for key in names]
    if not any(supplied):
        return {'status': 'NOT_CONFIGURED', 'historical_independent_anchor': 'NOT_PROVEN',
                'real_execution_allowed': False, 'strategy_entry_granted': False}
    _require(all(supplied), 'EXPLICIT_PAPER_FINANCIAL_POLICY_PIN_REQUIRED')
    _require(cfg.paper_only and not cfg.real_execution_enabled, 'REAL_EXECUTION_FORBIDDEN')
    auth = runtime.authority()
    _require(not getattr(auth, 'isolated_test_only', False), 'PAPER_POLICY_RESEARCH_AUTHORITY_FORBIDDEN')
    _require(auth.config.get('working_qualification_only') is False,
             'PAPER_POLICY_OWNER_AUTHORITY_REQUIRED')
    path = runtime.checked_path(supplied[0], existing=True)
    _require(not path.is_relative_to(auth.root), 'INDEPENDENT_PAPER_POLICY_REQUIRED')
    _require(os.statvfs(path).f_flag & os.ST_RDONLY, 'PAPER_POLICY_READONLY_MOUNT_REQUIRED')
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == supplied[1], 'PAPER_POLICY_PIN_CONFLICT')
    policy = runtime.read_json(raw)
    _require(policy.get('schema') == 'owner_paper_current_snapshot_policy_v1', 'PAPER_POLICY_SCHEMA')
    _require(policy.get('mode') == 'PAPER' and policy.get('real_execution_allowed') is False
             and policy.get('strategy_entry_granted') is False
             and policy.get('runtime_activation_granted') is False, 'PAPER_POLICY_SCOPE_CONFLICT')
    _require(policy.get('historical_independent_anchor') == 'NOT_PROVEN'
             and policy.get('historical_attestation_granted') is False, 'PAPER_POLICY_FALSE_HISTORICAL_CLAIM')
    _require(policy.get('epoch') == epoch == auth.config['epoch'], 'PAPER_POLICY_EPOCH_CONFLICT')
    _require(policy.get('financial_root') == str(auth.root), 'PAPER_POLICY_ROOT_CONFLICT')
    _require(policy.get('financial_descriptor_sha256') == auth.config_sha256,
             'PAPER_POLICY_DESCRIPTOR_CONFLICT')
    _require(auth.config['bootstrap_authorized'] is False, 'PAPER_POLICY_BOOTSTRAP_FORBIDDEN')
    approval = runtime.checked_path(policy['owner_source_path'], existing=True)
    _require(not approval.is_relative_to(auth.root)
             and os.statvfs(approval).f_flag & os.ST_RDONLY, 'PAPER_OWNER_SOURCE_NOT_INDEPENDENT_READONLY')
    _require(hashlib.sha256(approval.read_bytes()).hexdigest() == policy['owner_source_sha256'],
             'PAPER_OWNER_SOURCE_PIN_CONFLICT')
    from btc_ml.trading.intrabar_paper import cold_forward_guard as cold
    from btc_ml.trading.intrabar_paper import unified_financial_authority as unified
    from btc_ml.trading.intrabar_paper.execution_commit import verify_committed_head
    if cooperative:
        # Load the exact native verifier modules before acquiring the reader lock.
        from btc_ml.trading.intrabar_paper.cursor_ack import GuardExtension
    with cold.locked(runtime.case_root()) as shared_lock:
        _require(not (auth.root/'execution_commits_v1/pending.json').exists(),
                 'PAPER_FINANCIAL_RECOVERY_REQUIRED')
        boundary = auth.root/'execution_commits_v1/publications/1.json'
        _require(hashlib.sha256(boundary.read_bytes()).hexdigest() == policy['boundary_receipt_sha256'],
                 'PAPER_POLICY_BOUNDARY_CONFLICT')
        if cooperative:
            head=cold.verify_committed_head_cooperative(auth.root,epoch,shared_lock)
            baseline=(auth.root/'execution_commits_v1/head.json').read_bytes()
        else:
            head = verify_committed_head(auth.root, epoch)
            # Same SH ownership as the successful native full verification.
            baseline=(auth.root/'execution_commits_v1/head.json').read_bytes()
    result = {'status': 'PAPER_FINANCIAL_BASE_ADMITTED',
            'policy_sha256': supplied[1], 'verified_generation': head['publication']['generation'],
            'historical_independent_anchor': 'NOT_PROVEN',
            'historical_attestation_granted': False, 'real_execution_allowed': False,
            'strategy_entry_granted': False, 'runtime_activation_granted': False}
    result['verified_head_sha256']=hashlib.sha256(baseline).hexdigest()
    return result
