import unittest

import numpy as np
import pandas as pd
from types import SimpleNamespace
from unittest.mock import patch

from pragma import backtest_engine
from pragma.run_pipeline import run_pipeline
from pragma.instrument_profiles import (
    FX_MEAN_REVERSION,
    MOMENTUM_TREND,
    canonical_symbol,
    get_instrument_profile,
)
from pragma.regime_poi_engine import generate_regime_pois
from pragma.trigger_engine import evaluate_trigger


class InstrumentProfileTests(unittest.TestCase):
    def test_momentum_profile_parameters_and_symbol_aliases(self):
        for symbol in ("XAUUSD", "XAUUSD.a", "GOLD", "XAGUSD", "BTCUSD",
                       "BTCUSDT", "ETHUSD", "SOLUSD", "SPX", "US100",
                       "US30", "GBPJPY", "USDJPY"):
            with self.subTest(symbol=symbol):
                self.assertEqual(get_instrument_profile(symbol), MOMENTUM_TREND)
        self.assertEqual(MOMENTUM_TREND.name, "MOMENTUM_TREND")
        self.assertTrue(MOMENTUM_TREND.allow_trend_pullback)
        self.assertFalse(MOMENTUM_TREND.allow_mean_reversion)
        self.assertEqual(MOMENTUM_TREND.poi_atr_multiplier, 0.35)
        self.assertEqual(MOMENTUM_TREND.sl_atr_buffer, 0.50)
        self.assertEqual(MOMENTUM_TREND.imbalance_vwap_poc_atr, 0.15)
        self.assertEqual(MOMENTUM_TREND.min_spread_to_sl_ratio, 4.0)

    def test_fx_profile_parameters_and_cross_detection(self):
        for symbol in ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD",
                       "USDCHF", "EURGBP", "AUDJPY", "EURTRY", "USDINR"):
            with self.subTest(symbol=symbol):
                self.assertEqual(get_instrument_profile(symbol), FX_MEAN_REVERSION)
        self.assertEqual(FX_MEAN_REVERSION.name, "FX_MEAN_REVERSION")
        self.assertFalse(FX_MEAN_REVERSION.allow_trend_pullback)
        self.assertTrue(FX_MEAN_REVERSION.allow_mean_reversion)
        self.assertEqual(FX_MEAN_REVERSION.poi_atr_multiplier, 0.55)
        self.assertEqual(FX_MEAN_REVERSION.sl_atr_buffer, 0.95)
        self.assertEqual(FX_MEAN_REVERSION.mean_reversion_confluence_atr, 1.0)
        self.assertEqual(FX_MEAN_REVERSION.min_spread_to_sl_ratio, 3.0)

    def test_symbol_canonicalization(self):
        self.assertEqual(canonical_symbol("XAUUSD.a"), "XAUUSD")
        self.assertEqual(canonical_symbol("GC=F"), "XAUUSD")
        self.assertEqual(canonical_symbol("BTCUSDT"), "BTCUSD")
        self.assertEqual(get_instrument_profile("EURCHFm"), FX_MEAN_REVERSION)

    def test_profile_parameters_control_poi_radius_and_trend_permission(self):
        previous = {"pdPOC": 100.0, "pdVAH": 102.0, "pdVAL": 98.0, "pdLVN": []}
        vwap = {
            "vwap": 103.0, "vwap_sigma": 1.0,
            "vwap_lower_1p0sigma": 102.0, "vwap_upper_1p0sigma": 104.0,
            "vwap_lower_1p5sigma": 101.5, "vwap_upper_1p5sigma": 104.5,
            "vwap_lower_2p5sigma": 100.5, "vwap_upper_2p5sigma": 105.5,
        }
        trend = generate_regime_pois(
            1, previous, vwap, 102.1, 2.0,
            allow_trend_pullback=True, allow_mean_reversion=False,
            poi_atr_multiplier=MOMENTUM_TREND.poi_atr_multiplier,
            imbalance_vwap_poc_atr=MOMENTUM_TREND.imbalance_vwap_poc_atr,
        )
        self.assertTrue(any(p.poi_type == "LONG_TREND_PULLBACK" for p in trend.pois))
        for poi in trend.pois:
            self.assertAlmostEqual(poi.poi_high - poi.center, 0.35 * 2.0)

        disabled = generate_regime_pois(
            1, previous, vwap, 102.1, 2.0,
            allow_trend_pullback=FX_MEAN_REVERSION.allow_trend_pullback,
            allow_mean_reversion=False,
            poi_atr_multiplier=FX_MEAN_REVERSION.poi_atr_multiplier,
            imbalance_vwap_poc_atr=FX_MEAN_REVERSION.imbalance_vwap_poc_atr,
        )
        self.assertFalse(any("TREND_PULLBACK" in p.poi_type for p in disabled.pois))

    def test_pipeline_and_backtest_report_profile_names(self):
        pipeline_report = run_pipeline(
            dry_run=True, symbol="EURUSD", macro_bias=1,
            now=pd.Timestamp("2026-10-15T16:00:00Z"),
        )
        self.assertEqual(pipeline_report["instrument_profile"], "FX_MEAN_REVERSION")

        bars = backtest_engine._synthetic_bars(
            1500, end_time=pd.Timestamp("2026-10-02T01:00:00Z")
        )
        captured = []
        def fake_generate(bias, profile, vwap, price, atr, **kwargs):
            captured.append(kwargs.copy())
            return SimpleNamespace(pois=(), regime=SimpleNamespace(value="BALANCE"))
        with patch.object(backtest_engine, "generate_regime_pois", side_effect=fake_generate):
            report = backtest_engine.run_backtest(
                bars, symbol="EURUSD", macro_bias=1, profile_bins=30,
            )
        self.assertEqual(report.instrument_profile, "FX_MEAN_REVERSION")
        self.assertTrue(captured)
        self.assertTrue(captured[0]["allow_mean_reversion"])
        self.assertFalse(captured[0]["allow_trend_pullback"])
        self.assertEqual(captured[0]["poi_atr_multiplier"], 0.55)
        self.assertEqual(captured[0]["mean_reversion_confluence_atr"], 1.0)

    def test_trigger_uses_profile_stop_buffer_and_spread_ratio(self):
        x = np.arange(30, dtype=float)
        close = 100.0 + 0.25 * np.sin(x * 1.3)
        close[-2], close[-1] = 90.0, 99.8
        open_ = close.copy()
        open_[-1] = close[-1] - 0.10
        high, low = close + 0.15, close - 0.15
        high[-1], low[-1] = close[-1] + 0.20, close[-1] - 0.20
        high[-2], low[-2] = 102.1, 97.9
        volume = np.full(30, 10.0)
        volume[-2] = 100.0
        bars = pd.DataFrame({
            "open": open_, "high": high, "low": low,
            "close": close, "tick_volume": volume,
        })
        result = evaluate_trigger(
            bars, "LONG", 98.0, 102.0, atr_14=2.0,
            take_profit=110.0, cost_price=1.0,
            sl_atr_buffer=FX_MEAN_REVERSION.sl_atr_buffer,
            min_spread_to_sl_ratio=FX_MEAN_REVERSION.min_spread_to_sl_ratio,
        )
        self.assertAlmostEqual(result.stop_loss, 98.0 - 0.95 * 2.0)
        self.assertEqual(result.metrics["min_spread_to_sl_ratio"], 3.0)
        self.assertFalse(result.metrics["high_spread_to_sl"])
        self.assertNotEqual(result.reason, "HIGH_SPREAD_TO_SL")


if __name__ == "__main__":
    unittest.main()
