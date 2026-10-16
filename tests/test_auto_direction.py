"""Tests for causal autonomous long/short crypto regime selection."""
import unittest

from pragma.regime_poi_engine import MarketRegime, generate_regime_pois


PROFILE = {"pdVAL": 90.0, "pdPOC": 100.0, "pdVAH": 110.0, "pdLVN": []}


class AutoDirectionTests(unittest.TestCase):
    def test_auto_selects_bull_only_when_both_thresholds_pass(self):
        result = generate_regime_pois(
            "auto", PROFILE, {"vwap": 102.0, "vwap_sigma": 1.0},
            112.0, 10.0,
        )
        self.assertEqual(result.macro_bias, 1)
        self.assertEqual(result.regime, MarketRegime.IMBALANCE_BULL)
        self.assertTrue(all(p.direction == "LONG" for p in result.pois))

    def test_auto_selects_bear_only_when_both_thresholds_pass(self):
        result = generate_regime_pois(
            "auto", PROFILE, {"vwap": 98.0, "vwap_sigma": 1.0},
            88.0, 10.0,
        )
        self.assertEqual(result.macro_bias, -1)
        self.assertEqual(result.regime, MarketRegime.IMBALANCE_BEAR)
        self.assertTrue(all(p.direction == "SHORT" for p in result.pois))

    def test_auto_stays_neutral_if_price_threshold_fails(self):
        result = generate_regime_pois(
            "auto", PROFILE, {"vwap": 103.0, "vwap_sigma": 1.0},
            109.0, 10.0,
        )
        self.assertEqual(result.macro_bias, 0)
        self.assertEqual(result.pois, ())
        self.assertEqual(result.reason, "NEUTRAL_MACRO")

    def test_auto_stays_neutral_if_vwap_atr_buffer_fails(self):
        result = generate_regime_pois(
            "auto", PROFILE, {"vwap": 101.0, "vwap_sigma": 1.0},
            112.0, 10.0,
        )
        self.assertEqual(result.macro_bias, 0)
        self.assertEqual(result.pois, ())

    def test_fixed_direction_validation_remains_compatible(self):
        with self.assertRaises(ValueError):
            generate_regime_pois(
                "sideways", PROFILE, {"vwap": 102.0, "vwap_sigma": 1.0},
                112.0, 10.0,
            )


if __name__ == "__main__":
    unittest.main()
