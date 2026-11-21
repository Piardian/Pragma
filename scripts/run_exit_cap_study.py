"""One frozen, exploratory exit experiment; never changes production decisions."""
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
from pragma.backtest_engine import _OpenTrade, _manage_open_trade, _trade_record
from pragma.measurement import ExecutionCosts
from pragma.research_measurement import replay_fixed_entries

CAP_MINUTES = 15


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def replay_capped(bars, trade, costs):
    """Keep ordinary exits before deadline; close remaining size at deadline OPEN.

    No deadline candle extremes are read. Missing minutes invalidate still-open
    paths rather than supply favorable fills. Funding is not modeled here.
    """
    if costs.funding_rate_8h:
        raise ValueError("This FX experiment does not support funding")
    if not bars.index.is_unique or not bars.index.is_monotonic_increasing:
        raise ValueError("Bars must have unique increasing timestamps")
    fill = pd.Timestamp(trade["fill_time"])
    deadline = fill + pd.Timedelta(minutes=CAP_MINUTES)
    risk = abs(trade["entry_price"] - trade["initial_stop_loss"])
    if risk <= 0:
        raise ValueError("Invalid initial risk")
    p = _OpenTrade(
        trade["symbol"], trade["direction"], trade["poi_type"], trade["regime"],
        fill, trade["entry_price"], trade["initial_stop_loss"], trade["initial_stop_loss"],
        trade["tp1"], trade["tp2"], risk, entry_at_open=True, be_offset_r=0,
        funding_rate_8h=0, signal_bar_time=trade["signal_bar_time"],
        decision_time=trade["decision_time"],
    )
    for minute in range(CAP_MINUTES):
        stamp = fill + pd.Timedelta(minutes=minute)
        if stamp not in bars.index:
            return {"record": None, "missing_reason": "MISSING_PRE_DEADLINE_MINUTE"}
        record = _manage_open_trade(p, bars.loc[stamp], stamp,
                                    costs.fixed_per_side, costs.pct_per_side, False)
        if record:
            return {"record": asdict(record), "missing_reason": None}
    if deadline not in bars.index:
        return {"record": None, "missing_reason": "MISSING_DEADLINE_OPEN"}
    price = costs.adverse(float(bars.loc[deadline, "open"]), p.direction, False)
    fraction = 1 - p.tp1_close_pct if p.tp1_taken else 1.0
    sign = 1 if p.direction == "LONG" else -1
    p.r_multiple += fraction * sign * (price - p.entry_price) / p.initial_risk
    record = asdict(_trade_record(p, deadline, "TIME_CAP_15M"))
    record["exit_time_precision"] = "DEADLINE_M1_OPEN_SCENARIO_NOT_ACTUAL_FILL"
    return {"record": record, "missing_reason": None}


def anatomy(rows, symbol):
    selected = [r for r in rows if r["symbol"] == symbol and r["variant"] == "baseline"
                and r["horizon_minutes"] == CAP_MINUTES]
    complete = [r["observation"] for r in selected if r["observation"] is not None]
    def mean(field, items):
        values = [r[field] for r in items if r.get(field) is not None]
        return sum(values) / len(values) if values else None
    return {
        "selected_candidates": len(selected), "quote_complete": len(complete),
        "missing_quotes": len(selected) - len(complete),
        "mean_mid_gross_bps": mean("mid_gross_bps", complete),
        "mean_spread_only_bps": mean("quoted_spread_only_bps", complete),
        "mean_spread_drag_bps": mean("spread_drag", [
            {"spread_drag": r["mid_gross_bps"] - r["quoted_spread_only_bps"]} for r in complete]),
        "fee_proxy_complete": sum(r["known_cost_subtotal_bps"] is not None for r in complete),
        "mean_known_cost_subtotal_bps": mean("known_cost_subtotal_bps", complete),
        "fully_net_bps": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--entry-study", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    baseline = Path(args.baseline).resolve()
    study = Path(args.entry_study).resolve()
    out = Path(args.output).resolve()
    # Existing output cannot be overwritten, including a failed experiment.
    out.mkdir(parents=True, exist_ok=False)
    try:
        original = json.loads((baseline / "protocol_frozen.json").read_text(encoding="utf-8"))
        for source in (baseline, study):
            completion = json.loads((source / "completion.json").read_text(encoding="utf-8"))
            if completion["status"] != "COMPLETE" or sha(source / "protocol_frozen.json") != completion["protocol_sha256"]:
                raise ValueError("Invalid source completion/protocol")
        paths = sorted(list((ROOT / "pragma").rglob("*.py")) + list((ROOT / "config").glob("*.py")))
        paths += [Path(__file__).resolve(), baseline / "protocol_frozen.json", baseline / "completion.json",
                  study / "protocol_frozen.json", study / "completion.json", study / "observations.json"]
        for symbol in original["symbols"]:
            paths += [baseline / f"{symbol}_baseline.json", baseline / "frozen" / original["captured"][symbol]["path"]]
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
            "hypothesis": "Maximum holding time of 15 minutes, retaining earlier original stops/targets/partials/BE",
            "cap_minutes": CAP_MINUTES, "parameter_search": False,
            "rationale": "15 minutes was already the entry study primary horizon; test profit giveback without selecting a best duration",
            "universe": original["symbols"], "entries": "IDENTICAL_FROZEN_BASELINE_ENTRIES",
            "deadline_fill": "Deadline M1 OPEN, after processing only earlier bars; no deadline-bar high/low",
            "costs": "UNCHANGED_OLD_ASSUMED_SCENARIO_NOT_CALIBRATED_BROKER_NET_SWAP_MISSING",
            "missing_policy": "No interpolation or gap fills; missing paths retained and excluded from paired means",
            "counterfactual_scope": "Fixed entries only; does not model additional entries allowed by earlier exits or portfolio capital",
            "decision_rule": "No universal promotion; report every symbol and coverage, including negative outcomes; no follow-up cap sweep on this history",
            "edge_proven": False, "live_execution": False,
        }
        save(out / "protocol_frozen.json", protocol)
        (out / "protocol.sha256").write_text(sha(out / "protocol_frozen.json"), encoding="ascii")
        def frozen(path):
            return out / "frozen" / path.relative_to(ROOT)
        observations = json.loads(frozen(study / "observations.json").read_text(encoding="utf-8"))
        details, summaries = [], []
        for symbol in original["symbols"]:
            meta = original["captured"][symbol]
            data = frozen(baseline / "frozen" / meta["path"])
            if sha(data) != meta["sha256"]:
                raise ValueError(f"Captured data mismatch: {symbol}")
            bars = pd.read_csv(data, index_col="time", parse_dates=True)
            bars.index = pd.DatetimeIndex(pd.to_datetime(bars.index, utc=True))
            bars[["open", "high", "low", "close"]] += meta["half_spread_assumed"]
            report = json.loads(frozen(baseline / f"{symbol}_baseline.json").read_text(encoding="utf-8"))
            costs = ExecutionCosts(**report["measurement"]["costs"])
            trades = report["trades"]
            # Reject a changed execution engine before drawing exit conclusions.
            reproduced = replay_fixed_entries(bars, trades, costs, be_offset_r=0)
            for a, b in zip(trades, reproduced, strict=True):
                if (abs(a["r_multiple"] - b["r_multiple"]) > 1e-10 or
                        a["exit_time"] != b["exit_time"] or a["exit_reason"] != b["exit_reason"]):
                    raise ValueError(f"Baseline replay mismatch: {symbol}")
            local = []
            for trade in trades:
                capped = replay_capped(bars, trade, costs)
                valid = trade["exit_reason"] != "END_OF_DATA" and capped["record"] is not None
                row = {"symbol": symbol, "entry_time": trade["entry_time"], "baseline": trade,
                       "capped": capped["record"], "missing_reason": capped["missing_reason"],
                       "paired_closed": valid,
                       "delta_scenario_r": capped["record"]["r_multiple"] - trade["r_multiple"] if valid else None}
                details.append(row)
                local.append(row)
            paired = [r for r in local if r["paired_closed"]]
            capped_r = sum(r["capped"]["r_multiple"] for r in paired) if paired else None
            base_r = sum(r["baseline"]["r_multiple"] for r in paired) if paired else None
            summaries.append({"symbol": symbol, "baseline_parity_n": len(trades),
                              "paired_closed_n": len(paired), "excluded_n": len(local) - len(paired),
                              "baseline_paired_scenario_r": base_r, "capped_paired_scenario_r": capped_r,
                              "delta_scenario_r": capped_r - base_r if paired else None,
                              "time_cap_exits": sum(r["capped"]["exit_reason"] == "TIME_CAP_15M" for r in paired),
                              "candidate_anatomy_15m": anatomy(observations, symbol)})
            print(f"DONE {symbol}: paired={len(paired)}, delta={summaries[-1]['delta_scenario_r']}", flush=True)
        save(out / "trades.json", details)
        save(out / "summary.json", summaries)
        for row in inputs:
            path = ROOT / row["path"]
            if sha(path) != row["sha256"] or sha(frozen(path)) != row["sha256"]:
                raise ValueError(f"Input changed: {path}")
        save(out / "completion.json", {"status": "COMPLETE", "protocol_sha256": sha(out / "protocol_frozen.json"),
                                      "source_hashes_unchanged": True, "baseline_parity_n": sum(s["baseline_parity_n"] for s in summaries),
                                      "edge_proven": False, "live_execution": False})
    except Exception as exc:
        save(out / "completion.json", {"status": "INCOMPLETE", "error": str(exc), "edge_proven": False})
        raise


if __name__ == "__main__":
    main()
