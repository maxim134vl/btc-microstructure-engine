"""Restore an indexed volume archive into an EMPTY isolated target only.

No application imports. It recreates bytes, metadata and original hardlinks;
deduplicated independent files are materialized independently before return.
"""
import os,sys,json,gzip,tarfile,hashlib,shutil,stat
from pathlib import Path,PurePosixPath
archive=Path(sys.argv[1]); target=Path(sys.argv[2]); component=sys.argv[3]
assert component in {'main','legacy','visual'}
target.mkdir(parents=True,exist_ok=True);assert not any(target.iterdir()),'REFUSE_NONEMPTY_RESTORE_TARGET'
hashes={};pending={};dirs=[];footer_seen=False;rows=[]
def path(arc):
 p=PurePosixPath(arc);assert not p.is_absolute() and '..' not in p.parts and p.parts[0]==component,arc
 return target.joinpath(*p.parts[1:])
def attrs(p,row):
 if os.geteuid()==0:os.chown(p,row['uid'],row['gid'],follow_symlinks=False)
 if not p.is_symlink():os.chmod(p,row['mode'])
 os.utime(p,ns=(row['mtime_ns'],row['mtime_ns']),follow_symlinks=False)
 if not p.is_symlink():
  fd=os.open(p,os.O_RDONLY)
  try:os.fsync(fd)
  finally:os.close(fd)
if archive.suffix=='.zst':
 import pyarrow as pa
 outer=pa.CompressedInputStream(pa.OSFile(str(archive),'rb'),'zstd')
else:outer=gzip.open(archive,'rb')
with outer,tarfile.open(fileobj=outer,mode='r|') as tar:
 for m in tar:
  if m.name=='__BTCML_'+component+'_FILE_INDEX.jsonl.gz':
   with gzip.GzipFile(fileobj=tar.extractfile(m)) as z:rows=[json.loads(line) for line in z]
   footer_seen=True;continue
  if m.name.startswith('__BTCML_'):continue
  p=path(m.name);p.parent.mkdir(parents=True,exist_ok=True)
  if m.isdir():p.mkdir(exist_ok=True)
  elif m.isfile():
   h=hashlib.sha256()
   with p.open('xb') as f:
    src=tar.extractfile(m)
    while block:=src.read(2**20):f.write(block);h.update(block)
    f.flush();os.fsync(f.fileno())
   hashes[m.name]=h.hexdigest()
  elif m.islnk():pending[m.name]=m.linkname
  elif m.issym():p.symlink_to(m.linkname);hashes[m.name]=hashlib.sha256(m.linkname.encode()).hexdigest()
  elif m.isfifo():os.mkfifo(p,m.mode)
  else:raise RuntimeError('Unsupported restore member: '+m.name)
  tar.members.clear()
assert footer_seen,'MISSING_FILE_INDEX'
for row in rows:
 if row.get('archive_storage')!='content_link':continue
 p=path(row['path']);src=path(row['archive_linkname']);assert src.is_file() and row['path'] in pending
 shutil.copyfile(src,p);hashes[row['path']]=hashes[row['archive_linkname']]
for row in rows:
 if row['type']!='hardlink':continue
 p=path(row['path']);src=path(row['linkname']);os.link(src,p);hashes[row['path']]=hashes[row['linkname']]
for row in rows:
 p=path(row['path'])
 if row['type'] in {'file','hardlink','symlink'}:assert hashes[row['path']]==row['sha256'],row['path']
 if row['type']=='directory':dirs.append(row)
 else:attrs(p,row)
for row in reversed(dirs):attrs(path(row['path']),row)
print(json.dumps({'component':component,'indexed_entries':len(rows),'verified_file_or_link_hashes':len(hashes),'independent_duplicates_materialized':sum(r.get('archive_storage')=='content_link' for r in rows),'status':'PASS'}))
