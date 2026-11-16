from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pragma.shadow_trader import PaperTradingBook


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send_text(self, message):
        self.messages.append(message)


def signal():
    return {
        "execute": True,
        "direction": "LONG",
        "entry_price": 100.0,
        "stop_loss": 99.0,
        "take_profit_1": 102.0,
        "take_profit_2": 104.0,
        "rr_ratio": 4.0,
        "macro_bias": 1,
        "poi_type": "LONG_TREND_PULLBACK",
        "metrics": {"effective_entry": 100.0},
    }


def bar(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close}


class PaperTradingBookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.json"
        self.notifier = FakeNotifier()
        self.book = PaperTradingBook(self.path, initial_balance=10_000, risk_pct=1, notifier=self.notifier)

    def test_open_and_stop_loss_updates_balance(self):
        events = self.book.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100, 100.5, 99.5, 100), [signal()])
        self.assertEqual([event["type"] for event in events], ["OPEN"])
        self.assertAlmostEqual(self.book.state["balance"], 10_000)
        events = self.book.process_bar("EURUSD", "2026-01-01T10:01:00Z", bar(100, 100.2, 98.9, 99.2))
        self.assertEqual(events[0]["outcome"], "SL")
        self.assertAlmostEqual(self.book.state["balance"], 9_900)
        self.assertEqual(len(self.book.state["closed_trades"]), 1)
        self.assertAlmostEqual(self.book.state["closed_trades"][0]["realized_r"], -1.0)

    def test_tp1_then_breakeven_preserves_partial_profit(self):
        self.book.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100, 100.5, 99.5, 100), [signal()])
        events = self.book.process_bar("EURUSD", "2026-01-01T10:01:00Z", bar(100, 102.1, 100.2, 101.5))
        self.assertEqual(events[0]["type"], "TP1")
        self.assertTrue(self.book.state["open_positions"]["EURUSD"]["tp1_done"])
        self.assertAlmostEqual(self.book.state["balance"], 10_100)
        events = self.book.process_bar("EURUSD", "2026-01-01T10:02:00Z", bar(101, 101.2, 99.9, 100.1))
        self.assertEqual(events[0]["outcome"], "BE")
        self.assertAlmostEqual(self.book.state["balance"], 10_100)
        self.assertAlmostEqual(self.book.state["closed_trades"][0]["realized_r"], 1.0)

    def test_same_bar_stop_wins_over_target(self):
        self.book.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100, 100.5, 99.5, 100), [signal()])
        events = self.book.process_bar("EURUSD", "2026-01-01T10:01:00Z", bar(100, 103, 98.5, 101))
        self.assertEqual(events[0]["outcome"], "SL")
        self.assertAlmostEqual(self.book.state["balance"], 9_900)

    def test_duplicate_bar_and_restart_are_idempotent(self):
        self.book.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100, 100.5, 99.5, 100), [signal()])
        duplicate = self.book.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100, 103, 98, 100), [signal()])
        self.assertEqual(duplicate, [])
        restored = PaperTradingBook(self.path, initial_balance=1, risk_pct=2, notifier=FakeNotifier())
        self.assertAlmostEqual(restored.state["balance"], 10_000)
        self.assertIn("EURUSD", restored.state["open_positions"])
        self.assertEqual(restored.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100, 103, 98, 100), [signal()]), [])
        self.assertEqual(len(restored.state["open_positions"]), 1)

    def test_scoreboard_included_in_close_notification(self):
        self.book.process_bar("EURUSD", "2026-10-01T10:00:00Z", bar(100, 100.5, 99.5, 100), [signal()])
        self.book.process_bar("EURUSD", "2026-10-01T10:01:00Z", bar(100, 100.2, 98.9, 99.2))
        self.assertEqual(len(self.notifier.messages), 2)  # OPEN + SL
        close_msg = self.notifier.messages[-1]
        self.assertIn("PERFORMANS SAYACI", close_msg)
        self.assertIn("Net R", close_msg)
        self.assertIn("-1.00R", close_msg)
        self.assertIn("SL (Zarar Kes): 1", close_msg)

    def test_tp2_takes_25_pct_and_runner_trailing_exits(self):
        self.book.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100, 100.5, 99.5, 100), [signal()])
        # Hit TP1 (102.0) -> +2R on 50% = +100$, SL moves to BE (100)
        self.book.process_bar("EURUSD", "2026-01-01T10:01:00Z", bar(100, 102.1, 100.2, 101.5))
        self.assertAlmostEqual(self.book.state["balance"], 10_100)
        self.assertEqual(self.book.state["open_positions"]["EURUSD"]["remaining_fraction"], 0.5)

        # Hit TP2 (104.0) -> +4R on 25% = +100$, 25% remaining as runner, trailing stop active
        events_tp2 = self.book.process_bar("EURUSD", "2026-01-01T10:02:00Z", bar(102, 104.2, 101.8, 104))
        self.assertEqual(events_tp2[0]["type"], "TP2")
        self.assertAlmostEqual(self.book.state["balance"], 10_200)
        pos = self.book.state["open_positions"]["EURUSD"]
        self.assertTrue(pos["trailing_active"])
        self.assertAlmostEqual(pos["remaining_fraction"], 0.25)

        # Price advances to 105.0 -> Trailing stop tightens to 105 - 0.75 = 104.25
        self.book.process_bar("EURUSD", "2026-01-01T10:03:00Z", bar(104, 105.0, 103.8, 104.8))
        self.assertAlmostEqual(self.book.state["open_positions"]["EURUSD"]["stop_loss"], 104.25)

        # Price drops and hits trailing stop at 104.25 -> +4.25R on 25% = +106.25$
        events_trail = self.book.process_bar("EURUSD", "2026-01-01T10:04:00Z", bar(104.5, 104.6, 104.0, 104.1))
        self.assertEqual(events_trail[0]["outcome"], "TRAILING_STOP")
        self.assertAlmostEqual(self.book.state["balance"], 10_306.25)
        self.assertEqual(len(self.book.state["closed_trades"]), 1)
        self.assertAlmostEqual(self.book.state["closed_trades"][0]["realized_r"], 3.0625)

    def test_low_rr_below_1_to_2_is_rejected(self):
        low_rr_sig = signal()
        low_rr_sig["take_profit_1"] = 101.0  # 1.0 R
        low_rr_sig["take_profit_2"] = 101.5  # 1.5 R (below 2.0 R!)
        low_rr_sig["rr_ratio"] = 1.5
        events = self.book.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100, 100.5, 99.5, 100), [low_rr_sig])
        self.assertEqual(events, [])
        self.assertEqual(len(self.book.state["open_positions"]), 0)

    def test_begonya_macro_veto_rejects_opposite_signal(self):
        veto_sig = signal()
        veto_sig["macro_bias"] = -1  # Begonya says SHORT_ONLY, but signal is LONG
        events = self.book.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100, 100.5, 99.5, 100), [veto_sig])
        self.assertEqual(events, [])
        self.assertEqual(len(self.book.state["open_positions"]), 0)


if __name__ == "__main__":
    unittest.main()
