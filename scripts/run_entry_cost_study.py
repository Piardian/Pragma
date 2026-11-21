"""Frozen entry-quality study using historical bid/ask and account fee evidence."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from pragma.cost_evidence import deal_cost_profiles, select_quote, quoted_outcome, fee_price_proxy
from pragma.entry_hypotheses import entry_variant
from pragma.measurement import ExecutionCosts, evaluate_prefix
from pragma.research_measurement import finite_json, weekly_bootstrap
from pragma.data.clock_alignment import observed_offset_seconds
from scripts.run_broker_measurement_research import research_client


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value): path.write_text(json.dumps(finite_json(value),indent=2,allow_nan=False),encoding="utf-8")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",required=True)
    parser.add_argument("--output",required=True)
    parser.add_argument("--terminal-path",required=True)
    args=parser.parse_args()
    source=Path(args.baseline).resolve(); out=Path(args.output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    frozen=out/"frozen"; frozen.mkdir()
    original=json.loads((source/"protocol_frozen.json").read_text(encoding="utf-8"))
    symbols=original["symbols"]
    variants=("baseline","directional_body_half","delay_one_m5_break")
    inputs=[]
    paths=sorted(list((ROOT/"pragma").rglob("*.py"))+list((ROOT/"config").glob("*.py"))+[Path(__file__).resolve(),ROOT/"scripts/run_broker_measurement_research.py",source/"protocol_frozen.json"])
    for symbol in symbols:
        paths += [source/"frozen"/original["captured"][symbol]["path"],source/f"{symbol}_baseline.json",source/f"{symbol}_entry_quality.jsonl"]
    for path in paths:
        relative=path.relative_to(ROOT); target=frozen/relative
        target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,target)
        inputs.append({"path":str(relative),"sha256":sha(target)})
    protocol={"created_at":datetime.now(timezone.utc).isoformat(),"symbols":symbols,
              "classification":"EXPLORATORY_REUSED_HISTORY_NOT_OOS","source_protocol_sha256":sha(source/"protocol_frozen.json"),
              "variants":list(variants),"definitions":{
                  "baseline":"All unique executable pre-occupancy candidates of the frozen baseline; existing cost gate remains unchanged",
                  "directional_body_half":"Only signal M5 directional real body >=50% of its full range; no new levels or time delay",
                  "delay_one_m5_break":"Wait exactly one complete M5; require its close beyond original signal high/low in direction; cancel if original SL or TP1 touched during wait; then first eligible quote",
              },"horizons_minutes":[5,15,30],"primary_horizon_minutes":15,
              "quote_proxy":"First valid historical quote at/after event, maximum 2 seconds delay; opposite bid/ask for exit; NOT an actual fill",
              "cost_policy":"Observed spreads; per-lot fee proxy only from >=3 complete account positions; no inferred zero fees; swap/slippage remain missing",
              "missing_policy":"Retain every selected/rejected/missing case and coverage counts; no filling absent quotes or fees; compare only common complete pairs and show loss of coverage",
              "reference":"Previous week same clock and direction; reference observed only when frozen history covers it",
              "unchanged":"No TP/SL, volume, session, macro, universe or live behavior changes",
              "acceptance":"No promotion; historical improvement with incomplete costs or short sample is not edge proof; no model selected by best return",
              "inputs":inputs,"edge_proven":False,"live_execution":False}
    save(out/"protocol_frozen.json",protocol)
    (out/"protocol.sha256").write_text(sha(out/"protocol_frozen.json"),encoding="ascii")
    bars={}; mids={}; candidates={}; reports={}
    for symbol in symbols:
        meta=original["captured"][symbol]
        path=frozen/(source/"frozen"/meta["path"]).relative_to(ROOT)
        frame=pd.read_csv(path,index_col="time",parse_dates=True)
        frame.index=pd.DatetimeIndex(pd.to_datetime(frame.index,utc=True))
        frame.attrs.update(source="mt5",volume_semantics="BROKER_TICK_COUNT")
        bars[symbol]=frame
        mid=frame.copy();mid[["open","high","low","close"]]+=meta["half_spread_assumed"];mids[symbol]=mid
        reports[symbol]=json.loads((frozen/(source/f"{symbol}_baseline.json").relative_to(ROOT)).read_text(encoding="utf-8"))
        unique={}
        for line in (frozen/(source/f"{symbol}_entry_quality.jsonl").relative_to(ROOT)).read_text(encoding="utf-8").splitlines():
            row=json.loads(line);unique[(row["signal_bar_time"],row["direction"],row["poi_type"])]=row
        candidates[symbol]=list(unique.values())
    ticks_dir=out/"ticks"; ticks_dir.mkdir()
    raw_deals=[]; results=[]; selections=[]; quote_events=[]; cache={}; specs={}
    with research_client(args.terminal_path) as client:
        offset=observed_offset_seconds(client.mt5)
        account=client.mt5.account_info(); currency=getattr(account,"currency",None)
        start=min(f.index[0] for f in bars.values())
        # Read one extra day for timestamp-boundary uncertainty, then explicitly
        # normalize/filter local evidence. Never export identifying trade fields.
        history=client.mt5.history_deals_get((start-pd.Timedelta(days=1)).to_pydatetime(),datetime.now(timezone.utc))
        history_available=history is not None
        for deal in history if history is not None else []:
            row=deal._asdict()
            stamp=pd.to_datetime(row.get("time_msc",row["time"]*1000),unit="ms",utc=True)-pd.Timedelta(seconds=offset)
            if row.get("symbol") not in symbols or stamp<start:
                continue
            raw_deals.append({"symbol":row["symbol"],"time":stamp.isoformat(),
                              "position_key":hashlib.sha256((out.name+str(row.get("position_id"))).encode()).hexdigest(),
                              **{k:row.get(k) for k in ("type","entry","volume","commission","fee","swap")}})
        profiles=deal_cost_profiles(raw_deals,symbols)
        for symbol in symbols:
            info=client.mt5.symbol_info(symbol)
            specs[symbol]={k:getattr(info,k,None) for k in ("point","trade_contract_size","swap_long","swap_short","swap_mode")}
        save(out/"account_cost_evidence.json",{"history_available":history_available,"account_currency":currency,
             "anonymous_trade_cost_records":raw_deals,"profiles":profiles,"specifications":specs,
             "scope":"Observed account sample, not Pragma strategy fills; swap specifications not historical accrual calibration",
             "slippage":None,"full_cost_calibrated":False})

        def quote(symbol,event):
            event=pd.Timestamp(event); key=(symbol,event.isoformat())
            if key in cache:return cache[key]
            frame=bars[symbol]
            if event.floor("min") not in frame.index:
                cache[key]=None;quote_events.append({"symbol":symbol,"event":event.isoformat(),"status":"OUTSIDE_FROZEN_HISTORY"});return None
            if observed_offset_seconds(client.mt5)!=offset:raise ValueError("CLOCK_CHANGED")
            raw=client.mt5.copy_ticks_range(symbol,(event-pd.Timedelta(seconds=2)+pd.Timedelta(seconds=offset)).to_pydatetime(),
                                           (event+pd.Timedelta(seconds=3)+pd.Timedelta(seconds=offset)).to_pydatetime(),client.mt5.COPY_TICKS_ALL)
            record={"symbol":symbol,"event":event.isoformat(),"rows":len(raw) if raw is not None else 0}
            selected=None
            if raw is not None and len(raw):
                ticks=pd.DataFrame(raw)
                ticks.index=pd.DatetimeIndex(pd.to_datetime(ticks.time_msc,unit="ms",utc=True))-pd.Timedelta(seconds=offset)
                ticks=ticks.sort_index(kind="stable")
                filename=f"{symbol}_{event.strftime('%Y%m%dT%H%M%S')}.csv"
                path=ticks_dir/filename;ticks.to_csv(path,index_label="normalized_time")
                record.update(path=str(path.relative_to(out)),sha256=sha(path))
                selected=select_quote(ticks,event)
                if selected:
                    minute=pd.Timestamp(selected["time"]).floor("min")
                    if minute not in frame.index: selected=None
                    else:
                        candle=frame.loc[minute]; tolerance=2*specs[symbol]["point"]
                        if not candle.low-tolerance<=selected["bid"]<=candle.high+tolerance:
                            record["status"]="TICK_BAR_BID_MISMATCH";selected=None
            record.setdefault("status","VALID_QUOTE_PROXY" if selected else "NO_VALID_QUOTE_WITHIN_2_SECONDS")
            quote_events.append(record);cache[key]=selected;return selected

        for symbol in symbols:
            print(f"ENTRY STUDY {symbol}: {len(candidates[symbol])} pre-occupancy candidates",flush=True)
            original_cost=ExecutionCosts(**reports[symbol]["measurement"]["costs"])
            for candidate in candidates[symbol]:
                signal=pd.Timestamp(candidate["signal_bar_time"])
                prefix=mids[symbol].loc[:signal]
                names=list(dict.fromkeys(prefix.index.strftime("%Y-%m-%d")))
                if len(names)>8:prefix=prefix.loc[prefix.index>=pd.Timestamp(names[-8],tz="UTC")]
                snapshot=evaluate_prefix(prefix,symbol=symbol,macro_bias="auto",allow_range=True,trigger_tf="M5",costs=original_cost)
                decisions=[d for d in snapshot["triggers"] if d["execute"] and d["direction"]==candidate["direction"] and d["poi_type"]==candidate["poi_type"]]
                if snapshot["veto"] or not decisions:raise ValueError("Frozen baseline candidate parity failed")
                decision=decisions[0]
                for variant in variants:
                    selection=entry_variant(mids[symbol],signal,candidate["direction"],decision["stop_loss"],decision["take_profit_1"],variant)
                    selection.update(symbol=symbol,signal_bar_time=signal.isoformat(),direction=candidate["direction"],poi_type=candidate["poi_type"],variant=variant)
                    selections.append(selection)
                    if not selection["accepted"]:continue
                    entry_time=pd.Timestamp(selection["entry_time"])
                    entry_quote=quote(symbol,entry_time)
                    entry_fee=fee_price_proxy(symbol,entry_time,specs,profiles,bars,currency)
                    for horizon in (5,15,30):
                        end_time=entry_time+pd.Timedelta(minutes=horizon)
                        exit_quote=quote(symbol,end_time)
                        exit_fee=fee_price_proxy(symbol,end_time,specs,profiles,bars,currency)
                        observed=quoted_outcome(candidate["direction"],entry_quote,exit_quote,entry_fee,exit_fee)
                        ref_entry=quote(symbol,entry_time-pd.Timedelta(days=7))
                        ref_exit=quote(symbol,end_time-pd.Timedelta(days=7))
                        reference=quoted_outcome(candidate["direction"],ref_entry,ref_exit)
                        row={**selection,"horizon_minutes":horizon,"entry_quote":entry_quote,"exit_quote":exit_quote,
                             "observation":observed,"missing_quote":observed is None,
                             "reference_available":reference is not None,
                             "paired_reference_excess_bps":observed["quoted_spread_only_bps"]-reference["quoted_spread_only_bps"] if observed and reference else None}
                        results.append(row)
            save(out/"selections.json",selections);save(out/"quote_events.json",quote_events);save(out/"observations.json",results)
    summaries=[]
    for symbol in symbols:
        for variant in variants:
            selection=[r for r in selections if r["symbol"]==symbol and r["variant"]==variant]
            horizons={}
            for horizon in (5,15,30):
                rows=[r for r in results if r["symbol"]==symbol and r["variant"]==variant and r["horizon_minutes"]==horizon]
                good=[dict(entry_time=r["entry_time"],r_multiple=r["observation"]["quoted_spread_only_bps"]) for r in rows if r["observation"]]
                known=[dict(entry_time=r["entry_time"],r_multiple=r["observation"]["known_cost_subtotal_bps"]) for r in rows if r["observation"] and r["observation"]["known_cost_subtotal_bps"] is not None]
                baseline={r["signal_bar_time"]:r for r in results if r["symbol"]==symbol and r["variant"]=="baseline" and r["horizon_minutes"]==horizon and r["observation"]}
                pairs=[dict(entry_time=r["entry_time"],r_multiple=r["observation"]["quoted_spread_only_bps"]-baseline[r["signal_bar_time"]]["observation"]["quoted_spread_only_bps"]) for r in rows if r["observation"] and r["signal_bar_time"] in baseline]
                baseline_mean=sum(r["observation"]["quoted_spread_only_bps"] for r in baseline.values())/len(baseline) if baseline else None
                selected_mean=sum(r["r_multiple"] for r in good)/len(good) if good else None
                horizons[str(horizon)]={"selected":len(rows),"quote_complete":len(good),"missing_quotes":len(rows)-len(good),
                                       "spread_only_bps":weekly_bootstrap(good),"known_cost_subtotal_bps":weekly_bootstrap(known),
                                       "paired_change_vs_baseline_bps":weekly_bootstrap(pairs),
                                       "conditional_mean_minus_all_baseline_mean_bps":selected_mean-baseline_mean if selected_mean is not None and baseline_mean is not None else None,
                                       "fully_net_bps":None}
            summaries.append({"symbol":symbol,"variant":variant,"candidate_count":len(selection),"accepted":sum(r["accepted"] for r in selection),"horizons":horizons})
    save(out/"summary.json",summaries)
    for row in inputs:
        if sha(ROOT/row["path"])!=row["sha256"] or sha(frozen/row["path"])!=row["sha256"]:raise ValueError("Input changed during study")
    save(out/"completion.json",{"status":"COMPLETE","source_hashes_verified":True,"protocol_sha256":sha(out/"protocol_frozen.json"),
                                 "baseline_candidates":sum(len(v) for v in candidates.values()),"quote_events":len(quote_events),
                                 "full_cost_calibrated":False,"edge_proven":False,"live_execution":False})
    print("COMPLETE",flush=True)


if __name__=="__main__":main()
