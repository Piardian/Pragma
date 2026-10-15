"""M1 Z-score exhaustion + volume-absorption trigger engine."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TriggerDecision:
    execute: bool
    direction: str
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    rr_ratio: float | None
    reason: str
    metrics: dict[str, Any]


def evaluate_trigger(
    m1_bars: pd.DataFrame,
    direction: str,
    poi_low: float,
    poi_high: float,
    atr_14: float,
    take_profit: float,
    *,
    min_rr: float = 1.5,
    volume_multiplier: float = 1.8,
    z_extreme: float = 2.0,
    z_recovery: float = 1.5,
) -> TriggerDecision:
    """Evaluate the most recently closed M1 bar against a POI.

    At least 30 bars are required. SMA/std and volume SMA use their specified
    20-period windows. A volume climax may be on the latest candle or on a
    preceding candle that registered the qualifying Z-score extreme. Rejection
    is checked on the latest closed candle.
    """
    direction = direction.upper()
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    required = {"open", "high", "low", "close", "tick_volume"}
    missing = required.difference(m1_bars.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if len(m1_bars) < 30:
        raise ValueError("At least 30 M1 bars are required")
    bars = m1_bars.loc[:, ["open", "high", "low", "close", "tick_volume"]].tail(30).astype(float).copy()
    if not np.isfinite(bars.to_numpy()).all():
        raise ValueError("M1 bars contain NaN or infinite values")
    if (bars["high"] < bars["low"]).any():
        raise ValueError("M1 high must be >= low")
    if (bars["tick_volume"] < 0).any():
        raise ValueError("tick_volume cannot be negative")
    if poi_low > poi_high:
        raise ValueError("poi_low must be <= poi_high")
    atr = float(atr_14)
    if not isfinite(atr) or atr <= 0:
        raise ValueError("atr_14 must be a finite number greater than zero")
    target = float(take_profit)
    if not isfinite(target):
        raise ValueError("take_profit must be finite")
    if min_rr <= 0 or volume_multiplier <= 0:
        raise ValueError("min_rr and volume_multiplier must be positive")

    close = bars["close"]
    sma_20 = close.rolling(20, min_periods=20).mean()
    std_20 = close.rolling(20, min_periods=20).std(ddof=0)
    z_score = (close - sma_20) / std_20.replace(0.0, np.nan)
    vol_sma_20 = bars["tick_volume"].rolling(20, min_periods=20).mean()
    last = bars.iloc[-1]
    last_z = z_score.iloc[-1]
    last_vol_sma = vol_sma_20.iloc[-1]

    if direction == "LONG":
        extreme_series = z_score.iloc[-3:]
        extreme_indices = list(extreme_series[extreme_series <= -abs(z_extreme)].index)
        z_ok = bool(extreme_indices and pd.notna(last_z) and last_z >= -abs(z_recovery))
        candle_range = float(last["high"] - last["low"])
        lower_wick_ratio = (float(min(last["open"], last["close"]) - last["low"]) / candle_range
                            if candle_range > 0 else 0.0)
        rejection = bool(last["close"] > last["open"] or lower_wick_ratio >= 0.50)
        stop_loss = float(poi_low) - 0.5 * atr
        extreme_desc = "Z<=-2 followed by recovery to Z>=-1.5"
    else:
        extreme_series = z_score.iloc[-3:]
        extreme_indices = list(extreme_series[extreme_series >= abs(z_extreme)].index)
        z_ok = bool(extreme_indices and pd.notna(last_z) and last_z <= abs(z_recovery))
        candle_range = float(last["high"] - last["low"])
        upper_wick_ratio = (float(last["high"] - max(last["open"], last["close"])) / candle_range
                            if candle_range > 0 else 0.0)
        rejection = bool(last["close"] < last["open"] or upper_wick_ratio >= 0.50)
        stop_loss = float(poi_high) + 0.5 * atr
        extreme_desc = "Z>=+2 followed by recovery to Z<=+1.5"

    poi_touched = bool(
        float(poi_low) <= float(last["close"]) <= float(poi_high)
        or (float(last["low"]) <= float(poi_high) and float(last["high"]) >= float(poi_low))
    )

    # The latest candle is always eligible; earlier candles are eligible only
    # when they are the Z-score extreme candle(s) that preceded recovery.
    volume_candidates = [len(bars) - 1]
    extreme_pos = {bars.index.get_loc(idx) for idx in extreme_indices}
    volume_candidates.extend(sorted(i for i in extreme_pos if i < len(bars) - 1))
    volume_candidates = list(dict.fromkeys(volume_candidates))
    baseline = float(last_vol_sma) if pd.notna(last_vol_sma) else float("nan")
    climax_pos = None
    volume_factor = float("nan")
    if isfinite(baseline) and baseline > 0:
        for pos in volume_candidates:
            factor = float(bars["tick_volume"].iloc[pos]) / baseline
            if factor >= volume_multiplier:
                climax_pos = pos
                volume_factor = factor
                break
    volume_ok = climax_pos is not None

    entry = float(last["close"])
    risk = abs(entry - stop_loss)
    rr = abs(target - entry) / risk if risk > 0 else float("inf")
    metrics = {
        "poi_touched": poi_touched,
        "z_score": float(last_z) if pd.notna(last_z) else None,
        "z_condition": z_ok,
        "z_extreme_indices": [str(i) for i in extreme_indices],
        "z_rule": extreme_desc,
        "tick_volume": float(last["tick_volume"]),
        "vol_sma_20": baseline if isfinite(baseline) else None,
        "volume_multiplier": volume_factor if isfinite(volume_factor) else None,
        "volume_climax": volume_ok,
        "volume_climax_position": int(climax_pos) if climax_pos is not None else None,
        "rejection": rejection,
        "rr_ratio": rr if isfinite(rr) else None,
        "min_rr": min_rr,
        "entry_price": entry,
        "stop_loss": stop_loss,
        "take_profit": target,
    }

    if not poi_touched:
        return TriggerDecision(False, direction, entry, stop_loss, target, rr, "OUTSIDE_POI", metrics)
    if not z_ok:
        return TriggerDecision(False, direction, entry, stop_loss, target, rr, "Z_SCORE_NOT_CONFIRMED", metrics)
    if not volume_ok:
        return TriggerDecision(False, direction, entry, stop_loss, target, rr, "VOLUME_CLIMAX_NOT_CONFIRMED", metrics)
    if not rejection:
        return TriggerDecision(False, direction, entry, stop_loss, target, rr, "REJECTION_NOT_CONFIRMED", metrics)
    if rr < min_rr:
        return TriggerDecision(False, direction, entry, stop_loss, target, rr, "LOW_RR", metrics)
    return TriggerDecision(True, direction, entry, stop_loss, target, rr, "EXECUTE", metrics)


class TriggerEngine:
    def evaluate(self, m1_bars: pd.DataFrame, direction: str, poi_low: float,
                 poi_high: float, atr_14: float, take_profit: float,
                 **kwargs: Any) -> TriggerDecision:
        return evaluate_trigger(m1_bars, direction, poi_low, poi_high,
                                atr_14, take_profit, **kwargs)
