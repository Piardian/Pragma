import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from pragma.macro_gate import (
    Bias, MacroGate, _parse_timestamp, candidate_gate_paths, resolve_gate_path,
)


class BegonyaMacroGateTests(unittest.TestCase):
    def write_gate(self, directory, *, timestamp=None, gates=None, schema="execution_bias_gates", extra=None):
        path = Path(directory) / "macro_bias_gate.json"
        payload = {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            schema: gates if gates is not None else {"XAUUSD": "LONG_ONLY"},
        }
        if extra:
            payload.update(extra)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_naive_begonya_timestamp_uses_istanbul_timezone(self):
        local_now = datetime.now().astimezone().replace(tzinfo=None)
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_gate(
                directory,
                timestamp=local_now.isoformat(timespec="seconds"),
                gates={"EURUSD": "SHORT_ONLY"},
            )
            result = MacroGate(path).get_bias("EURUSD")
            self.assertEqual(result.bias, Bias.SHORT)
            self.assertEqual(result.source, "begonya")
            self.assertEqual(MacroGate(path).gate_symbols(), ["EURUSD"])

    def test_three_hour_naive_future_timestamp_is_accepted_as_local_clock_skew(self):
        future_naive = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_gate(directory, timestamp=future_naive.isoformat(), gates={"XAUUSD": "LONG_ONLY"})
            with patch("pragma.macro_gate._local_timezone", return_value=timezone.utc), \
                 patch.dict("os.environ", {"BEGONYA_MACRO_TIMEZONE": ""}):
                result = MacroGate(path).get_bias("XAUUSD")
                self.assertEqual(result.bias, Bias.LONG)
                self.assertNotEqual(result.source, "begonya_invalid")
                self.assertEqual(MacroGate(path).gate_symbols(), ["XAUUSD"])

    def test_future_timestamp_more_than_four_hours_is_rejected(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_gate(directory, timestamp=future)
            result = MacroGate(path).get_bias("XAUUSD")
            self.assertEqual(result.bias, Bias.NEUTRAL)
            self.assertEqual(result.source, "begonya_invalid")

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

    def test_resolver_selects_newest_timestamp_across_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            older_dir = Path(directory) / "older"
            newer_dir = Path(directory) / "newer"
            older_dir.mkdir()
            newer_dir.mkdir()
            older = self.write_gate(older_dir, timestamp=(datetime.now(timezone.utc) - timedelta(hours=5)).isoformat())
            newer = self.write_gate(newer_dir, timestamp=(datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat())
            with patch("pragma.macro_gate.candidate_gate_paths", return_value=[older, newer]):
                selected, infos = resolve_gate_path()
            self.assertEqual(selected, newer)
            self.assertEqual(len(infos), 2)
            gate = MacroGate(newer)
            self.assertEqual(gate.resolved_gate_path, str(newer))

    def test_event_freeze_blocks_even_a_long_symbol_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_gate(
                directory, gates={"XAUUSD": "LONG_ONLY"},
                extra={"execution_gate": "EVENT_FREEZE", "gate_reason": "High impact event"},
            )
            result = MacroGate(path).get_bias("XAUUSD")
            self.assertEqual(result.bias, Bias.NEUTRAL)
            self.assertEqual(result.source, "begonya_blocked")
            self.assertIn("EVENT_FREEZE", result.reason)
            self.assertIn("High impact event", result.reason)

    def test_systemic_stress_blocks_and_event_freeze_has_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_gate(
                directory, gates={"XAUUSD": "LONG_ONLY"},
                extra={"regime_state": "SYSTEMIC_STRESS"},
            )
            result = MacroGate(path).get_bias("XAUUSD")
            self.assertEqual(result.bias, Bias.NEUTRAL)
            self.assertIn("SYSTEMIC_STRESS", result.reason)
            path.write_text(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbols": {"XAUUSD": {"gate": "LONG_ONLY"}},
                "event_freeze": True,
                "systemic_stress": True,
            }), encoding="utf-8")
            result = MacroGate(path).get_bias("XAUUSD")
            self.assertEqual(result.bias, Bias.NEUTRAL)
            self.assertIn("EVENT_FREEZE", result.reason)

    def test_symbol_aliases_and_alternate_schemas(self):
        cases = [
            ("symbols", {"XAUUSD.a": {"decision": "BULLISH"}, "BTCUSDT": "SHORT", "EURUSD": "+1"}),
            ("gates", {"GOLD": "LONG", "BTCUSDT": "BEARISH", "EURUSD": "1"}),
            ("assets", {"GC=F": "LONG_ONLY", "BTCUSD": "-1", "EURUSD": "LONG"}),
            ("decisions", {"XAUUSD": "1", "BTCUSDT": "SHORT_ONLY", "EURUSD": "BULLISH"}),
            ("instruments", {"XAUUSD.pro": "LONG", "BTCUSD": "SHORT", "EURUSD": "LONG"}),
            ("symbol_gates", {"XAUUSD.m": "LONG_ONLY", "BTCUSDT": "SHORT_ONLY", "EURUSD": "LONG_ONLY"}),
        ]
        expected = {"XAUUSD": Bias.LONG, "BTCUSD": Bias.SHORT, "EURUSD": Bias.LONG}
        for schema, gates in cases:
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as directory:
                path = self.write_gate(directory, schema=schema, gates=gates)
                gate = MacroGate(path)
                self.assertEqual(gate.get_bias("XAUUSD.a").bias, expected["XAUUSD"])
                self.assertEqual(gate.get_bias("BTCUSD").bias, expected["BTCUSD"])
                self.assertEqual(gate.get_bias("EURUSD").bias, expected["EURUSD"])
                self.assertTrue(gate.gate_symbols())

    def test_root_level_symbol_mapping_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "macro_bias_gate.json"
            path.write_text(json.dumps({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "XAUUSD.a": "LONG_ONLY",
                "BTCUSDT": "SHORT_ONLY",
            }), encoding="utf-8")
            gate = MacroGate(path)
            self.assertEqual(gate.get_bias("XAUUSD").bias, Bias.LONG)
            self.assertEqual(gate.get_bias("BTCUSD").bias, Bias.SHORT)
            self.assertEqual(gate.gate_symbols(), ["BTCUSDT", "XAUUSD.A"])

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
