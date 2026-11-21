import unittest

import pandas as pd

from pragma.measurement import ExecutionCosts
from scripts.run_exit_cap_study import replay_capped, anatomy


class ExitCapStudyTests(unittest.TestCase):
    def setUp(self):
        self.ix = pd.date_range("2026-10-05T08:00Z", periods=16, freq="min")
        self.bars = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100.}, index=self.ix)
        self.trade = {"symbol": "X", "direction": "LONG", "poi_type": "T", "regime": "R",
                      "fill_time": self.ix[0].isoformat(), "entry_price": 100.1,
                      "initial_stop_loss": 95., "tp1": 105., "tp2": 110.,
                      "signal_bar_time": (self.ix[0] - pd.Timedelta(minutes=1)).isoformat(),
                      "decision_time": self.ix[0].isoformat()}
        self.cost = ExecutionCosts(fixed_per_side=.1)

    def test_deadline_open_ignores_deadline_high_low_and_close(self):
        self.bars.loc[self.ix[-1], ["open", "high", "low", "close"]] = [102, 200, 1, 150]
        record = replay_capped(self.bars, self.trade, self.cost)["record"]
        self.assertEqual(record["exit_reason"], "TIME_CAP_15M")
        self.assertEqual(record["exit_time"], self.ix[-1].isoformat())
        self.assertAlmostEqual(record["r_multiple"], (101.9 - 100.1) / 5.1)

    def test_prior_stop_has_priority_and_retains_adverse_gap(self):
        self.bars.loc[self.ix[2], ["open", "high", "low", "close"]] = [90, 120, 89, 100]
        record = replay_capped(self.bars, self.trade, self.cost)["record"]
        self.assertEqual(record["exit_reason"], "STOP_LOSS")
        self.assertAlmostEqual(record["r_multiple"], (89.9 - 100.1) / 5.1)

    def test_partial_then_cap_charges_only_remaining_exit_size(self):
        self.bars.loc[self.ix[2]:, ["open", "high", "low", "close"]] = [102, 103, 101, 102]
        self.bars.loc[self.ix[2], "high"] = 106
        record = replay_capped(self.bars, self.trade, self.cost)["record"]
        self.assertTrue(record["tp1_taken"])
        self.assertEqual(record["exit_reason"], "TIME_CAP_15M")
        self.assertAlmostEqual(record["r_multiple"], (.5 * (104.9 - 100.1) + .5 * (101.9 - 100.1)) / 5.1)

    def test_missing_deadline_is_missing_not_last_close(self):
        result = replay_capped(self.bars.iloc[:-1], self.trade, self.cost)
        self.assertIsNone(result["record"])
        self.assertEqual(result["missing_reason"], "MISSING_DEADLINE_OPEN")

    def test_gap_before_deadline_invalidates_open_path(self):
        result = replay_capped(self.bars.drop(self.ix[2]), self.trade, self.cost)
        self.assertIsNone(result["record"])
        self.assertEqual(result["missing_reason"], "MISSING_PRE_DEADLINE_MINUTE")

    def test_missing_later_bars_do_not_invalidate_earlier_stop(self):
        self.bars.loc[self.ix[0], "low"] = 94
        record = replay_capped(self.bars.iloc[:1], self.trade, self.cost)["record"]
        self.assertEqual(record["exit_reason"], "STOP_LOSS")

    def test_short_exit_cost_is_adverse(self):
        self.trade.update(direction="SHORT", entry_price=99.9, initial_stop_loss=105., tp1=95., tp2=90.)
        self.bars.loc[self.ix[-1], "open"] = 98
        record = replay_capped(self.bars, self.trade, self.cost)["record"]
        self.assertAlmostEqual(record["r_multiple"], (99.9 - 98.1) / 5.1)

    def test_unknown_funding_path_rejected(self):
        with self.assertRaisesRegex(ValueError, "funding"):
            replay_capped(self.bars, self.trade, ExecutionCosts(funding_rate_8h=.001))

    def test_anatomy_preserves_missing_fees_and_quote_coverage(self):
        row = {"symbol": "X", "variant": "baseline", "horizon_minutes": 15,
               "observation": {"mid_gross_bps": 2, "quoted_spread_only_bps": 1,
                               "known_cost_subtotal_bps": None}}
        result = anatomy([row, dict(row, observation=None)], "X")
        self.assertEqual(result["missing_quotes"], 1)
        self.assertEqual(result["fee_proxy_complete"], 0)
        self.assertIsNone(result["mean_known_cost_subtotal_bps"])
        self.assertEqual(result["mean_spread_drag_bps"], 1)


if __name__ == "__main__":
    unittest.main()
