"""Frozen, time-separated broker entry diagnosis. No rule search or live writes."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import pragma.backtest_engine as engine
from pragma.data.clock_alignment import observed_offset_seconds
from pragma.measurement import ExecutionCosts
from pragma.research_measurement import weekly_bootstrap
from scripts.run_broker_measurement_research import research_client, sha, save

CAPTURE_START = pd.Timestamp("2026-07-20T00:00Z")
SCORE_START = pd.Timestamp("2026-07-27T00:00Z")
BLOCK_SPLIT = pd.Timestamp("2026-08-24T00:00Z")
END = pd.Timestamp("2026-09-23T00:00Z")


def strict_rates(raw, start, end):
    if raw is None or not len(raw):
        raise ValueError("No broker rates")
    frame = pd.DataFrame(raw)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("time"), unit="s", utc=True))
    frame.index.name = "time"
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("Duplicate or unordered broker rates")
    if frame.index[0] < start or frame.index[-1] > end:
        raise ValueError("Broker response outside requested bounds")
    values = frame[["open", "high", "low", "close", "tick_volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (frame.tick_volume < 0).any() or not (frame.tick_volume > 0).any():
        raise ValueError("Invalid or unavailable observed tick volume/OHLC")
    if ((frame.low > frame[["open", "close"]].min(axis=1)) |
        (frame.high < frame[["open", "close"]].max(axis=1)) | (frame.low <= 0)).any():
        raise ValueError("Invalid OHLC geometry")
    return frame


def contiguous_returns(close):
    return close.pct_change(fill_method=None).where(close.index.to_series().diff() == pd.Timedelta(minutes=5))


def audit_clock(broker_close, reference_close, weeks):
    """Clock-only calibration, never a trading-return optimization."""
    br, ref = contiguous_returns(broker_close), contiguous_returns(reference_close)
    audit = []
    for start in weeks:
        raw_week = br.loc[(br.index >= start) & (br.index < start + pd.Timedelta(days=7))]
        scores = []
        for hours in range(5):
            shifted = raw_week.copy()
            shifted.index -= pd.Timedelta(hours=hours)
            pair = pd.concat([shifted.rename("broker"), ref.rename("reference")], axis=1, join="inner").dropna()
            corr = float(pair.broker.corr(pair.reference)) if len(pair) >= 500 else None
            scores.append({"offset_seconds": hours * 3600, "n": len(pair),
                           "correlation": corr if corr is not None and np.isfinite(corr) else None})
        ranked = sorted([s for s in scores if s["correlation"] is not None], key=lambda s: s["correlation"], reverse=True)
        valid = len(ranked) >= 2 and ranked[0]["correlation"] >= .8 and ranked[0]["correlation"] - ranked[1]["correlation"] >= .25
        audit.append({"reported_week_start": start.isoformat(), "passed": bool(valid), "scores": scores,
                      "selected_offset_seconds": ranked[0]["offset_seconds"] if valid else None})
    offsets = {r["selected_offset_seconds"] for r in audit if r["passed"]}
    passed = len(audit) > 0 and all(r["passed"] for r in audit) and len(offsets) == 1
    return {"passed": passed, "weeks": audit, "constant_offset_seconds": offsets.pop() if passed else None,
            "method": "Contiguous M5 BTCUSD vs independent Binance BTCUSDT returns, offset candidates 0..4h; >=500 pairs/week, corr>=0.8, margin>=0.25",
            "limitation": "Common broker server clock inferred from BTC, not independent execution/cost proof for each FX symbol"}


def gross_window(bars, start, direction, minutes):
    expected = pd.date_range(start, periods=minutes + 1, freq="min")
    window = bars.loc[(bars.index >= expected[0]) & (bars.index <= expected[-1])]
    if not window.index.equals(expected):
        return None
    sign = 1 if direction == "LONG" else -1
    return sign * (float(window.open.iloc[-1]) - float(window.open.iloc[0])) / float(window.open.iloc[0]) * 10000


def summarize_horizons(rows):
    result = {}
    for horizon in (5, 15, 30):
        subset = [r for r in rows if r["horizon_minutes"] == horizon]
        good = [r for r in subset if r["gross_directional_bid_bps"] is not None]
        paired = [r for r in good if r["reference_gross_bid_bps"] is not None]
        make = lambda items, field: [{"entry_time": r["entry_time"], "r_multiple": r[field]} for r in items]
        result[str(horizon)] = {"candidates": len(subset), "complete": len(good), "missing": len(subset) - len(good),
                                "gross_directional_bid_bps": weekly_bootstrap(make(good, "gross_directional_bid_bps")),
                                "same_clock_prior_week_excess_bps": weekly_bootstrap(make(paired, "reference_excess_bps")),
                                "fully_net_bps": None}
    return result


def worker(symbol, directory):
    out = Path(directory)
    protocol = json.loads((out / "protocol_frozen.json").read_text(encoding="utf-8"))
    meta = protocol["captured"][symbol]
    path = out / meta["path"]
    if sha(path) != meta["sha256"]:
        raise ValueError("Frozen worker input changed")
    bid = pd.read_csv(path, index_col="time", parse_dates=True)
    bid.index = pd.DatetimeIndex(pd.to_datetime(bid.index, utc=True))
    baseline = json.loads((out / protocol["baseline_reports"][symbol]).read_text(encoding="utf-8"))
    costs = ExecutionCosts(**baseline["measurement"]["costs"])
    mid = bid.copy()
    mid[["open", "high", "low", "close"]] += meta["half_spread_assumed_for_unchanged_gate"]
    mid.attrs.update(source="mt5", volume_semantics="BROKER_TICK_COUNT")
    unique = {}
    original = engine.decide_trigger
    def decide(symbol, bars, poi, *args, **kwargs):
        d = original(symbol, bars, poi, *args, **kwargs)
        decision = bars.index[-1] + pd.Timedelta(minutes=5)
        return replace(d, execute=False, reason="RESEARCH_WARMUP_ONLY") if decision < SCORE_START else d
    def observe(stamp, poi, d, atr, veto):
        decision = stamp + pd.Timedelta(minutes=1)
        if d.execute and not veto and SCORE_START <= decision < END:
            key = (stamp.isoformat(), poi.direction, poi.poi_type)
            unique.setdefault(key, {"symbol": symbol, "signal_bar_time": stamp.isoformat(), "entry_time": decision.isoformat(),
                                    "direction": poi.direction, "poi_type": poi.poi_type,
                                    "stop": d.stop_loss, "tp1": d.take_profit_1, "tp2": d.take_profit_2 or d.take_profit_1})
    with patch.object(engine, "decide_trigger", decide):
        report = engine.run_backtest(mid, symbol=symbol, macro_bias="auto", allow_range=True, trigger_tf="M5", costs=costs,
                                     candidate_observer=observe).to_dict()
    save(out / f"{symbol}_scenario_replay.json", report)
    outcomes = []
    for candidate in unique.values():
        start = pd.Timestamp(candidate["entry_time"])
        invalid = None
        if start not in mid.index:
            invalid = "MISSING_NEXT_MINUTE_OPEN"
        else:
            fill = costs.adverse(float(mid.loc[start, "open"]), candidate["direction"], True)
            valid = (candidate["stop"] < fill < candidate["tp1"] <= candidate["tp2"]) if candidate["direction"] == "LONG" else (candidate["stop"] > fill > candidate["tp1"] >= candidate["tp2"])
            if not valid:
                invalid = "INVALID_NEXT_OPEN_GEOMETRY"
        for horizon in (5, 15, 30):
            gross = gross_window(bid, start, candidate["direction"], horizon) if invalid is None else None
            reference = gross_window(bid, start - pd.Timedelta(days=7), candidate["direction"], horizon) if invalid is None else None
            outcomes.append(dict(candidate, horizon_minutes=horizon, block="A" if start < BLOCK_SPLIT else "B",
                                 gross_directional_bid_bps=gross, reference_gross_bid_bps=reference,
                                 reference_excess_bps=gross - reference if gross is not None and reference is not None else None,
                                 missing_reason=invalid or ("MISSING_CONTIGUOUS_HORIZON" if gross is None else None), fully_net_bps=None))
    save(out / f"{symbol}_entry_outcomes.json", outcomes)
    trades = [t for t in report["trades"] if SCORE_START <= pd.Timestamp(t["fill_time"]) < END]
    closed = [t for t in trades if t["exit_reason"] != "END_OF_DATA"]
    return {"symbol": symbol, "candidate_n": len(unique), "all": summarize_horizons(outcomes),
            "blocks": {b: summarize_horizons([r for r in outcomes if r["block"] == b]) for b in ("A", "B")},
            "scenario_closed_n": len(closed), "scenario_censored_n": len(trades) - len(closed),
            "scenario_closed_r": sum(t["r_multiple"] for t in closed) if closed else None,
            "scenario_closed_expectancy": weekly_bootstrap(closed), "edge_proven": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--terminal-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=3, choices=(1, 2, 3))
    args = parser.parse_args()
    base, out = Path(args.baseline).resolve(), Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    try:
        source = json.loads((base / "protocol_frozen.json").read_text(encoding="utf-8"))
        source_done = json.loads((base / "completion.json").read_text(encoding="utf-8"))
        if source_done["status"] != "COMPLETE" or sha(base / "protocol_frozen.json") != source_done["protocol_sha256"]:
            raise ValueError("Invalid original baseline")
        core = {"pragma/backtest_engine.py", "pragma/measurement.py", "pragma/trigger_engine.py",
                "pragma/regime_poi_engine.py", "pragma/instrument_profiles.py", "pragma/amt_engine.py",
                "pragma/vwap_engine.py", "config/settings.py"}
        core_rows = [r for r in source["inputs"] if Path(r["path"]).as_posix() in core]
        if len(core_rows) != len(core) or any(sha(ROOT / r["path"]) != r["sha256"] for r in core_rows):
            raise ValueError("Original baseline decision/core source changed")
        reference = ROOT / "data_cache/binance_BTCUSDT_M1.csv"
        paths = sorted(list((ROOT / "pragma").rglob("*.py")) + list((ROOT / "config").glob("*.py")))
        paths += [Path(__file__).resolve(), ROOT / "scripts/run_broker_measurement_research.py", base / "protocol_frozen.json", reference]
        paths += [base / f"{s}_baseline.json" for s in source["symbols"]]
        inputs = []
        for path in paths:
            relative = path.relative_to(ROOT)
            target = out / "frozen" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            inputs.append({"path": str(relative), "sha256": sha(target)})
        plan = {"created_at": datetime.now(timezone.utc).isoformat(), "inputs": inputs,
                "capture_start": CAPTURE_START.isoformat(), "score_start": SCORE_START.isoformat(), "score_end_exclusive": END.isoformat(),
                "block_A_end_exclusive": BLOCK_SPLIT.isoformat(), "symbols": source["symbols"],
                "classification": "TIME_SEPARATED_ADDITIONAL_HISTORICAL_DIAGNOSIS_NOT_GENUINE_FORWARD_OR_OOS_CLAIM",
                "hypothesis": "Does unchanged original entry logic have gross directional movement and excess over previous-week same-clock direction? No filters or exit variants selected",
                "primary_horizon_minutes": 15, "secondary_horizons_minutes": [5, 30],
                "primary_price_basis": "Broker BID next contiguous minute OPEN to minute+15 OPEN, all intervening minutes required; directional gross proxy, not executable ask/bid or net return",
                "reference": "Same broker, same clock/direction one week earlier, only complete windows; missing retained",
                "unchanged_gates": "Original archived-spread + 1bps commission +0.5bps slippage scenario retained for entry admission; not a zero-cost strategy or calibrated-cost study",
                "clock_gate": "Every required reported week: BTCUSD/Binance M5 return corr>=0.8, margin>=0.25 vs other 0..4h offsets, >=500 pairs; one constant offset required",
                "coverage_gate": "Every symbol >=40000 scored M1 bars, each fixed block >=15000; no time-window retuning if missing",
                "no_search": "No parameter, symbol, block or horizon selection by outcome; no pooling symbol R as portfolio performance; no live promotion from this diagnostic",
                "uncertainty": "Calendar-week clusters, exploratory uncorrected intervals only, overlap and multiple testing remain; report both fixed blocks",
                "original_core_hashes_verified": len(core_rows),
                "edge_proven": False, "live_execution": False}
        save(out / "plan_frozen.json", plan)
        market = out / "frozen/market"
        market.mkdir(parents=True)
        captured = {}
        with research_client(args.terminal_path) as client:
            mt5 = client.mt5
            current_offset = observed_offset_seconds(mt5)
            terminal = mt5.terminal_info()
            btc_start, btc_end = pd.Timestamp("2026-07-13T00:00Z"), pd.Timestamp("2026-09-28T00:00Z")
            btc = strict_rates(mt5.copy_rates_range("BTCUSD", mt5.TIMEFRAME_M5, btc_start.to_pydatetime(), btc_end.to_pydatetime()), btc_start, btc_end)
            btc.to_csv(market / "BTCUSD_reported_M5.csv", index_label="time")
            raw_start, raw_end = CAPTURE_START - pd.Timedelta(hours=6), END + pd.Timedelta(hours=6)
            for symbol in source["symbols"]:
                if observed_offset_seconds(mt5) != current_offset:
                    raise ValueError("Current broker clock changed")
                frame = strict_rates(mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, raw_start.to_pydatetime(), raw_end.to_pydatetime()), raw_start, raw_end)
                path = market / f"{symbol}_reported_M1.csv"
                frame.to_csv(path, index_label="time")
                captured[symbol] = {"raw_path": str(path.relative_to(out)), "raw_sha256": sha(path)}
                print(f"CAPTURED {symbol}: {len(frame)} real M1 bars", flush=True)
            save(out / "capture_metadata.json", {"maxbars": terminal.maxbars, "current_offset_seconds": current_offset,
                                                 "clock_raw_sha256": sha(market / "BTCUSD_reported_M5.csv"), "captured": captured})
        ref = pd.read_csv(out / "frozen" / reference.relative_to(ROOT), usecols=["time", "close"])
        ref.index = pd.DatetimeIndex(pd.to_datetime(ref.pop("time"), utc=True))
        if not ref.index.is_unique or not ref.index.is_monotonic_increasing:
            raise ValueError("Invalid independent clock reference index")
        aggregated = ref.close.resample("5min").agg(["last", "count"])
        ref5 = aggregated["last"].where(aggregated["count"] == 5)
        weeks = list(pd.date_range(CAPTURE_START, END, freq="W-MON"))
        clock = audit_clock(btc.close, ref5, weeks)
        save(out / "historical_clock_audit.json", clock)
        if not clock["passed"]:
            raise ValueError("Historical broker clock not uniquely validated for every week")
        offset = clock["constant_offset_seconds"]
        print(f"CLOCK PASS: {len(weeks)} weeks, offset={offset}", flush=True)
        for symbol, meta in captured.items():
            frame = pd.read_csv(out / meta["raw_path"], index_col="time", parse_dates=True)
            frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True)) - pd.Timedelta(seconds=offset)
            frame = frame.loc[(frame.index >= CAPTURE_START) & (frame.index < END)]
            scored = frame.loc[frame.index >= SCORE_START]
            counts = [sum((scored.index >= a) & (scored.index < b)) for a, b in ((SCORE_START, BLOCK_SPLIT), (BLOCK_SPLIT, END))]
            if len(scored) < 40000 or min(counts) < 15000:
                raise ValueError(f"Insufficient predeclared coverage: {symbol}")
            path = market / f"{symbol}_bid_M1.csv"
            frame.to_csv(path, index_label="time")
            meta.update(path=str(path.relative_to(out)), sha256=sha(path), bars=len(frame), scored_bars=len(scored), block_bars=[int(n) for n in counts],
                        start=frame.index[0].isoformat(), end=frame.index[-1].isoformat(),
                        half_spread_assumed_for_unchanged_gate=source["captured"][symbol]["half_spread_assumed"])
        protocol = dict(plan, plan_sha256=sha(out / "plan_frozen.json"), captured=captured,
                        historical_clock_sha256=sha(out / "historical_clock_audit.json"), historical_offset_seconds=offset,
                        clock_raw_sha256=sha(market / "BTCUSD_reported_M5.csv"),
                        baseline_reports={s: str((Path("frozen") / (base / f"{s}_baseline.json").relative_to(ROOT))) for s in source["symbols"]})
        save(out / "protocol_frozen.json", protocol)
        (out / "protocol.sha256").write_text(sha(out / "protocol_frozen.json"), encoding="ascii")
        results, failures = {}, {}
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(worker, s, str(out)): s for s in source["symbols"]}
            for future in as_completed(pending):
                symbol = pending[future]
                try:
                    results[symbol] = future.result()
                    print(f"DONE {symbol}: {results[symbol]['candidate_n']} candidates", flush=True)
                except Exception as exc:
                    failures[symbol] = f"{type(exc).__name__}: {exc}"
                    print(f"FAILED {symbol}: {exc}", flush=True)
                save(out / "summary.json", [results[s] for s in source["symbols"] if s in results])
                save(out / "progress.json", {"completed": list(results), "failed": failures, "expected": source["symbols"]})
        for r in inputs:
            if sha(ROOT / r["path"]) != r["sha256"] or sha(out / "frozen" / r["path"]) != r["sha256"]:
                raise ValueError("Input changed during study")
        for meta in captured.values():
            if sha(out / meta["path"]) != meta["sha256"] or sha(out / meta["raw_path"]) != meta["raw_sha256"]:
                raise ValueError("Captured data changed during study")
        save(out / "completion.json", {"status": "COMPLETE" if not failures and len(results) == len(source["symbols"]) else "INCOMPLETE_SYMBOLS",
                                      "protocol_sha256": sha(out / "protocol_frozen.json"), "source_hashes_verified": True,
                                      "completed_symbols": len(results), "failed_symbols": failures, "edge_proven": False, "live_execution": False})
    except Exception as exc:
        save(out / "completion.json", {"status": "INCOMPLETE", "error": str(exc), "edge_proven": False})
        raise


if __name__ == "__main__":
    main()
