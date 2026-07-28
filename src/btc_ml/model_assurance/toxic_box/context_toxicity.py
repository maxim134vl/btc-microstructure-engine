"""Context Toxicity branch (MODEL-4) — observational / non-blocking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from btc_ml.model_assurance.toxic_box.common import (
    append_unique,
    base_event,
    parse_ts,
    read_jsonl,
)

TF_SECONDS = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}


def _horizon_key(cfg_horizon: str) -> str:
    text = str(cfg_horizon or "3X").upper().replace(" ", "")
    if text in {"3X", "3XTF", "3"}:
        return "3xTF"
    if text in {"2X", "2XTF", "2"}:
        return "2xTF"
    if text in {"1X", "1XTF", "1"}:
        return "1xTF"
    return "3xTF"


def _f(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_context_toxicity(
    *,
    active: dict[str, Any],
    predictions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    config: dict[str, Any],
    events_path: Path,
    existing_ids: set[str],
) -> dict[str, Any]:
    ctx_cfg = config.get("context") or {}
    min_move = float(ctx_cfg.get("minimum_move_bps", 10.0))
    horizon = _horizon_key(str(ctx_cfg.get("false_direction_horizon", "3X")))
    mae_mfe_ratio = float(ctx_cfg.get("false_direction_mae_to_mfe_ratio", 2.0))
    premature_frac = float(ctx_cfg.get("premature_max_lifecycle_fraction", 0.5))
    overstay_mfe = float(ctx_cfg.get("overstay_min_mfe_bps", 20.0))
    giveback = float(ctx_cfg.get("overstay_giveback_ratio", 0.8))
    max_flips = int(ctx_cfg.get("flip_instability_max_flips", 3))
    flip_window_tf = int(ctx_cfg.get("flip_instability_window_timeframes", 2))

    registry_id = str(active.get("registry_record_id") or "")
    epoch_id = str(active.get("paper_epoch_id") or "")

    preds = [
        p
        for p in predictions
        if str(p.get("registry_record_id") or "") == registry_id
        and str(p.get("paper_epoch_id") or "") == epoch_id
        and str(p.get("direction") or "").upper() in {"LONG", "SHORT"}
    ]
    outs = [
        o
        for o in outcomes
        if str(o.get("registry_record_id") or o.get("prediction_id") or "")  # soft filter
    ]
    # Prefer epoch/registry when present on outcomes
    filtered_outs: list[dict[str, Any]] = []
    for o in outs:
        if o.get("registry_record_id") and str(o.get("registry_record_id")) != registry_id:
            continue
        if o.get("paper_epoch_id") and str(o.get("paper_epoch_id")) != epoch_id:
            continue
        filtered_outs.append(o)

    by_pred: dict[str, list[dict[str, Any]]] = {}
    for o in filtered_outs:
        pid = str(o.get("prediction_id") or "")
        if pid:
            by_pred.setdefault(pid, []).append(o)

    created = 0
    candidates = 0
    confirmed = 0
    evaluable = 0
    not_evaluable: dict[str, int] = {}
    last_event_at = None

    # Flip instability: count CLOSE via CONTEXT_FLIP per timeframe
    from datetime import datetime

    flips_by_tf_ts: dict[str, list[datetime]] = {}
    for p in preds:
        if str(p.get("close_reason") or "").upper() == "CONTEXT_FLIP":
            tf = str(p.get("timeframe") or "")
            ts = parse_ts(p.get("closed_at") or p.get("start_timestamp"))
            if ts is not None:
                flips_by_tf_ts.setdefault(tf, []).append(ts)

    for tf, stamps in flips_by_tf_ts.items():
        stamps = sorted(stamps)
        window_s = flip_window_tf * TF_SECONDS.get(tf, 900)
        # sliding count
        for i, t0 in enumerate(stamps):
            count = 1
            for t1 in stamps[i + 1 :]:
                if (t1 - t0).total_seconds() <= window_s:
                    count += 1
                else:
                    break
            if count > max_flips:
                row = base_event(
                    branch="CONTEXT",
                    subtype="CTX_FLIP_INSTABILITY",
                    severity="WATCH",
                    status="CANDIDATE",
                    active=active,
                    subject_event_at=t0.isoformat().replace("+00:00", "Z"),
                    timeframe=tf,
                    subject_id=f"FLIP|{tf}|{t0.isoformat()}",
                    expected_value=f"<={max_flips}",
                    observed_value=count,
                    threshold={"max_flips": max_flips, "window_timeframes": flip_window_tf},
                    evidence={"window_seconds": window_s},
                )
                if append_unique(events_path, row, existing_ids=existing_ids):
                    created += 1
                    candidates += 1
                break

    for pred in preds:
        pid = str(pred.get("prediction_id") or "")
        if not pid:
            continue
        pred_outs = by_pred.get(pid) or []
        evaluated = [o for o in pred_outs if str(o.get("outcome_status") or "") == "EVALUATED"]
        if not evaluated:
            not_evaluable["CONTEXT_NO_EVALUATED_OUTCOME"] = not_evaluable.get("CONTEXT_NO_EVALUATED_OUTCOME", 0) + 1
            continue
        evaluable += 1

        # Causality breach only with explicit evidence
        for o in evaluated:
            evidence = o.get("evidence") if isinstance(o.get("evidence"), dict) else {}
            if o.get("causality_breach") is True or evidence.get("causality_breach") is True:
                row = base_event(
                    branch="CONTEXT",
                    subtype="CTX_CAUSALITY_BREACH",
                    severity="CRITICAL",
                    status="CONFIRMED",
                    active=active,
                    subject_event_at=o.get("evaluated_at") or pred.get("start_timestamp"),
                    timeframe=pred.get("timeframe"),
                    direction=pred.get("direction"),
                    context_event_id=pred.get("context_event_id"),
                    lifecycle_episode_id=pred.get("lifecycle_episode_id"),
                    prediction_id=pid,
                    outcome_id=o.get("outcome_id"),
                    subject_id=pid,
                    expected_value="causal_cutoff_respected",
                    observed_value=evidence or o.get("causality_breach"),
                    evidence=evidence,
                )
                if append_unique(events_path, row, existing_ids=existing_ids):
                    created += 1
                    confirmed += 1
                    last_event_at = row["detected_at"]

        # False direction on configured horizon
        h_out = next((o for o in evaluated if str(o.get("horizon_type")) == horizon), None)
        if h_out is not None:
            signed = _f(h_out.get("signed_return_bps"))
            mfe = _f(h_out.get("mfe_bps"))
            mae = _f(h_out.get("mae_bps"))
            if signed is None or mfe is None or mae is None:
                not_evaluable["CTX_FALSE_DIRECTION_MISSING_METRICS"] = (
                    not_evaluable.get("CTX_FALSE_DIRECTION_MISSING_METRICS", 0) + 1
                )
            elif signed <= -min_move and abs(mae) >= mae_mfe_ratio * max(mfe, 1.0):
                row = base_event(
                    branch="CONTEXT",
                    subtype="CTX_FALSE_DIRECTION",
                    severity="WATCH",
                    status="CANDIDATE",
                    active=active,
                    subject_event_at=h_out.get("evaluated_at") or pred.get("start_timestamp"),
                    timeframe=pred.get("timeframe"),
                    direction=pred.get("direction"),
                    context_event_id=pred.get("context_event_id"),
                    lifecycle_episode_id=pred.get("lifecycle_episode_id"),
                    prediction_id=pid,
                    outcome_id=h_out.get("outcome_id"),
                    subject_id=pid,
                    expected_value={"signed_return_bps": f">{-min_move}", "mae_mfe_ratio": f"<{mae_mfe_ratio}"},
                    observed_value={"signed_return_bps": signed, "mfe_bps": mfe, "mae_bps": mae},
                    threshold={
                        "minimum_move_bps": min_move,
                        "false_direction_horizon": horizon,
                        "mae_to_mfe_ratio": mae_mfe_ratio,
                    },
                )
                if append_unique(events_path, row, existing_ids=existing_ids):
                    created += 1
                    candidates += 1
                    last_event_at = row["detected_at"]

        # Lifecycle outcomes for premature / overstay
        life = next((o for o in evaluated if str(o.get("horizon_type")) == "LIFECYCLE_END"), None)
        if life is None:
            not_evaluable["CTX_LIFECYCLE_OUTCOME_MISSING"] = not_evaluable.get("CTX_LIFECYCLE_OUTCOME_MISSING", 0) + 1
        else:
            signed = _f(life.get("signed_return_bps"))
            mfe = _f(life.get("mfe_bps"))
            start = parse_ts(pred.get("start_timestamp"))
            end = parse_ts(pred.get("closed_at") or life.get("cutoff_timestamp"))
            tf = str(pred.get("timeframe") or "")
            tf_s = TF_SECONDS.get(tf)
            if (
                str(pred.get("prediction_status") or "").upper() == "CLOSED"
                and str(pred.get("close_reason") or "").upper() in {"CONTEXT_END", "CONTEXT_FLIP"}
                and start
                and end
                and tf_s
                and signed is not None
                and mfe is not None
            ):
                dur = max(0.0, (end - start).total_seconds())
                if dur < premature_frac * tf_s and mfe < min_move and signed <= 0:
                    row = base_event(
                        branch="CONTEXT",
                        subtype="CTX_PREMATURE_START",
                        severity="WATCH",
                        status="CANDIDATE",
                        active=active,
                        subject_event_at=pred.get("closed_at") or life.get("evaluated_at"),
                        timeframe=tf,
                        direction=pred.get("direction"),
                        context_event_id=pred.get("context_event_id"),
                        lifecycle_episode_id=pred.get("lifecycle_episode_id"),
                        prediction_id=pid,
                        outcome_id=life.get("outcome_id"),
                        subject_id=pid,
                        expected_value={"min_lifecycle_fraction": premature_frac},
                        observed_value={"duration_s": dur, "mfe_bps": mfe, "signed_return_bps": signed},
                        threshold={"premature_max_lifecycle_fraction": premature_frac, "minimum_move_bps": min_move},
                    )
                    if append_unique(events_path, row, existing_ids=existing_ids):
                        created += 1
                        candidates += 1
                        last_event_at = row["detected_at"]

            if signed is not None and mfe is not None and mfe >= overstay_mfe:
                if signed <= mfe * (1.0 - giveback):
                    row = base_event(
                        branch="CONTEXT",
                        subtype="CTX_OVERSTAY",
                        severity="WATCH",
                        status="CANDIDATE",
                        active=active,
                        subject_event_at=life.get("evaluated_at") or pred.get("closed_at"),
                        timeframe=pred.get("timeframe"),
                        direction=pred.get("direction"),
                        context_event_id=pred.get("context_event_id"),
                        lifecycle_episode_id=pred.get("lifecycle_episode_id"),
                        prediction_id=pid,
                        outcome_id=life.get("outcome_id"),
                        subject_id=pid,
                        expected_value={"giveback_ratio_lt": giveback},
                        observed_value={"mfe_bps": mfe, "signed_return_bps": signed},
                        threshold={
                            "overstay_min_mfe_bps": overstay_mfe,
                            "overstay_giveback_ratio": giveback,
                        },
                    )
                    if append_unique(events_path, row, existing_ids=existing_ids):
                        created += 1
                        candidates += 1
                        last_event_at = row["detected_at"]

    events = read_jsonl(events_path)
    open_like = [e for e in events if e.get("branch") == "CONTEXT"]
    return {
        "predictions_seen": len(preds),
        "predictions_evaluable": evaluable,
        "toxic_candidates": sum(1 for e in open_like if e.get("status") == "CANDIDATE"),
        "confirmed_events": sum(1 for e in open_like if e.get("status") == "CONFIRMED"),
        "created_this_pass": created,
        "not_evaluable_checks": not_evaluable,
        "last_context_event_at": last_event_at or (open_like[-1].get("detected_at") if open_like else None),
        "events": open_like,
    }
