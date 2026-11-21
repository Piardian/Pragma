"""Verify frozen bytes and EVERY baseline entry against the pointwise observer."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from pragma.measurement import ExecutionCosts, evaluate_prefix


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    args = parser.parse_args()
    run = Path(args.run)
    protocol = json.loads((run/"protocol_frozen.json").read_text())
    costs = ExecutionCosts(**protocol["costs"])
    for row in protocol["inputs"]:
        actual = hashlib.sha256((run/"frozen"/row["path"]).read_bytes()).hexdigest()
        if actual != row["sha256"]:
            raise ValueError(f"Frozen input hash mismatch: {row['path']}")
    # Current pure decision/execution code must still match the experiment.
    for row in protocol["inputs"]:
        if Path(row["path"]).name in ("measurement.py", "backtest_engine.py", "trigger_engine.py", "regime_poi_engine.py", "instrument_profiles.py", "amt_engine.py", "vwap_engine.py"):
            if hashlib.sha256((ROOT/row["path"]).read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("Decision core changed; use the frozen code to verify")
    results = []
    for symbol, tf in protocol["combinations"]:
        bars = pd.read_csv(run/"frozen"/"data_cache"/f"binance_{symbol}_M1.csv", index_col="time", parse_dates=True)
        bars.index = pd.DatetimeIndex(pd.to_datetime(bars.index, utc=True))
        bars = bars.tail(protocol["requested_bars"]).copy()
        bars.attrs.update(source="binance", volume_semantics="EXCHANGE_BASE_VOLUME")
        trades = json.loads((run/f"{symbol}_{tf}_baseline.json").read_text())["trades"]
        for trade_index, trade in enumerate(trades):
            signal_time = pd.Timestamp(trade["signal_bar_time"])
            prefix = bars.loc[:signal_time]
            names = list(dict.fromkeys(prefix.index.strftime("%Y-%m-%d")))
            # Contract state is finite: prior profile, current-session VWAP,
            # 30 trigger bars, ATR14, and five completed daily volumes. Eight
            # observed sessions preserve all of those plus a discarded first
            # fragment. Check full-prefix equality at BOTH range boundaries.
            window = prefix if len(names) <= 8 else prefix.loc[prefix.index >= pd.Timestamp(names[-8],tz="UTC")]
            snapshot = evaluate_prefix(window, symbol=symbol, macro_bias="auto", trigger_tf=tf, costs=costs)
            full_equal = None
            if trade_index in (0, len(trades)-1):
                full = evaluate_prefix(prefix, symbol=symbol, macro_bias="auto", trigger_tf=tf, costs=costs)
                full_equal = json.loads(json.dumps(full)) == json.loads(json.dumps(snapshot))
                if not full_equal:
                    raise ValueError("Finite decision window differs from full prefix")
            candidates = [t for t in snapshot["triggers"] if t["execute"] and t["direction"] == trade["direction"] and t["poi_type"] == trade["poi_type"]]
            if snapshot["veto"] or not candidates:
                raise ValueError(f"Executed candidate missing in observer: {symbol} {signal_time}")
            d = candidates[0]
            for key, other in [("stop_loss", "initial_stop_loss"), ("take_profit_1", "tp1"), ("take_profit_2", "tp2")]:
                if abs(d[key]-trade[other]) > 1e-9:
                    raise ValueError(f"Level mismatch: {symbol} {signal_time} {key}")
            fill = pd.Timestamp(trade["fill_time"])
            if fill != signal_time+pd.Timedelta(minutes=1) or fill.isoformat() != trade["decision_time"]:
                raise ValueError("Timestamp mismatch")
            expected = costs.adverse(float(bars.loc[fill,"open"]), trade["direction"], True)
            if abs(expected-trade["entry_price"]) > 1e-9:
                raise ValueError("Fill cost mismatch")
            results.append({"symbol":symbol,"tf":tf,"signal_bar_time":signal_time.isoformat(),"equal":True,
                            "full_prefix_boundary_equal":full_equal})
        print(f"VERIFIED {symbol} {tf}: {len(trades)} baseline entries",flush=True)
    report = {"status":"PASS","frozen_hashes_verified":True,"decision_core_current_matches_frozen":True,
              "baseline_entries_verified":len(results),"checks":results,"edge_proven":False}
    (run/"all_entry_parity_verification.json").write_text(json.dumps(report,indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
