
import pathlib,sys,unittest,json
import pandas as pd
sys.path.insert(0,'/app')
from legacy_source_inputs import select_available,publication_records,FIELDS,utc
from storage.path_registry import resolve_read,resolve_write,migrate_legacy
ROOT=pathlib.Path('/legacy')
class TestInputs(unittest.TestCase):
 def test_all_original_real_schemas_and_causality(self):
  for name in FIELDS:
   df=pd.read_parquet(ROOT/name,use_threads=False)
   pubs=publication_records(ROOT,name)
   at=utc(pubs[-2]['available_at'])
   got,times=select_available(df,pubs,name,at)
   self.assertEqual(list(got.columns),FIELDS[name])
   self.assertTrue(all(utc(t)<=at for t in times))
   if 'timestamp' in got:
    self.assertTrue((utc(got.timestamp)<=at).all())
    self.assertFalse(got.duplicated(['timestamp','exchange'] if 'exchange' in got else ['timestamp']).any())
   if name=='multi_exchange_flow.parquet':self.assertEqual(set(got.exchange),{'BINANCE'})
 def test_future_publication_cannot_change_prefix(self):
  name='volume_reactions.parquet';df=pd.read_parquet(ROOT/name,use_threads=False)
  pubs=publication_records(ROOT,name);at=utc(pubs[len(pubs)//2]['available_at'])
  a,_=select_available(df,pubs,name,at)
  b,_=select_available(df,[p for p in pubs if utc(p['available_at'])<=at],name,at)
  pd.testing.assert_frame_equal(a,b)
 def test_no_provenance_fails_closed(self):
  name='volume_reactions.parquet';df=pd.read_parquet(ROOT/name,use_threads=False)
  with self.assertRaises(RuntimeError):select_available(df,[],name,pd.Timestamp.now(tz='UTC'))
 def test_incompatible_archive_rejected(self):
  name='volume_reactions.parquet';df=pd.read_parquet(ROOT/name,use_threads=False);df['archive_extra_column']=1
  with self.assertRaises(ValueError):select_available(df,[],name,pd.Timestamp.now(tz='UTC'))
 def test_routing_no_archive_fallback_no_writer(self):
  for name in FIELDS:
   self.assertEqual(resolve_read(name),'/app/data/legacy_sources/'+name)
   self.assertFalse(migrate_legacy(name))
   with self.assertRaises(PermissionError):resolve_write(name)

 def test_live_read_audit_preserves_original_nonunique_index(self):
  import tempfile,os
  from legacy_source_inputs import read_available_source
  with tempfile.TemporaryDirectory() as d:
   os.environ['BTC_ML_DATA_ROOT']=d
   got=read_available_source('volume_reactions.parquet',pd.Timestamp.now(tz='UTC'),consumer='test')
   self.assertGreater(len(got),50)
   item=json.loads((pathlib.Path(d)/'diagnostics/legacy_source_consumption/test.jsonl').read_text())
   self.assertEqual(item['rows'],len(got))
  os.environ.pop('BTC_ML_DATA_ROOT',None)

 def test_complete_runtime_hardening_shared_readonly_mount(self):
  import tempfile,os
  from runtime_hardening import run_hardening_checks
  with tempfile.TemporaryDirectory() as d:
   os.environ['BTC_ML_DATA_ROOT']=d
   report=run_hardening_checks()
   self.assertTrue(report.ok,report.failures)
  os.environ.pop('BTC_ML_DATA_ROOT',None)
if __name__=='__main__':unittest.main()


