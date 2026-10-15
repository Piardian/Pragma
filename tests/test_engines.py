import unittest

import numpy as np
import pandas as pd

from pragma.amt_engine import calculate_volume_profile
from pragma.vwap_engine import calculate_session_vwap


def sample_bars():
    return pd.DataFrame({
        "high": [10.0, 11.0, 12.0, 11.0, 10.0],
        "low": [9.0, 10.0, 11.0, 10.0, 9.0],
        "close": [9.5, 10.5, 11.5, 10.5, 9.5],
        "tick_volume": [10, 20, 50, 20, 10],
    })


class AMTTests(unittest.TestCase):
    def test_profile_volume_conservation_and_levels(self):
        result = calculate_volume_profile(sample_bars(), bins=20)
        self.assertAlmostEqual(result.total_volume, 110.0)
        self.assertLessEqual(result.val, result.poc)
        self.assertGreaterEqual(result.vah, result.poc)
        self.assertGreaterEqual(result.value_area_fraction, 0.70)
        self.assertEqual(len(result.histogram), 20)

    def test_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            calculate_volume_profile(sample_bars().assign(tick_volume=-1))
        with self.assertRaises(ValueError):
            calculate_volume_profile(sample_bars(), value_area_fraction=0)

    def test_constant_price_is_handled(self):
        bars = pd.DataFrame({
            "high": [100.0] * 3, "low": [100.0] * 3,
            "close": [100.0] * 3, "tick_volume": [1, 2, 3],
        })
        result = calculate_volume_profile(bars, bins=5)
        self.assertAlmostEqual(result.total_volume, 6.0)


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
