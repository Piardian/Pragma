"""End-to-end Pragma pipeline: closed bars -> AMT/VWAP -> POI -> trigger -> alert.

Examples:
    python -m pragma.run_pipeline --symbol XAUUSD --bars 3000
    python -m pragma.run_pipeline --dry-run
    python -m pragma.run_pipeline --macro-bias 1 --symbol XAUUSD
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from pragma.amt_engine import AMTEngine, calculate_session_profiles
from pragma.data.mt5_data import MT5DataClient, filter_closed_bars
from pragma.execution_notifier import ExecutionNotifier
from pragma.macro_gate import MacroGate
from pragma.regime_poi_engine import generate_regime_pois
from pragma.trigger_engine import evaluate_trigger
from pragma.vwap_engine import VWAPEngine


def _session_labels(bars: pd.DataFrame) -> pd.Series:
    return pd.Series(bars.index.strftime("%Y-%m-%d"), index=bars.index, name="session")


def _synthetic_bars(now: datetime | pd.Timestamp | None = None,
                    bars_per_session: int = 360) -> pd.DataFrame:
    """Create repeatable, historical M1 OHLCV data for offline smoke tests."""
    clock = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if clock.tzinfo is None:
        clock = clock.tz_localize("UTC")
    else:
        clock = clock.tz_convert("UTC")
    minute = clock.floor("min")
    active_end = minute - pd.Timedelta(minutes=2)
    active_index = pd.date_range(end=active_end, periods=bars_per_session, freq="min")
    previous_index = active_index - pd.Timedelta(days=1)
    indices = previous_index.append(active_index)
    n = len(indices)
    x = np.arange(n, dtype=float)
    # Deterministic bounded walk with oscillation; no future data is used.
    close = 2300.0 + 0.012 * x + 0.45 * np.sin(x / 8.0) + 0.18 * np.sin(x / 2.7)
    open_ = np.r_[close[0] - 0.03, close[:-1]]
    high = np.maximum(open_, close) + 0.08 + 0.02 * (1.0 + np.sin(x / 3.0))
    low = np.minimum(open_, close) - 0.08 - 0.02 * (1.0 + np.cos(x / 4.0))
    volume = 80.0 + 15.0 * (1.0 + np.sin(x / 5.0)) + (x.astype(int) % 11)
    frame = pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "tick_volume": volume,
    }, index=indices)
    frame.index.name = "time"
    frame["session"] = ["previous"] * bars_per_session + ["active"] * bars_per_session
    return frame.sort_index()


def _atr_from_m15(bars: pd.DataFrame, period: int = 14) -> float:
    if len(bars) < period + 1:
        raise ValueError(f"At least {period + 1} closed M15 bars are required for ATR({period})")
    previous_close = bars["close"].shift(1)
    true_range = pd.concat([
        bars["high"] - bars["low"],
        (bars["high"] - previous_close).abs(),
        (bars["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    atr = true_range.rolling(period, min_periods=period).mean().iloc[-1]
    if pd.isna(atr) or not np.isfinite(float(atr)) or float(atr) <= 0:
        raise ValueError("Could not calculate a valid M15 ATR(14)")
    return float(atr)


def _closed_m15_from_m1(m1: pd.DataFrame, now: datetime | pd.Timestamp) -> pd.DataFrame:
    # Resample only already-closed M1 candles. Each M15 bucket is left-labelled.
    m15 = m1[["open", "high", "low", "close", "tick_volume"]].resample(
        "15min", label="left", closed="left"
    ).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "tick_volume": "sum",
    }).dropna()
    return filter_closed_bars(m15, "M15", now=now)


def run_pipeline(
    *,
    symbol: str = "XAUUSD",
    bars_count: int = 3000,
    profile_bins: int = 100,
    macro_bias: int | None = None,
    dry_run: bool = False,
    notifier: Any | None = None,
    now: datetime | pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Run all analytical layers and return a JSON-serializable report."""
    clock = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if clock.tzinfo is None:
        clock = clock.tz_localize("UTC")
    else:
        clock = clock.tz_convert("UTC")

    if macro_bias is None:
        macro_decision = MacroGate().get_bias(symbol)
        bias = int(macro_decision.bias)
        macro_source = macro_decision.source
        macro_reason = macro_decision.reason
    else:
        if macro_bias not in (-1, 0, 1):
            raise ValueError("--macro-bias must be -1, 0, or 1")
        bias = int(macro_bias)
        macro_source = "cli"
        macro_reason = "Explicit command-line override"

    if dry_run:
        raw_m1 = _synthetic_bars(clock)
        m1 = filter_closed_bars(raw_m1, "M1", now=clock)
        session_key = "session"
        m15 = _closed_m15_from_m1(m1, clock)
    else:
        with MT5DataClient() as client:
            raw_m1 = client.rates(symbol, "M1", bars_count)
            raw_m15 = client.rates(symbol, "M15", max(200, bars_count // 15 + 50))
        m1 = filter_closed_bars(raw_m1, "M1", now=clock)
        m15 = filter_closed_bars(raw_m15, "M15", now=clock)
        if m1.empty:
            raise ValueError("No fully closed M1 bars available")
        m1 = m1.copy()
        m1["session"] = _session_labels(m1)
        session_key = "session"

    if len(m1) < 30:
        raise ValueError("At least 30 fully closed M1 bars are required")
    if m1[session_key].nunique() < 2:
        raise ValueError("At least two M1 sessions are required for previous-session AMT")

    last_bar_time = m1.index[-1]
    last_bar = m1.iloc[-1]
    current_price = float(last_bar["close"])
    profiles = calculate_session_profiles(
        m1, session_key=session_key, as_of=last_bar_time, bins=profile_bins
    )
    active_session = profiles.developing.session
    active_m1 = m1.loc[m1[session_key] == active_session].copy()
    vwap_frame = VWAPEngine().calculate(active_m1, session_key=session_key)
    latest_vwap = vwap_frame.iloc[-1]
    atr_14 = _atr_from_m15(m15)
    regime_decision = generate_regime_pois(
        bias, profiles.previous, latest_vwap, current_price, atr_14
    )

    notifier_instance = notifier
    if notifier_instance is None:
        notifier_instance = ExecutionNotifier(
            bot_token="" if dry_run else None,
            chat_id="" if dry_run else None,
        )

    poi_reports: list[dict[str, Any]] = []
    trigger_reports: list[dict[str, Any]] = []
    notifications: list[dict[str, Any]] = []
    for poi in regime_decision.pois:
        intersects = (
            float(last_bar["low"]) <= poi.poi_high
            and float(last_bar["high"]) >= poi.poi_low
        )
        poi_reports.append({
            "direction": poi.direction,
            "poi_type": poi.poi_type,
            "center": poi.center,
            "poi_low": poi.poi_low,
            "poi_high": poi.poi_high,
            "take_profits": list(poi.take_profits),
            "intersects_last_closed_m1": bool(intersects),
        })
        if not intersects:
            continue
        decision = evaluate_trigger(
            m1, poi.direction, poi.poi_low, poi.poi_high, atr_14,
            poi.take_profits,
        )
        trigger_reports.append({
            "execute": decision.execute,
            "direction": decision.direction,
            "entry_price": decision.entry_price,
            "stop_loss": decision.stop_loss,
            "take_profit_1": decision.take_profit_1,
            "take_profit_2": decision.take_profit_2,
            "take_profit": decision.take_profit,
            "rr_ratio": decision.rr_ratio,
            "reason": decision.reason,
            "metrics": decision.metrics,
            "poi_type": poi.poi_type,
        })
        if decision.execute:
            notifications.append(notifier_instance.notify(
                symbol, poi, decision, regime_decision.regime, last_bar_time
            ))

    return {
        "symbol": symbol,
        "dry_run": dry_run,
        "macro": {
            "bias": bias,
            "source": macro_source,
            "reason": macro_reason,
            "gate": getattr(macro_decision, "gate", None) if macro_bias is None else None,
            "timestamp": getattr(macro_decision, "timestamp", None) if macro_bias is None else None,
        },
        "bars": {
            "m1_closed_count": int(len(m1)),
            "m15_closed_count": int(len(m15)),
            "last_closed_m1_time": last_bar_time.isoformat(),
            "last_closed_m1_close": current_price,
            "forming_m1_excluded": True,
        },
        "atr_14_m15": atr_14,
        "previous_session": {
            "session": str(profiles.previous.session),
            "pdPOC": profiles.previous.pdPOC,
            "pdVAH": profiles.previous.pdVAH,
            "pdVAL": profiles.previous.pdVAL,
            "pdLVN": list(profiles.previous.pdLVN),
        },
        "developing_session": {
            "session": str(profiles.developing.session),
            "poc": profiles.developing.profile.poc,
            "vah": profiles.developing.profile.vah,
            "val": profiles.developing.profile.val,
        },
        "vwap": {
            "vwap": float(latest_vwap["vwap"]),
            "sigma": float(latest_vwap["vwap_sigma"]),
            "lower_1p5sigma": float(latest_vwap["vwap_lower_1p5sigma"]),
            "upper_1p5sigma": float(latest_vwap["vwap_upper_1p5sigma"]),
        },
        "regime": regime_decision.regime.value,
        "regime_reason": regime_decision.reason,
        "pois": poi_reports,
        "triggers": trigger_reports,
        "notifications": notifications,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pragma end-to-end quantitative pipeline")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--bars", type=int, default=3000)
    parser.add_argument("--profile-bins", type=int, default=100)
    parser.add_argument("--macro-bias", type=int, choices=(-1, 0, 1), default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the complete pipeline using deterministic synthetic M1 data")
    args = parser.parse_args(argv)
    result = run_pipeline(
        symbol=args.symbol, bars_count=args.bars, profile_bins=args.profile_bins,
        macro_bias=args.macro_bias, dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
