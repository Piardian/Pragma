"""Causal entry features versus frozen quote outcomes; diagnostic, not a filter search."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from pragma.backtest_engine import _resample_tf, _atr14
from pragma.measurement import ExecutionCosts, evaluate_prefix
from pragma.trigger_engine import evaluate_trigger


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def key(row):
    return row["symbol"], row["signal_bar_time"], row["direction"], row["poi_type"]


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else None


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def past_features(bid_bars, decision, direction):
    """Only strictly earlier complete M1 candles; gaps stay missing.

    Directional movement is positive when movement BEFORE the decision already
    followed the proposed trade direction. This is descriptive, not a gate.
    """
    if direction not in ("LONG", "SHORT"):
        raise ValueError("Invalid direction")
    if not bid_bars.index.is_unique or not bid_bars.index.is_monotonic_increasing:
        raise ValueError("Bars must have unique increasing timestamps")
    decision = pd.Timestamp(decision)
    bars = bid_bars.loc[bid_bars.index < decision]
    sign = 1 if direction == "LONG" else -1
    result = {}
    for minutes in (5, 15, 60):
        expected = pd.date_range(decision - pd.Timedelta(minutes=minutes), periods=minutes, freq="min")
        window = bars.loc[(bars.index >= expected[0]) & (bars.index <= expected[-1])]
        complete = window.index.equals(expected)
        move = None
        location = None
        if complete:
            opening, close = float(window.open.iloc[0]), float(window.close.iloc[-1])
            move = sign * (close - opening) / opening * 10000
            low, high = float(window.low.min()), float(window.high.max())
            location = ((close - low) if sign == 1 else (high - close)) / (high - low) if high > low else None
        result[f"prior_{minutes}m_complete"] = complete
        result[f"prior_{minutes}m_directional_bid_bps"] = move
        result[f"prior_{minutes}m_directional_range_location"] = location
    prior = result["prior_15m_directional_bid_bps"]
    result["prior_15m_group"] = "MISSING" if prior is None else "ALIGNED" if prior > 0 else "OPPOSED" if prior < 0 else "FLAT"
    return result


def volume_touch_chronology(m5, poi_low, poi_high):
    """Reconstruct ALL qualifying touches, not just the engine's first match.

    First-match age alone does not prove stale evidence: a newer candle may
    qualify too. Use the exact current trigger's default threshold and SMA.
    """
    bars = m5.tail(30)
    threshold = evaluate_trigger.__kwdefaults__["volume_multiplier"]
    baseline = bars.tick_volume.rolling(20, min_periods=20).mean()
    ages = []
    for pos in range(max(0, len(bars) - 3), len(bars)):
        candle = bars.iloc[pos]
        touched = candle.low <= poi_high and candle.high >= poi_low
        if touched and pd.notna(baseline.iloc[pos]) and baseline.iloc[pos] > 0:
            if float(candle.tick_volume) / float(baseline.iloc[pos]) >= threshold:
                ages.append((len(bars) - 1 - pos) * 5)
    return {"qualifying_volume_touch_ages_minutes": ages,
            "latest_qualifying_volume_touch_age_minutes": min(ages) if ages else None,
            "volume_multiplier_threshold": threshold}


def summarize(rows):
    good = [r for r in rows if r["outcome_15m"] is not None]
    return {
        "selected": len(rows), "quote_complete": len(good), "missing_quotes": len(rows) - len(good),
        "gross_mean_bps": mean([r["outcome_15m"]["mid_gross_bps"] for r in good]),
        "spread_only_mean_bps": mean([r["outcome_15m"]["quoted_spread_only_bps"] for r in good]),
        "gross_positive_n": sum(r["outcome_15m"]["mid_gross_bps"] > 0 for r in good),
        "prior_15m_median_bps": median([r["features"]["prior_15m_directional_bid_bps"] for r in rows]),
        "last_touch_age_median_minutes": median([r["timing"]["last_touch_age_minutes"] for r in rows]),
        "climax_age_median_minutes": median([r["timing"]["climax_age_minutes"] for r in rows]),
        "latest_volume_touch_age_median_minutes": median([r["timing"]["latest_qualifying_volume_touch_age_minutes"] for r in rows]),
        "stop_distance_median_atr": median([r["geometry"]["stop_distance_atr"] for r in rows]),
        "tp1_distance_median_atr": median([r["geometry"]["tp1_distance_atr"] for r in rows]),
        "fully_net_bps": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--entry-study", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    base, study, out = (Path(x).resolve() for x in (args.baseline, args.entry_study, args.output))
    out.mkdir(parents=True, exist_ok=False)
    try:
        source = json.loads((base / "protocol_frozen.json").read_text(encoding="utf-8"))
        for path in (base, study):
            completion = json.loads((path / "completion.json").read_text(encoding="utf-8"))
            if completion["status"] != "COMPLETE" or completion["protocol_sha256"] != sha(path / "protocol_frozen.json"):
                raise ValueError("Invalid source protocol/completion")
        inputs = []
        paths = sorted(list((ROOT / "pragma").rglob("*.py")) + list((ROOT / "config").glob("*.py")))
        paths += [Path(__file__).resolve(), base / "protocol_frozen.json", study / "protocol_frozen.json", study / "observations.json"]
        for symbol in source["symbols"]:
            paths += [base / "frozen" / source["captured"][symbol]["path"], base / f"{symbol}_baseline.json"]
        for path in paths:
            relative = path.relative_to(ROOT)
            target = out / "frozen" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            inputs.append({"path": str(relative), "sha256": sha(target)})
        def frozen(path):
            return out / "frozen" / path.relative_to(ROOT)
        protocol = {
            "created_at": datetime.now(timezone.utc).isoformat(), "inputs": inputs,
            "classification": "EXPLORATORY_REUSED_HISTORY_DIAGNOSTIC_NOT_STRATEGY_TRIAL",
            "primary_horizon_minutes": 15, "secondary_context_minutes": [5, 60],
            "population": "ALL_FROZEN_BASELINE_PRE_OCCUPANCY_CANDIDATES_118",
            "features": "Strictly closed M1 before decision, prior 5/15/60 directional bid movement and range location; canonical POI touch/climax/Z-extreme ages; ALL qualifying volume-touch ages at the unchanged default threshold; entry/stop/TP1 geometry in closed M15 ATR",
            "groups": ["ALIGNED", "OPPOSED", "FLAT", "MISSING"],
            "group_rule": "Sign of prior 15-minute direction-adjusted bid change, zero boundary only; no optimized thresholds",
            "mechanism_separation": "Keep canonical POI type/regime; momentum continuation and mean reversion cannot share a universal interpretation of prior trend",
            "candidate_precedence": "First executable matching canonical POI, same ordered precedence as the frozen entry study; record alternative count and verify actual trade levels",
            "outcomes": "Existing historical opposite-side quote proxies, primary 15 minutes; fees/slippage/swap incomplete",
            "actual_trade_link": "Separately link frozen 64 trade outcomes to the same candidate keys; exclude post-exit 15m movement from claims about open trades",
            "decision": "No filter, symbol or earlier entry selected by best outcome; no production change; no causality or edge claim from post-hoc associations",
            "live_execution": False, "edge_proven": False,
        }
        save(out / "protocol_frozen.json", protocol)
        (out / "protocol.sha256").write_text(sha(out / "protocol_frozen.json"), encoding="ascii")
        observations = json.loads(frozen(study / "observations.json").read_text(encoding="utf-8"))
        candidates = [r for r in observations if r["variant"] == "baseline" and r["horizon_minutes"] == 15]
        if len({key(r) for r in candidates}) != len(candidates):
            raise ValueError("Duplicate candidate keys")
        details, trades = [], []
        for symbol in source["symbols"]:
            meta = source["captured"][symbol]
            data = frozen(base / "frozen" / meta["path"])
            if sha(data) != meta["sha256"]:
                raise ValueError("Frozen bar hash mismatch")
            bid = pd.read_csv(data, index_col="time", parse_dates=True)
            bid.index = pd.DatetimeIndex(pd.to_datetime(bid.index, utc=True))
            mid = bid.copy()
            mid[["open", "high", "low", "close"]] += meta["half_spread_assumed"]
            mid.attrs.update(source="mt5", volume_semantics="BROKER_TICK_COUNT")
            report = json.loads(frozen(base / f"{symbol}_baseline.json").read_text(encoding="utf-8"))
            costs = ExecutionCosts(**report["measurement"]["costs"])
            actual = {key(t): t for t in report["trades"]}
            local = []
            for row in [r for r in candidates if r["symbol"] == symbol]:
                decision = pd.Timestamp(row["entry_time"])
                signal = pd.Timestamp(row["signal_bar_time"])
                if signal + pd.Timedelta(minutes=1) != decision:
                    raise ValueError("Unexpected entry timing")
                prefix = mid.loc[:signal]
                snapshot = evaluate_prefix(prefix, symbol=symbol, macro_bias="auto", allow_range=True, trigger_tf="M5", costs=costs)
                matches = [(p, t) for p, t in zip(snapshot["pois"], snapshot["triggers"], strict=True)
                           if t["execute"] and t["direction"] == row["direction"] and t["poi_type"] == row["poi_type"]]
                if snapshot["veto"] or not matches:
                    raise ValueError(f"Candidate parity failed: {key(row)}")
                poi, trigger = matches[0]
                metrics = trigger["metrics"]
                touches = metrics["poi_touch_positions"]
                climax = metrics["volume_climax_position"]
                extreme_times = [pd.Timestamp(t) for t in metrics["z_extreme_indices"]]
                timing = {
                    "last_touch_age_minutes": (29 - max(touches)) * 5 if touches else None,
                    "climax_age_minutes": (29 - climax) * 5 if climax is not None else None,
                    "last_z_extreme_age_minutes": (decision - max(extreme_times)).total_seconds() / 60 - 5 if extreme_times else None,
                    "interpretation": "Age since end of completed M5 candle; intrabar touch time unknown",
                }
                closed_m5 = _resample_tf(prefix, "M5").loc[lambda f: f.index + pd.Timedelta(minutes=5) <= decision]
                chronology = volume_touch_chronology(closed_m5, poi["poi_low"], poi["poi_high"])
                if not chronology["qualifying_volume_touch_ages_minutes"] or chronology["qualifying_volume_touch_ages_minutes"][0] != timing["climax_age_minutes"]:
                    raise ValueError("Volume evidence chronology mismatch")
                timing.update(chronology)
                atr = _atr14(_resample_tf(prefix, "M15").loc[lambda f: f.index + pd.Timedelta(minutes=15) <= decision])
                quote = row["entry_quote"]
                entry_mid = (quote["bid"] + quote["ask"]) / 2 if quote else None
                sign = 1 if row["direction"] == "LONG" else -1
                geometry = {
                    "closed_m15_atr": float(atr) if atr is not None else None,
                    "entry_mid": entry_mid, "stop": trigger["stop_loss"], "target1": trigger["take_profit_1"],
                    "stop_distance_atr": sign * (entry_mid - trigger["stop_loss"]) / atr if entry_mid is not None and atr else None,
                    "tp1_distance_atr": sign * (trigger["take_profit_1"] - entry_mid) / atr if entry_mid is not None and atr else None,
                    "bid_gap_after_decision_bps": sign * (quote["bid"] - float(bid.loc[signal, "close"])) / entry_mid * 10000 if quote else None,
                    "basis": "Observed entry quote mid vs frozen canonical levels and fixed-half-spread M15 ATR; geometry only, no executable return",
                }
                result = {**{k: row[k] for k in ("symbol", "direction", "poi_type", "signal_bar_time", "entry_time")},
                          "regime": snapshot["regime"], "features": past_features(bid, decision, row["direction"]),
                          "timing": timing, "geometry": geometry, "outcome_15m": row["observation"],
                          "paired_reference_excess_bps": row["paired_reference_excess_bps"],
                          "canonical_candidate_parity": True, "matching_poi_count": len(matches)}
                details.append(result)
                local.append(result)
                trade = actual.get(key(row))
                if trade:
                    for trigger_field, trade_field in (("stop_loss", "initial_stop_loss"), ("take_profit_1", "tp1"), ("take_profit_2", "tp2")):
                        if abs(trigger[trigger_field] - trade[trade_field]) > 1e-9:
                            raise ValueError("Actual trade level parity mismatch")
                    end = pd.Timestamp(trade["exit_time"])
                    still_open = end > decision + pd.Timedelta(minutes=15)
                    trades.append({**{k: result[k] for k in ("symbol", "direction", "poi_type", "signal_bar_time", "entry_time")},
                                   "exit_reason": trade["exit_reason"], "scenario_r": trade["r_multiple"],
                                   "tp1_taken": trade["tp1_taken"], "still_open_at_15m_by_bar_bound": still_open,
                                   "positive_mid_at_15m_then_lost": still_open and row["observation"] is not None and row["observation"]["mid_gross_bps"] > 0 and trade["r_multiple"] < 0,
                                   "prior_15m_group": result["features"]["prior_15m_group"],
                                   "outcome_15m": row["observation"]})
            if len(actual) != sum(r["symbol"] == symbol for r in trades):
                raise ValueError(f"Trade/candidate linkage incomplete: {symbol}")
            print(f"DONE {symbol}: {len(local)} candidates", flush=True)
        summaries = []
        for symbol in source["symbols"]:
            rows = [r for r in details if r["symbol"] == symbol]
            summaries.append({"symbol": symbol, "all": summarize(rows),
                              "by_prior_15m": {g: summarize([r for r in rows if r["features"]["prior_15m_group"] == g]) for g in protocol["groups"]},
                              "by_poi_type": {p: summarize([r for r in rows if r["poi_type"] == p]) for p in sorted({r["poi_type"] for r in rows})}})
        save(out / "summary.json", summaries)
        save(out / "candidates.json", details)
        save(out / "matched_actual_trades.json", trades)
        for row in inputs:
            path = ROOT / row["path"]
            if sha(path) != row["sha256"] or sha(frozen(path)) != row["sha256"]:
                raise ValueError("Inputs changed during analysis")
        save(out / "completion.json", {"status": "COMPLETE", "protocol_sha256": sha(out / "protocol_frozen.json"),
                                      "candidate_parity_n": len(details), "matched_actual_trades": len(trades),
                                      "inputs_hash_verified": True, "edge_proven": False, "live_execution": False})
    except Exception as exc:
        save(out / "completion.json", {"status": "INCOMPLETE", "error": str(exc), "edge_proven": False})
        raise


if __name__ == "__main__":
    main()
