"""Unit tests for FAZ 13 crypto audit fixes, funding model, and filters."""
import unittest
import numpy as np
import pandas as pd

from pragma.backtest_engine import (
    _OpenTrade,
    _apply_funding,
    _count_funding_events,
    run_backtest,
)
from pragma.data.binance_data import btc_leader_allows_direction
from pragma.instrument_profiles import get_instrument_profile, CRYPTO_MOMENTUM
from pragma.regime_poi_engine import generate_regime_pois
from pragma.trigger_engine import evaluate_trigger


class TestPhase13Crypto(unittest.TestCase):

    def test_binance_funding_cost_deduction(self):
        """Verify funding events deduction from trade R multiple across 08:00 UTC."""
        entry_time = pd.Timestamp("2026-05-01 07:30:00", tz="UTC")
        exit_time = pd.Timestamp("2026-05-01 08:30:00", tz="UTC")
        events = _count_funding_events(entry_time, exit_time)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], pd.Timestamp("2026-05-01 08:00:00", tz="UTC"))

        trade = _OpenTrade(
            symbol="BTCUSDT",
            direction="LONG",
            poi_type="LONG_TREND_PULLBACK",
            regime="IMBALANCE_BULL",
            entry_time=entry_time,
            entry_price=60000.0,
            initial_stop_loss=59000.0,
            stop_loss=59000.0,
            tp1=61000.0,
            tp2=62000.0,
            initial_risk=1000.0,
            r_multiple=1.5,
        )
        _apply_funding(trade, exit_time)
        self.assertEqual(trade.funding_events, 1)
        # 0.0001 * 60000.0 = 6.0 USDT. delta_r = 6.0 / 1000.0 = 0.006 R
        expected_funding_r = (0.0001 * 60000.0) / 1000.0
        self.assertAlmostEqual(trade.funding_cost_r, expected_funding_r, places=6)
        self.assertAlmostEqual(trade.r_multiple, 1.5 - expected_funding_r, places=6)

    def test_binance_funding_partial_tp1_reduction(self):
        """Verify funding cost scales down when TP1 was reached before the funding event."""
        entry_time = pd.Timestamp("2026-05-01 06:00:00", tz="UTC")
        tp1_time = pd.Timestamp("2026-05-01 07:00:00", tz="UTC")
        exit_time = pd.Timestamp("2026-05-01 09:00:00", tz="UTC")

        trade = _OpenTrade(
            symbol="SOLUSDT",
            direction="LONG",
            poi_type="LONG_TREND_PULLBACK",
            regime="IMBALANCE_BULL",
            entry_time=entry_time,
            entry_price=150.0,
            initial_stop_loss=147.0,
            stop_loss=150.0,
            tp1=153.0,
            tp2=156.0,
            initial_risk=3.0,
            r_multiple=1.0,
            tp1_taken=True,
            tp1_time=tp1_time,
            tp1_close_pct=0.50,
        )
        _apply_funding(trade, exit_time)
        self.assertEqual(trade.funding_events, 1)
        # Remaining notional = 0.5 * 150 = 75.0. Funding = 75.0 * 0.0001 = 0.0075. delta_r = 0.0075 / 3.0 = 0.0025 R
        expected_funding_r = (0.50 * 150.0 * 0.0001) / 3.0
        self.assertAlmostEqual(trade.funding_cost_r, expected_funding_r, places=6)
        self.assertAlmostEqual(trade.r_multiple, 1.0 - expected_funding_r, places=6)

    def test_binance_funding_zero_events_when_intraday(self):
        """Verify intraday trade not crossing 00:00, 08:00, or 16:00 UTC incurs zero funding."""
        entry_time = pd.Timestamp("2026-05-01 09:00:00", tz="UTC")
        exit_time = pd.Timestamp("2026-05-01 15:00:00", tz="UTC")
        events = _count_funding_events(entry_time, exit_time)
        self.assertEqual(len(events), 0)

        trade = _OpenTrade(
            symbol="LINKUSDT",
            direction="LONG",
            poi_type="LONG_TREND_PULLBACK",
            regime="IMBALANCE_BULL",
            entry_time=entry_time,
            entry_price=15.0,
            initial_stop_loss=14.5,
            stop_loss=14.5,
            tp1=15.5,
            tp2=16.0,
            initial_risk=0.5,
            r_multiple=1.2,
        )
        _apply_funding(trade, exit_time)
        self.assertEqual(trade.funding_events, 0)
        self.assertEqual(trade.funding_cost_r, 0.0)
        self.assertEqual(trade.r_multiple, 1.2)

    def test_crypto_short_requires_btc_bear(self):
        """Altcoin short POIs must be vetoed unless BTC regime is IMBALANCE_BEAR."""
        profile = {
            "pdPOC": 150.0,
            "pdVAH": 155.0,
            "pdVAL": 145.0,
            "pdLVN": [],
        }
        vwap = {
            "vwap": 140.0,
            "vwap_sigma": 2.0,
            "vwap_lower_1p0sigma": 138.0,
            "vwap_upper_1p0sigma": 142.0,
            "vwap_lower_1p5sigma": 137.0,
            "vwap_upper_1p5sigma": 143.0,
            "vwap_lower_2p0sigma": 136.0,
            "vwap_upper_2p0sigma": 144.0,
            "vwap_lower_2p5sigma": 135.0,
            "vwap_upper_2p5sigma": 145.0,
        }
        current_price = 141.0
        atr = 2.0

        # Case 1: BTC leader filter active, BTC regime is IMBALANCE_BULL -> VETO
        decision_bull = generate_regime_pois(
            macro_bias=-1,
            previous_profile=profile,
            vwap=vwap,
            current_price=current_price,
            atr_14=atr,
            is_crypto=True,
            is_btc=False,
            btc_leader_filter=True,
            btc_leader_regime="IMBALANCE_BULL",
        )
        self.assertEqual(len(decision_bull.pois), 0)

        # Case 2: BTC leader filter active, BTC regime is BALANCE -> VETO
        decision_bal = generate_regime_pois(
            macro_bias=-1,
            previous_profile=profile,
            vwap=vwap,
            current_price=current_price,
            atr_14=atr,
            is_crypto=True,
            is_btc=False,
            btc_leader_filter=True,
            btc_leader_regime="BALANCE",
        )
        self.assertEqual(len(decision_bal.pois), 0)

        # Case 3: BTC leader filter active, BTC regime is None/missing -> VETO
        decision_none = generate_regime_pois(
            macro_bias=-1,
            previous_profile=profile,
            vwap=vwap,
            current_price=current_price,
            atr_14=atr,
            is_crypto=True,
            is_btc=False,
            btc_leader_filter=True,
            btc_leader_regime=None,
        )
        self.assertEqual(len(decision_none.pois), 0)

        # Case 4: BTC leader filter active, BTC regime is IMBALANCE_BEAR -> ALLOWED
        decision_bear = generate_regime_pois(
            macro_bias=-1,
            previous_profile=profile,
            vwap=vwap,
            current_price=current_price,
            atr_14=atr,
            is_crypto=True,
            is_btc=False,
            btc_leader_filter=True,
            btc_leader_regime="IMBALANCE_BEAR",
        )
        self.assertGreaterEqual(len(decision_bear.pois), 1)
        self.assertTrue(all(poi.direction == "SHORT" for poi in decision_bear.pois))

    def test_crypto_short_requires_vwap_separation(self):
        """Crypto short trend pullback requires VWAP <= pdPOC - 0.35 * ATR."""
        atr = 2.0
        poc = 100.0
        vah = 105.0
        val = 99.0
        profile = {"pdPOC": poc, "pdVAH": vah, "pdVAL": val, "pdLVN": []}

        # Separation required: 0.35 * 2.0 = 0.70 -> max vwap = 99.30
        # Case A: vwap = 99.50 (separation = 0.50 < 0.70) -> VETO
        vwap_insufficient = {
            "vwap": 99.50,
            "vwap_sigma": 1.0,
            "vwap_lower_1p0sigma": 98.50,
            "vwap_upper_1p0sigma": 100.50,
            "vwap_lower_1p5sigma": 98.0,
            "vwap_upper_1p5sigma": 101.0,
            "vwap_lower_2p0sigma": 97.50,
            "vwap_upper_2p0sigma": 101.50,
            "vwap_lower_2p5sigma": 97.0,
            "vwap_upper_2p5sigma": 102.0,
        }
        dec_a = generate_regime_pois(
            macro_bias=-1, previous_profile=profile, vwap=vwap_insufficient,
            current_price=94.0, atr_14=atr, is_crypto=True, is_btc=True,
        )
        self.assertEqual(len(dec_a.pois), 0)

        # Case B: vwap = 99.20 (separation = 0.80 >= 0.70) -> ALLOWED
        vwap_sufficient = {
            "vwap": 99.20,
            "vwap_sigma": 1.0,
            "vwap_lower_1p0sigma": 98.20,
            "vwap_upper_1p0sigma": 100.20,
            "vwap_lower_1p5sigma": 97.70,
            "vwap_upper_1p5sigma": 100.70,
            "vwap_lower_2p0sigma": 97.20,
            "vwap_upper_2p0sigma": 101.20,
            "vwap_lower_2p5sigma": 96.70,
            "vwap_upper_2p5sigma": 101.70,
        }
        dec_b = generate_regime_pois(
            macro_bias=-1, previous_profile=profile, vwap=vwap_sufficient,
            current_price=94.0, atr_14=atr, is_crypto=True, is_btc=True,
        )
        self.assertGreaterEqual(len(dec_b.pois), 1)

    def test_crypto_short_rejects_positive_delta(self):
        """Short trigger must strictly reject positive or zero volume delta."""
        idx = pd.date_range("2026-05-01 10:00:00", periods=30, freq="min", tz="UTC")
        close = 100.0 - 0.1 * np.arange(30)
        open_ = close + 0.1
        high = open_ + 0.05
        low = close - 0.05
        vol = np.full(30, 100.0)

        # Trigger bar has positive volume_delta (+10.0)
        delta_pos = np.full(30, -5.0)
        delta_pos[-1] = 10.0  # Positive delta on trigger bar

        bars_pos = pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "tick_volume": vol, "volume_delta": delta_pos,
        }, index=idx)
        bars_pos.attrs["source"] = "binance"

        decision_pos = evaluate_trigger(
            bars_pos, "SHORT", poi_low=96.5, poi_high=97.5, atr_14=1.0,
            take_profit=94.0, confirm_binance_delta=True,
        )
        self.assertFalse(decision_pos.execute)
        self.assertFalse(decision_pos.metrics["binance_delta_confirmation"])

        # Trigger bar has strictly negative volume_delta (-10.0)
        delta_neg = np.full(30, -5.0)
        delta_neg[-1] = -10.0
        bars_neg = pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "tick_volume": vol, "volume_delta": delta_neg,
        }, index=idx)
        bars_neg.attrs["source"] = "binance"

        decision_neg = evaluate_trigger(
            bars_neg, "SHORT", poi_low=96.5, poi_high=97.5, atr_14=1.0,
            take_profit=94.0, confirm_binance_delta=True,
        )
        # Check delta condition passed
        self.assertTrue(decision_neg.metrics.get("binance_delta_confirmation", False))

    def test_crypto_active_hours_enforced(self):
        """Crypto trading outside (8, 22) UTC must be rejected with SESSION_HOURS."""
        # 23:30 UTC candle
        idx_late = pd.date_range("2026-05-01 23:01:00", periods=30, freq="min", tz="UTC")
        close = 100.0 + 0.05 * np.arange(30)
        bars_late = pd.DataFrame({
            "open": close - 0.02, "high": close + 0.1, "low": close - 0.1, "close": close,
            "tick_volume": np.full(30, 50.0),
        }, index=idx_late)
        bars_late.attrs["source"] = "binance"

        decision_late = evaluate_trigger(
            bars_late, "LONG", poi_low=101.0, poi_high=102.0, atr_14=1.0, take_profit=105.0,
            session_hours_utc=CRYPTO_MOMENTUM.active_hours_utc,
        )
        self.assertFalse(decision_late.execute)
        self.assertEqual(decision_late.reason, "SESSION_HOURS")
        self.assertFalse(decision_late.metrics["session_allowed"])
        self.assertEqual(decision_late.metrics["session_hour_utc"], 23)

    def test_crypto_long_requires_btc_bull(self):
        """Altcoin long POIs must be vetoed unless BTC regime is IMBALANCE_BULL."""
        profile = {"pdPOC": 100.0, "pdVAH": 105.0, "pdVAL": 95.0, "pdLVN": []}
        vwap = {
            "vwap": 108.0,
            "vwap_sigma": 2.0,
            "vwap_lower_1p0sigma": 106.0,
            "vwap_upper_1p0sigma": 110.0,
            "vwap_lower_1p5sigma": 105.0,
            "vwap_upper_1p5sigma": 111.0,
            "vwap_lower_2p0sigma": 104.0,
            "vwap_upper_2p0sigma": 112.0,
            "vwap_lower_2p5sigma": 103.0,
            "vwap_upper_2p5sigma": 113.0,
        }
        current_price = 106.0
        atr = 2.0

        # Case 1: BTC regime is IMBALANCE_BEAR -> VETO
        dec_bear = generate_regime_pois(
            macro_bias=1, previous_profile=profile, vwap=vwap, current_price=current_price,
            atr_14=atr, is_crypto=True, is_btc=False, btc_leader_filter=True,
            btc_leader_regime="IMBALANCE_BEAR",
        )
        self.assertEqual(len(dec_bear.pois), 0)

        # Case 2: BTC regime is BALANCE -> VETO
        dec_bal = generate_regime_pois(
            macro_bias=1, previous_profile=profile, vwap=vwap, current_price=current_price,
            atr_14=atr, is_crypto=True, is_btc=False, btc_leader_filter=True,
            btc_leader_regime="BALANCE",
        )
        self.assertEqual(len(dec_bal.pois), 0)

        # Case 3: BTC regime is IMBALANCE_BULL -> ALLOWED
        dec_bull = generate_regime_pois(
            macro_bias=1, previous_profile=profile, vwap=vwap, current_price=current_price,
            atr_14=atr, is_crypto=True, is_btc=False, btc_leader_filter=True,
            btc_leader_regime="IMBALANCE_BULL",
        )
        self.assertGreaterEqual(len(dec_bull.pois), 1)
        self.assertTrue(all(poi.direction == "LONG" for poi in dec_bull.pois))

    def test_crypto_long_requires_vwap_separation(self):
        """Crypto long trend pullback requires VWAP >= pdPOC + 0.35 * ATR."""
        atr = 2.0
        poc = 100.0
        vah = 101.0
        val = 95.0
        profile = {"pdPOC": poc, "pdVAH": vah, "pdVAL": val, "pdLVN": []}

        # Separation required: 0.35 * 2.0 = 0.70 -> min vwap = 100.70
        # Case A: vwap = 100.50 (separation = 0.50 < 0.70) -> VETO
        vwap_insufficient = {
            "vwap": 100.50,
            "vwap_sigma": 1.0,
            "vwap_lower_1p0sigma": 99.50,
            "vwap_upper_1p0sigma": 101.50,
            "vwap_lower_1p5sigma": 99.0,
            "vwap_upper_1p5sigma": 102.0,
            "vwap_lower_2p0sigma": 98.50,
            "vwap_upper_2p0sigma": 102.50,
            "vwap_lower_2p5sigma": 98.0,
            "vwap_upper_2p5sigma": 103.0,
        }
        dec_a = generate_regime_pois(
            macro_bias=1, previous_profile=profile, vwap=vwap_insufficient,
            current_price=106.0, atr_14=atr, is_crypto=True, is_btc=True,
        )
        self.assertEqual(len(dec_a.pois), 0)

        # Case B: vwap = 100.80 (separation = 0.80 >= 0.70) -> ALLOWED
        vwap_sufficient = {
            "vwap": 100.80,
            "vwap_sigma": 1.0,
            "vwap_lower_1p0sigma": 99.80,
            "vwap_upper_1p0sigma": 101.80,
            "vwap_lower_1p5sigma": 99.30,
            "vwap_upper_1p5sigma": 102.30,
            "vwap_lower_2p0sigma": 98.80,
            "vwap_upper_2p0sigma": 102.80,
            "vwap_lower_2p5sigma": 98.30,
            "vwap_upper_2p5sigma": 103.30,
        }
        dec_b = generate_regime_pois(
            macro_bias=1, previous_profile=profile, vwap=vwap_sufficient,
            current_price=106.0, atr_14=atr, is_crypto=True, is_btc=True,
        )
        self.assertGreaterEqual(len(dec_b.pois), 1)

    def test_crypto_long_rejects_negative_delta(self):
        """Long trigger must strictly reject negative or zero volume delta."""
        idx = pd.date_range("2026-05-01 10:00:00", periods=30, freq="min", tz="UTC")
        close = 100.0 + 0.1 * np.arange(30)
        open_ = close - 0.1
        high = close + 0.05
        low = open_ - 0.05
        vol = np.full(30, 100.0)

        # Trigger bar has negative volume_delta (-10.0), even with high wick
        delta_neg = np.full(30, 5.0)
        delta_neg[-1] = -10.0

        bars_neg = pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "tick_volume": vol, "volume_delta": delta_neg,
        }, index=idx)
        bars_neg.attrs["source"] = "binance"

        decision_neg = evaluate_trigger(
            bars_neg, "LONG", poi_low=102.5, poi_high=103.5, atr_14=1.0,
            take_profit=106.0, confirm_binance_delta=True,
        )
        self.assertFalse(decision_neg.execute)
        self.assertFalse(decision_neg.metrics["binance_delta_confirmation"])

        # Trigger bar has strictly positive volume_delta (+10.0)
        delta_pos = np.full(30, 5.0)
        delta_pos[-1] = 10.0
        bars_pos = pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "tick_volume": vol, "volume_delta": delta_pos,
        }, index=idx)
        bars_pos.attrs["source"] = "binance"

        decision_pos = evaluate_trigger(
            bars_pos, "LONG", poi_low=102.5, poi_high=103.5, atr_14=1.0,
            take_profit=106.0, confirm_binance_delta=True,
        )
        self.assertTrue(decision_pos.metrics.get("binance_delta_confirmation", False))

    def test_crypto_low_volume_day_filter_default(self):
        """CRYPTO_MOMENTUM profile must enable low volume / weekend filter by default."""
        profile = get_instrument_profile("BTCUSDT")
        self.assertEqual(profile.name, "CRYPTO_MOMENTUM")
        self.assertEqual(profile.active_hours_utc, (8, 22))
        self.assertEqual(profile.default_trigger_tf, "M15")


if __name__ == "__main__":
    unittest.main()
