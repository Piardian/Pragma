"""Post-hoc timing attribution; no new trial or parameter selection."""
import argparse
import hashlib
import json
from pathlib import Path


def components(base, delayed, direction):
    """Use one original mid denominator and one shared original exit clock."""
    sign=1 if direction=='LONG' else -1
    reference=(base['entry_quote']['bid']+base['entry_quote']['ask'])/2
    key_entry='ask' if direction=='LONG' else 'bid'
    key_exit='bid' if direction=='LONG' else 'ask'
    original_entry=base['entry_quote'][key_entry]
    delayed_entry=delayed['entry_quote'][key_entry]
    original_exit=base['exit_quote'][key_exit]
    entry_change=sign*(original_entry-delayed_entry)/reference*10000
    exit_change=None
    if delayed.get('exit_quote'):
        exit_change=sign*(delayed['exit_quote'][key_exit]-original_exit)/reference*10000
    return {'same_original_exit_entry_change_bps':entry_change,
            'shifted_exit_clock_change_bps':exit_change,
            'equal_holding_period_total_change_common_denominator_bps':entry_change+exit_change if exit_change is not None else None}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('run');args=parser.parse_args();root=Path(args.run)
    rows=json.loads((root/'observations.json').read_text(encoding='utf-8'))
    def key(r):return (r['symbol'],r['signal_bar_time'],r['direction'],r['poi_type'])
    baseline={key(r):r for r in rows if r['variant']=='baseline' and r['horizon_minutes']==15}
    details=[];missing=[]
    for delayed in rows:
        if delayed['variant']!='delay_one_m5_break' or delayed['horizon_minutes']!=15:continue
        base=baseline.get(key(delayed))
        if not base or not base.get('entry_quote') or not base.get('exit_quote') or not delayed.get('entry_quote'):
            missing.append({'symbol':delayed['symbol'],'signal_bar_time':delayed['signal_bar_time']});continue
        details.append({'symbol':delayed['symbol'],'signal_bar_time':delayed['signal_bar_time'],**components(base,delayed,delayed['direction'])})
    summary=[]
    for symbol in sorted({r['symbol'] for r in rows}):
        selected=[r for r in details if r['symbol']==symbol]
        values=[r['same_original_exit_entry_change_bps'] for r in selected]
        summary.append({'symbol':symbol,'paired_cases':len(values),'mean_entry_only_change_bps':sum(values)/len(values) if values else None})
    result={'classification':'POSTHOC_DECOMPOSITION_NOT_ADDITIONAL_STRATEGY_TRIAL','script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope':'Spread-only quote proxies, same original exit clock and common original mid denominator; no complete fees/slippage/swap',
            'summary':summary,'details':details,'missing':missing,'edge_proven':False}
    (root/'timing_attribution_posthoc.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':main()
