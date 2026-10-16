"""End-to-end Pragma pipeline: closed bars -> AMT/VWAP -> POI -> trigger -> alert.

Examples:
    python -m pragma.run_pipeline --symbol XAUUSD --bars 3000
    python -m pragma.run_pipeline --dry-run
    python -m pragma.run_pipeline --macro-bias 1 --symbol XAUUSD
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from pragma.amt_engine import AMTEngine, calculate_session_profiles
from pragma.data.mt5_data import MT5DataClient, filter_closed_bars
from pragma.execution_notifier import ExecutionNotifier
from pragma.macro_gate import MacroGate, refresh_begonya_gate
from pragma.instrument_profiles import canonical_symbol, get_instrument_profile, normalize_trigger_tf, trigger_tf_minutes
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


def _closed_tf_from_m1(m1: pd.DataFrame, timeframe: str, now: datetime | pd.Timestamp) -> pd.DataFrame:
    timeframe = normalize_trigger_tf(timeframe)
    minutes = trigger_tf_minutes(timeframe)
    columns = ["open", "high", "low", "close", "tick_volume"]
    if minutes == 1:
        return filter_closed_bars(m1[columns], "M1", now=now)
    frame = m1[columns].resample(
        f"{minutes}min", label="left", closed="left", origin="start_day"
    ).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "tick_volume": "sum",
    }).dropna()
    return filter_closed_bars(frame, timeframe, now=now)


def _closed_m15_from_m1(m1: pd.DataFrame, now: datetime | pd.Timestamp) -> pd.DataFrame:
    return _closed_tf_from_m1(m1, "M15", now)


def run_pipeline(
    *,
    symbol: str = "XAUUSD",
    bars_count: int = 3000,
    profile_bins: int = 100,
    macro_bias: int | None = None,
    dry_run: bool = False,
    notifier: Any | None = None,
    now: datetime | pd.Timestamp | None = None,
    notify_pois: bool = True,
    allow_mean_reversion: bool | None = None,
    disable_trend_pullback: bool = False,
    cost_price: float = 0.0,
    trigger_tf: str | None = None,
) -> dict[str, Any]:
    """Run all analytical layers and return a JSON-serializable report."""
    clock = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if clock.tzinfo is None:
        clock = clock.tz_localize("UTC")
    else:
        clock = clock.tz_convert("UTC")

    instrument_profile = get_instrument_profile(symbol)
    trigger_tf = normalize_trigger_tf(trigger_tf or instrument_profile.default_trigger_tf)
    effective_allow_mean_reversion = (
        instrument_profile.allow_mean_reversion
        if allow_mean_reversion is None else bool(allow_mean_reversion)
    )
    effective_allow_trend_pullback = (
        instrument_profile.allow_trend_pullback and not disable_trend_pullback
    )

    macro_decision = None
    allow_range = False
    if macro_bias is None:
        macro_decision = MacroGate().get_bias(symbol)
        bias = int(macro_decision.bias)
        allow_range = getattr(macro_decision, "gate", None) == "NEUTRAL_RANGE"
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
    trigger_minutes = trigger_tf_minutes(trigger_tf)
    trigger_bars = _closed_tf_from_m1(m1, trigger_tf, clock)
    trigger_is_newly_closed = (
        trigger_minutes == 1 or
        (last_bar_time + pd.Timedelta(minutes=1)).minute % trigger_minutes == 0
    )
    trigger_window = trigger_bars.iloc[-20:] if trigger_is_newly_closed else trigger_bars.iloc[0:0]
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
        bias, profiles.previous, latest_vwap, current_price, atr_14,
        allow_range=allow_range,
        allow_mean_reversion=effective_allow_mean_reversion,
        allow_trend_pullback=effective_allow_trend_pullback,
        poi_atr_multiplier=instrument_profile.poi_atr_multiplier,
        imbalance_vwap_poc_atr=instrument_profile.imbalance_vwap_poc_atr,
        mean_reversion_confluence_atr=instrument_profile.mean_reversion_confluence_atr,
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
        trigger_bar = trigger_window.iloc[-1] if not trigger_window.empty else None
        intersects = (
            trigger_bar is not None
            and float(trigger_bar["low"]) <= poi.poi_high
            and float(trigger_bar["high"]) >= poi.poi_low
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
        if notify_pois and hasattr(notifier_instance, "notify_poi"):
            notifications.append(notifier_instance.notify_poi(
                symbol, poi, regime_decision.regime, last_bar_time
            ))
        if not intersects:
            continue
        decision = evaluate_trigger(
            trigger_window, poi.direction, poi.poi_low, poi.poi_high, atr_14,
            poi.take_profits, poi_type=poi.poi_type,
            center_price=poi.center, cost_price=cost_price,
            sl_atr_buffer=instrument_profile.sl_atr_buffer,
            min_spread_to_sl_ratio=instrument_profile.min_spread_to_sl_ratio,
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
        "instrument_profile": instrument_profile.name,
        "trigger_tf": trigger_tf,
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


def _default_point_size(symbol: str) -> float:
    name = symbol.upper()
    if name.startswith(("XAU", "XAG", "BTC", "SOL")):
        return 0.01
    if "JPY" in name:
        return 0.001
    if name.startswith(("SPX", "NAS", "US30")):
        return 0.1
    return 0.00001


def _latest_closed_m1_time(symbol: str) -> pd.Timestamp | None:
    """Cheap watch poll: return the timestamp of the latest fully closed M1 bar."""
    with MT5DataClient() as client:
        raw = client.rates(symbol, "M1", 3)
    closed = filter_closed_bars(raw, "M1", now=pd.Timestamp.now(tz="UTC"))
    return None if closed.empty else pd.Timestamp(closed.index[-1])


def _active_begonya_mt5_symbols() -> list[tuple[str, int]]:
    """Return broker symbols that have a fresh, non-neutral Begonya bias."""
    gate = MacroGate()
    active: dict[str, int] = {}
    for gate_symbol in gate.gate_symbols():
        decision = gate.get_bias(gate_symbol)
        bias = int(decision.bias)
        if bias:
            active[canonical_symbol(gate_symbol)] = bias
    if not active:
        return []
    with MT5DataClient() as client:
        broker_symbols = client.symbols()
    matched: dict[str, str] = {}
    for broker_symbol in broker_symbols:
        key = canonical_symbol(broker_symbol)
        if key in active and key not in matched:
            matched[key] = broker_symbol
    return sorted(
        [(broker_symbol, active[key]) for key, broker_symbol in matched.items()],
        key=lambda item: item[0].upper(),
    )


def _scan_begonya_once(args: argparse.Namespace, notifier: Any | None = None) -> list[dict[str, Any]]:
    """Run one sequential pass over all active Begonya symbols present in MT5."""
    symbols = _active_begonya_mt5_symbols()
    if not symbols:
        print("BEGONYA SCAN | no active non-neutral gate symbols found in MT5", flush=True)
        return []
    results: list[dict[str, Any]] = []
    for symbol, gate_bias in symbols:
        try:
            result = run_pipeline(
                symbol=symbol, bars_count=args.bars,
                profile_bins=args.profile_bins, macro_bias=None,
                dry_run=False, notifier=notifier, notify_pois=False,
                allow_mean_reversion=True if args.allow_mean_reversion else None,
                disable_trend_pullback=args.disable_trend_pullback,
                cost_price=args.spread_points * (
                    args.point_size if args.point_size is not None else _default_point_size(symbol)
                ),
                trigger_tf=args.trigger_tf,
            )
            executed = any(item.get("execute") is True for item in result.get("triggers", []))
            row = {
                "symbol": symbol, "bias": gate_bias,
                "profile": result["instrument_profile"],
                "trigger_tf": result["trigger_tf"],
                "regime": result["regime"],
                "pois": len(result.get("pois", [])),
                "status": "EXECUTE" if executed else "WAIT",
                "result": result,
            }
        except Exception as exc:
            profile = get_instrument_profile(symbol)
            row = {
                "symbol": symbol, "bias": gate_bias,
                "profile": profile.name,
                "trigger_tf": normalize_trigger_tf(args.trigger_tf or profile.default_trigger_tf),
                "regime": "-", "pois": 0, "status": f"ERROR: {exc}",
                "result": None,
            }
        results.append(row)
    print("\\nBEGONYA ACTIVE SYMBOL SCAN")
    print(f"{'SYMBOL':<14} {'BIAS':<6} {'PROFILE':<20} {'TF':<5} {'REGIME':<18} {'POI':>4}  STATUS")
    for row in results:
        bias_label = "LONG" if row["bias"] > 0 else "SHORT"
        print(
            f"{row['symbol']:<14} {bias_label:<6} {row['profile']:<20} "
            f"{row['trigger_tf']:<5} {row['regime']:<18} {row['pois']:>4}  {row['status']}",
            flush=True,
        )
    return results


def _watch(args: argparse.Namespace) -> int:
    if args.dry_run:
        raise ValueError("--watch requires a live MT5 connection; --dry-run is not supported")
    if args.interval_sec < 1:
        raise ValueError("--interval-sec must be >= 1")
    notifier = ExecutionNotifier()
    last_processed: dict[str, str] = {}
    if args.scan_begonya:
        print(f"PRAGMA WATCH started | mode=Begonya multi-symbol scan | poll={args.interval_sec}s")
    else:
        profile = get_instrument_profile(args.symbol)
        print(
            f"PRAGMA WATCH started | symbol={args.symbol} | profile={profile.name} | "
            f"trigger_tf={normalize_trigger_tf(args.trigger_tf or profile.default_trigger_tf)} | "
            f"poll={args.interval_sec}s"
        )
    try:
        while True:
            try:
                if args.scan_begonya:
                    active_symbols = _active_begonya_mt5_symbols()
                    if not active_symbols:
                        print("BEGONYA SCAN | no active non-neutral gate symbols found in MT5", flush=True)
                    for symbol, bias in active_symbols:
                        latest_time = _latest_closed_m1_time(symbol)
                        if latest_time is None or latest_time.isoformat() == last_processed.get(symbol):
                            continue
                        result = run_pipeline(
                            symbol=symbol, bars_count=args.bars,
                            profile_bins=args.profile_bins, macro_bias=None,
                            dry_run=False, notifier=notifier, notify_pois=False,
                            allow_mean_reversion=True if args.allow_mean_reversion else None,
                            disable_trend_pullback=args.disable_trend_pullback,
                            cost_price=args.spread_points * (
                                args.point_size if args.point_size is not None else _default_point_size(symbol)
                            ),
                            trigger_tf=args.trigger_tf,
                        )
                        stamp = result["bars"]["last_closed_m1_time"]
                        last_processed[symbol] = stamp
                        executed = any(item.get("execute") is True for item in result.get("triggers", []))
                        print(
                            f"[{stamp}] {symbol} bias={'LONG' if bias > 0 else 'SHORT'} "
                            f"| {result['instrument_profile']} | TF={result['trigger_tf']} "
                            f"| {result['regime']} | POI={len(result.get('pois', []))} "
                            f"| {'EXECUTE' if executed else 'WAIT'}",
                            flush=True,
                        )
                else:
                    latest_time = _latest_closed_m1_time(args.symbol)
                    if latest_time is not None and latest_time.isoformat() != last_processed.get(args.symbol):
                        result = run_pipeline(
                            symbol=args.symbol, bars_count=args.bars,
                            profile_bins=args.profile_bins, macro_bias=args.macro_bias,
                            dry_run=False, notifier=notifier, notify_pois=False,
                            allow_mean_reversion=True if args.allow_mean_reversion else None,
                            disable_trend_pullback=args.disable_trend_pullback,
                            cost_price=args.spread_points * (
                                args.point_size if args.point_size is not None else _default_point_size(args.symbol)
                            ),
                            trigger_tf=args.trigger_tf,
                        )
                        stamp = result["bars"]["last_closed_m1_time"]
                        last_processed[args.symbol] = stamp
                        executed = any(item.get("execute") is True for item in result.get("triggers", []))
                        print(
                            f"[{stamp}] {args.symbol} | {result['instrument_profile']} "
                            f"| TF={result['trigger_tf']} | {result['regime']} "
                            f"| Active POI: {len(result.get('pois', []))} "
                            f"| {'EXECUTE' if executed else 'WAIT'}",
                            flush=True,
                        )
            except Exception as exc:
                print(f"[{pd.Timestamp.now(tz='UTC').isoformat()}] WATCH_ERROR | {exc}", flush=True)
            time.sleep(args.interval_sec)
    except KeyboardInterrupt:
        print("PRAGMA WATCH stopped by Ctrl+C", flush=True)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pragma end-to-end quantitative pipeline")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--bars", type=int, default=3000)
    parser.add_argument("--profile-bins", type=int, default=100)
    parser.add_argument("--macro-bias", type=int, choices=(-1, 0, 1), default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Run the complete pipeline using deterministic synthetic M1 data")
    parser.add_argument("--watch", action="store_true",
                        help="Continuously process only newly closed M1 bars (live MT5)")
    parser.add_argument("--scan-begonya", action="store_true",
                        help="Scan all active non-neutral Begonya symbols available in MT5")
    parser.add_argument("--interval-sec", type=int, default=15,
                        help="Watch polling interval in seconds (default: 15)")
    parser.add_argument("--allow-mean-reversion", action="store_true",
                        help="Override the instrument profile and enable BALANCE mean-reversion POIs")
    parser.add_argument("--disable-trend-pullback", action="store_true",
                        help="Override the instrument profile and disable trend-pullback POIs")
    parser.add_argument("--spread-points", type=float, default=0.0,
                        help="Spread/slippage cost in instrument points")
    parser.add_argument("--point-size", type=float, default=None,
                        help="Price units per point; inferred by symbol when omitted")
    parser.add_argument("--trigger-tf", choices=("M1", "M5", "M15", "M30", "H1", "M60"), default=None,
                        help="Closed-candle trigger timeframe; defaults to the instrument profile")
    parser.add_argument("--refresh-macro", action="store_true",
                        help="Refresh Begonya macro gate first if missing or stale")
    args = parser.parse_args(argv)
    if args.refresh_macro:
        refresh_result = refresh_begonya_gate()
        print("MACRO_REFRESH: " + json.dumps(refresh_result, default=str), flush=True)
    if args.watch:
        return _watch(args)
    if args.scan_begonya:
        if args.dry_run:
            raise ValueError("--scan-begonya requires a live MT5 connection; --dry-run is not supported")
        _scan_begonya_once(args, notifier=ExecutionNotifier())
        return 0
    point_size = args.point_size if args.point_size is not None else _default_point_size(args.symbol)
    cost_price = args.spread_points * point_size
    result = run_pipeline(
        symbol=args.symbol, bars_count=args.bars, profile_bins=args.profile_bins,
        macro_bias=args.macro_bias, dry_run=args.dry_run,
        allow_mean_reversion=True if args.allow_mean_reversion else None,
        disable_trend_pullback=args.disable_trend_pullback, cost_price=cost_price,
        trigger_tf=args.trigger_tf,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
