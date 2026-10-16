"""Regression tests for Binance crypto market-data and profile behavior."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from pragma.data import binance_data
from pragma.data.binance_data import BinanceDataClient, _parse_rows, filter_closed_bars
from pragma.instrument_profiles import CRYPTO_MOMENTUM, get_instrument_profile, default_trigger_tf_for_symbol
from pragma.trigger_engine import evaluate_trigger


def _row(open_ms, interval_ms=60_000, volume=10.0, buy=7.0):
    return [open_ms, "100", "102", "99", "101", str(volume),
            open_ms + interval_ms - 1, str(volume * 100), 100,
            str(buy), str(buy * 100), "0"]


class _Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.payload).encode()


class BinanceCryptoTests(unittest.TestCase):
    def test_delta_calculation_and_real_volume_mapping(self):
        frame = _parse_rows([_row(1_000_000, volume=10, buy=7)])
        row = frame.iloc[0]
        self.assertEqual(row["tick_volume"], 10)
        self.assertEqual(row["buy_volume"], 7)
        self.assertEqual(row["sell_volume"], 3)
        self.assertEqual(row["volume_delta"], 4)
        self.assertEqual(row["quote_asset_volume"], 1000)

    def test_closed_bar_filter_uses_exchange_close_time(self):
        now = pd.Timestamp("2026-01-01T00:02:00Z")
        rows = [_row(int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp()*1000)),
                _row(int(pd.Timestamp("2026-01-01T00:01:00Z").timestamp()*1000))]
        frame = _parse_rows(rows)
        closed = filter_closed_bars(frame, "M1", now=now)
        self.assertEqual(len(closed), 2)
        active = filter_closed_bars(frame, "M1", now=pd.Timestamp("2026-01-01T00:01:30Z"))
        self.assertEqual(len(active), 1)

    def test_pagination_collects_multiple_pages(self):
        # The fake endpoint emits two bars per request and respects endTime.
        starts = [1_000_000 + i * 60_000 for i in range(5)]
        calls = []
        def opener(request, timeout=15):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(request.full_url).query)
            end = int(qs["endTime"][0]); limit = int(qs["limit"][0])
            calls.append((end, limit))
            eligible = [t for t in starts if t + 59_999 <= end]
            return _Response([_row(t) for t in eligible[-min(limit, 2):]])
        with tempfile.TemporaryDirectory() as tmp:
            client = BinanceDataClient(cache_dir=tmp, no_cache=True, sleep_seconds=0, opener=opener)
            with patch("pragma.data.binance_data.pd.Timestamp.now",
                       return_value=pd.Timestamp("1970-01-01T00:20:00Z")):
                # Test deterministic pagination directly using a controlled end time.
                frames = []
                end = starts[-1] + 59_999
                for _ in range(3):
                    page, _url = client._fetch_before("BTCUSDT", "1m", end, 2)
                    frames.append(page)
                    if page.empty: break
                    end = int(page.index[0].timestamp()*1000) - 1
                combined = pd.concat(frames).sort_index()
            self.assertGreaterEqual(len(calls), 2)
            self.assertEqual(len(combined.index.unique()), 5)

    def test_crypto_profiles_are_m15_and_247(self):
        symbols = ("BTC", "BTCUSD", "BTCUSDT", "ETH", "ETHUSD", "ETHUSDT",
                   "SOL", "SOLUSD", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
                   "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT")
        for symbol in symbols:
            with self.subTest(symbol=symbol):
                profile = get_instrument_profile(symbol)
                self.assertEqual(profile.name, "CRYPTO_MOMENTUM")
                self.assertEqual(profile.default_trigger_tf, "M15")
                self.assertEqual(profile.active_hours_utc, (8, 22))
                expected_tf = "M15"
                self.assertEqual(default_trigger_tf_for_symbol(symbol), expected_tf)
        self.assertEqual(CRYPTO_MOMENTUM.active_hours_utc, (8, 22))

    def test_crypto_trigger_session_hours_utc(self):
        # 02:00 UTC should be rejected outside (8, 22)
        idx_night = pd.date_range("2026-01-01T01:31:00Z", periods=30, freq="min")
        close = 100 + 0.1 * np.sin(np.arange(30))
        bars_night = pd.DataFrame({"open": close - .02, "high": close + .2,
                                   "low": close - .2, "close": close,
                                   "tick_volume": np.full(30, 10.0)}, index=idx_night)
        bars_night.attrs["source"] = "binance"
        res_night = evaluate_trigger(bars_night, "LONG", 99, 101, 1, 110,
                                     session_hours_utc=CRYPTO_MOMENTUM.active_hours_utc)
        self.assertFalse(res_night.metrics["session_allowed"])
        self.assertEqual(res_night.metrics["session_hour_utc"], 2)
        self.assertEqual(res_night.reason, "SESSION_HOURS")

        # 14:00 UTC should be allowed within (8, 22)
        idx_day = pd.date_range("2026-01-01T13:31:00Z", periods=30, freq="min")
        bars_day = pd.DataFrame({"open": close - .02, "high": close + .2,
                                 "low": close - .2, "close": close,
                                 "tick_volume": np.full(30, 10.0)}, index=idx_day)
        bars_day.attrs["source"] = "binance"
        res_day = evaluate_trigger(bars_day, "LONG", 99, 101, 1, 110,
                                   session_hours_utc=CRYPTO_MOMENTUM.active_hours_utc)
        self.assertTrue(res_day.metrics["session_allowed"])
        self.assertEqual(res_day.metrics["session_hour_utc"], 14)

    def test_btc_leader_filter_direction_rules(self):
        allows = binance_data.btc_leader_allows_direction
        self.assertFalse(allows("IMBALANCE_BEAR", "ETHUSDT", "LONG"))
        self.assertTrue(allows("IMBALANCE_BEAR", "ETHUSDT", "SHORT"))
        self.assertFalse(allows("IMBALANCE_BULL", "SOLUSDT", "SHORT"))
        self.assertTrue(allows("IMBALANCE_BULL", "SOLUSDT", "LONG"))
        # FAZ 13.6: Strict symmetry - Altcoin longs require IMBALANCE_BULL; BALANCE/RANGE must be vetoed
        self.assertFalse(allows("BALANCE", "SOLUSDT", "LONG"))
        self.assertFalse(allows("RANGE", "SOLUSDT", "LONG"))
        self.assertFalse(allows(None, "SOLUSDT", "LONG"))
        # Altcoin shorts require IMBALANCE_BEAR; BALANCE/RANGE must be vetoed
        self.assertFalse(allows("BALANCE", "SOLUSDT", "SHORT"))
        self.assertFalse(allows("RANGE", "SOLUSDT", "SHORT"))
        self.assertFalse(allows(None, "SOLUSDT", "SHORT"))
        self.assertTrue(allows("IMBALANCE_BEAR", "BTCUSDT", "LONG"))
        self.assertTrue(allows("IMBALANCE_BULL", "BTCUSDT", "SHORT"))

    def test_partial_cache_backfill_and_exact_count(self):
        # 20 bars available at 1m intervals
        base_ms = 10_000_000
        starts = [base_ms + i * 60_000 for i in range(20)]
        def opener(request, timeout=15):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(request.full_url).query)
            end = int(qs["endTime"][0]); limit = int(qs["limit"][0])
            eligible = [t for t in starts if t + 59_999 <= end]
            return _Response([_row(t) for t in eligible[-min(limit, len(eligible)):]])

        with tempfile.TemporaryDirectory() as tmp:
            client = BinanceDataClient(cache_dir=tmp, no_cache=False, sleep_seconds=0, opener=opener)
            fake_now = pd.Timestamp(datetime.fromtimestamp((starts[-1] + 120_000) / 1000, tz=timezone.utc))
            with patch("pragma.data.binance_data.pd.Timestamp.now", return_value=fake_now):
                # Request 5 bars first
                df1 = client.rates("BTCUSDT", "M1", 5)
                self.assertEqual(len(df1), 5)
                # Next request 12 bars with partial cache (5 in cache)
                df2 = client.rates("BTCUSDT", "M1", 12)
                self.assertEqual(len(df2), 12)
                self.assertEqual(len(df2.index.unique()), 12)

    def test_request_page_retries_on_rate_limit(self):
        attempts = 0
        def flaking_opener(request, timeout=15):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                from urllib.error import HTTPError
                raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)
            return _Response([_row(1_000_000)])

        with tempfile.TemporaryDirectory() as tmp:
            client = BinanceDataClient(cache_dir=tmp, sleep_seconds=0, opener=flaking_opener)
            with patch("time.sleep", return_value=None):
                rows = client._request_page("https://fapi.binance.com/fapi/v1/klines", "BTCUSDT", "1m", 2_000_000, 10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(attempts, 2)


if __name__ == "__main__":
    unittest.main()
