"""Fixture-only namespace compatibility; trusted offline harness issues proofs.

Not a REAL verifier, journal, context builder or trading permission API. Trust
anchors belong to the test runner; observations cannot supply a new trust root.
Files are reread against pinned SHA on every use. Same-process code replacement
is outside this fixture-test trust boundary, as for accepted FixtureAuthority.
"""
from dataclasses import dataclass,asdict
from pathlib import Path
from copy import deepcopy
from types import MappingProxyType
import importlib.util,sys,json,ast,types
import pandas as pd
from .trend_october_consumer import CompletedContextReader,BindingError,sha,digest,utc,DUR,SHARED,scalar
VERSION='OCTOBER_CANONICAL_FIXTURE_BINDING_V1'
W=Path('/Volumes/MaksTiger/BTC-ML-CONTROLLED-STAGE1-START-2026-10-08/analysis/TREND_STRENGTH_OCTOBER_NAMESPACE_COMPAT_V1/working_copy');N=W.parent
PINS={'repository/research/trend_opportunity_isolated_v1/ledger.py': '303c124f6a2c2bac0dd5ab3db28084768a845bf3dce156a237c873faaecda6d1', 'repository/research/trend_opportunity_isolated_v1/__init__.py': '97cd5222065ad54538c884e5e922cd860afeae2a6e23bbfade4efc585d1fc907', 'repository/research/trend_opportunity_isolated_v1/machine.py': '75548c4b6ccc194b716f965db52ab67c6a6e7a3bd7a8c6ab61ee9f20f3367ed5', 'repository/research/trend_opportunity_isolated_v1/candidate_adapter.py': '2694d663a983393627f4e8ab6c96332b3527059fcdef006f6bd623a90b2ce95c', 'repository/research/trend_opportunity_isolated_v1/contract.py': 'f2290d5343b2f2bb9eb88f03a1d36c92ba3bc5b15009eac0337dc44ed21261db', 'repository/tests/research/trend_opportunity_isolated_v1/test_contract.py': '984c2666560a901a8561715b970b2261f271c2ebb65bcf30786241861dc224d3', 'repository/tests/research/trend_opportunity_isolated_v1/generate_fixture_proof.py': '786efcc207c5093275efbcacf13982a201d384b3837d856127cf18c1d62a78c5', 'DRA_INTEGRATED_ISOLATED_RESEARCH_V1/src/handoff.py': '383477471946d3c84cddfca8b7d59450655a955c5c062bc72c9a3ab1eddf8bd9', 'DRA_INTEGRATED_ISOLATED_RESEARCH_V1/src/scope_sessions.py': '8cf85ffbf918a17cb8cca0b30d3fc86b1aa4ab92c8d8e555631507feaf87573b', 'captured_october/timeframe-manager/config/timeframe_trader_risk.json': '302101a31c474d26e60c91d1d9931c5de92be798505cd08aa57bf72fd21a33ef', 'captured_october/timeframe-manager/config/intrabar_paper_execution.json': '8e4c55e05e5694a885e8a434daad0716fbbb376e331a9e940c96ff8ee0537fce', 'captured_october/timeframe-manager/deploy/vps/entrypoints/timeframe_manager.sh': '924843e3dfa40da335de85431acd89405c3c81ca8c5dbf14b2269588a1afbabc', 'captured_october/timeframe-manager/src/btc_ml/trading/anti_saw_path_density.py': '89c1630b85cd5b972bec0f3fc83217ce6f0a0b95da028cabb281447c8a24e469', 'captured_october/timeframe-manager/src/btc_ml/trading/timeframe_state_adapter.py': '88bc7348e3b3dc848406559ac1389298966328c0d615cb4ca8a7667c03b32357', 'captured_october/timeframe-manager/src/btc_ml/trading/timeframe_manager.py': '48940d83300fdcc3f4d2c67b042ec76dc8ec6c4e497108f124b8a20064d87e6b', 'captured_october/context-refresh-daemon/scripts/research/build_auction_episode_memory.py': 'e109ff1bfdab53e7c6b144ec88d07ef5d8cd190bf6ca48a68b60b3fb7552f597', 'captured_october/context-refresh-daemon/scripts/research/build_market_context_lifecycle_memory.py': '44b7f0bc39790a8c1c1feec615c622970daebdb3996996ae763c8fca8f1dd18f', 'captured_october/context-refresh-daemon/scripts/research/build_final_market_context_memory.py': 'e385e9eafd493835be7d1ce57cff5dddfa54496a13f82f31d5612d70c876b9c5', 'captured_october/context-refresh-daemon/scripts/research/build_cognitive_market_state_memory.py': '006893a20765b92f7dcc7d8edaac31dff8800255c6add9955bbfa73f0af11b0d', 'captured_october/context-refresh-daemon/scripts/live/run_causal_context_chain_candidate.py': '4b26ee0a689c1f618b8a18aa89117a882b228baa18d96d5d80d36f5dc0ebade3', 'captured_october/context-refresh-daemon/src/btc_ml/cognition/living_market_process.py': 'f9a98dddc187c066a4d591686a2fd01373e156024b591178df291a8b4ba9c141', 'captured_october/context-refresh-daemon/src/btc_ml/external_traders/proxy_planes.py': '0901406788c9980e29ab34601e8f3da2e639ed1c67fb7a186b1940c85dfad6da', 'captured_october/context-refresh-daemon/src/btc_ml/external_traders/m15_september_boundary.py': 'fa4114fe5ee40dce771cf30bae6efbf148ac72b3d34561c8c33258801ffbc588', 'captured_october/context-refresh-daemon/src/btc_ml/external_traders/rebuild_context.py': '981a27698bd4c9fbebc80e08085a72d3f764087bd961d262ecebd1dc04a62438', 'captured_october/context-refresh-daemon/src/btc_ml/external_traders/tf_market_pack.py': 'fce5dadfff92d61da779290b10527c7aaadd8b9ae5bc25ec9cadc3e75a98ac9d', 'captured_october/context-refresh-daemon/src/btc_ml/external_traders/independent_context_publication.py': '043fb1aef92a2253fc94dd26813e873916974f9875f8ee2cafd7fb156a4be77d', 'captured_october/context-refresh-daemon/src/btc_ml/external_traders/candle_structure.py': '7a386ffc82e0f3977173330926a2ab1b0af558fec65afd941dd91853e528b0aa', 'captured_october/context-refresh-daemon/src/btc_ml/external_traders/incremental_context_publication.py': 'e9afb54e6de1e9b28537a4432849025f66d85ca5709cf07f1afd9ada9c7e057a'}
_BINDINGS={}
_VERIFY_CACHE={}
@dataclass(frozen=True)
class CanonicalFixtureProof:
 contract_version:str
 binding_sha:str
 def to_dict(self):return asdict(self)

def _sources():
 for rel,wanted in PINS.items():
  if sha((W/rel).read_bytes())!=wanted:raise BindingError('SYNTHETIC_SOURCE_SHA_MISMATCH:'+rel)
 return dict(PINS)

def _module(name,rel):
 # Isolated namespace transport for cold restart, never a model/test double.
 cap=W/'captured_october/context-refresh-daemon/src/btc_ml'
 for pkg,path in [('btc_ml',cap),('btc_ml.cognition',cap/'cognition'),('btc_ml.external_traders',cap/'external_traders')]:
  existing=sys.modules.get(pkg)
  if existing is not None:
   if str(path) not in list(getattr(existing,'__path__',[])):raise BindingError('CAPTURED_IMPORT_NAMESPACE_CONFLICT')
  else:
   namespace=types.ModuleType(pkg);namespace.__path__=[str(path)];sys.modules[pkg]=namespace
 for mod,m in list(sys.modules.items()):
  if mod.startswith('btc_ml.') and getattr(m,'__file__',None) and not Path(m.__file__).resolve().is_relative_to(cap):raise BindingError('CAPTURED_MODULE_SOURCE_CONFLICT')
 p=W/rel
 if name not in sys.modules:
  spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
 return sys.modules[name]

def _mapper():
 rel='captured_october/timeframe-manager/src/btc_ml/trading/timeframe_state_adapter.py';p=W/rel
 node=next(x for x in ast.parse(p.read_text()).body if isinstance(x,ast.FunctionDef) and x.name=='_episode_id_for_timeframe')
 scope={'Any':object,'pd':pd};exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),scope);return scope['_episode_id_for_timeframe']

def _verify_artifacts(a):
 _sources()
 root=Path(a['root']).resolve()
 if not root.is_relative_to(N/'test_artifacts') or root.stat().st_dev==Path('/').stat().st_dev:raise BindingError('SYNTHETIC_STORAGE_AUTHORITY')
 for rel,h in a['files'].items():
  p=(root/rel).resolve()
  if not p.is_relative_to(root) or not p.is_file() or p.stat().st_size>16*1024*1024 or sha(p.read_bytes())!=h:raise BindingError('SYNTHETIC_ARTIFACT_SHA_MISMATCH:'+rel)
 cpin=json.loads((root/'pinned_config.json').read_text())
 for file,h in cpin['implementation_sha'].items():
  if sha(Path(file).read_bytes())!=h:raise BindingError('BOUND_IMPLEMENTATION_SHA_MISMATCH')
 cache_key=digest(a)
 if cache_key in _VERIFY_CACHE:return deepcopy(_VERIFY_CACHE[cache_key])
 decl=json.loads((root/'synthetic_provenance.json').read_text());c=json.loads((root/'pinned_config.json').read_text());authority=json.loads((root/'fixture_authority.json').read_text());policy=json.loads((root/'policy_provenance.json').read_text());receipt=json.loads((root/'completed_receipt.json').read_text())
 if decl!={'kind':'EXPLICIT_SYNTHETIC_INPUT_RECIPE','recipe':'ACCEPTANCE_16_V1','origin':'FIXTURE_ONLY','timeframe':a['timeframe'],'direction':a['direction'],'source_bar_open':a['source_bar_open'],'real_grant':'ABSENT'}:raise BindingError('SYNTHETIC_PROVENANCE_CONFLICT')
 if c['mode']!='FIXTURE_ONLY' or digest(c)!=a['config_sha'] or digest(authority)!=c['authority_sha'] or authority.get('type')!='AUTHOR_DECLARED_SYNTHETIC_FIXTURE' or not authority.get('capture_family','').startswith('fixture:') or authority['capture_family']!=c['capture_family'] or authority['coverage_ref']!=c['coverage_ref']:raise BindingError('SYNTHETIC_POLICY_SOURCE_AUTHORITY')
 if authority.get('scope')!='NO_REAL_GRANT / EXPLICIT_SYNTHETIC_GENESIS_ONLY':raise BindingError('SYNTHETIC_SCOPE_GRANT_FORBIDDEN')
 checkpoint=json.loads((root/'issuance_checkpoint.json').read_text())
 if checkpoint.get('version')=='DRA_RESEARCH_JOURNAL_V3_DELTA':raise BindingError('V3_REQUIRES_JOURNAL_REPLAY_NOT_LEGACY_FIXTURE_SNAPSHOT')
 state=checkpoint['state'];session=state['scope_sessions'][a['scope_ref']]
 if digest({k:v for k,v in checkpoint.items() if k!='sha'})!=a['issuance_record_sha'] or checkpoint['sha']!=a['issuance_record_sha'] or checkpoint['state_sha']!=digest(state) or digest(state['config'])!=a['config_sha'] or checkpoint['boundary']!='C_E' or checkpoint['action'].get('kind')!='BIND_CONTEXT_SCOPE' or checkpoint['action'].get('session_id')!=a['scope_ref'] or checkpoint['action'].get('cutoff')!=a['issued_at'] or digest(session['proof'])!=a['scope_proof_sha'] or session['predecessor']!=a['predecessor']:raise BindingError('ISSUANCE_CHECKPOINT_MISMATCH')
 if utc(a['issued_at'])<utc(a['available_at']) or any(utc(raw['available_at'])>utc(a['issued_at']) for raw in state['raw'].values()):raise BindingError('PROOF_ISSUANCE_NOT_PREEXISTING')
 expected={'kind':'SYNTHETIC_FROZEN_PREFIX_POLICY','origin':'FIXTURE_ONLY','policy_id':a['policy_id'],'policy_available_at':c['policy_available_at'],'baseline_sha':digest(c['baseline']),'baseline_available_at':c['baseline_available_at'],'capture_family':c['capture_family'],'authority_sha':c['authority_sha'],'config_sha':a['config_sha'],'numeric_predicates':'UNCHANGED','real_grant':'ABSENT'}
 if policy!=expected:raise BindingError('SYNTHETIC_POLICY_PINS_MISMATCH')
 # Compare the entire input to the explicit synthetic recipe, not its label.
 tf=a['timeframe'];direction=a['direction'];last=pd.Timestamp(a['source_bar_open']);rows=[]
 for i in range(16):
  rows.append({'timestamp':last-pd.Timedelta(seconds=DUR[tf]*(15-i)),'timeframe':tf,'close':100+i if direction=='LONG' else 200-i,'cognitive_market_state':'ACCEPTANCE_HIGHER' if direction=='LONG' else 'ACCEPTANCE_LOWER','state_direction':'BUYER_CONTROL' if direction=='LONG' else 'SELLER_CONTROL','state_status':'CONFIRMED','state_reason':'EXPLICIT_SYNTHETIC_INPUT','effort_result':'ACCEPTANCE','price_result':'HIGHER' if direction=='LONG' else 'LOWER','effort_side':'BUYER' if direction=='LONG' else 'SELLER','volume_effort':'HIGH','relative_volume':2.0,'relative_spread':1.0})
 cog=pd.read_parquet(root/'synthetic_cognitive_input.parquet');pd.testing.assert_frame_equal(cog,pd.DataFrame(rows),check_exact=True)
 final_mod=_module('namespace_original_final','captured_october/context-refresh-daemon/scripts/research/build_final_market_context_memory.py');life_mod=_module('namespace_original_lifecycle','captured_october/context-refresh-daemon/scripts/research/build_market_context_lifecycle_memory.py')
 f=final_mod.build_final_market_context_rows(cog);l=life_mod.build_lifecycle_memory(f,evaluation_frame=cog)
 suffix='' if tf=='M15' else 'timeframes/'+tf+'/';frel='data/cognition/'+suffix+'final_market_context_memory.parquet';lrel=SHARED if tf=='M15' else 'data/cognition/'+suffix+'market_context_lifecycle_memory.parquet'
 pd.testing.assert_frame_equal(pd.read_parquet(root/frel),f,check_exact=True)
 episodes=life_mod.build_lifecycle_episodes(l);episodes['timeframe']=tf
 actual_ep=pd.read_parquet(root/'data/cognition/market_context_lifecycle_episodes.parquet');pd.testing.assert_frame_equal(actual_ep,episodes,check_dtype=False,check_exact=True)
 own=pd.read_parquet(root/lrel);pd.testing.assert_frame_equal(own[[col for col in l]],l,check_dtype=False,check_exact=True)
 # CompletedContextReader verifies shared lifecycle-last membership and own rows.
 manifest={rel:a['files'][rel] for rel in a['files'] if rel.endswith('.parquet') and rel.startswith('data/')}
 bound=CompletedContextReader(root,manifest,'SYNTHETIC_FIXTURE',_mapper()).consume(tf,a['source_bar_open'],receipt['available_at'],receipt)
 row_hashes={'final':digest(bound.final_row),'lifecycle':digest(bound.lifecycle_row)}
 if (bound.canonical_context_episode_id,bound.canonical_direction,bound.actual_publication_at,row_hashes)!=(a['context_id'],a['direction'],a['available_at'],a['row_hashes']):raise BindingError('SYNTHETIC_COMPLETED_BINDING_MISMATCH')
 if a['sources']!=_sources():raise BindingError('SYNTHETIC_IMPLEMENTATION_PIN')
 if len(_VERIFY_CACHE)>=4096:raise BindingError('BOUNDED_PROOF_CACHE_CAP')
 _VERIFY_CACHE[cache_key]=deepcopy((c,authority,policy,bound))
 return c,authority,policy,bound

def issue_binding(system,bound,reader,cog,policy_id='fixture:ANCHORED_FIRST_ELIGIBLE_PREFIX_V1'):
 """Trusted test harness only, after original publication and accepted H1 bind.

 Registration verifies files/recipe/reexecution; it is never called by an event.
 A proof reference alone is not a trust anchor. Accepted predecessor and H1/H2
 guards stay authoritative and are not edited by this function.
 """
 if policy_id not in ('fixture:ANCHORED_FIRST_ELIGIBLE_PREFIX_V1','ANCHORED_FIRST_ELIGIBLE_PREFIX_V1'):raise BindingError('ORIGINAL_POLICY_ID_REQUIRED')
 from .trend_scope_sessions import head,verify
 if bound.authority!='FIXTURE_ONLY' or reader.origin!='SYNTHETIC_FIXTURE' or not reader.root.is_relative_to(N/'test_artifacts'):raise BindingError('REAL_FIXTURE_AUTHORITY_FORBIDDEN')
 verify(system);s=system.state;c=s['config'];scope=head(s,bound.timeframe);session=s.get('scope_sessions',{}).get(scope)
 if not session or session['proof']['canonical_episode_id']!=bound.canonical_context_episode_id or session['proof']['direction']!=bound.canonical_direction or session['proof']['available_at']!=bound.actual_publication_at:raise BindingError('ACCEPTED_H1_SCOPE_REQUIRED')
 if c['mode']!='FIXTURE_ONLY' or not system.authority or digest(system.authority.declaration)!=c['authority_sha']:raise BindingError('FIXTURE_POLICY_AUTHORITY_REQUIRED')
 record=deepcopy(system.j.records[-1])
 if record['action'].get('kind')!='BIND_CONTEXT_SCOPE' or record['action'].get('session_id')!=scope or any(utc(r['available_at'])>utc(bound.actual_publication_at) for r in s['raw'].values()):raise BindingError('PROOF_MUST_PRECEDE_CONSTITUENTS')
 issued_at=record['action']['cutoff']
 if utc(issued_at)<utc(bound.actual_publication_at):raise BindingError('PROOF_ISSUANCE_BEFORE_CONTEXT')
 root=reader.root/'namespace_proofs'/digest([digest(c),scope,policy_id])
 root.mkdir(parents=True,exist_ok=False)
 for rel in reader.manifest:
  target=root/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(reader._read(rel))
 # Evidence receipts, not a second state/persistence subsystem. Fresh fixture only.
 cog.to_parquet(root/'synthetic_cognitive_input.parquet',index=False)
 decl={'kind':'EXPLICIT_SYNTHETIC_INPUT_RECIPE','recipe':'ACCEPTANCE_16_V1','origin':'FIXTURE_ONLY','timeframe':bound.timeframe,'direction':bound.canonical_direction,'source_bar_open':bound.source_bar_open,'real_grant':'ABSENT'}
 policy={'kind':'SYNTHETIC_FROZEN_PREFIX_POLICY','origin':'FIXTURE_ONLY','policy_id':policy_id,'policy_available_at':c['policy_available_at'],'baseline_sha':digest(c['baseline']),'baseline_available_at':c['baseline_available_at'],'capture_family':c['capture_family'],'authority_sha':c['authority_sha'],'config_sha':digest(c),'numeric_predicates':'UNCHANGED','real_grant':'ABSENT'}
 for file,data in [('issuance_checkpoint.json',record),('synthetic_provenance.json',decl),('pinned_config.json',c),('fixture_authority.json',system.authority.declaration),('policy_provenance.json',policy),('completed_receipt.json',bound.context_publication_ref['fixture_receipt'])]:
  (root/file).write_text(json.dumps(data,sort_keys=True,indent=2))
 files={str(p.relative_to(root)):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
 a={'version':VERSION,'issued_at':issued_at,'issuance_record_sha':record['sha'],'root':str(root),'timeframe':bound.timeframe,'context_id':bound.canonical_context_episode_id,'direction':bound.canonical_direction,'source_bar_open':bound.source_bar_open,'available_at':bound.actual_publication_at,'policy_id':policy_id,'config_sha':digest(c),'row_hashes':{'final':digest(bound.final_row),'lifecycle':digest(bound.lifecycle_row)},'sources':_sources(),'files':files,'scope_ref':scope,'scope_proof_sha':digest(session['proof']),'predecessor':session['predecessor']}
 _verify_artifacts(a);key=digest(a)
 _BINDINGS[key]=deepcopy(a)
 (N/'evidence'/'fixture_proofs').mkdir(exist_ok=True);(N/'evidence'/'fixture_proofs'/str(key+'.json')).write_text(json.dumps(a,sort_keys=True,indent=2))
 return CanonicalFixtureProof(VERSION,key)

def verify_observation(o,proof):
 try:
  if o.origin!='FIXTURE_ONLY':return 'SYNTHETIC_PROOF_ON_REAL_FORBIDDEN'
  if not isinstance(proof,dict) or set(proof)!={'contract_version','binding_sha'} or proof['contract_version']!=VERSION or proof['binding_sha'] not in _BINDINGS:return 'UNTRUSTED_SYNTHETIC_BINDING'
  a=deepcopy(_BINDINGS[proof['binding_sha']]);c,authority,policy,bound=_verify_artifacts(a)
  if digest(a)!=proof['binding_sha']:return 'SYNTHETIC_BINDING_MUTATED'
  if (o.tf,o.context_id,o.context_direction,o.context_available_at,o.partition_policy_id,o.partition_declared_at)!=(a['timeframe'],a['context_id'],a['direction'],a['available_at'],a['policy_id'],c['policy_available_at']):return 'SYNTHETIC_CONTEXT_OR_POLICY_MISMATCH'
  if [asdict(t) for t in o.baseline_trades]!=c['baseline'] or o.baseline_available_at!=c['baseline_available_at']:return 'SYNTHETIC_BASELINE_PINS_MISMATCH'
  allowed=set(authority['allowed_payload_hashes'])
  if any(t.payload_sha not in allowed or c['coverage_assertion']['memberships'].get(t.source_key)!=t.payload_sha for t in o.trades):return 'SYNTHETIC_CONSTITUENT_AUTHORITY_MISMATCH'
  if max(utc(a['available_at']),utc(a['issued_at']))>utc(o.trades[0].trade_time):return 'SYNTHETIC_PROOF_LATE'
 except Exception as e:return 'SYNTHETIC_PROOF_REJECTED:'+type(e).__name__
 return None

def proof_for_window(s,tf,own,ids):
 """Only transport; exact H1 admission already checked by unchanged context()."""
 from .trend_scope_sessions import head
 from .trend_handoff import permissions
 if s['config']['mode']!='FIXTURE_ONLY':return None
 scope=head(s,tf);session=s.get('scope_sessions',{}).get(scope)
 if not session:return None
 if not permissions(s,tf,ids):return None
 found=[(key,a) for key,a in _BINDINGS.items() if (a['config_sha'],a['scope_ref'],a['timeframe'],a['context_id'],a['direction'],a['policy_id'])==(digest(s['config']),scope,tf,own['id'],own['direction'],'fixture:ANCHORED_FIRST_ELIGIBLE_PREFIX_V1')]
 if len(found)!=1:return None
 key,a=found[0]
 if digest(session['proof'])!=a['scope_proof_sha'] or session['predecessor']!=a['predecessor']:return None
 return CanonicalFixtureProof(VERSION,key).to_dict()


def restore_binding(path,expected_binding_sha):
 """Offline runner supplies a pinned receipt SHA; an event cannot register itself.

 Rechecks all artifacts and implementation pins. Accepted journals/reducers own
 recovery and predecessor checks. This loads a proof, not another state machine.
 """
 p=Path(path).resolve()
 if not p.is_relative_to(N/'evidence/fixture_proofs') or p.stat().st_size>1024*1024:raise BindingError('PROOF_RECEIPT_STORAGE_OR_CAP')
 a=json.loads(p.read_text())
 if digest(a)!=expected_binding_sha or a['version']!=VERSION:raise BindingError('RESTORE_PROOF_PIN_MISMATCH')
 _verify_artifacts(a);_BINDINGS[expected_binding_sha]=deepcopy(a)
 return CanonicalFixtureProof(VERSION,expected_binding_sha)
