from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from pragma.analytics import analyze_trade_journal, format_analytics_report
from pragma.shadow_trader import PaperTradingBook
from pragma.trade_journal import (
    load_rejected_signals,
    load_trade_journal,
    record_rejected_signal,
    record_trade_to_journal,
)


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send_text(self, message):
        self.messages.append(message)


def sample_signal(execute=True, direction="LONG", entry=100.0, sl=99.0, tp1=102.0, tp2=104.0):
    return {
        "execute": execute,
        "direction": direction,
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "poi_type": "LONG_TREND_PULLBACK",
        "regime": "TRENDING_EXPANSION",
        "macro_bias": 1,
        "rr_planned": 2.0,
        "z_score": 1.25,
        "volume_multiplier": 1.8,
        "order_flow_delta": 45.0,
        "atr": 0.5,
        "vwap": 99.8,
        "pdpoc": 99.5,
        "metrics": {"effective_entry": entry},
    }


def sample_rejection():
    return {
        "timestamp": "2026-01-01T10:00:00Z",
        "symbol": "EURUSD",
        "direction": "LONG",
        "poi_type": "LONG_VALUE_REVERSAL",
        "reason": "REJECT_WICK_ONLY",
        "details": "candle wick pierced POI without body close",
        "entry_candidate": 100.0,
        "stop_loss_candidate": 99.0,
        "rr_candidate": 1.5,
        "z_score": 2.3,
        "volume_multiplier": 0.8,
        "order_flow_delta": -12.0,
        "atr": 0.45,
        "vwap": 100.2,
        "pdpoc": 100.5,
    }


def bar(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close}


class TradeJournalAndAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.temp_dir = Path(self.temp.name)
        self.state_path = self.temp_dir / "state.json"
        self.journal_path = self.temp_dir / "trade_journal.csv"
        self.rejected_path = self.temp_dir / "rejected_signals.csv"
        self.notifier = FakeNotifier()
        self.book = PaperTradingBook(
            self.state_path,
            initial_balance=10_000,
            risk_pct=1,
            notifier=self.notifier,
            journal_path=self.journal_path,
            rejected_path=self.rejected_path,
        )

    def test_record_and_load_rejected_signals(self):
        rej = sample_rejection()
        record_rejected_signal(self.rejected_path, rej)
        record_rejected_signal(self.rejected_path, rej)  # second row

        df = load_rejected_signals(self.rejected_path)
        self.assertEqual(len(df), 2)
        self.assertIn("reason", df.columns)
        self.assertEqual(df["reason"].iloc[0], "REJECT_WICK_ONLY")
        self.assertAlmostEqual(df["z_score"].iloc[0], 2.3)

    def test_trade_lifecycle_records_to_journal_with_mae_mfe(self):
        # Open LONG trade at 100.0, SL=99.0, TP1=102.0, TP2=104.0 (Risk = 1.0)
        sig = sample_signal()
        self.book.process_bar("EURUSD", "2026-01-01T10:00:00Z", bar(100.0, 100.5, 99.5, 100.0), [sig])
        pos = self.book.state["open_positions"]["EURUSD"]
        self.assertEqual(pos["bars_held"], 0)

        # Bar 2: price dips to 99.2 (MAE = 0.8) and peaks at 101.5 (MFE = 1.5)
        self.book.process_bar("EURUSD", "2026-01-01T10:01:00Z", bar(100.0, 101.5, 99.2, 101.0))
        pos = self.book.state["open_positions"]["EURUSD"]
        self.assertEqual(pos["bars_held"], 1)
        self.assertAlmostEqual(pos["mae_r"], 0.8, places=3)
        self.assertAlmostEqual(pos["mfe_r"], 1.5, places=3)

        # Bar 3: Hits TP1 at 102.0
        self.book.process_bar("EURUSD", "2026-01-01T10:02:00Z", bar(101.0, 102.5, 100.5, 102.2))
        pos = self.book.state["open_positions"]["EURUSD"]
        self.assertTrue(pos["tp1_done"])

        # Bar 4: Hits TP2 at 104.0 -> trade closes
        events = self.book.process_bar("EURUSD", "2026-01-01T10:03:00Z", bar(102.2, 104.2, 102.0, 104.0))
        self.assertEqual(events[0]["outcome"], "TP2")
        self.assertEqual(len(self.book.state["closed_trades"]), 1)

        # Verify trade_journal.csv was written automatically
        self.assertTrue(self.journal_path.exists())
        df = load_trade_journal(self.journal_path)
        self.assertEqual(len(df), 1)
        row = df.iloc[0]
        self.assertEqual(row["symbol"], "EURUSD")
        self.assertEqual(row["direction"], "LONG")
        self.assertEqual(row["outcome"], "TP2")
        self.assertEqual(row["bars_held"], 3)
        self.assertAlmostEqual(row["mae_r"], 0.8, places=3)
        self.assertAlmostEqual(row["mfe_r"], 4.2, places=3)  # high was 104.2 -> (104.2-100)/1 = 4.2
        self.assertAlmostEqual(row["realized_r"], 3.0, places=3)  # 0.5 * 2R + 0.5 * 4R = 3.0R

    def test_analytics_metrics_and_feature_attribution(self):
        # Create a synthetic dataset with winning (TP) and losing (SL) trades
        trades = [
            {
                "trade_id": "T1",
                "symbol": "EURUSD",
                "direction": "LONG",
                "entry_time": "2026-01-01T10:00:00Z",
                "exit_time": "2026-01-01T10:15:00Z",
                "entry_price": 100.0,
                "exit_price": 104.0,
                "initial_sl": 99.0,
                "final_sl": 100.0,
                "tp1": 102.0,
                "tp2": 104.0,
                "planned_rr": 2.0,
                "realized_r": 3.0,
                "realized_pnl": 300.0,
                "outcome": "TP2",
                "bars_held": 15,
                "mae_r": 0.2,
                "mfe_r": 4.1,
                "poi_type": "LONG_TREND_PULLBACK",
                "regime": "TRENDING_EXPANSION",
                "macro_bias": 1,
                "z_score": 1.2,
                "volume_multiplier": 2.2,
                "order_flow_delta": 60.0,
                "atr": 0.5,
                "vwap": 99.8,
                "pdpoc": 99.5,
                "balance_after": 10300.0,
            },
            {
                "trade_id": "T2",
                "symbol": "EURUSD",
                "direction": "LONG",
                "entry_time": "2026-01-01T11:00:00Z",
                "exit_time": "2026-01-01T11:05:00Z",
                "entry_price": 100.0,
                "exit_price": 99.0,
                "initial_sl": 99.0,
                "final_sl": 99.0,
                "tp1": 102.0,
                "tp2": 104.0,
                "planned_rr": 2.0,
                "realized_r": -1.0,
                "realized_pnl": -100.0,
                "outcome": "SL",
                "bars_held": 5,
                "mae_r": 1.0,
                "mfe_r": 0.1,
                "poi_type": "LONG_TREND_PULLBACK",
                "regime": "TRENDING_EXPANSION",
                "macro_bias": 1,
                "z_score": 2.8,
                "volume_multiplier": 0.9,
                "order_flow_delta": -15.0,
                "atr": 0.5,
                "vwap": 99.9,
                "pdpoc": 99.6,
                "balance_after": 10200.0,
            },
        ]
        for t in trades:
            record_trade_to_journal(self.journal_path, t)

        report = analyze_trade_journal(self.journal_path)
        self.assertEqual(report["total_trades"], 2)
        self.assertEqual(report["win_rate"], 50.0)
        self.assertAlmostEqual(report["total_r"], 2.0)
        self.assertAlmostEqual(report["profit_factor"], 3.0)

        # Check feature attribution: TP vs SL
        fa = report["feature_comparison"]
        self.assertAlmostEqual(fa["z_score"]["win_avg"], 1.2)
        self.assertAlmostEqual(fa["z_score"]["loss_avg"], 2.8)
        self.assertAlmostEqual(fa["volume_multiplier"]["win_avg"], 2.2)
        self.assertAlmostEqual(fa["volume_multiplier"]["loss_avg"], 0.9)

        # Check ASCII report formatter runs without exception
        text = format_analytics_report(report)
        self.assertIn("PRAGMA", text)
        self.assertIn("KÖK NEDEN VE KARAKTERİSTİK ANALİZİ".encode("ascii", "ignore").decode("ascii"), text.encode("ascii", "ignore").decode("ascii"))
        self.assertIn("POI", text)


if __name__ == "__main__":
    unittest.main()
