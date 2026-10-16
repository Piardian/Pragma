"""FAZ 10 tests for higher trigger timeframes and per-instrument defaults."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

from pragma.backtest_engine import _resample_tf
from pragma.data.mt5_data import MT5DataClient, filter_closed_bars
from pragma.instrument_profiles import (
    CRYPTO_MOMENTUM,
    FX_MEAN_REVERSION,
    MOMENTUM_TREND,
    get_instrument_profile,
    normalize_trigger_tf,
    trigger_tf_minutes,
)
from pragma.run_pipeline import _closed_tf_from_m1


def bars(count, freq="min"):
    index = pd.date_range("2026-01-01T00:00:00Z", periods=count, freq=freq)
    return pd.DataFrame({
        "open": range(count), "high": [x + 2 for x in range(count)],
        "low": [x - 1 for x in range(count)], "close": range(count),
        "tick_volume": [1] * count,
    }, index=index)


class Faz10TriggerTimeframeTests(unittest.TestCase):
    def test_m30_and_h1_resampling(self):
        frame = bars(120)
        self.assertEqual(len(_resample_tf(frame, "M30")), 4)
        self.assertEqual(len(_resample_tf(frame, "H1")), 2)
        self.assertEqual(len(_resample_tf(frame, "M60")), 2)
        self.assertEqual(trigger_tf_minutes("M30"), 30)
        self.assertEqual(trigger_tf_minutes("H1"), 60)
        self.assertEqual(trigger_tf_minutes("M60"), 60)
        self.assertEqual(normalize_trigger_tf("M60"), "H1")

    def test_pipeline_resampling_excludes_unclosed_higher_timeframe_bar(self):
        frame = bars(61)
        now = pd.Timestamp("2026-01-01T01:01:00Z")
        h1 = _closed_tf_from_m1(frame, "H1", now)
        self.assertEqual(len(h1), 1)
        self.assertEqual(h1.index[-1], pd.Timestamp("2026-01-01T00:00:00Z"))

    def test_mt5_timeframe_aliases_and_closed_bar_filter(self):
        fake = SimpleNamespace(TIMEFRAME_M30=30, TIMEFRAME_H1=60)
        client = MT5DataClient(mt5_module=fake)
        self.assertEqual(client._timeframe("M30"), 30)
        self.assertEqual(client._timeframe("H1"), 60)
        self.assertEqual(client._timeframe("M60"), 60)
        frame = bars(2, freq="30min")
        now = datetime(2026, 1, 1, 0, 45, tzinfo=timezone.utc)
        self.assertEqual(len(filter_closed_bars(frame, "M30", now=now)), 1)
        self.assertEqual(len(filter_closed_bars(frame, "M60", now=now)), 0)

    def test_profile_default_trigger_timeframes(self):
        self.assertEqual(FX_MEAN_REVERSION.default_trigger_tf, "M5")
        self.assertEqual(MOMENTUM_TREND.default_trigger_tf, "M5")
        self.assertEqual(CRYPTO_MOMENTUM.default_trigger_tf, "M15")
        for symbol in ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "EURGBP"):
            self.assertEqual(get_instrument_profile(symbol).default_trigger_tf, "M5", symbol)
        for symbol in ("BTCUSD", "BTC", "ETHUSD", "SOLUSD", "SOL"):
            self.assertEqual(get_instrument_profile(symbol).default_trigger_tf, "M15", symbol)
        for symbol in ("XAUUSD", "SPX", "US100"):
            self.assertEqual(get_instrument_profile(symbol).default_trigger_tf, "M5", symbol)

    def test_invalid_trigger_timeframe_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_trigger_tf("M3")


if __name__ == "__main__":
    unittest.main()
