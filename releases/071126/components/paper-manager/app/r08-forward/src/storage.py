"""External-only immutable, no-clobber root journal; ACK is a separate truth."""
import os, fcntl, plistlib, subprocess, uuid, json, threading
from pathlib import Path
from .common import *
ROOT=Path(__file__).resolve().parents[1]
MOUNT=Path(os.environ.get('BTC_ML_R08_RUNTIME_MOUNT','/Volumes/MaksTiger'))
DIRS=('scope','native','normalized','receipts','coverage','manifests','pending')
class ExternalGuard:
    def __init__(self,root,probe=None):
        self.root=Path(root).absolute(); self.probe=probe or self._probe
        self.mountfd=None;self.attested_info=None;self.dynamic_probe=probe is not None
        # A pinned live mount descriptor binds the one-time UUID attestation.
        # No TTL and no automatic re-attestation of a replaced mount.
        try:
            self.mountfd=os.open(MOUNT,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            st=os.fstat(self.mountfd);self.mount_identity=(st.st_dev,st.st_ino)
            self.device=st.st_dev;self.check()
        except BaseException:self.close();raise
    def close(self):
        if self.mountfd is not None:os.close(self.mountfd);self.mountfd=None
    def __del__(self):
        self.close()
    def _probe(self):
        return plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil','info','-plist',str(MOUNT)]))
    def check(self):
        if self.mountfd is None:raise Blocked('STORAGE_LEASE_CLOSED')
        pinned=os.fstat(self.mountfd);current=MOUNT.stat()
        if ((pinned.st_dev,pinned.st_ino)!=self.mount_identity
            or (current.st_dev,current.st_ino)!=self.mount_identity
            or not MOUNT.is_mount()):raise Blocked('EXTERNAL_STORAGE_UNAVAILABLE')
        # Injected probes remain dynamic for fault tests. Default UUID/USB/APFS
        # attributes are reusable only while this exact mounted root is pinned.
        runtime=os.environ.get('BTC_ML_R08_RUNTIME_MOUNT')
        if runtime:
            # Deployment binds an existing directory on MaksTiger here. Only
            # actual mount/device identity is claimed inside Linux.
            if not MOUNT.is_mount() or self.device==Path('/').stat().st_dev:raise Blocked('EXTERNAL_STORAGE_UNAVAILABLE')
            allowed=MOUNT/'captures'
            if not self.root.is_relative_to(allowed) or self.root==allowed:raise Blocked('INTERNAL_OR_PROTECTED_ROOT_FORBIDDEN')
            if self.root.resolve()!=self.root or any(p.is_symlink() for p in (self.root,*self.root.parents)):raise Blocked('REFERENCE_ESCAPE')
            if os.statvfs(MOUNT).f_flag & os.ST_RDONLY:raise Blocked('READ_ONLY_STORAGE')
            return {'mode':'EXPLICIT_EXTERNAL_RUNTIME_BIND','mount':str(MOUNT),'device':self.device}
        info=self.probe() if self.dynamic_probe or self.attested_info is None else self.attested_info
        if (not MOUNT.is_mount() or MOUNT.stat().st_dev!=self.device or self.device==Path('/').stat().st_dev
            or info.get('VolumeUUID')!=VOLUME_UUID or info.get('BusProtocol')!='USB'
            or info.get('FilesystemType')!='apfs' or info.get('Internal') is not False
            or info.get('WritableVolume') is not True): raise Blocked('EXTERNAL_STORAGE_UNAVAILABLE')
        allowed=ROOT/'captures'
        if not self.root.is_relative_to(allowed) or self.root==allowed: raise Blocked('INTERNAL_OR_PROTECTED_ROOT_FORBIDDEN')
        for p in (self.root,*self.root.parents):
            if p.is_symlink(): raise Blocked('SYMLINK_STORAGE_FORBIDDEN')
            if p==MOUNT: break
        if self.root.resolve()!=self.root or not self.root.resolve().is_relative_to(allowed): raise Blocked('ROOT_ESCAPE')
        if os.statvfs(MOUNT).f_flag & os.ST_RDONLY: raise Blocked('READ_ONLY_STORAGE')
        after=MOUNT.stat()
        if (after.st_dev,after.st_ino)!=self.mount_identity:raise Blocked('EXTERNAL_STORAGE_UNAVAILABLE')
        self.attested_info=dict(info)
        return info
class Journal:
    def __init__(self,root,*,probe=None,clock=stamp,quota=512*1024*1024,max_transactions=20000,rss_budget=128*1024*1024):
        if not 256*1024<=quota<=13*1024*1024*1024 or not 1<=max_transactions<=65568 or not 128*1024*1024<=rss_budget<=512*1024*1024: raise ValueError('TECHNICAL_CAP')
        self.guard=ExternalGuard(root,probe);self.root=self.guard.root;self.clock=clock
        self.rss_budget=rss_budget;self.quota=quota;self.max_transactions=max_transactions;self.reserve=65536;self.mutex=threading.RLock()
        self.root.mkdir(parents=True,exist_ok=True)
        self.guard.check()
        self.dirfds={}
        self.owner_pid=os.getpid()
        self.lockfd=os.open(self.root/'writer.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try: fcntl.flock(self.lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError: self.close();raise Blocked('SINGLE_WRITER_BUSY')
        try:
            for d in DIRS: self.guard.check();(self.root/d).mkdir(exist_ok=True)
            self.seq=0;self.tip=None;self.keys={};self.committed_ack=None;self.ack_missing=[];self.orphans=[];committed_inodes=set()
            for entry in self.records():
                self.seq=entry['seq'];self.tip=entry['content_sha256'];self.keys[entry['idempotency_key']]={'seq':self.seq,'request_sha':entry['request_sha']}
                linked=[self.root/'manifests'/f'{entry["seq"]:08d}.json']+[self._path(r['path']) for r in entry['files'] if r['path'] not in entry.get('inline_files',{})]
                ack=self.root/'receipts'/('ack-'+entry['content_sha256']+'.json')
                if ack.exists():linked.append(ack)
                committed_inodes.update(p.stat().st_ino for p in linked)
            self.orphans=[p.name for p in (self.root/'pending').iterdir() if p.stat().st_ino not in committed_inodes]
            if len(self.orphans)>self.max_transactions*8: raise Corrupt('PENDING_COUNT_CAP')
            self.used=self.size();self.dir_stamps=self._dir_stamps()
            # Bind the already validated capture directories once. Relative
            # syscalls avoid repeated VirtioFS path walks for every publication.
            for name in DIRS:
                self.dirfds[name]=os.open(self.root/name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        except BaseException:self.close();raise
    def close(self):
        for fd in getattr(self,"dirfds",{}).values():os.close(fd)
        self.dirfds={}
        if getattr(self,'lockfd',None) is not None:
            os.close(self.lockfd);self.lockfd=None
        self.guard.close()
    def _path(self,rel):
        p=self.root/rel
        if len(Path(rel).parts)!=2 or Path(rel).parts[0] not in DIRS or Path(rel).is_absolute() or '..' in Path(rel).parts or not p.is_relative_to(self.root): raise Corrupt('REFERENCE_ESCAPE')
        if p.parent.name not in DIRS or p.is_symlink() or p.parent.is_symlink(): raise Corrupt('REFERENCE_PATH')
        return p
    def _read(self,p,limit=8*1024*1024):
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            if os.fstat(fd).st_size>limit: raise Corrupt('RECORD_SIZE_CAP')
            with os.fdopen(fd,'rb',closefd=False) as f:return f.read(limit+1)
        finally:os.close(fd)
    def fsyncdir(self,p):
        self.guard.check();fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    @staticmethod
    def charge(n):return ((n+4095)//4096)*4096+4096 # block rounding + metadata reserve, per directory entry
    def _dir_stamps(self):return tuple((self.root/d).stat().st_mtime_ns for d in DIRS)
    def size(self):
        total=65536;count=0 # capture-directory/lock/metadata budget overhead
        for d in DIRS:
            for p in (self.root/d).iterdir():
                count+=1
                if count>self.max_transactions*24+20: raise Corrupt('FILE_COUNT_CAP')
                if not p.is_file() or p.is_symlink(): raise Corrupt('UNEXPECTED_STORAGE_ENTRY')
                st=p.stat();total+=max(self.charge(st.st_size),st.st_blocks*512+4096)
        return total
    def _publish(self,rel,raw):
        # Called under the transaction mutex and pinned external directory FDs.
        # Mount/path validation brackets the transaction, not each metadata file.
        # Same no-clobber links and fsync-before-ACK order.
        # Directory descriptors remain owned by this Journal's writer lock.
        parts=Path(rel).parts
        if len(parts)!=2 or parts[0] not in DIRS or Path(rel).is_absolute() or '..' in parts:
            raise Corrupt('REFERENCE_ESCAPE')
        pendingfd=self.dirfds['pending'];finalfd=self.dirfds[parts[0]]
        temporary='stage-'+str(uuid.uuid4())
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=pendingfd)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        self.used+=self.charge(len(raw))
        os.fsync(pendingfd)
        os.link(temporary,parts[1],src_dir_fd=pendingfd,dst_dir_fd=finalfd,follow_symlinks=False)
        self.used+=self.charge(len(raw))
        os.fsync(finalfd)
    def records(self):
        paths=sorted((self.root/'manifests').glob('*.json'))
        if len(paths)>self.max_transactions: raise Corrupt('TRANSACTION_CAP')
        prev=None;expected=1;self.ack_missing=[]
        for p in paths:
            try:
                entry=json.loads(self._read(p))
                if p.name!=f'{expected:08d}.json' or not verified(entry) or entry['seq']!=expected or entry['previous_manifest_sha']!=prev: raise Corrupt('MANIFEST_ANCESTRY_OR_HASH')
                inline=entry.get('inline_files',{})
                if 'inline_files' in entry:
                    if (entry.get('transaction_encoding')!='INLINE_TRANSACTION_RECEIPT_V1'
                        or not isinstance(inline,dict) or entry['receipt_path'] not in inline
                        or any(not isinstance(v,str) or (k!=entry['receipt_path'] and not k.startswith(('normalized/','coverage/'))) for k,v in inline.items())
                        or not set(inline).issubset({r['path'] for r in entry['files']})):
                        raise Corrupt('INLINE_TRANSACTION_RECEIPT_ENCODING')
                elif 'transaction_encoding' in entry:raise Corrupt('INLINE_TRANSACTION_RECEIPT_ENCODING')
                def read_ref(rel):
                    path=self._path(rel)
                    return inline[rel].encode('utf-8') if rel in inline else self._read(path)
                for ref in entry['files']:
                    raw=read_ref(ref['path'])
                    if sha(raw)!=ref['sha256'] or len(raw)!=ref['bytes']: raise Corrupt('CHUNK_HASH_OR_SIZE')
                rec=json.loads(read_ref(entry['receipt_path']))
                if not verified(rec): raise Corrupt('RECEIPT_HASH')
                if any(k!=entry['receipt_path'] for k in inline) and rec.get('files_persisted_scope')!='EXTERNAL_FILES_ONLY_INLINE_AT_ROOT_COMMIT':
                    raise Corrupt('INLINE_PERSISTENCE_SCOPE')
                ackp=self.root/'receipts'/('ack-'+entry['content_sha256']+'.json')
                if ackp.exists():
                    ack=json.loads(self._read(ackp))
                    if not verified(ack) or ack['manifest_sha']!=entry['content_sha256'] or ack['seq']!=expected: raise Corrupt('ACK_HASH_OR_PARENT')
                    entry['ack_state']='POST_COMMIT_ACK_OBSERVED'
                else:
                    entry['ack_state']='PUBLISHED_ACK_UNOBSERVED';self.ack_missing.append(expected)
                entry['record']=rec
            except (OSError,KeyError,ValueError,TypeError) as e:raise Corrupt('MISSING_OR_CORRUPT_ANCESTOR') from e
            yield entry
            prev=entry['content_sha256'];expected+=1
    def commit(self,key,record,blobs=None,*,fault=None,emergency=False):
        with self.mutex:return self._commit_locked(key,record,blobs,fault=fault,emergency=emergency)
    def _commit_locked(self,key,record,blobs=None,*,fault=None,emergency=False):
        if self.lockfd is None:raise Blocked('WRITER_CLOSED')
        if os.getpid()!=self.owner_pid:raise Blocked('WRITER_PROCESS_CHANGED')
        # The existing process/flock owner is the sole capture writer.
        # Every publication charges self.used, including pending hard links and
        # incomplete publications. Directory mtime is not a byte counter and
        # may become visible late through the runtime bind. Reconstruct usage
        # once on open; never rescan the growing capture in this hot path.
        request_sha=digest({'record':record,'blobs':sorted((k,sha(v)) for k,v in (blobs or {}).items())})
        if key in self.keys:
            saved=self.keys[key]
            if saved['request_sha']!=request_sha:raise Corrupt('IDEMPOTENCY_KEY_CONTENT_CONFLICT')
            return {'seq':saved['seq'],'status':'IDEMPOTENT_RETURN'}
        self.committed_ack=None
        if not emergency and rss_bytes()>self.rss_budget:raise Capacity('RECORDER_RSS_BUDGET_INCOMPLETE')
        if len(blobs or {})>8:raise Capacity('TRANSACTION_FILES_CAP')
        self.guard.check()
        if self.seq>=self.max_transactions: raise Capacity('TRANSACTION_CAP')
        blobs=blobs or {}
        overhead=len(blobs)*512
        estimate=2*(sum(self.charge(len(x)) for x in blobs.values())+self.charge(len(canonical(record))+overhead+2000)+self.charge(overhead+2500)+self.charge(2000))
        if self.used+estimate>self.quota-(0 if emergency else self.reserve): raise Capacity('CAPTURE_QUOTA_INCOMPLETE')
        def hook(phase):
            if fault:fault(phase)
        hook('before_blobs');refs=[];inline={}
        compact=len(canonical(record))<=32768
        for rel,raw in blobs.items():
            # Literal RAW is always a separate immutable file. Only redundant
            # derived JSON metadata may share the committed manifest envelope.
            if compact and rel.startswith(('normalized/','coverage/')) and len(raw)<=65536:
                try:inline[rel]=raw.decode('utf-8')
                except UnicodeDecodeError:self._publish(rel,raw)
            else:self._publish(rel,raw)
            refs.append({'path':rel,'sha256':sha(raw),'bytes':len(raw)})
        hook('after_blobs');seq=self.seq+1;rid=str(uuid.uuid4())
        persisted_clock=self.clock()
        native_persisted=[{'type':'NATIVE_EVENT_PERSISTED','application_message_ref':r,'native_normalization_accepted':bool(record.get('mapping') and record['mapping']['status']=='ACCEPTED'),'post_files_fsync_clock':persisted_clock,'authority':'ROOT_PENDING_NOT_YET_COMMITTED'} for r in refs if r['path'].startswith('native/')]
        rec=seal({'native_persisted_receipts':native_persisted,'version':VERSION,'type':'RECORDER_TRANSACTION_RECEIPT','record':record,'files_persisted_observed':persisted_clock,'files':refs})
        if inline:
            # This pre-commit clock describes only the external files above.
            # Inline metadata is first durable with the root manifest, not here.
            body=dict(rec);body.pop('content_sha256')
            body['files_persisted_scope']='EXTERNAL_FILES_ONLY_INLINE_AT_ROOT_COMMIT'
            rec=seal(body)
        recraw=canonical(rec);rel='receipts/'+rid+'.json'
        encoded={}
        if compact:
            inline[rel]=recraw.decode('utf-8')
            encoded={'transaction_encoding':'INLINE_TRANSACTION_RECEIPT_V1','inline_files':inline}
        else:self._publish(rel,recraw)
        refs.append({'path':rel,'sha256':sha(recraw),'bytes':len(recraw)})
        entry=seal({'version':VERSION,'type':'CHUNK_MANIFEST_COMMITTED','seq':seq,'request_sha':request_sha,'idempotency_key':key,'previous_manifest_sha':self.tip,'files':refs,'receipt_path':rel,**encoded,'prepare_clock':self.clock()})
        hook('before_root');self._publish(f'manifests/{seq:08d}.json',canonical(entry))
        self.seq=seq;self.tip=entry['content_sha256'];self.keys[key]={'seq':seq,'request_sha':request_sha}
        hook('after_root');hook('before_ack')
        ack=seal({'type':'POST_COMMIT_OBSERVED_ACK','seq':seq,'manifest_sha':self.tip,'observed_clock':self.clock()})
        ackraw=canonical(ack)
        self._publish('receipts/ack-'+self.tip+'.json',ackraw);self.guard.check();hook('after_ack')
        # Exact bytes from the completed durable publication, one entry only.
        self.committed_ack=(seq,self.tip,ackraw)
        return {'seq':seq,'manifest_sha':self.tip,'status':'POST_COMMIT_ACK_OBSERVED'}
