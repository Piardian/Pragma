import unittest
import pandas as pd
from pragma.cost_evidence import deal_cost_profiles, select_quote, quoted_outcome, fee_price_proxy
from pragma.entry_hypotheses import entry_variant
from scripts.attribute_entry_timing import components


class CostEvidenceTests(unittest.TestCase):
    def test_entry_delay_is_separated_from_shifted_exit_clock(self):
        base={'entry_quote':{'bid':99.,'ask':101.},'exit_quote':{'bid':109.,'ask':111.}}
        delayed={'entry_quote':{'bid':104.,'ask':106.},'exit_quote':{'bid':114.,'ask':116.}}
        row=components(base,delayed,'LONG')
        self.assertEqual(row['same_original_exit_entry_change_bps'],-500.)
        self.assertEqual(row['shifted_exit_clock_change_bps'],500.)
        self.assertEqual(row['equal_holding_period_total_change_common_denominator_bps'],0.)

    def test_empty_history_is_missing_not_zero(self):
        p=deal_cost_profiles([],['EURUSD'])['EURUSD']
        self.assertIsNone(p['observed_fee_debit_per_lot_side'])
        self.assertFalse(p['fee_proxy_usable'])

    def test_complete_positions_required_and_credits_not_used_as_savings(self):
        rows=[]
        for i in range(3):
            for entry in (0,1):
                rows.append(dict(symbol='EURUSD',type=entry,entry=entry,volume=1.,position_key=str(i),commission=-2.,fee=1.,swap=0.))
        rows.append(dict(symbol='EURUSD',type=0,entry=0,volume=100.,position_key='incomplete',commission=-1000.,fee=0.,swap=0.))
        p=deal_cost_profiles(rows,['EURUSD'])['EURUSD']
        self.assertEqual(p['complete_positions'],3)
        self.assertEqual(p['observed_fee_debit_per_lot_side'],2.)
        self.assertTrue(p['fee_proxy_usable'])
        self.assertFalse(p['full_cost_calibrated'])

    def test_quote_delay_and_invalid_crossed_quotes(self):
        event=pd.Timestamp('2026-10-01T08:00Z')
        ticks=pd.DataFrame({'bid':[100,101,102],'ask':[99,102,103]},index=[event,event+pd.Timedelta(seconds=1),event+pd.Timedelta(seconds=3)])
        self.assertEqual(select_quote(ticks,event)['delay_seconds'],1.)
        self.assertIsNone(select_quote(ticks.iloc[2:],event))

    def test_bid_ask_side_cost_is_directionally_correct(self):
        entry={'bid':99.,'ask':101.};exit={'bid':109.,'ask':111.}
        a=quoted_outcome('LONG',entry,exit)
        b=quoted_outcome('SHORT',entry,exit)
        self.assertAlmostEqual(a['quoted_spread_only_bps'],800.)
        self.assertAlmostEqual(b['quoted_spread_only_bps'],-1200.)
        self.assertIsNone(a['known_cost_subtotal_bps'])
        self.assertIsNone(a['fully_net_bps'])
        c=quoted_outcome('LONG',entry,exit,1.,1.)
        self.assertAlmostEqual(c['known_cost_subtotal_bps'],600.)

    def test_fee_conversion_never_uses_current_or_future_fx_rate(self):
        p={'EURGBP':{'fee_proxy_usable':True,'observed_fee_debit_per_lot_side':2.}}
        specs={'EURGBP':{'trade_contract_size':100000}}
        stamp=pd.Timestamp('2026-10-01T08:00Z')
        bars={'GBPUSD':pd.DataFrame({'open':[1.25]},index=[stamp])}
        self.assertAlmostEqual(fee_price_proxy('EURGBP',stamp,specs,p,bars,'USD'),2/125000)
        self.assertIsNone(fee_price_proxy('EURGBP',stamp-pd.Timedelta(minutes=1),specs,p,bars,'USD'))


class EntryHypothesesTests(unittest.TestCase):
    def setUp(self):
        self.ix=pd.date_range('2026-10-01T08:00Z',periods=10,freq='min')
        self.bars=pd.DataFrame({'open':100.,'high':102.,'low':99.,'close':101.,'tick_volume':10.},index=self.ix)
        self.signal=self.ix[4]

    def test_body_threshold_uses_only_closed_signal(self):
        a=entry_variant(self.bars,self.signal,'LONG',95,110,'directional_body_half')
        changed=self.bars.copy();changed.loc[self.ix[5]:,'close']=1000
        b=entry_variant(changed,self.signal,'LONG',95,110,'directional_body_half')
        self.assertEqual(a,b)
        self.assertFalse(a['accepted'])

    def test_body_half_boundary(self):
        self.bars.loc[self.signal,'close']=101.5
        a=entry_variant(self.bars,self.signal,'LONG',95,110,'directional_body_half')
        self.assertTrue(a['accepted'])
        self.assertEqual(pd.Timestamp(a['entry_time']),self.ix[5])

    def test_delay_requires_confirmation_and_uses_later_entry(self):
        self.bars.loc[self.ix[-1],'close']=103
        self.bars.loc[self.ix[-1],'high']=103
        a=entry_variant(self.bars,self.signal,'LONG',95,110,'delay_one_m5_break')
        self.assertTrue(a['accepted'])
        self.assertEqual(pd.Timestamp(a['entry_time']),self.ix[0]+pd.Timedelta(minutes=10))

    def test_stop_or_target_before_delayed_entry_cancels(self):
        self.bars.loc[self.ix[-1],'close']=103
        self.bars.loc[self.ix[6],'low']=94
        a=entry_variant(self.bars,self.signal,'LONG',95,110,'delay_one_m5_break')
        self.assertFalse(a['accepted'])
        self.assertEqual(a['reason'],'STOP_OR_TARGET_BEFORE_DELAYED_ENTRY')

    def test_missing_confirmation_is_not_interpolated(self):
        a=entry_variant(self.bars.drop(self.ix[7]),self.signal,'LONG',95,110,'delay_one_m5_break')
        self.assertEqual(a['reason'],'MISSING_CONFIRMATION_MINUTES')


if __name__=='__main__':unittest.main()
