"""Exit-only research: cap existing split TP1 at 1R, preserve single targets."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
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
from pragma.research_measurement import finite_json, replay_fixed_entries, weekly_bootstrap


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(finite_json(value), indent=2, allow_nan=False), encoding="utf-8")


def capped_tp1(direction, entry, stop, tp1, tp2):
    """No future prices, no change to single targets or already-nearer TP1."""
    if direction not in ("LONG", "SHORT"):
        raise ValueError("Invalid direction")
    sign = 1 if direction == "LONG" else -1
    risk = sign * (entry - stop)
    if risk <= 0 or sign * (tp1 - entry) <= 0 or sign * (tp2 - tp1) < -1e-12:
        raise ValueError("Invalid entry/stop/target geometry")
    if abs(tp1 - tp2) <= 1e-12:
        return tp1
    return entry + sign * min(sign * (tp1 - entry), risk)


def adjusted_trade(trade):
    return dict(trade, tp1=capped_tp1(trade["direction"], trade["entry_price"],
                                    trade["initial_stop_loss"], trade["tp1"], trade["tp2"]))


def near_tp1_manager(original):
    """Adapt after real simulated fill, before reading that candle's extremes."""
    seen, adjustments = set(), []

    def manage(position, bar, stamp, *args, **kwargs):
        identity = position.symbol, position.entry_time.isoformat()
        if identity not in seen:
            seen.add(identity)
            before = position.tp1
            position.tp1 = capped_tp1(position.direction, position.entry_price,
                                     position.initial_stop_loss, position.tp1, position.tp2)
            adjustments.append({"symbol": position.symbol, "entry_time": identity[1],
                                "original_tp1": before, "new_tp1": position.tp1,
                                "changed": before != position.tp1})
        return original(position, bar, stamp, *args, **kwargs)

    return manage, adjustments


def summarize(trades):
    closed = [t for t in trades if t["exit_reason"] != "END_OF_DATA"]
    return {"closed_n": len(closed), "end_of_data_n": len(trades) - len(closed),
            "scenario_r": sum(t["r_multiple"] for t in closed) if closed else None,
            "expectancy": weekly_bootstrap(closed), "fully_net_r": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    base, out = Path(args.baseline).resolve(), Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    try:
        source = json.loads((base / "protocol_frozen.json").read_text(encoding="utf-8"))
        done = json.loads((base / "completion.json").read_text(encoding="utf-8"))
        if done["status"] != "COMPLETE" or sha(base / "protocol_frozen.json") != done["protocol_sha256"]:
            raise ValueError("Invalid source completion/protocol")
        # Entry/core rules must be byte-identical to the original baseline.
        core = {"pragma\\backtest_engine.py", "pragma\\measurement.py", "pragma\\trigger_engine.py",
                "pragma\\regime_poi_engine.py", "pragma\\instrument_profiles.py", "pragma\\amt_engine.py",
                "pragma\\vwap_engine.py", "config\\settings.py"}
        core_rows = [r for r in source["inputs"] if str(Path(r["path"])) in core]
        if len(core_rows) != len(core):
            raise ValueError("Missing baseline core-source evidence")
        for row in core_rows:
            if sha(ROOT / row["path"]) != row["sha256"]:
                raise ValueError("Core source differs from original baseline")
        paths = sorted(list((ROOT / "pragma").rglob("*.py")) + list((ROOT / "config").glob("*.py")))
        paths += [Path(__file__).resolve(), base / "protocol_frozen.json", base / "completion.json"]
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
            "created_at": datetime.now(timezone.utc).isoformat(), "inputs": inputs,
            "classification": "EXPLORATORY_REUSED_HISTORY_NOT_OOS", "universe": source["symbols"],
            "hypothesis": "Only original distinct TP1/TP2 trades: cap TP1 distance at 1 initial R after fill; keep an already-nearer target; preserve single-target trades",
            "tp1_cap_r": 1.0, "parameter_search": False,
            "unchanged": "Original entry eligibility/cost gates, entry fill, stop, TP2, 50% partial size, BE offset 0, sessions/regime/volume/universe/costs",
            "mechanical_consequence": "Earlier TP1 also activates the EXISTING BE rule earlier; this is part of this single policy change, not independent evidence about BE",
            "primary": "Paired identical baseline entries, per-symbol closed R delta with both exits uncensored; no portfolio sum or extra-entry claim",
            "secondary": "Complete original candidate stream with altered exit management and position occupancy; original single-target handling retained",
            "fill_and_ambiguity": "Original next-M1 adverse fill and SL-first/BE-priority OHLC management; 1R uses actual simulated entry before inspecting fill-bar extremes",
            "costs": "Original fixed spread + 1bps fee +0.5bps slippage per side, swap absent; assumed scenario only, NOT calibrated broker net",
            "validation": "Eight decision/core input hashes equal original baseline; identical-entry baseline exit parity and full replay reference paths validated separately",
            "decision": "No automatic production promotion; report all symbols, losses, trade counts and censoring; no best-symbol or R-cap selection afterward",
            "edge_proven": False, "live_execution": False,
        }
        save(out / "protocol_frozen.json", protocol)
        (out / "protocol.sha256").write_text(sha(out / "protocol_frozen.json"), encoding="ascii")
        def frozen(path):
            return out / "frozen" / path.relative_to(ROOT)
        summary, paired_details = [], []
        for symbol in source["symbols"]:
            meta = source["captured"][symbol]
            path = frozen(base / "frozen" / meta["path"])
            if sha(path) != meta["sha256"]:
                raise ValueError("Frozen data hash mismatch")
            bars = pd.read_csv(path, index_col="time", parse_dates=True)
            bars.index = pd.DatetimeIndex(pd.to_datetime(bars.index, utc=True))
            bars[["open", "high", "low", "close"]] += meta["half_spread_assumed"]
            bars.attrs.update(source="mt5", volume_semantics="BROKER_TICK_COUNT")
            original = json.loads(frozen(base / f"{symbol}_baseline.json").read_text(encoding="utf-8"))
            trades = original["trades"]
            costs = ExecutionCosts(**original["measurement"]["costs"])
            reproduced = replay_fixed_entries(bars, trades, costs, be_offset_r=0)
            for a, b in zip(trades, reproduced, strict=True):
                if abs(a["r_multiple"] - b["r_multiple"]) > 1e-10 or a["exit_time"] != b["exit_time"] or a["exit_reason"] != b["exit_reason"]:
                    raise ValueError("Baseline fixed-entry parity failed")
            modified = [adjusted_trade(t) for t in trades]
            paired = replay_fixed_entries(bars, modified, costs, be_offset_r=0)
            closed_pairs = []
            for before, after in zip(trades, paired, strict=True):
                complete = before["exit_reason"] != "END_OF_DATA" and after["exit_reason"] != "END_OF_DATA"
                row = {"symbol": symbol, "entry_time": before["entry_time"], "baseline": before, "variant": after,
                       "tp1_changed": before["tp1"] != after["tp1"], "paired_closed": complete,
                       "delta_r": after["r_multiple"] - before["r_multiple"] if complete else None}
                paired_details.append(row)
                if complete:
                    closed_pairs.append(row)
            save(out / "paired_trades.json", paired_details)
            print(f"REPLAY {symbol}", flush=True)
            manage, adjustments = near_tp1_manager(engine._manage_open_trade)
            with patch.object(engine, "_manage_open_trade", manage):
                report = engine.run_backtest(bars, symbol=symbol, macro_bias="auto", allow_range=True, trigger_tf="M5", costs=costs).to_dict()
            if len(adjustments) != len(report["trades"]):
                raise ValueError("Every simulated entry must receive exactly one exit-policy assignment")
            save(out / f"{symbol}_full_replay.json", report)
            save(out / f"{symbol}_adjustments.json", adjustments)
            summary.append({"symbol": symbol, "baseline": summarize(trades), "fixed_entry_variant": summarize(paired),
                            "paired_closed_n": len(closed_pairs), "paired_excluded_n": len(trades) - len(closed_pairs),
                            "tp1_changed_n": sum(r["tp1_changed"] for r in paired_details if r["symbol"] == symbol),
                            "paired_delta": weekly_bootstrap([{"entry_time": r["entry_time"], "r_multiple": r["delta_r"]} for r in closed_pairs]),
                            "full_replay": summarize(report["trades"]), "baseline_exit_parity_n": len(trades)})
            save(out / "summary.json", summary)
            print(f"DONE {symbol}: paired delta={summary[-1]['paired_delta']['mean']}", flush=True)
        for row in inputs:
            if sha(ROOT / row["path"]) != row["sha256"] or sha(out / "frozen" / row["path"]) != row["sha256"]:
                raise ValueError("Source changed during experiment")
        save(out / "completion.json", {"status": "COMPLETE", "protocol_sha256": sha(out / "protocol_frozen.json"),
                                      "source_hashes_verified": True, "original_core_hashes_verified": len(core_rows),
                                      "baseline_exit_parity_n": sum(s["baseline_exit_parity_n"] for s in summary),
                                      "edge_proven": False, "live_execution": False})
    except Exception as exc:
        save(out / "completion.json", {"status": "INCOMPLETE", "error": str(exc), "edge_proven": False})
        raise


if __name__ == "__main__":
    main()
