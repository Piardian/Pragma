"""One entry filter: original reversal plus current-M5 POI volume touch.

Research-only execution adapter. Production files and running observers are
never edited. Fixed candidate quotes and full occupancy replay are separate.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
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
from pragma.research_measurement import weekly_bootstrap, finite_json
from scripts.audit_entry_timing import volume_touch_chronology


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(finite_json(value), indent=2, allow_nan=False), encoding="utf-8")


def key(row):
    return row["symbol"], row["signal_bar_time"], row["direction"], row["poi_type"]


def current_touch_volume(bars, poi):
    if len(bars) < 30:
        return False
    return volume_touch_chronology(bars, poi.poi_low, poi.poi_high)["latest_qualifying_volume_touch_age_minutes"] == 0


def synchronized_decider(original):
    """Keep the FIRST original executable POI for each existing candidate key.

    If its volume is stale, do not substitute another zone with different
    levels. This preserves the frozen first-POI candidate convention.
    """
    seen = set()
    selections = {}

    def decide(symbol, bars, poi, *args, **kwargs):
        decision = original(symbol, bars, poi, *args, **kwargs)
        if not decision.execute:
            return decision
        stamp = (bars.index[-1] + pd.Timedelta(minutes=4)).isoformat()
        identity = (symbol, stamp, poi.direction, poi.poi_type)
        if identity in seen:
            return replace(decision, execute=False, reason="RESEARCH_DUPLICATE_CANONICAL_POI")
        seen.add(identity)
        accepted = current_touch_volume(bars, poi)
        selections[identity] = accepted
        return decision if accepted else replace(decision, execute=False, reason="RESEARCH_CURRENT_M5_VOLUME_TOUCH_REQUIRED")

    return decide, selections


def quote_summary(rows):
    good = [r for r in rows if r["observation"] is not None]
    values = [{"entry_time": r["entry_time"], "r_multiple": r["observation"]["quoted_spread_only_bps"]} for r in good]
    known = [{"entry_time": r["entry_time"], "r_multiple": r["observation"]["known_cost_subtotal_bps"]}
             for r in good if r["observation"]["known_cost_subtotal_bps"] is not None]
    return {"selected": len(rows), "quote_complete": len(good), "missing_quotes": len(rows) - len(good),
            "spread_only_bps": weekly_bootstrap(values), "known_cost_subtotal_bps": weekly_bootstrap(known),
            "fully_net_bps": None, "same_signal_return_change_bps": 0.0 if good else None}


def scenario_summary(report):
    closed = [t for t in report["trades"] if t["exit_reason"] != "END_OF_DATA"]
    return {"n": len(closed), "end_of_data_n": len(report["trades"]) - len(closed),
            "closed_scenario_r": sum(t["r_multiple"] for t in closed) if closed else None,
            "closed_expectancy": weekly_bootstrap(closed), "fully_net_r": None}


def assert_baseline_parity(actual, expected):
    if actual["trades"] != expected["trades"]:
        raise ValueError("Full baseline trade-path parity failed")
    for field in ("bars_processed", "total_trades", "net_r", "funnel_counts"):
        if actual[field] != expected[field]:
            raise ValueError(f"Full baseline parity failed: {field}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--entry-study", required=True)
    parser.add_argument("--timing-audit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    base, study, audit, out = [Path(x).resolve() for x in (args.baseline, args.entry_study, args.timing_audit, args.output)]
    out.mkdir(parents=True, exist_ok=False)
    try:
        source = json.loads((base / "protocol_frozen.json").read_text(encoding="utf-8"))
        for directory in (base, study, audit):
            done = json.loads((directory / "completion.json").read_text(encoding="utf-8"))
            if done["status"] != "COMPLETE" or done["protocol_sha256"] != sha(directory / "protocol_frozen.json"):
                raise ValueError("Invalid source completion/protocol")
        paths = sorted(list((ROOT / "pragma").rglob("*.py")) + list((ROOT / "config").glob("*.py")))
        paths += [Path(__file__).resolve(), ROOT / "scripts/audit_entry_timing.py",
                  base / "protocol_frozen.json", study / "protocol_frozen.json", study / "observations.json",
                  audit / "protocol_frozen.json", audit / "candidates.json"]
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
            "classification": "EXPLORATORY_REUSED_HISTORY_NOT_OOS",
            "variants": ["baseline", "same_m5_volume_touch"],
            "hypothesis": "Keep an original executable reversal only when its signal M5 ALSO touches the SAME canonical POI with the existing >=1.35x SMA20 tick volume condition",
            "unchanged": "Existing Z-turn/recovery, wick-or-body rejection, fees, entry time, stops, targets, BE, sessions, regime and universe",
            "not_added": "No extra directional body threshold; no extra waiting candle; no requirement that Z extreme itself occur on the reversal candle",
            "candidate_precedence": "First original executable POI per signal/direction/type; reject alternate same-key POIs rather than change levels when first fails",
            "primary": "15-minute observed-spread quote mean and coverage: all, kept and rejected; conditional selection contrast, NOT a same-signal price improvement",
            "secondary_horizons_minutes": [5, 30],
            "full_replay": "Run baseline and filtered rule with position occupancy and pending fills from scratch; require exact original baseline reproduction; isolated in-process research adapter only",
            "costs": "Quote study observed bid/ask, fees where evidenced, missing slippage/swap; full replay old fixed-spread +1bps fee +0.5bps slippage per side unchanged, not calibrated net",
            "missing_policy": "Keep missing quotes/counts; never score missing quotes or zero-trade symbols as wins; zero-trade summary mean/R undefined",
            "no_search": "Only current M5, no 5/10-minute freshness or volume-threshold sweep; all 13 symbols, no best-symbol selection",
            "decision": "No live promotion from reused history; assess every symbol and sample loss; independent validation only if a convincing candidate survives, never relabel this as OOS",
            "edge_proven": False, "live_execution": False,
        }
        save(out / "protocol_frozen.json", protocol)
        (out / "protocol.sha256").write_text(sha(out / "protocol_frozen.json"), encoding="ascii")
        def frozen(path):
            return out / "frozen" / path.relative_to(ROOT)
        candidates = json.loads(frozen(audit / "candidates.json").read_text(encoding="utf-8"))
        accepted = {key(r): r["timing"]["latest_qualifying_volume_touch_age_minutes"] == 0 for r in candidates}
        if len(accepted) != len(candidates):
            raise ValueError("Duplicate frozen candidate keys")
        observations = [r for r in json.loads(frozen(study / "observations.json").read_text(encoding="utf-8")) if r["variant"] == "baseline"]
        decisions = [{**{k: r[k] for k in ("symbol", "signal_bar_time", "direction", "poi_type", "entry_time")},
                      "accepted": accepted[key(r)], "latest_volume_touch_age_minutes": r["timing"]["latest_qualifying_volume_touch_age_minutes"]}
                     for r in candidates]
        save(out / "selections.json", decisions)
        quotes = []
        for symbol in source["symbols"]:
            horizons = {}
            for horizon in (5, 15, 30):
                rows = [r for r in observations if r["symbol"] == symbol and r["horizon_minutes"] == horizon]
                kept = [r for r in rows if accepted[key(r)]]
                rejected = [r for r in rows if not accepted[key(r)]]
                all_s, keep_s, reject_s = [quote_summary(x) for x in (rows, kept, rejected)]
                all_mean, kept_mean = all_s["spread_only_bps"]["mean"], keep_s["spread_only_bps"]["mean"]
                horizons[str(horizon)] = {"baseline": all_s, "kept": keep_s, "rejected": reject_s,
                                          "conditional_mean_change_bps": kept_mean - all_mean if kept_mean is not None and all_mean is not None else None}
            quotes.append({"symbol": symbol, "horizons": horizons})
        save(out / "quote_summary.json", quotes)
        replays = []
        for symbol in source["symbols"]:
            meta = source["captured"][symbol]
            path = frozen(base / "frozen" / meta["path"])
            if sha(path) != meta["sha256"]:
                raise ValueError("Frozen bars mismatch")
            bars = pd.read_csv(path, index_col="time", parse_dates=True)
            bars.index = pd.DatetimeIndex(pd.to_datetime(bars.index, utc=True))
            bars[["open", "high", "low", "close"]] += meta["half_spread_assumed"]
            bars.attrs.update(source="mt5", volume_semantics="BROKER_TICK_COUNT")
            original = json.loads(frozen(base / f"{symbol}_baseline.json").read_text(encoding="utf-8"))
            costs = ExecutionCosts(**original["measurement"]["costs"])
            print(f"BASELINE {symbol}", flush=True)
            base_report = engine.run_backtest(bars, symbol=symbol, macro_bias="auto", allow_range=True, trigger_tf="M5", costs=costs).to_dict()
            assert_baseline_parity(base_report, original)
            save(out / f"{symbol}_baseline_reproduced.json", base_report)
            decide, selection_map = synchronized_decider(engine.decide_trigger)
            print(f"FILTERED {symbol}", flush=True)
            with patch.object(engine, "decide_trigger", decide):
                filtered = engine.run_backtest(bars, symbol=symbol, macro_bias="auto", allow_range=True, trigger_tf="M5", costs=costs).to_dict()
            expected = {k: v for k, v in accepted.items() if k[0] == symbol}
            # Frozen quote candidates can exclude events at the very end of data
            # that never had a usable original horizon. Preserve extras explicitly.
            if any(selection_map.get(k) != v for k, v in expected.items()):
                raise ValueError(f"Frozen candidate/filter parity mismatch: {symbol}")
            extras = [{"identity": list(k), "accepted": v} for k, v in selection_map.items() if k not in expected]
            for trade in filtered["trades"]:
                if selection_map.get(key(trade)) is not True:
                    raise ValueError("Filtered trade did not pass frozen gate")
            save(out / f"{symbol}_filtered.json", filtered)
            before, after = scenario_summary(base_report), scenario_summary(filtered)
            replays.append({"symbol": symbol, "baseline": before, "filtered": after,
                            "closed_scenario_r_change": after["closed_scenario_r"] - before["closed_scenario_r"] if after["n"] and before["n"] else None,
                            "baseline_parity": True, "candidate_selection_parity_n": len(expected), "extra_decision_events": extras})
            save(out / "replay_summary.json", replays)
            print(f"DONE {symbol}: {before['n']} -> {after['n']} closed trades", flush=True)
        for row in inputs:
            path = ROOT / row["path"]
            if sha(path) != row["sha256"] or sha(frozen(path)) != row["sha256"]:
                raise ValueError("Input changed during experiment")
        save(out / "completion.json", {"status": "COMPLETE", "protocol_sha256": sha(out / "protocol_frozen.json"),
                                      "source_hashes_verified": True, "baseline_entries_reproduced": sum(r["baseline"]["n"] for r in replays),
                                      "candidate_selection_parity_n": len(candidates), "selected_candidates": sum(accepted.values()),
                                      "edge_proven": False, "live_execution": False})
    except Exception as exc:
        save(out / "completion.json", {"status": "INCOMPLETE", "error": str(exc), "edge_proven": False})
        raise


if __name__ == "__main__":
    main()
