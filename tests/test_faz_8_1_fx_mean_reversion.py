import unittest

from pragma.instrument_profiles import FX_MEAN_REVERSION, MOMENTUM_TREND
from pragma.regime_poi_engine import MarketRegime, generate_regime_pois
from pragma.trigger_engine import _select_targets


class Faz81ProfileTests(unittest.TestCase):
    def test_fx_mean_reversion_calibration(self):
        self.assertEqual(FX_MEAN_REVERSION.poi_atr_multiplier, 0.45)
        self.assertEqual(FX_MEAN_REVERSION.sl_atr_buffer, 0.65)
        self.assertEqual(FX_MEAN_REVERSION.min_spread_to_sl_ratio, 3.0)
        self.assertEqual(FX_MEAN_REVERSION.min_rr_tp1, 1.0)
        self.assertEqual(FX_MEAN_REVERSION.min_rr_tp2, 1.35)

    def test_momentum_profile_is_unchanged(self):
        self.assertEqual(MOMENTUM_TREND.poi_atr_multiplier, 0.35)
        self.assertEqual(MOMENTUM_TREND.sl_atr_buffer, 0.50)
        self.assertEqual(MOMENTUM_TREND.min_spread_to_sl_ratio, 4.0)
        self.assertEqual(MOMENTUM_TREND.min_rr_tp1, 1.5)
        self.assertEqual(MOMENTUM_TREND.min_rr_tp2, 2.0)


class Faz81TargetTests(unittest.TestCase):
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

    def test_long_balance_mean_reversion_has_full_rotation_targets(self):
        profile = {"pdPOC": 100.0, "pdVAH": 101.0, "pdVAL": 99.0}
        result = generate_regime_pois(
            1, profile, self.vwap(), 100.0, 2.0, allow_mean_reversion=True,
            poi_atr_multiplier=0.45,
        )
        poi = next(p for p in result.pois if p.poi_type == "LONG_MEAN_REVERSION")
        self.assertEqual(poi.regime, MarketRegime.BALANCE)
        self.assertEqual(poi.take_profits, (99.0, 100.0, 100.0, 101.0, 101.0))

    def test_short_balance_mean_reversion_has_full_rotation_targets(self):
        profile = {"pdPOC": 100.0, "pdVAH": 101.0, "pdVAL": 99.0}
        result = generate_regime_pois(
            -1, profile, self.vwap(), 100.0, 2.0, allow_mean_reversion=True,
            poi_atr_multiplier=0.45,
        )
        poi = next(p for p in result.pois if p.poi_type == "SHORT_MEAN_REVERSION")
        self.assertEqual(poi.regime, MarketRegime.BALANCE)
        self.assertEqual(poi.take_profits, (101.0, 100.0, 100.0, 99.0, 99.0))

    def test_mean_reversion_target_selector_skips_sub_1r_intermediate_target(self):
        tp1, tp2 = _select_targets(
            [100.4, 101.5, 103.0], "LONG", 100.0,
            risk=1.0, min_rr_tp1=1.0,
        )
        self.assertEqual(tp1, 101.5)
        self.assertEqual(tp2, 103.0)

    def test_mean_reversion_target_selector_preserves_low_rr_for_gate(self):
        tp1, tp2 = _select_targets(
            [100.4, 100.8], "LONG", 100.0,
            risk=1.0, min_rr_tp1=1.0,
        )
        self.assertEqual(tp1, 100.4)
        self.assertEqual(tp2, 100.8)


if __name__ == "__main__":
    unittest.main()
