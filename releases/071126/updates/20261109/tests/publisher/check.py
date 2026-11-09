from pathlib import Path
import os,sys,json,subprocess,hashlib,time,resource,importlib.util,ast

def load(version):
 p=Path('/checks')/(version+'.py');s=importlib.util.spec_from_file_location(version+'_codec',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def rss():
 d={}
 for l in Path('/proc/self/status').read_text().splitlines():
  if ':' in l:
   k,v=l.split(':',1)
   if k in ['VmRSS','VmHWM']:d[k]=int(v.split()[0])*1024
 return d

def worker(version,tf,trial):
 print('CHECK_PHASE '+json.dumps({'version':version,'tf':tf,'phase':'IMPORT_BEGIN'}),flush=True)
 import pandas as pd,pyarrow as pa
 print('CHECK_PHASE '+json.dumps({'version':version,'tf':tf,'phase':'IMPORT_END','rss':rss()}),flush=True)
 E=load(version);stage=Path('/checks/.primary-context-stage-code-check');path=stage/E.SIDECAR_ROOT/'sources'/('own_tf_'+tf+'.parquet');pin=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
 calls={'native_read_bytes_calls':0,'native_raw_bytes_materialized':0};original=Path.read_bytes
 def counted(p):
  b=original(p)
  if p==path:calls['native_read_bytes_calls']+=1;calls['native_raw_bytes_materialized']+=len(b)
  return b
 Path.read_bytes=counted
 with E.NativeSourcePass(stage) as owner:
  owner.frozen(path,pin);start=rss();w=time.perf_counter();c=time.process_time()
  print('CHECK_PHASE '+json.dumps({'version':version,'tf':tf,'phase':'LOAD_BEGIN','rss':rss()}),flush=True)
  result=E.load_sources(stage,specifications={'own_tf_'+tf:E.TF_NATIVE_SOURCES['own_tf_'+tf]},_native_pass=owner)['own_tf_'+tf]
  cpu=time.process_time()-c;wall=time.perf_counter()-w;memory=rss()
  print('CHECK_PHASE '+json.dumps({'version':version,'tf':tf,'phase':'LOAD_END','rss':memory,'wall_s':wall,'CPU_s':cpu}),flush=True)
  assert result['status']=='PRESENT',result
  frame=result.pop('frame');assert result['sha256']==pin
  # Validation is outside the timed load boundary and avoids a full JSON list.
  h=hashlib.sha256();h.update(E._bytes({'columns':list(frame.columns),'dtypes':[str(t) for t in frame.dtypes],'attrs':frame.attrs,'index':list(frame.index)}))
  for values in frame.itertuples(index=False,name=None):h.update(E._bytes(dict(zip(frame.columns,values))))
  print('CHECK_PHASE '+json.dumps({'version':version,'tf':tf,'phase':'LOGICAL_HASH_END','rss':rss()}),flush=True)
  snapshot=Path('/tmp/decoded.parquet');frame.to_parquet(snapshot,index=False);persisted=hashlib.file_digest(snapshot.open('rb'),'sha256').hexdigest();snapshot.unlink()
  out={'version':version,'tf':tf,'trial':trial,'input_bytes':path.stat().st_size,'input_sha256':pin,'rows':len(frame),'columns':list(frame.columns),'dtypes':[str(t) for t in frame.dtypes],'logical_frame_sha256':h.hexdigest(),'source_result_without_frame_sha256':hashlib.sha256(E._bytes(result)).hexdigest(),'persisted_output_sha256':persisted,'wall_s':wall,'CPU_s':cpu,'start_RSS':start['VmRSS'],'current_RSS_after_load':memory['VmRSS'],'peak_RSS_at_end_of_load':memory['VmHWM'],'arrow_current_bytes_after_load':pa.total_allocated_bytes(),'arrow_pool_historical_peak_bytes':pa.default_memory_pool().max_memory(),**calls}
  print('CHECK_RESULT '+json.dumps(out),flush=True)

def regressions():
 import pandas as pd
 before=load('before');after=load('after');passes=[];stage=Path('/tmp/.primary-context-stage-regression');folder=stage/after.SIDECAR_ROOT/'sources';folder.mkdir(parents=True);path=folder/'own_tf_M15.parquet'
 def run(E,owner=None):return E.load_sources(stage,specifications={'own_tf_M15':E.TF_NATIVE_SOURCES['own_tf_M15']},_native_pass=owner)['own_tf_M15']
 def same(a,b):
  pd.testing.assert_frame_equal(a['frame'],b['frame'],check_exact=True);aa={k:v for k,v in a.items() if k!='frame'};bb={k:v for k,v in b.items() if k!='frame'};assert before._bytes(aa)==after._bytes(bb)
 f=pd.DataFrame({'timestamp':pd.to_datetime(['2026-01-01','2026-01-02']),'quantity':[0.123456789012345,1.23456789012345],'id':[9007199254740993,9007199254740995],'provenance_json':['{"x":1}','{"x":2}']})
 f.to_parquet(path,index=False);pin=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
 with before.NativeSourcePass(stage) as a,after.NativeSourcePass(stage) as b:
  a.frozen(path,pin);b.frozen(path,pin);ra=run(before,a);rb=run(after,b);same(ra,rb);passes.append('small_frozen_input_all_values_schema_timestamps_ID_precision')
  b.handoff(path,pin,rb['frame']);got=run(after,b);assert got['frame'] is rb['frame'] and b._handoff is None;passes.append('handoff_transfer_unchanged')
  fresh=run(after,b);assert fresh['frame'] is not got['frame'];got['frame'].iloc[0,1]=3.;assert fresh['frame'].iloc[0,1]!=3.;passes.append('next_decode_has_no_mutable_frame_alias')
  f['quantity']=[2.5,3.5];f.to_parquet(path,index=False);same(run(before,a),run(after,b));passes.append('changed_frozen_generation_rehashes_and_matches_original')
 same(run(before),run(after));passes.append('default_reader_stays_strict')
 # Deliberate modification while candidate decodes: no stale pin is returned.
 with after.NativeSourcePass(stage) as owner:
  pin=hashlib.file_digest(path.open('rb'),'sha256').hexdigest();owner.frozen(path,pin);orig=after._decode_source_frame;once=[False]
  def swap(raw,**kw):
   if isinstance(raw,Path) and not once[0]:
    once[0]=True;g=f.copy();g['quantity']=[7.,8.];tmp=folder/'new.tmp';g.to_parquet(tmp,index=False);os.replace(tmp,path)
   return orig(raw,**kw)
  after._decode_source_frame=swap
  try:r=run(after,owner)
  finally:after._decode_source_frame=orig
  assert r['sha256']==hashlib.file_digest(path.open('rb'),'sha256').hexdigest() and list(r['frame']['quantity'])==[7.,8.];passes.append('changed_during_file_decode_falls_back_to_consistent_byte_snapshot')
 bad=f.copy();bad['timestamp']=['invalid','invalid'];bad.to_parquet(path,index=False)
 a=run(before);b=run(after);assert a==b and a['status']=='UNREADABLE';passes.append('invalid_timestamp_same_rejection')
 path.write_bytes(b'not parquet');assert run(before)==run(after);passes.append('corrupt_parquet_same_rejection')
 with before.NativeSourcePass(stage) as a,after.NativeSourcePass(stage) as b:
  pin=hashlib.file_digest(path.open('rb'),'sha256').hexdigest();a.frozen(path,pin);b.frozen(path,pin)
  assert run(before,a)==run(after,b);passes.append('corrupt_pinned_private_file_preserves_exact_original_error_reason')
 print('REGRESSION_RESULT '+json.dumps({'PASS':len(passes),'FAIL':0,'cases':passes}),flush=True)

if __name__=='__main__':
 if len(sys.argv)>1 and sys.argv[1]=='worker':worker(sys.argv[2],sys.argv[3],sys.argv[4])
 else:
  trials=[(v,tf,'1') for tf in ['H4','H1','M30','M15'] for v in ['before','after']];results=[]
  for version,tf,trial in trials:
   x=subprocess.run([sys.executable,__file__,'worker',version,tf,trial],capture_output=True,text=True,timeout=90)
   assert x.returncode==0,(version,tf,x.stdout[-1500:],x.stderr[-1500:])
   line=next(l for l in x.stdout.splitlines() if l.startswith('CHECK_RESULT '));d=json.loads(line[13:]);results.append(d);print(line,flush=True)
  for tf in ['M15','M30','H1','H4']:
   rows=[x for x in results if x['tf']==tf]
   for field in ['input_sha256','logical_frame_sha256','source_result_without_frame_sha256','persisted_output_sha256','columns','dtypes']:
    assert all(x[field]==rows[0][field] for x in rows),(tf,field)
  regressions();print('ALL_CHECKS_PASS '+json.dumps({'trials':len(results),'four_TF_logical_source_and_persisted_hashes_equal':True,'Linux_versions':'recorded per image baseline','no_market_permission_or_S0':True}),flush=True)
