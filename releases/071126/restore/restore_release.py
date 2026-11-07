"""Offline backup restore, separate empty targets; never touches an existing stack."""
import argparse, pathlib, subprocess, json, os, shutil, hashlib, sys
p=argparse.ArgumentParser();p.add_argument('--backup-root',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parents[1]);p.add_argument('--runtime-root',type=pathlib.Path,required=True);p.add_argument('--volume-prefix',required=True);p.add_argument('--socket-gid',required=True);p.add_argument('--apply',action='store_true');p.add_argument('--start',action='store_true');a=p.parse_args()
B=a.backup_root.resolve();T=a.runtime_root.resolve();assert B.is_dir() and T!=B and B not in T.parents and T not in B.parents,'Runtime and immutable backup must be separate trees';assert a.volume_prefix.replace('_','').replace('-','').isalnum()
manifest=json.loads((B/'BACKUP_MANIFEST.json').read_text());assert manifest.get('status')=='VERIFIED','Only a finalized, verified preservation manifest may restore'
cs=json.loads((B/'RESTORE/compose.restore.private.json').read_text());imgs=list(dict.fromkeys(s['image'] for s in cs['services'].values()));vols={k:a.volume_prefix+'_'+k for k in ['data','legacy','visual']}
print(json.dumps({'project':'btcml-vps-smoke','images':imgs,'new_volumes':vols,'runtime_root':str(T),'plan_only':not a.apply},indent=2))
if not a.apply:sys.exit(0)
def run(cmd,**kw):return subprocess.run(cmd,check=True,**kw)
r=run(['docker','ps','-aq','--filter','label=com.docker.compose.project=btcml-vps-smoke'],capture_output=True,text=True);assert not r.stdout.strip(),'REFUSE_EXISTING_PRODUCTION_PROJECT; restore is for a new compatible Docker host'
arch=run(['docker','version','--format','{{.Server.Arch}}'],capture_output=True,text=True).stdout.strip();assert arch in {'arm64','aarch64'},'Preserved images are linux/arm64; x86/emulation is not verified'
assert not T.exists() or not any(T.iterdir()),'REFUSE_NONEMPTY_RUNTIME_ROOT'
for v in vols.values():assert subprocess.run(['docker','volume','inspect',v],capture_output=True).returncode!=0,'REFUSE_EXISTING_VOLUME '+v
# Verify every listed saved object before imports; private files stay local.
for line in (B/'SHA256SUMS').read_text().splitlines():
 if not line.strip():continue
 h,name=line.split('  ',1);q=(B/name).resolve();assert B in q.parents and q.is_file(),name
 with q.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
 assert actual==h,'BACKUP_CHECKSUM_MISMATCH '+name
archives=[B/'images.tar.gz',B/'DOCKER_IMAGES/cognition.reconstructed-image.tar.gz']
if manifest.get('additional_saved_build_base'):archives.append(B/manifest['additional_saved_build_base']['archive'])
for archive in archives:run(['docker','image','load','--input',str(archive)])
for image in imgs:run(['docker','image','inspect',image],stdout=subprocess.DEVNULL)
T.mkdir(parents=True,exist_ok=True);os.chmod(T,0o700)
shutil.copytree(B/'CONFIG/HOST_MOUNTS',T/'HOST_MOUNTS',symlinks=True)
image=cs['services']['paper-manager']['image']
# Ownership normalization is confined to NEW runtime copies, never the backup.
permission_code="import os,pathlib;root=pathlib.Path('/target');[(os.chown(p,10001,10001,follow_symlinks=False)) for p in [root,*root.rglob('*')]]"
run(['docker','run','--rm','--pull','never','--log-driver','none','--no-healthcheck','--network','none','--read-only','--user','0','--mount','type=bind,source='+str(T/'HOST_MOUNTS')+',target=/target','--entrypoint','python',image,'-I','-c',permission_code])
for component,key in [('main','data'),('legacy','legacy'),('visual','visual')]:
 run(['docker','volume','create','--label','btcml.restore=071126',vols[key]],stdout=subprocess.DEVNULL)
 run(['docker','run','--rm','--pull','never','--log-driver','none','--no-healthcheck','--network','none','--read-only','--user','0','--memory','1g','--cpus','1','--tmpfs','/tmp:rw,nosuid,noexec,size=128m','--mount','type=bind,source='+str(B)+',target=/backup,readonly','--mount','type=volume,source='+vols[key]+',target=/restore,volume-nocopy','--entrypoint','python',image,'-I','/backup/RESTORE/restore_component.py','/backup/VOLUMES/'+component+'.tar.zst','/restore',component])
# One exact application-user write/rename/unlink probe in restored R08 bind.
probe="from pathlib import Path;p=Path('/runtime/.restore-user-access-check');q=p.with_name(p.name+'.renamed');p.write_bytes(b'071126');assert p.read_bytes()==b'071126';p.rename(q);q.unlink();print('UID10001_ACCESS_PASS')"
run(['docker','run','--rm','--pull','never','--log-driver','none','--no-healthcheck','--network','none','--read-only','--user','10001:10001','--mount','type=bind,source='+str(T/'HOST_MOUNTS/bind-06')+',target=/runtime','--entrypoint','python',image,'-I','-c',probe])
env=dict(os.environ,BTCML_BACKUP_ROOT=str(B),BTCML_RUNTIME_ROOT=str(T),BTCML_VOLUME_PREFIX=a.volume_prefix,DOCKER_SOCKET_GID=a.socket_gid)
base=['docker','compose','-f',str(B/'RESTORE/compose.restore.private.json')]
run(base+['config','--quiet'],env=env)
if a.start:
 order=['legacy-multi-exchange','legacy-volume-clusters','legacy-volume-memory','legacy-volume-reactions','collector-watchdog','cognition-runtime','canonical-runtime','paper-manager','timeframe-manager','intrabar-supervisor','context-refresher','context-refresh-daemon','ops-api','dashboard-ui']
 for service in order:run(base+['up','-d','--no-deps','--no-build','--pull','never',service],env=env)
 print('14 requested services started; verify current health/cursors/guards before declaring operational. No replay, synthetic permission, forced OPEN or REAL enable is performed.')
else:print('Restored artifacts only. No application or market socket started. Use --start only as an explicit operational decision on the new host.')
