import unittest
from unittest.mock import patch

from pragma.execution_notifier import ExecutionNotifier, SignalDeduplicator


class POIAlertTests(unittest.TestCase):
    def test_poi_alert_is_deduplicated_by_zone(self):
        poi = {
            "direction": "LONG",
            "poi_type": "LONG_MEAN_REVERSION",
            "center": 4100.25,
            "poi_low": 4099.5,
            "poi_high": 4101.0,
            "take_profits": [4140.0, 4150.0],
        }
        notifier = ExecutionNotifier(bot_token="", chat_id="", deduplicator=SignalDeduplicator())
        with patch("builtins.print") as output:
            first = notifier.notify_poi("XAUUSD", poi, "BALANCE", "2026-10-15T12:00:00Z")
            second = notifier.notify_poi("XAUUSD", poi, "BALANCE", "2026-10-15T12:15:00Z")
        self.assertTrue(first["sent"])
        self.assertEqual(first["channel"], "console")
        self.assertEqual(second["reason"], "DUPLICATE_POI")
        self.assertEqual(output.call_count, 1)


if __name__ == "__main__":
    unittest.main()
