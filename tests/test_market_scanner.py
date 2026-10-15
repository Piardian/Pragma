import unittest
from datetime import datetime, timezone

from pragma.market_scanner import resolve_symbols, seconds_until_next_boundary


class MarketScannerTests(unittest.TestCase):
    def test_resolves_exact_symbols_and_broker_suffixes(self):
        resolved = resolve_symbols(
            ["XAUUSD", "EURUSD", "BTC", "SPX"],
            ["EURUSD.a", "EURUSDm", "XAUUSD", "BTCUSD", "SPX500"],
        )
        self.assertEqual(resolved, ["BTCUSD", "EURUSD.a", "SPX500", "XAUUSD"])

    def test_ignores_gate_symbols_not_available_in_mt5(self):
        resolved = resolve_symbols(["XAUUSD", "EURUSD", "SOL"], ["XAUUSD"])
        self.assertEqual(resolved, ["XAUUSD"])

    def test_next_quarter_hour_boundary(self):
        now = datetime(2026, 10, 15, 12, 7, 30, tzinfo=timezone.utc)
        self.assertEqual(seconds_until_next_boundary(15, now), 450.0)

    def test_rejects_non_divisor_interval(self):
        with self.assertRaises(ValueError):
            seconds_until_next_boundary(17, datetime.now(timezone.utc))


if __name__ == "__main__":
    unittest.main()
