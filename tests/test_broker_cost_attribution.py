import unittest
import pandas as pd
from scripts.attribute_broker_costs import attribute


class BrokerCostAttributionTests(unittest.TestCase):
    def setUp(self):
        self.bars=pd.DataFrame({"open":[100.,90.],"close":[101.,100.]},index=pd.date_range("2026-10-01T08:00Z",periods=2,freq="min"))
        self.trade={"fill_time":"2026-10-01T08:00:00+00:00","entry_time":"2026-10-01T08:00:00+00:00",
                    "exit_time":"2026-10-01T08:02:00+00:00","entry_price":100.2,"initial_stop_loss":95.,
                    "exit_reason":"TAKE_PROFIT_2","tp1_taken":True,"direction":"LONG","tp1":105.,"tp2":110.,
                    "r_multiple":1.,"funding_cost_r":.01}
        self.costs={"fixed_per_side":.1,"commission_bps":5.,"slippage_bps":5.}

    def test_partial_exits_pay_weighted_cost_not_two_full_exit_costs(self):
        row=attribute(self.trade,self.bars,self.costs)
        expected=(.2+(100+(.5*105+.5*110))*.001)/5.2+.01
        self.assertAlmostEqual(row["total_cost_r"],expected)
        self.assertAlmostEqual(row["fixed_path_before_attributed_cost_r"],1+expected)

    def test_gap_stop_cost_reference_uses_worse_open(self):
        self.trade.update(exit_reason="STOP_LOSS",tp1_taken=False)
        row=attribute(self.trade,self.bars,self.costs)
        expected=(.2+(100+90)*.001)/5.2+.01
        self.assertAlmostEqual(row["total_cost_r"],expected)

    def test_unknown_exit_does_not_invent_a_price(self):
        self.trade["exit_reason"]="UNKNOWN"
        with self.assertRaisesRegex(ValueError,"Unrecognized"):
            attribute(self.trade,self.bars,self.costs)


if __name__=="__main__": unittest.main()
