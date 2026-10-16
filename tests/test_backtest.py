import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
import pandas as pd

from pragma import backtest_engine as be


class TradePathTests(unittest.TestCase):
    @staticmethod
    def position():
        return be._OpenTrade(
            symbol="XAUUSD", direction="LONG", poi_type="LONG_MEAN_REVERSION",
            regime="BALANCE", entry_time=pd.Timestamp("2026-10-01T10:00:00Z"),
            entry_price=100.0, initial_stop_loss=95.0, stop_loss=95.0,
            tp1=105.0, tp2=110.0, initial_risk=5.0,
        )

    @staticmethod
    def bar(low, high, close=103.0):
        return pd.Series({"open": close, "high": high, "low": low,
                          "close": close, "tick_volume": 10.0})

    def test_tp1_partial_then_tp2_closes_remaining_half(self):
        position = self.position()
        first = be._manage_open_trade(
            position, self.bar(101.0, 106.0),
            pd.Timestamp("2026-10-01T10:01:00Z")
        )
        self.assertIsNone(first)
        self.assertTrue(position.tp1_taken)
        self.assertEqual(position.stop_loss, position.entry_price)
        self.assertAlmostEqual(position.r_multiple, 0.5)

        final = be._manage_open_trade(
            position, self.bar(101.0, 111.0),
            pd.Timestamp("2026-10-01T10:02:00Z")
        )
        self.assertIsNotNone(final)
        self.assertEqual(final.exit_reason, "TAKE_PROFIT_2")
        self.assertAlmostEqual(final.r_multiple, 1.5)

    def test_breakeven_closes_remaining_half_after_tp1(self):
        position = self.position()
        be._manage_open_trade(
            position, self.bar(101.0, 106.0),
            pd.Timestamp("2026-10-01T10:01:00Z")
        )
        final = be._manage_open_trade(
            position, self.bar(99.0, 103.0),
            pd.Timestamp("2026-10-01T10:02:00Z")
        )
        self.assertIsNotNone(final)
        self.assertEqual(final.exit_reason, "BREAKEVEN_STOP")
        self.assertAlmostEqual(final.r_multiple, 0.5)

    def test_stop_loss_has_priority_when_sl_and_tp_hit_same_bar(self):
        position = self.position()
        final = be._manage_open_trade(
            position, self.bar(94.0, 111.0),
            pd.Timestamp("2026-10-01T10:01:00Z")
        )
        self.assertIsNotNone(final)
        self.assertEqual(final.exit_reason, "STOP_LOSS")
        self.assertAlmostEqual(final.r_multiple, -1.0)
        self.assertFalse(final.tp1_taken)

    def test_same_tp1_tp2_target_closes_full_position(self):
        position = self.position()
        position.tp1 = position.tp2 = 110.0
        final = be._manage_open_trade(
            position, self.bar(99.0, 111.0),
            pd.Timestamp("2026-10-01T10:01:00Z")
        )
        self.assertIsNotNone(final)
        self.assertEqual(final.exit_reason, "TAKE_PROFIT_2_SINGLE_TARGET")
        self.assertAlmostEqual(final.r_multiple, 2.0)

    def test_spread_cost_is_applied_adversely(self):
        position = self.position()
        final = be._manage_open_trade(
            position, self.bar(94.0, 111.0),
            pd.Timestamp("2026-10-01T10:01:00Z"), cost=0.1
        )
        self.assertIsNotNone(final)
        self.assertLess(final.r_multiple, -1.0)


class WalkForwardTests(unittest.TestCase):
    def test_future_bars_do_not_change_earlier_decision_inputs(self):
        base = be._synthetic_bars(
            1500, end_time=pd.Timestamp("2026-10-02T01:00:00Z")
        )
        changed = base.copy()
        # Alter only future bars after the first 30 minutes of the second day.
        changed.iloc[1471:, changed.columns.get_indexer(["open", "high", "low", "close"])] += 1000.0

        def capture(frame):
            observed = []
            def fake_generate(bias, profile, vwap, price, atr, **kwargs):
                observed.append((
                    profile["pdPOC"], profile["pdVAH"], profile["pdVAL"],
                    float(vwap["vwap"]), float(vwap["vwap_sigma"]), float(atr), float(price)
                ))
                return SimpleNamespace(pois=(), regime=SimpleNamespace(value="BALANCE"))
            with patch.object(be, "generate_regime_pois", side_effect=fake_generate):
                be.run_backtest(frame, symbol="XAUUSD", macro_bias=1, profile_bins=30, trigger_tf="M1")
            return observed

        original_inputs = capture(base)
        changed_inputs = capture(changed)
        # Each run has no decisions in the first observed session. Compare the
        # first 30 decision snapshots in the next session, before the mutation.
        self.assertGreaterEqual(len(original_inputs), 30)
        self.assertGreaterEqual(len(changed_inputs), 30)
        np.testing.assert_allclose(
            np.asarray(original_inputs[:30], dtype=float),
            np.asarray(changed_inputs[:30], dtype=float),
            rtol=0, atol=1e-10,
        )

    def test_report_handles_no_trades(self):
        bars = be._synthetic_bars(
            1500, end_time=pd.Timestamp("2026-10-02T01:00:00Z")
        )
        with patch.object(
            be, "generate_regime_pois",
            return_value=SimpleNamespace(pois=(), regime=SimpleNamespace(value="BALANCE")),
        ):
            report = be.run_backtest(bars, symbol="XAUUSD", macro_bias=1, profile_bins=30)
        self.assertEqual(report.total_trades, 0)
        self.assertEqual(report.net_r, 0.0)
        self.assertEqual(report.expectancy_r, 0.0)
        self.assertIn("sessions_evaluated", report.funnel_counts)
        self.assertIn("rejected_session_hours", report.funnel_counts)
        self.assertEqual(report.funnel_counts["trades_opened"], 0)


class OptimizationAndLeaderFilterTests(unittest.TestCase):
    def test_precompute_atr14_matches_pointwise_atr14(self):
        dates = pd.date_range("2026-10-01", periods=50, freq="15min", tz="UTC")
        np.random.seed(42)
        m15 = pd.DataFrame({
            "open": np.random.uniform(100, 200, 50),
            "high": np.random.uniform(200, 300, 50),
            "low": np.random.uniform(50, 100, 50),
            "close": np.random.uniform(100, 200, 50),
        }, index=dates)
        precomputed = be._precompute_m15_atr14(m15)
        self.assertEqual(len(precomputed), len(m15))
        for i in range(14):
            self.assertTrue(np.isnan(precomputed[i]))
        for i in range(14, len(m15)):
            pointwise = be._atr14(m15.iloc[:i + 1])
            self.assertIsNotNone(pointwise)
            self.assertAlmostEqual(precomputed[i], pointwise, places=9)

    def test_btc_leader_filter_suppresses_counter_trend(self):
        bars = be._synthetic_bars(1500, end_time=pd.Timestamp("2026-10-02T01:00:00Z"))
        btc_regimes = {t: "IMBALANCE_BEAR" for t in bars.index}
        with patch.object(
            be, "generate_regime_pois",
            return_value=SimpleNamespace(
                pois=(SimpleNamespace(
                    direction="LONG", poi_type="LONG_TREND_PULLBACK",
                    poi_low=100.0, poi_high=102.0, take_profits=(110.0, 115.0),
                    center=101.0,
                ),),
                regime=SimpleNamespace(value="IMBALANCE_BULL")
            ),
        ), patch.object(
            be, "evaluate_trigger",
            return_value=SimpleNamespace(
                execute=True, stop_loss=95.0, take_profit_1=110.0, take_profit_2=115.0,
                metrics={"poi_touched": True, "z_condition": True, "volume_climax": True, "rejection": True},
                reason=None,
            ),
        ):
            # With btc_leader_filter against ETHUSDT: LONG is suppressed
            report_eth = be.run_backtest(
                bars, symbol="ETHUSDT", macro_bias=1, profile_bins=30,
                btc_regimes=btc_regimes,
            )
            self.assertEqual(report_eth.total_trades, 0)

            # For BTCUSDT itself, leader filter does not suppress
            report_btc = be.run_backtest(
                bars, symbol="BTCUSDT", macro_bias=1, profile_bins=30,
                btc_regimes=btc_regimes,
            )
            self.assertGreater(report_btc.total_trades, 0)


if __name__ == "__main__":
    unittest.main()
