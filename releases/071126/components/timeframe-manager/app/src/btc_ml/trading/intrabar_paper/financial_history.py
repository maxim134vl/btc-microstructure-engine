"""Append-only Merkle mountain range for authenticated publication membership.

Only history hashes, not balances. Under the existing writer EX, pending intent
binds append bytes and fsync order. Readers use O(log(g)) membership reads, never
receipt enumeration. All receipts remain original immutable transaction evidence.
"""
import hashlib, json, os

def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()

def receipt_leaf(receipt):
    core = dict(receipt, status="COMMITTED")
    core["publication"] = dict(core["publication"])
    core["publication"].pop("history", None)
    return hash_bytes(b"financial-history-leaf-v1\x00" + json.dumps(core, sort_keys=True, default=str).encode())

def combine(left, right):
    return hash_bytes(b"financial-history-node-v1\x00" + bytes.fromhex(left) + bytes.fromhex(right))

def plan(previous, leaf):
    n = previous["leaves"] if previous else 0
    peaks = [dict(p) for p in previous["peaks"]] if previous else []
    count = previous["nodes"] if previous else 0
    appended = [leaf]; h = 0; index = count
    while peaks and peaks[-1]["height"] == h:
        leaf = combine(peaks.pop()["sha256"], leaf)
        appended.append(leaf); h += 1; index += 1
    peaks.append({"height": h, "index": index, "sha256": leaf})
    meta = {"schema": "financial_history_mmr_v1", "leaves": n + 1,
            "nodes": count + len(appended), "peaks": peaks}
    validate_shape(meta)
    return meta, b"".join(bytes.fromhex(x) for x in appended)

def validate_shape(meta):
    n = meta["leaves"]
    if meta["schema"] != "financial_history_mmr_v1" or type(n) is not int or n < 1 or type(meta["nodes"]) is not int or meta["nodes"] != 2*n-n.bit_count():
        raise RuntimeError("COMMITTED_HISTORY_SHAPE_INVALID")
    expected = []; offset = 0
    for height in range(n.bit_length()-1, -1, -1):
        if n & (1 << height):
            nodes = (1 << (height+1))-1
            expected.append((height, offset+nodes-1)); offset += nodes
    if [(p["height"], p["index"]) for p in meta["peaks"]] != expected:
        raise RuntimeError("COMMITTED_HISTORY_PEAK_CONFLICT")
    for p in meta["peaks"]:
        if len(bytes.fromhex(p["sha256"])) != 32:
            raise RuntimeError("COMMITTED_HISTORY_HASH_INVALID")

def read_node(f, index):
    f.seek(index*32); data = f.read(32)
    if len(data) != 32:
        raise RuntimeError("COMMITTED_HISTORY_TRUNCATED")
    return data.hex()

def verify_storage(path, meta, *, allow_tail=False):
    validate_shape(meta)
    size = path.stat().st_size
    expected = meta["nodes"]*32
    if size < expected or (not allow_tail and size != expected):
        raise RuntimeError("COMMITTED_HEAD_ROLLED_BACK_OR_HISTORY_LENGTH_CONFLICT")
    with path.open("rb") as f:
        for p in meta["peaks"]:
            if read_node(f, p["index"]) != p["sha256"]:
                raise RuntimeError("COMMITTED_HISTORY_PEAK_CONFLICT")

def verify_member(path, meta, ordinal, leaf):
    validate_shape(meta)
    if type(ordinal) is not int or not 1 <= ordinal <= meta["leaves"]:
        raise RuntimeError("COMMITTED_HISTORY_MEMBERSHIP_INVALID")
    wanted = ordinal-1; node_start = 0; leaf_start = 0
    for peak in meta["peaks"]:
        leaves = 1 << peak["height"]
        if wanted < leaf_start+leaves:
            local = wanted-leaf_start; start = node_start; width = leaves; proof = []
            with path.open("rb") as f:
                while width > 1:
                    half = width//2; child_nodes = 2*half-1
                    if local < half:
                        proof.append((False, read_node(f, start+2*child_nodes-1)))
                    else:
                        proof.append((True, read_node(f, start+child_nodes-1)))
                        start += child_nodes; local -= half
                    width = half
                if read_node(f, start) != leaf:
                    raise RuntimeError("COMMITTED_HISTORY_LEAF_CONFLICT")
            value = leaf
            for is_left, sibling in reversed(proof):
                value = combine(sibling, value) if is_left else combine(value, sibling)
            if value != peak["sha256"]:
                raise RuntimeError("COMMITTED_HISTORY_MEMBERSHIP_CONFLICT")
            return
        leaf_start += leaves; node_start += 2*leaves-1
    raise RuntimeError("COMMITTED_HISTORY_MEMBERSHIP_INVALID")

def append_nodes(path, previous, data):
    base = previous["nodes"]*32 if previous else 0
    if previous:
        verify_storage(path, previous, allow_tail=True)
    elif path.exists() and path.stat().st_size > len(data):
        raise RuntimeError("COMMITTED_HISTORY_UNEXPECTED_GENESIS")
    # Replay accepts precisely a prefix of the pending append, never foreign tail.
    with path.open("r+b" if path.exists() else "w+b") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() < base or f.tell() > base+len(data):
            raise RuntimeError("COMMITTED_HISTORY_UNEXPECTED_TAIL")
        f.seek(base); tail = f.read(len(data)+1)
        if not data.startswith(tail):
            raise RuntimeError("COMMITTED_HISTORY_UNEXPECTED_TAIL")
        f.seek(base+len(tail)); f.write(data[len(tail):]); f.flush(); os.fsync(f.fileno())
