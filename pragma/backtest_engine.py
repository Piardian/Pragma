"""Causal walk-forward backtest engine for Pragma.

All decisions are made after an M1 bar closes. Daily profiles use only the
previous completed observed session; VWAP uses the active session prefix;
M15 ATR uses only fully closed M15 bars. OHLC ambiguity is resolved
conservatively: stop loss takes priority over targets.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from typing import Any

import numpy as np
import pandas as pd

from pragma.amt_engine import calculate_volume_profile
from pragma.data.mt5_data import MT5DataClient, filter_closed_bars
from pragma.data.binance_data import BinanceDataClient, normalize_binance_symbol
from pragma.macro_gate import MacroGate
from pragma.instrument_profiles import default_trigger_tf_for_symbol, get_instrument_profile, normalize_trigger_tf, trigger_tf_minutes
from pragma.regime_poi_engine import generate_regime_pois
from pragma.trigger_engine import evaluate_trigger
from pragma.vwap_engine import VWAPEngine


@dataclass(frozen=True)
class BacktestTrade:
    symbol: str
    direction: str
    poi_type: str
    regime: str
    entry_time: str
    exit_time: str
    entry_price: float
    initial_stop_loss: float
    tp1: float
    tp2: float
    exit_reason: str
    r_multiple: float
    tp1_taken: bool


@dataclass(frozen=True)
class BacktestReport:
    symbol: str
    bars_processed: int
    total_trades: int
    win_rate: float
    profit_factor: float
    net_r: float
    expectancy_r: float
    max_drawdown_r: float
    max_daily_drawdown_pct: float
    max_total_drawdown_pct: float
    trades_by_regime: dict[str, dict[str, float]]
    trades_by_poi_type: dict[str, dict[str, float]]
    trade_outcomes: dict[str, int]
    spread_points: float
    point_size: float
    funnel_counts: dict[str, int]
    instrument_profile: str = "MOMENTUM_TREND"
    risk_per_trade_pct: float = 1.0
    trigger_tf: str = "M1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _OpenTrade:
    symbol: str
    direction: str
    poi_type: str
    regime: str
    entry_time: pd.Timestamp
    entry_price: float
    initial_stop_loss: float
    stop_loss: float
    tp1: float
    tp2: float
    initial_risk: float
    r_multiple: float = 0.0
    tp1_taken: bool = False
    tp1_close_pct: float = 0.50
    be_offset_r: float | None = 0.0


def _trade_record(position: _OpenTrade, timestamp: pd.Timestamp,
                  reason: str) -> BacktestTrade:
    return BacktestTrade(
        position.symbol, position.direction, position.poi_type, position.regime,
        position.entry_time.isoformat(), timestamp.isoformat(),
        position.entry_price, position.initial_stop_loss, position.tp1, position.tp2,
        reason, float(position.r_multiple), position.tp1_taken,
    )


def _manage_open_trade(position: _OpenTrade, bar: pd.Series,
                       timestamp: pd.Timestamp, cost: float = 0.0) -> BacktestTrade | None:
    """Advance one subsequent closed candle; return a record only when flat."""
    if timestamp <= position.entry_time:
        return None
    low, high = float(bar["low"]), float(bar["high"])
    direction = position.direction
    stop_hit = low <= position.stop_loss if direction == "LONG" else high >= position.stop_loss
    if stop_hit:
        exit_price = _adverse_price(position.stop_loss, direction, False, cost)
        if position.tp1_taken:
            remaining_r = (1.0 - position.tp1_close_pct) * (
                (exit_price - position.entry_price) if direction == "LONG"
                else (position.entry_price - exit_price)
            ) / position.initial_risk
            position.r_multiple += remaining_r
            reason = "BREAKEVEN_STOP" if position.be_offset_r == 0.0 and abs(position.stop_loss - position.entry_price) < 1e-12 else "STOP_LOSS"
        else:
            position.r_multiple = (
                (exit_price - position.entry_price) if direction == "LONG"
                else (position.entry_price - exit_price)
            ) / position.initial_risk
            reason = "STOP_LOSS"
        return _trade_record(position, timestamp, reason)

    tp1_hit = high >= position.tp1 if direction == "LONG" else low <= position.tp1
    tp2_hit = high >= position.tp2 if direction == "LONG" else low <= position.tp2
    if (not position.tp1_taken and tp1_hit and tp2_hit
            and abs(position.tp1 - position.tp2) < 1e-12):
        target_exit = _adverse_price(position.tp2, direction, False, cost)
        position.r_multiple = (
            (target_exit - position.entry_price) if direction == "LONG"
            else (position.entry_price - target_exit)
        ) / position.initial_risk
        return _trade_record(position, timestamp, "TAKE_PROFIT_2_SINGLE_TARGET")
    if not position.tp1_taken and tp1_hit:
        if position.tp1_close_pct <= 0.0:
            if tp2_hit:
                target_exit = _adverse_price(position.tp2, direction, False, cost)
                position.r_multiple = (
                    (target_exit - position.entry_price) if direction == "LONG"
                    else (position.entry_price - target_exit)
                ) / position.initial_risk
                return _trade_record(position, timestamp, "TAKE_PROFIT_2")
            return None
        tp1_exit = _adverse_price(position.tp1, direction, False, cost)
        position.r_multiple += position.tp1_close_pct * (
            (tp1_exit - position.entry_price) if direction == "LONG"
            else (position.entry_price - tp1_exit)
        ) / position.initial_risk
        position.tp1_taken = True
        if position.be_offset_r is not None:
            offset = position.be_offset_r * position.initial_risk
            position.stop_loss = position.entry_price + offset if direction == "LONG" else position.entry_price - offset
        # OHLC cannot reveal target ordering. If TP2 is also touched, treat the
        # remaining half as breakeven when that level was crossed in the candle.
        breakeven_hit = (
            low <= position.stop_loss if direction == "LONG"
            else high >= position.stop_loss
        )
        if tp2_hit and not breakeven_hit:
            tp2_exit = _adverse_price(position.tp2, direction, False, cost)
            position.r_multiple += (1.0 - position.tp1_close_pct) * (
                (tp2_exit - position.entry_price) if direction == "LONG"
                else (position.entry_price - tp2_exit)
            ) / position.initial_risk
            return _trade_record(position, timestamp, "TP1_TP2_SAME_BAR")
        if breakeven_hit:
            be_exit = _adverse_price(position.entry_price, direction, False, cost)
            position.r_multiple += (1.0 - position.tp1_close_pct) * (
                (be_exit - position.entry_price) if direction == "LONG"
                else (position.entry_price - be_exit)
            ) / position.initial_risk
            return _trade_record(position, timestamp, "TP1_THEN_BREAKEVEN_SAME_BAR")
        return None

    if position.tp1_taken and tp2_hit:
        tp2_exit = _adverse_price(position.tp2, direction, False, cost)
        position.r_multiple += (1.0 - position.tp1_close_pct) * (
            (tp2_exit - position.entry_price) if direction == "LONG"
            else (position.entry_price - tp2_exit)
        ) / position.initial_risk
        return _trade_record(position, timestamp, "TAKE_PROFIT_2")
    return None


def _utc_index(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError(f"{name} must have a DatetimeIndex")
    out = frame.copy().sort_index()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    out.index = idx
    out = out.loc[~out.index.duplicated(keep="last")]
    required = {"open", "high", "low", "close", "tick_volume"}
    missing = required.difference(out.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")
    values = out[list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"{name} contains non-finite OHLCV values")
    if (out["high"] < out["low"]).any():
        raise ValueError(f"{name} has high below low")
    if (out["tick_volume"] < 0).any():
        raise ValueError(f"{name} has negative tick volume")
    return out


def _resample_tf(m1: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample M1 bars into left-labelled OHLCV buckets."""
    timeframe = normalize_trigger_tf(timeframe)
    minutes = trigger_tf_minutes(timeframe)
    columns = ["open", "high", "low", "close", "tick_volume"]
    has_delta = "volume_delta" in m1.columns
    selected = columns + (["volume_delta"] if has_delta else [])
    if minutes == 1:
        out = m1[selected].copy()
        out.attrs.update(m1.attrs)
        return out
    aggregations = {
        "open": "first", "high": "max", "low": "min",
        "close": "last", "tick_volume": "sum",
    }
    if has_delta:
        aggregations["volume_delta"] = "sum"
    out = m1[selected].resample(
        f"{minutes}min", label="left", closed="left", origin="start_day"
    ).agg(aggregations).dropna()
    out.attrs.update(m1.attrs)
    return out


def _resample_m15(m1: pd.DataFrame) -> pd.DataFrame:
    return _resample_tf(m1, "M15")


def _atr14(m15_closed: pd.DataFrame) -> float | None:
    if len(m15_closed) < 15:
        return None
    previous_close = m15_closed["close"].shift(1)
    true_range = pd.concat([
        m15_closed["high"] - m15_closed["low"],
        (m15_closed["high"] - previous_close).abs(),
        (m15_closed["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    value = true_range.rolling(14, min_periods=14).mean().iloc[-1]
    if pd.isna(value) or not np.isfinite(float(value)) or float(value) <= 0:
        return None
    return float(value)


def _profile_levels(day_bars: pd.DataFrame, bins: int) -> dict[str, Any]:
    profile = calculate_volume_profile(day_bars, bins=bins)
    return {
        "pdPOC": profile.poc,
        "pdVAH": profile.vah,
        "pdVAL": profile.val,
        "pdLVN": profile.lvn_levels,
        "session": str(day_bars.index[0].date()),
    }


def _adverse_price(price: float, direction: str, entry: bool, cost: float) -> float:
    """Apply a symmetric adverse execution cost in price units."""
    is_buy = (direction == "LONG") if entry else (direction == "SHORT")
    return float(price + cost if is_buy else price - cost)


def _daily_group_stats(trades: list[BacktestTrade], field: str) -> dict[str, dict[str, float]]:
    groups: dict[str, list[float]] = {}
    for trade in trades:
        key = str(getattr(trade, field))
        groups.setdefault(key, []).append(trade.r_multiple)
    result = {}
    for key, values in sorted(groups.items()):
        wins = sum(v for v in values if v > 0)
        losses = -sum(v for v in values if v < 0)
        result[key] = {
            "trades": float(len(values)),
            "win_rate": sum(v > 0 for v in values) / len(values),
            "net_r": float(sum(values)),
            "expectancy_r": float(sum(values) / len(values)),
            "profit_factor": float(wins / losses) if losses else (math.inf if wins else 0.0),
        }
    return result


def _make_report(symbol: str, bars_processed: int, trades: list[BacktestTrade],
                 spread_points: float, point_size: float,
                 funnel_counts: dict[str, int] | None = None,
                 instrument_profile: str = "MOMENTUM_TREND",
                 trigger_tf: str = "M1") -> BacktestReport:
    values = [trade.r_multiple for trade in trades]
    trade_outcomes = {
        "full_sl_hits": sum(t.exit_reason == "STOP_LOSS" and not t.tp1_taken for t in trades),
        "tp1_then_be_hits": sum(t.tp1_taken and t.exit_reason in {"BREAKEVEN_STOP", "TP1_THEN_BREAKEVEN_SAME_BAR"} for t in trades),
        "full_tp2_hits": sum(t.exit_reason in {"TAKE_PROFIT_2", "TP1_TP2_SAME_BAR", "TAKE_PROFIT_2_SINGLE_TARGET"} for t in trades),
    }
    wins = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    equity_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0
    equity_pct = 100.0
    peak_pct = 100.0
    max_total_dd_pct = 0.0
    daily_start_pct: dict[str, float] = {}
    daily_min_pct: dict[str, float] = {}
    for trade in trades:
        day = pd.Timestamp(trade.exit_time).date().isoformat()
        daily_start_pct.setdefault(day, equity_pct)
        equity_r += trade.r_multiple
        equity_pct *= max(0.0, 1.0 + trade.r_multiple * 0.01)
        peak_r = max(peak_r, equity_r)
        max_dd_r = max(max_dd_r, peak_r - equity_r)
        peak_pct = max(peak_pct, equity_pct)
        max_total_dd_pct = max(max_total_dd_pct, peak_pct - equity_pct)
        daily_min_pct[day] = min(daily_min_pct.get(day, daily_start_pct[day]), equity_pct)
    max_daily_dd_pct = max(
        (daily_start_pct[day] - daily_min_pct[day] for day in daily_start_pct),
        default=0.0,
    )
    count = len(values)
    return BacktestReport(
        symbol=symbol,
        bars_processed=bars_processed,
        total_trades=count,
        win_rate=sum(value > 0 for value in values) / count if count else 0.0,
        profit_factor=float(wins / losses) if losses else (math.inf if wins else 0.0),
        net_r=float(sum(values)),
        expectancy_r=float(sum(values) / count) if count else 0.0,
        max_drawdown_r=float(max_dd_r),
        max_daily_drawdown_pct=float(max_daily_dd_pct),
        max_total_drawdown_pct=float(max_total_dd_pct),
        trades_by_regime=_daily_group_stats(trades, "regime"),
        trades_by_poi_type=_daily_group_stats(trades, "poi_type"),
        trade_outcomes=trade_outcomes,
        spread_points=float(spread_points),
        point_size=float(point_size),
        funnel_counts=dict(funnel_counts or {}),
        instrument_profile=instrument_profile,
        trigger_tf=trigger_tf,
    )


def run_backtest(
    m1_bars: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    macro_bias: int | str = 1,
    m15_bars: pd.DataFrame | None = None,
    profile_bins: int = 100,
    spread_points: float = 0.0,
    point_size: float = 0.01,
    allow_range: bool = False,
    allow_mean_reversion: bool | None = None,
    disable_trend_pullback: bool = False,
    trigger_tf: str | None = None,
    tp1_close_pct: float = 0.50,
    be_offset_r: float | None = 0.0,
) -> BacktestReport:
    """Simulate a single instrument without future-data leakage.

    spread_points is multiplied by point_size to produce the adverse price
    cost applied at entry and each exit. Only one position can be open at once.
    """
    instrument_profile = get_instrument_profile(symbol)
    trigger_tf = normalize_trigger_tf(trigger_tf or default_trigger_tf_for_symbol(symbol))
    effective_allow_mean_reversion = (
        instrument_profile.allow_mean_reversion
        if allow_mean_reversion is None else bool(allow_mean_reversion)
    )
    effective_allow_trend_pullback = (
        instrument_profile.allow_trend_pullback and not disable_trend_pullback
    )
    if not (isinstance(macro_bias, str) and macro_bias.strip().lower() == "auto") and macro_bias not in (-1, 0, 1):
        raise ValueError("macro_bias must be -1, 0, +1, or 'auto'")
    if not np.isfinite(tp1_close_pct) or not 0.0 <= tp1_close_pct <= 1.0:
        raise ValueError("tp1_close_pct must be between 0 and 1")
    if be_offset_r is not None and not np.isfinite(be_offset_r):
        raise ValueError("be_offset_r must be finite or None")
    if profile_bins < 2:
        raise ValueError("profile_bins must be >= 2")
    if not np.isfinite(spread_points) or spread_points < 0:
        raise ValueError("spread_points must be finite and non-negative")
    if not np.isfinite(point_size) or point_size <= 0:
        raise ValueError("point_size must be finite and greater than zero")
    m1 = _utc_index(m1_bars, "M1 bars")
    if len(m1) < 300:
        raise ValueError("At least 300 M1 bars are required for walk-forward simulation")
    trigger_bars = _resample_tf(m1, trigger_tf)
    if m15_bars is None:
        m15 = _resample_m15(m1)
    else:
        m15 = _utc_index(m15_bars, "M15 bars")
    m15 = filter_closed_bars(m15, "M15", now=m1.index[-1] + pd.Timedelta(minutes=1))
    if m1.index.to_series().diff().dropna().le(pd.Timedelta(0)).any():
        raise ValueError("M1 timestamps must be strictly increasing")

    m1 = m1.copy()
    m1["session"] = m1.index.strftime("%Y-%m-%d")
    session_names = list(dict.fromkeys(m1["session"].tolist()))
    if len(session_names) < 3:
        raise ValueError("At least three observed UTC sessions are required to avoid using the initial partial session as a profile")
    # The first observed session may be truncated by the history-download
    # boundary. Skip it as a profile source; begin trading on session 3 using
    # the fully observed session 2 profile.
    prior_profiles: dict[str, dict[str, Any]] = {}
    for position in range(2, len(session_names)):
        current_name = session_names[position]
        previous_name = session_names[position - 1]
        prior_profiles[current_name] = _profile_levels(
            m1.loc[m1["session"] == previous_name], profile_bins
        )

    vwap_engine = VWAPEngine()
    # Vectorized cumulative VWAP is causal: each row depends only on that
    # session's prefix, so precomputing it does not introduce future leakage.
    vwap_input = m1.copy()
    vwap_input["session"] = m1["session"]
    vwap_all = vwap_engine.calculate(vwap_input, session_key="session")
    cost = float(spread_points) * float(point_size)
    trades: list[BacktestTrade] = []
    position: _OpenTrade | None = None
    processed = 0
    funnel_counts = {
        "sessions_evaluated": len(prior_profiles),
        "bars_with_active_poi": 0,
        "bars_touched_poi": 0,
        "passed_zscore": 0,
        "passed_volume": 0,
        "passed_rejection": 0,
        "rejected_low_rr": 0,
        "rejected_session_hours": 0,
        "rejected_high_spread_to_sl": 0,
        "trades_opened": 0,
    }

    for i in range(len(m1)):
        timestamp = m1.index[i]
        bar = m1.iloc[i]
        decision_time = timestamp + pd.Timedelta(minutes=1)
        processed += 1

        # Manage an existing trade first, using only this fully closed candle.
        if position is not None:
            closed_trade = _manage_open_trade(position, bar, timestamp, cost)
            if closed_trade is not None:
                trades.append(closed_trade)
                position = None

        trigger_minutes = trigger_tf_minutes(trigger_tf)
        if trigger_minutes > 1 and decision_time.minute % trigger_minutes != 0:
            continue
        trigger_cutoff = decision_time - pd.Timedelta(minutes=trigger_minutes)
        trigger_idx = trigger_bars.index.searchsorted(trigger_cutoff, side="right")
        eligible_triggers = trigger_bars.iloc[:trigger_idx]
        if eligible_triggers.empty or eligible_triggers.index[-1] + pd.Timedelta(minutes=trigger_minutes) > decision_time:
            continue

        # Keep diagnostics running while a trade is open, but block new entries.
        can_enter = position is None
        current_session = str(bar["session"])
        profile = prior_profiles.get(current_session)
        if profile is None:
            continue

        # The active-session VWAP receives only M1 bars through this closed bar.
        latest_vwap = vwap_all.iloc[i]
        if pd.isna(latest_vwap["vwap"]) or float(latest_vwap["cumulative_volume"]) <= 0:
            continue

        # A M15 candle is eligible only after its entire 15-minute interval ends.
        eligible_cutoff = decision_time - pd.Timedelta(minutes=15)
        eligible_m15 = m15.iloc[:m15.index.searchsorted(eligible_cutoff, side="right")]
        atr = _atr14(eligible_m15)
        if atr is None or i < 29:
            continue
        price = float(bar["close"])
        regime_decision = generate_regime_pois(
            macro_bias, profile, latest_vwap, price, atr,
            allow_range=allow_range,
            allow_mean_reversion=effective_allow_mean_reversion,
            allow_trend_pullback=effective_allow_trend_pullback,
            poi_atr_multiplier=instrument_profile.poi_atr_multiplier,
            imbalance_vwap_poc_atr=instrument_profile.imbalance_vwap_poc_atr,
            mean_reversion_confluence_atr=instrument_profile.mean_reversion_confluence_atr,
        )
        if regime_decision.pois:
            funnel_counts["bars_with_active_poi"] += 1
        bar_touched = bar_z = bar_volume = bar_rejection = bar_low_rr = False
        decisions = []
        for poi in regime_decision.pois:
            decision = evaluate_trigger(
                eligible_triggers.iloc[max(0, len(eligible_triggers) - 30):], poi.direction,
                poi.poi_low, poi.poi_high, atr, poi.take_profits,
                poi_type=poi.poi_type, center_price=poi.center, cost_price=cost,
                sl_atr_buffer=instrument_profile.sl_atr_buffer,
                min_spread_to_sl_ratio=instrument_profile.min_spread_to_sl_ratio,
            )
            metrics = decision.metrics
            if metrics.get("poi_touched"):
                bar_touched = True
                if metrics.get("z_condition"):
                    bar_z = True
                    if metrics.get("volume_climax"):
                        bar_volume = True
                        if metrics.get("rejection"):
                            bar_rejection = True
            if decision.reason == "LOW_RR":
                bar_low_rr = True
            if decision.reason == "SESSION_HOURS":
                funnel_counts["rejected_session_hours"] += 1
            if decision.reason == "HIGH_SPREAD_TO_SL":
                funnel_counts["rejected_high_spread_to_sl"] += 1
            decisions.append((poi, decision))
        funnel_counts["bars_touched_poi"] += int(bar_touched)
        funnel_counts["passed_zscore"] += int(bar_touched and bar_z)
        funnel_counts["passed_volume"] += int(bar_touched and bar_z and bar_volume)
        funnel_counts["passed_rejection"] += int(bar_touched and bar_z and bar_volume and bar_rejection)
        funnel_counts["rejected_low_rr"] += int(bar_low_rr)
        if not can_enter or i >= len(m1) - 1:
            continue
        for poi, decision in decisions:
            if not decision.execute:
                continue
            entry = _adverse_price(float(bar["close"]), poi.direction, True, cost)
            stop = float(decision.stop_loss)
            risk = abs(entry - stop)
            tp1 = decision.take_profit_1
            tp2 = decision.take_profit_2 if decision.take_profit_2 is not None else tp1
            if tp1 is None or tp2 is None or risk <= 0:
                continue
            # Entry is at this candle's close; its high/low cannot close the
            # newly opened trade. Management starts on the next M1 candle.
            position = _OpenTrade(
                symbol=symbol, direction=poi.direction, poi_type=poi.poi_type,
                regime=regime_decision.regime.value, entry_time=timestamp,
                entry_price=entry, initial_stop_loss=stop, stop_loss=stop,
                tp1=float(tp1 if tp1_close_pct > 0.0 else tp2), tp2=float(tp2),
                initial_risk=risk, tp1_close_pct=tp1_close_pct, be_offset_r=be_offset_r,
            )
            funnel_counts["trades_opened"] += 1
            break

    # Mark any still-open position at the final closed close, conservatively
    # without assuming future targets are hit.
    if position is not None:
        final_time = m1.index[-1]
        final_close = _adverse_price(float(m1.iloc[-1]["close"]), position.direction, False, cost)
        remaining_fraction = (1.0 - position.tp1_close_pct) if position.tp1_taken else 1.0
        position.r_multiple += remaining_fraction * (
            (final_close - position.entry_price) if position.direction == "LONG"
            else (position.entry_price - final_close)
        ) / position.initial_risk
        trades.append(BacktestTrade(
            position.symbol, position.direction, position.poi_type, position.regime,
            position.entry_time.isoformat(), final_time.isoformat(),
            position.entry_price, position.initial_stop_loss, position.tp1, position.tp2,
            "END_OF_DATA", float(position.r_multiple), position.tp1_taken,
        ))

    return _make_report(
        symbol, processed, trades, spread_points, point_size, funnel_counts,
        instrument_profile=instrument_profile.name,
        trigger_tf=trigger_tf,
    )


def _synthetic_bars(count: int, end_time: pd.Timestamp | None = None) -> pd.DataFrame:
    if count < 300:
        raise ValueError("--bars must be at least 300")
    end = pd.Timestamp(end_time if end_time is not None else datetime.now(timezone.utc))
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    last_closed_open = end.floor("min") - pd.Timedelta(minutes=2)
    index = pd.date_range(end=last_closed_open, periods=count, freq="min", tz="UTC")
    x = np.arange(count, dtype=float)
    close = 2300.0 + 0.012 * x + 0.45 * np.sin(x / 8.0) + 0.18 * np.sin(x / 2.7)
    open_ = np.r_[close[0] - 0.03, close[:-1]]
    high = np.maximum(open_, close) + 0.08 + 0.02 * (1.0 + np.sin(x / 3.0))
    low = np.minimum(open_, close) - 0.08 - 0.02 * (1.0 + np.cos(x / 4.0))
    volume = 80.0 + 15.0 * (1.0 + np.sin(x / 5.0)) + (x.astype(int) % 11)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "tick_volume": volume,
    }, index=index)


def _default_point_size(symbol: str) -> float:
    name = symbol.upper()
    if name.startswith(("XAU", "XAG", "BTC", "SOL")):
        return 0.01
    if "JPY" in name:
        return 0.001
    if name.startswith(("SPX", "NAS", "US30")):
        return 0.1
    return 0.00001


def _print_report(report: BacktestReport) -> None:
    print("\n=== PRAGMA WALK-FORWARD BACKTEST ===")
    print(f"Symbol: {report.symbol} | Profile: {report.instrument_profile} | Trigger TF: {report.trigger_tf} | Bars: {report.bars_processed} | Trades: {report.total_trades}")
    print(f"Win rate: {report.win_rate:.2%} | Profit factor: {report.profit_factor:.3f}")
    print(f"Net R: {report.net_r:.3f} | Expectancy: {report.expectancy_r:.4f} R/trade")
    print(f"Max drawdown: {report.max_drawdown_r:.3f} R")
    print(f"Max daily DD (1% risk): {report.max_daily_drawdown_pct:.2f}%")
    print(f"Max total DD (1% risk): {report.max_total_drawdown_pct:.2f}%")
    print(f"Costs: {report.spread_points:g} points x {report.point_size:g} price units")
    print("\nFunnel diagnostics:")
    for name, count in report.funnel_counts.items():
        print(f"  {name}: {count}")
    for title, groups in (("By regime", report.trades_by_regime), ("By POI type", report.trades_by_poi_type)):
        print(f"\n{title}:")
        if not groups:
            print("  No closed trades")
        for name, values in groups.items():
            print(f"  {name}: n={int(values['trades'])}, win={values['win_rate']:.1%}, "
                  f"net={values['net_r']:.2f}R, exp={values['expectancy_r']:.3f}R, "
                  f"PF={values['profit_factor']:.3f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Causal Pragma walk-forward backtest")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--source", choices=("auto", "mt5", "binance"), default="auto")
    parser.add_argument("--no-cache", action="store_true", help="Disable Binance CSV cache")
    parser.add_argument("--scan-crypto", action="store_true", help="Backtest the major Binance USDT crypto basket")
    parser.add_argument("--btc-leader-filter", action="store_true", help="Apply BTC regime leadership filter in crypto scans")
    parser.add_argument("--bars", type=int, default=100000)
    parser.add_argument("--macro-bias", choices=("-1", "0", "1", "auto"), default=None, help="Macro direction override, or auto for internal crypto regime")
    parser.add_argument("--auto-direction", action="store_true", help="Infer long/short direction from the current causal crypto regime")
    parser.add_argument("--profile-bins", type=int, default=100)
    parser.add_argument("--spread-points", type=float, default=0.0,
                        help="Adverse spread/slippage cost in instrument points")
    parser.add_argument("--point-size", type=float, default=None,
                        help="Price units per point; inferred by symbol when omitted")
    parser.add_argument("--trigger-tf", choices=("M1", "M5", "M15", "M30", "H1", "M60"), default=None,
                        help="Trigger timeframe; defaults to the instrument profile")
    parser.add_argument("--tp1-close-pct", type=float, default=0.50,
                        help="Fraction closed at TP1; 0 disables partial exit")
    be_group = parser.add_mutually_exclusive_group()
    be_group.add_argument("--be-offset-r", type=float, default=0.0,
                          help="Stop offset from entry after TP1, measured in R")
    be_group.add_argument("--no-breakeven", action="store_true",
                          help="Keep the original stop after TP1")
    parser.add_argument("--allow-mean-reversion", action="store_true",
                        help="Override the instrument profile and enable BALANCE mean-reversion POIs")
    parser.add_argument("--disable-trend-pullback", action="store_true",
                        help="Override the instrument profile and disable trend-pullback POIs")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use deterministic synthetic M1 data instead of MT5")
    args = parser.parse_args(argv)
    if args.macro_bias is not None and args.macro_bias != "auto":
        args.macro_bias = int(args.macro_bias)
    if args.auto_direction:
        args.macro_bias = "auto"
    if args.scan_crypto:
        symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT")
        timeframes = (args.trigger_tf,) if args.trigger_tf else ("M5", "M15")
        results = []
        for crypto_symbol in symbols:
            try:
                client = BinanceDataClient(no_cache=args.no_cache)
                m1 = client.rates(crypto_symbol, "M1", max(100000, args.bars))
                if len(m1) < 100000:
                    raise ValueError(f"Insufficient M1 history: {len(m1)} bars; at least 100000 required")
                m15 = client.rates(crypto_symbol, "M15", max(300, len(m1) // 15 + 50))
                m1.attrs["source"] = "binance"
                m15.attrs["source"] = "binance"
                bias = args.macro_bias if args.macro_bias is not None else "auto"
                crypto_point = args.point_size if args.point_size is not None else 0.01
                effective_spread = max(args.spread_points, float(m1["close"].iloc[-1]) * 0.0004 / crypto_point)
                for tf in timeframes:
                    report = run_backtest(m1, symbol=crypto_symbol, macro_bias=bias, m15_bars=m15,
                        profile_bins=args.profile_bins, spread_points=effective_spread, point_size=crypto_point,
                        allow_mean_reversion=True if args.allow_mean_reversion else None,
                        disable_trend_pullback=args.disable_trend_pullback, trigger_tf=tf,
                        tp1_close_pct=args.tp1_close_pct, be_offset_r=None if args.no_breakeven else args.be_offset_r)
                    row = report.to_dict()
                    row["data_source"] = "binance_usdm_futures"
                    row["requested_m1_bars"] = max(100000, args.bars)
                    row["actual_m1_bars"] = len(m1)
                    row["cost_bps_per_side"] = round(effective_spread / float(m1["close"].iloc[-1]) * 10000, 4)
                    results.append(row)
            except Exception as exc:
                results.append({"symbol": crypto_symbol, "error": str(exc)})
        print(json.dumps(results, indent=2, allow_nan=True))
        return 0
    source = ("binance" if str(args.symbol).upper().endswith("USDT") else "mt5") if args.source == "auto" else args.source
    symbol = normalize_binance_symbol(args.symbol) if source == "binance" else args.symbol
    point_size = args.point_size if args.point_size is not None else (0.01 if source == "binance" else _default_point_size(symbol))
    if args.dry_run:
        m1 = _synthetic_bars(args.bars)
        m15 = _resample_m15(m1)
        bias = 1 if args.macro_bias is None else args.macro_bias
        allow_range = False
    else:
        if args.macro_bias is None:
            gate = MacroGate().get_bias(symbol)
            bias = int(gate.bias)
            allow_range = getattr(gate, "gate", None) == "NEUTRAL_RANGE"
        else:
            bias = args.macro_bias
            allow_range = False
        if source == "binance":
            client = BinanceDataClient(no_cache=args.no_cache)
            m1 = client.rates(symbol, "M1", args.bars)
            m15 = client.rates(symbol, "M15", max(300, args.bars // 15 + 50))
            m1.attrs["source"] = "binance"
            m15.attrs["source"] = "binance"
        else:
            with MT5DataClient() as client:
                m1 = client.rates(symbol, "M1", args.bars)
                m15 = client.rates(symbol, "M15", max(300, args.bars // 15 + 50))
        now = pd.Timestamp.now(tz="UTC")
        m1 = filter_closed_bars(m1, "M1", now=now)
        m15 = filter_closed_bars(m15, "M15", now=now)
    effective_spread = max(args.spread_points, float(m1["close"].iloc[-1]) * 0.0004 / point_size) if source == "binance" else args.spread_points
    report = run_backtest(
        m1, symbol=symbol, macro_bias=bias, m15_bars=m15,
        profile_bins=args.profile_bins, spread_points=effective_spread,
        point_size=point_size, allow_range=allow_range,
        allow_mean_reversion=True if args.allow_mean_reversion else None,
        disable_trend_pullback=args.disable_trend_pullback,
        trigger_tf=args.trigger_tf, tp1_close_pct=args.tp1_close_pct,
        be_offset_r=None if args.no_breakeven else args.be_offset_r,
    )
    _print_report(report)
    print("\nJSON:")
    print(json.dumps(report.to_dict(), indent=2, allow_nan=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
