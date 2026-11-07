"""Fail closed before creating execution writers on unsupported storage."""
import fcntl, os, subprocess, sys, uuid
from pathlib import Path

def verify_execution_filesystem(root):
    if sys.platform != 'linux':
        raise RuntimeError('EXECUTION_STATE_REQUIRES_LINUX_FILESYSTEM')
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    mounts = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        mount = Path(left.split()[4].replace('\\040', ' '))
        if root == mount or mount in root.parents:
            mounts.append((len(str(mount)), right.split()[0]))
    fs = max(mounts)[1]
    if fs not in {'ext4', 'xfs', 'btrfs', 'tmpfs', 'overlay'}:
        raise RuntimeError('EXECUTION_STATE_FILESYSTEM_UNSUPPORTED:' + fs)
    path = root / ('.capability-probe-' + uuid.uuid4().hex)
    try:
        with path.open('w') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            script = '''import sys,fcntl
with open(sys.argv[1], 'r') as f:
 try: fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError: sys.exit(0)
 sys.exit(19)
'''
            result = subprocess.run([sys.executable, '-c', script, str(path)], timeout=5)
            if result.returncode != 0:
                raise RuntimeError('EXECUTION_STATE_LOCK_EXCLUSIVITY_UNSUPPORTED')
            return {'filesystem': fs, 'cross_process_exclusivity': True}
    finally:
        path.unlink(missing_ok=True)
