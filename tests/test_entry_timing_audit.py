import unittest

import pandas as pd

from scripts.audit_entry_timing import past_features, summarize, volume_touch_chronology


class EntryTimingAuditTests(unittest.TestCase):
    def setUp(self):
        self.index = pd.date_range("2026-10-05T08:00Z", periods=90, freq="min")
        self.bars = pd.DataFrame({"open": 100., "high": 102., "low": 99., "close": 101.}, index=self.index)
        self.decision = self.index[60]

    def test_features_ignore_all_decision_and_future_candles(self):
        expected = past_features(self.bars, self.decision, "LONG")
        changed = self.bars.copy()
        changed.loc[self.decision:, ["open", "high", "low", "close"]] = [1000, 2000, 1, 1500]
        self.assertEqual(expected, past_features(changed, self.decision, "LONG"))
        self.assertEqual(expected, past_features(self.bars.iloc[:60], self.decision, "LONG"))

    def test_directions_are_symmetric_without_using_outcomes(self):
        long = past_features(self.bars, self.decision, "LONG")
        short = past_features(self.bars, self.decision, "SHORT")
        self.assertEqual(long["prior_15m_group"], "ALIGNED")
        self.assertEqual(short["prior_15m_group"], "OPPOSED")
        self.assertAlmostEqual(long["prior_15m_directional_bid_bps"], -short["prior_15m_directional_bid_bps"])
        self.assertAlmostEqual(long["prior_15m_directional_range_location"] + short["prior_15m_directional_range_location"], 1)

    def test_missing_minute_cannot_be_replaced_by_neighboring_bar(self):
        result = past_features(self.bars.drop(self.index[55]), self.decision, "LONG")
        self.assertFalse(result["prior_15m_complete"])
        self.assertIsNone(result["prior_15m_directional_bid_bps"])
        self.assertEqual(result["prior_15m_group"], "MISSING")

    def test_insufficient_history_is_not_flat_history(self):
        result = past_features(self.bars.iloc[55:], self.decision, "LONG")
        self.assertTrue(result["prior_5m_complete"])
        self.assertFalse(result["prior_15m_complete"])
        self.assertEqual(result["prior_15m_group"], "MISSING")

    def test_flat_series_has_no_fabricated_range_position(self):
        bars = self.bars.copy()
        bars.loc[:, ["open", "high", "low", "close"]] = 100.
        result = past_features(bars, self.decision, "LONG")
        self.assertEqual(result["prior_15m_group"], "FLAT")
        self.assertIsNone(result["prior_15m_directional_range_location"])

    def test_duplicate_timestamps_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            past_features(pd.concat([self.bars, self.bars.iloc[-1:]]), self.decision, "LONG")

    def test_missing_quote_not_treated_as_zero_or_profit(self):
        row = {"outcome_15m": None, "features": {"prior_15m_directional_bid_bps": 3},
               "timing": {"last_touch_age_minutes": 5, "climax_age_minutes": 5,
                          "latest_qualifying_volume_touch_age_minutes": 5},
               "geometry": {"stop_distance_atr": None, "tp1_distance_atr": None}}
        summary = summarize([row])
        self.assertEqual(summary["missing_quotes"], 1)
        self.assertEqual(summary["gross_positive_n"], 0)
        self.assertIsNone(summary["gross_mean_bps"])
        self.assertIsNone(summary["fully_net_bps"])

    def test_first_old_volume_match_does_not_hide_fresh_match(self):
        m5 = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100.,
                           "tick_volume": 100.}, index=pd.date_range("2026-10-05T05:30Z", periods=30, freq="5min"))
        m5.loc[m5.index[-3], "tick_volume"] = 200
        m5.loc[m5.index[-1], "tick_volume"] = 200
        result = volume_touch_chronology(m5, 99.5, 100.5)
        self.assertEqual(result["qualifying_volume_touch_ages_minutes"], [10, 0])
        self.assertEqual(result["latest_qualifying_volume_touch_age_minutes"], 0)

    def test_volume_spike_outside_poi_does_not_count_as_fresh_touch(self):
        m5 = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100.,
                           "tick_volume": 100.}, index=pd.date_range("2026-10-05T05:30Z", periods=30, freq="5min"))
        m5.loc[m5.index[-3], "tick_volume"] = 200
        m5.loc[m5.index[-1], ["low", "high", "tick_volume"]] = [102, 104, 500]
        result = volume_touch_chronology(m5, 99.5, 100.5)
        self.assertEqual(result["qualifying_volume_touch_ages_minutes"], [10])
        self.assertEqual(result["latest_qualifying_volume_touch_age_minutes"], 10)


if __name__ == "__main__":
    unittest.main()
