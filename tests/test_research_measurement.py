import unittest
from dataclasses import asdict

import pandas as pd

from pragma.backtest_engine import _OpenTrade, _manage_open_trade, _utc_index
from pragma.measurement import ExecutionCosts, decide_trigger
from pragma.regime_poi_engine import POI, MarketRegime
from pragma.research_measurement import horizon_diagnostics, replay_fixed_entries, weekly_bootstrap
from pragma.trigger_engine import TriggerDecision


class ResearchMeasurementTests(unittest.TestCase):
    def test_touch_window_is_an_isolated_veto(self):
        ix = pd.date_range("2026-10-05T08:00Z", periods=30, freq="min")
        bars = pd.DataFrame({"open": 110., "high": 112., "low": 109., "close": 111., "tick_volume": 100.}, index=ix)
        bars.loc[ix[-2], "low"] = 99
        poi = POI("LONG", "LONG_TREND_PULLBACK", MarketRegime.IMBALANCE_BULL, 100, 99, 101, (120, 130), ())
        def evaluator(*args, **kwargs):
            self.assertAlmostEqual(kwargs["cost_price"], 0.3)
            return TriggerDecision(True, "LONG", 111, 95, 120, 130, 120, 1.5, "EXECUTE", {"cost_price": .3})
        a = decide_trigger("XAUUSD", bars, poi, 1, .3, touch_bars=3, evaluator=evaluator)
        b = decide_trigger("XAUUSD", bars, poi, 1, .3, touch_bars=1, evaluator=evaluator)
        self.assertTrue(a.execute)
        self.assertFalse(b.execute)
        self.assertEqual(a.stop_loss, b.stop_loss)
        self.assertEqual(a.take_profit_2, b.take_profit_2)

    def test_fixed_exit_replay_preserves_entry_and_reproduces_baseline(self):
        ix = pd.date_range("2026-10-05T08:00Z", periods=3, freq="min")
        bars = pd.DataFrame({"open": [100, 102, 102], "high": [104, 106, 111],
                             "low": [99, 101, 99], "close": [102, 104, 110]}, index=ix)
        p = _OpenTrade("X", "LONG", "T", "R", ix[0], 100.1, 95, 95, 105, 110, 5.1,
                       entry_at_open=True, signal_bar_time=(ix[0]-pd.Timedelta(minutes=1)).isoformat(), decision_time=ix[0].isoformat())
        cost = ExecutionCosts(fixed_per_side=.1)
        record = None
        for stamp, bar in bars.iterrows():
            record = _manage_open_trade(p, bar, stamp, cost=.1)
            if record:
                break
        original = asdict(record)
        baseline = replay_fixed_entries(bars, [original], cost, be_offset_r=0)[0]
        no_be = replay_fixed_entries(bars, [original], cost, be_offset_r=None)[0]
        self.assertAlmostEqual(baseline["r_multiple"], original["r_multiple"])
        self.assertEqual(baseline["exit_time"], original["exit_time"])
        self.assertEqual(no_be["entry_price"], original["entry_price"])
        self.assertEqual(no_be["fill_time"], original["fill_time"])
        self.assertGreater(no_be["r_multiple"], original["r_multiple"])

    def test_horizon_includes_both_sides_and_no_fabricated_reference(self):
        ix = pd.date_range("2026-10-05T08:00Z", periods=60, freq="min")
        bars = pd.DataFrame({"open": 100., "high": 100., "low": 100., "close": 100.}, index=ix)
        candidate = {"signal_bar_time": ix[0].isoformat(), "direction": "LONG", "eligible": True}
        summary, rows, _ = horizon_diagnostics(bars, [candidate], ExecutionCosts(commission_bps=4))
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[0]["net_bps"], -8)
        self.assertNotIn("paired_excess_bps", rows[0])
        self.assertIsNone(summary["5"]["paired_excess_bps"]["mean"])

    def test_week_bootstrap_small_sample_not_false_certainty(self):
        rows = [{"entry_time": "2026-10-05T08:00Z", "r_multiple": 5}]
        self.assertIsNone(weekly_bootstrap(rows)["ci95"])
        rows = [{"entry_time": (pd.Timestamp("2026-01-01T08:00Z")+pd.Timedelta(weeks=i)).isoformat(), "r_multiple": (-1)**i} for i in range(20)]
        self.assertEqual(weekly_bootstrap(rows), weekly_bootstrap(rows))
        self.assertFalse(weekly_bootstrap(rows)["multiple_testing_corrected"])

    def test_duplicate_inputs_are_rejected_instead_of_repaired(self):
        ix = pd.DatetimeIndex(["2026-10-05T08:00Z", "2026-10-05T08:00Z"])
        with self.assertRaisesRegex(ValueError, "unique"):
            _utc_index(pd.DataFrame(index=ix), "M1")


if __name__ == "__main__":
    unittest.main()
