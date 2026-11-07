"""Deterministic drift statistics (no p-value-only verdicts)."""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

QUANTILES = tuple(i / 100 for i in range(5, 100, 5))  # 0.05 .. 0.95
EPS = 1e-12


def _to_floats(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for v in values:
        try:
            if v is None:
                continue
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def quantile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    w = pos - lo
    return float(sorted_vals[lo]) * (1.0 - w) + float(sorted_vals[hi]) * w


def quantile_grid(values: Sequence[Any], quantiles: Sequence[float] = QUANTILES) -> list[float]:
    vals = sorted(_to_floats(values))
    if not vals:
        return [0.0 for _ in quantiles]
    return [quantile(vals, q) for q in quantiles]


def interquartile_range(values: Sequence[Any]) -> float:
    vals = sorted(_to_floats(values))
    if not vals:
        return 0.0
    return abs(quantile(vals, 0.75) - quantile(vals, 0.25))


def numeric_quantile_distance(
    baseline_values: Sequence[Any],
    current_values: Sequence[Any],
    *,
    quantiles: Sequence[float] = QUANTILES,
    epsilon: float = EPS,
) -> float:
    """Normalized mean absolute quantile distance (Wasserstein-like on fixed grid)."""
    bq = quantile_grid(baseline_values, quantiles)
    cq = quantile_grid(current_values, quantiles)
    iqr = interquartile_range(baseline_values)
    denom = max(iqr, epsilon)
    return float(sum(abs(c - b) for b, c in zip(bq, cq)) / len(bq) / denom)


def _normalize_counts(counts: dict[str, float], *, alpha: float = 1e-6) -> dict[str, float]:
    keys = sorted(counts.keys())
    total = float(sum(max(0.0, float(counts[k])) for k in keys))
    if total <= 0:
        # uniform over observed keys (or empty)
        if not keys:
            return {}
        u = 1.0 / len(keys)
        return {k: u for k in keys}
    # smooth zeros across union later
    return {k: max(0.0, float(counts[k])) / total for k in keys}


def categorical_js_distance(
    baseline_counts: dict[str, Any],
    current_counts: dict[str, Any],
    *,
    alpha: float = 1e-6,
) -> float:
    """Jensen–Shannon distance with small smoothing of zero probabilities."""
    keys = sorted(set(str(k) for k in baseline_counts) | set(str(k) for k in current_counts))
    if not keys:
        return 0.0
    b_raw = {k: float(baseline_counts.get(k, 0) or 0) + alpha for k in keys}
    c_raw = {k: float(current_counts.get(k, 0) or 0) + alpha for k in keys}
    b = _normalize_counts(b_raw, alpha=0.0)
    c = _normalize_counts(c_raw, alpha=0.0)
    m = {k: 0.5 * (b[k] + c[k]) for k in keys}

    def _kl(p: dict[str, float], q: dict[str, float]) -> float:
        s = 0.0
        for k in keys:
            pk = p[k]
            qk = max(q[k], EPS)
            if pk > 0:
                s += pk * math.log(pk / qk)
        return s

    js = 0.5 * _kl(b, m) + 0.5 * _kl(c, m)
    # JS divergence in nats → distance = sqrt(JS)
    return float(math.sqrt(max(0.0, js)))


def count_categories(values: Iterable[Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for v in values:
        if v is None:
            continue
        key = str(v)
        out[key] = out.get(key, 0.0) + 1.0
    return out


def severity_for_distance(
    distance: float,
    *,
    watch: float,
    warning: float,
    critical: float,
) -> str:
    if distance >= critical:
        return "CRITICAL"
    if distance >= warning:
        return "WARNING"
    if distance >= watch:
        return "WATCH"
    return "STABLE"


def max_status(statuses: Iterable[str]) -> str:
    rank = {
        "COLLECTING_BASELINE": 0,
        "STABLE": 1,
        "NOT_EVALUABLE": 1,
        "SUPPRESSED_DATA_QUALITY": 1,
        "WATCH": 2,
        "WARNING": 3,
        "CRITICAL": 4,
    }
    best = "STABLE"
    best_r = -1
    for s in statuses:
        r = rank.get(str(s), 0)
        if r > best_r:
            best_r = r
            best = str(s)
    return best
