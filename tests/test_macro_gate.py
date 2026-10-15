import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from pragma.macro_gate import Bias, MacroGate


class BegonyaMacroGateTests(unittest.TestCase):
    def write_gate(self, directory, *, timestamp=None, gates=None):
        path = Path(directory) / "macro_bias_gate.json"
        payload = {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "execution_bias_gates": gates or {"XAUUSD": "LONG_ONLY"},
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_naive_begonya_timestamp_uses_istanbul_timezone(self):
        # Begonya's current output uses a local timestamp without a UTC offset.
        local_now = datetime.now(ZoneInfo("Europe/Istanbul")).replace(tzinfo=None)
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_gate(
                directory,
                timestamp=local_now.isoformat(timespec="seconds"),
                gates={"EURUSD": "SHORT_ONLY"},
            )
            result = MacroGate(path).get_bias("EURUSD")
            self.assertEqual(result.bias, Bias.SHORT)
            self.assertEqual(result.source, "begonya")
            self.assertTrue(MacroGate(path).gate_symbols())

    def test_reads_symbol_specific_long_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_gate(directory, gates={"XAUUSD": "LONG_ONLY"})
            result = MacroGate(path).get_bias("XAUUSD")
            self.assertEqual(result.bias, Bias.LONG)
            self.assertEqual(result.gate, "LONG_ONLY")
            self.assertEqual(result.source, "begonya")

    def test_reads_short_gate_and_broker_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_gate(directory, gates={"EURUSD": "SHORT_ONLY"})
            result = MacroGate(path).get_bias("EURUSD.a")
            self.assertEqual(result.bias, Bias.SHORT)
            self.assertEqual(result.gate, "SHORT_ONLY")

    def test_neutral_range_maps_to_neutral(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_gate(directory, gates={"XAUUSD": "NEUTRAL_RANGE"})
            result = MacroGate(path).get_bias("XAUUSD")
            self.assertEqual(result.bias, Bias.NEUTRAL)
            self.assertEqual(result.gate, "NEUTRAL_RANGE")

    def test_stale_gate_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            old = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()
            path = self.write_gate(directory, timestamp=old)
            result = MacroGate(path, max_age_hours=36).get_bias("XAUUSD")
            self.assertEqual(result.bias, Bias.NEUTRAL)
            self.assertEqual(result.source, "begonya_stale")
            self.assertEqual(result.gate, "UNMAPPED")

    def test_missing_symbol_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_gate(directory, gates={"EURUSD": "LONG_ONLY"})
            result = MacroGate(path).get_bias("XAUUSD")
            self.assertEqual(result.bias, Bias.NEUTRAL)
            self.assertEqual(result.gate, "UNMAPPED")

    def test_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            result = MacroGate(Path(directory) / "missing.json").get_bias("XAUUSD")
            self.assertEqual(result.bias, Bias.NEUTRAL)
            self.assertEqual(result.source, "begonya_missing")


if __name__ == "__main__":
    unittest.main()
