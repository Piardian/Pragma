"""Validate every executed broker-research entry using a closed-prefix observer."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from pragma.measurement import ExecutionCosts, evaluate_prefix


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("run")
    args=parser.parse_args()
    run=Path(args.run)
    protocol=json.loads((run/"protocol_frozen.json").read_text(encoding="utf-8"))
    for row in protocol["inputs"]:
        if hashlib.sha256((run/"frozen"/row["path"]).read_bytes()).hexdigest()!=row["sha256"]:
            raise ValueError("Frozen source mismatch")
        if hashlib.sha256((ROOT/row["path"]).read_bytes()).hexdigest()!=row["sha256"]:
            raise ValueError("Current source mismatch; verify with frozen source")
    source=protocol.get("spread_quote_source")
    if source and hashlib.sha256((run/"frozen/spread_quotes.jsonl").read_bytes()).hexdigest()!=source["sha256"]:
        raise ValueError("Archived quote hash mismatch")
    checks=[]
    for symbol,meta in protocol["captured"].items():
        csv=run/"frozen"/meta["path"]
        if hashlib.sha256(csv.read_bytes()).hexdigest()!=meta["sha256"]:
            raise ValueError("Broker history hash mismatch")
        bars=pd.read_csv(csv,index_col="time",parse_dates=True)
        bars.index=pd.DatetimeIndex(pd.to_datetime(bars.index,utc=True))
        bars[["open","high","low","close"]]+=meta["half_spread_assumed"]
        bars.attrs.update(source="mt5",volume_semantics="BROKER_TICK_COUNT")
        report=json.loads((run/f"{symbol}_baseline.json").read_text(encoding="utf-8"))
        costs=ExecutionCosts(**report["measurement"]["costs"])
        for trade in report["trades"]:
            signal=pd.Timestamp(trade["signal_bar_time"])
            # At most 30k bars per prefix; use the complete downloaded prefix.
            actual=evaluate_prefix(bars.loc[:signal],symbol=symbol,macro_bias="auto",allow_range=True,trigger_tf="M5",costs=costs)
            candidates=[d for d in actual["triggers"] if d["execute"] and d["poi_type"]==trade["poi_type"] and d["direction"]==trade["direction"]]
            if actual["veto"] or not candidates:
                raise ValueError(f"Missing executed candidate: {symbol} {signal}")
            decision=candidates[0]
            for a,b in [("stop_loss","initial_stop_loss"),("take_profit_1","tp1"),("take_profit_2","tp2")]:
                if abs(decision[a]-trade[b])>1e-9: raise ValueError("Level mismatch")
            fill=pd.Timestamp(trade["fill_time"])
            if fill!=signal+pd.Timedelta(minutes=1) or fill.isoformat()!=trade["decision_time"]:
                raise ValueError("Timestamp mismatch")
            if abs(costs.adverse(float(bars.loc[fill,"open"]),trade["direction"],True)-trade["entry_price"])>1e-9:
                raise ValueError("Fill mismatch")
            checks.append({"symbol":symbol,"signal_bar_time":signal.isoformat(),"equal":True})
        print(f"VERIFIED {symbol}: {len(report['trades'])} baseline entries",flush=True)
    (run/"all_entry_parity_verification.json").write_text(json.dumps({"status":"PASS","frozen_hashes_verified":True,"baseline_entries_verified":len(checks),"checks":checks,"edge_proven":False},indent=2),encoding="utf-8")


if __name__=="__main__": main()
