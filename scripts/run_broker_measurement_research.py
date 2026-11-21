"""Broker tick-volume exploratory replay, isolated from HistData and live state."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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
from pragma.data.mt5_data import MT5DataClient, filter_closed_bars
from pragma.data.clock_alignment import observed_offset_seconds
from pragma.backtest_engine import run_backtest
from pragma.measurement import ExecutionCosts, evaluate_prefix
from pragma.research_measurement import finite_json, replay_fixed_entries, horizon_diagnostics, weekly_bootstrap


def save(path, data):
    path.write_text(json.dumps(finite_json(data), indent=2, allow_nan=False), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def research_client(terminal_path=None):
    """Bind this research IPC connection to an explicit existing terminal."""
    if terminal_path:
        import MetaTrader5 as mt5
        if not mt5.initialize(path=terminal_path, timeout=15000):
            raise RuntimeError(f"Explicit MT5 initialize failed: {mt5.last_error()}")
        try:
            with MT5DataClient(mt5_module=mt5) as client:
                yield client
        finally:
            mt5.shutdown()
    else:
        with MT5DataClient() as client:
            yield client


def archived_quotes(path):
    if path is None:
        return {}, None
    source = Path(path).resolve()
    quotes = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("source") != "mt5" or not (float(row["bid"]) > 0 and float(row["ask"]) >= float(row["bid"])):
            raise ValueError("Invalid archived MT5 quote")
        quotes[row["symbol"]] = row
    return quotes, {"path": str(source), "sha256": sha(source),
                    "usage": "EXPLICIT_ARCHIVED_SPREAD_SCENARIO_NOT_HISTORICAL_CALIBRATION"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--bars", type=int, default=30000)
    parser.add_argument("--terminal-path", help="Explicit existing MT5 terminal executable; no login/account switch")
    parser.add_argument("--quote-archive", help="Explicit MT5 quote JSONL for a closed-market spread SCENARIO")
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    freeze = out/"frozen"
    freeze.mkdir()
    symbols = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD", "CADCHF", "CADJPY", "EURGBP", "GBPCHF", "GBPJPY"]
    inputs = []
    code = sorted(list((ROOT/"pragma").rglob("*.py")) + list((ROOT/"config").glob("*.py")) + [Path(__file__).resolve()])
    for path in code:
        target = freeze/path.relative_to(ROOT)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
        inputs.append({"path":str(path.relative_to(ROOT)),"sha256":sha(target)})
    captured = {}
    failures = {}
    quotes, quote_source = archived_quotes(args.quote_archive)
    if args.quote_archive:
        shutil.copy2(args.quote_archive, freeze/"spread_quotes.jsonl")
    with research_client(args.terminal_path) as client:
        offset = observed_offset_seconds(client.mt5)
        for symbol in symbols:
            try:
                now = pd.Timestamp.now(tz="UTC")
                if args.quote_archive:
                    quote = quotes[symbol]
                    bid, ask = float(quote["bid"]), float(quote["ask"])
                    quote_time = pd.Timestamp(quote["quote_time"])
                    spread_source = "EXPLICIT_ARCHIVED_QUOTE_SCENARIO"
                else:
                    tick = client.mt5.symbol_info_tick(symbol)
                    quote_time = pd.to_datetime(tick.time_msc,unit="ms",utc=True)-pd.Timedelta(seconds=offset)
                    bid, ask = float(tick.bid), float(tick.ask)
                    if bid <= 0 or ask < bid or abs((now-quote_time).total_seconds()) > 60:
                        raise ValueError("No fresh bid/ask; historical replay can use an explicitly declared --quote-archive scenario")
                    spread_source = "CURRENT_QUOTE_SCENARIO"
                bars = filter_closed_bars(client.rates(symbol,"M1",args.bars),"M1",now=now)
                if len(bars) < args.bars*0.9:
                    raise ValueError(f"Insufficient history: {len(bars)}")
                path=freeze/f"{symbol}_bid_M1.csv"
                bars.to_csv(path,index_label="time")
                # Bid OHLC -> assumed midpoint using a FIXED observed spread.
                # This makes half-spread charges symmetric; it does not assert
                # that the historical spread was constant or measured.
                half=(ask-bid)/2
                captured[symbol]={"path":path.name,"sha256":sha(path),"bars":len(bars),
                                  "half_spread_assumed":half,"bid":bid,"ask":ask,
                                  "spread_source":spread_source,
                                  "quote_time":quote_time.isoformat(),"clock_offset_seconds":offset,
                                  "start":bars.index[0].isoformat(),"end":bars.index[-1].isoformat()}
                print(f"CAPTURED {symbol}: {len(bars)} broker tick-volume bars",flush=True)
            except Exception as exc:
                failures[symbol]=str(exc)
    protocol={"created_at":datetime.now(timezone.utc).isoformat(),"symbols":symbols,"timeframe":"M5",
              "terminal_path":args.terminal_path,"spread_quote_source":quote_source,
              "inputs":inputs,"captured":captured,"failures":failures,
              "cost_scenario":"Explicit observed/archived half-spread fixed across historical bid bars converted to assumed mid + ASSUMED 1bps commission and 0.5bps slippage per side; no swap data",
              "commission_calibrated":False,"historical_spread_calibrated":False,"swap_calibrated":False,
              "historical_clock_mapping_independently_verified":False,
              "classification":"EXPLORATORY_NOT_OOS_OR_MEASURED_NET_EVIDENCE",
              "trials":["baseline","last_bar_touch","cost_stress_1_5","no_be_fixed_entries"],
              "macro":"auto price regime, no vintage macro claim",
              "entry_quality":"5/15/30 minute net scenario bps and previous-week same-clock reference",
              "edge_proven":False,"live_execution":False}
    save(out/"protocol_frozen.json",protocol)
    (out/"protocol.sha256").write_text(sha(out/"protocol_frozen.json"),encoding="ascii")
    summary=[]
    for symbol,capture in captured.items():
        path=freeze/capture["path"]
        if sha(path)!=capture["sha256"]: raise ValueError("Input hash mismatch")
        bars=pd.read_csv(path,index_col="time",parse_dates=True)
        bars.index=pd.DatetimeIndex(pd.to_datetime(bars.index,utc=True))
        bars[["open","high","low","close"]]+=capture["half_spread_assumed"]
        bars.attrs.update(source="mt5",volume_semantics="BROKER_TICK_COUNT")
        cost=ExecutionCosts(fixed_per_side=capture["half_spread_assumed"],commission_bps=1,slippage_bps=.5,
                            provenance="ASSUMED_SCENARIO_SWAP_MISSING_NOT_NET_EVIDENCE")
        candidates=[]
        samples=[]
        def candidate(stamp,poi,decision,atr,veto):
            if decision.execute or decision.metrics.get("poi_touched"):
                candidates.append({"signal_bar_time":stamp.isoformat(),"direction":poi.direction,
                                   "reason":decision.reason,"eligible":decision.execute and not veto,
                                   "poi_type":poi.poi_type})
        def observed(snapshot):
            if snapshot["pois"] and len(samples)<5: samples.append(snapshot)
        results={}
        for name,c,touch in [("baseline",cost,3),("last_bar_touch",cost,1),("cost_stress_1_5",cost.stressed(1.5),3)]:
            print(f"RUN {symbol} {name}",flush=True)
            report=run_backtest(bars,symbol=symbol,macro_bias="auto",allow_range=True,trigger_tf="M5",costs=c,touch_bars=touch,
                                candidate_observer=candidate if name=="baseline" else None,
                                decision_observer=observed if name=="baseline" else None)
            results[name]=report
            save(out/f"{symbol}_{name}.json",report.to_dict())
        parity=[]
        for expected in samples:
            actual=evaluate_prefix(bars.loc[:pd.Timestamp(expected["signal_bar_time"])],symbol=symbol,macro_bias="auto",allow_range=True,trigger_tf="M5",costs=cost)
            parity.append({"signal_bar_time":expected["signal_bar_time"],"equal":json.loads(json.dumps(expected))==json.loads(json.dumps(actual))})
        if any(not p["equal"] for p in parity): raise ValueError("Broker replay/observer parity mismatch")
        save(out/f"{symbol}_parity.json",parity)
        baseline=results["baseline"].trades
        replay=replay_fixed_entries(bars,baseline,cost,be_offset_r=0)
        if any(abs(a["r_multiple"]-b["r_multiple"])>1e-10 for a,b in zip(baseline,replay)):
            raise ValueError("Fixed-entry parity mismatch")
        no_be=replay_fixed_entries(bars,baseline,cost,be_offset_r=None)
        save(out/f"{symbol}_no_be_fixed_entries.json",no_be)
        deltas=[{"entry_time":a["entry_time"],"r_multiple":b["r_multiple"]-a["r_multiple"]} for a,b in zip(baseline,no_be)
                if a["exit_reason"]!="END_OF_DATA" and b["exit_reason"]!="END_OF_DATA"]
        quality,eligible,rejected=horizon_diagnostics(bars,candidates,cost)
        for name,rows in [("entry_quality",eligible),("rejected_counterfactuals",rejected)]:
            with (out/f"{symbol}_{name}.jsonl").open("w",encoding="utf-8") as stream:
                for row in rows: stream.write(json.dumps(finite_json(row),allow_nan=False)+"\n")
        summary.append({"symbol":symbol,"trials":{name:{"scenario_r":r.net_r,"n":r.total_trades,"closed":weekly_bootstrap([t for t in r.trades if t["exit_reason"]!="END_OF_DATA"])} for name,r in results.items()},
                        "no_be_paired_delta":weekly_bootstrap(deltas),"entry_quality":quality,
                        "parity_checks":len(parity),"edge_proven":False})
        save(out/"summary.json",summary)
        print(f"DONE {symbol}",flush=True)
    for row in inputs:
        if sha(ROOT/row["path"])!=row["sha256"]: raise ValueError("Source changed; experiment invalid")
    save(out/"completion.json",{"status":"COMPLETE" if not failures else "INCOMPLETE_SYMBOLS","source_hashes_unchanged":True,"edge_proven":False,
                                 "protocol_sha256":sha(out/"protocol_frozen.json"),"failed_symbols":failures})


if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        # Keep data-capture and validation failures reviewable, including when
        # terminal authorization fails before a protocol can be frozen.
        if "--output" in sys.argv:
            output = Path(sys.argv[sys.argv.index("--output")+1]).resolve()
            if output.exists() and not (output/"completion.json").exists():
                save(output/"completion.json", {"status":"INCOMPLETE", "error":f"{type(exc).__name__}: {exc}", "edge_proven":False})
        raise
