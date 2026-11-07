"""Portable read-only regular-file checksum verification; no Docker/app/network."""
from pathlib import Path
import argparse,hashlib,json,os,time
p=argparse.ArgumentParser();p.add_argument('--backup-root',type=Path,default=Path(__file__).resolve().parents[1]);a=p.parse_args();B=a.backup_root.resolve();manifest=json.loads((B/'BACKUP_MANIFEST.json').read_text());assert manifest.get('status')=='VERIFIED','Backup finalization is not complete';count=0;size=0;t=time.monotonic()
with (B/'SHA256SUMS').open() as f:
 for line in f:
  if not line.strip():continue
  expected,name=line.rstrip('\n').split('  ',1);raw=B/name;q=raw.resolve();assert B in q.parents and q.is_file() and not raw.is_symlink(),'UNSAFE_OR_MISSING_FILE '+name
  before=q.stat()
  with q.open('rb') as r:actual=hashlib.file_digest(r,'sha256').hexdigest()
  after=q.stat();assert (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'FILE_CHANGED '+name
  assert actual==expected,'SHA256_MISMATCH '+name;count+=1;size+=before.st_size
print(json.dumps({'checksums':'PASS','regular_files':count,'bytes_read':size,'wall_s':time.monotonic()-t,'symlinks':'Link-text hashes remain in saved native indexes; this command never follows a link outside backup','full_runtime_restore':'NOT_TESTED by this file-verification command','app_network_Docker_started':False},indent=2))
