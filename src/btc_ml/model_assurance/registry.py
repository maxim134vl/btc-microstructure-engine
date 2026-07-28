"""Active runtime Model Registry (LIVE1B / LIVE1A identity only).

Non-blocking: does not start/stop processes or alter paper trading.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Canonical LIVE1A provisional input / synthesis field identity (not runtime values).
LIVE1A_FEATURE_SCHEMA_FIELDS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "last",
    "close_position",
    "volume_event",
    "climax_state",
    "effort_result_state",
    "volume_class",
    "relative_volume",
    "bar_event",
    "volume_effort",
    "auction_location",
    "effort_side",
    "price_result",
    "follow_through",
    "effort_result",
    "auction_episode",
    "episode_status",
    "market_context",
    "context_status",
    "context_reason",
    "cognitive_market_state",
    "state_direction",
)

# Canonical LIVE1A context-event + LIVE1B paper entity schema identity.
LIVE1A_CONTEXT_EVENT_FIELDS: tuple[str, ...] = (
    "context_event_id",
    "timeframe",
    "event_type",
    "previous_context",
    "new_context",
    "event_timestamp",
    "event_monotonic_ns",
    "context_event_price",
    "last_trade_id",
    "last_trade_timestamp",
    "best_bid",
    "best_ask",
    "book_update_id",
    "bbo_receive_monotonic_ns",
    "bbo_age_ms",
    "connection_session_id",
    "reconnect_generation",
    "causal_cutoff_timestamp",
    "causal_cutoff_monotonic_ns",
    "model_version",
    "lifecycle_episode_id",
    "evidence",
    "ingested_at",
    "evaluation_mode",
)

LIVE1B_PAPER_ENTITY_TABLES: tuple[str, ...] = (
    "signals",
    "commands",
    "orders",
    "fills",
    "trades",
    "positions",
    "equity_snapshots",
    "metrics",
    "blocked",
)

LIVE1B_RISK_CONFIG_KEYS: tuple[str, ...] = (
    "max_risk_per_trade_pct",
    "max_risk_per_trade_usd",
    "cost_aware_stop_sizing",
    "fixed_notional",
    "stop_loss_bps",
    "take_profit_bps",
    "entry_fee_bps",
    "exit_fee_bps",
    "entry_slippage_bps",
    "exit_slippage_bps",
    "stop_exit_slippage_bps",
    "economics_source",
)

REQUIRED_RULE_CONTRACT = "INTRABAR_RULES_V1"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def registry_paths(repo_root: Path | None = None) -> dict[str, Path]:
    root = repo_root or _repo_root()
    base = root / "data" / "model_assurance" / "registry"
    return {
        "root": base,
        "models_jsonl": base / "models" / "model_registry.jsonl",
        "active_model": base / "active" / "active_model.json",
        "candidate_model": base / "candidate" / "candidate_model.json",
        "registry_status": base / "registry_status.json",
        "identity_config": root / "config" / "model_assurance_active_runtime.json",
        "execution_config": root / "config" / "intrabar_paper_execution.json",
        "active_epoch": root / "data" / "trading" / "paper_epochs" / "active.json",
        "candidates_dir": root / "config" / "model_candidates",
    }


def load_identity_config(repo_root: Path | None = None) -> dict[str, Any]:
    path = registry_paths(repo_root)["identity_config"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = (
        "model_id",
        "model_version",
        "model_role",
        "model_type",
        "cognition_version",
        "rule_contract_version",
    )
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(f"model_assurance_active_runtime.json missing keys: {missing}")
    return payload


def load_active_paper_epoch(repo_root: Path | None = None) -> dict[str, Any] | None:
    path = registry_paths(repo_root)["active_epoch"]
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("epoch_status") or "").upper() != "ACTIVE":
        return None
    if not str(payload.get("paper_epoch_id") or "").strip():
        return None
    return payload


def load_safety_flags(repo_root: Path | None = None) -> dict[str, Any]:
    """Read paper_only / real_execution from LIVE1B execution config."""
    path = registry_paths(repo_root)["execution_config"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    paper_only = bool(raw.get("paper_only", True))
    # Canonical flag name in config is real_execution_enabled; expose real_execution.
    real_execution = bool(raw.get("real_execution_enabled", False))
    if "real_execution" in raw:
        real_execution = bool(raw.get("real_execution"))
    return {
        "paper_only": paper_only,
        "real_execution": real_execution,
        "rule_contract_version": str(raw.get("rule_contract_version") or ""),
    }


def compute_execution_config_hash(repo_root: Path | None = None) -> str:
    path = registry_paths(repo_root)["execution_config"]
    return _sha256_bytes(path.read_bytes())


def compute_risk_config_hash(repo_root: Path | None = None) -> str:
    path = registry_paths(repo_root)["execution_config"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    risk = {k: raw.get(k) for k in LIVE1B_RISK_CONFIG_KEYS}
    return _sha256_text(_canonical_json(risk))


def compute_feature_schema_hash() -> str:
    return _sha256_text(_canonical_json({"fields": list(LIVE1A_FEATURE_SCHEMA_FIELDS)}))


def compute_data_schema_hash() -> str:
    return _sha256_text(
        _canonical_json(
            {
                "context_event_fields": list(LIVE1A_CONTEXT_EVENT_FIELDS),
                "paper_entity_tables": list(LIVE1B_PAPER_ENTITY_TABLES),
            }
        )
    )


def resolve_source_commit(repo_root: Path | None = None) -> str:
    root = repo_root or _repo_root()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception:
        return "UNKNOWN_COMMIT"


def compute_runtime_fingerprint(
    *,
    model_id: str,
    model_version: str,
    model_type: str,
    cognition_version: str,
    rule_contract_version: str,
    source_commit: str,
    feature_schema_hash: str,
    data_schema_hash: str,
    execution_config_hash: str,
    risk_config_hash: str,
) -> str:
    payload = {
        "model_id": model_id,
        "model_version": model_version,
        "model_type": model_type,
        "cognition_version": cognition_version,
        "rule_contract_version": rule_contract_version,
        "source_commit": source_commit,
        "feature_schema_hash": feature_schema_hash,
        "data_schema_hash": data_schema_hash,
        "execution_config_hash": execution_config_hash,
        "risk_config_hash": risk_config_hash,
    }
    return _sha256_text(_canonical_json(payload))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = _canonical_json(row) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def _write_status_and_active(paths: dict[str, Path], record: dict[str, Any]) -> None:
    cand_payload = None
    if paths["candidate_model"].exists():
        try:
            loaded = json.loads(paths["candidate_model"].read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and str(loaded.get("record_status") or "") == "CANDIDATE_REGISTERED":
                cand_payload = loaded
        except Exception:
            cand_payload = None
    status = {
        "status": "ACTIVE_REGISTERED",
        "active_model_id": record["model_id"],
        "active_model_version": record["model_version"],
        "candidate_status": (
            cand_payload.get("record_status") if cand_payload else "NONE_REGISTERED"
        ),
        "candidate_model_id": (cand_payload or {}).get("model_id"),
        "candidate_model_version": (cand_payload or {}).get("model_version"),
        "shadow_status": "CANDIDATE_REGISTERED" if cand_payload else "NONE_REGISTERED",
        "runtime_impact": "NON_BLOCKING",
        "promotion_status": (
            "BLOCKED_UNTIL_SHADOW_EVIDENCE" if cand_payload else "NOT_APPLICABLE_NO_CANDIDATE"
        ),
        "active_registry_record_id": record["registry_record_id"],
        "candidate_registry_record_id": (cand_payload or {}).get("registry_record_id"),
        "paper_epoch_id": record.get("paper_epoch_id"),
        "runtime_fingerprint": record.get("runtime_fingerprint"),
        "updated_at": _utc_now(),
    }
    _atomic_write_json(paths["active_model"], record)
    _atomic_write_json(paths["registry_status"], status)


def build_active_runtime_record(
    *,
    repo_root: Path | None = None,
    source_commit: str | None = None,
    registered_at: str | None = None,
) -> dict[str, Any]:
    identity = load_identity_config(repo_root)
    epoch = load_active_paper_epoch(repo_root)
    if epoch is None:
        raise RuntimeError("REGISTRATION_BLOCKED_NO_ACTIVE_EPOCH")
    safety = load_safety_flags(repo_root)
    if safety["paper_only"] is not True or safety["real_execution"] is not False:
        raise RuntimeError("REGISTRATION_BLOCKED_SAFETY_FLAGS")
    epoch_rule = str(epoch.get("rule_contract_version") or "")
    if epoch_rule != REQUIRED_RULE_CONTRACT:
        raise RuntimeError("REGISTRATION_BLOCKED_RULE_CONTRACT_MISMATCH")

    feature_hash = compute_feature_schema_hash()
    data_hash = compute_data_schema_hash()
    exec_hash = compute_execution_config_hash(repo_root)
    risk_hash = compute_risk_config_hash(repo_root)
    commit = source_commit if source_commit is not None else resolve_source_commit(repo_root)
    fingerprint = compute_runtime_fingerprint(
        model_id=str(identity["model_id"]),
        model_version=str(identity["model_version"]),
        model_type=str(identity["model_type"]),
        cognition_version=str(identity["cognition_version"]),
        rule_contract_version=str(identity["rule_contract_version"]),
        source_commit=commit,
        feature_schema_hash=feature_hash,
        data_schema_hash=data_hash,
        execution_config_hash=exec_hash,
        risk_config_hash=risk_hash,
    )
    return {
        "registry_record_id": f"REG_{uuid.uuid4().hex}",
        "model_id": str(identity["model_id"]),
        "model_version": str(identity["model_version"]),
        "model_role": "ACTIVE",
        "model_type": str(identity["model_type"]),
        "cognition_version": str(identity["cognition_version"]),
        "rule_contract_version": str(identity["rule_contract_version"]),
        "feature_schema_version": f"SHA256:{feature_hash}",
        "data_schema_version": f"SHA256:{data_hash}",
        "paper_epoch_id": str(epoch["paper_epoch_id"]),
        "paper_epoch_activated_at": epoch.get("activated_at"),
        "source_commit": commit,
        "runtime_fingerprint": fingerprint,
        "execution_config_hash": exec_hash,
        "risk_config_hash": risk_hash,
        "feature_schema_hash": feature_hash,
        "data_schema_hash": data_hash,
        "paper_only": True,
        "real_execution": False,
        "registered_at": registered_at or _utc_now(),
        "record_status": "ACTIVE_REGISTERED",
    }


def register_active_runtime(*, repo_root: Path | None = None) -> dict[str, Any]:
    """Register the current active runtime. Idempotent for identical bindings."""
    paths = registry_paths(repo_root)
    try:
        candidate = build_active_runtime_record(repo_root=repo_root)
    except RuntimeError as exc:
        code = str(exc)
        return {
            "status": code,
            "active_model": None,
            "registry_record_id": None,
        }

    rows = _read_jsonl(paths["models_jsonl"])
    model_id = candidate["model_id"]
    model_version = candidate["model_version"]
    fingerprint = candidate["runtime_fingerprint"]
    paper_epoch_id = candidate["paper_epoch_id"]

    identical = [
        r
        for r in rows
        if r.get("model_id") == model_id
        and r.get("model_version") == model_version
        and r.get("runtime_fingerprint") == fingerprint
        and r.get("paper_epoch_id") == paper_epoch_id
    ]
    if identical:
        existing = identical[-1]
        _write_status_and_active(paths, existing)
        return {
            "status": "ALREADY_REGISTERED",
            "active_model": existing,
            "registry_record_id": existing.get("registry_record_id"),
        }

    same_version = [
        r
        for r in rows
        if r.get("model_id") == model_id
        and r.get("model_version") == model_version
        and r.get("runtime_fingerprint") != fingerprint
    ]
    if same_version:
        return {
            "status": "VERSION_CONFLICT",
            "active_model": same_version[-1],
            "registry_record_id": same_version[-1].get("registry_record_id"),
            "conflicting_fingerprint": fingerprint,
            "existing_fingerprint": same_version[-1].get("runtime_fingerprint"),
        }

    # New record: either first registration, or same fingerprint with new paper epoch.
    _append_jsonl(paths["models_jsonl"], candidate)
    _write_status_and_active(paths, candidate)
    return {
        "status": "ACTIVE_REGISTERED",
        "active_model": candidate,
        "registry_record_id": candidate["registry_record_id"],
    }


def read_active_runtime(*, repo_root: Path | None = None) -> dict[str, Any] | None:
    path = registry_paths(repo_root)["active_model"]
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def read_registry_status(*, repo_root: Path | None = None) -> dict[str, Any]:
    path = registry_paths(repo_root)["registry_status"]
    if not path.exists():
        return {
            "status": "NONE_REGISTERED",
            "active_model_id": None,
            "active_model_version": None,
            "candidate_status": "NONE_REGISTERED",
            "shadow_status": "NONE_REGISTERED",
            "runtime_impact": "NON_BLOCKING",
            "promotion_status": "NOT_APPLICABLE_NO_CANDIDATE",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "CORRUPT_STATUS"}
    return payload if isinstance(payload, dict) else {"status": "CORRUPT_STATUS"}


# ---------------------------------------------------------------------------
# Candidate registry (MODEL-7) — prediction/shadow only, never replaces ACTIVE
# ---------------------------------------------------------------------------

FORBIDDEN_CANDIDATE_FLAGS = (
    "execution_enabled",
    "real_execution",
    "paper_execution",
    "order_routing",
)


def validate_candidate_descriptor(descriptor: dict[str, Any]) -> None:
    """Raise ValueError if candidate violates the safety contract."""
    for flag in FORBIDDEN_CANDIDATE_FLAGS:
        if bool(descriptor.get(flag)) is True:
            raise ValueError(f"CANDIDATE_REJECTED_{flag.upper()}_TRUE")
    if descriptor.get("execution_enabled") is not False:
        raise ValueError("CANDIDATE_REJECTED_EXECUTION_ENABLED_REQUIRED_FALSE")
    if descriptor.get("prediction_only") is not True:
        raise ValueError("CANDIDATE_REJECTED_PREDICTION_ONLY_REQUIRED")
    if descriptor.get("shadow_only") is not True:
        raise ValueError("CANDIDATE_REJECTED_SHADOW_ONLY_REQUIRED")
    for key in ("model_id", "model_version", "model_type"):
        if not str(descriptor.get(key) or "").strip():
            raise ValueError(f"CANDIDATE_REJECTED_MISSING_{key.upper()}")


def build_candidate_record(
    descriptor: dict[str, Any],
    *,
    repo_root: Path | None = None,
    registered_at: str | None = None,
) -> dict[str, Any]:
    validate_candidate_descriptor(descriptor)
    feature_hash = str(descriptor.get("feature_schema_hash") or compute_feature_schema_hash())
    data_hash = str(descriptor.get("data_schema_hash") or compute_data_schema_hash())
    commit = str(descriptor.get("source_commit") or resolve_source_commit(repo_root))
    cognition = str(descriptor.get("cognition_version") or "UNKNOWN")
    rule = str(descriptor.get("rule_contract_version") or "SHADOW_NO_EXECUTION")
    fingerprint = str(
        descriptor.get("runtime_fingerprint")
        or compute_runtime_fingerprint(
            model_id=str(descriptor["model_id"]),
            model_version=str(descriptor["model_version"]),
            model_type=str(descriptor["model_type"]),
            cognition_version=cognition,
            rule_contract_version=rule,
            source_commit=commit,
            feature_schema_hash=feature_hash,
            data_schema_hash=data_hash,
            execution_config_hash="SHADOW_NONE",
            risk_config_hash="SHADOW_NONE",
        )
    )
    return {
        "registry_record_id": f"REGC_{uuid.uuid4().hex}",
        "model_id": str(descriptor["model_id"]),
        "model_version": str(descriptor["model_version"]),
        "model_role": "CANDIDATE",
        "model_type": str(descriptor["model_type"]),
        "cognition_version": cognition,
        "rule_contract_version": rule,
        "feature_schema_version": str(
            descriptor.get("feature_schema_version") or f"SHA256:{feature_hash}"
        ),
        "data_schema_version": str(descriptor.get("data_schema_version") or f"SHA256:{data_hash}"),
        "source_commit": commit,
        "runtime_fingerprint": fingerprint,
        "execution_capability": "NONE",
        "prediction_only": True,
        "shadow_only": True,
        "execution_enabled": False,
        "adapter_module": descriptor.get("adapter_module"),
        "adapter_class": descriptor.get("adapter_class"),
        "registered_at": registered_at or _utc_now(),
        "record_status": "CANDIDATE_REGISTERED",
    }


def _refresh_registry_status_with_candidate(
    *,
    repo_root: Path | None,
    candidate: dict[str, Any] | None,
) -> None:
    paths = registry_paths(repo_root)
    active = read_active_runtime(repo_root=repo_root) or {}
    status = {
        "status": active.get("record_status") or "ACTIVE_REGISTERED",
        "active_model_id": active.get("model_id"),
        "active_model_version": active.get("model_version"),
        "candidate_status": (
            candidate.get("record_status") if candidate else "NONE_REGISTERED"
        ),
        "candidate_model_id": (candidate or {}).get("model_id"),
        "candidate_model_version": (candidate or {}).get("model_version"),
        "shadow_status": (
            "CANDIDATE_REGISTERED"
            if candidate and candidate.get("record_status") == "CANDIDATE_REGISTERED"
            else "NONE_REGISTERED"
        ),
        "runtime_impact": "NON_BLOCKING",
        "promotion_status": (
            "BLOCKED_UNTIL_SHADOW_EVIDENCE" if candidate else "NOT_APPLICABLE_NO_CANDIDATE"
        ),
        "active_registry_record_id": active.get("registry_record_id"),
        "candidate_registry_record_id": (candidate or {}).get("registry_record_id"),
        "paper_epoch_id": active.get("paper_epoch_id"),
        "runtime_fingerprint": active.get("runtime_fingerprint"),
        "updated_at": _utc_now(),
    }
    _atomic_write_json(paths["registry_status"], status)


def register_candidate(
    descriptor: dict[str, Any] | None = None,
    *,
    config_path: Path | str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Register a prediction-only / shadow-only candidate. Never promotes to ACTIVE."""
    if descriptor is None:
        if config_path is None:
            return {"status": "CANDIDATE_REJECTED_MISSING_CONFIG", "candidate": None}
        path = Path(config_path)
        descriptor = json.loads(path.read_text(encoding="utf-8"))
    try:
        record = build_candidate_record(descriptor, repo_root=repo_root)
    except ValueError as exc:
        return {"status": str(exc), "candidate": None, "registry_record_id": None}

    paths = registry_paths(repo_root)
    existing = read_candidate(repo_root=repo_root)
    if (
        existing
        and existing.get("model_id") == record["model_id"]
        and existing.get("model_version") == record["model_version"]
        and existing.get("runtime_fingerprint") == record["runtime_fingerprint"]
        and existing.get("record_status") == "CANDIDATE_REGISTERED"
    ):
        _atomic_write_json(paths["candidate_model"], existing)
        _refresh_registry_status_with_candidate(repo_root=repo_root, candidate=existing)
        return {
            "status": "ALREADY_REGISTERED",
            "candidate": existing,
            "registry_record_id": existing.get("registry_record_id"),
        }

    _append_jsonl(paths["models_jsonl"], record)
    _atomic_write_json(paths["candidate_model"], record)
    _refresh_registry_status_with_candidate(repo_root=repo_root, candidate=record)
    return {
        "status": "CANDIDATE_REGISTERED",
        "candidate": record,
        "registry_record_id": record["registry_record_id"],
    }


def read_candidate(*, repo_root: Path | None = None) -> dict[str, Any] | None:
    path = registry_paths(repo_root)["candidate_model"]
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("record_status") or "") not in {"CANDIDATE_REGISTERED", "RETIRED", "REJECTED"}:
        return None
    return payload


def read_candidate_status(*, repo_root: Path | None = None) -> dict[str, Any]:
    cand = read_candidate(repo_root=repo_root)
    if cand is None or str(cand.get("record_status") or "") != "CANDIDATE_REGISTERED":
        return {
            "candidate_status": "NONE_REGISTERED",
            "candidate_model_id": None,
            "candidate_model_version": None,
            "registry_record_id": None,
            "execution_capability": None,
        }
    return {
        "candidate_status": cand.get("record_status"),
        "candidate_model_id": cand.get("model_id"),
        "candidate_model_version": cand.get("model_version"),
        "registry_record_id": cand.get("registry_record_id"),
        "execution_capability": cand.get("execution_capability"),
        "runtime_fingerprint": cand.get("runtime_fingerprint"),
    }


def retire_candidate(
    *,
    reason: str,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    paths = registry_paths(repo_root)
    cand = read_candidate(repo_root=repo_root)
    if cand is None or str(cand.get("record_status") or "") != "CANDIDATE_REGISTERED":
        return {"status": "NO_CANDIDATE_REGISTERED", "candidate": None}
    retired = dict(cand)
    retired["record_status"] = "RETIRED"
    retired["model_role"] = "RETIRED"
    retired["retired_at"] = _utc_now()
    retired["retire_reason"] = str(reason or "UNSPECIFIED")
    _append_jsonl(paths["models_jsonl"], retired)
    _atomic_write_json(paths["candidate_model"], retired)
    _refresh_registry_status_with_candidate(repo_root=repo_root, candidate=None)
    return {"status": "CANDIDATE_RETIRED", "candidate": retired}
