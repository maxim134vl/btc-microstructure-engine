"""AES5 coordinator — checkpoint verdicts, case outcomes, post-mortems.

Observer-only. Never mutates AES2/AES3/AES4 memories or canonical trading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .canonical_lifecycle import iter_paper_closes
from .checkpoint import CHECKPOINT_CONTEXT_START, CHECKPOINT_PAPER_CLOSE, CHECKPOINT_PAPER_ENTRY
from .outcome import OutcomeEngine, build_outcome, trade_fields_from_raw
from .postmortem import DEFAULT_HORIZON_SEC, PostmortemEngine, build_postmortem
from .verdict import VerdictEngine, interpret_checkpoint


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _group_cases(checkpoints: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for ckp in checkpoints:
        cid = str(ckp.get("shadow_case_id") or "")
        if not cid:
            continue
        bucket = cases.setdefault(
            cid,
            {"context": None, "entry": None, "close": None, "checkpoints": []},
        )
        bucket["checkpoints"].append(ckp)
        ctype = ckp.get("checkpoint_type")
        if ctype == CHECKPOINT_CONTEXT_START:
            bucket["context"] = ckp
        elif ctype == CHECKPOINT_PAPER_ENTRY:
            bucket["entry"] = ckp
        elif ctype == CHECKPOINT_PAPER_CLOSE:
            bucket["close"] = ckp
    return cases


@dataclass
class Aes5Evaluator:
    """Incremental AES5 evaluation over frozen AES4 checkpoints."""

    logic_version: str = "AES_V1"
    logic_fingerprint: str = ""
    horizon_sec: int = DEFAULT_HORIZON_SEC
    verdicts: VerdictEngine = field(default_factory=VerdictEngine)
    outcomes: OutcomeEngine = field(default_factory=OutcomeEngine)
    postmortems: PostmortemEngine = field(default_factory=PostmortemEngine)
    open_cases_waiting_close: int = 0
    last_outcome_id: str | None = None
    last_postmortem_id: str | None = None

    def __post_init__(self) -> None:
        self.verdicts.logic_version = self.logic_version
        self.verdicts.logic_fingerprint = self.logic_fingerprint
        self.outcomes.logic_version = self.logic_version
        self.outcomes.logic_fingerprint = self.logic_fingerprint
        self.outcomes.index = self.outcomes.index
        self.postmortems.logic_version = self.logic_version
        self.postmortems.logic_fingerprint = self.logic_fingerprint
        self.postmortems.horizon_sec = self.horizon_sec
        self.postmortems.index = self.outcomes.index

    def restore(self, memory_dir: Path) -> None:
        self.verdicts.restore(memory_dir / "checkpoint_verdict_memory.jsonl")
        self.outcomes.restore(memory_dir / "shadow_outcome_memory.jsonl")
        self.postmortems.restore(memory_dir / "postmortem_memory.jsonl")

    def evaluate_checkpoint(self, checkpoint: Mapping[str, Any]) -> dict[str, Any]:
        return self.verdicts.ingest(checkpoint)

    def evaluate_case(
        self,
        *,
        case_id: str,
        context_ckp: Mapping[str, Any] | None,
        entry_ckp: Mapping[str, Any] | None,
        close_ckp: Mapping[str, Any] | None,
        canonical_trade: Mapping[str, Any] | None = None,
        extra_anchor_rows: list[Mapping[str, Any]] | None = None,
        extra_hierarchy_rows: list[Mapping[str, Any]] | None = None,
        causal_price_path: list[Mapping[str, Any]] | None = None,
        now_ts: str | None = None,
    ) -> dict[str, Any]:
        ctx_v = None if context_ckp is None else interpret_checkpoint(context_ckp)
        ent_v = None if entry_ckp is None else interpret_checkpoint(entry_ckp)
        close_v = None if close_ckp is None else interpret_checkpoint(close_ckp)
        out = None
        pm = None
        if close_ckp is not None:
            out = build_outcome(
                case_id=case_id,
                context_ckp=context_ckp,
                entry_ckp=entry_ckp,
                close_ckp=close_ckp,
                context_verdict=ctx_v,
                entry_verdict=ent_v,
                index=self.outcomes.index,
                canonical_trade=canonical_trade,
                extra_anchor_rows=extra_anchor_rows,
                causal_price_path=causal_price_path,
                logic_version=self.logic_version,
                logic_fingerprint=self.logic_fingerprint,
            )
            pm = build_postmortem(
                case_id=case_id,
                trade_id=None if close_ckp is None else close_ckp.get("trade_id"),
                position_id=None if close_ckp is None else close_ckp.get("position_id"),
                context_ckp=context_ckp,
                entry_ckp=entry_ckp,
                close_ckp=close_ckp,
                index=self.postmortems.index,
                extra_anchor_rows=extra_anchor_rows,
                extra_hierarchy_rows=extra_hierarchy_rows,
                now_ts=now_ts,
                horizon_sec=self.horizon_sec,
                logic_version=self.logic_version,
                logic_fingerprint=self.logic_fingerprint,
            )
        return {
            "context_verdict": ctx_v,
            "entry_verdict": ent_v,
            "close_verdict": close_v,
            "outcome": out,
            "postmortem": pm,
        }

    def health_fields(self) -> dict[str, Any]:
        payload = {
            "aes5_enabled": True,
            "open_cases_waiting_close": self.open_cases_waiting_close,
            "last_outcome_id": self.outcomes.last_outcome_id or self.last_outcome_id,
            "last_postmortem_id": self.postmortems.last_postmortem_id or self.last_postmortem_id,
            "aes5_duplicate_suppressed": (
                self.verdicts.duplicate_suppressed
                + self.outcomes.duplicate_suppressed
                + self.postmortems.duplicate_suppressed
            ),
            "aes5_payload_conflicts": (
                self.verdicts.payload_conflicts
                + self.outcomes.payload_conflicts
                + self.postmortems.payload_conflicts
            ),
            "aes5_lookahead_violations": self.verdicts.lookahead_violations
            + self.outcomes.lookahead_violations,
        }
        payload.update(self.verdicts.health_fields())
        payload.update(self.outcomes.health_fields())
        payload.update(self.postmortems.health_fields())
        payload["aes5_duplicate_suppressed"] = (
            self.verdicts.duplicate_suppressed
            + self.outcomes.duplicate_suppressed
            + self.postmortems.duplicate_suppressed
        )
        payload["aes5_payload_conflicts"] = (
            self.verdicts.payload_conflicts
            + self.outcomes.payload_conflicts
            + self.postmortems.payload_conflicts
        )
        return payload


def load_trade_map(repo: Path) -> dict[str, dict[str, Any]]:
    """Read-only paper close fields keyed by trade_id / position_id."""
    out: dict[str, dict[str, Any]] = {}
    try:
        events = list(iter_paper_closes(repo) or [])
    except Exception:
        return out
    for ev in events:
        fields = trade_fields_from_raw(ev.raw)
        if ev.entry_price is not None:
            fields.setdefault("entry_price", ev.entry_price)
        if ev.close_price is not None:
            fields.setdefault("exit_price", ev.close_price)
        if ev.close_reason:
            fields.setdefault("exit_reason", ev.close_reason)
        if ev.canonical_side:
            fields.setdefault("side", ev.canonical_side)
        if ev.trade_id:
            out[str(ev.trade_id)] = fields
        if ev.position_id:
            out.setdefault(str(ev.position_id), fields)
    return out
