import unittest

import numpy as np
import pandas as pd

from pragma.regime_poi_engine import (
    MarketRegime,
    classify_regime,
    generate_regime_pois,
)
from pragma.trigger_engine import evaluate_trigger
from pragma.vwap_engine import calculate_session_vwap


class RegimePOITests(unittest.TestCase):
    def setUp(self):
        self.profile = {"pdPOC": 100.0, "pdVAH": 101.0, "pdVAL": 99.0,
                        "pdLVN": (98.0, 102.0)}

    @staticmethod
    def vwap(value=100.0, sigma=1.0):
        return {
            "vwap": value,
            "vwap_sigma": sigma,
            "vwap_lower_1p0sigma": value - sigma,
            "vwap_upper_1p0sigma": value + sigma,
            "vwap_lower_1p5sigma": value - 1.5 * sigma,
            "vwap_upper_1p5sigma": value + 1.5 * sigma,
            "vwap_lower_2p0sigma": value - 2 * sigma,
            "vwap_upper_2p0sigma": value + 2 * sigma,
            "vwap_lower_2p5sigma": value - 2.5 * sigma,
            "vwap_upper_2p5sigma": value + 2.5 * sigma,
        }

    def test_balance_long_mean_reversion_poi(self):
        result = generate_regime_pois(1, self.profile, self.vwap(), 100.0, 2.0)
        self.assertEqual(result.regime, MarketRegime.BALANCE)
        self.assertTrue(any(p.poi_type == "LONG_MEAN_REVERSION" for p in result.pois))
        poi = next(p for p in result.pois if p.poi_type == "LONG_MEAN_REVERSION")
        self.assertAlmostEqual(poi.poi_high - poi.poi_low, 1.0)
        self.assertIn(100.0, poi.take_profits)

    def test_bull_imbalance_long_pullback(self):
        result = generate_regime_pois(1, self.profile, self.vwap(value=102.0), 103.0, 2.0)
        self.assertEqual(result.regime, MarketRegime.IMBALANCE_BULL)
        poi = next(p for p in result.pois if p.poi_type == "LONG_TREND_PULLBACK")
        self.assertAlmostEqual(poi.center, 101.0)
        self.assertAlmostEqual(poi.take_profit, 104.0)

    def test_balance_short_mean_reversion_poi(self):
        result = generate_regime_pois(-1, self.profile, self.vwap(), 100.0, 2.0)
        self.assertEqual(result.regime, MarketRegime.BALANCE)
        self.assertTrue(any(p.poi_type == "SHORT_MEAN_REVERSION" for p in result.pois))

    def test_bear_imbalance_short_pullback(self):
        result = generate_regime_pois(-1, self.profile, self.vwap(value=98.0), 97.0, 2.0)
        self.assertEqual(result.regime, MarketRegime.IMBALANCE_BEAR)
        poi = next(p for p in result.pois if p.poi_type == "SHORT_TREND_PULLBACK")
        self.assertAlmostEqual(poi.center, 99.0)
        self.assertAlmostEqual(poi.take_profit, 96.0)

    def test_neutral_macro_never_generates_poi(self):
        result = generate_regime_pois(0, self.profile, self.vwap(), 100.0, 2.0)
        self.assertEqual(result.pois, ())
        self.assertEqual(result.reason, "NEUTRAL_MACRO")

    def test_neutral_range_allows_balance_mean_reversion_only(self):
        result = generate_regime_pois(
            0, self.profile, self.vwap(), 100.0, 2.0, allow_range=True
        )
        self.assertEqual(result.regime, MarketRegime.BALANCE)
        self.assertTrue(result.pois)
        self.assertTrue(all(p.poi_type in (
            "LONG_MEAN_REVERSION", "SHORT_MEAN_REVERSION"
        ) for p in result.pois))

    def test_transition_when_price_and_vwap_disagree(self):
        self.assertEqual(classify_regime(103, self.profile, {"vwap": 99}),
                         MarketRegime.TRANSITION)


class TriggerTests(unittest.TestCase):
    @staticmethod
    def bars(direction):
        base = 100.0 + 0.25 * np.sin(np.arange(30) * 1.3)
        if direction == "LONG":
            base[-2] = 90.0
            base[-1] = 99.8
        else:
            base[-2] = 110.0
            base[-1] = 100.2
        close = base.copy()
        open_ = close.copy()
        high = close + 0.15
        low = close - 0.15
        if direction == "LONG":
            open_[-1] = close[-1] - 0.10
            high[-1] = close[-1] + 0.20
            low[-1] = close[-1] - 0.20
        else:
            open_[-1] = close[-1] + 0.10
            high[-1] = close[-1] + 0.20
            low[-1] = close[-1] - 0.20
        volume = np.full(30, 10.0)
        volume[-2] = 100.0
        return pd.DataFrame({"open": open_, "high": high, "low": low,
                             "close": close, "tick_volume": volume})

    def test_long_execute(self):
        result = evaluate_trigger(self.bars("LONG"), "LONG", 98.0, 102.0,
                                  atr_14=2.0, take_profit=110.0)
        self.assertTrue(result.execute, result.reason)
        self.assertEqual(result.reason, "EXECUTE")
        self.assertEqual(result.direction, "LONG")
        self.assertGreaterEqual(result.rr_ratio, 1.5)
        self.assertTrue(result.metrics["z_condition"])
        self.assertTrue(result.metrics["volume_climax"])

    def test_short_execute(self):
        result = evaluate_trigger(self.bars("SHORT"), "SHORT", 98.0, 102.0,
                                  atr_14=2.0, take_profit=90.0)
        self.assertTrue(result.execute, result.reason)
        self.assertEqual(result.reason, "EXECUTE")
        self.assertEqual(result.direction, "SHORT")
        self.assertGreaterEqual(result.rr_ratio, 1.5)

    def test_low_rr_blocks_execute(self):
        result = evaluate_trigger(self.bars("LONG"), "LONG", 98.0, 102.0,
                                  atr_14=2.0, take_profit=100.0)
        self.assertFalse(result.execute)
        self.assertEqual(result.reason, "LOW_RR")

    def test_vwap_engine_produces_1p5_sigma_bands(self):
        bars = pd.DataFrame({"high": [11.0, 12.0, 13.0],
                             "low": [9.0, 10.0, 11.0],
                             "close": [10.0, 11.0, 12.0],
                             "tick_volume": [10.0, 20.0, 30.0]})
        result = calculate_session_vwap(bars, band_multipliers=(1.0, 1.5, 2.0, 2.5))
        self.assertIn("vwap_lower_1p5sigma", result.columns)
        self.assertIn("vwap_upper_1p5sigma", result.columns)
        self.assertTrue(np.allclose(result.vwap_lower_1p5sigma,
                                    result.vwap - 1.5 * result.vwap_sigma))


if __name__ == "__main__":
    unittest.main()
