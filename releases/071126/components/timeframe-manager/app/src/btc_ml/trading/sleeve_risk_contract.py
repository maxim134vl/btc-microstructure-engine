"""Approved OCT-LIVE1B-010 authority; USD approval is an as-of preview."""
import math, json
PERCENTAGES = {"M15": 0.5, "M30": 0.5, "H1": 1.0, "H4": 1.0}
CONTRACT = "PER_TF_COMMITTED_EQUITY_PCT_V1"
SEMANTICS = "PRE_CLOSE_PREVIEW_OPEN_FROM_COMMITTED_EQUITY"
FIELDS = ("risk_approval_contract", "risk_usd_semantics", "approved_risk_pct",
          "risk_equity_snapshot_usd", "risk_paper_epoch_id")
def approval(timeframe, equity, epoch):
    tf = str(timeframe).upper()
    binding = epoch if isinstance(epoch, dict) else None
    epoch = binding["epoch"] if binding else epoch
    equity = float(equity)
    if tf not in PERCENTAGES or not math.isfinite(equity) or equity < 0 or not epoch:
        raise ValueError("RISK_APPROVAL_INVALID_SLEEVE")
    contract = CONTRACT
    if binding:
        authority = binding["authority"]
        if authority["timeframe"] != tf or authority["epoch"] != epoch or float(authority["equity"]) != equity:
            raise ValueError("RISK_APPROVAL_COMMITTED_AUTHORITY_CONFLICT")
        # Existing persisted string column: no manager/command-bus schema rewrite.
        contract = json.dumps({"contract": CONTRACT, "authority": authority}, sort_keys=True)
    return dict(zip(FIELDS, (contract, SEMANTICS, PERCENTAGES[tf], equity, str(epoch))))

def bound_authority(command):
    raw = command.get("risk_approval_contract")
    try:
        parsed = json.loads(raw)
        if parsed["contract"] == CONTRACT:
            return parsed["authority"]
    except (TypeError, ValueError, KeyError):
        pass
    return None
def validate(command, epoch, sleeve_pct):
    tf = str(command.get("timeframe", "")).upper()
    try:
        eq = float(command["risk_equity_snapshot_usd"])
        pct = float(command["approved_risk_pct"])
        usd = float(command["approved_risk_usd"])
        if ((command["risk_approval_contract"] != CONTRACT and bound_authority(command) is None) or command["risk_usd_semantics"] != SEMANTICS
                or command["risk_paper_epoch_id"] != epoch or tf not in PERCENTAGES
                or pct != PERCENTAGES[tf] or pct != float(sleeve_pct)
                or not math.isfinite(eq) or eq < 0 or not math.isfinite(usd) or usd <= 0
                or not math.isclose(usd, eq * pct / 100, rel_tol=1e-12, abs_tol=1e-9)):
            return "ENTRY_BLOCKED_RISK_APPROVAL_CONTRACT"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "ENTRY_BLOCKED_RISK_APPROVAL_CONTRACT"
    return None


def fence_open(command, books, sleeves):
    """Called inside the engine's existing EX transaction, never a second lock."""
    from .intrabar_paper.execution_commit import (verify_committed_head, open_authority,
        head_reference, AUTHORITY_SCHEMA, decode_authority, digest, nullable, encode_authority, canonical, authenticated_prior)
    try:
        if not books.owns_exclusive():
            raise ValueError("OPEN_FENCE_REQUIRES_EXCLUSIVE_OWNER")
        epoch = books.paper_epoch_id; tf = str(command["timeframe"]).upper()
        token = bound_authority(command)
        if (not token or token["schema"] != AUTHORITY_SCHEMA or token["epoch"] != epoch
                or token["timeframe"] != tf or float(token["equity"]) != float(command["risk_equity_snapshot_usd"])):
            raise ValueError("OPEN_AUTHORITY_BINDING_INVALID")
        head = verify_committed_head(books.root.parent, epoch)
        current = open_authority(head, tf, sleeves.get(tf).to_dict())
        if token == current:
            return None
        # Authenticate the exact pinned publication through its MMR membership,
        # not a traversal across all unrelated intervening financial receipts.
        if token["head"]["generation"] >= head["publication"]["generation"]:
            raise ValueError("OPEN_APPROVAL_NOT_ANCESTOR")
        cursor, _ = authenticated_prior(head, token["head"], books.root.parent, epoch)
        prior_scope = cursor["publication"]["scopes"][tf]
        if token != open_authority(cursor, tf, prior_scope["sleeve"]):
            raise ValueError("OPEN_PRIOR_AUTHORITY_CONFLICT")
        version = prior_scope["version"]
        if current["scope_version"] == version:
            if current["equity"] != token["equity"] or current["position_id"] != token["position_id"] or current["open_risk"] != token["open_risk"]:
                raise ValueError("OPEN_SCOPE_CONTENT_CONFLICT")
            return None
        if current["scope_version"] != version + 1:
            raise ValueError("OPEN_OWN_SCOPE_CHANGED_OR_ABA")
        change = head["publication"]["scopes"][tf]["last_change"]
        if change is None or change["generation"] <= token["head"]["generation"]:
            raise ValueError("OPEN_SCOPE_VERSION_CONFLICT")
        rp = books.commit.receipt_path(change["receipt_key"])
        saved = decode_authority(rp, epoch)
        own_head = {"schema": head["schema"], "epoch": epoch,
            "publication": saved["publication"], "receipt_sha256": digest(rp.read_bytes())}
        _, receipt = authenticated_prior(head, head_reference(own_head), books.root.parent, epoch)
        if receipt["publication"]["generation"] != change["generation"] or receipt["publication"]["scopes"][tf]["version"] != version + 1:
            raise ValueError("OPEN_SCOPE_VERSION_CONFLICT")
        source = receipt["source"]
        result = receipt["result"]
        if source["method"] == "apply_s41_manager_command":
            close = (source.get("args") or [source.get("kwargs", {}).get("command", {})])[0]
        elif source["method"] in {"update_bbo_from_market", "update_from_trade"}:
            # Native delayed-BBO completion is the original same CLOSE, not a
            # new entry grant. Its exact fill parent must resolve to the retained
            # immutable original command-bus CLOSE in the same manager cycle.
            matches = [r for r in result or [] if isinstance(r, dict)
                       and r.get("status") == "EXITED" and r.get("trade", {}).get("position_id") == token["position_id"]]
            if len(matches) != 1:
                raise ValueError("OPEN_NATIVE_CLOSE_RECEIPT_AMBIGUOUS")
            result = matches[0]
            trigger = result["fill"]["trigger_event_id"]
            from .command_bus import CommandBus, CommandBusPaths
            root = books.root.parents[4]
            bus = CommandBus(CommandBusPaths(root / "data/trading/manager/timeframe_command_memory.parquet",
                root / "data/runtime/timeframe_manager_latest.json", root / "data/trading/manager/manager_state.json",
                root / "data/trading/manager/portfolio_summary.json"))
            rows = bus.frame(); owned = rows[rows["command_id"] == trigger].to_dict("records")
            if len(owned) != 1:
                raise ValueError("OPEN_NATIVE_CLOSE_COMMAND_PARENT_MISSING")
            close = owned[0]
        else:
            raise ValueError("OPEN_NOT_OWN_COMMITTED_CLOSE_SUCCESSOR")
        keys = ("manager_cycle_id", "timeframe", "decision_id", "lifecycle_episode_id", "evaluation_timestamp")
        if (close.get("intent") != "CLOSE"
                or result.get("status") != "EXITED" or not token["position_id"]
                or result["trade"]["position_id"] != token["position_id"]
                or current["position_id"] is not None
                or any(nullable(close.get(k)) != nullable(command.get(k)) for k in keys)
                or not close.get("manager_cycle_id")
                or receipt["occupancy_before"].get(tf) != token["position_id"]
                or receipt["occupancy_after"].get(tf) is not None):
            raise ValueError("OPEN_NOT_OWN_COMMITTED_CLOSE_SUCCESSOR")
        return None
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return "ENTRY_BLOCKED_COMMITTED_AUTHORITY"
