"""Forward-only FX entry/quote observer. No orders, Telegram or legacy state.

Late observations never receive backdated paper fills. Closed-market quotes
are blocked. Pending confirmation and fixed-horizon quote observations are
persisted so restarting the observer cannot invent completed outcomes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from pragma.measurement import ExecutionCosts, evaluate_prefix
from pragma.entry_hypotheses import entry_variant
from pragma.cost_evidence import quoted_outcome
from pragma.data.mt5_data import filter_closed_bars
from pragma.data.clock_alignment import observed_offset_seconds
from scripts.run_broker_measurement_research import research_client


def append(path,row):
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,allow_nan=False)+'\n')


def timely_quote(bid,ask,quote_time,now,event, *, max_delay=30):
    values=(float(bid),float(ask))
    return bool(all(math.isfinite(v) for v in values) and 0<values[0]<=values[1] and 0<=(now-quote_time).total_seconds()<=5
                and event<=quote_time<=now and 0<=(now-event).total_seconds()<=max_delay)


def state_fingerprint(manifest):
    keys=('script_sha256','decision_code_sha256','study_protocol_sha256','baseline_protocol_sha256','entry_deadline_seconds','quote_max_age_seconds')
    return hashlib.sha256(json.dumps({k:manifest[k] for k in keys},sort_keys=True).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',required=True)
    parser.add_argument('--cost-study',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--terminal-path',required=True)
    parser.add_argument('--cycles',type=int,default=1)
    parser.add_argument('--poll-seconds',type=float,default=10)
    args=parser.parse_args()
    if args.cycles<0 or args.poll_seconds<1:parser.error('Invalid cycles/poll interval')
    source=Path(args.baseline).resolve();study=Path(args.cost_study).resolve();out=Path(args.output).resolve()
    out.mkdir(parents=True,exist_ok=True)
    baseline=json.loads((source/'protocol_frozen.json').read_text(encoding='utf-8'))
    completion=json.loads((study/'completion.json').read_text(encoding='utf-8'))
    if completion['status']!='COMPLETE':raise ValueError('Completed historical entry study required')
    variants=('baseline','directional_body_half','delay_one_m5_break')
    costs={s:ExecutionCosts(**json.loads((source/f'{s}_baseline.json').read_text(encoding='utf-8'))['measurement']['costs']) for s in baseline['symbols']}
    manifest={'started_at':datetime.now(timezone.utc).isoformat(),'symbols':baseline['symbols'],
              'study_protocol_sha256':completion['protocol_sha256'],
              'baseline_protocol_sha256':hashlib.sha256((source/'protocol_frozen.json').read_bytes()).hexdigest(),
              'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'decision_code_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'pragma').rglob('*.py')},
              'entry_deadline_seconds':30,'quote_max_age_seconds':5,'history_bars':12000,
              'source':'MT5_EXPLICIT_BROKER_TERMINAL','terminal_path':args.terminal_path,
              'quote_proxy_only':True,'actual_fills':False,'fully_net_returns':False,
              'cost_policy':'Historical baseline gates fixed; observed live bid/ask for proxy outcomes; cost-study fee samples referenced, no invented fees/slippage/swap',
              'live_execution':False,'notifications':False,'edge_proven':False}
    manifest_name=f'manifest_{time.time_ns()}.json';(out/manifest_name).write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    state_path=out/'state.json'
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'processed':{},'pending':[],'open_observations':[]}
    fingerprint=state_fingerprint(manifest)
    if state.get('contract_fingerprint') not in (None,fingerprint):
        raise ValueError('Forward state belongs to different code/protocol; use a separate output folder')
    if state.get('contract_fingerprint') is None and (state['pending'] or state['open_observations']):
        raise ValueError('Forward pending state has no protocol provenance; do not reinterpret it')
    state['contract_fingerprint']=fingerprint
    cycle=0
    while args.cycles==0 or cycle<args.cycles:
        cycle+=1;fresh=0;stale=0;errors=[]
        try:
            with research_client(args.terminal_path) as client:
                offset=observed_offset_seconds(client.mt5)
                for symbol in baseline['symbols']:
                    try:
                        now=pd.Timestamp.now(tz='UTC');tick=client.mt5.symbol_info_tick(symbol)
                        if tick is None:raise ValueError('No quote')
                        quote_time=pd.to_datetime(tick.time_msc,unit='ms',utc=True)-pd.Timedelta(seconds=offset)
                        if not 0<=(now-quote_time).total_seconds()<=5 or not 0<tick.bid<=tick.ask:
                            stale+=1;continue
                        fresh+=1;quote={'bid':float(tick.bid),'ask':float(tick.ask),'time':quote_time.isoformat()}
                        append(out/'quotes.jsonl',{'observed_at':now.isoformat(),'symbol':symbol,**quote,'actual_fill':False})
                        # Outcomes use the first CURRENT quote observed after
                        # each real observation horizon; never retrospective ticks.
                        for obs in list(state['open_observations']):
                            if obs['symbol']!=symbol:continue
                            due=pd.Timestamp(obs['entry_observed_at'])+pd.Timedelta(minutes=obs['horizon_minutes'])
                            if now<due:continue
                            valid=timely_quote(tick.bid,tick.ask,quote_time,now,due)
                            if not valid and (now-due).total_seconds()<=30:continue
                            outcome=quoted_outcome(obs['direction'],obs['entry_quote'],quote) if valid else None
                            append(out/'outcomes.jsonl',dict(obs,exit_observed_at=now.isoformat(),exit_quote=quote if valid else None,
                                   observation=outcome,status='QUOTE_PROXY_COMPLETE' if valid else 'MISSED_EXIT_DEADLINE',actual_fill=False))
                            state['open_observations'].remove(obs)
                        boundary=now.floor('5min')
                        need_history=(now-boundary).total_seconds()<=30 and state['processed'].get(symbol)!=boundary.isoformat()
                        pending=[p for p in state['pending'] if p['symbol']==symbol and pd.Timestamp(p['due'])<=now]
                        if not need_history and not pending:continue
                        bars=filter_closed_bars(client.rates(symbol,'M1',12000),'M1',now=now)
                        bars=bars.copy();bars[['open','high','low','close']]+=baseline['captured'][symbol]['half_spread_assumed']
                        def open_observation(case,event):
                            observed=pd.Timestamp.now(tz='UTC'); current=client.mt5.symbol_info_tick(symbol)
                            qtime=pd.to_datetime(current.time_msc,unit='ms',utc=True)-pd.Timedelta(seconds=offset)
                            valid=timely_quote(current.bid,current.ask,qtime,observed,event)
                            entry_price=float(current.ask) if case['direction']=='LONG' else float(current.bid)
                            geometry=(case['stop']<entry_price<case['tp1']<=case['tp2']) if case['direction']=='LONG' else (case['stop']>entry_price>case['tp1']>=case['tp2'])
                            valid=valid and geometry
                            q={'time':qtime.isoformat(),'bid':float(current.bid),'ask':float(current.ask)}
                            append(out/'selections.jsonl',dict(case,entry_observed_at=observed.isoformat(),entry_quote=q if valid else None,
                                   forward_entry_eligible=valid,quote_geometry_valid=bool(geometry),manifest=manifest_name,actual_fill=False))
                            if valid:
                                for h in (5,15,30):state['open_observations'].append(dict(case,entry_quote=q,entry_observed_at=observed.isoformat(),horizon_minutes=h))
                        for case in pending:
                            due=pd.Timestamp(case['due'])
                            if now>due+pd.Timedelta(seconds=30):
                                append(out/'selections.jsonl',dict(case,accepted=False,reason='MISSED_CONFIRMATION_DEADLINE',forward_entry_eligible=False))
                            elif bars.index[-1]+pd.Timedelta(minutes=1)<due:
                                continue
                            else:
                                decision=entry_variant(bars,pd.Timestamp(case['signal_bar_time']),case['direction'],case['stop'],case['tp1'],'delay_one_m5_break')
                                item=dict(case,**decision)
                                if decision['accepted']:open_observation(item,due)
                                else:append(out/'selections.jsonl',dict(item,forward_entry_eligible=False))
                            state['pending'].remove(case)
                        if need_history:
                            snapshot=evaluate_prefix(bars,symbol=symbol,macro_bias='auto',allow_range=True,trigger_tf='M5',costs=costs[symbol])
                            decision_time=pd.Timestamp(snapshot['decision_time'])
                            if snapshot['veto']=='TRIGGER_NOT_CLOSED':continue
                            state['processed'][symbol]=boundary.isoformat()
                            append(out/'decisions.jsonl',dict(snapshot,observed_at=pd.Timestamp.now(tz='UTC').isoformat(),manifest=manifest_name,sample_kind='GENUINE_FORWARD_OBSERVER_NO_ORDERS'))
                            if snapshot['veto'] or now>decision_time+pd.Timedelta(seconds=30):continue
                            for d in snapshot['triggers']:
                                if not d['execute']:continue
                                base={'symbol':symbol,'signal_bar_time':snapshot['signal_bar_time'],'direction':d['direction'],
                                      'poi_type':d['poi_type'],'stop':d['stop_loss'],'tp1':d['take_profit_1'],'tp2':d['take_profit_2']}
                                for variant in variants[:2]:
                                    selection=entry_variant(bars,pd.Timestamp(snapshot['signal_bar_time']),d['direction'],d['stop_loss'],d['take_profit_1'],variant)
                                    case=dict(base,variant=variant,**selection)
                                    if selection['accepted']:open_observation(case,decision_time)
                                    else:append(out/'selections.jsonl',dict(case,forward_entry_eligible=False))
                                state['pending'].append(dict(base,variant='delay_one_m5_break',due=(decision_time+pd.Timedelta(minutes=5)).isoformat()))
                    except Exception as exc:errors.append({'symbol':symbol,'error':f'{type(exc).__name__}: {exc}'})
        except Exception as exc:errors.append({'source':'mt5','error':f'{type(exc).__name__}: {exc}'})
        # Missing/stale market data still expires observations; it is never
        # turned into a flat or winning paper trade on Monday/restart.
        now=pd.Timestamp.now(tz='UTC')
        for obs in list(state['open_observations']):
            due=pd.Timestamp(obs['entry_observed_at'])+pd.Timedelta(minutes=obs['horizon_minutes'])
            if now>due+pd.Timedelta(seconds=30):
                append(out/'outcomes.jsonl',dict(obs,status='MISSED_EXIT_NO_FRESH_DATA',observation=None,actual_fill=False));state['open_observations'].remove(obs)
        for case in list(state['pending']):
            if now>pd.Timestamp(case['due'])+pd.Timedelta(seconds=30):
                append(out/'selections.jsonl',dict(case,accepted=False,reason='MISSED_CONFIRMATION_NO_FRESH_DATA',forward_entry_eligible=False));state['pending'].remove(case)
        status={'observed_at':now.isoformat(),'fresh_symbols':fresh,'stale_or_closed_symbols':stale,'errors':errors,
                'pending':len(state['pending']),'open_quote_observations':len(state['open_observations']),
                'status':'WAITING_FOR_FRESH_MARKET' if stale and not fresh and not errors else ('SOURCE_ERROR' if errors else 'OBSERVING'),
                'live_execution':False,'edge_proven':False}
        (out/'status.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
        temp=out/'state.tmp';temp.write_text(json.dumps(state,indent=2),encoding='utf-8');temp.replace(state_path)
        print(f"{now.isoformat()} {status['status']} fresh={fresh} closed={stale} errors={len(errors)}",flush=True)
        if args.cycles==0 or cycle<args.cycles:time.sleep(args.poll_seconds)


if __name__=='__main__':main()
