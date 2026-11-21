import unittest

import numpy as np
import pandas as pd

from scripts.run_extended_entry_study import audit_clock, contiguous_returns, gross_window, strict_rates, summarize_horizons


class ExtendedEntryStudyTests(unittest.TestCase):
    def rates(self, times):
        return pd.DataFrame({"time": [int(t.timestamp()) for t in times], "open": 100., "high": 101.,
                             "low": 99., "close": 100., "tick_volume": 10}).to_records(index=False)

    def test_response_later_than_requested_is_rejected(self):
        start = pd.Timestamp("2026-06-01T00:00Z")
        with self.assertRaisesRegex(ValueError, "bounds"):
            strict_rates(self.rates([start+pd.Timedelta(days=40)]), start, start+pd.Timedelta(days=1))

    def test_duplicate_rates_are_not_silently_repaired(self):
        start = pd.Timestamp("2026-07-20T00:00Z")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            strict_rates(self.rates([start, start]), start, start+pd.Timedelta(minutes=1))

    def test_fake_zero_volume_history_rejected(self):
        start = pd.Timestamp("2026-07-20T00:00Z")
        raw = self.rates([start])
        raw["tick_volume"] = 0
        with self.assertRaisesRegex(ValueError, "volume"):
            strict_rates(raw, start, start+pd.Timedelta(minutes=1))

    def test_contiguous_return_does_not_bridge_weekend(self):
        ix = pd.DatetimeIndex(["2026-07-24T20:00Z", "2026-07-24T20:05Z", "2026-07-26T21:00Z"])
        returns = contiguous_returns(pd.Series([100., 101., 110.], index=ix))
        self.assertAlmostEqual(returns.iloc[1], .01)
        self.assertTrue(pd.isna(returns.iloc[2]))

    def test_clock_identifies_known_shift_without_price_outcomes(self):
        ix = pd.date_range("2026-07-20T00:00Z", periods=2100, freq="5min")
        rng = np.random.default_rng(27)
        ref = pd.Series(100*np.exp(np.cumsum(rng.normal(0, .001, len(ix)))), index=ix)
        broker = ref.copy()
        broker.index += pd.Timedelta(hours=3)
        result = audit_clock(broker, ref, [ix[0]])
        self.assertTrue(result["passed"])
        self.assertEqual(result["constant_offset_seconds"], 10800)

    def test_unrelated_clock_prices_fail_closed(self):
        ix = pd.date_range("2026-07-20T00:00Z", periods=2100, freq="5min")
        rng = np.random.default_rng(28)
        a = pd.Series(100*np.exp(np.cumsum(rng.normal(0, .001, len(ix)))), index=ix)
        b = pd.Series(100*np.exp(np.cumsum(rng.normal(0, .001, len(ix)))), index=ix)
        result = audit_clock(a, b, [ix[0]])
        self.assertFalse(result["passed"])
        self.assertIsNone(result["constant_offset_seconds"])

    def test_short_clock_history_does_not_pass(self):
        ix = pd.date_range("2026-07-20T00:00Z", periods=100, freq="5min")
        a = pd.Series(np.linspace(100, 110, len(ix)), index=ix)
        self.assertFalse(audit_clock(a, a, [ix[0]])["passed"])

    def test_gross_window_uses_future_open_not_future_close(self):
        ix = pd.date_range("2026-07-27T08:00Z", periods=16, freq="min")
        bars = pd.DataFrame({"open": 100., "close": 500.}, index=ix)
        bars.loc[ix[-1], "open"] = 101
        self.assertAlmostEqual(gross_window(bars, ix[0], "LONG", 15), 100.)
        self.assertAlmostEqual(gross_window(bars, ix[0], "SHORT", 15), -100.)

    def test_missing_intermediate_minute_is_missing_not_free_return(self):
        ix = pd.date_range("2026-07-27T08:00Z", periods=16, freq="min")
        bars = pd.DataFrame({"open": 100.}, index=ix).drop(ix[4])
        self.assertIsNone(gross_window(bars, ix[0], "LONG", 15))

    def test_missing_outcomes_are_neither_zero_nor_net(self):
        row = {"entry_time": "2026-07-27T08:00Z", "horizon_minutes": 15,
               "gross_directional_bid_bps": None, "reference_gross_bid_bps": None}
        result = summarize_horizons([row])["15"]
        self.assertEqual(result["missing"], 1)
        self.assertIsNone(result["gross_directional_bid_bps"]["mean"])
        self.assertIsNone(result["fully_net_bps"])


if __name__ == "__main__":
    unittest.main()
