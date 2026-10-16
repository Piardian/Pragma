"""M1 Z-score exhaustion + volume-absorption trigger engine."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Sequence

import numpy as np
import pandas as pd

from config.settings import ACTIVE_TRADING_HOURS_UTC


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


def _select_targets(
    targets: float | Sequence[float],
    direction: str,
    entry: float,
    *,
    risk: float | None = None,
    min_rr_tp1: float | None = None,
) -> tuple[float | None, float | None]:
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

    # Mean-reversion target selection is risk-aware: ignore intermediate
    # targets that cannot satisfy the TP1 R:R floor, then use the furthest
    # remaining target as TP2. If nothing qualifies, preserve the nearest /
    # furthest pair so the normal LOW_RR gate can report the rejection.
    if (
        min_rr_tp1 is not None
        and risk is not None
        and risk > 0
        and min_rr_tp1 > 0
    ):
        qualified = [
            value for value in candidates
            if abs(value - entry) / risk >= float(min_rr_tp1)
        ]
        if qualified:
            candidates = qualified
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
    volume_multiplier: float = 1.35,
    z_extreme: float = 1.75,
    z_recovery: float = 1.65,
    poi_type: str | None = None,
    center_price: float | None = None,
    cost_price: float = 0.0,
    sl_atr_buffer: float = 0.50,
    min_spread_to_sl_ratio: float = 4.0,
    min_rr_tp1: float = 1.0,
    min_rr_tp2: float = 1.35,
    session_hours_utc: tuple[int, int] | None = None,
    confirm_binance_delta: bool = True,
) -> TriggerDecision:
    """Evaluate closed M1 bars using POI touch, Z recovery and volume climax."""
    direction = direction.upper()
    if direction not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    required = {"open", "high", "low", "close", "tick_volume"}
    missing = required.difference(m1_bars.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if len(m1_bars) < 30:
        raise ValueError("At least 30 closed M1 bars are required")
    extra = ["volume_delta"] if "volume_delta" in m1_bars.columns else []
    bars = m1_bars.loc[:, ["open", "high", "low", "close", "tick_volume", *extra]].tail(30).astype(float).copy()
    bars.attrs.update(m1_bars.attrs)
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
    if not isfinite(float(min_rr_tp1)) or float(min_rr_tp1) <= 0:
        raise ValueError("min_rr_tp1 must be finite and positive")
    if not isfinite(float(min_rr_tp2)) or float(min_rr_tp2) <= 0:
        raise ValueError("min_rr_tp2 must be finite and positive")
    if not isfinite(float(sl_atr_buffer)) or float(sl_atr_buffer) < 0:
        raise ValueError("sl_atr_buffer must be finite and non-negative")
    if not isfinite(float(min_spread_to_sl_ratio)) or float(min_spread_to_sl_ratio) <= 0:
        raise ValueError("min_spread_to_sl_ratio must be finite and positive")
    if not isfinite(float(cost_price)) or float(cost_price) < 0:
        raise ValueError("cost_price must be finite and non-negative")
    cost_price = float(cost_price)
    session_hour_utc = None
    source_is_binance = str(bars.attrs.get("source", "")).lower() == "binance"
    session_allowed = True
    if isinstance(bars.index, pd.DatetimeIndex):
        last_timestamp = pd.Timestamp(bars.index[-1])
        if last_timestamp.tzinfo is None:
            last_timestamp = last_timestamp.tz_localize("UTC")
        else:
            last_timestamp = last_timestamp.tz_convert("UTC")
        session_hour_utc = int(last_timestamp.hour)
        session_start, session_end = session_hours_utc or ((0, 24) if source_is_binance else ACTIVE_TRADING_HOURS_UTC)
        session_allowed = session_start <= session_hour_utc < session_end

    close = bars["close"]
    sma_20 = close.rolling(20, min_periods=20).mean()
    std_20 = close.rolling(20, min_periods=20).std(ddof=0)
    z_score = (close - sma_20) / std_20.replace(0.0, np.nan)
    vol_sma_20 = bars["tick_volume"].rolling(20, min_periods=20).mean()
    last = bars.iloc[-1]
    last_z = z_score.iloc[-1]
    previous_z = z_score.iloc[-2]
    baseline = float(vol_sma_20.iloc[-1]) if pd.notna(vol_sma_20.iloc[-1]) else float("nan")

    last_three = bars.iloc[-3:]
    touch_mask = (last_three["low"] <= poi_high) & (last_three["high"] >= poi_low)
    poi_touched = bool(touch_mask.any())
    last_five_z = z_score.iloc[-5:]
    last_delta = float(bars["volume_delta"].iloc[-1]) if "volume_delta" in bars.columns else None
    delta_ok = True
    if direction == "LONG":
        extreme_indices = list(last_five_z[last_five_z <= -abs(z_extreme)].index)
        z_turn = bool(pd.notna(last_z) and pd.notna(previous_z) and last_z > previous_z)
        z_ok = bool(extreme_indices and z_turn and last_z >= -abs(z_recovery))
        candle_range = float(last["high"] - last["low"])
        wick_ratio = (float(min(last["open"], last["close"]) - last["low"]) / candle_range
                      if candle_range > 0 else 0.0)
        rejection = bool(last["close"] > last["open"] or wick_ratio >= 0.40)
        if confirm_binance_delta and source_is_binance and last_delta is not None:
            delta_ok = last_delta > 0 or wick_ratio >= 0.60
            rejection = rejection and delta_ok
        stop_loss = poi_low - float(sl_atr_buffer) * atr
        z_rule = f"Z<=-{abs(z_extreme):g} in last 5; current Z rises and >=-{abs(z_recovery):g}"
    else:
        extreme_indices = list(last_five_z[last_five_z >= abs(z_extreme)].index)
        z_turn = bool(pd.notna(last_z) and pd.notna(previous_z) and last_z < previous_z)
        z_ok = bool(extreme_indices and z_turn and last_z <= abs(z_recovery))
        candle_range = float(last["high"] - last["low"])
        wick_ratio = (float(last["high"] - max(last["open"], last["close"])) / candle_range
                      if candle_range > 0 else 0.0)
        rejection = bool(last["close"] < last["open"] or wick_ratio >= 0.40)
        if confirm_binance_delta and source_is_binance and last_delta is not None:
            delta_ok = last_delta < 0 or wick_ratio >= 0.60
            rejection = rejection and delta_ok
        stop_loss = poi_high + float(sl_atr_buffer) * atr
        z_rule = f"Z>=+{abs(z_extreme):g} in last 5; current Z falls and <=+{abs(z_recovery):g}"

    entry = float(last["close"])
    effective_entry = entry + cost_price if direction == "LONG" else entry - cost_price
    risk = abs(effective_entry - stop_loss)
    is_mean_reversion = poi_type in ("LONG_MEAN_REVERSION", "SHORT_MEAN_REVERSION")
    target_tp1_floor = float(min_rr_tp1) if is_mean_reversion else None
    tp1, tp2 = _select_targets(
        take_profit, direction, effective_entry,
        risk=risk, min_rr_tp1=target_tp1_floor,
    )
    touched_positions = [len(bars) - 3 + offset
                         for offset, touched in enumerate(touch_mask.to_numpy()) if touched]
    climax_pos = None
    volume_factor = float("nan")
    for pos in touched_positions:
        baseline_at_touch = float(vol_sma_20.iloc[pos]) if pd.notna(vol_sma_20.iloc[pos]) else float("nan")
        if isfinite(baseline_at_touch) and baseline_at_touch > 0:
            factor = float(bars["tick_volume"].iloc[pos]) / baseline_at_touch
            if factor >= volume_multiplier:
                climax_pos, volume_factor = pos, factor
                break
    volume_ok = climax_pos is not None

    rr_tp1 = abs(tp1 - effective_entry) / risk if tp1 is not None and risk > 0 else None
    rr_tp2 = abs(tp2 - effective_entry) / risk if tp2 is not None and risk > 0 else None
    distinct_targets = bool(
        tp1 is not None and tp2 is not None and abs(tp1 - tp2) > 1e-12
    )
    is_trend_pullback = poi_type in ("LONG_TREND_PULLBACK", "SHORT_TREND_PULLBACK")
    if is_trend_pullback:
        split_rr_ok = bool(
            distinct_targets and rr_tp1 is not None and rr_tp1 >= 1.2
            and rr_tp2 is not None and rr_tp2 >= 2.0
        )
        target_fallback = bool(
            distinct_targets and rr_tp1 is not None and rr_tp1 < 1.2
            and rr_tp2 is not None and rr_tp2 >= 1.6
        )
    elif is_mean_reversion:
        split_rr_ok = bool(
            distinct_targets and rr_tp1 is not None and rr_tp1 >= float(min_rr_tp1)
            and rr_tp2 is not None and rr_tp2 >= float(min_rr_tp2)
        )
        # Mean-reversion uses risk-aware target selection above instead of
        # promoting an arbitrary near TP1 to the main target.
        target_fallback = False
    else:
        split_rr_ok = bool(
            distinct_targets and rr_tp1 is not None and rr_tp1 >= 1.0
            and rr_tp2 is not None and rr_tp2 >= 1.8
        )
        target_fallback = bool(
            distinct_targets and rr_tp1 is not None and rr_tp1 < 1.0
            and rr_tp2 is not None and rr_tp2 >= 1.5
        )
    if target_fallback:
        tp1 = tp2
        rr_tp1 = rr_tp2
    single_target_min_rr = (
        float(min_rr_tp2) if is_mean_reversion
        else 2.0 if is_trend_pullback else min_rr
    )
    single_target_rr_ok = bool(
        not distinct_targets and rr_tp1 is not None and rr_tp1 >= single_target_min_rr
    )
    rr = rr_tp1
    center = float(center_price) if center_price is not None else (poi_low + poi_high) / 2.0
    reclaim_required = is_mean_reversion
    if poi_type == "LONG_MEAN_REVERSION":
        level_reclaim = bool(
            float(last["close"]) >= center
            or (
                float(last["close"]) > float(last["open"])
                and float(last["close"]) >= poi_low + 0.5 * (poi_high - poi_low)
            )
        )
    elif poi_type == "SHORT_MEAN_REVERSION":
        level_reclaim = bool(
            float(last["close"]) <= center
            or (
                float(last["close"]) < float(last["open"])
                and float(last["close"]) <= poi_high - 0.5 * (poi_high - poi_low)
            )
        )
    else:
        level_reclaim = True
    metrics = {
        "poi_touched": poi_touched,
        "poi_touch_positions": [int(p) for p in touched_positions],
        "z_score": float(last_z) if pd.notna(last_z) else None,
        "z_score_previous": float(previous_z) if pd.notna(previous_z) else None,
        "z_condition": z_ok,
        "z_turn": z_turn,
        "z_extreme_indices": [str(i) for i in extreme_indices],
        "z_rule": z_rule,
        "tick_volume": float(last["tick_volume"]),
        "vol_sma_20": baseline if isfinite(baseline) else None,
        "volume_multiplier": volume_factor if isfinite(volume_factor) else None,
        "volume_climax": volume_ok,
        "volume_climax_position": int(climax_pos) if climax_pos is not None else None,
        "rejection": rejection,
        "volume_delta": last_delta,
        "volume_delta": last_delta,
        "binance_delta_confirmation": delta_ok,
        "rr_ratio": rr,
        "rr_tp1": rr_tp1,
        "rr_tp2": rr_tp2,
        "target_fallback_to_tp2": target_fallback,
        "distinct_targets": distinct_targets,
        "split_rr_gate": split_rr_ok,
        "single_target_rr_gate": single_target_rr_ok,
        "poi_type": poi_type,
        "center_price": center,
        "level_reclaim_required": reclaim_required,
        "level_reclaim": level_reclaim,
        "min_rr": single_target_min_rr,
        "min_rr_tp1": float(min_rr_tp1),
        "min_rr_tp2": float(min_rr_tp2),
        "entry_price": entry,
        "effective_entry": effective_entry,
        "cost_price": cost_price,
        "session_hour_utc": session_hour_utc,
        "session_allowed": session_allowed,
        "high_spread_to_sl": bool(cost_price > 0 and risk < float(min_spread_to_sl_ratio) * cost_price),
        "min_spread_to_sl_ratio": float(min_spread_to_sl_ratio),
        "sl_atr_buffer": float(sl_atr_buffer),
        "stop_loss": stop_loss,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
    }

    def decision(execute: bool, reason: str) -> TriggerDecision:
        return TriggerDecision(execute, direction, entry, stop_loss, tp1, tp2,
                              tp1, rr, reason, metrics)

    if not session_allowed:
        return decision(False, "SESSION_HOURS")
    if cost_price > 0 and risk < float(min_spread_to_sl_ratio) * cost_price:
        return decision(False, "HIGH_SPREAD_TO_SL")
    if not poi_touched:
        return decision(False, "OUTSIDE_POI")
    if not z_ok:
        return decision(False, "Z_SCORE_NOT_CONFIRMED")
    if not volume_ok:
        return decision(False, "VOLUME_CLIMAX_NOT_CONFIRMED")
    if not rejection:
        return decision(False, "REJECTION_NOT_CONFIRMED")
    if reclaim_required and not level_reclaim:
        return decision(False, "LEVEL_RECLAIM_NOT_CONFIRMED")
    if tp1 is None:
        return decision(False, "NO_VALID_TP")
    if target_fallback:
        pass
    elif distinct_targets:
        if not split_rr_ok:
            return decision(False, "LOW_RR")
    elif not single_target_rr_ok:
        return decision(False, "LOW_RR")
    return decision(True, "EXECUTE")


class TriggerEngine:
    def evaluate(self, m1_bars: pd.DataFrame, direction: str, poi_low: float,
                 poi_high: float, atr_14: float,
                 take_profit: float | Sequence[float], **kwargs: Any) -> TriggerDecision:
        return evaluate_trigger(m1_bars, direction, poi_low, poi_high,
                                atr_14, take_profit, **kwargs)
