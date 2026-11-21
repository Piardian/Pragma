import io
import json
import unittest
from pathlib import Path
from dataclasses import asdict
from unittest.mock import patch

import numpy as np
import pandas as pd

from pragma import backtest_engine as be
from pragma.measurement import ExecutionCosts, evaluate_prefix, low_volume_veto
from pragma.one_year_backtest import parse_histdata_m1, require_observed_volume, run_one_year
from pragma.regime_poi_engine import POI, MarketRegime, RegimePOIDecision
from pragma.trigger_engine import TriggerDecision
from pragma.run_pipeline import run_pipeline


class MeasurementTests(unittest.TestCase):
    def test_histdata_est_is_fixed_and_volume_never_invented(self):
        data = parse_histdata_m1(io.StringIO("20250701 120000;1;2;0.5;1.5;0\n"))
        self.assertEqual(data.index[0], pd.Timestamp("2025-07-01T17:00:00Z"))
        self.assertEqual(data.tick_volume.iloc[0], 0)
        with self.assertRaisesRegex(ValueError, "VOLUME_UNAVAILABLE"):
            require_observed_volume(data)

    def test_legacy_parquet_and_current_macro_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "VOLUME_UNAVAILABLE"):
            require_observed_volume(pd.DataFrame({"tick_volume": [100]}))
        with patch("pragma.one_year_backtest.MacroGate") as gate:
            result = run_one_year("EURUSD", with_macro=True)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("MACRO_VINTAGE_UNAVAILABLE", result["error"])
        gate.assert_not_called()

    def test_costs_both_sides_and_stress(self):
        c = ExecutionCosts(0.1, 4, 1, 0.0001, "ASSUMED")
        self.assertAlmostEqual(c.adverse(100, "LONG", True), 100.15)
        self.assertAlmostEqual(c.adverse(100, "LONG", False), 99.85)
        self.assertAlmostEqual(c.adverse(100, "SHORT", True), 99.85)
        self.assertAlmostEqual(c.stressed(1.5).price_cost(100), 0.225)
        for v in (float("nan"), -1, float("inf")):
            with self.assertRaises(ValueError):
                ExecutionCosts(commission_bps=v)

    def test_prior_volume_excludes_first_fragment_and_current_day(self):
        names = ["2026-10-05", "2026-10-06", "2026-10-07"]
        vols = dict(zip(names, [1e9, 100, 1e-9]))
        self.assertFalse(low_volume_veto(names, vols)[names[-1]])
        vols[names[-1]] = 1e20
        self.assertFalse(low_volume_veto(names, vols)[names[-1]])

    def test_shared_prefix_matches_precomputed_replay_with_rejections(self):
        # Full three sessions plus an active tail, with irregular price/volume.
        bars = be._synthetic_bars(4600, end_time=pd.Timestamp("2026-10-07T11:00:00Z"))
        snapshots = []
        be.run_backtest(bars, symbol="BTCUSDT", macro_bias="auto", trigger_tf="M15",
                        profile_bins=20, decision_observer=snapshots.append)
        self.assertGreater(len(snapshots), 50)
        costs = ExecutionCosts(commission_bps=4, funding_rate_8h=0.0001, provenance="ASSUMED")
        for expected in snapshots[::max(1, len(snapshots)//12)]:
            prefix = bars.loc[:pd.Timestamp(expected["signal_bar_time"])].copy()
            actual = evaluate_prefix(prefix, symbol="BTCUSDT", macro_bias="auto",
                                     trigger_tf="M15", profile_bins=20, costs=costs)
            self.assertEqual(json.loads(json.dumps(expected)), json.loads(json.dumps(actual)))

    def test_future_mutation_does_not_change_prefix(self):
        bars = be._synthetic_bars(4600, end_time=pd.Timestamp("2026-10-07T11:00:00Z"))
        cut = bars.index[-40]
        changed = bars.copy()
        changed.loc[changed.index > cut, ["open", "high", "low", "close"]] *= 5
        a = evaluate_prefix(bars.loc[:cut], symbol="EURUSD", macro_bias="auto")
        b = evaluate_prefix(changed.loc[:cut], symbol="EURUSD", macro_bias="auto")
        self.assertEqual(a, b)

    def test_next_open_fill_has_separate_signal_decision_fill_clocks(self):
        bars = be._synthetic_bars(4600, end_time=pd.Timestamp("2026-10-07T11:00:00Z"))
        poi = POI("LONG", "LONG_TREND_PULLBACK", MarketRegime.IMBALANCE_BULL,
                  2300, 2000, 2700, (2800, 2900), ())
        regime = RegimePOIDecision(MarketRegime.IMBALANCE_BULL, 1, 2300, 1, (poi,), "test")
        d = TriggerDecision(True, "LONG", 2300, 2100, 2800, 2900, 2800, 2, "EXECUTE", {})
        with patch.object(be, "generate_regime_pois", return_value=regime), patch.object(be, "evaluate_trigger", return_value=d):
            report = be.run_backtest(bars, macro_bias=1, trigger_tf="M15", profile_bins=20,
                                     costs=ExecutionCosts(commission_bps=4))
        self.assertGreater(report.total_trades, 0)
        t = report.trades[0]
        fill = pd.Timestamp(t["fill_time"])
        self.assertEqual(fill, pd.Timestamp(t["decision_time"]))
        self.assertEqual(fill, pd.Timestamp(t["signal_bar_time"]) + pd.Timedelta(minutes=1))
        self.assertAlmostEqual(t["entry_price"], bars.loc[fill, "open"] * 1.0004)

    def test_stop_gap_uses_worse_open(self):
        p = be._OpenTrade("X", "LONG", "T", "R", pd.Timestamp("2026-10-01T10:00Z"),
                          100, 95, 95, 105, 110, 5)
        r = be._manage_open_trade(p, pd.Series({"open": 90, "low": 89, "high": 101}),
                                  pd.Timestamp("2026-10-01T10:01Z"), cost=0.1)
        self.assertAlmostEqual(r.r_multiple, -2.02)

    def test_fill_bar_can_stop_and_no_be_keeps_original_stop(self):
        p = be._OpenTrade("X", "LONG", "T", "R", pd.Timestamp("2026-10-01T10:00Z"),
                          100, 95, 95, 105, 110, 5, entry_at_open=True)
        r = be._manage_open_trade(p, pd.Series({"open": 100, "low": 94, "high": 111}), p.entry_time)
        self.assertEqual(r.exit_reason, "STOP_LOSS")
        self.assertEqual(r.exit_time, "2026-10-01T10:01:00+00:00")
        p = be._OpenTrade("X", "LONG", "T", "R", pd.Timestamp("2026-10-01T10:00Z"),
                          100, 95, 95, 105, 110, 5, be_offset_r=None)
        be._manage_open_trade(p, pd.Series({"open": 102, "low": 99, "high": 106}), pd.Timestamp("2026-10-01T10:01Z"))
        self.assertEqual(p.stop_loss, 95)
        r = be._manage_open_trade(p, pd.Series({"open": 102, "low": 99, "high": 111}), pd.Timestamp("2026-10-01T10:02Z"))
        self.assertAlmostEqual(r.r_multiple, 1.5)

    def test_measurement_pipeline_has_no_notifications(self):
        with patch("pragma.run_pipeline.ExecutionNotifier") as notifier:
            result = run_pipeline(dry_run=True, macro_bias=1, measurement_mode=True,
                                  now=pd.Timestamp("2026-10-15T16:00Z"))
        self.assertEqual(result["notifications"], [])
        self.assertFalse(result["measurement"]["edge_proven"])
        notifier.assert_not_called()

    def test_observer_error_preserves_legacy_and_explicit_measurement_fails_closed(self):
        with patch("pragma.run_pipeline.evaluate_prefix", side_effect=ValueError("bad data")):
            result = run_pipeline(dry_run=True, macro_bias=1, now=pd.Timestamp("2026-10-15T16:00Z"))
            self.assertEqual(result["measurement_observer"]["veto"], "OBSERVER_ERROR")
            self.assertIn("regime", result)
            with self.assertRaisesRegex(ValueError, "bad data"):
                run_pipeline(dry_run=True, macro_bias=1, measurement_mode=True,
                             now=pd.Timestamp("2026-10-15T16:00Z"))

    def test_observer_disk_failure_does_not_interrupt_book(self):
        from pragma.shadow_trader import _append_measurement_observer
        with patch.object(Path, "open", side_effect=OSError("disk failure")), patch("builtins.print"):
            self.assertFalse(_append_measurement_observer(Path("unused.jsonl"), {}))


if __name__ == "__main__":
    unittest.main()
