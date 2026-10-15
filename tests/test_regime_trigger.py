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
        self.assertEqual(result.pois, ())
        opted_in = generate_regime_pois(
            1, self.profile, self.vwap(), 100.0, 2.0, allow_mean_reversion=True
        )
        self.assertTrue(any(p.poi_type == "LONG_MEAN_REVERSION" for p in opted_in.pois))
        poi = next(p for p in opted_in.pois if p.poi_type == "LONG_MEAN_REVERSION")
        self.assertAlmostEqual(poi.poi_high - poi.poi_low, 1.4)
        self.assertIn(100.0, poi.take_profits)

    def test_bull_imbalance_long_pullback(self):
        result = generate_regime_pois(1, self.profile, self.vwap(value=102.0), 103.0, 2.0)
        self.assertEqual(result.regime, MarketRegime.IMBALANCE_BULL)
        poi = next(p for p in result.pois if p.poi_type == "LONG_TREND_PULLBACK")
        self.assertAlmostEqual(poi.center, 101.0)
        self.assertAlmostEqual(poi.take_profit, 103.5)

    def test_balance_short_mean_reversion_poi(self):
        result = generate_regime_pois(-1, self.profile, self.vwap(), 100.0, 2.0)
        self.assertEqual(result.regime, MarketRegime.BALANCE)
        self.assertEqual(result.pois, ())
        opted_in = generate_regime_pois(
            -1, self.profile, self.vwap(), 100.0, 2.0, allow_mean_reversion=True
        )
        self.assertTrue(any(p.poi_type == "SHORT_MEAN_REVERSION" for p in opted_in.pois))

    def test_bear_imbalance_short_pullback(self):
        result = generate_regime_pois(-1, self.profile, self.vwap(value=98.0), 97.0, 2.0)
        self.assertEqual(result.regime, MarketRegime.IMBALANCE_BEAR)
        poi = next(p for p in result.pois if p.poi_type == "SHORT_TREND_PULLBACK")
        self.assertAlmostEqual(poi.center, 99.0)
        self.assertAlmostEqual(poi.take_profit, 96.5)

    def test_bear_imbalance_locks_all_long_pois(self):
        result = generate_regime_pois(
            1, self.profile, self.vwap(value=98.0), 97.0, 2.0
        )
        self.assertEqual(result.regime, MarketRegime.IMBALANCE_BEAR)
        self.assertFalse(any(p.direction == "LONG" for p in result.pois))

    def test_bull_imbalance_locks_all_short_pois(self):
        result = generate_regime_pois(
            -1, self.profile, self.vwap(value=102.0), 103.0, 2.0
        )
        self.assertEqual(result.regime, MarketRegime.IMBALANCE_BULL)
        self.assertFalse(any(p.direction == "SHORT" for p in result.pois))

    def test_balance_long_mean_reversion_requires_vwap_at_or_above_val(self):
        result = generate_regime_pois(
            1, self.profile, self.vwap(value=98.5), 101.5, 2.0
        )
        self.assertEqual(result.regime, MarketRegime.BALANCE)
        self.assertFalse(any(p.poi_type == "LONG_MEAN_REVERSION" for p in result.pois))

    def test_balance_short_mean_reversion_requires_vwap_at_or_below_vah(self):
        result = generate_regime_pois(
            -1, self.profile, self.vwap(value=101.5), 98.5, 2.0
        )
        self.assertEqual(result.regime, MarketRegime.BALANCE)
        self.assertFalse(any(p.poi_type == "SHORT_MEAN_REVERSION" for p in result.pois))

    def test_bull_pullback_can_center_on_active_vwap_or_lower_band(self):
        result = generate_regime_pois(
            1, self.profile, self.vwap(value=103.0), 102.2, 2.0
        )
        pullbacks = [p for p in result.pois if p.poi_type == "LONG_TREND_PULLBACK"]
        self.assertTrue(any(abs(p.center - 102.0) < 1e-9 for p in pullbacks))
        self.assertTrue(all(p.take_profits == (104.5, 105.5) for p in pullbacks))

    def test_bear_pullback_can_center_on_active_vwap_or_upper_band(self):
        result = generate_regime_pois(
            -1, self.profile, self.vwap(value=97.0), 97.8, 2.0
        )
        pullbacks = [p for p in result.pois if p.poi_type == "SHORT_TREND_PULLBACK"]
        self.assertTrue(any(abs(p.center - 98.0) < 1e-9 for p in pullbacks))
        self.assertTrue(all(p.take_profits == (95.5, 94.5) for p in pullbacks))

    def test_neutral_macro_never_generates_poi(self):
        result = generate_regime_pois(0, self.profile, self.vwap(), 100.0, 2.0)
        self.assertEqual(result.pois, ())
        self.assertEqual(result.reason, "NEUTRAL_MACRO")

    def test_neutral_range_allows_balance_mean_reversion_only(self):
        result = generate_regime_pois(
            0, self.profile, self.vwap(), 100.0, 2.0,
            allow_range=True, allow_mean_reversion=True,
        )
        self.assertEqual(result.regime, MarketRegime.BALANCE)
        self.assertTrue(result.pois)
        self.assertTrue(all(p.poi_type in (
            "LONG_MEAN_REVERSION", "SHORT_MEAN_REVERSION"
        ) for p in result.pois))
        self.assertTrue(any(p.poi_type == "LONG_MEAN_REVERSION" for p in result.pois))
        self.assertTrue(any(p.poi_type == "SHORT_MEAN_REVERSION" for p in result.pois))

    def test_bull_imbalance_requires_vwap_poc_separation(self):
        result = generate_regime_pois(
            1, self.profile, self.vwap(value=100.2), 103.0, 2.0
        )
        self.assertEqual(result.regime, MarketRegime.IMBALANCE_BULL)
        self.assertEqual(result.pois, ())

    def test_bear_imbalance_requires_vwap_poc_separation(self):
        result = generate_regime_pois(
            -1, self.profile, self.vwap(value=99.8), 97.0, 2.0
        )
        self.assertEqual(result.regime, MarketRegime.IMBALANCE_BEAR)
        self.assertEqual(result.pois, ())

    def test_transition_when_price_and_vwap_disagree(self):
        self.assertEqual(classify_regime(103, self.profile, {"vwap": 99}),
                         MarketRegime.TRANSITION)

    def test_atr_buffer_keeps_bull_pullback_regime_near_vah(self):
        self.assertEqual(classify_regime(100.5, self.profile, {"vwap": 102}, 2.0),
                         MarketRegime.IMBALANCE_BULL)

    def test_atr_buffer_keeps_balance_regime_just_below_val_without_directional_vwap(self):
        self.assertEqual(classify_regime(98.5, self.profile, {"vwap": 100}, 2.0),
                         MarketRegime.BALANCE)


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
        # The climax candle must itself intersect the active POI, even though
        # its close is the exhaustion extreme used by the Z-score rule.
        high[-2] = 102.1
        low[-2] = 97.9
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

    def test_rejects_outside_active_utc_session(self):
        bars = self.bars("LONG")
        bars.index = pd.date_range("2026-10-15T02:00:00Z", periods=len(bars), freq="min")
        result = evaluate_trigger(bars, "LONG", 98.0, 102.0, atr_14=2.0,
                                  take_profit=110.0)
        self.assertFalse(result.execute)
        self.assertEqual(result.reason, "SESSION_HOURS")
        self.assertFalse(result.metrics["session_allowed"])

    def test_rejects_when_spread_is_too_large_relative_to_stop(self):
        result = evaluate_trigger(
            self.bars("LONG"), "LONG", 99.0, 102.0, atr_14=2.0,
            take_profit=110.0, cost_price=0.7,
        )
        self.assertFalse(result.execute)
        self.assertEqual(result.reason, "HIGH_SPREAD_TO_SL")
        self.assertTrue(result.metrics["high_spread_to_sl"])

    def test_trend_pullback_requires_higher_net_rr(self):
        result = evaluate_trigger(
            self.bars("LONG"), "LONG", 98.0, 102.0, atr_14=2.0,
            take_profit=[103.2, 105.5], poi_type="LONG_TREND_PULLBACK",
        )
        self.assertTrue(result.execute, result.reason)
        self.assertGreaterEqual(result.metrics["rr_tp1"], 1.2)
        self.assertGreaterEqual(result.metrics["rr_tp2"], 2.0)

    def test_trend_pullback_promotes_tp2_when_tp1_rr_is_low(self):
        result = evaluate_trigger(
            self.bars("LONG"), "LONG", 98.0, 102.0, atr_14=2.0,
            take_profit=[102.8, 104.8], poi_type="LONG_TREND_PULLBACK",
        )
        self.assertTrue(result.execute, result.reason)
        self.assertTrue(result.metrics["target_fallback_to_tp2"])
        self.assertEqual(result.take_profit_1, 104.8)
        self.assertGreaterEqual(result.metrics["rr_ratio"], 1.6)

    def test_spread_cost_changes_effective_rr(self):
        baseline = evaluate_trigger(
            self.bars("LONG"), "LONG", 98.0, 102.0, atr_14=2.0,
            take_profit=110.0,
        )
        costly = evaluate_trigger(
            self.bars("LONG"), "LONG", 98.0, 102.0, atr_14=2.0,
            take_profit=110.0, cost_price=0.2,
        )
        self.assertGreater(baseline.metrics["rr_ratio"], costly.metrics["rr_ratio"])
        self.assertAlmostEqual(costly.metrics["effective_entry"], costly.entry_price + 0.2)

    def test_low_rr_blocks_execute(self):
        result = evaluate_trigger(self.bars("LONG"), "LONG", 98.0, 102.0,
                                  atr_14=2.0, take_profit=100.0)
        self.assertFalse(result.execute)
        self.assertEqual(result.reason, "LOW_RR")

    def test_previous_candle_wick_counts_as_poi_touch(self):
        bars = self.bars("LONG")
        bars.iloc[-1, bars.columns.get_loc("low")] = 99.6
        bars.iloc[-1, bars.columns.get_loc("high")] = 100.0
        bars.iloc[-2, bars.columns.get_loc("low")] = 98.9
        bars.iloc[-2, bars.columns.get_loc("high")] = 99.05
        bars.iloc[-2, bars.columns.get_loc("tick_volume")] = 100.0
        result = evaluate_trigger(bars, "LONG", 99.0, 99.1, atr_14=2.0,
                                  take_profit=110.0)
        self.assertTrue(result.metrics["poi_touched"])
        self.assertTrue(result.metrics["volume_climax"])
        self.assertNotEqual(result.reason, "OUTSIDE_POI")

    def test_tp2_fallback_when_tp1_rr_is_too_low(self):
        result = evaluate_trigger(self.bars("LONG"), "LONG", 98.0, 102.0,
                                  atr_14=2.0, take_profit=[100.0, 110.0])
        self.assertTrue(result.execute, result.reason)
        self.assertTrue(result.metrics["target_fallback_to_tp2"])
        self.assertEqual(result.take_profit_1, 110.0)
        self.assertGreaterEqual(result.rr_ratio, 1.5)

    def test_long_mean_reversion_requires_level_reclaim(self):
        bars = self.bars("LONG")
        result = evaluate_trigger(
            bars, "LONG", 98.0, 102.0, atr_14=2.0, take_profit=110.0,
            poi_type="LONG_MEAN_REVERSION", center_price=100.0,
        )
        self.assertFalse(result.execute)
        self.assertEqual(result.reason, "LEVEL_RECLAIM_NOT_CONFIRMED")
        self.assertFalse(result.metrics["level_reclaim"])

    def test_long_mean_reversion_accepts_reclaimed_level(self):
        bars = self.bars("LONG")
        bars.iloc[-1, bars.columns.get_loc("open")] = 100.0
        bars.iloc[-1, bars.columns.get_loc("close")] = 100.2
        bars.iloc[-1, bars.columns.get_loc("high")] = 100.4
        bars.iloc[-1, bars.columns.get_loc("low")] = 99.8
        result = evaluate_trigger(
            bars, "LONG", 98.0, 102.0, atr_14=2.0, take_profit=110.0,
            poi_type="LONG_MEAN_REVERSION", center_price=100.0,
        )
        self.assertTrue(result.metrics["level_reclaim"])

    def test_short_mean_reversion_requires_level_reclaim(self):
        bars = self.bars("SHORT")
        result = evaluate_trigger(
            bars, "SHORT", 98.0, 102.0, atr_14=2.0, take_profit=90.0,
            poi_type="SHORT_MEAN_REVERSION", center_price=100.0,
        )
        self.assertFalse(result.execute)
        self.assertEqual(result.reason, "LEVEL_RECLAIM_NOT_CONFIRMED")
        self.assertFalse(result.metrics["level_reclaim"])

    def test_split_targets_accept_rr1_at_least_1_and_rr2_at_least_1_8(self):
        result = evaluate_trigger(
            self.bars("LONG"), "LONG", 98.0, 102.0, atr_14=2.0,
            take_profit=[103.2, 105.5],
        )
        self.assertTrue(result.execute, result.reason)
        self.assertTrue(result.metrics["split_rr_gate"])
        self.assertAlmostEqual(result.take_profit_1, 103.2)
        self.assertAlmostEqual(result.take_profit_2, 105.5)

    def test_split_targets_reject_when_rr2_below_1_8_and_tp1_below_min_rr(self):
        result = evaluate_trigger(
            self.bars("LONG"), "LONG", 98.0, 102.0, atr_14=2.0,
            take_profit=[103.2, 104.5],
        )
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
