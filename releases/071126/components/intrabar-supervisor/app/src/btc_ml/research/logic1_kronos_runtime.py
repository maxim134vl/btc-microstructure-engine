"""Kronos-mini research runtime: closed-bar sample paths for the OPEN prior.

Phase 3. Isolated from ``logic1_kronos_open_prior`` so that module stays free of
torch / HuggingFace. Vendor ``KronosPredictor.predict(sample_count=N)`` averages
the N paths internally; this runtime calls ``sample_count=1`` N times so
agree_frac / disagreement stay defined.

Never imported by timeframe_manager. Weights live in a local HF cache and are
not fetched from the live paper cycle.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from btc_ml.research.logic1_kronos_open_prior import (
    LOOKBACK_BARS,
    PRED_LEN_BY_TF,
    SAMPLE_COUNT,
    TF_SECONDS,
    last_closed_bar_open,
    lookback_is_causal,
    select_closed_lookback,
)

ROOT = Path(__file__).resolve().parents[3]
VENDOR_ROOT = ROOT / "data/research/kronos/vendor/Kronos"
HF_CACHE = ROOT / "data/research/kronos/hf_cache"
CHECKPOINT = "NeoQuasar/Kronos-mini"
TOKENIZER = "NeoQuasar/Kronos-Tokenizer-2k"
OHLCV = ("open", "high", "low", "close", "volume")
MIN_LOOKBACK = 64


def resolve_device(prefer: str | None = None) -> str:
    wanted = str(prefer or "").strip().lower()
    if wanted in {"cpu", "mps", "cuda", "cuda:0"}:
        return wanted
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda:0"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def configure_hf_cache(cache_dir: Path | None = None) -> Path:
    cache = Path(cache_dir or HF_CACHE)
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(cache)
    os.environ["HF_HUB_CACHE"] = str(cache)
    return cache


def future_bar_opens(source_bar_close: Any, timeframe: str, pred_len: int) -> pd.DatetimeIndex:
    """Calendar opens of the next ``pred_len`` bars. No OHLCV of those bars."""
    close = pd.Timestamp(source_bar_close)
    if close.tzinfo is None:
        close = close.tz_localize("UTC")
    else:
        close = close.tz_convert("UTC")
    last_open = last_closed_bar_open(close, timeframe)
    if last_open is None:
        raise ValueError(f"unknown timeframe: {timeframe}")
    step = close - last_open
    stamps = [close + step * i for i in range(int(pred_len))]
    return pd.DatetimeIndex(stamps, tz="UTC")


def lookback_ohlcv(
    bars: pd.DataFrame,
    *,
    source_bar_close: Any,
    timeframe: str,
    lookback_bars: int = LOOKBACK_BARS,
) -> pd.DataFrame:
    window = select_closed_lookback(
        bars,
        source_bar_close=source_bar_close,
        timeframe=timeframe,
        lookback_bars=lookback_bars,
    )
    if window.empty:
        return window
    missing = [c for c in OHLCV if c not in window.columns]
    if missing:
        raise ValueError(f"lookback missing columns: {missing}")
    out = window.loc[:, list(OHLCV) + ["timestamp"]].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    for col in OHLCV:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["timestamp", *OHLCV]).reset_index(drop=True)
    if "amount" not in out.columns:
        out["amount"] = out["volume"] * out[["open", "high", "low", "close"]].mean(axis=1)
    return out


def lookback_atr(window: pd.DataFrame) -> float:
    if window is None or len(window) < 2:
        return float("nan")
    high = pd.to_numeric(window["high"], errors="coerce")
    low = pd.to_numeric(window["low"], errors="coerce")
    close = pd.to_numeric(window["close"], errors="coerce")
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    val = float(tr.iloc[1:].mean())
    return val if np.isfinite(val) and val > 0 else float("nan")


def lookback_volume_median(window: pd.DataFrame) -> float:
    if window is None or window.empty:
        return float("nan")
    med = float(pd.to_numeric(window["volume"], errors="coerce").median())
    return med if np.isfinite(med) and med > 0 else float("nan")


def _import_vendor():
    if not VENDOR_ROOT.is_dir():
        raise FileNotFoundError(f"Kronos vendor missing: {VENDOR_ROOT}")
    root = str(VENDOR_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from model import Kronos, KronosPredictor, KronosTokenizer

    return Kronos, KronosTokenizer, KronosPredictor


def load_predictor(
    *,
    checkpoint: str = CHECKPOINT,
    tokenizer: str = TOKENIZER,
    device: str | None = None,
    max_context: int = 2048,
    cache_dir: Path | None = None,
    local_files_only: bool = False,
):
    cache = configure_hf_cache(cache_dir)
    Kronos, KronosTokenizer, KronosPredictor = _import_vendor()
    tok = KronosTokenizer.from_pretrained(
        tokenizer,
        cache_dir=str(cache),
        local_files_only=local_files_only,
    )
    model = Kronos.from_pretrained(
        checkpoint,
        cache_dir=str(cache),
        local_files_only=local_files_only,
    )
    return KronosPredictor(
        model,
        tok,
        device=resolve_device(device),
        max_context=int(max_context),
    )


def _vendor_keep_samples(
    predictor: Any,
    x: np.ndarray,
    x_stamp: np.ndarray,
    y_stamp: np.ndarray,
    *,
    pred_len: int,
    temperature: float,
    top_p: float,
    sample_count: int,
) -> np.ndarray:
    """Vendor generate averages sample_count. Capture the 4-d tensor before mean."""
    import model.kronos as kronos_mod

    captured: dict[str, np.ndarray] = {}
    orig_mean = kronos_mod.np.mean

    def _mean(a, axis=None, *args, **kwargs):  # type: ignore[no-untyped-def]
        if axis == 1 and getattr(a, "ndim", 0) == 4:
            captured["samples"] = np.asarray(a)
        return orig_mean(a, axis=axis, *args, **kwargs)

    kronos_mod.np.mean = _mean
    try:
        predictor.generate(
            x,
            x_stamp,
            y_stamp,
            pred_len,
            float(temperature),
            0,
            float(top_p),
            int(sample_count),
            False,
        )
    finally:
        kronos_mod.np.mean = orig_mean
    samples = captured.get("samples")
    if samples is None or samples.ndim != 4:
        raise RuntimeError("could not recover unaveraged Kronos sample paths")
    return samples[:, :, -int(pred_len) :, :]


def _predict_terminals_loop(
    predictor: Any,
    x_df: pd.DataFrame,
    x_timestamp: pd.Series,
    y_timestamp: pd.Series,
    *,
    horizon: int,
    n_paths: int,
    temperature: float,
    top_p: float,
) -> dict[str, np.ndarray]:
    closes: list[float] = []
    volumes: list[float] = []
    for _ in range(n_paths):
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=horizon,
            T=float(temperature),
            top_p=float(top_p),
            sample_count=1,
            verbose=False,
        )
        closes.append(float(pred_df["close"].iloc[-1]))
        volumes.append(float(pred_df["volume"].iloc[-1]))
    return {
        "terminal_close": np.asarray(closes, dtype=float),
        "terminal_volume": np.asarray(volumes, dtype=float),
    }


def predict_terminals(
    predictor: Any,
    lookback: pd.DataFrame,
    *,
    source_bar_close: Any,
    timeframe: str,
    pred_len: int | None = None,
    n_paths: int = SAMPLE_COUNT,
    temperature: float = 1.0,
    top_p: float = 0.9,
) -> dict[str, np.ndarray]:
    """Return unaveraged terminal close/volume, one row per sample path."""
    n = int(n_paths)
    if n < 2:
        raise ValueError("n_paths must be >= 2 so disagreement is defined")
    horizon = int(pred_len or PRED_LEN_BY_TF.get(str(timeframe).upper() or "", 8))
    x_df = lookback.loc[:, ["open", "high", "low", "close", "volume", "amount"]].copy()
    x_timestamp = pd.Series(pd.to_datetime(lookback["timestamp"], utc=True))
    y_timestamp = pd.Series(future_bar_opens(source_bar_close, timeframe, horizon))
    cutoff = pd.Timestamp(source_bar_close)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    if bool((x_timestamp >= cutoff).any()):
        raise ValueError("lookback timestamp leaked past source_bar_close")
    if not hasattr(predictor, "generate"):
        return _predict_terminals_loop(
            predictor,
            x_df,
            x_timestamp,
            y_timestamp,
            horizon=horizon,
            n_paths=n,
            temperature=temperature,
            top_p=top_p,
        )
    from model.kronos import calc_time_stamps

    clip = float(getattr(predictor, "clip", 5) or 5)
    x = x_df.to_numpy(dtype=np.float32)
    x_stamp = calc_time_stamps(x_timestamp).to_numpy(dtype=np.float32)
    y_stamp = calc_time_stamps(y_timestamp).to_numpy(dtype=np.float32)
    x_mean = np.mean(x, axis=0)
    x_std = np.std(x, axis=0)
    x_norm = np.clip((x - x_mean) / (x_std + 1e-5), -clip, clip)
    samples = _vendor_keep_samples(
        predictor,
        x_norm[np.newaxis, :],
        x_stamp[np.newaxis, :],
        y_stamp[np.newaxis, :],
        pred_len=horizon,
        temperature=temperature,
        top_p=top_p,
        sample_count=n,
    )
    denorm = samples * (x_std + 1e-5) + x_mean
    return {
        "terminal_close": np.asarray(denorm[0, :, -1, 3], dtype=float),
        "terminal_volume": np.asarray(denorm[0, :, -1, 4], dtype=float),
    }


def cloud_for_closed_bar(
    bars: pd.DataFrame,
    *,
    source_bar_close: Any,
    timeframe: str,
    predictor: Any | None = None,
    lookback_bars: int = LOOKBACK_BARS,
    n_paths: int = SAMPLE_COUNT,
    pred_len: int | None = None,
    temperature: float = 1.0,
    top_p: float = 0.9,
) -> dict[str, Any] | None:
    """One cloud for ``attach_kronos_features``. None = fail-open upstream."""
    window = lookback_ohlcv(
        bars,
        source_bar_close=source_bar_close,
        timeframe=timeframe,
        lookback_bars=lookback_bars,
    )
    if len(window) < min(int(lookback_bars), MIN_LOOKBACK):
        return None
    if not lookback_is_causal(window, source_bar_close=source_bar_close, timeframe=timeframe):
        raise ValueError("lookback is not causal")
    last_close = float(window["close"].iloc[-1])
    if last_close <= 0 or not np.isfinite(last_close):
        return None
    if predictor is None:
        return None
    pred = predict_terminals(
        predictor,
        window,
        source_bar_close=source_bar_close,
        timeframe=timeframe,
        pred_len=pred_len,
        n_paths=n_paths,
        temperature=temperature,
        top_p=top_p,
    )
    return {
        "last_close": last_close,
        "terminal_close": pred["terminal_close"],
        "terminal_volume": pred["terminal_volume"],
        "lookback_volume_median": lookback_volume_median(window),
        "lookback_atr": lookback_atr(window),
        "lookback_bars": int(len(window)),
        "source_bar_close": str(source_bar_close),
        "timeframe": str(timeframe).upper(),
    }


def load_m15_ohlcv(path: Path | None = None) -> pd.DataFrame:
    candle = Path(path or (ROOT / "data/cognition/candle_structure_memory.parquet"))
    frame = pd.read_parquet(candle, columns=["timestamp", *OHLCV])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return frame.dropna(subset=["timestamp", *OHLCV]).sort_values("timestamp").reset_index(drop=True)


def smoke_windows(bars: pd.DataFrame, *, timeframe: str = "M15", n_windows: int = 20, lookback_bars: int = LOOKBACK_BARS) -> list[Any]:
    """Evenly spaced closed-bar cutoffs that have a full lookback."""
    stamps = pd.to_datetime(bars["timestamp"], utc=True)
    step = int(PRED_LEN_BY_TF.get(str(timeframe).upper(), 8))
    seconds = int(TF_SECONDS[str(timeframe).upper()])
    usable = list(range(int(lookback_bars) - 1, len(stamps) - step))
    if not usable:
        return []
    if n_windows >= len(usable):
        chosen = usable
    else:
        idxs = np.linspace(0, len(usable) - 1, int(n_windows), dtype=int)
        chosen = [usable[int(i)] for i in idxs]
    out: list[Any] = []
    seen: set[str] = set()
    for i in chosen:
        close = stamps.iloc[i] + pd.Timedelta(seconds=seconds)
        key = str(close)
        if key in seen:
            continue
        seen.add(key)
        out.append(close)
    return out


def predictor_kwargs_from_config(cfg: Mapping[str, Any] | None = None) -> dict[str, Any]:
    model = dict((cfg or {}).get("model") or {})
    return {
        "checkpoint": str(model.get("checkpoint") or CHECKPOINT),
        "tokenizer": str(model.get("tokenizer") or TOKENIZER),
        "max_context": int(model.get("max_context") or 2048),
        "device": None if str(model.get("device") or "").startswith("cpu_or") else model.get("device"),
    }
