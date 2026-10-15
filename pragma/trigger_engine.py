"""M1 Z-score exhaustion + volume-absorption trigger engine."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TriggerDecision:
    execute: bool
    direction: str
    entry_price: float | None
    stop_loss: float | None
    take_profit_1: float | None
    take_profit_2: float | None
    take_profit: float | None
    rr_ratio: float | None
    reason: str
    metrics: dict[str, Any]


def _select_targets(targets: float | Sequence[float], direction: str,
                    entry: float) -> tuple[float | None, float | None]:
    if isinstance(targets, (int, float, np.number)):
        candidates = [float(targets)]
    else:
        candidates = [float(value) for value in targets]
    if not all(isfinite(value) for value in candidates):
        raise ValueError("take_profit targets must be finite")
    if direction == "LONG":
        candidates = sorted({value for value in candidates if value > entry})
    else:
        candidates = sorted({value for value in candidates if value < entry}, reverse=True)
    if not candidates:
        return None, None
    return candidates[0], candidates[-1]


def evaluate_trigger(
    m1_bars: pd.DataFrame,
    direction: str,
    poi_low: float,
    poi_high: float,
    atr_14: float,
    take_profit: float | Sequence[float],
    *,
    min_rr: float = 1.5,
    volume_multiplier: float = 1.8,
    z_extreme: float = 2.0,
    z_recovery: float = 1.5,
) -> TriggerDecision:
    """Evaluate the latest supplied *closed* M1 bar against an active POI.

    Caller must remove any forming bar before passing the series. At least 30
    closed bars are required. R:R is always evaluated using the nearest valid
    directional target (TP1), even when TP2 is much farther away.
    """
    direction = direction.upper()
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    required = {"open", "high", "low", "close", "tick_volume"}
    missing = required.difference(m1_bars.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if len(m1_bars) < 30:
        raise ValueError("At least 30 closed M1 bars are required")
    bars = m1_bars.loc[:, ["open", "high", "low", "close", "tick_volume"]].tail(30).astype(float).copy()
    if not np.isfinite(bars.to_numpy()).all():
        raise ValueError("M1 bars contain NaN or infinite values")
    if (bars["high"] < bars["low"]).any():
        raise ValueError("M1 high must be >= low")
    if (bars["tick_volume"] < 0).any():
        raise ValueError("tick_volume cannot be negative")
    poi_low, poi_high = float(poi_low), float(poi_high)
    if poi_low > poi_high:
        raise ValueError("poi_low must be <= poi_high")
    atr = float(atr_14)
    if not isfinite(atr) or atr <= 0:
        raise ValueError("atr_14 must be a finite number greater than zero")
    if min_rr <= 0 or volume_multiplier <= 0:
        raise ValueError("min_rr and volume_multiplier must be positive")

    close = bars["close"]
    sma_20 = close.rolling(20, min_periods=20).mean()
    std_20 = close.rolling(20, min_periods=20).std(ddof=0)
    z_score = (close - sma_20) / std_20.replace(0.0, np.nan)
    vol_sma_20 = bars["tick_volume"].rolling(20, min_periods=20).mean()
    last = bars.iloc[-1]
    last_z = z_score.iloc[-1]
    baseline = float(vol_sma_20.iloc[-1]) if pd.notna(vol_sma_20.iloc[-1]) else float("nan")

    if direction == "LONG":
        extremes = z_score.iloc[-3:]
        extreme_indices = list(extremes[extremes <= -abs(z_extreme)].index)
        z_ok = bool(extreme_indices and pd.notna(last_z) and last_z >= -abs(z_recovery))
        candle_range = float(last["high"] - last["low"])
        wick_ratio = (float(min(last["open"], last["close"]) - last["low"]) / candle_range
                      if candle_range > 0 else 0.0)
        rejection = bool(last["close"] > last["open"] or wick_ratio >= 0.50)
        stop_loss = poi_low - 0.5 * atr
        z_rule = "Z<=-2 followed by recovery to Z>=-1.5"
    else:
        extremes = z_score.iloc[-3:]
        extreme_indices = list(extremes[extremes >= abs(z_extreme)].index)
        z_ok = bool(extreme_indices and pd.notna(last_z) and last_z <= abs(z_recovery))
        candle_range = float(last["high"] - last["low"])
        wick_ratio = (float(last["high"] - max(last["open"], last["close"])) / candle_range
                      if candle_range > 0 else 0.0)
        rejection = bool(last["close"] < last["open"] or wick_ratio >= 0.50)
        stop_loss = poi_high + 0.5 * atr
        z_rule = "Z>=+2 followed by recovery to Z<=+1.5"

    entry = float(last["close"])
    tp1, tp2 = _select_targets(take_profit, direction, entry)
    poi_touched = bool(
        poi_low <= entry <= poi_high
        or (float(last["low"]) <= poi_high and float(last["high"]) >= poi_low)
    )

    # Volume climax can be the latest bar or a preceding qualifying Z-extreme bar.
    volume_candidates = [len(bars) - 1]
    extreme_positions = {bars.index.get_loc(idx) for idx in extreme_indices}
    volume_candidates.extend(sorted(i for i in extreme_positions if i < len(bars) - 1))
    volume_candidates = list(dict.fromkeys(volume_candidates))
    climax_pos = None
    volume_factor = float("nan")
    if isfinite(baseline) and baseline > 0:
        for pos in volume_candidates:
            factor = float(bars["tick_volume"].iloc[pos]) / baseline
            if factor >= volume_multiplier:
                climax_pos, volume_factor = pos, factor
                break
    volume_ok = climax_pos is not None

    risk = abs(entry - stop_loss)
    rr = abs(tp1 - entry) / risk if tp1 is not None and risk > 0 else None
    metrics = {
        "poi_touched": poi_touched,
        "z_score": float(last_z) if pd.notna(last_z) else None,
        "z_condition": z_ok,
        "z_extreme_indices": [str(i) for i in extreme_indices],
        "z_rule": z_rule,
        "tick_volume": float(last["tick_volume"]),
        "vol_sma_20": baseline if isfinite(baseline) else None,
        "volume_multiplier": volume_factor if isfinite(volume_factor) else None,
        "volume_climax": volume_ok,
        "volume_climax_position": int(climax_pos) if climax_pos is not None else None,
        "rejection": rejection,
        "rr_ratio": rr,
        "min_rr": min_rr,
        "entry_price": entry,
        "stop_loss": stop_loss,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
    }

    def decision(execute: bool, reason: str) -> TriggerDecision:
        return TriggerDecision(execute, direction, entry, stop_loss, tp1, tp2,
                              tp1, rr, reason, metrics)

    if not poi_touched:
        return decision(False, "OUTSIDE_POI")
    if not z_ok:
        return decision(False, "Z_SCORE_NOT_CONFIRMED")
    if not volume_ok:
        return decision(False, "VOLUME_CLIMAX_NOT_CONFIRMED")
    if not rejection:
        return decision(False, "REJECTION_NOT_CONFIRMED")
    if tp1 is None:
        return decision(False, "NO_VALID_TP")
    if rr is None or rr < min_rr:
        return decision(False, "LOW_RR")
    return decision(True, "EXECUTE")


class TriggerEngine:
    def evaluate(self, m1_bars: pd.DataFrame, direction: str, poi_low: float,
                 poi_high: float, atr_14: float,
                 take_profit: float | Sequence[float], **kwargs: Any) -> TriggerDecision:
        return evaluate_trigger(m1_bars, direction, poi_low, poi_high,
                                atr_14, take_profit, **kwargs)
