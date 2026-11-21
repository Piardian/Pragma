"""Frozen, broker-free research; existing results are never overwritten."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from pragma.backtest_engine import run_backtest
from pragma.measurement import ExecutionCosts, evaluate_prefix
from pragma.research_measurement import finite_json, weekly_bootstrap, replay_fixed_entries, horizon_diagnostics


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(finite_json(data), indent=2, allow_nan=False), encoding="utf-8")


def load_bars(path):
    frame = pd.read_csv(path)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("time"), utc=True))
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Duplicate or unsorted timestamps; input is not silently repaired")
    if (frame.index.to_series().diff().dropna() != pd.Timedelta(minutes=1)).any():
        raise ValueError("Crypto research requires contiguous M1 history")
    if not (frame.tick_volume == frame.volume).all():
        raise ValueError("Cache volume differs from exchange base volume")
    if not ((frame.volume_delta - (2*frame.taker_buy_base_asset_volume-frame.volume)).abs() < 1e-7).all():
        raise ValueError("Cache taker delta does not match raw fields")
    frame.attrs.update(source="binance", volume_semantics="EXCHANGE_BASE_VOLUME")
    return frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--bars", type=int, default=300000)
    parser.add_argument("--timeframes", nargs="+", choices=("M5", "M15"), default=["M15"])
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    snapshots = out / "frozen"
    snapshots.mkdir()
    symbols = ("BTCUSDT", "SOLUSDT", "LINKUSDT")
    combinations = [(s, tf) for s in symbols for tf in args.timeframes]
    cost = ExecutionCosts(commission_bps=4, slippage_bps=1, funding_rate_8h=0.0001, provenance="ASSUMED_NOT_BROKER_CALIBRATED")
    inputs = []
    code = sorted(list((ROOT/"pragma").rglob("*.py")) + list((ROOT/"config").glob("*.py")) + [Path(__file__).resolve()])
    data = [ROOT/"data_cache"/f"binance_{s}_M1.csv" for s in symbols]
    for path in code + data:
        relative = path.relative_to(ROOT)
        target = snapshots / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        inputs.append({"path": str(relative), "sha256": sha(target), "bytes": target.stat().st_size})
    protocol = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "contract": "measurement-v2",
        "classification": "EXPLORATORY_ALREADY_INSPECTED_HISTORY_NOT_OOS",
        "combinations": combinations, "requested_bars": args.bars, "costs": asdict(cost),
        "hypotheses": {
            "baseline": "3 trigger-bar touch, next M1 open, 50% TP1, BE=0; one position per symbol per run",
            "last_bar_touch": "Change ONLY touch window from 3 to 1, full strategy replay",
            "cost_stress_1_5": "Multiply ALL cost components by 1.5, full strategy replay",
            "no_be_fixed_entries": "Change ONLY BE to None on IDENTICAL baseline entries; independent paired exit counterfactuals, no portfolio return claim",
            "entry_quality": "All executable candidates before occupancy; 5/15/30-minute net bps versus previous-week same-clock same-direction reference",
        },
        "selection_policy": "Report every predeclared combination and trial; do not promote winners",
        "uncertainty": "Week-cluster bootstrap seed 231026; exploratory unadjusted intervals; overlapping horizons are dependent",
        "acceptance": "No live promotion. Fresh cost evidence, parity, time-separated forward data, net positive expectancy and 1.5x survival required; multiplicity unresolved -> edge_proven false",
        "macro_policy": "auto causal price regime, no current gate applied to past",
        "fx_gold_status": "Historical HistData volume invalid; not silently replaced or pooled with crypto",
        "inputs": inputs, "edge_proven": False, "live_execution": False,
    }
    save(out/"protocol_frozen.json", protocol)
    (out/"protocol.sha256").write_text(sha(out/"protocol_frozen.json"), encoding="ascii")
    # Verify imported code is byte-identical to the frozen sources before use.
    for row in inputs:
        if sha(ROOT/row["path"]) != row["sha256"]:
            raise ValueError("Source changed during freeze")
    summaries = []
    for symbol, tf in combinations:
        print(f"START {symbol} {tf}", flush=True)
        bars = load_bars(snapshots/"data_cache"/f"binance_{symbol}_M1.csv").tail(args.bars).copy()
        candidates = []
        parity_samples = []
        def candidate(stamp, poi, decision, atr, veto):
            # Keep touched/rejected candidates as well as executable candidates.
            if decision.execute or decision.metrics.get("poi_touched"):
                candidates.append({"signal_bar_time": stamp.isoformat(), "direction": poi.direction,
                                   "poi_type": poi.poi_type, "reason": decision.reason,
                                   "day_veto": veto, "eligible": decision.execute and not veto,
                                   "atr": atr})
        def observe(snapshot):
            # Deterministic first 12 nonempty decision snapshots per combo.
            if snapshot["pois"] and len(parity_samples) < 12:
                parity_samples.append(snapshot)
        reports = {}
        for name, actual_cost, touch in [("baseline", cost, 3), ("last_bar_touch", cost, 1), ("cost_stress_1_5", cost.stressed(1.5), 3)]:
            print(f"  RUN {name}", flush=True)
            report = run_backtest(bars, symbol=symbol, macro_bias="auto", trigger_tf=tf,
                                  costs=actual_cost, touch_bars=touch,
                                  decision_observer=observe if name == "baseline" else None,
                                  candidate_observer=candidate if name == "baseline" else None)
            reports[name] = report
            save(out/f"{symbol}_{tf}_{name}.json", report.to_dict())
        parity = []
        for expected in parity_samples:
            prefix = bars.loc[:pd.Timestamp(expected["signal_bar_time"])]
            actual = evaluate_prefix(prefix, symbol=symbol, macro_bias="auto", trigger_tf=tf, costs=cost)
            equal = finite_json(json.loads(json.dumps(expected))) == finite_json(json.loads(json.dumps(actual)))
            parity.append({"signal_bar_time": expected["signal_bar_time"], "equal": equal,
                           "expected": expected, "actual": actual})
        save(out/f"{symbol}_{tf}_parity.json", parity)
        if not parity or not all(x["equal"] for x in parity):
            raise ValueError(f"Decision parity not proven: {symbol} {tf}")
        baseline = reports["baseline"].trades
        replay = replay_fixed_entries(bars, baseline, cost, be_offset_r=0.0)
        if len(replay) != len(baseline) or any(abs(a["r_multiple"]-b["r_multiple"]) > 1e-10 or a["exit_reason"] != b["exit_reason"] for a,b in zip(replay, baseline)):
            raise ValueError("Fixed-entry baseline exit replay differs")
        no_be = replay_fixed_entries(bars, baseline, cost, be_offset_r=None)
        save(out/f"{symbol}_{tf}_no_be_fixed_entries.json", no_be)
        deltas = [{"entry_time": a["entry_time"], "r_multiple": b["r_multiple"]-a["r_multiple"]}
                  for a,b in zip(baseline,no_be) if a["exit_reason"] != "END_OF_DATA" and b["exit_reason"] != "END_OF_DATA"]
        quality, eligible, rejected = horizon_diagnostics(bars, candidates, cost)
        for name, rows in [("entry_quality", eligible), ("rejected_counterfactuals", rejected), ("candidates", candidates)]:
            with (out/f"{symbol}_{tf}_{name}.jsonl").open("w",encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(finite_json(row), allow_nan=False)+"\n")
        row = {"symbol": symbol, "tf": tf, "parity_checks": len(parity),
               "start": bars.index[0].isoformat(), "end": bars.index[-1].isoformat(),
               "trials": {}, "no_be_paired_delta": weekly_bootstrap(deltas), "entry_quality": quality}
        for name, report in reports.items():
            closed = [t for t in report.trades if t["exit_reason"] != "END_OF_DATA"]
            row["trials"][name] = {"reported_r_including_mark": report.net_r, "trades_including_mark": report.total_trades,
                                   "closed": weekly_bootstrap(closed), "max_dd_r": report.max_drawdown_r}
        summaries.append(row)
        save(out/"summary.json", summaries)
        print(f"DONE {symbol} {tf} baseline={reports['baseline'].net_r:.4f}R", flush=True)
    for row in inputs:
        if sha(ROOT/row["path"]) != row["sha256"]:
            raise ValueError("Source changed during experiment; run invalid")
    save(out/"completion.json", {"status": "COMPLETE", "source_hashes_unchanged": True,
                                 "protocol_sha256": sha(out/"protocol_frozen.json"),
                                 "edge_proven": False, "live_execution": False,
                                 "unresolved": ["Costs assumed, not calibrated", "Exploratory reused data", "No forward profitability evidence", "Multiplicity not corrected"]})
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
