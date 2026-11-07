"""PROPOSED current-snapshot trust seam. Never creates owner approval or financial effects.

The separately supplied operator descriptor is the trust root, not this module or
an engine-produced file. Local clocks and SHA are not historical notarization.
"""
from pathlib import Path
import hashlib,json,os,datetime as dt

EPOCH='PER_TF_EQUITY_1PCT_V1_VPS_20260826_112613'
PROFILE='WORKING_LEGACY_ADMISSION_V1'
PERMISSIONS={'metadata_boundary_only':True,'new_open':False,'real_execution':False,
 'reprice_history':False,'new_epoch':False,'reset_cursor':False,'protective_close_requires_open_permission':False}
MODULES=('working_admission.py','financial_authority_runtime.py','legacy_admission.py','unified_financial_authority.py')

class WorkingAdmissionBlocked(RuntimeError): pass

def need(ok,code):
 if not ok:raise WorkingAdmissionBlocked(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def unique(pairs):
 out={}
 for k,v in pairs:need(k not in out,'WORKING_DUPLICATE_KEY');out[k]=v
 return out
def read(path):return json.loads(Path(path).read_bytes(),object_pairs_hook=unique,parse_constant=lambda _:need(False,'WORKING_NONFINITE_JSON'))
def stamp(v):
 try:t=dt.datetime.fromisoformat(v.replace('Z','+00:00'))
 except (ValueError,AttributeError):raise WorkingAdmissionBlocked('WORKING_CLOCK_INVALID')
 need(t.tzinfo is not None and t.utcoffset()==dt.timedelta(0),'WORKING_UTC_REQUIRED');return t

def pinned(config,name,root):
 need(config.get(name+'_path') and config.get(name+'_sha256'),'WORKING_'+name.upper()+'_REQUIRED')
 p=Path(config[name+'_path']);need(p.is_absolute(),'WORKING_ABSOLUTE_PATH_REQUIRED')
 need(not any(x.is_symlink() for x in (p,*p.parents)),'WORKING_SYMLINK_FORBIDDEN')
 need(not p.resolve().is_relative_to(Path(root).resolve()),'WORKING_INDEPENDENT_SOURCE_REQUIRED')
 need(p.is_file(),'WORKING_'+name.upper()+'_MISSING')
 need(os.statvfs(p).f_flag & os.ST_RDONLY,'WORKING_OPERATOR_MOUNT_NOT_READONLY')
 raw=p.read_bytes();need(sha(raw)==config[name+'_sha256'],'WORKING_'+name.upper()+'_PIN_CONFLICT')
 return read(p)

def implementation_pins(root,config,snapshot):
 """Release configuration is independent of historical financial descriptors."""
 fields={'implementation_release_path':'BTC_ML_IMPLEMENTATION_RELEASE',
         'implementation_release_sha256':'BTC_ML_IMPLEMENTATION_RELEASE_SHA256',
         'implementation_release_role':'BTC_ML_IMPLEMENTATION_ROLE'}
 if not any(name in os.environ for name in fields.values()):
  return snapshot.get('implementation_sha256',{})
 need(all(os.environ.get(name) for name in fields.values()),'WORKING_RELEASE_CONFIGURATION_REQUIRED')
 release_config={key:os.environ[name] for key,name in fields.items()}
 role=release_config['implementation_release_role']
 need(role in ('paper-manager','timeframe-manager'),'WORKING_RELEASE_ROLE_CONFLICT')
 release=pinned(release_config,'implementation_release',root)
 need(release.get('schema')=='BTCML_ACCEPTED_EXECUTION_RELEASE_V1','WORKING_RELEASE_SCHEMA_CONFLICT')
 return release.get('implementation_sha256',{}).get(role,{})

def verify(root,config):
 """Read-only proof, rechecked even on verified-continuation use. No grant discovery."""
 need(config.get('admission_profile')==PROFILE,'WORKING_PROFILE_REQUIRED')
 need(config.get('epoch')==EPOCH,'WORKING_EPOCH_NOT_IN_SCOPE')
 snapshot=pinned(config,'working_snapshot',root);approval=pinned(config,'working_approval',root)
 need(snapshot.get('schema')=='working_legacy_current_snapshot_v1','WORKING_SNAPSHOT_SCHEMA')
 need(snapshot.get('epoch')==approval.get('epoch')==EPOCH,'WORKING_EPOCH_CONFLICT')
 need(snapshot.get('scope')=='CURRENT_SNAPSHOT_ONLY_NO_HISTORICAL_ATTESTATION','WORKING_NO_HISTORICAL_ATTESTATION')
 need(snapshot.get('historical_independent_anchor')=='NOT_PROVEN','WORKING_HISTORICAL_CLAIM_FORBIDDEN')
 need(snapshot.get('permissions')==approval.get('permissions')==PERMISSIONS,'WORKING_PERMISSION_CONFLICT')
 need(approval.get('snapshot_sha256')==config['working_snapshot_sha256'],'WORKING_SNAPSHOT_APPROVAL_CONFLICT')
 need(approval.get('contract_sha256')==snapshot.get('contract_sha256'),'WORKING_CONTRACT_APPROVAL_CONFLICT')
 need(approval.get('effective_config_sha256')==snapshot.get('effective_config_sha256')==config['observation_config_sha256'],'WORKING_EFFECTIVE_CONFIG_CONFLICT')
 need(approval.get('source_manifest_sha256')==snapshot.get('source_manifest_sha256'),'WORKING_SOURCE_APPROVAL_CONFLICT')
 need(approval.get('base_verification_policy_sha256')==snapshot.get('base_verification_policy_sha256')==config['policy_sha256'],'WORKING_RECIPE_PIN_CONFLICT')
 need(stamp(approval.get('approved_at'))>=stamp(snapshot.get('captured_at')),'WORKING_APPROVAL_BEFORE_CAPTURE')
 need(approval.get('approval_record') and approval.get('issuer'),'WORKING_APPROVAL_PROVENANCE_REQUIRED')
 qualifier=config.get('working_qualification_only',False)
 need(type(qualifier) is bool,'WORKING_QUALIFICATION_TYPE')
 if qualifier:
  need(os.environ.get('BTC_ML_WORKING_ADMISSION_TEST_ONLY')=='TEST_ONLY' and Path(root).resolve().is_relative_to('/research-state'),'WORKING_TEST_ONLY_NOT_AUTHORIZED')
  need(approval.get('schema')=='test_only_working_admission_approval_v1' and approval.get('issuer')=='TEST_ONLY_NOT_OWNER','WORKING_QUALIFICATION_APPROVAL_REQUIRED')
 else:
  need(approval.get('schema')=='owner_approved_working_admission_v1' and approval.get('issuer')!='TEST_ONLY_NOT_OWNER','WORKING_OWNER_APPROVAL_REQUIRED')
  need(approval.get('approval_record')!='TEST_ONLY','WORKING_OWNER_APPROVAL_REQUIRED')
 need(set(snapshot.get('implementation_sha256',{}))==set(MODULES),'WORKING_HISTORICAL_IMPLEMENTATION_PIN_SET')
 pins=implementation_pins(root,config,snapshot)
 need(isinstance(pins,dict) and set(pins)==set(MODULES),'WORKING_IMPLEMENTATION_PIN_SET')
 for name,h in pins.items():need(sha((Path(__file__).parent/name).read_bytes())==h,'WORKING_IMPLEMENTATION_DRIFT:'+name)
 policy=read(config['policy_path'])
 need(snapshot.get('source_manifest_sha256')==policy['source_export_manifest_sha256'],'WORKING_EXPORT_IDENTITY_CONFLICT')
 need(snapshot.get('members')==policy['state_members'],'WORKING_MEMBER_SET_CONFLICT')
 need(snapshot.get('ledger_required') is True,'WORKING_SLEEVELEDGER_REQUIRED')
 return {'scope':'ISOLATED_CONTRACT_QUALIFICATION_ONLY' if qualifier else 'OWNER_APPROVED_CURRENT_SNAPSHOT_ONLY',
  'entry_allowed':False,'historical_attestation':False,'snapshot_sha256':config['working_snapshot_sha256'],
  'owner_approval_sha256':config['working_approval_sha256'],'permissions':PERMISSIONS}

def verify_initial(root,config):
 proof=verify(root,config);snapshot=read(config['working_snapshot_path']);repo=Path(config.get('repo_root',str(Path(config['case_root'])/'app')))
 for m in snapshot['members']:
  rel=Path(m['path']);need(not rel.is_absolute() and '..' not in rel.parts and rel.parts[0]=='app','WORKING_MEMBER_PATH_CONFLICT')
  path=repo/Path(*rel.parts[1:]);need(path.is_file(),'WORKING_INITIAL_MEMBER_MISSING:'+m['path'])
  raw=path.read_bytes();need(len(raw)==m['bytes'] and sha(raw)==m['sha256'],'WORKING_INITIAL_MEMBER_DRIFT:'+m['path'])
 return proof

def provenance(config):
 return {'working_snapshot_sha256':config['working_snapshot_sha256'],
  'working_owner_approval_sha256':config['working_approval_sha256'],
  'qualification_only':config.get('working_qualification_only',False)}
