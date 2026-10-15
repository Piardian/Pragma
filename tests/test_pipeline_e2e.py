import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from pragma.data.mt5_data import filter_closed_bars
from pragma.execution_notifier import ExecutionNotifier, SignalDeduplicator, format_signal_message
from pragma.run_pipeline import run_pipeline
from pragma.trigger_engine import _select_targets


class ClosedBarTests(unittest.TestCase):
    def test_forming_bar_is_removed(self):
        now = pd.Timestamp("2026-10-15T12:03:20Z")
        bars = pd.DataFrame(
            {"close": [1.0, 2.0, 3.0]},
            index=pd.to_datetime([
                "2026-10-15T12:00:00Z",
                "2026-10-15T12:01:00Z",
                "2026-10-15T12:03:00Z",
            ]),
        )
        result = filter_closed_bars(bars, "M1", now=now)
        self.assertEqual(result.close.tolist(), [1.0, 2.0])
        self.assertEqual(result.index[-1], pd.Timestamp("2026-10-15T12:01:00Z"))

    def test_m15_forming_bar_is_removed(self):
        now = pd.Timestamp("2026-10-15T12:30:10Z")
        bars = pd.DataFrame(
            {"close": [1.0, 2.0, 3.0]},
            index=pd.to_datetime([
                "2026-10-15T12:00:00Z",
                "2026-10-15T12:15:00Z",
                "2026-10-15T12:30:00Z",
            ]),
        )
        result = filter_closed_bars(bars, "M15", now=now)
        self.assertEqual(result.close.tolist(), [1.0])


class TargetSelectionTests(unittest.TestCase):
    def test_long_targets_are_sorted_nearest_first(self):
        self.assertEqual(_select_targets([112.0, 105.0, 99.0, 108.0], "LONG", 100.0),
                         (105.0, 112.0))

    def test_short_targets_are_sorted_nearest_first(self):
        self.assertEqual(_select_targets([88.0, 95.0, 101.0, 92.0], "SHORT", 100.0),
                         (95.0, 88.0))

    def test_single_target_is_both_tp1_and_tp2(self):
        self.assertEqual(_select_targets([105.0], "LONG", 100.0), (105.0, 105.0))


class NotifierTests(unittest.TestCase):
    def test_deduplication_and_console_fallback(self):
        poi = {"poi_type": "LONG_MEAN_REVERSION", "poi_low": 99.0, "poi_high": 100.0}
        decision = {
            "execute": True, "direction": "LONG", "entry_price": 99.5,
            "stop_loss": 98.0, "take_profit_1": 102.0, "take_profit_2": 105.0,
            "take_profit": 102.0, "rr_ratio": 1.67,
            "metrics": {"z_score": -1.2, "volume_multiplier": 2.1},
        }
        dedup = SignalDeduplicator()
        notifier = ExecutionNotifier(bot_token="", chat_id="", deduplicator=dedup)
        bar_time = pd.Timestamp("2026-10-15T12:01:00Z")
        with patch("builtins.print") as output:
            first = notifier.notify("XAUUSD", poi, decision, "BALANCE", bar_time)
            second = notifier.notify("XAUUSD", poi, decision, "BALANCE", bar_time)
        self.assertTrue(first["sent"])
        self.assertEqual(first["channel"], "console")
        self.assertEqual(second["reason"], "DUPLICATE")
        self.assertEqual(output.call_count, 1)

    def test_message_contains_required_quantitative_fields(self):
        poi = {"poi_type": "LONG_TREND_PULLBACK", "poi_low": 100.0, "poi_high": 101.0}
        decision = {
            "execute": True, "direction": "LONG", "entry_price": 100.5,
            "stop_loss": 99.0, "take_profit_1": 104.0, "take_profit_2": 104.0,
            "take_profit": 104.0, "rr_ratio": 2.33,
            "metrics": {"z_score": -1.1, "volume_multiplier": 2.0},
        }
        message = format_signal_message("XAUUSD", poi, decision, "IMBALANCE_BULL",
                                        datetime(2026, 10, 15, 12, 1, tzinfo=timezone.utc))
        for required in ("XAUUSD", "LONG", "IMBALANCE_BULL", "LONG_TREND_PULLBACK",
                         "Giriş:", "SL:", "TP1:", "TP2:", "R:R", "Z-Score",
                         "Hacim çarpanı"):
            self.assertIn(required, message)


class PipelineE2ETests(unittest.TestCase):
    def test_dry_run_executes_full_pipeline_without_mt5(self):
        now = pd.Timestamp("2026-10-15T16:00:00Z")
        result = run_pipeline(dry_run=True, macro_bias=1, profile_bins=40, now=now)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["macro"]["bias"], 1)
        self.assertGreaterEqual(result["bars"]["m1_closed_count"], 30)
        self.assertGreaterEqual(result["bars"]["m15_closed_count"], 15)
        self.assertTrue(result["bars"]["forming_m1_excluded"])
        self.assertIn(result["regime"], ("BALANCE", "IMBALANCE_BULL",
                                         "IMBALANCE_BEAR", "TRANSITION"))
        self.assertIn("pdPOC", result["previous_session"])
        self.assertIn("lower_1p5sigma", result["vwap"])
        self.assertIsInstance(result["pois"], list)
        self.assertIsInstance(result["triggers"], list)
        self.assertIsInstance(result["notifications"], list)

    def test_invalid_macro_bias_rejected(self):
        with self.assertRaises(ValueError):
            run_pipeline(dry_run=True, macro_bias=2)


if __name__ == "__main__":
    unittest.main()
