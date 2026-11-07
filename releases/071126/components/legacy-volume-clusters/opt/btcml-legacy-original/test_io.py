import concurrent.futures,hashlib,importlib.util,json,pathlib,tempfile,threading,time
import pandas as pd
spec=importlib.util.spec_from_file_location('io_runtime','/opt/btcml-legacy-original/io_runtime.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=pathlib.Path(tempfile.mkdtemp());m.ROOT=root;m.AUDIT=root/'ops';m.SERVICE='test';m.OUTPUT='volume_reactions.parquet'
original=pd.read_parquet('/real/volume_reactions.parquet');first=original.iloc[:1];second=original.iloc[:2]
path=root/'volume_reactions.parquet';m.write(first,path);before=path.read_bytes();m.write(second,path)
pd.testing.assert_frame_equal(pd.read_parquet(path),second)
checks=['original_schema_roundtrip','real_history_append']
try:m.write(first,path);raise AssertionError('truncation accepted')
except RuntimeError:pass
checks.append('history_truncation_refused');assert path.read_bytes()!=before
preserved=path.read_bytes();bad=second.copy();bad['extra']=0
try:m.write(bad,path);raise AssertionError('bad schema accepted')
except ValueError:pass
assert path.read_bytes()==preserved;checks.append('schema_rejection_preserves_published_file')
serializer=m.WRITE
def broken(df,path,*args,**kwargs):
 pathlib.Path(path).write_bytes(b'partial');raise OSError('injected disk failure')
m.WRITE=broken
try:m.write(second,path);raise AssertionError('fault not injected')
except OSError:pass
m.WRITE=serializer;assert path.read_bytes()==preserved;checks.append('partial_write_never_published')
stop=threading.Event();errors=[]
def reader():
 while not stop.is_set():
  try:pd.testing.assert_frame_equal(pd.read_parquet(path),second)
  except Exception as e:errors.append(str(e))
t=threading.Thread(target=reader);t.start()
for _ in range(10):m.write(second,path)
stop.set();t.join();assert not errors;checks.append('concurrent_readers_only_complete_files')
path.unlink()
try:m.write(second,path);raise AssertionError('missing history silently replaced')
except RuntimeError:pass
checks.append('published_history_loss_is_not_silently_reset')
print(json.dumps({'passed':len(checks),'checks':checks,'real_fixture_only':True},indent=2))
