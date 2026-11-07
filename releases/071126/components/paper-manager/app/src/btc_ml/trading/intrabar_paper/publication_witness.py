"""Bounded append-only publication witness. No balances or entry authority.

The retained tail is an independent local rollback anchor, not an external
monotonic counter. Coordinated rollback of all local anchors is not detectable.
All append/recovery operations are called by the original EX financial writer.
"""
import hashlib, os, struct

MAGIC = b"BTCWIT01"
RECORD_BYTES = 176
ZERO = bytes(32)
DOMAIN = b"financial-publication-witness-v1\x00"

def sha(data):
    return hashlib.sha256(data).digest()

def record(head, previous):
    from .execution_commit import head_reference
    ref = head_reference(head)
    prefix = (MAGIC + struct.pack(">Q", ref["generation"]) + sha(head["epoch"].encode())
              + bytes.fromhex(ref["sha256"]) + bytes.fromhex(head["receipt_sha256"])
              + (sha(previous) if previous else ZERO))
    return prefix + sha(DOMAIN + prefix)

def validate(data, ordinal, epoch):
    if (len(data) != RECORD_BYTES or data[:8] != MAGIC
            or struct.unpack(">Q", data[8:16])[0] != ordinal
            or data[16:48] != sha(epoch.encode())
            or data[144:176] != sha(DOMAIN + data[:144])):
        raise RuntimeError("COMMITTED_WITNESS_INTEGRITY_CONFLICT")

def tail_at(f, count, epoch):
    if not count:
        return None
    start = max(0, count-2)
    f.seek(start*RECORD_BYTES)
    data = f.read((count-start)*RECORD_BYTES)
    current = data[-RECORD_BYTES:]
    validate(current, count, epoch)
    if count == 1:
        if current[112:144] != ZERO:
            raise RuntimeError("COMMITTED_WITNESS_PARENT_CONFLICT")
    else:
        previous = data[:RECORD_BYTES]
        validate(previous, count-1, epoch)
        if current[112:144] != sha(previous):
            raise RuntimeError("COMMITTED_WITNESS_PARENT_CONFLICT")
    return current

def binds(data, head):
    from .execution_commit import head_reference
    return (data[48:80] == bytes.fromhex(head_reference(head)["sha256"])
            and data[80:112] == bytes.fromhex(head["receipt_sha256"]))

def verify(path, head):
    if not path.exists():
        raise RuntimeError("COMMITTED_WITNESS_MISSING")
    g = head["publication"]["generation"]
    size = path.stat().st_size
    if size != g*RECORD_BYTES:
        raise RuntimeError("COMMITTED_HEAD_ROLLED_BACK_OR_WITNESS_LENGTH_CONFLICT")
    with path.open("rb") as f:
        current = tail_at(f, g, head["epoch"])
    if not binds(current, head):
        raise RuntimeError("COMMITTED_WITNESS_HEAD_CONFLICT")

def recovery_plan(path, previous_head, head):
    """Only exact parent + exact pending append prefix is recoverable."""
    g = head["publication"]["generation"]
    base = (g-1)*RECORD_BYTES
    if (previous_head is None) != (g == 1):
        raise RuntimeError("COMMITTED_WITNESS_RECOVERY_PARENT_CONFLICT")
    if previous_head is not None and previous_head["publication"]["generation"] != g-1:
        raise RuntimeError("COMMITTED_WITNESS_RECOVERY_PARENT_CONFLICT")
    if not path.exists():
        if base:
            raise RuntimeError("COMMITTED_WITNESS_MISSING")
        return 0, record(head, None), 0
    size = path.stat().st_size
    if not base <= size <= base+RECORD_BYTES:
        raise RuntimeError("COMMITTED_WITNESS_RECOVERY_LENGTH_CONFLICT")
    with path.open("rb") as f:
        previous = tail_at(f, g-1, head["epoch"])
        if previous_head is not None and not binds(previous, previous_head):
            raise RuntimeError("COMMITTED_WITNESS_RECOVERY_PARENT_CONFLICT")
        expected = record(head, previous)
        f.seek(base); actual = f.read(RECORD_BYTES+1)
        if not expected.startswith(actual):
            raise RuntimeError("COMMITTED_WITNESS_RECOVERY_APPEND_CONFLICT")
    return base, expected, len(actual)

def append(path, previous_head, head, phase):
    from .execution_commit import sync_dir
    base, expected, retained = recovery_plan(path, previous_head, head)
    with path.open("r+b" if path.exists() else "w+b") as f:
        f.seek(base+retained)
        phase("before_witness_write")
        f.write(expected[retained:]); phase("after_witness_write")
        f.flush(); phase("before_witness_fsync")
        os.fsync(f.fileno()); phase("after_witness_fsync")
    sync_dir(path.parent)
    verify(path, head)
