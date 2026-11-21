"""Research-only early BE at +1R, preserving original profit targets and size."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
import pragma.backtest_engine as engine
from pragma.measurement import ExecutionCosts
from pragma.research_measurement import replay_fixed_entries, weekly_bootstrap
from scripts.run_near_tp1_study import sha, save, summarize


def early_be_manager(original):
    events, armed = [], set()

    def manage(p, bar, stamp, cost=0., cost_pct=0., apply_funding=False):
        if stamp < p.entry_time or (stamp == p.entry_time and not p.entry_at_open):
            return original(p, bar, stamp, cost, cost_pct, apply_funding)
        identity = p.symbol, p.entry_time.isoformat()
        sign = 1 if p.direction == "LONG" else -1
        applicable = (not p.tp1_taken and abs(p.tp1 - p.tp2) > 1e-12
                      and sign * (p.tp1 - p.entry_price) > p.initial_risk)
        if applicable and identity not in armed:
            trigger = p.entry_price + sign * p.initial_risk
            reached = bar.high >= trigger if sign == 1 else bar.low <= trigger
            old_stop_hit = bar.low <= p.stop_loss if sign == 1 else bar.high >= p.stop_loss
            if reached and old_stop_hit:
                events.append({"symbol": p.symbol, "entry_time": identity[1], "bar_time": stamp.isoformat(),
                               "event": "OLD_STOP_AND_TRIGGER_SAME_BAR_ORIGINAL_STOP_PRIORITY"})
            elif reached:
                armed.add(identity)
                p.stop_loss = p.entry_price
                touched = bar.low <= p.entry_price if sign == 1 else bar.high >= p.entry_price
                at_open = bar.open >= trigger if sign == 1 else bar.open <= trigger
                events.append({"symbol": p.symbol, "entry_time": identity[1], "bar_time": stamp.isoformat(),
                               "event": "ARMED", "trigger_price": trigger,
                               "trigger_at_open": bool(at_open), "same_bar_be_touch": bool(touched),
                               "intrabar_order_ambiguous": bool(touched and not at_open)})
                if touched:
                    # The opening price may PRECEDE activation. Do not pretend
                    # an earlier adverse opening was a post-activation stop fill.
                    # As with existing intrabar partial/BE logic, exit at the BE
                    # level plus adverse modeled costs, before crediting targets.
                    price = engine._adverse_price(p.entry_price, p.direction, False, cost, cost_pct)
                    p.r_multiple = sign * (price - p.entry_price) / p.initial_risk
                    end = stamp + pd.Timedelta(minutes=1) if p.entry_at_open else stamp
                    if apply_funding:
                        engine._apply_funding(p, end)
                    reason = "EARLY_BE_ACTIVATION_BAR_ORDER_ASSUMPTION" if not at_open else "EARLY_BE_TRIGGER_AT_OPEN_STOP"
                    return engine._trade_record(p, end, reason)
        record = original(p, bar, stamp, cost, cost_pct, apply_funding)
        if record and identity in armed and not record.tp1_taken and record.exit_reason == "STOP_LOSS":
            record = replace(record, exit_reason="EARLY_BREAKEVEN_STOP")
        return record

    return manage, events


def replay_entries(bars, trades, costs):
    if costs.funding_rate_8h:
        raise ValueError("FX-only experiment: funding unsupported")
    records = []
    manage, events = early_be_manager(engine._manage_open_trade)
    for t in trades:
        fill = pd.Timestamp(t["fill_time"])
        p = engine._OpenTrade(t["symbol"], t["direction"], t["poi_type"], t["regime"], fill,
                              t["entry_price"], t["initial_stop_loss"], t["initial_stop_loss"],
                              t["tp1"], t["tp2"], abs(t["entry_price"] - t["initial_stop_loss"]),
                              entry_at_open=True, funding_rate_8h=0, be_offset_r=0,
                              signal_bar_time=t["signal_bar_time"], decision_time=t["decision_time"])
        record = None
        for stamp, bar in bars.loc[fill:].iterrows():
            record = manage(p, bar, stamp, costs.fixed_per_side, costs.pct_per_side, False)
            if record:
                break
        if record is None:
            end = bars.index[-1] + pd.Timedelta(minutes=1)
            price = costs.adverse(float(bars.close.iloc[-1]), p.direction, False)
            fraction = 1 - p.tp1_close_pct if p.tp1_taken else 1
            p.r_multiple += fraction * (price - p.entry_price) * (1 if p.direction == "LONG" else -1) / p.initial_risk
            record = engine._trade_record(p, end, "END_OF_DATA")
        records.append(asdict(record))
    return records, events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--previous-study", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    base, previous, out = [Path(x).resolve() for x in (args.baseline, args.previous_study, args.output)]
    out.mkdir(parents=True, exist_ok=False)
    try:
        source = json.loads((base / "protocol_frozen.json").read_text(encoding="utf-8"))
        for directory in (base, previous):
            done = json.loads((directory / "completion.json").read_text(encoding="utf-8"))
            if done["status"] != "COMPLETE" or sha(directory / "protocol_frozen.json") != done["protocol_sha256"]:
                raise ValueError("Invalid source completion/protocol")
        previous_source = previous / "frozen" / (base / "protocol_frozen.json").relative_to(ROOT)
        if sha(previous_source) != sha(base / "protocol_frozen.json"):
            raise ValueError("Previous hypothesis used a different baseline")
        core = {"pragma/backtest_engine.py", "pragma/measurement.py", "pragma/trigger_engine.py",
                "pragma/regime_poi_engine.py", "pragma/instrument_profiles.py", "pragma/amt_engine.py",
                "pragma/vwap_engine.py", "config/settings.py"}
        core_rows = [r for r in source["inputs"] if Path(r["path"]).as_posix() in core]
        if len(core_rows) != len(core) or any(sha(ROOT / r["path"]) != r["sha256"] for r in core_rows):
            raise ValueError("Original decision/core source mismatch")
        paths = sorted(list((ROOT / "pragma").rglob("*.py")) + list((ROOT / "config").glob("*.py")))
        paths += [Path(__file__).resolve(), ROOT / "scripts/run_near_tp1_study.py", base / "protocol_frozen.json",
                  previous / "protocol_frozen.json", previous / "paired_trades.json"]
        for symbol in source["symbols"]:
            paths += [base / "frozen" / source["captured"][symbol]["path"], base / f"{symbol}_baseline.json"]
        inputs = []
        for path in paths:
            relative = path.relative_to(ROOT)
            target = out / "frozen" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            inputs.append({"path": str(relative), "sha256": sha(target)})
        protocol = {
            "created_at": datetime.now(timezone.utc).isoformat(), "inputs": inputs, "universe": source["symbols"],
            "classification": "EXPLORATORY_REUSED_HISTORY_NOT_OOS", "trigger_r": 1.0, "parameter_search": False,
            "hypothesis": "Original split-target positions whose TP1 exceeds 1 initial R: move stop to entry on +1R without early partial; preserve original TP1/TP2 and 50% partial size",
            "scope": "Same eligible split-target population as previous 1R partial study; single-target and already-near TP1 positions unchanged",
            "unchanged": "Original candidate eligibility, fills, first stop, targets, partial size, existing post-TP1 BE, costs, sessions and universe",
            "primary": "Identical baseline entries and per-symbol closed R deltas; previous 1R partial result shown as an already-completed reference, not a new fitted arm",
            "secondary": "Full original candidate-stream replay with altered stops and position occupancy",
            "ambiguity": "Old stop plus +1R in same M1: original stop wins. New activation and return to entry in same M1: modeled BE exit before target credit, flagged ambiguous unless open already crossed trigger. Intraminute gaps unobserved; stop-level fill is a scenario, not an actual fill",
            "gap_policy": "Do not use a pre-activation opening as a later BE fill. Subsequent bars retain original adverse opening-gap handling",
            "costs": "Original fixed-spread +1bps commission +0.5bps slippage per side, swap missing; not calibrated broker net and BE is not zero net cost",
            "decision": "No production promotion or winning-symbol/threshold selection from reused history; report ambiguity, censoring and every symbol",
            "edge_proven": False, "live_execution": False,
        }
        save(out / "protocol_frozen.json", protocol)
        (out / "protocol.sha256").write_text(sha(out / "protocol_frozen.json"), encoding="ascii")
        def frozen(path):
            return out / "frozen" / path.relative_to(ROOT)
        old_pairs = json.loads(frozen(previous / "paired_trades.json").read_text(encoding="utf-8"))
        summary, pairs = [], []
        for symbol in source["symbols"]:
            meta = source["captured"][symbol]
            data = frozen(base / "frozen" / meta["path"])
            if sha(data) != meta["sha256"]:
                raise ValueError("Frozen bars mismatch")
            bars = pd.read_csv(data, index_col="time", parse_dates=True)
            bars.index = pd.DatetimeIndex(pd.to_datetime(bars.index, utc=True))
            bars[["open", "high", "low", "close"]] += meta["half_spread_assumed"]
            bars.attrs.update(source="mt5", volume_semantics="BROKER_TICK_COUNT")
            baseline = json.loads(frozen(base / f"{symbol}_baseline.json").read_text(encoding="utf-8"))
            costs = ExecutionCosts(**baseline["measurement"]["costs"])
            trades = baseline["trades"]
            reproduced = replay_fixed_entries(bars, trades, costs, be_offset_r=0)
            for a, b in zip(trades, reproduced, strict=True):
                if abs(a["r_multiple"] - b["r_multiple"]) > 1e-10 or a["exit_time"] != b["exit_time"] or a["exit_reason"] != b["exit_reason"]:
                    raise ValueError("Baseline exit parity failed")
            variant, events = replay_entries(bars, trades, costs)
            local = []
            for a, b in zip(trades, variant, strict=True):
                complete = a["exit_reason"] != "END_OF_DATA" and b["exit_reason"] != "END_OF_DATA"
                row = {"symbol": symbol, "entry_time": a["entry_time"], "baseline": a, "variant": b,
                       "paired_closed": complete, "delta_r": b["r_multiple"] - a["r_multiple"] if complete else None}
                pairs.append(row)
                if complete:
                    local.append(row)
            save(out / "paired_trades.json", pairs)
            save(out / f"{symbol}_paired_events.json", events)
            manage, full_events = early_be_manager(engine._manage_open_trade)
            print(f"REPLAY {symbol}", flush=True)
            with patch.object(engine, "_manage_open_trade", manage):
                report = engine.run_backtest(bars, symbol=symbol, macro_bias="auto", allow_range=True, trigger_tf="M5", costs=costs).to_dict()
            save(out / f"{symbol}_full_replay.json", report)
            save(out / f"{symbol}_full_events.json", full_events)
            old_rows = [r for r in old_pairs if r["symbol"] == symbol]
            if [r["baseline"] for r in old_rows] != trades:
                raise ValueError("Previous fixed-entry comparison does not match baseline")
            old = [r["variant"] for r in old_rows]
            summary.append({"symbol": symbol, "baseline": summarize(trades), "fixed_entry_early_be": summarize(variant),
                            "previous_fixed_entry_1r_partial": summarize(old), "full_replay": summarize(report["trades"]),
                            "paired_closed_n": len(local), "paired_excluded_n": len(trades) - len(local),
                            "paired_delta": weekly_bootstrap([{"entry_time": r["entry_time"], "r_multiple": r["delta_r"]} for r in local]),
                            "paired_activated_n": sum(e["event"] == "ARMED" for e in events),
                            "paired_activation_order_ambiguous_n": sum(e.get("intrabar_order_ambiguous", False) for e in events),
                            "paired_old_stop_trigger_same_bar_n": sum(e["event"].startswith("OLD_STOP") for e in events)})
            save(out / "summary.json", summary)
            print(f"DONE {symbol}: paired delta={summary[-1]['paired_delta']['mean']}", flush=True)
        for r in inputs:
            if sha(ROOT / r["path"]) != r["sha256"] or sha(out / "frozen" / r["path"]) != r["sha256"]:
                raise ValueError("Input changed during study")
        save(out / "completion.json", {"status": "COMPLETE", "protocol_sha256": sha(out / "protocol_frozen.json"),
                                      "input_hashes_verified": True, "original_core_hashes_verified": len(core_rows),
                                      "baseline_exit_parity_n": len(pairs), "edge_proven": False, "live_execution": False})
    except Exception as exc:
        save(out / "completion.json", {"status": "INCOMPLETE", "error": str(exc), "edge_proven": False})
        raise


if __name__ == "__main__":
    main()
