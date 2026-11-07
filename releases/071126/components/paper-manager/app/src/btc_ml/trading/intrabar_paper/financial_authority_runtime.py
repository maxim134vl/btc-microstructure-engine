"""Explicit pinned authority inputs; registration never grants entry authority."""
from __future__ import annotations
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import threading
import os
import platform
from types import MappingProxyType
from collections.abc import Mapping

@dataclass(frozen=True)
class FinancialAuthority:
    root: Path
    config_path: Path
    config_sha256: str
    config: Mapping[str, str | bool]
    isolated_test_only: bool = False

_REGISTRY: dict[Path, FinancialAuthority] = {}
_CURRENT: ContextVar[FinancialAuthority | None] = ContextVar('financial_authority', default=None)
_REGISTRY_LOCK = threading.RLock()
_PATH_READ_AUTHORITY: ContextVar[FinancialAuthority | None] = ContextVar('financial_path_read_authority', default=None)

def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def read_json(raw: bytes) -> dict:
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise RuntimeError('DUPLICATE_AUTHORITY_CONFIG_KEY')
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique)

APPROVED_LEGACY_POLICY_SHA='157d13d38579a33e8efe8583221354e0f931c4702f01679be91bad7beac067fb'

def checked_path(value: str | Path, *, existing: bool = False) -> Path:
    raw=Path(value)
    if not raw.is_absolute(): raise RuntimeError('AUTHORITY_ABSOLUTE_PATH_REQUIRED')
    if any(p.is_symlink() for p in (raw,*raw.parents)):
        raise RuntimeError('AUTHORITY_SYMLINK_FORBIDDEN')
    if existing and not raw.is_file(): raise RuntimeError('AUTHORITY_FILE_MISSING')
    return raw.resolve()

def _isolated_storage(root: Path) -> None:
    """Explicit test API only, on a separate Linux filesystem, never /app/data."""
    if os.environ.get('BTC_ML_WLA_ISOLATED_TEST_ONLY')!='TEST_ONLY' or platform.system()!='Linux':
        raise RuntimeError('EXPLICIT_LINUX_TEST_ONLY_REQUIRED')
    base=Path('/research-state')
    if not root.is_relative_to(base) or not base.is_mount():
        raise RuntimeError('PHYSICALLY_ISOLATED_RESEARCH_ROOT_REQUIRED')
    mounts=Path('/proc/self/mountinfo').read_text().splitlines()
    mount=next((line for line in mounts if line.split()[4]=='/research-state'),None)
    if mount is None or mount.split(' - ')[1].split()[0] not in {'ext4','xfs','btrfs'}:
        raise RuntimeError('RESEARCH_NATIVE_LINUX_FILESYSTEM_REQUIRED')
    if 'btc_ml_data_vps_smoke' in '\n'.join(mounts):
        raise RuntimeError('WORKING_FINANCIAL_VOLUME_FORBIDDEN')
    # An alias of the ordinary financial /app/data filesystem is not isolation.
    if Path('/app/data').exists() and os.stat(base).st_ino==os.stat('/app/data').st_ino and os.stat(base).st_dev==os.stat('/app/data').st_dev:
        raise RuntimeError('RESEARCH_WORKING_STORAGE_ALIAS')


def _check_registration_mode(root, config, isolated):
    if isolated:
        _isolated_storage(root)
        if config.get('admission_profile') not in (None,'WORKING_LEGACY_ADMISSION_V1'):
            raise RuntimeError('ISOLATED_PROFILE_CONFLICT')
        if config.get('admission_profile') is not None and config.get('working_qualification_only') is not True:
            raise RuntimeError('ISOLATED_OWNER_AUTHORITY_FORBIDDEN')
    elif config.get('admission_profile')!='WORKING_LEGACY_ADMISSION_V1' or config.get('working_qualification_only',False) is not False:
        raise RuntimeError('WORKING_PROFILE_REQUIRED_NO_RESEARCH_AUTHORITY')


def configure_financial_authority(root: Path, config_path: Path, config_sha256: str) -> None:
    """Working attachment: owner profile mandatory, never infer research mode."""
    return _configure_financial_authority(root,config_path,config_sha256,isolated=False)


def configure_isolated_financial_authority(root: Path, config_path: Path, config_sha256: str) -> None:
    """Explicit test entry, no owner or working authority; Linux isolation required."""
    return _configure_financial_authority(root,config_path,config_sha256,isolated=True)


def _configure_financial_authority(root: Path, config_path: Path, config_sha256: str, *, isolated: bool) -> None:
    """Pin operator-supplied descriptor before engine constructor, never discover."""
    root=checked_path(root); path=checked_path(config_path,existing=True)
    if path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise RuntimeError('INDEPENDENT_AUTHORITY_CONFIGURATION_REQUIRED')
    raw=path.read_bytes()
    if digest(raw)!=config_sha256: raise RuntimeError('FINANCIAL_CONFIG_PIN_CONFLICT')
    config=read_json(raw)
    if config.get('schema')!='financial_authority_runtime_v1': raise RuntimeError('FINANCIAL_CONFIG_SCHEMA_CONFLICT')
    required=('epoch','case_root','policy_path','policy_sha256','independent_anchor_path','binding_path','bootstrap_authorized','observation_config_path','observation_config_sha256')
    if any(k not in config for k in required): raise RuntimeError('FINANCIAL_CONFIG_INCOMPLETE')
    if any(type(value) not in (str,bool) for value in config.values()): raise RuntimeError('FINANCIAL_CONFIG_MUTABLE_VALUE_FORBIDDEN')
    case=checked_path(config['case_root'])
    repo=checked_path(config.get('repo_root',str(case/'app')))
    if not repo.is_relative_to(case) or root!=repo/'data/trading/intrabar_paper'/config['epoch']:
        raise RuntimeError('FINANCIAL_ROOT_IDENTITY_CONFLICT')
    anchor=checked_path(config['independent_anchor_path'])
    binding=checked_path(config['binding_path'])
    policy_path=checked_path(config['policy_path'],existing=True)
    if config['policy_sha256']!=APPROVED_LEGACY_POLICY_SHA or digest(policy_path.read_bytes())!=APPROVED_LEGACY_POLICY_SHA:
        raise RuntimeError('UNAPPROVED_LEGACY_POLICY')
    policy=json.loads(policy_path.read_bytes())
    if policy['epoch']!=config['epoch']: raise RuntimeError('POLICY_EPOCH_CONFLICT')
    references=checked_path(config.get('reference_source_root',str(policy_path.parent.parent/'reference_final65')))
    for independent in (binding,policy_path,references):
        if independent.is_relative_to(root): raise RuntimeError('INDEPENDENT_AUTHORITY_SOURCE_REQUIRED')
    observation=checked_path(config['observation_config_path'],existing=True)
    if digest(observation.read_bytes())!=config['observation_config_sha256']:
        raise RuntimeError('OBSERVATION_MODE_CONFIG_DRIFT')
    if anchor.is_relative_to(root): raise RuntimeError('INDEPENDENT_ANCHOR_REQUIRED')
    if type(config['bootstrap_authorized']) is not bool: raise RuntimeError('BOOTSTRAP_AUTHORITY_REQUIRED')
    _check_registration_mode(root,config,isolated)
    if config.get("admission_profile") is not None:
        from .working_admission import verify
        verify(root,config)
    _check_registration_mode(root,config,isolated)
    authority=FinancialAuthority(root,path,config_sha256,MappingProxyType(config),isolated)
    with _REGISTRY_LOCK:
        old=_REGISTRY.get(root)
        if old is not None and old!=authority: raise RuntimeError('FINANCIAL_AUTHORITY_REBIND_FORBIDDEN')
        _REGISTRY[root]=authority
    activate(root)

def activate(root: Path) -> FinancialAuthority:
    with _REGISTRY_LOCK: authority=_REGISTRY.get(Path(root).resolve())
    if authority is None: raise RuntimeError('FINANCIAL_AUTHORITY_NOT_CONFIGURED')
    checked_path(authority.config_path,existing=True)
    current=authority.config_path.read_bytes()
    if digest(current)!=authority.config_sha256 or read_json(current)!=dict(authority.config):
        raise RuntimeError('FINANCIAL_CONFIG_PIN_CONFLICT')
    _check_registration_mode(authority.root,authority.config,authority.isolated_test_only)
    if authority.config.get("admission_profile") is not None:
        from .working_admission import verify
        verify(authority.root,authority.config)
    _CURRENT.set(authority)
    return authority

def authority() -> FinancialAuthority:
    value=_CURRENT.get()
    if value is None: raise RuntimeError('FINANCIAL_AUTHORITY_NOT_CONFIGURED')
    if _PATH_READ_AUTHORITY.get() is value:
        return value
    return activate(value.root)

@contextmanager
def validated_path_reads():
    """Reuse ONE validation only while locating this call's member paths.

    No economic effect is performed here. The original descriptor/registration/
    implementation verification runs at entry AND exit. No process-wide cache,
    no authority is shared with another thread, and explicit activate() retains
    its complete checks even inside this narrowly delimited read scope.
    """
    selected=authority()
    token=_PATH_READ_AUTHORITY.set(selected)
    try:
        yield selected
    finally:
        _PATH_READ_AUTHORITY.reset(token)
        activate(selected.root)

def policy() -> dict:
    value=authority(); path=checked_path(value.config['policy_path'],existing=True)
    raw=path.read_bytes()
    if value.config['policy_sha256']!=APPROVED_LEGACY_POLICY_SHA or digest(raw)!=APPROVED_LEGACY_POLICY_SHA: raise RuntimeError('UNTRUSTED_POLICY')
    return read_json(raw)

def epoch() -> str: return authority().config['epoch']
def source() -> Path:
    auth = authority()  # Revalidates the externally pinned descriptor.
    supplied = auth.config.get('reference_legacy_source_root')
    if type(supplied) is not str or not supplied:
        raise RuntimeError('EXPLICIT_LEGACY_REFERENCE_ROOT_REQUIRED')
    path = checked_path(supplied)
    if not path.is_dir():
        raise RuntimeError('LEGACY_REFERENCE_DIRECTORY_REQUIRED')
    if path.is_relative_to(auth.root):
        raise RuntimeError('INDEPENDENT_LEGACY_REFERENCE_ROOT_REQUIRED')
    if not os.statvfs(path).f_flag & os.ST_RDONLY:
        raise RuntimeError('LEGACY_REFERENCE_MOUNT_NOT_READONLY')
    legacy_root = path/'app/data/trading/intrabar_paper'/auth.config['epoch']
    if legacy_root.exists() and legacy_root.samefile(auth.root):
        raise RuntimeError('LEGACY_REFERENCE_WORKING_ROOT_ALIAS')
    # A RO bind alone is insufficient when the same files have a RW bind alias.
    mounts = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, separator, right = line.partition(' - ')
        fields = left.split()
        if not separator or len(fields) < 6:
            raise RuntimeError('LEGACY_REFERENCE_MOUNT_PROOF_INVALID')
        fsroot, target = fields[3:5]
        for encoded, decoded in ((chr(92)+'040', ' '), (chr(92)+'011', chr(9)),
                                 (chr(92)+'012', chr(10)), (chr(92)+'134', chr(92))):
            fsroot = fsroot.replace(encoded, decoded)
            target = target.replace(encoded, decoded)
        mounts.append((fields[2], Path(fsroot), Path(target), set(fields[5].split(','))))
    covering = [m for m in mounts if path.is_relative_to(m[2])]
    if not covering:
        raise RuntimeError('LEGACY_REFERENCE_MOUNT_PROOF_MISSING')
    base = max(covering, key=lambda m: len(m[2].parts))
    views = [(base[0], base[1]/path.relative_to(base[2]), base[3])]
    views.extend((device, fsroot, options) for device, fsroot, target, options in mounts
                 if target != path and target.is_relative_to(path))
    for device, physical, options in views:
        if 'ro' not in options:
            raise RuntimeError('LEGACY_REFERENCE_NESTED_WRITABLE_MOUNT')
        for alias_device, alias_root, target, alias_options in mounts:
            if (alias_device == device and 'rw' in alias_options
                    and (physical.is_relative_to(alias_root)
                         or alias_root.is_relative_to(physical))):
                raise RuntimeError('LEGACY_REFERENCE_WRITABLE_MOUNT_ALIAS')
    # Hard links can expose a member through a different pathname, without a bind alias.
    # The unchanged native verifier still owns all 46 byte/SHA and economic checks.
    for member in policy()['state_members']:
        member_path = path/member['path']
        if member_path.exists() and member_path.stat(follow_symlinks=False).st_nlink != 1:
            raise RuntimeError('LEGACY_REFERENCE_MEMBER_HARDLINK_ALIAS')
    return path
def root_relative() -> Path: return authority().root.relative_to(case_root())
def repo_root() -> Path: return checked_path(authority().config.get('repo_root',str(case_root()/'app')))
def source_financial_root() -> Path: return source()/'app/data/trading/intrabar_paper'/epoch()
def member_path(case: Path, member: str) -> Path:
    relative=Path(member)
    if relative.is_absolute() or '..' in relative.parts: raise RuntimeError('AUTHORITY_MEMBER_PATH_CONFLICT')
    if Path(case).resolve()==case_root() and relative.parts[0]=='app':
        result=repo_root()/Path(*relative.parts[1:])
    else: result=Path(case)/relative
    return checked_path(result)
def policy_sha() -> str: return authority().config['policy_sha256']
def case_root() -> Path: return checked_path(authority().config['case_root'])
def binding_path() -> Path: return checked_path(authority().config['binding_path'])
def anchor_path() -> Path: return checked_path(authority().config['independent_anchor_path'])
def reference_source_root() -> Path:
    config=authority().config
    return checked_path(config.get('reference_source_root',str(Path(config['policy_path']).parent.parent/'reference_final65')))
def legacy_ids() -> list[str]:
    return json.loads((source_financial_root()/'s41_command_cursor.json').read_bytes())['processed_command_ids']


def working_profile():
    return authority().config.get('admission_profile')=='WORKING_LEGACY_ADMISSION_V1'

def admission_provenance():
    if not working_profile():return {}
    from .working_admission import provenance
    return provenance(authority().config)

def admission_status():
    if not working_profile():return 'LEGACY_SNAPSHOT_ADMITTED_FOR_RESEARCH'
    return ('LEGACY_SNAPSHOT_ADMISSION_QUALIFICATION_ONLY' if authority().config.get('working_qualification_only')
        else 'LEGACY_SNAPSHOT_ADMITTED_FROM_OWNER_CURRENT_SNAPSHOT')

def admission_key(policy):
    key=policy['epoch']+'|legacy_snapshot_admission_v1|'+policy['state_members_sha256']
    if working_profile():
        p=admission_provenance();key+='|owner_current_snapshot|'+p['working_snapshot_sha256']+'|'+p['working_owner_approval_sha256']
    return key

def binding_mode():
    if not working_profile():return 'ISOLATED_ONLY'
    return ('WORKING_PROPOSAL_TEST_ONLY' if authority().config.get('working_qualification_only')
        else 'WORKING_OWNER_CURRENT_SNAPSHOT_V1')
