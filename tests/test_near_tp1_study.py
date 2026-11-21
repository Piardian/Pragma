import unittest
from dataclasses import asdict

import pandas as pd

from pragma.backtest_engine import _OpenTrade, _manage_open_trade
from pragma.measurement import ExecutionCosts
from pragma.research_measurement import replay_fixed_entries
from scripts.run_near_tp1_study import capped_tp1, adjusted_trade, near_tp1_manager


class NearTp1StudyTests(unittest.TestCase):
    def position(self):
        stamp = pd.Timestamp("2026-10-05T08:00Z")
        return _OpenTrade("X", "LONG", "T", "R", stamp, 100., 95., 95., 110., 120., 5.,
                          entry_at_open=True, funding_rate_8h=0,
                          signal_bar_time=(stamp-pd.Timedelta(minutes=1)).isoformat(), decision_time=stamp.isoformat())

    def test_long_and_short_cap_at_actual_entry_risk(self):
        self.assertEqual(capped_tp1("LONG", 100, 95, 110, 120), 105)
        self.assertEqual(capped_tp1("SHORT", 100, 105, 90, 80), 95)

    def test_already_near_target_is_not_moved_farther(self):
        self.assertEqual(capped_tp1("LONG", 100, 95, 103, 120), 103)

    def test_single_target_trade_keeps_original_full_exit(self):
        self.assertEqual(capped_tp1("LONG", 100, 95, 120, 120), 120)

    def test_invalid_stop_geometry_rejected(self):
        with self.assertRaisesRegex(ValueError, "geometry"):
            capped_tp1("LONG", 100, 105, 110, 120)

    def test_fill_bar_stop_still_beats_both_targets(self):
        p = self.position()
        manage, changes = near_tp1_manager(_manage_open_trade)
        record = manage(p, pd.Series(dict(open=100, low=94, high=130, close=125)), p.entry_time)
        self.assertEqual(record.exit_reason, "STOP_LOSS")
        self.assertEqual(record.r_multiple, -1)
        self.assertEqual(changes[0]["new_tp1"], 105)

    def test_partial_then_same_bar_be_keeps_existing_priority_and_cost(self):
        p = self.position()
        manage, _ = near_tp1_manager(_manage_open_trade)
        record = manage(p, pd.Series(dict(open=100, low=99, high=106, close=105)), p.entry_time, .1, 0, False)
        self.assertTrue(record.tp1_taken)
        self.assertEqual(record.exit_reason, "TP1_THEN_BREAKEVEN_SAME_BAR")
        self.assertAlmostEqual(record.r_multiple, (.5*4.9 + .5*(-.1))/5)

    def test_target_assigned_once_and_tp2_stop_entry_unchanged(self):
        p = self.position()
        manage, changes = near_tp1_manager(lambda *args, **kwargs: None)
        bar = pd.Series(dict(open=100, low=99, high=101, close=100))
        manage(p, bar, p.entry_time)
        manage(p, bar, p.entry_time+pd.Timedelta(minutes=1))
        self.assertEqual(len(changes), 1)
        self.assertEqual((p.entry_price, p.initial_stop_loss, p.stop_loss, p.tp2, p.tp1_close_pct), (100, 95, 95, 120, .5))

    def test_fixed_entry_replay_matches_streaming_policy(self):
        p = self.position()
        ix = pd.date_range(p.entry_time, periods=3, freq="min")
        bars = pd.DataFrame(dict(open=[100, 104, 105], high=[101, 106, 121],
                                 low=[99, 103, 104], close=[100, 105, 120]), index=ix)
        manage, _ = near_tp1_manager(_manage_open_trade)
        record = None
        for stamp, bar in bars.iterrows():
            record = manage(p, bar, stamp)
            if record:
                break
        original_shape = asdict(record)
        original_shape["tp1"] = 110
        modified = adjusted_trade(original_shape)
        replay = replay_fixed_entries(bars, [modified], ExecutionCosts(), be_offset_r=0)[0]
        self.assertEqual(replay["exit_reason"], record.exit_reason)
        self.assertAlmostEqual(replay["r_multiple"], record.r_multiple)
        self.assertEqual(replay["fill_time"], original_shape["fill_time"])


if __name__ == "__main__":
    unittest.main()
