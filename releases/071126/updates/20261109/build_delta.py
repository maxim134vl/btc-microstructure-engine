#!/usr/bin/env python3
"""Build only the three accepted owner updates, against exact071126 image IDs."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
def inspect(ref):return json.loads(subprocess.check_output(['docker','image','inspect',ref]))[0]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--platform',default='linux/arm64');args=p.parse_args()
if args.platform!='linux/arm64':raise SystemExit('AMD64_NOT_VERIFIED: explicit native AMD64 bases/locks/regressions are required; no ARM64 substitution')
out=args.output.resolve()
if out==ROOT or ROOT in out.parents:raise SystemExit('Build output must be outside the source worktree')
out.mkdir(parents=True,exist_ok=True)
delta=json.loads((HERE/'DELTA.json').read_text());scope=json.loads((HERE/'runtime-source-scope.json').read_text())
for x in scope:
    assert hashlib.sha256((ROOT/x['source']).read_bytes()).hexdigest()==x['sha256'],x['source']
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
payload=hashlib.sha256((HERE/'DELTA.json').read_bytes()).hexdigest();results=[]
for service in sorted({x['service'] for x in delta}):
    r=json.loads((HERE/'build'/service/'recipe.json').read_text());base=inspect(r['accepted071126_base'])
    assert base['Id']==r['accepted071126_base'] and base['Architecture']=='arm64' and base['Os']=='linux'
    assert shutil.disk_usage(Path.home()).free>3*1024**3,'INSUFFICIENT_HOST_DISK'
    alias='btcml-071126-delta-base/'+service+':'+base['Id'].split(':')[1][:16]
    existing=subprocess.run(['docker','image','inspect',alias],capture_output=True)
    if existing.returncode==0:assert inspect(alias)['Id']==base['Id'],'BASE_ALIAS_CONFLICT'
    else:subprocess.run(['docker','image','tag',base['Id'],alias],check=True)
    folder=out/service;folder.mkdir(exist_ok=True);(folder/'files').mkdir(exist_ok=True)
    shutil.copyfile(HERE/'build'/service/'Dockerfile',folder/'Dockerfile')
    for x in delta:
        if x['service']!=service:continue
        dest=folder/'files'/Path(x['runtime_path']).name;shutil.copyfile(ROOT/x['source'],dest);dest.chmod(x['mode'])
    tag='btcml-071126-delta/'+service+':20261109-'+payload[:12]
    assert subprocess.run(['docker','image','inspect',tag],capture_output=True).returncode!=0,'REFUSE_EXISTING_TAG'
    command=['docker','build','--network=none','--pull=false','--platform','linux/arm64','--build-arg','ACCEPTED_BASE='+alias+'@'+base['Id'],'--label','org.btcml.source.revision='+revision,'--label','org.btcml.071126.delta.sha256='+payload,'-t',tag,str(folder)]
    (folder/'COMMAND.json').write_text(json.dumps(command,indent=2)+'\n')
    with (folder/'BUILD.log').open('w') as f:run=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT)
    assert run.returncode==0,str(folder/'BUILD.log')
    image=inspect(tag);record={'service':service,'image_id':image['Id'],'tag':tag,'base_image_id':base['Id'],'installed_target_id':r['installed_target'],
      'platform':'linux/arm64','source_revision':revision,'delta_sha256':payload,'source_changes':sum(x['service']==service for x in delta)}
    results.append(record);(folder/'RESULT.json').write_text(json.dumps(record,indent=2)+'\n');print(service,image['Id'],flush=True)
(out/'RESULTS.json').write_text(json.dumps(results,indent=2)+'\n')
