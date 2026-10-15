import unittest

import numpy as np
import pandas as pd

from pragma.amt_engine import (
    AMTEngine,
    calculate_session_profiles,
    calculate_volume_profile,
)
from pragma.vwap_engine import calculate_session_vwap


def sample_bars():
    return pd.DataFrame({
        "high": [10.0, 11.0, 12.0, 11.0, 10.0],
        "low": [9.0, 10.0, 11.0, 10.0, 9.0],
        "close": [9.5, 10.5, 11.5, 10.5, 9.5],
        "tick_volume": [10, 20, 50, 20, 10],
    })


class AMTTests(unittest.TestCase):
    def test_profile_conserves_volume_and_has_valid_levels(self):
        bars = sample_bars()
        result = calculate_volume_profile(bars, bins=20)
        self.assertAlmostEqual(result.total_volume, bars.tick_volume.sum())
        self.assertLessEqual(result.val, result.poc)
        self.assertGreaterEqual(result.vah, result.poc)
        self.assertGreaterEqual(result.value_area_fraction, 0.70)
        self.assertEqual(len(result.histogram), 20)

    def test_bar_volume_is_spread_across_full_range(self):
        bars = pd.DataFrame({
            "high": [10.0], "low": [0.0], "close": [5.0],
            "tick_volume": [100.0],
        })
        result = calculate_volume_profile(bars, bins=10)
        volumes = result.histogram["tick_volume"].to_numpy()
        self.assertTrue(np.allclose(volumes, np.full(10, 10.0)))
        self.assertAlmostEqual(volumes.sum(), 100.0)

    def test_zero_range_bar_is_assigned_to_one_bin(self):
        bars = pd.DataFrame({
            "high": [100.0], "low": [100.0], "close": [100.0],
            "tick_volume": [12.0],
        })
        result = calculate_volume_profile(bars, bins=5)
        positive = result.histogram.loc[result.histogram.tick_volume > 0]
        self.assertEqual(len(positive), 1)
        self.assertAlmostEqual(positive.tick_volume.iloc[0], 12.0)

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            calculate_volume_profile(sample_bars().assign(tick_volume=-1))
        with self.assertRaises(ValueError):
            calculate_volume_profile(sample_bars(), value_area_fraction=0)

    def test_previous_and_developing_profiles_respect_as_of(self):
        index = pd.to_datetime([
            "2026-10-13T10:00:00Z", "2026-10-13T10:01:00Z",
            "2026-10-14T10:00:00Z", "2026-10-14T10:01:00Z",
            "2026-10-14T10:02:00Z",
        ])
        bars = sample_bars().iloc[:5].copy()
        bars.index = index
        bars["session"] = ["2026-10-13", "2026-10-13", "2026-10-14",
                           "2026-10-14", "2026-10-14"]
        result = calculate_session_profiles(
            bars, session_key="session", as_of="2026-10-14T10:01:00Z", bins=10
        )
        self.assertEqual(result.previous.session, "2026-10-13")
        self.assertEqual(result.developing.session, "2026-10-14")
        self.assertAlmostEqual(result.previous.profile.total_volume, 30.0)
        self.assertAlmostEqual(result.developing.profile.total_volume, 70.0)

    def test_engine_session_wrapper(self):
        bars = sample_bars()
        bars["session"] = ["a", "a", "b", "b", "b"]
        result = AMTEngine(bins=10).calculate_sessions(bars, "session")
        self.assertEqual(result.previous.session, "a")
        self.assertEqual(result.developing.session, "b")


class VWAPTests(unittest.TestCase):
    def test_weighted_vwap(self):
        bars = sample_bars()
        result = calculate_session_vwap(bars)
        typical = (bars.high + bars.low + bars.close) / 3
        expected = np.average(typical, weights=bars.tick_volume)
        self.assertAlmostEqual(result.vwap.iloc[-1], expected)
        self.assertGreaterEqual(result.vwap_sigma.iloc[-1], 0.0)

    def test_session_resets(self):
        bars = sample_bars()
        bars["session"] = ["a", "a", "a", "b", "b"]
        result = calculate_session_vwap(bars, session_key="session")
        expected = (bars.high.iloc[3] + bars.low.iloc[3] + bars.close.iloc[3]) / 3
        self.assertAlmostEqual(result.vwap.iloc[3], expected)

    def test_rejects_negative_volume(self):
        with self.assertRaises(ValueError):
            calculate_session_vwap(sample_bars().assign(tick_volume=-1))


if __name__ == "__main__":
    unittest.main()
