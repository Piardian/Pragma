import unittest

import pandas as pd

from pragma.backtest_engine import _OpenTrade, _manage_open_trade
from scripts.run_early_be_study import early_be_manager


class EarlyBeStudyTests(unittest.TestCase):
    def position(self, direction="LONG"):
        stamp = pd.Timestamp("2026-10-05T08:00Z")
        stop, tp1, tp2 = (95, 110, 120) if direction == "LONG" else (105, 90, 80)
        return _OpenTrade("X", direction, "T", "R", stamp, 100., stop, stop, tp1, tp2, 5.,
                          entry_at_open=True, funding_rate_8h=0)

    def bar(self, opening, high, low, close):
        return pd.Series(dict(open=opening, high=high, low=low, close=close))

    def test_below_threshold_preserves_stop_and_targets(self):
        p = self.position()
        manage, events = early_be_manager(_manage_open_trade)
        self.assertIsNone(manage(p, self.bar(100, 104, 99, 103), p.entry_time))
        self.assertEqual((p.stop_loss, p.tp1, p.tp2), (95, 110, 120))
        self.assertFalse(events)

    def test_threshold_arms_without_partial_or_target_change(self):
        p = self.position()
        manage, events = early_be_manager(_manage_open_trade)
        self.assertIsNone(manage(p, self.bar(104, 106, 103, 105), p.entry_time))
        self.assertEqual((p.initial_stop_loss, p.stop_loss, p.tp1, p.tp2), (95, 100, 110, 120))
        self.assertFalse(p.tp1_taken)
        self.assertEqual(events[0]["event"], "ARMED")

    def test_activation_bar_retrace_is_flagged_and_costs_money(self):
        p = self.position()
        manage, events = early_be_manager(_manage_open_trade)
        record = manage(p, self.bar(100, 121, 99, 120), p.entry_time, .1)
        self.assertEqual(record.exit_reason, "EARLY_BE_ACTIVATION_BAR_ORDER_ASSUMPTION")
        self.assertTrue(events[0]["intrabar_order_ambiguous"])
        self.assertFalse(record.tp1_taken)
        self.assertAlmostEqual(record.r_multiple, -.1/5)

    def test_original_stop_beats_trigger_when_both_seen(self):
        p = self.position()
        manage, events = early_be_manager(_manage_open_trade)
        record = manage(p, self.bar(100, 106, 94, 105), p.entry_time)
        self.assertEqual(record.exit_reason, "STOP_LOSS")
        self.assertEqual(record.r_multiple, -1)
        self.assertTrue(events[0]["event"].startswith("OLD_STOP"))

    def test_pre_activation_open_is_not_a_later_stop_fill(self):
        p = self.position()
        manage, _ = early_be_manager(_manage_open_trade)
        record = manage(p, self.bar(99, 106, 98, 105), p.entry_time, .1)
        self.assertAlmostEqual(record.r_multiple, -.1/5)

    def test_trigger_already_crossed_at_open_has_known_order(self):
        p = self.position()
        manage, events = early_be_manager(_manage_open_trade)
        record = manage(p, self.bar(106, 107, 99, 100), p.entry_time, .1)
        self.assertEqual(record.exit_reason, "EARLY_BE_TRIGGER_AT_OPEN_STOP")
        self.assertFalse(events[0]["intrabar_order_ambiguous"])

    def test_subsequent_gap_uses_adverse_opening(self):
        p = self.position()
        manage, _ = early_be_manager(_manage_open_trade)
        manage(p, self.bar(104, 106, 103, 105), p.entry_time, .1)
        record = manage(p, self.bar(99, 101, 98, 100), p.entry_time+pd.Timedelta(minutes=1), .1)
        self.assertEqual(record.exit_reason, "EARLY_BREAKEVEN_STOP")
        self.assertAlmostEqual(record.r_multiple, (98.9-100)/5)

    def test_short_side_subsequent_gap_is_symmetric(self):
        p = self.position("SHORT")
        manage, _ = early_be_manager(_manage_open_trade)
        manage(p, self.bar(96, 97, 94, 95), p.entry_time, .1)
        record = manage(p, self.bar(101, 102, 99, 100), p.entry_time+pd.Timedelta(minutes=1), .1)
        self.assertAlmostEqual(record.r_multiple, (100-101.1)/5)

    def test_single_target_positions_unchanged(self):
        p = self.position()
        p.tp1 = p.tp2
        manage, events = early_be_manager(_manage_open_trade)
        self.assertIsNone(manage(p, self.bar(100, 106, 99, 105), p.entry_time))
        self.assertEqual(p.stop_loss, 95)
        self.assertFalse(events)

    def test_runner_reaching_old_targets_keeps_original_profit(self):
        p = self.position()
        manage, _ = early_be_manager(_manage_open_trade)
        manage(p, self.bar(104, 106, 103, 105), p.entry_time)
        record = manage(p, self.bar(110, 121, 109, 120), p.entry_time+pd.Timedelta(minutes=1))
        self.assertTrue(record.tp1_taken)
        self.assertAlmostEqual(record.r_multiple, 3.)
        self.assertEqual((record.tp1, record.tp2), (110, 120))


if __name__ == "__main__":
    unittest.main()
