"""Pinned native Clusters + Inventory, separate I/O namespaces in one OS process.

Only native pandas I/O call sites are rebound. Native clocks, loops, exception
handling and sleep remain untouched. OS termination retains native crash recovery.
"""
from __future__ import annotations
import argparse
import ast
import builtins
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import sys
import threading
import traceback
import types

SOURCE = Path('/opt/btcml-legacy-original')
PINS = {
 'io_runtime.py':'3d0794a3a74f13c04bd655519436f7d72639c212e7ac37c475b85049fb4b3916',
 'source_manifest.json':'67b9c1e6ea75d9ff63153daed962b253741415612ce83aa0b9dcf320f9cb8dee',
 'engines/volume_cluster_engine.py':'8f7d592165115516791f4cb607245a3cf2678e187d728b5522d9744857167639',
 'engines/inventory_engine.py':'0f029ac1ae68180c24b65a9ac3a634c2ef23637f79e0162b3b100d41b4ebe615',
}
ROLES = {
 'clusters':('volume_cluster_engine.py','volume_clusters.parquet',2,'300a23b1dab1d2260457840976506e54c5e569532d307319961a2f367898620a'),
 'inventory':('inventory_engine.py','inventory_states.parquet',3,'20d1ea6b73ae18daa92a66b350e85b77993595a7ac32bc9cd402489cda88dce5'),
}
GUARD_PREFIX_SHA='52ac2b037fd20ca418ee2c00de7a60febf541e91adc823238920d80492d465e8'

class FlowSnapshot:
 """One current atomic producer snapshot, shared only by this native pair.

 Readers open the current inode on every call. Keeping its descriptor prevents
 inode reuse; fstat changes invalidate the cache. Each engine gets its own
 mutable DataFrame and still runs native freshness, capture and audit handling.
 """
 def __init__(self):
  self.lock=threading.Lock();self.current=None
 @staticmethod
 def version(handle):
  s=os.fstat(handle.fileno())
  return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
 def read(self,path,decode):
  with self.lock:
   handle=open(path,'rb');keep=False
   try:
    version=(os.path.abspath(path),self.version(handle))
    if self.current is not None and self.current[0]==version:
     return self.current[1],self.current[2].copy(deep=True)
    raw=handle.read();pin=hashlib.sha256(raw).hexdigest()
    frame=decode(io.BytesIO(raw))
    if version==(os.path.abspath(path),self.version(handle)) and len(raw)==version[1][2]:
     if self.current is not None:self.current[3].close()
     self.current=(version,pin,frame,handle);keep=True
    return pin,frame.copy(deep=True)
   finally:
    if not keep:handle.close()


FLOW_SNAPSHOT=FlowSnapshot()


def digest(raw):
 return hashlib.sha256(raw).hexdigest()

def verified_sources():
 raw={}
 for name,expected in PINS.items():
  raw[name]=(SOURCE/name).read_bytes()
  if digest(raw[name])!=expected:
   raise RuntimeError('NATIVE_SOURCE_SHA_MISMATCH:'+name)
 return raw

class BindIO(ast.NodeTransformer):
 def __init__(self):self.edits=[]
 def visit_Call(self,n):
  self.generic_visit(n)
  if isinstance(n.func,ast.Attribute) and n.func.attr=='read_parquet' and isinstance(n.func.value,ast.Name) and n.func.value.id=='pd':
   self.edits.append({'line':n.lineno,'from':'pd.read_parquet','to':'__IO.read'})
   n.func=ast.copy_location(ast.Attribute(ast.Name('__IO',ast.Load()),'read',ast.Load()),n.func)
  elif isinstance(n.func,ast.Attribute) and n.func.attr=='to_parquet':
   self.edits.append({'line':n.lineno,'from':ast.unparse(n.func),'to':'__IO.write'})
   n.args.insert(0,n.func.value)
   n.func=ast.copy_location(ast.Attribute(ast.Name('__IO',ast.Load()),'write',ast.Load()),n.func)
  return n

class UnbindIO(ast.NodeTransformer):
 def visit_Call(self,n):
  self.generic_visit(n)
  if isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='__IO':
   if n.func.attr=='read':n.func=ast.Attribute(ast.Name('pd',ast.Load()),'read_parquet',ast.Load())
   elif n.func.attr=='write':n.func=ast.Attribute(n.args.pop(0),'to_parquet',ast.Load())
  return n

def engine_code(raw,role):
 name,output,count,expected=ROLES[role]
 original=ast.parse(raw['engines/'+name]);tree=copy.deepcopy(original)
 bind=BindIO();tree=bind.visit(tree)
 if len(bind.edits)!=count or ast.dump(UnbindIO().visit(copy.deepcopy(tree)))!=ast.dump(original):
  raise RuntimeError('NON_IO_NATIVE_AST_CHANGE:'+role)
 if digest(ast.dump(tree).encode())!=expected:
  raise RuntimeError('UNQUALIFIED_NATIVE_DISPATCH:'+role)
 return compile(ast.fix_missing_locations(tree),str(SOURCE/'engines'/name),'exec'),bind.edits

def context(raw,role):
 name,output,_,_=ROLES[role]
 m=types.ModuleType('legacy_io_'+role);m.__file__=str(SOURCE/'io_runtime.py')
 exec(compile(raw['io_runtime.py'],m.__file__,'exec'),m.__dict__)
 m.READ_SNAPSHOT=FLOW_SNAPSHOT.read
 fn=copy.deepcopy(next(n for n in ast.parse(raw['io_runtime.py']).body if isinstance(n,ast.FunctionDef) and n.name=='main'))
 cut=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Attribute) and isinstance(t.value,ast.Name) and t.value.id=='pd' and t.attr=='read_parquet' for t in n.targets))
 prefix=copy.deepcopy(fn.body[:cut])
 if digest(ast.dump(ast.Module(prefix,type_ignores=[])).encode())!=GUARD_PREFIX_SHA:
  raise RuntimeError('UNQUALIFIED_NATIVE_INITIALIZATION')
 fn.name='_initialize_native';fn.body=prefix+[ast.Return(ast.Name('lock',ast.Load()))]
 # Per-context argv for the unchanged native guard; sys.argv is never changed.
 m.sys=types.SimpleNamespace(argv=['io_runtime.py',str(SOURCE/'engines'/name),output])
 exec(compile(ast.fix_missing_locations(ast.Module([fn],type_ignores=[])),m.__file__,'exec'),m.__dict__)
 return m

def run(root):
 os.chdir(root)
 raw=verified_sources();prepared=[]
 # All source/dispatch checks and both native locks precede engine execution.
 try:
  for role in ROLES:
   code,edits=engine_code(raw,role);m=context(raw,role)
   prepared.append((role,m,code,m._initialize_native()))
 except BaseException:
  for _,_,_,lock in prepared:lock.close()
  raise
 result=queue.Queue()
 def execute(role,m,code):
  try:
   local_builtins=dict(vars(builtins));local_builtins['print']=m.observed_print
   exec(code,{'__name__':'__main__','__file__':str(SOURCE/'engines'/ROLES[role][0]),'__builtins__':local_builtins,'__IO':m})
  except BaseException:
   result.put((role,traceback.format_exc()))
  else:result.put((role,'Native endless loop returned unexpectedly'))
 threads=[]
 for role,m,code,lock in prepared:
  t=threading.Thread(target=execute,args=(role,m,code),name=role,daemon=True)
  t.start();threads.append(t)
 role,detail=result.get()
 # Any fatal worker exit ends the common process. Normal Python exceptions stay
 # in each unchanged native try/except/backoff loop. Keep locks until OS exit.
 print('LEGACY_PAIR_FATAL '+role+' '+detail,file=sys.stderr,flush=True)
 return 1

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--root',type=Path,default=Path('/legacy'))
 parser.add_argument('--verify-only',action='store_true')
 args=parser.parse_args()
 if args.verify_only:
  raw=verified_sources()
  proof={role:engine_code(raw,role)[1] for role in ROLES}
  for role in ROLES:context(raw,role)
  print(json.dumps({'source_SHA256':PINS,'dispatch':proof,'native_clocks':True}));return 0
 return run(args.root)

if __name__=='__main__':
 raise SystemExit(main())
