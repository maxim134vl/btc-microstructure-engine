"""In-process continuation certificate for fully validated financial prefixes.

Never persisted, never reconstructed from a head alone. Native MMR/witness,
currentness and full semantic suffix validation are unchanged. Certification
requires this process/thread's native EX; readers/restarts run full cold proof.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import threading
import stat
from . import financial_authority_runtime as runtime

@dataclass(frozen=True)
class CertifiedPrefix:
    pid: int
    root: Path
    root_identity: tuple
    config_sha: str
    anchor_sha: str
    immutable: dict
    mmr_bytes: int
    mmr_sha: str
    witness_bytes: int
    witness_sha: str
    state: dict

_CERTIFICATES: dict[tuple[int,Path], CertifiedPrefix] = {}
_MUTEX=threading.RLock()

def signature(path: Path) -> tuple:
    value=path.stat(follow_symlinks=False)
    if not stat.S_ISREG(value.st_mode): raise RuntimeError('CONTINUATION_SOURCE_TYPE_CONFLICT')
    return value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns

def prefix_sha(path: Path, length: int) -> str:
    digest=hashlib.sha256();remaining=length
    with path.open('rb') as stream:
        while remaining:
            piece=stream.read(min(1024*1024,remaining))
            if not piece: raise RuntimeError('CONTINUATION_PREFIX_TRUNCATED')
            remaining-=len(piece);digest.update(piece)
    return digest.hexdigest()

def owns_ex(root: Path) -> bool:
    from .execution_commit import EXCLUSIVE_ROOT
    return EXCLUSIVE_ROOT.get()==(root.resolve(),os.getpid(),threading.get_ident())

def immutable_paths(root: Path) -> set[Path]:
    # These are path selections within ONE read-only collection. source() itself
    # checks the entire RO source namespace; do not repeat that N times for N
    # members. All returned paths are still independently signature-checked by
    # the original certify/certified_prefix code below.
    with runtime.validated_path_reads():
        auth=runtime.authority();policy=runtime.policy();ar=root/'execution_commits_v1'
        source=runtime.source();reference=runtime.reference_source_root();case=runtime.case_root()
        paths={auth.config_path,Path(auth.config['policy_path']),runtime.anchor_path(),runtime.binding_path(),Path(auth.config['observation_config_path'])}
        paths.update(source/m['path'] for m in policy['state_members'])
        paths.update(reference/name for name in policy['reference_sha256'])
        paths.update(p for directory in (ar/'receipts',ar/'publications') for p in directory.iterdir() if p.is_file())
        for m in policy['state_members']:
            if '/paper_epochs/' in m['path'] or m['path'].endswith('/trading_contract.json'):
                paths.add(runtime.member_path(case,m['path']))
        # Recheck the actual RO source and reference selection at this read's
        # end, in addition to the full authority recheck at scope exit.
        if runtime.source()!=source or runtime.reference_source_root()!=reference:
            raise RuntimeError('CONTINUATION_SOURCE_SELECTION_CHANGED')
        return paths

def certified_prefix(root: Path, anchor_sha: str) -> tuple[dict | None, dict | None]:
    """Return known semantic prefix, or require full proof retaining last-seen pin."""
    root=root.resolve()
    if not owns_ex(root): return None,None
    with _MUTEX: certificate=_CERTIFICATES.get((os.getpid(),root))
    if certificate is None: return None,None
    prior=certificate.state['heads'][certificate.state['generation']]
    st=root.stat();root_id=(st.st_dev,st.st_ino)
    if certificate.root_identity!=root_id or certificate.config_sha!=runtime.authority().config_sha256 or certificate.anchor_sha!=anchor_sha:
        return None,prior
    for path,identity in certificate.immutable.items():
        try:
            if signature(path)!=identity: return None,prior
        except (FileNotFoundError,RuntimeError): return None,prior
    ar=root/'execution_commits_v1'
    if prefix_sha(ar/'history.mmr',certificate.mmr_bytes)!=certificate.mmr_sha:
        raise RuntimeError('CONTINUATION_MMR_PREFIX_CONFLICT')
    if prefix_sha(ar/'publication.witness',certificate.witness_bytes)!=certificate.witness_sha:
        raise RuntimeError('CONTINUATION_WITNESS_PREFIX_CONFLICT')
    from . import execution_commit as ec
    head=ec._verify_committed_head_raw(root,runtime.epoch())
    ec.authenticated_prior(head,prior,root,runtime.epoch())
    return copy.deepcopy(certificate.state),prior

def certify(root: Path, anchor_sha: str, state: dict) -> None:
    """Called only after the complete cold/suffix verifier succeeds."""
    root=root.resolve()
    if not owns_ex(root): return
    ar=root/'execution_commits_v1';g=state['generation'];st=root.stat()
    mmr_bytes=state['prev']['publication']['history']['nodes']*32;witness_bytes=g*176
    identities={path:signature(path) for path in immutable_paths(root)}
    certificate=CertifiedPrefix(os.getpid(),root,(st.st_dev,st.st_ino),runtime.authority().config_sha256,anchor_sha,identities,mmr_bytes,prefix_sha(ar/'history.mmr',mmr_bytes),witness_bytes,prefix_sha(ar/'publication.witness',witness_bytes),copy.deepcopy(state))
    with _MUTEX: _CERTIFICATES[(os.getpid(),root)]=certificate

def discard(root: Path) -> None:
    with _MUTEX: _CERTIFICATES.pop((os.getpid(),root.resolve()),None)
