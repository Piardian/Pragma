"""Read-only order/deal matching against a pre-order broker quote.

This measures a SERVER-side execution proxy, not client decision-to-fill
slippage. It never substitutes for missing Pragma requested-price evidence.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from scripts.run_broker_measurement_research import research_client
from pragma.data.clock_alignment import observed_offset_seconds


def pre_order_quote(frame,event):
    if frame.empty:return None
    valid=frame.loc[(frame.index<=event)&(frame.index>=event-pd.Timedelta(seconds=1))]
    valid=valid.loc[np.isfinite(valid.bid)&np.isfinite(valid.ask)&(valid.bid>0)&(valid.ask>=valid.bid)]
    if valid.empty:return None
    row=valid.sort_index(kind='stable').iloc[-1]
    return {'time':row.name.isoformat(),'bid':float(row.bid),'ask':float(row.ask)}


def slippage_bps(side,fill_price,quote):
    reference=(quote['bid']+quote['ask'])/2
    return ((fill_price-quote['ask']) if side==0 else (quote['bid']-fill_price))/reference*10000


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--study',required=True);parser.add_argument('--terminal-path',required=True);args=parser.parse_args()
    root=Path(args.study);protocol=json.loads((root/'protocol_frozen.json').read_text(encoding='utf-8'));symbols=protocol['symbols']
    records=[]
    with research_client(args.terminal_path) as client:
        offset=observed_offset_seconds(client.mt5)
        begin=datetime(2026,9,23,tzinfo=timezone.utc);end=datetime.now(timezone.utc)
        orders=client.mt5.history_orders_get(begin,end);deals=client.mt5.history_deals_get(begin,end)
        if orders is None or deals is None:raise ValueError('Order/deal history unavailable; do not impute zero slippage')
        lookup={o.ticket:o for o in orders}
        for deal in deals:
            if deal.symbol not in symbols or deal.type not in (0,1) or deal.volume<=0:continue
            record={'symbol':deal.symbol,'entry_kind':deal.entry,
                    'execution_key':hashlib.sha256((root.name+str(deal.ticket)).encode()).hexdigest()}
            order=lookup.get(deal.order)
            if order is None or order.type not in (0,1):
                records.append(dict(record,status='NO_MATCHED_MARKET_ORDER'));continue
            setup=pd.to_datetime(order.time_setup_msc,unit='ms',utc=True)-pd.Timedelta(seconds=offset)
            fill=pd.to_datetime(deal.time_msc,unit='ms',utc=True)-pd.Timedelta(seconds=offset)
            latency=(fill-setup).total_seconds()
            if not 0<=latency<=30:
                records.append(dict(record,status='INVALID_OR_LONG_SERVER_TIMING',server_latency_seconds=latency));continue
            if observed_offset_seconds(client.mt5)!=offset:raise ValueError('Clock changed')
            raw=client.mt5.copy_ticks_range(deal.symbol,(setup-pd.Timedelta(seconds=2)+pd.Timedelta(seconds=offset)).to_pydatetime(),
                                           (setup+pd.Timedelta(milliseconds=1)+pd.Timedelta(seconds=offset)).to_pydatetime(),client.mt5.COPY_TICKS_ALL)
            quote=None;proof={}
            if raw is not None and len(raw):
                frame=pd.DataFrame(raw);frame.index=pd.DatetimeIndex(pd.to_datetime(frame.time_msc,unit='ms',utc=True))-pd.Timedelta(seconds=offset)
                target=root/'ticks'/f"slippage_{deal.symbol}_{setup.strftime('%Y%m%dT%H%M%S%f')}.csv"
                frame.to_csv(target,index_label='normalized_time')
                proof={'path':str(target.relative_to(root)),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
                quote=pre_order_quote(frame,setup)
            if quote is None:
                records.append(dict(record,status='MISSING_PRE_ORDER_QUOTE',**proof));continue
            signed=slippage_bps(deal.type,float(deal.price),quote)
            records.append(dict(record,status='SERVER_QUOTE_PROXY',setup_time=setup.isoformat(),fill_time=fill.isoformat(),
                                side='BUY' if deal.type==0 else 'SELL',fill_price=float(deal.price),quote=quote,
                                server_latency_seconds=latency,signed_slippage_proxy_bps=signed,
                                adverse_only_proxy_bps=max(signed,0.),**proof))
    summary=[]
    for symbol in symbols:
        rows=[r for r in records if r['symbol']==symbol];matched=[r for r in rows if r['status']=='SERVER_QUOTE_PROXY']
        values=[r['adverse_only_proxy_bps'] for r in matched]
        summary.append({'symbol':symbol,'trade_legs':len(rows),'matched':len(values),'missing':len(rows)-len(values),
                        'adverse_only_mean_bps':float(np.mean(values)) if values else None,
                        'adverse_only_p90_bps':float(np.quantile(values,.9)) if values else None,
                        'client_decision_to_fill_slippage_bps':None,'full_slippage_calibrated':False})
    result={'classification':'POSTHOC_SERVER_ORDER_TO_DEAL_QUOTE_PROXY_NOT_CLIENT_SLIPPAGE',
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'used_in_frozen_entry_study':False,'actual_Pragma_fill_sample':False,
            'limitations':['No client intent/request quote archive','Account trades may be other strategies','Pre-order tick granularity and same-millisecond ordering are uncertain','Small and incomplete sample','Adverse-only costs do not use favorable fills as savings'],
            'summary':summary,'records':records,'edge_proven':False}
    (root/'broker_slippage_proxy_posthoc.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print('Observed matched server quote proxies:',sum(r['matched'] for r in summary),'of',len(records),'trade legs',flush=True)


if __name__=='__main__':main()
