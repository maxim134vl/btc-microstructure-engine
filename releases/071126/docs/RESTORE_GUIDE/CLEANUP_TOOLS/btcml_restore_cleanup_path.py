"""Offline restoration of one path removed by the verified 071126 cleanup.

Default is read-only. Never starts services, replays events or changes admission.
"""
from pathlib import Path, PurePosixPath
import argparse, json, gzip, hashlib, os, shutil, subprocess, tarfile, zipfile, uuid
from btcml_fs_metadata import restore_attributes

def copy_hash(reader, writer):
    h=hashlib.sha256();n=0
    while chunk:=reader.read(1024*1024):
        writer.write(chunk);h.update(chunk);n+=len(chunk)
    return h.hexdigest(),n

def find(manifest,path):
    with gzip.open(manifest,'rt') as f:
        for line in f:
            d=json.loads(line)
            if d['target']['path']==path:return d
    raise ValueError('Path not present in this preservation manifest')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--storage-root',type=Path,required=True)
    p.add_argument('--path',required=True)
    p.add_argument('--destination-root',type=Path)
    p.add_argument('--write',action='store_true')
    a=p.parse_args();d=find(a.manifest,a.path);old=d['target'];ref=d['keeper']['path']
    relative=PurePosixPath(old['path'])
    assert not relative.is_absolute() and '..' not in relative.parts
    if not a.write:
        print(json.dumps({'mode':'DRY_RUN','path':old['path'],'keeper':ref,'sha256':old['sha'],'bytes':old['size']},ensure_ascii=False));return
    if a.destination_root is None:p.error('--write requires an explicit --destination-root')
    root=a.destination_root.resolve();dest=root/relative
    assert root in dest.resolve().parents and not dest.exists()
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_name(dest.name+'.cleanup-restore-'+uuid.uuid4().hex)
    process=None
    try:
        with tmp.open('xb') as out:
            if '::' not in ref:
                with (a.storage_root/ref).open('rb') as source:got,n=copy_hash(source,out)
            else:
                archive,member=ref.split('::',1);archive=a.storage_root/archive
                if archive.suffix=='.zip':
                    with zipfile.ZipFile(archive) as z, z.open(member) as source:got,n=copy_hash(source,out)
                else:
                    stream=None
                    if archive.name.endswith(('.zst','.zstd')):
                        process=subprocess.Popen(['zstd','-d','-q','-c',str(archive)],stdout=subprocess.PIPE)
                        stream=process.stdout
                    else:stream=archive.open('rb')
                    with stream, tarfile.open(fileobj=stream,mode='r|*') as tar:
                        source=None
                        for entry in tar:
                            name=entry.name[2:] if entry.name.startswith('./') else entry.name
                            wanted=member[2:] if member.startswith('./') else member
                            if name==wanted:
                                assert entry.isfile();source=tar.extractfile(entry)
                                got,n=copy_hash(source,out);break
                        if source is None:raise ValueError('Saved archive member absent')
            assert got==old['sha'] and n==old['size'], 'Complete saved bytes must match before publication'
            out.flush();os.fsync(out.fileno())
        os.chmod(tmp,old['mode']);os.utime(tmp,ns=(old['mtime'],old['mtime']))
        restore_attributes(tmp,d.get('preserved_target_xattrs',d.get('original_xattrs',{})))
        # Exclusive publication; never replace an existing runtime/history file.
        os.link(tmp,dest);tmp.unlink()
        print(json.dumps({'status':'RESTORED_EXACT_BYTES','destination':str(dest),'sha256':got,'bytes':n,
                          'original_uid_gid':[old['uid'],old['gid']],
                          'restored_as_current_user':True,'services_started':False},ensure_ascii=False))
    finally:
        if process is not None:
            process.terminate();process.wait()
        tmp.unlink(missing_ok=True)

if __name__=='__main__':main()
