"""Isolated, pinned legacy-snapshot admission. Never starts an engine or trades.

This prototype publishes one CURRENT metadata admission, not historical v3 fills.
Final65 validators and materializer are imported byte-for-byte from research copies.
"""
from __future__ import annotations
import contextlib
import datetime as dt
from decimal import Decimal
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import types

sys.dont_write_bytecode = True
from . import financial_authority_runtime as runtime
PACKAGE = '_legacy_admission_exact_final65'
TABLES = ('signals', 'commands', 'orders', 'fills', 'trades', 'positions', 'equity_snapshots', 'metrics', 'blocked')
AUTH_NAMES = ('pending.json', 'head.json', 'currentness.json', 'history.mmr', 'publication.witness', 'publications')
RESERVE = 20 * 1024**3

class AdmissionBlocked(RuntimeError):
    pass

def require(ok, code):
    if not ok:
        raise AdmissionBlocked(code)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def unique_object(pairs):
    value = {}
    for k, v in pairs:
        require(k not in value, 'DUPLICATE_JSON_KEY')
        value[k] = v
    return value

def read_json(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique_object)

def money(value):
    require(not isinstance(value, bool), 'INVALID_FINANCIAL_NUMBER')
    n = Decimal(str(value))
    require(n.is_finite(), 'INVALID_FINANCIAL_NUMBER')
    return n

def near(a, b):
    # Reconcile retained float decimal encodings, not execution-price recomputation.
    return abs(money(a) - money(b)) <= Decimal('0.00000001')

def load_policy(path=None):
    path = Path(path) if path is not None else Path(runtime.authority().config["policy_path"])
    require(sha(Path(path).read_bytes()) == runtime.policy_sha(), 'UNTRUSTED_POLICY')
    p = read_json(path)
    require(p['mode'] == 'ISOLATED_ONLY' and p['trading_activation_authorized'] is False, 'NO_ACTIVATION_AUTHORITY')
    require(sha(json.dumps(p['state_members'], sort_keys=True).encode()) == p['state_members_sha256'], 'POLICY_MEMBERS_CONFLICT')
    for name, digest in p['reference_sha256'].items():
        require(sha((runtime.reference_source_root()/name).read_bytes()) == digest, 'FINAL65_REFERENCE_SOURCE_DRIFT')
    return p

def reference():
    load_policy()
    from . import execution_commit as ec, financial_history as fh, books as bm
    data=dict(vars(ec));data['verify_committed_head']=ec._verify_committed_head_raw
    return types.SimpleNamespace(**data),fh,bm

def guard_case(case):
    case = Path(case)
    require(case.resolve() == runtime.case_root(), 'FINANCIAL_CASE_IDENTITY_CONFLICT')
    for item in load_policy()['state_members']:runtime.member_path(case,item['path'])
    require(shutil.disk_usage(case).free > RESERVE, 'SSD_RESERVE_EXHAUSTED')
    return case.resolve()

def roots(case, policy):
    data = runtime.repo_root()/'data/trading' if Path(case).resolve()==runtime.case_root() else case/'app/data/trading'
    return data, data/'intrabar_paper'/policy['epoch']

def pinned_check(case, policy):
    for item in policy['state_members']:
        path = runtime.member_path(case,item['path'])
        require(path.resolve().is_relative_to(case) and not path.is_symlink(), 'SOURCE_SYMLINK_FORBIDDEN')
        require(path.is_file(), 'LEGACY_MEMBER_MISSING:'+item['path'])
        data = path.read_bytes()
        require(len(data) == item['bytes'] and sha(data) == item['sha256'], 'LEGACY_MEMBER_DRIFT:'+item['path'])

def rows(path):
    data = Path(path).read_bytes()
    require(not data or data.endswith(b'\n'), 'INCOMPLETE_JSONL_TAIL')
    return [json.loads(line, object_pairs_hook=unique_object) for line in data.splitlines() if line.strip()]

def semantic_check(case, policy):
    """Read-only checks; no prices/fees/SL/TP/PnL are recomputed."""
    data, root = roots(case, policy)
    epoch = policy['epoch']; active = read_json(data/'paper_epochs/active.json')
    require(active['paper_epoch_id'] == epoch and active['epoch_status'] == 'ACTIVE', 'EPOCH_CONFLICT')
    require(active['paper_only'] is True and active['real_execution_enabled'] is False, 'REAL_EXECUTION_FORBIDDEN')
    require(active['execution_enabled'] is False, 'EXECUTION_ACTIVATION_FORBIDDEN')
    other = read_json(data/'paper_epochs'/f'{epoch}.json')
    require(other == active, 'ACTIVE_POINTER_RECORD_CONFLICT')
    a = read_json(root/'trading_contract.json'); b = read_json(data/'paper_epochs'/f'{epoch}.trading_contract.json')
    require(a['trading_contract_fingerprint'] == b['trading_contract_fingerprint'] == active['trading_contract_fingerprint'], 'CONTRACT_FINGERPRINT_CONFLICT')
    require(a['trading_contract_manifest'] == b['trading_contract_manifest'], 'CONTRACT_MANIFEST_CONFLICT')
    books = {t: rows(root/'books'/f'{t}.jsonl') for t in TABLES}
    for table in books.values():
        require(all(row.get('paper_epoch_id', epoch) == epoch for row in table), 'BOOK_EPOCH_CONFLICT')
    latest = {}
    for row in books['positions']:
        require(row['position_id'] and row['timeframe'] in policy['risk_pct'], 'POSITION_ID_OR_TF_CONFLICT')
        if row['position_id'] in latest:
            old = latest[row['position_id']]
            require(old['timeframe'] == row['timeframe'] and old['side'] == row['side'], 'POSITION_ID_REPARENTED')
            require(old['status'] == 'OPEN' and row['status'] == 'CLOSED', 'POSITION_HISTORY_CONFLICT')
        latest[row['position_id']] = row
    require(len(latest) == policy['expected_positions_closed'] and all(x['status'] == 'CLOSED' for x in latest.values()), 'OPEN_OR_UNEXPECTED_POSITIONS')
    require(len(books['fills']) == policy['expected_fills'], 'FILL_COUNT_CONFLICT')
    for table in books.values():
        stamps=[r.get('ts',r.get('execution_timestamp')) for r in table]
        stamps=[dt.datetime.fromisoformat(t.replace('Z','+00:00')) for t in stamps if t]
        require(all(t.tzinfo is not None for t in stamps), 'TIMESTAMP_TIMEZONE_MISSING')
        require(stamps==sorted(stamps), 'RECORDED_PUBLICATION_TIME_REGRESSION')
    for row in latest.values():
        opening = next(x for x in books['positions'] if x['position_id']==row['position_id'] and x['status']=='OPEN')
        require(dt.datetime.fromisoformat(opening['opened_at'].replace('Z','+00:00')) <= dt.datetime.fromisoformat(row['closed_at'].replace('Z','+00:00')), 'POSITION_TIME_CONFLICT')
    for table, field in [('fills','fill_id'), ('orders','order_id'), ('commands','command_id'), ('trades','trade_id')]:
        ids = [r[field] for r in books[table]]
        require(len(ids) == len(set(ids)), 'DUPLICATE_BOOK_ID:'+table)
    require(len(books['trades']) == len(latest), 'TRADE_POSITION_COUNT_CONFLICT')
    for trade in books['trades']:
        require(trade['position_id'] in latest and trade['status'] == 'CLOSED', 'TRADE_POSITION_OWNERSHIP_CONFLICT')
        require(trade['timeframe'] == latest[trade['position_id']]['timeframe'], 'TRADE_TF_CONFLICT')
    cursor = read_json(root/'s41_command_cursor.json')
    ids = cursor['processed_command_ids']
    require(len(ids) == len(set(ids)), 'DUPLICATE_CONSUMER_CURSOR')
    require(read_json(root/'context_consumer_checkpoint.json')['paper_epoch_id'] == epoch, 'CONTEXT_CURSOR_EPOCH_CONFLICT')
    ledger = read_json(root/'sleeves.json')
    require(ledger['schema_version'] == 'per_tf_equity_sleeves_v1' and ledger['epoch_id'] == epoch, 'LEDGER_SCHEMA_OR_EPOCH_CONFLICT')
    require(set(ledger['sleeves']) == set(policy['risk_pct']), 'SLEEVE_SET_CONFLICT')
    for tf, sleeve in ledger['sleeves'].items():
        net = sum((money(x['net_pnl_usd']) for x in books['trades'] if x['timeframe'] == tf), Decimal(0))
        count = sum(x['timeframe'] == tf for x in books['trades'])
        require(sleeve['epoch_id'] == epoch and sleeve['timeframe'] == tf, 'SLEEVE_OWNER_CONFLICT')
        require(sleeve['open_position_id'] is None and money(sleeve['open_position_risk_usd']) == 0, 'SLEEVE_OPEN_OCCUPANCY')
        require(sleeve['closed_trades_count'] == count, 'SLEEVE_TRADE_COUNT_CONFLICT')
        require(near(sleeve['cumulative_realized_net_pnl_usd'], net), 'SLEEVE_RECORDED_PNL_CONFLICT')
        require(near(sleeve['current_equity_usd'], money(sleeve['initial_equity_usd']) + net), 'SLEEVE_EQUITY_CONFLICT')
        require(money(sleeve['risk_pct_per_trade']) == money(policy['risk_pct'][tf]), 'RISK_PERCENT_CONFLICT')
        require(near(sleeve['next_risk_budget_usd'], money(sleeve['current_equity_usd'])*money(policy['risk_pct'][tf])/100), 'RISK_BUDGET_CONFLICT')
    master = ledger['master']
    require(money(master['master_current_equity_usd']) == money(policy['master_equity_usd']), 'MASTER_EQUITY_CONFLICT')
    require(money(master['master_realized_net_pnl_usd']) == money(policy['recorded_net_pnl_usd']), 'MASTER_RECORDED_PNL_CONFLICT')
    require(master['open_positions_count'] == 0 and money(master['master_open_risk_usd']) == 0, 'MASTER_OCCUPANCY_CONFLICT')
    require(near(sum((money(s['current_equity_usd']) for s in ledger['sleeves'].values()), Decimal(0)), master['master_current_equity_usd']), 'MASTER_SLEEVE_SUM_CONFLICT')
    require(near(sum((money(t['net_pnl_usd']) for t in books['trades']), Decimal(0)), master['master_realized_net_pnl_usd']), 'MASTER_TRADE_SUM_CONFLICT')
    receipt_paths = sorted((root/'execution_commits_v1/receipts').glob('*.json'))
    legacy = [p for p in receipt_paths if json.loads(json.loads(p.read_bytes())['payload']).get('schema') == 'execution_commit_v1']
    require(len(legacy) == policy['expected_v1_receipts'], 'LEGACY_RECEIPT_COUNT_CONFLICT')
    spans = {t: [] for t in TABLES}; keys = []; methods = {}; fill_owners = {}
    for path in legacy:
        envelope = read_json(path); raw = envelope['payload'].encode()
        require(sha(raw) == envelope['sha256'], 'LEGACY_RECEIPT_CHECKSUM_CONFLICT')
        r = json.loads(raw, object_pairs_hook=unique_object)
        require(r['schema'] == 'execution_commit_v1' and r['status'] == 'COMMITTED' and r['epoch'] == epoch, 'LEGACY_RECEIPT_AUTHORITY_CONFLICT')
        require(path.stem == sha(r['key'].encode()) and r['key'].startswith(epoch+'|'), 'LEGACY_RECEIPT_ID_CONFLICT')
        require(r['key'] not in keys, 'DUPLICATE_LEGACY_KEY'); keys.append(r['key']); methods[r['key']] = r['source']['method']
        if 'fills' in r['books']:
            effect_positions = [json.loads(l) for l in r['books'].get('positions',{}).get('data','').splitlines() if l]
            for fill in [json.loads(l) for l in r['books']['fills']['data'].splitlines() if l]:
                tf = fill['timeframe']; action = fill['action']
                require(action in {'ENTRY','EXIT'}, 'FILL_ACTION_CONFLICT')
                owner = r['occupancy_after' if action=='ENTRY' else 'occupancy_before'].get(tf)
                status = 'OPEN' if action=='ENTRY' else 'CLOSED'
                require(owner in latest and any(x['position_id']==owner and x['timeframe']==tf and x['status']==status for x in effect_positions), 'RECEIPT_FILL_OWNER_CONFLICT')
                require(fill.get('position_id',owner)==owner, 'EXPLICIT_FILL_OWNER_CONFLICT')
                require(fill['fill_id'] not in fill_owners, 'DUPLICATE_RECEIPT_FILL')
                fill_owners[fill['fill_id']] = owner
        for table, entry in r['books'].items():
            require(table in TABLES and type(entry['offset']) is int and entry['offset'] >= 0, 'INVALID_LEGACY_BOOK_RANGE')
            payload = entry['data'].encode(); current = (root/'books'/f'{table}.jsonl').read_bytes(); off = entry['offset']
            require(sha(current[:off]) == entry['prefix_sha256'], 'LEGACY_BOOK_PREFIX_CONFLICT')
            require(current[off:off+len(payload)] == payload, 'LEGACY_BOOK_EFFECT_CONFLICT')
            spans[table].append([off, off+len(payload)])
    require(set(fill_owners)=={x['fill_id'] for x in books['fills']}, 'FILL_RECEIPT_COVERAGE_CONFLICT')
    for pid in latest:
        require(sum(owner==pid for owner in fill_owners.values())==2, 'FILL_POSITION_COVERAGE_CONFLICT')
    coverage = {}
    for table, values in spans.items():
        merged = []
        for start, end in sorted(values):
            if merged and start < merged[-1][1]:
                raise AdmissionBlocked('OVERLAPPING_LEGACY_EFFECTS:'+table)
            if merged and start == merged[-1][1]:merged[-1][1] = end
            else:merged.append([start,end])
        size = (root/'books'/f'{table}.jsonl').stat().st_size
        require(merged == ([[0,size]] if size else []), 'UNWITNESSED_LEGACY_BOOK_BYTES:'+table)
        coverage[table] = merged
    return {'epoch':epoch,'positions':len(latest),'fills':len(books['fills']),'receipts_v1':len(legacy),'master_equity_usd':master['master_current_equity_usd'],'recorded_net_pnl_usd':master['master_realized_net_pnl_usd'],'coverage':coverage,'fill_owner_receipt_bindings':fill_owners,'legacy_receipt_keys':keys,'legacy_source_methods':methods,'ledger':ledger,'old_commands_consumed':len(ids)}

def verify_legacy(case, policy):
    pinned_check(case, policy)
    return semantic_check(case, policy)

def prepare(case):
    case = guard_case(case); policy = load_policy(); facts = verify_legacy(case, policy)
    ec, fh, _ = reference(); _, root = roots(case, policy)
    control = case/'control'; path = control/'admission_plan.json'
    key = runtime.admission_key(policy)
    # Both directories were COMPLETELY captured, unlike excluded market WAL.
    prefix='app/data/trading/intrabar_paper/'+policy['epoch']+'/'
    original={m['path'].removeprefix(prefix) for m in policy['state_members'] if m['path'].startswith(prefix)}
    known_books={x for x in original if x.startswith('books/')}
    present_books={str(p.relative_to(root)) for p in (root/'books').rglob('*') if p.is_file()}
    require(present_books==known_books, 'UNEXPECTED_BOOK_ARTIFACT')
    known_commit={x for x in original if x.startswith('execution_commits_v1/')}
    allowed_new={'execution_commits_v1/'+x for x in ('pending.json','head.json','currentness.json','history.mmr','publication.witness','publications/1.json')}
    allowed_new.add('execution_commits_v1/receipts/'+sha(key.encode())+'.json')
    present_commit={str(p.relative_to(root)) for p in (root/'execution_commits_v1').rglob('*') if p.is_file()}
    require(present_commit <= known_commit | allowed_new, 'UNEXPECTED_COMMIT_ARTIFACT')
    if path.exists():
        plan = ec.decode_authority(path, policy['epoch'])
    else:
        # Never regenerate a lost plan against a partially admitted financial root.
        authority = root/'execution_commits_v1'
        require(not any((authority/n).exists() for n in AUTH_NAMES), 'UNPLANNED_OR_EXISTING_AUTHORITY')
        existing = list((authority/'receipts').glob('*.json'))
        require(len(existing) == policy['expected_v1_receipts'], 'UNPLANNED_RECEIPT_PRESENT')
        source = {'method':'legacy_snapshot_admission_v1','args':[{'export_manifest_sha256':policy['source_export_manifest_sha256'],'state_members_sha256':policy['state_members_sha256'],'policy_sha256':runtime.policy_sha(),'admitted_at':dt.datetime.now(dt.timezone.utc).isoformat(),'record_kind':'CURRENT_METADATA_ADMISSION_NOT_HISTORICAL_EXECUTION','new_financial_operations_allowed':False}], 'kwargs':{}}
        source['args'][0].update(runtime.admission_provenance())
        publication = {'schema':ec.HEAD_SCHEMA,'epoch':policy['epoch'],'generation':1,'parent':None,'key':key,'association':ec.command_association(source),'files':ec.constituent_identities(root),'scopes':{tf:{'version':0,'sleeve':s,'last_change':None} for tf,s in facts['ledger']['sleeves'].items()}}
        plan = {'schema':'execution_commit_v3','epoch':policy['epoch'],'key':key,'source_key':key,'status':'INTENT','source':source,'result':{'status':runtime.admission_status(),'economic_effects':0,'entry_allowed':False},'record_kind':'LEGACY_ADMISSION_BOUNDARY_V1','occupancy_before':{},'occupancy_after':{},'terminal':True,'books':{},'documents':{},'publication':publication}
        plan['publication']['history'], _ = fh.plan(None, fh.receipt_leaf(plan))
        control.mkdir(exist_ok=True)
        ec.atomic_bytes(path, ec.encode_authority(plan))
    validate_plan(plan, root, policy, facts)
    return case, policy, facts, plan

def validate_plan(plan, root, policy, facts):
    ec, fh, _ = reference()
    require(plan['schema']=='execution_commit_v3' and plan['epoch']==policy['epoch'] and plan['status']=='INTENT', 'ADMISSION_PLAN_SCHEMA_CONFLICT')
    require(plan['books']=={} and plan['documents']=={} and plan['occupancy_before']=={} and plan['occupancy_after']=={}, 'ADMISSION_MUST_NOT_APPLY_ECONOMIC_EFFECTS')
    require(plan['record_kind']=='LEGACY_ADMISSION_BOUNDARY_V1' and plan['result']=={'status':runtime.admission_status(),'economic_effects':0,'entry_allowed':False}, 'ADMISSION_EFFECT_AUTHORITY_CONFLICT')
    key=runtime.admission_key(policy);require(plan['key']==key and plan['source_key']==key, 'ADMISSION_KEY_CONFLICT')
    source=plan['source'];a=source['args'][0]
    require(source['method']=='legacy_snapshot_admission_v1' and source['kwargs']=={} and len(source['args'])==1, 'ADMISSION_SOURCE_CONFLICT')
    require(a['export_manifest_sha256']==policy['source_export_manifest_sha256'] and a['state_members_sha256']==policy['state_members_sha256'] and a['policy_sha256']==runtime.policy_sha() and a['new_financial_operations_allowed'] is False and a['record_kind']=='CURRENT_METADATA_ADMISSION_NOT_HISTORICAL_EXECUTION', 'ADMISSION_ANCHOR_CONFLICT')
    for name,value in runtime.admission_provenance().items():require(a.get(name)==value,'WORKING_ADMISSION_SOURCE_PIN_CONFLICT')
    if not runtime.working_profile():require(not any(k.startswith('working_') for k in a),'WORKING_SOURCE_IN_RESEARCH_CONTEXT')
    pub=plan['publication'];require(pub['schema']==ec.HEAD_SCHEMA and pub['epoch']==policy['epoch'] and pub['generation']==1 and pub['parent'] is None and pub['key']==key, 'ADMISSION_BOUNDARY_CONFLICT')
    require(pub['association']==ec.command_association(source), 'ADMISSION_ASSOCIATION_CONFLICT')
    require(pub['files']==ec.constituent_identities(root), 'ADMISSION_CONSTITUENTS_CONFLICT')
    scopes={tf:{'version':0,'sleeve':s,'last_change':None} for tf,s in facts['ledger']['sleeves'].items()}
    require(pub['scopes']==scopes, 'ADMISSION_SCOPE_CONFLICT')
    require(pub['history']==fh.plan(None,fh.receipt_leaf(plan))[0], 'ADMISSION_HISTORY_CONFLICT')

def admit(case, phase=None):
    """Only metadata publication on a permitted SSD case; no engine/callback."""
    case, policy, facts, plan = prepare(case)
    ec, _, bookmod = reference(); _, root = roots(case, policy); authority=root/'execution_commits_v1'
    # Before the original books constructor can recover, check exact pending bytes.
    if (authority/'pending.json').exists():
        require((authority/'pending.json').read_bytes()==ec.encode_authority(plan), 'FOREIGN_OR_CORRUPT_PENDING')
    hook=phase or (lambda _:None)
    original_phase=ec.ExecutionCommit._phase
    ec.ExecutionCommit._phase=lambda self,name:hook(name)
    try:
        books=bookmod.EpochBooks(root/'books',paper_epoch_id=policy['epoch'])
        with books.exclusive():
            verify_legacy(case,policy)
            if (authority/'head.json').exists() and not (authority/'pending.json').exists():
                head=ec.verify_committed_head(root,policy['epoch'])
                require(head['publication']==plan['publication'], 'NEWER_AUTHORITY_OUTSIDE_ADMISSION_SCOPE')
            else:
                require(not (authority/'head.json').exists(), 'UNRESOLVED_ADMISSION_HEAD')
                ec.atomic_bytes(authority/'pending.json',ec.encode_authority(plan));hook('after_admission_intent')
                books.commit.materialize(plan)
                head=ec.verify_committed_head(root,policy['epoch'])
            verify_legacy(case,policy)
            require(head['publication']==plan['publication'], 'ADMISSION_READBACK_CONFLICT')
        return {'status':'PASS_ISOLATED_ADMISSION','head':ec.head_reference(head),'facts':{k:v for k,v in facts.items() if k not in ['ledger','legacy_source_methods']},'new_financial_operations_allowed':False,'Final65_checker':'UNCHANGED_VERIFY_COMMITTED_HEAD','Linux_storage_qualified':False}
    finally:
        ec.ExecutionCommit._phase=original_phase

def authorize_new_operation(*args, **kwargs):
    raise AdmissionBlocked('NO_NEW_FINANCIAL_OPERATION_AUTHORITY')

def reject_legacy_replay(case, key):
    """Execute the unchanged Final65 v1 receipt guard; never a PAPER engine."""
    case=guard_case(case);policy=load_policy();verify_legacy(case,policy)
    ec,_,bookmod=reference();_,root=roots(case,policy);books=bookmod.EpochBooks(root/'books',paper_epoch_id=policy['epoch'])
    path=books.commit.receipt_path(key);require(path.exists(),'LEGACY_KEY_MISSING')
    saved=books.commit.load(path);require(saved['schema']=='execution_commit_v1','NOT_LEGACY_KEY')
    def forbidden_callback():
        raise AssertionError('FINANCIAL_CALLBACK_MUST_NEVER_RUN')
    with books.exclusive():
        try:
            books.commit.run(key,forbidden_callback,None,saved['source'])
        except RuntimeError as exc:
            require(str(exc)=='EXECUTION_RECEIPT_MIGRATION_REQUIRED','UNEXPECTED_REPLAY_GUARD')
            return {'status':'BLOCKED_NO_EFFECT','reason':str(exc)}
    raise AdmissionBlocked('LEGACY_REPLAY_UNEXPECTEDLY_ALLOWED')
