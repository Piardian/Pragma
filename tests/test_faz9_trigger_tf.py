"""FAZ 9 regression tests for trigger resampling and trade outcome diagnostics."""
import unittest

import pandas as pd

from pragma.backtest_engine import (
    BacktestTrade,
    _make_report,
    _resample_tf,
)


class TriggerTimeframeTests(unittest.TestCase):
    def test_m5_resampling_aggregates_ohlcv_and_does_not_invent_partial_bar(self):
        index = pd.date_range("2026-01-01T00:00:00Z", periods=10, freq="min")
        frame = pd.DataFrame({
            "open": range(100, 110),
            "high": range(101, 111),
            "low": range(99, 109),
            "close": range(100, 110),
            "tick_volume": [1] * 10,
        }, index=index)
        result = _resample_tf(frame, "M5")
        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["open"], 100)
        self.assertEqual(result.iloc[0]["high"], 105)
        self.assertEqual(result.iloc[0]["low"], 99)
        self.assertEqual(result.iloc[0]["close"], 104)
        self.assertEqual(result.iloc[0]["tick_volume"], 5)
        self.assertEqual(result.iloc[1]["open"], 105)
        self.assertEqual(result.iloc[1]["close"], 109)

    def test_invalid_trigger_timeframe_is_rejected(self):
        index = pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="min")
        frame = pd.DataFrame({
            "open": [1, 1], "high": [2, 2], "low": [0, 0],
            "close": [1, 1], "tick_volume": [1, 1],
        }, index=index)
        with self.assertRaises(ValueError):
            _resample_tf(frame, "M3")


class TradeOutcomeTests(unittest.TestCase):
    @staticmethod
    def trade(reason, tp1_taken, r):
        return BacktestTrade(
            symbol="XAUUSD", direction="LONG", poi_type="BALANCE",
            regime="BALANCE", entry_time="2026-01-01T00:00:00+00:00",
            exit_time="2026-01-01T00:05:00+00:00", entry_price=100.0,
            initial_stop_loss=99.0, tp1=101.0, tp2=102.0,
            exit_reason=reason, r_multiple=r, tp1_taken=tp1_taken,
        )

    def test_trade_outcomes_are_counted_by_exit_path(self):
        trades = [
            self.trade("STOP_LOSS", False, -1.0),
            self.trade("BREAKEVEN_STOP", True, 0.5),
            self.trade("TAKE_PROFIT_2", True, 1.5),
            self.trade("END_OF_DATA", False, 0.2),
        ]
        report = _make_report("XAUUSD", 1000, trades, 15, 0.01)
        self.assertEqual(report.trade_outcomes, {
            "full_sl_hits": 1,
            "tp1_then_be_hits": 1,
            "full_tp2_hits": 1,
        })


if __name__ == "__main__":
    unittest.main()
