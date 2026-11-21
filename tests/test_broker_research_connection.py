import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from scripts import run_broker_measurement_research as research


class BrokerResearchConnectionTests(unittest.TestCase):
    def test_explicit_terminal_does_not_fall_back_to_other_installation(self):
        mt5 = SimpleNamespace(initialize=Mock(return_value=True), shutdown=Mock())
        client = MagicMock()
        client.__enter__.return_value = client
        with patch.dict("sys.modules", {"MetaTrader5": mt5}), patch.object(research, "MT5DataClient", return_value=client) as constructor:
            with research.research_client("C:/broker/terminal64.exe") as actual:
                self.assertIs(actual, client)
            mt5.initialize.assert_called_once_with(path="C:/broker/terminal64.exe", timeout=15000)
            constructor.assert_called_once_with(mt5_module=mt5)
            mt5.shutdown.assert_called_once()

    def test_explicit_authorization_failure_never_tries_default_terminal(self):
        mt5 = SimpleNamespace(initialize=Mock(return_value=False), last_error=Mock(return_value=(-6, "Authorization failed")))
        with patch.dict("sys.modules", {"MetaTrader5": mt5}), patch.object(research, "MT5DataClient") as constructor:
            with self.assertRaisesRegex(RuntimeError, "Authorization failed"):
                with research.research_client("C:/broker/terminal64.exe"):
                    self.fail("Unreachable")
            constructor.assert_not_called()

    def test_closed_market_quote_requires_explicit_archive_and_preserves_hash(self):
        self.assertEqual(research.archived_quotes(None), ({}, None))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/"quotes.jsonl"
            source.write_text(json.dumps({"source": "mt5", "symbol": "EURUSD", "bid": 1.1, "ask": 1.1002,
                                          "quote_time": "2026-10-23T20:49:00+00:00"})+"\n", encoding="utf-8")
            quotes, evidence = research.archived_quotes(source)
            self.assertEqual(quotes["EURUSD"]["bid"], 1.1)
            self.assertEqual(evidence["sha256"], research.sha(source))
            self.assertIn("NOT_HISTORICAL_CALIBRATION", evidence["usage"])
            source.write_text(json.dumps({"source": "mt5", "symbol": "EURUSD", "bid": 1.1, "ask": 1.0})+"\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid"):
                research.archived_quotes(source)


if __name__ == "__main__":
    unittest.main()
