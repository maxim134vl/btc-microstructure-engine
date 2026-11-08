"""Offline batch path restoration from already restored backup components.

Restore each required main/legacy archive ONCE with the existing sealed
restore_component.py, then use its empty-target output here. This avoids
rescanning a multi-GB archive for each historical alias. Default is plan-only.
No application, service, replay, source qualification or permission is created.
"""
from pathlib import Path,PurePosixPath
import argparse,json,gzip,hashlib,os,uuid
from btcml_fs_metadata import restore_attributes
def rows(manifest,prefix):
 with gzip.open(manifest,'rt') as f:
  for line in f:
   d=json.loads(line)
   if not prefix or d['target']['path'].startswith(prefix):yield d
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--storage-root',type=Path,required=True);p.add_argument('--materialized-components',type=Path);p.add_argument('--destination-root',type=Path);p.add_argument('--prefix',default='');p.add_argument('--write',action='store_true');a=p.parse_args()
 n=0;total=0;components=set()
 for d in rows(a.manifest,a.prefix):
  n+=1;total+=d['target']['size']
  if '::' in d['keeper']['path']:components.add(PurePosixPath(d['keeper']['path'].split('::',1)[1]).parts[0])
 if not a.write:print(json.dumps({'mode':'PLAN_ONLY','paths':n,'logical_bytes':total,'components_to_restore_once':sorted(components)}));return
 if not a.destination_root:p.error('--write requires --destination-root')
 if components and not a.materialized_components:p.error('--materialized-components required for archive aliases')
 root=a.destination_root.resolve();restored=0
 for d in rows(a.manifest,a.prefix):
  t=d['target'];relative=PurePosixPath(t['path']);assert not relative.is_absolute() and '..' not in relative.parts
  dest=root/relative;assert root in dest.resolve().parents and not dest.exists() and not dest.is_symlink(),'REFUSE_EXISTING_DESTINATION'
  ref=d['keeper']['path']
  if '::' in ref:
   archive,member=ref.split('::',1);m=PurePosixPath(member);assert m.parts[0] in {'main','legacy'} and '..' not in m.parts and not m.is_absolute()
   assert archive.startswith('BTCML_BACKUP_071126/VOLUMES/')
   source=a.materialized_components.joinpath(*m.parts)
  else:source=a.storage_root/ref
  assert source.is_file() and not source.is_symlink()
  dest.parent.mkdir(parents=True,exist_ok=True);tmp=dest.with_name(dest.name+'.offline-restore-'+uuid.uuid4().hex)
  try:
   h=hashlib.sha256();size=0
   with source.open('rb') as f,tmp.open('xb') as out:
    while b:=f.read(1024*1024):out.write(b);h.update(b);size+=len(b)
    assert size==t['size'] and h.hexdigest()==t['sha'],'SAVED_PAYLOAD_MISMATCH';out.flush();os.fsync(out.fileno())
   os.chmod(tmp,t['mode']);os.utime(tmp,ns=(t['mtime'],t['mtime']));restore_attributes(tmp,d.get('original_xattrs',{}))
   os.link(tmp,dest);tmp.unlink();restored+=1
  finally:tmp.unlink(missing_ok=True)
 print(json.dumps({'status':'RESTORED_EXACT_BYTES','paths':restored,'logical_bytes':total,'original_uid_gid_retained_in_manifest_not_forced':True,'services_started':False}))
if __name__=='__main__':main()
