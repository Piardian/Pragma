import unittest
import pandas as pd
from scripts.measure_broker_slippage_proxy import pre_order_quote,slippage_bps


class BrokerSlippageProxyTests(unittest.TestCase):
    def test_benchmark_is_pre_order_not_future_or_stale(self):
        event=pd.Timestamp('2026-10-01T08:00Z')
        rows=pd.DataFrame({'bid':[99.,100.,110.],'ask':[100.,101.,111.]},index=[event-pd.Timedelta(seconds=2),event-pd.Timedelta(milliseconds=100),event+pd.Timedelta(milliseconds=1)])
        self.assertEqual(pre_order_quote(rows,event)['bid'],100.)
        self.assertIsNone(pre_order_quote(rows.iloc[:1],event))
        self.assertIsNone(pre_order_quote(rows.iloc[2:],event))

    def test_fill_side_is_compared_with_correct_quote(self):
        quote={'bid':99.,'ask':101.}
        self.assertEqual(slippage_bps(0,102.,quote),100.)
        self.assertEqual(slippage_bps(1,98.,quote),100.)
        self.assertEqual(slippage_bps(0,100.,quote),-100.)


if __name__=='__main__':unittest.main()
