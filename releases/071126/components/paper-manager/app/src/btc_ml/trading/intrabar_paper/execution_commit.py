"""Single-owner durable publication of the original engine's staged results."""
from __future__ import annotations
import contextvars, hashlib, json, os, shutil
from pathlib import Path

CURRENT = contextvars.ContextVar("execution_commit", default=None)
EXCLUSIVE_ROOT = contextvars.ContextVar("financial_exclusive_root",default=None)
MAX_INTENT_BYTES = 8 * 1024 * 1024
RESERVE_BYTES = 64 * 1024 * 1024

def digest(data):
    return hashlib.sha256(data).hexdigest()

def prefix_digest(path, size):
    h = hashlib.sha256()
    with path.open("rb") as f:
        left = size
        while left:
            chunk = f.read(min(left, 65536))
            if not chunk:
                raise RuntimeError("EXECUTION_PREFIX_TRUNCATED")
            h.update(chunk); left -= len(chunk)
    return h.hexdigest()

def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)

def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".commit-tmp")
    with tmp.open("wb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path); sync_dir(path.parent)

def save_document(path, data):
    active = CURRENT.get()
    if active is not None:
        if not active.books.owns_exclusive():
            raise RuntimeError("FINANCIAL_WRITER_REQUIRES_EX")
        active.stage_document(Path(path), data)
    elif Path(path).name == "sleeves.json":
        # Fresh unpublished, empty genesis only. Never overwrite a published
        # ledger or historical epoch outside the financial commit.
        from .books import EpochBooks
        root = Path(path).parent
        epoch = json.loads(data)["epoch_id"]
        books = EpochBooks(root / "books", paper_epoch_id=epoch)
        with books.exclusive():
            if Path(path).exists() or books.commit.pending.exists() or (books.commit.root / "head.json").exists() or books.commit.has_history() or any(books.count(t) for t in books.TABLES):
                raise RuntimeError("FINANCIAL_DOCUMENT_REQUIRES_COMMIT")
            atomic_bytes(Path(path), data)
    elif Path(path).name == "context_consumer_checkpoint.json":
        from .unified_financial_authority import save_observation_checkpoint
        save_observation_checkpoint(Path(path),data)
    else:
        atomic_bytes(Path(path), data)


HEAD_SCHEMA = "execution_committed_head_v3"
AUTHORITY_SCHEMA = "execution_open_authority_v3"
BOUND_DOCUMENTS = ("sleeves.json",)
BOUND_TABLES = ("signals", "commands", "orders", "fills", "trades", "positions", "equity_snapshots", "metrics", "blocked")

def canonical(value):
    return json.dumps(value, sort_keys=True, default=str)

def encode_authority(payload):
    raw = canonical(payload)
    return canonical({"payload": raw, "sha256": digest(raw.encode())}).encode()

def decode_authority(path, epoch):
    envelope = json.loads(path.read_bytes())
    raw = envelope["payload"].encode()
    if digest(raw) != envelope["sha256"]:
        raise RuntimeError("COMMITTED_AUTHORITY_CHECKSUM_MISMATCH")
    value = json.loads(raw)
    if value["epoch"] != epoch:
        raise RuntimeError("COMMITTED_AUTHORITY_EPOCH_MISMATCH")
    return value

def file_identity(path):
    if not path.exists():
        return None
    size = path.stat().st_size
    return {"bytes": size, "sha256": prefix_digest(path, size)}

def constituent_identities(epoch_root):
    return {rel: file_identity(epoch_root / rel) for rel in
            [*("books/" + t + ".jsonl" for t in BOUND_TABLES), *BOUND_DOCUMENTS]}

def command_association(source):
    # JSON arrays are the explicit tuple/list equivalence. Preserve order and
    # JSON scalar types; compare encoded associations, not Python bool == int.
    def normalize(value):
        if value is None or type(value) in (str, bool, int):
            return value
        if type(value) is float:
            import math
            if math.isnan(value):
                return None  # Optional absent command fields use JSON null.
            if not math.isfinite(value):
                raise RuntimeError("EXECUTION_SOURCE_TYPE_UNQUALIFIED")
            return value
        if type(value) in (list, tuple):
            return [normalize(x) for x in value]
        if type(value) is dict and all(type(k) is str for k in value):
            return {k: normalize(v) for k, v in value.items()}
        raise RuntimeError("EXECUTION_SOURCE_TYPE_UNQUALIFIED")
    normalized = normalize(source)
    if source.get("method") == "apply_s41_manager_command":
        from btc_ml.trading.command_bus import COMMAND_COLUMNS
        cmd = (normalized.get("args") or [normalized.get("kwargs", {}).get("command", {})])[0]
        extras = set(cmd) - set(COMMAND_COLUMNS)
        if extras - {"living_process", "process_strength"}:
            raise RuntimeError("EXECUTION_SOURCE_COMMAND_FIELDS_UNQUALIFIED")
        # Existing bus intentionally projects these two non-executable manager
        # annotations out. Their original values remain in the immutable source
        # receipt; they never supply OPEN economic/source authority.
        return {"method": source["method"], "command": {k: cmd.get(k) for k in COMMAND_COLUMNS}}
    return normalized

def same_association(left, right):
    if canonical(command_association(left)) != canonical(command_association(right)):
        return False
    if left.get("method") == "apply_s41_manager_command":
        a = (left.get("args") or [left.get("kwargs", {}).get("command", {})])[0]
        b = (right.get("args") or [right.get("kwargs", {}).get("command", {})])[0]
        for key in ("living_process", "process_strength"):
            if key in a and key in b and canonical(a[key]) != canonical(b[key]):
                return False
    return True


def nullable(value):
    return None if value is None or isinstance(value, float) and value != value else value

def _verify_receipt(head, root, epoch, history):
    from .financial_history import receipt_leaf, verify_member
    pub = head["publication"]
    path = root / "receipts" / (digest(pub["key"].encode()) + ".json")
    receipt = decode_authority(path, epoch)
    if (receipt.get("schema") != "execution_commit_v3" or receipt.get("status") != "COMMITTED"
            or receipt.get("key") != pub["key"] or receipt.get("publication") != pub
            or digest(path.read_bytes()) != head["receipt_sha256"]
            or canonical(pub["association"]) != canonical(command_association(receipt["source"]))):
        raise RuntimeError("COMMITTED_HEAD_RECEIPT_CONFLICT")
    verify_member(root / "history.mmr", history, pub["generation"], receipt_leaf(receipt))
    return receipt

def authenticated_prior(head, reference, epoch_root, epoch):
    """O(log generation) membership of the exact retained approval receipt."""
    root = Path(epoch_root) / "execution_commits_v1"
    path = root / "receipts" / (digest(reference["receipt_key"].encode()) + ".json")
    receipt = decode_authority(path, epoch)
    prior = {"schema": HEAD_SCHEMA, "epoch": epoch, "publication": receipt["publication"],
             "receipt_sha256": digest(path.read_bytes())}
    if head_reference(prior) != reference:
        raise RuntimeError("OPEN_CHAIN_PARENT_CONFLICT")
    _verify_receipt(prior, root, epoch, head["publication"]["history"])
    return prior, receipt

def currentness_for(head):
    return {"schema": "financial_currentness_v1", "epoch": head["epoch"],
            "head": head_reference(head), "receipt_sha256": head["receipt_sha256"],
            "history": head["publication"]["history"]}

def _verify_committed_head_raw(epoch_root, epoch, *, verify_files=True):
    from .financial_history import verify_storage
    root = Path(epoch_root) / "execution_commits_v1"
    path = root / "head.json"
    if not path.exists():
        raise RuntimeError("COMMITTED_HEAD_MIGRATION_REQUIRED")
    head = decode_authority(path, epoch); pub = head["publication"]
    if head["schema"] != HEAD_SCHEMA or pub["schema"] != HEAD_SCHEMA or pub["epoch"] != epoch:
        raise RuntimeError("COMMITTED_HEAD_SCHEMA_INVALID")
    generation = pub["generation"]
    if type(generation) is not int or generation < 1:
        raise RuntimeError("COMMITTED_HEAD_GENERATION_INVALID")
    if verify_files and (root / "pending.json").exists():
        raise RuntimeError("COMMITTED_PUBLICATION_PENDING")
    if not (root / "currentness.json").exists():
        raise RuntimeError("COMMITTED_CURRENTNESS_MISSING")
    current = decode_authority(root / "currentness.json", epoch)
    if canonical(current) != canonical(currentness_for(head)):
        if current.get("head", {}).get("generation", 0) > generation:
            raise RuntimeError("COMMITTED_HEAD_ROLLED_BACK")
        raise RuntimeError("COMMITTED_CURRENTNESS_CONFLICT")
    if pub["history"]["leaves"] != generation:
        raise RuntimeError("COMMITTED_HISTORY_GENERATION_CONFLICT")
    verify_storage(root / "history.mmr", pub["history"])
    # Immutable generation markers are hardlinks to original receipts. Even a
    # rolled-back head+small currentness+MMR prefix cannot hide retained g+1.
    marker = root / "publications" / (str(generation) + ".json")
    if (root / "publications" / (str(generation + 1) + ".json")).exists():
        raise RuntimeError("COMMITTED_HEAD_ROLLED_BACK")
    if not marker.exists() or digest(marker.read_bytes()) != head["receipt_sha256"]:
        raise RuntimeError("COMMITTED_PUBLICATION_MARKER_MISSING_OR_CONFLICTING")
    _verify_receipt(head, root, epoch, pub["history"])
    parent = pub["parent"]
    if generation == 1:
        if parent is not None:
            raise RuntimeError("COMMITTED_HEAD_PARENT_CONFLICT")
    else:
        if parent is None or parent["generation"] != generation-1:
            raise RuntimeError("COMMITTED_HEAD_PARENT_CONFLICT")
        prior, _ = authenticated_prior(head, parent, epoch_root, epoch)
        for tf, scope in pub["scopes"].items():
            old = prior["publication"]["scopes"][tf]
            if (scope["version"] not in {old["version"], old["version"]+1}
                    or scope["version"] == old["version"] and canonical(scope) != canonical(old)):
                raise RuntimeError("COMMITTED_ANCESTRY_SCOPE_CONFLICT")
            if scope["version"] != old["version"] and scope["last_change"] != {"generation": generation, "receipt_key": pub["key"]}:
                raise RuntimeError("COMMITTED_SCOPE_ORIGIN_CONFLICT")
    from .publication_witness import verify as verify_witness
    verify_witness(root / "publication.witness", head)
    scopes = pub["scopes"]
    if set(scopes) != {"M15", "M30", "H1", "H4"} or any(type(x["version"]) is not int or x["version"] < 0 for x in scopes.values()):
        raise RuntimeError("COMMITTED_SCOPE_INVALID")
    if verify_files and pub["files"] != constituent_identities(Path(epoch_root)):
        raise RuntimeError("COMMITTED_HEAD_CONSTITUENTS_SUPERSEDED_OR_CONFLICTING")
    return head

def audit_full_history(epoch_root, epoch):
    """Separate streaming complete reconciliation; never called by trading paths."""
    head = verify_committed_head(epoch_root, epoch)
    cursor = head; checked = 0
    while True:
        checked += 1; parent = cursor["publication"]["parent"]
        if parent is None:
            if cursor["publication"]["generation"] != 1:
                raise RuntimeError("COMMITTED_ANCESTRY_PARENT_CONFLICT")
            return {"generations": checked, "head": head_reference(head)}
        if parent["generation"] != cursor["publication"]["generation"]-1:
            raise RuntimeError("COMMITTED_ANCESTRY_PARENT_CONFLICT")
        cursor, _ = authenticated_prior(head, parent, epoch_root, epoch)


def head_reference(head):
    return {"generation": head["publication"]["generation"],
            "receipt_key": head["publication"]["key"], "sha256": digest(encode_authority(head))}

def open_authority(head, tf, sleeve):
    return {"schema": AUTHORITY_SCHEMA, "epoch": head["epoch"], "timeframe": tf,
            "head": head_reference(head), "receipt_sha256": head["receipt_sha256"],
            "files_sha256": digest(canonical(head["publication"]["files"]).encode()),
            "equity": sleeve["current_equity_usd"], "position_id": sleeve["open_position_id"],
            "open_risk": sleeve["open_position_risk_usd"],
            "scope_version": head["publication"]["scopes"][tf]["version"]}

class ExecutionCommit:
    def __init__(self, books):
        self.books = books
        self.root = books.root.parent / "execution_commits_v1"
        self.receipts = self.root / "receipts"
        self.receipts.mkdir(parents=True, exist_ok=True)
        sync_dir(self.root); sync_dir(self.root.parent)
        self.pending = self.root / "pending.json"
        self.rows = {}; self.documents = {}; self.poisoned = False
        # Receipt history is not a writer-local authority or publication budget.

    def has_history(self):
        # Cold fresh-genesis rejection only; not a normal trading count/scan.
        return ((self.root / "currentness.json").exists()
                or (self.root / "history.mmr").exists()
                or (self.root / "publication.witness").exists()
                or (self.root / "publications").exists()
                or next(self.receipts.glob("*.json"), None) is not None)

    def _phase(self, name):
        # Fault-injection seam; production performs no action here.
        pass

    def receipt_path(self, key):
        return self.receipts / (digest(key.encode()) + ".json")

    def load(self, path):
        envelope = json.loads(path.read_bytes())
        raw = envelope["payload"].encode()
        if digest(raw) != envelope["sha256"]:
            raise RuntimeError("EXECUTION_INTENT_CHECKSUM_MISMATCH")
        result = json.loads(raw)
        if result["epoch"] != self.books.paper_epoch_id:
            raise RuntimeError("EXECUTION_INTENT_EPOCH_MISMATCH")
        return result

    def encode(self, payload):
        raw = json.dumps(payload, sort_keys=True, default=str)
        return json.dumps({"payload": raw, "sha256": digest(raw.encode())}, sort_keys=True).encode()

    def stage_document(self, path, data):
        relative = path.resolve().relative_to(self.books.root.parent.resolve())
        name = str(relative)
        if name not in self.documents:
            self.documents[name] = {"before": digest(path.read_bytes()) if path.exists() else None}
        self.documents[name]["data"] = data.decode()
        if name == "context_consumer_checkpoint.json":
            self.documents[name].setdefault("observation_before_data",path.read_text())

    def initialize_new_epoch(self, engine):
        """Explicit fresh-empty-epoch authority; never migrate historical books."""
        with self.books.exclusive():
            if (self.pending.exists() or (self.root / "head.json").exists()
                    or any(self.books._path(t).stat().st_size for t in self.books.TABLES)
                    or self.has_history()):
                raise RuntimeError("COMMITTED_GENESIS_REQUIRES_EMPTY_NEW_EPOCH")
            if engine.sleeves is None or any(s.open_position_id or s.closed_trades_count
                    or s.cumulative_realized_net_pnl_usd for s in engine.sleeves.sleeves.values()):
                raise RuntimeError("COMMITTED_GENESIS_REQUIRES_EMPTY_NEW_EPOCH")
            return self.run(self.books.paper_epoch_id + "|initialize_new_epoch",
                lambda: (engine.sleeves.save(), engine.consumer.save()), engine,
                {"method": "initialize_new_epoch", "args": [], "kwargs": {}}, initialize=True)

    def materialize(self, intent):
        if not self.books.owns_exclusive():
            raise RuntimeError("EXECUTION_MATERIALIZE_REQUIRES_EX")
        if intent.get("schema") != "execution_commit_v3" or (intent.get("publication") is not None and intent["publication"].get("schema") != HEAD_SCHEMA):
            raise RuntimeError("EXECUTION_SCHEMA_MIGRATION_REQUIRED")
        head_path = self.root / "head.json"
        if head_path.exists() and decode_authority(head_path, self.books.paper_epoch_id).get("schema") != HEAD_SCHEMA:
            raise RuntimeError("COMMITTED_SCHEMA_MIGRATION_REQUIRED")
        # Before any recovery materialization, authenticate exact parent and
        # exact pending successor witness bytes. Never rebuild a lost journal.
        witness_previous = None
        witness_head = None
        if intent.get("publication") is not None:
            publication = intent["publication"]
            receipt = {**intent, "status": "COMMITTED"}
            witness_head = {"schema": HEAD_SCHEMA, "epoch": self.books.paper_epoch_id,
                            "publication": publication, "receipt_sha256": digest(self.encode(receipt))}
            if publication["parent"] is not None:
                parent_path = self.receipt_path(publication["parent"]["receipt_key"])
                parent = self.load(parent_path)
                witness_previous = {"schema": HEAD_SCHEMA, "epoch": self.books.paper_epoch_id,
                    "publication": parent["publication"], "receipt_sha256": digest(parent_path.read_bytes())}
                if head_reference(witness_previous) != publication["parent"]:
                    raise RuntimeError("COMMITTED_WITNESS_RECOVERY_PARENT_CONFLICT")
            from .publication_witness import recovery_plan
            recovery_plan(self.root / "publication.witness", witness_previous, witness_head)
        for table, entry in intent["books"].items():
            path = self.books._path(table); base = entry["offset"]
            data = entry["data"].encode()
            if path.stat().st_size < base or prefix_digest(path, base) != entry["prefix_sha256"]:
                raise RuntimeError("EXECUTION_BOOK_PREFIX_MISMATCH")
            with path.open("r+b") as f:
                f.seek(base); tail = f.read(len(data) + 1)
                if len(tail) > len(data) or not data.startswith(tail):
                    raise RuntimeError("EXECUTION_BOOK_UNEXPECTED_TAIL")
                f.seek(base + len(tail)); f.write(data[len(tail):]); f.flush(); os.fsync(f.fileno())
            self._phase("book:" + table)
        for relative, entry in intent["documents"].items():
            path = self.books.root.parent / relative
            if path.resolve().parent != self.books.root.parent.resolve():
                raise RuntimeError("EXECUTION_DOCUMENT_PATH_INVALID")
            data = entry["data"].encode()
            current = digest(path.read_bytes()) if path.exists() else None
            if current not in {entry["before"], digest(data)}:
                raise RuntimeError("EXECUTION_DOCUMENT_UNEXPECTED_STATE")
            atomic_bytes(path, data); self._phase("document:" + relative)
        sync_dir(self.books.root)
        self._phase("before_receipt")
        pub = intent.get("publication")
        if pub is not None:
            if pub["files"] != constituent_identities(self.books.root.parent):
                raise RuntimeError("COMMITTED_PUBLICATION_CONSTITUENTS_CONFLICT")
            if (self.root / "head.json").exists():
                current = decode_authority(self.root / "head.json", self.books.paper_epoch_id)
                # During recovery, MMR/currentness may already contain the exact
                # pending successor. Do not accept an unrelated third publication.
                anchor_path = self.root / "currentness.json"
                if not anchor_path.exists():
                    raise RuntimeError("COMMITTED_CURRENTNESS_MISSING")
                anchor = decode_authority(anchor_path, self.books.paper_epoch_id)
                if canonical(anchor) != canonical(currentness_for(current)):
                    expected = {"schema": HEAD_SCHEMA, "epoch": self.books.paper_epoch_id,
                        "publication": pub, "receipt_sha256": digest(self.receipt_path(intent["key"]).read_bytes())}
                    if canonical(anchor) != canonical(currentness_for(expected)):
                        raise RuntimeError("COMMITTED_RECOVERY_CURRENTNESS_CONFLICT")
                ref = head_reference(current)
                if ref != pub["parent"] and current["publication"] != pub:
                    raise RuntimeError("COMMITTED_HEAD_ADVANCE_CONFLICT")
            elif pub["generation"] != 1 or pub["parent"] is not None:
                raise RuntimeError("COMMITTED_HEAD_MISSING_DURING_RECOVERY")
        receipt = {**intent, "status": "COMMITTED"}
        existing = self.receipt_path(intent["key"])
        if existing.exists() and canonical(self.load(existing)) != canonical(receipt):
            raise RuntimeError("EXECUTION_RECEIPT_INVALID")
        atomic_bytes(self.receipt_path(intent["key"]), self.encode(receipt))
        self._phase("after_receipt")
        if pub is not None:
            head = {"schema": HEAD_SCHEMA, "epoch": self.books.paper_epoch_id,
                    "publication": pub, "receipt_sha256": digest(existing.read_bytes())}
            from .financial_history import receipt_leaf, plan, append_nodes, verify_storage
            previous = None
            if pub["parent"] is not None:
                parent_path = self.receipt_path(pub["parent"]["receipt_key"])
                parent = self.load(parent_path)
                previous = parent["publication"]["history"]
                prior = {"schema": HEAD_SCHEMA, "epoch": self.books.paper_epoch_id,
                    "publication": parent["publication"], "receipt_sha256": digest(parent_path.read_bytes())}
                if head_reference(prior) != pub["parent"]:
                    raise RuntimeError("COMMITTED_RECOVERY_PARENT_CONFLICT")
            history, nodes = plan(previous, receipt_leaf(receipt))
            if history != pub["history"]:
                raise RuntimeError("COMMITTED_HISTORY_PLAN_CONFLICT")
            # Retain one immutable, directly addressable publication witness per
            # generation. A hardlink needs no second receipt data allocation.
            markers = self.root / "publications"
            markers.mkdir(exist_ok=True); sync_dir(self.root)
            marker = markers / (str(pub["generation"]) + ".json")
            self._phase("before_publication_marker")
            if marker.exists():
                if digest(marker.read_bytes()) != head["receipt_sha256"]:
                    raise RuntimeError("COMMITTED_PUBLICATION_MARKER_CONFLICT")
            else:
                os.link(existing, marker)
            sync_dir(markers); self._phase("after_publication_marker")
            self._phase("before_history")
            append_nodes(self.root / "history.mmr", previous, nodes); sync_dir(self.root)
            self._phase("after_history")
            verify_storage(self.root / "history.mmr", history)
            self._phase("before_currentness")
            atomic_bytes(self.root / "currentness.json", encode_authority(currentness_for(head)))
            self._phase("after_currentness")
            self._phase("before_head")
            if not (self.root / "head.json").exists() or (self.root / "head.json").read_bytes() != encode_authority(head):
                atomic_bytes(self.root / "head.json", encode_authority(head))
            self._phase("after_head")
            self._phase("before_witness")
            from .publication_witness import append as append_witness
            append_witness(self.root / "publication.witness", witness_previous, head, self._phase)
            self._phase("after_witness")
        self._phase("before_pending_cleanup")
        self.pending.unlink(missing_ok=True); sync_dir(self.root)
        self._phase("after_pending_cleanup")

    def recover(self):
        if self.pending.exists():
            from .unified_financial_authority import validate_pending
            validate_pending(self.books.root.parent,self.books.paper_epoch_id)
            intent = self.load(self.pending)
            # Recovery is performed before engine positions, sleeves and cursors load.
            self.materialize(intent)

    def validate_staged_ledger(self):
        entry = self.documents.get("sleeves.json")
        if entry is None:
            return
        proposed = json.loads(entry["data"])
        path = self.books.root.parent / "sleeves.json"
        before = json.loads(path.read_text()) if path.exists() else None
        touched = {json.loads(line).get("timeframe") for table in ("positions", "orders", "fills", "trades") for line in self.rows.get(table, [])}
        if self.source.get("method") in {"apply_s41_manager_command", "process_context_event"}:
            argument = (self.source.get("args") or list(self.source.get("kwargs", {}).values()))[0]
            touched.add(argument.get("timeframe"))
        if self.source.get("kwargs", {}).get("timeframe") in {"M15", "M30", "H1", "H4"}:
            touched.add(self.source["kwargs"]["timeframe"])
        owned = {}
        for row in self.books.open_positions():
            tf = row["timeframe"]
            if tf in owned:
                raise RuntimeError("FINANCIAL_MULTIPLE_OWN_POSITIONS")
            owned[tf] = row
        for tf, state in proposed["sleeves"].items():
            if before and canonical(before["sleeves"][tf]) != canonical(state) and tf not in touched:
                raise RuntimeError("FINANCIAL_UNRELATED_SCOPE_OVERWRITE")
            position = owned.get(tf)
            if state["open_position_id"] != (position["position_id"] if position else None):
                raise RuntimeError("FINANCIAL_OCCUPANCY_CONFLICT")
            if position and float(state["open_position_risk_usd"]) != float(position["risk_amount_usd"]):
                raise RuntimeError("FINANCIAL_RISK_CONFLICT")

    def scopes_after(self, head, engine):
        before = head["publication"]["scopes"] if head else {}
        out = {}
        for tf in ("M15", "M30", "H1", "H4"):
            doc = self.documents.get("sleeves.json")
            ledger = json.loads(doc["data"] if doc else (self.books.root.parent / "sleeves.json").read_text())
            state = ledger["sleeves"][tf]
            old = before.get(tf)
            changed = old is not None and canonical(old["sleeve"]) != canonical(state)
            # Own position/order/fill/trade effects advance even if equity or
            # occupancy later returns to the same value (ABA).
            changed = changed or any(json.loads(line).get("timeframe") == tf
                for table in ("positions", "orders", "fills", "trades")
                for line in self.rows.get(table, []))
            out[tf] = {"version": (old["version"] if old else 0) + int(changed),
                       "sleeve": state,
                       "last_change": old.get("last_change") if old else None}
        return out

    def run(self, key, callback, engine, source, *, initialize=False):
        if not self.books.owns_exclusive():
            raise RuntimeError("EXECUTION_COMMIT_REQUIRES_EX")
        if self.poisoned: raise RuntimeError("EXECUTION_COMMIT_RESTART_REQUIRED")
        if self.pending.exists(): raise RuntimeError("EXECUTION_UNRESOLVED_INTENT")
        receipt = self.receipt_path(key)
        if receipt.exists():
            saved = self.load(receipt)
            if saved.get("schema") != "execution_commit_v3":
                raise RuntimeError("EXECUTION_RECEIPT_MIGRATION_REQUIRED")
            if (saved["key"] != key or saved["status"] != "COMMITTED"
                    or not same_association(saved["source"], source)):
                raise RuntimeError("EXECUTION_RECEIPT_INVALID")
            if saved.get("terminal", True):
                method = source["method"]
                if method in {"update_from_trade", "update_bbo_from_market"}:
                    return []
                if method == "process_context_event":
                    if any(action.get("status") == "ENTERED" for action in saved["result"] or []):
                        from .consumer import idempotency_key
                        event = (source["args"] or [source["kwargs"].get("event", {})])[0]
                        return [{"status": "DUPLICATE_PREVENTED", "key": idempotency_key(
                            paper_epoch_id=engine.epoch.paper_epoch_id,
                            context_event_id=str(event.get("context_event_id") or event.get("event_id")),
                            timeframe=str(event.get("timeframe") or "").upper(),
                            action="ENTRY_" + engine._event_side(event))}]
                    return []
                result = saved["result"]
                command = (source["args"] or [source["kwargs"].get("command", {})])[0]
                if str(command.get("intent", "")).startswith("OPEN") and result and result.get("status") == "ENTERED":
                    return {"status": "ENTRY_BLOCKED_DUPLICATE_COMMAND", "timeframe": command.get("timeframe"), "context_event_id": command.get("command_id")}
                return {**result, "execution_replayed": True} if isinstance(result, dict) else result
        if (self.root / "head.json").exists():
            base_head = verify_committed_head(self.books.root.parent, self.books.paper_epoch_id)
        else:
            base_head = None  # Headless legacy CLOSE only; OPEN still fails closed.
        engine._refresh_financial_state(base_head)
        self.source = source
        self.rows = {}; self.documents = {}
        checkpoint_before = engine.consumer.checkpoint.to_dict()
        occupancy_before = {tf: pos.position_id for tf, pos in engine.positions.items()}
        token = CURRENT.set(self)
        try:
            result = callback()
            if self.rows or engine.consumer.checkpoint.to_dict() != checkpoint_before:
                engine.consumer.save()
            if not self.rows and set(self.documents) <= {"context_consumer_checkpoint.json"} and not (set(engine.consumer.checkpoint.processed_keys)-set(checkpoint_before["processed_keys"])) - {k for k in engine.consumer.checkpoint.processed_keys if k.endswith("|CONSUME_OBSERVE")}:
                for name, entry in self.documents.items():
                    atomic_bytes(self.books.root.parent / name, entry["data"].encode())
                return result
            if not self.rows and not self.documents:
                return result
            self.validate_staged_ledger()
            intent = {"schema": "execution_commit_v3", "epoch": self.books.paper_epoch_id,
                      "key": key, "status": "INTENT", "result": result, "source": source,
                      "occupancy_before": occupancy_before, "occupancy_after": {tf: pos.position_id for tf, pos in engine.positions.items()},
                      "terminal": bool(any(self.rows.get(t) for t in ("orders", "fills", "trades", "positions")) or set(engine.consumer.checkpoint.processed_keys) != set(checkpoint_before["processed_keys"])),
                      "books": {}, "documents": self.documents}
            for table, lines in self.rows.items():
                path = self.books._path(table); size = path.stat().st_size
                intent["books"][table] = {"offset": size, "prefix_sha256": prefix_digest(path, size), "data": "".join(lines)}
            # A transient no-fill attempt is not the terminal command receipt.
            # Preserve its immutable provenance under an attempt key; a later
            # live BBO can still complete the same pending command.
            intent["source_key"] = key
            if not intent["terminal"]:
                intent["key"] = key + "|attempt|" + digest(self.encode(intent))
            if base_head is not None or initialize:
                files = constituent_identities(self.books.root.parent)
                for table, entry in intent["books"].items():
                    path = self.books._path(table); h = hashlib.sha256()
                    with path.open("rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""): h.update(chunk)
                    data_bytes = entry["data"].encode(); h.update(data_bytes)
                    files["books/" + table + ".jsonl"] = {"bytes": entry["offset"] + len(data_bytes), "sha256": h.hexdigest()}
                for name, entry in intent["documents"].items():
                    if name in BOUND_DOCUMENTS:
                        raw = entry["data"].encode(); files[name] = {"bytes": len(raw), "sha256": digest(raw)}
                parent = head_reference(base_head) if base_head is not None else None
                intent["publication"] = {"schema": HEAD_SCHEMA, "epoch": self.books.paper_epoch_id,
                    "generation": parent["generation"] + 1 if parent else 1,
                    "parent": parent, "key": intent["key"], "association": command_association(source), "files": files,
                    "scopes": self.scopes_after(base_head, engine)}
                for tf, scope in intent["publication"]["scopes"].items():
                    old_version = base_head["publication"]["scopes"][tf]["version"] if base_head else 0
                    if scope["version"] != old_version:
                        scope["last_change"] = {"generation": intent["publication"]["generation"], "receipt_key": intent["key"]}
                from .financial_history import plan, receipt_leaf
                previous = base_head["publication"]["history"] if base_head else None
                intent["publication"]["history"], _ = plan(previous, receipt_leaf(intent))
            else:
                intent["publication"] = None
            data = self.encode(intent)
            if len(data) > MAX_INTENT_BYTES:
                raise RuntimeError("EXECUTION_COMMIT_STORAGE_BOUND")
            if shutil.disk_usage(self.root).free < RESERVE_BYTES + len(data) * 3:
                raise OSError("EXECUTION_COMMIT_DISK_RESERVE")
            self._phase("before_intent")
            atomic_bytes(self.pending, data); self._phase("after_intent")
            self.materialize(intent)
            return result
        except BaseException:
            # Never continue callbacks on mutated RAM or partially published books.
            self.poisoned = True
            market = getattr(engine, "execution_market", None)
            if market is not None:
                from .execution_market_state import ExecutionMarketState
                market._halted = True
                market.state._set(ExecutionMarketState.UNSAFE, "execution_commit_failed")
            raise
        finally:
            CURRENT.reset(token); self.rows = {}; self.documents = {}


def verify_committed_head(epoch_root, epoch, *, verify_files=True):
    import fcntl,threading
    from .unified_financial_authority import check_locked
    root=Path(epoch_root).resolve()
    def verified():
        check_locked(root,epoch)
        return _verify_committed_head_raw(root,epoch,verify_files=verify_files)
    if EXCLUSIVE_ROOT.get()==(root,os.getpid(),threading.get_ident()):return verified()
    with (root/'books/.writer.lock').open('rb') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_SH|fcntl.LOCK_NB)
        try:return verified()
        finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
