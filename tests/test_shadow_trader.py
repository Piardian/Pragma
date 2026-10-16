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
        self.assertEqual(events[0]["outcome"], "SL")
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

    def test_tp2_closes_remaining_half(self):
        self.book.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100, 100.5, 99.5, 100), [signal()])
        self.book.process_bar("EURUSD", "2026-01-01T10:01:00Z", bar(100, 102.1, 100.2, 101.5))
        events = self.book.process_bar("EURUSD", "2026-01-01T10:02:00Z", bar(102, 104.2, 101.8, 104))
        self.assertEqual(events[0]["outcome"], "TP2")
        self.assertAlmostEqual(self.book.state["balance"], 10_300)
        self.assertAlmostEqual(self.book.state["closed_trades"][0]["realized_r"], 3.0)


if __name__ == "__main__":
    unittest.main()
