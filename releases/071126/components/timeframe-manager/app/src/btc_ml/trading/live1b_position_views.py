"""Read-only LIVE1B epoch open-position views for the S4.1 manager.

Used by hybrid mode: manager emits commands; LIVE1B owns books/capital/PnL.
"""

from __future__ import annotations

import json
import copy
import os
import threading
import fcntl
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


class Live1BBooksUnavailable(RuntimeError):
    """No committed, mutually consistent execution snapshot is available."""



def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, 1):
                if not raw.strip():
                    continue
                item = json.loads(raw)
                if not isinstance(item, dict):
                    raise ValueError(f"NON_OBJECT_BOOK_ROW:{line_number}")
                rows.append(item)
    except (OSError, UnicodeError, ValueError) as exc:
        raise Live1BBooksUnavailable(f"LIVE1B_BOOKS_INPUT_UNAVAILABLE:{path.name}") from exc
    return rows


def _sf(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def active_live1b_epoch_id(repo_root: Path | None = None) -> str | None:
    root = repo_root or ROOT
    active = _read_json(root / "data/trading/paper_epochs/active.json")
    if str(active.get("epoch_status") or "").upper() != "ACTIVE":
        return None
    epoch_id = active.get("paper_epoch_id")
    return str(epoch_id) if epoch_id else None


def _latest_open_by_timeframe(positions_path: Path, *, rows=None) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(positions_path) if rows is None else rows:
        pid = str(row.get("position_id") or "").strip()
        if not pid:
            continue
        latest[pid] = row
    opens: dict[str, dict[str, Any]] = {}
    for row in latest.values():
        if str(row.get("status") or "").upper() != "OPEN":
            continue
        tf = str(row.get("timeframe") or "").upper()
        if tf:
            if tf in opens:
                raise Live1BBooksUnavailable("LIVE1B_BOOKS_DUPLICATE_OPEN_TIMEFRAME")
            opens[tf] = row
    return opens


# Reader-owned confirmation only; never a writer EX continuation certificate.
_READER_CONFIRMATION = threading.local()


def _confirmed_reader_head(root: Path, epoch: str, shared_lock):
    """Reuse this reader's proof only when every proof input remains unchanged."""
    from .intrabar_paper import execution_commit as ec
    from .intrabar_paper import financial_authority_runtime as runtime
    from .intrabar_paper.cold_forward_guard import verify_committed_head_cooperative, _contains_symlink
    from .intrabar_paper.cursor_ack import observe_only
    from .intrabar_paper.verified_continuation import immutable_paths, signature, prefix_sha

    root = root.resolve()
    ar = root / "execution_commits_v1"

    def pins():
        if (ar / "pending.json").exists():
            raise RuntimeError("PAPER_FINANCIAL_RECOVERY_REQUIRED")
        auth = runtime.authority()
        if auth.root.resolve() != root or runtime.epoch() != epoch:
            raise RuntimeError("READER_FINANCIAL_AUTHORITY_CONFLICT")
        paths = immutable_paths(root)
        # Presence/path safety remains mandatory for independent operational
        # members; their changing contents do not prove or revoke financial state.
        for member in runtime.policy()["state_members"]:
            path = runtime.member_path(runtime.case_root(), member["path"])
            if not path.is_file():
                raise RuntimeError("LEGACY_MEMBER_MISSING:" + member["path"])
        if _contains_symlink(root):
            raise RuntimeError("SYMLINK_FORBIDDEN")
        from .intrabar_paper.legacy_admission import TABLES
        if {p.name for p in (root/"books").iterdir()} != {".writer.lock"}|{t+".jsonl" for t in TABLES}:
            raise RuntimeError("UNKNOWN_FINANCIAL_BOOK")
        paths.update(root/"books"/(table+".jsonl") for table in TABLES)
        paths.update(root/name for name in ("sleeves.json","s41_command_cursor.json",
                                           "s41_recovery_open_barrier.json","trading_contract.json"))
        directories = [ar]
        for path in ar.rglob("*"):
            if path.is_dir():
                directories.append(path)
            else:
                paths.add(path)
        directory_pins = []
        for path in directories:
            st = path.stat(follow_symlinks=False)
            directory_pins.append((str(path),st.st_dev,st.st_ino,st.st_mtime_ns,st.st_ctime_ns))
        # Unrelated heartbeat/WAL updates can change root directory metadata.
        root_st = root.stat();books_st = (root/"books").stat()
        return (os.getpid(), threading.get_ident(), str(root), epoch,
                (root_st.st_dev,root_st.st_ino,books_st.st_dev,books_st.st_ino),
                auth.config_sha256, ec.canonical(dict(auth.config)),
                tuple(sorted(directory_pins)),
                tuple(sorted((str(path),signature(path)) for path in paths)))

    def current_identity():
        before = pins()
        checkpoint = root/"context_consumer_checkpoint.json"
        checkpoint_pin = signature(checkpoint)
        error = None
        # Native payload hashing and history fingerprints must not hold SH.
        fcntl.flock(shared_lock.fileno(), fcntl.LOCK_UN)
        try:
            try:
                head = ec._verify_committed_head_raw(root, epoch)
                cursor = checkpoint.read_bytes()
                history = tuple((name,prefix_sha(ar/name,(ar/name).stat().st_size))
                                for name in ("history.mmr","publication.witness"))
            except Exception as exc:
                error = exc
        finally:
            fcntl.flock(shared_lock.fileno(), fcntl.LOCK_SH)
        if pins() != before or signature(checkpoint) != checkpoint_pin:
            return None
        if error is not None:
            raise error
        return before, ec.canonical(head), history, head, cursor

    try:
        current = current_identity()
        saved = getattr(_READER_CONFIRMATION, "value", None)
        if current is not None and saved is not None and saved[:3] == current[:3]:
            # The only unreceipted financial-document advance already permitted
            # by GuardExtension.final_document: monotonic CONSUME_OBSERVE only.
            observe_only(json.loads(saved[3]), json.loads(current[4]))
            _READER_CONFIRMATION.value = (*current[:3], current[4])
            return copy.deepcopy(current[3])
        _READER_CONFIRMATION.value = None
        head = verify_committed_head_cooperative(root, epoch, shared_lock)
        # Full proof may follow a moving writer. Seed reuse only if the complete
        # input set was stable across this proof; otherwise recheck next cycle.
        if (current is not None and pins() == current[0] and ec.canonical(head) == current[1]
                and (root/"context_consumer_checkpoint.json").read_bytes() == current[4]):
            _READER_CONFIRMATION.value = (*current[:3], current[4])
        return head
    except BaseException:
        _READER_CONFIRMATION.value = None
        raise


# Derived statistics only. This is not a verifier or a financial certificate.
_TRADE_TOTALS_CACHE = threading.local()


def _historical_trade_totals(books, epoch, timeframes, committed_head):
    """Called under SH only after native current-state verification succeeds.

    Every invocation of live1b_trader_views first verifies books/receipts and
    currentness through _confirmed_reader_head. The key alone is never proof.
    Current positions, sleeve capital and mark-price risk are not cached here.
    """
    from .intrabar_paper import execution_commit as ec
    key = (os.getpid(), str(books.parent.resolve()), epoch, tuple(timeframes),
           ec.canonical(committed_head))
    saved = getattr(_TRADE_TOTALS_CACHE, "value", None)
    if saved is not None and saved[0] == key:
        return copy.deepcopy(saved[1])
    _TRADE_TOTALS_CACHE.value = None
    totals = {tf: {"count": 0, "realized": 0.0, "fees": 0.0, "slippage": 0.0}
              for tf in timeframes}
    for trade in _read_jsonl(books / "trades.jsonl"):
        if trade.get("paper_epoch_id") not in (None, epoch):
            raise Live1BBooksUnavailable("LIVE1B_TRADE_EPOCH_CONFLICT")
        tf = str(trade.get("timeframe") or "").upper()
        if tf not in totals:
            continue
        row = totals[tf]; row["count"] += 1
        net = _sf(trade.get("realized_net_pnl_usd"))
        if net is None:
            net = _sf(trade.get("realized_pnl_usd"))
        if net is None:
            net = _sf(trade.get("net_pnl_usd"))
        if net is not None:
            row["realized"] += net
        fee = _sf(trade.get("fees_usd"))
        if fee is not None:
            row["fees"] += fee
        slip = _sf(trade.get("slippage_usd"))
        if slip is not None:
            row["slippage"] += slip
    _TRADE_TOTALS_CACHE.value = (key, copy.deepcopy(totals))
    return totals


def live1b_trader_views(
    *,
    timeframes: tuple[str, ...] | list[str],
    mark_price: float | None = None,
    repo_root: Path | None = None,
    paper_epoch_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Snapshot shape compatible with ``PaperTraderEngine.snapshot``."""
    root = repo_root or ROOT
    active_epoch = active_live1b_epoch_id(root)
    epoch_id = paper_epoch_id or active_epoch
    if not active_epoch or epoch_id != active_epoch:
        raise Live1BBooksUnavailable("LIVE1B_ACTIVE_EPOCH_UNAVAILABLE_OR_CONFLICTING")
    views: dict[str, dict[str, Any]] = {}
    opens: dict[str, dict[str, Any]] = {}
    trade_totals = {}
    sleeves_snapshot: dict[str, Any] = {}
    if epoch_id:
        books = root / "data/trading/intrabar_paper" / epoch_id / "books"
        pending = books.parent / "execution_commits_v1" / "pending.json"
        # Imports may be expensive; never hold the financial lock for them.
        from .intrabar_paper.cold_forward_guard import verify_committed_head_cooperative, _contains_symlink
        from .intrabar_paper.cursor_ack import GuardExtension
        try:
            lock = (books / ".writer.lock").open("rb")
        except OSError as exc:
            raise Live1BBooksUnavailable("LIVE1B_BOOKS_LOCK_UNAVAILABLE") from exc
        with lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            except BlockingIOError as exc:
                raise Live1BBooksUnavailable("LIVE1B_BOOKS_COMMIT_IN_PROGRESS") from exc
            try:
                if pending.exists():
                    raise Live1BBooksUnavailable("LIVE1B_BOOKS_UNCOMMITTED_INTENT")
                try:
                    committed_head = _confirmed_reader_head(books.parent, epoch_id, lock)
                except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                    raise Live1BBooksUnavailable("LIVE1B_" + str(exc)) from exc
                try:
                    sleeve_document = json.loads((books.parent / "sleeves.json").read_text())
                    if sleeve_document.get("epoch_id") != epoch_id:
                        raise ValueError("SLEEVE_EPOCH_MISMATCH")
                    sleeves_snapshot = sleeve_document["sleeves"]
                    for tf in timeframes:
                        row = sleeves_snapshot[tf]
                        if str(row["timeframe"]).upper() != tf:
                            raise ValueError("SLEEVE_TIMEFRAME_MISMATCH")
                        equity = float(row["current_equity_usd"])
                        pct = float(row["risk_pct_per_trade"])
                        if not math.isfinite(equity) or not math.isfinite(pct) or equity < 0 or pct <= 0:
                            raise ValueError("INVALID_SLEEVE_CAPITAL")
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise Live1BBooksUnavailable("LIVE1B_SLEEVE_CONTRACT_UNAVAILABLE") from exc
                if active_live1b_epoch_id(root) != epoch_id:
                    raise Live1BBooksUnavailable("LIVE1B_ACTIVE_EPOCH_CHANGED")
                position_rows = _read_jsonl(books / "positions.jsonl")
                for row in position_rows:
                    if row.get("paper_epoch_id") not in (None, epoch_id):
                        raise Live1BBooksUnavailable("LIVE1B_POSITION_EPOCH_CONFLICT")
                opens = _latest_open_by_timeframe(books / "positions.jsonl", rows=position_rows)
                trade_totals = _historical_trade_totals(books, epoch_id, timeframes, committed_head)
                # The committed ledger and append-only books describe the same
                # publication. Never turn lost exposure/history into a FLAT view.
                try:
                    for tf in timeframes:
                        sleeve = sleeves_snapshot[tf]
                        position = opens.get(tf)
                        if sleeve["open_position_id"] != (position or {}).get("position_id"):
                            raise ValueError("POSITION_ID_DISAGREES_WITH_SLEEVE")
                        book_risk = float((position or {}).get("risk_amount_usd") or (position or {}).get("risk_budget_usd") or 0.0)
                        ledger_risk = float(sleeve["open_position_risk_usd"])
                        if not math.isfinite(book_risk) or not math.isfinite(ledger_risk) or book_risk != ledger_risk:
                            raise ValueError("OPEN_RISK_DISAGREES_WITH_SLEEVE")
                        if int(sleeve["closed_trades_count"]) != trade_totals[tf]["count"]:
                            raise ValueError("CLOSED_COUNT_DISAGREES_WITH_SLEEVE")
                except (KeyError, TypeError, ValueError) as exc:
                    raise Live1BBooksUnavailable("LIVE1B_BOOKS_SLEEVE_MISMATCH") from exc
                if pending.exists():
                    raise Live1BBooksUnavailable("LIVE1B_BOOKS_UNCOMMITTED_INTENT")
                if active_live1b_epoch_id(root) != epoch_id:
                    raise Live1BBooksUnavailable("LIVE1B_ACTIVE_EPOCH_CHANGED")
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    from .intrabar_paper.execution_commit import open_authority
    for tf in timeframes:
        open_row = opens.get(tf)
        totals = trade_totals[tf]
        realized = totals["realized"]
        fees = totals["fees"]
        slippage = totals["slippage"]

        open_risk = 0.0
        unrealized = 0.0
        open_position = None
        if open_row:
            open_risk = float(
                _sf(open_row.get("risk_amount_usd"))
                or _sf(open_row.get("risk_budget_usd"))
                or 0.0
            )
            qty = float(_sf(open_row.get("quantity")) or 0.0)
            entry = float(_sf(open_row.get("entry_price")) or 0.0)
            direction = str(open_row.get("side") or open_row.get("direction") or "").upper()
            if mark_price is not None and qty and entry:
                unrealized = (
                    (float(mark_price) - entry) * qty
                    if direction == "LONG"
                    else (entry - float(mark_price)) * qty
                )
            open_position = {
                "position_id": open_row.get("position_id"),
                "direction": direction,
                "quantity": _sf(open_row.get("quantity")),
                "entry_price": _sf(open_row.get("entry_price")),
                "opened_at": open_row.get("opened_at") or open_row.get("execution_timestamp"),
                "status": "OPEN",
                "stop_loss_price": _sf(open_row.get("stop_loss_price")),
                "take_profit_price": _sf(open_row.get("take_profit_price")),
                "entry_fee_usd": _sf(open_row.get("entry_fee_usd")),
                "risk_amount_usd": open_risk,
            }
        views[tf] = {
            "timeframe": tf,
            "open_position": open_position,
            "open_risk_usd": open_risk,
            "realized_pnl_usd": realized,
            "unrealized_pnl_usd": unrealized,
            "fees_paid_usd": fees,
            "slippage_paid_usd": slippage,
            "closed_trades": totals["count"],
            "last_command_id": open_row.get("entry_command_id") if open_row else None,
            "last_result": "POSITION_OPEN" if open_position else "FLAT",
            "last_reason": "LIVE1B_EPOCH_BOOK",
            "cursor_evaluation_timestamp": None,
            "position_source": "live1b_epoch_books",
            "execution_authority": open_authority(committed_head, tf, sleeves_snapshot[tf]),
            "paper_epoch_id": epoch_id,
            "sleeve_current_equity_usd": (sleeves_snapshot.get(tf) or {}).get("current_equity_usd"),
            "sleeve_risk_pct_per_trade": (sleeves_snapshot.get(tf) or {}).get("risk_pct_per_trade"),
        }
    return views
