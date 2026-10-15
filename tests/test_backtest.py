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
                be.run_backtest(frame, symbol="XAUUSD", macro_bias=1, profile_bins=30)
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
        self.assertEqual(report.funnel_counts["trades_opened"], 0)


if __name__ == "__main__":
    unittest.main()
