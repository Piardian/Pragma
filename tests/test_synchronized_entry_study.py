import unittest
from dataclasses import asdict
from types import SimpleNamespace

import pandas as pd

from pragma.trigger_engine import TriggerDecision
from scripts.run_synchronized_entry_study import (current_touch_volume, synchronized_decider,
                                                quote_summary, scenario_summary, assert_baseline_parity, save)


class SynchronizedEntryStudyTests(unittest.TestCase):
    def setUp(self):
        self.bars = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100.,
                                  "tick_volume": 100.}, index=pd.date_range("2026-10-05T07:00Z", periods=30, freq="5min"))
        self.poi = SimpleNamespace(direction="LONG", poi_type="LONG_TREND_PULLBACK", poi_low=99.5, poi_high=100.5)
        self.base = TriggerDecision(True, "LONG", 100, 95, 105, 110, 105, 1, "EXECUTE", {"z_condition": True})

    def test_older_spike_alone_cannot_satisfy_current_candle_gate(self):
        self.bars.loc[self.bars.index[-3], "tick_volume"] = 200
        self.assertFalse(current_touch_volume(self.bars, self.poi))

    def test_current_touch_and_spike_accepts_original_decision_unchanged(self):
        self.bars.loc[self.bars.index[-1], "tick_volume"] = 200
        decide, selections = synchronized_decider(lambda *a, **k: self.base)
        result = decide("X", self.bars, self.poi)
        self.assertEqual(result, self.base)
        self.assertEqual(list(selections.values()), [True])

    def test_rejection_does_not_move_entry_stop_or_targets(self):
        decide, _ = synchronized_decider(lambda *a, **k: self.base)
        result = decide("X", self.bars, self.poi)
        self.assertFalse(result.execute)
        before, after = asdict(self.base), asdict(result)
        for k in before:
            if k not in ("execute", "reason"):
                self.assertEqual(before[k], after[k])

    def test_second_zone_cannot_replace_failed_original_zone(self):
        self.bars.loc[self.bars.index[-1], ["open", "high", "low", "close", "tick_volume"]] = [102, 103, 101, 102, 200]
        alternative = SimpleNamespace(direction="LONG", poi_type=self.poi.poi_type, poi_low=101, poi_high=103)
        self.assertTrue(current_touch_volume(self.bars, alternative))
        decide, selections = synchronized_decider(lambda *a, **k: self.base)
        self.assertFalse(decide("X", self.bars, self.poi).execute)
        result = decide("X", self.bars, alternative)
        self.assertFalse(result.execute)
        self.assertEqual(result.reason, "RESEARCH_DUPLICATE_CANONICAL_POI")
        self.assertEqual(len(selections), 1)

    def test_failed_original_trigger_never_becomes_eligible(self):
        from dataclasses import replace
        rejected = replace(self.base, execute=False, reason="LOW_RR")
        self.bars.loc[self.bars.index[-1], "tick_volume"] = 200
        decide, selections = synchronized_decider(lambda *a, **k: rejected)
        self.assertEqual(decide("X", self.bars, self.poi), rejected)
        self.assertFalse(selections)

    def test_unknown_quote_is_missing_not_flat_return(self):
        result = quote_summary([{"entry_time": "2026-10-05T08:00Z", "observation": None}])
        self.assertEqual(result["missing_quotes"], 1)
        self.assertIsNone(result["spread_only_bps"]["mean"])
        self.assertIsNone(result["same_signal_return_change_bps"])

    def test_zero_trades_have_undefined_performance(self):
        result = scenario_summary({"trades": []})
        self.assertEqual(result["n"], 0)
        self.assertIsNone(result["closed_scenario_r"])
        self.assertIsNone(result["closed_expectancy"]["mean"])

    def test_parity_checks_full_trade_path_not_just_total(self):
        base = {"trades": [{"exit_time": "2026-10-05T08:00Z"}]}
        with self.assertRaisesRegex(ValueError, "trade-path"):
            assert_baseline_parity({"trades": [{"exit_time": "2026-10-05T08:01Z"}]}, base)

    def test_infinite_profit_factor_is_undefined_not_zero_in_json(self):
        from unittest.mock import Mock
        import json
        path = Mock()
        save(path, {"profit_factor": float("inf"), "n": 1})
        stored = json.loads(path.write_text.call_args.args[0])
        self.assertIsNone(stored["profit_factor"])
        self.assertEqual(stored["n"], 1)


if __name__ == "__main__":
    unittest.main()
