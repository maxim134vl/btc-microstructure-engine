"""Read-only paper readiness, with separate FLAT and OPEN resume contracts."""
from pathlib import Path
from datetime import datetime,timezone
import json,os,hashlib
RESUME='OPEN_POSITION_RESUME_V1'
def envelope(path):
 e=json.loads(path.read_text());raw=e['payload']
 if hashlib.sha256(raw.encode()).hexdigest()!=e['sha256']:raise ValueError('DOCUMENT_CHECKSUM')
 return json.loads(raw)
def running_mode(command):
 if not any(str(a).endswith('/run_intrabar_paper_manager.py') for a in command):raise ValueError('NOT_PAPER_RUNNER')
 try:mode=command[command.index('--continuity-mode')+1]
 except ValueError:mode='FLAT_START'
 if mode not in ('FLAT_START',RESUME):raise ValueError('UNKNOWN_CONTINUITY_MODE')
 return mode

def evaluate(*,root,domain,mode,h,ep,contract,now,pid_alive=True):
 root=Path(root);r=root/'trading/intrabar_paper'/ep['paper_epoch_id'];m=h['execution_market'];s=m['state'];b=m['fresh_live_boundary'] or {};age=(now-datetime.fromisoformat(h['updated_at'].replace('Z','+00:00'))).total_seconds();expected=r/'live_continuity_v1'/domain/'execution_market_wal'
 stage='NOT_ADMITTED';resume_valid=False
 if mode==RESUME and b.get('status') in ('CONTINUITY_ADMITTED','CATCHUP_COMPLETE','ACTIVE') and b.get('schema_version')==RESUME:
  d=expected.parent;proof=envelope(d/'fresh_live_boundary.json');manifest=envelope(d/'resume_manifest.json');cp=json.loads((d/'execution_market_checkpoint.json').read_text()) if (d/'execution_market_checkpoint.json').exists() else {}
  admitted=(proof.get('schema_version')==RESUME and proof.get('paper_epoch_id')==ep['paper_epoch_id'] and proof.get('status') in ('CONTINUITY_ADMITTED','CATCHUP_COMPLETE') and proof.get('manifest_sha256')==hashlib.sha256((d/'resume_manifest.json').read_bytes()).hexdigest() and manifest.get('contract')==RESUME and manifest.get('epoch')==ep['paper_epoch_id'] and Path(manifest['new_domain'])==d and manifest['expected_position_ids'] and proof.get('no_unresolved_gap') is True and proof['verified_rows']==proof['boundary_agg_trade_id']-manifest['last_durable_market_checkpoint']['last_processed_agg_trade_id'] and proof['boundary_WS_event']['a']==proof['boundary_agg_trade_id'])
  if admitted:
   stage='ADMITTED_RECOVERING' if proof['status']=='CONTINUITY_ADMITTED' else 'CATCHUP_COMPLETE'
   resume_valid=(proof['status']=='CATCHUP_COMPLETE' and b.get('status') in ('CATCHUP_COMPLETE','ACTIVE') and b.get('manifest_sha256')==proof['manifest_sha256'] and b.get('verified_range_sha256')==proof['verified_range_sha256'] and cp.get('paper_epoch_id')==ep['paper_epoch_id'] and int(cp.get('last_processed_agg_trade_id') or -1)>=proof['boundary_agg_trade_id'] and int(m['checkpoint'].get('last_processed_agg_trade_id') or -1)>=proof['boundary_agg_trade_id'])
 elif mode=='FLAT_START':stage=b.get('status') or 'NOT_ADMITTED'
 # Identical FLAT readiness gates; only the mode-specific proof-status condition differs.
 proof_ready=b.get('status')=='ACTIVE' if mode=='FLAT_START' else resume_valid
 ready=(pid_alive and contract.get('status')=='PASSED' and contract.get('real_execution_enabled') is False and ep.get('epoch_status')=='ACTIVE' and h.get('paper_epoch_id')==ep['paper_epoch_id'] and h.get('alive') is True and h.get('paper_only') is True and h.get('real_execution_enabled') is False and 0<=age<=45 and s.get('state')=='HEALTHY' and s.get('entry_allowed') is True and s.get('agg_trade_stream_fresh') is True and s.get('book_ticker_stream_fresh') is True and float(s.get('last_agg_trade_age_ms',float('inf')))+age*1000<=5000 and float(s.get('last_book_ticker_age_ms',float('inf')))+age*1000<=float(h['max_bbo_age_ms']) and s.get('unresolved_gap') is False and int(s.get('wal_write_failures',0))==0 and proof_ready and b.get('admission_committed') is True and Path(m['wal']['root'])==expected and not (r/'execution_commits_v1/pending.json').exists())
 return {'execution_ready':bool(ready),'mode':mode,'stage':stage,'process_alive':pid_alive,'market_state':s.get('state'),'health_age_seconds':age,'entry_allowed':s.get('entry_allowed'),'fresh_domain':domain}
def main():
 try:
  root=Path('/app/data');ep=json.loads((root/'trading/paper_epochs/active.json').read_text());r=root/'trading/intrabar_paper'/ep['paper_epoch_id'];h=json.loads((r/'health.json').read_text());contract=json.loads((root/'deployment/paper_only_contract.json').read_text());pid=int(h['pid']);os.kill(pid,0);command=Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\x00');mode=running_mode(command);domain=os.environ['BTCML_FRESH_LIVE_DOMAIN']
  if '--fresh-live-domain' not in command or command[command.index('--fresh-live-domain')+1]!=domain:raise ValueError('RUNNING_DOMAIN_MISMATCH')
  result=evaluate(root=root,domain=domain,mode=mode,h=h,ep=ep,contract=contract,now=datetime.now(timezone.utc));print(json.dumps(result));return 0 if result['execution_ready'] else 1
 except Exception as exc:print('EXECUTION_NOT_READY:'+type(exc).__name__+':'+str(exc)[:160]);return 1
if __name__=='__main__':raise SystemExit(main())
