"""Narrow legacy ownership proof; NEVER publication/availability authority.

Accepted R07 snapshot pins and explicit own-M15 Lifecycle rows authenticate the
unchanged legacy Final/Cognitive prefix. No inference from cadence or filenames,
no assignment into source frames, no new admission/phase/trading rule.
"""
from copy import deepcopy
from io import BytesIO
import json
from hashlib import sha256
from pathlib import Path
import pandas as pd

HOME = Path('data/cognition/context_trend_phase_v1/legacy_m15_owner')
# Exact accepted R07 preserved source identities (ISOLATED_INPUT_MANIFEST.json).
PINS = {
 'source_manifest.json':'c5359720c35c04e987ea8a423b11f29b3495a155da4e358e8909df7468f22f28',
 'boundary.json':'c721073120f1dd3ec6eb484e8ca18fb3c03165dfb458e90c6adafe6be735b0d1',
 'final.parquet':'67332a3a7226bd1f6c4776e5586deaa136b3c2d7db4e1a4b57978e536e729a79',
 'cognitive.parquet':'32216355c70dddff776872639fc5ca9418f0cc1497bbf3e6f96d26ba26d70f33',
 'lifecycle.parquet':'1944d7d8b9eeffe270730b3c164372024467722a446d80454703a6d69eaee7f0',
}

# Decode only already SHA-verified immutable proof bytes. Each constructor and
# each reader still re-opens and hashes every proof file before using the cache.
_OWNER_REFERENCE_CACHE = {}

class LegacyM15Owner:
 def __init__(self, folder):
  from .context_phase_qualification import _clean, _hash
  self.folder=Path(folder);raw=self.verify_files()
  key=(tuple(PINS.items()),_clean,_hash)
  cached=_OWNER_REFERENCE_CACHE.get(key)
  if cached is not None:
   self.end,self.rows,self.columns=deepcopy(cached)
   return
  boundary=json.loads(raw['boundary.json']);manifest=json.loads(raw['source_manifest.json'])
  if (boundary['version']!='M15_SEPTEMBER_SEMANTICS_CAUSAL_V1'
      or boundary['authoritative_commit']!='9e5d5934ec5c6fcea60a018afdd51d37b9501822'
      or boundary['legacy_version']!='LEGACY_M15_V1_SEMANTICS'):
   raise ValueError('LEGACY_M15_BOUNDARY_IDENTITY')
  self.end=pd.Timestamp(boundary['legacy_end']);self.rows={};self.columns={}
  frames={}
  for kind in ('final','cognitive','lifecycle'):
   name={'final':'final_market_context_memory','cognitive':'cognitive_market_state_memory','lifecycle':'market_context_lifecycle_memory'}[kind]
   if manifest['cognition/'+name+'.parquet']!=PINS[kind+'.parquet']:raise ValueError('LEGACY_M15_SOURCE_MANIFEST')
   f=pd.read_parquet(BytesIO(raw[kind+'.parquet']));f['timestamp']=pd.to_datetime(f.timestamp,utc=True)
   if kind=='lifecycle':f=f.loc[f.timeframe=='M15']
   else:
    if not set(f.timeframe.dropna().astype(str))<= {'M15'}:raise ValueError('LEGACY_M15_REFERENCE_FOREIGN_TF')
   f=f.loc[f.timestamp<=self.end].copy()
   if f.timestamp.duplicated().any() or len(f)!=boundary['replay_rows']:raise ValueError('LEGACY_M15_REFERENCE_KEYS')
   frames[kind]=f.set_index('timestamp',drop=False)
  final,cog,life=(frames[k] for k in ('final','cognitive','lifecycle'))
  if not final.index.equals(cog.index) or not final.index.equals(life.index):raise ValueError('LEGACY_M15_REFERENCE_LINEAGE')
  # Independent, already explicitly scoped canonical Lifecycle binds every row.
  pairs={'close':'close','market_context':'raw_market_context','cognitive_market_state':'raw_cognitive_market_state','state_direction':'raw_state_direction','context_reason':'raw_context_reason','process_strength':'process_strength','living_process':'living_process'}
  for left,right in pairs.items():
   if [_clean(v) for v in final[left]]!=[_clean(v) for v in life[right]]:raise ValueError('LEGACY_M15_EXPLICIT_LIFECYCLE_CONFLICT')
  for col in ('close','cognitive_market_state','state_direction','state_status'):
   if [_clean(v) for v in final[col]]!=[_clean(v) for v in cog[col]]:raise ValueError('LEGACY_M15_COGNITIVE_LINEAGE')
  for kind,f in (('final',final),('cognitive',cog)):
   self.columns[kind]=list(f.columns)
   self.rows[kind]={t:_hash(row.to_dict()) for t,row in f.iterrows()}
  _OWNER_REFERENCE_CACHE.clear()  # One immutable proof/version, bounded memory.
  _OWNER_REFERENCE_CACHE[key]=deepcopy((self.end,self.rows,self.columns))
 def verify_files(self):
  raw={name:(self.folder/name).read_bytes() for name in PINS}
  if any(sha256(b).hexdigest()!=PINS[name] for name,b in raw.items()):raise ValueError('LEGACY_M15_OWNER_PROOF_SHA')
  return raw
 def validate_frame(self,frame,kind):
  from .context_phase_qualification import _clean,_hash
  if kind not in self.rows or 'timeframe' not in frame:raise ValueError('LEGACY_M15_OWNER_KIND')
  if not set(frame.timeframe.dropna().astype(str))<= {'M15'}:raise ValueError('CONFLICTING_LEGACY_M15_OWNER')
  if not set(self.columns[kind])<=set(frame.columns):raise ValueError('LEGACY_M15_SOURCE_SCHEMA')
  # Validate every original legacy row and field; avoid thousands of Series
  # constructions/reindexes. _hash/_clean, proof verification and errors stay native.
  columns=list(frame.columns)
  reference=self.columns[kind]
  extra=[c for c in columns if c not in reference]
  for values in frame.loc[frame.timeframe.isna()].itertuples(index=False,name=None):
   row=dict(zip(columns,values))
   t=pd.Timestamp(row['timestamp'])
   if t not in self.rows[kind] or t>self.end:raise ValueError('LEGACY_M15_UNKNOWN_ROW')
   if _hash({c:row[c] for c in reference})!=self.rows[kind][t]:raise ValueError('LEGACY_M15_ROW_PROVENANCE')
   if any(_clean(row[c]) is not None for c in extra):raise ValueError('LEGACY_M15_UNKNOWN_HISTORICAL_FIELD')
  return frame  # Original null values / row hashes / full prefix preserved.
 def identity(self):
  return {'kind':'LEGACY_OWNER_ONLY_NOT_PUBLICATION_EVIDENCE','timeframe':'M15','pins':dict(PINS),'availability_authority':False}

def load_owner(root):
 folder=Path(root)/HOME
 return LegacyM15Owner(folder) if folder.exists() else None
