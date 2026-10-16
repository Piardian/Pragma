"""Binance USD-M Futures OHLCV adapter with true taker-flow delta and CSV cache.

Public endpoints only; no API key or third-party exchange package is required.
The adapter returns the same UTC DatetimeIndex/OHLC/tick_volume shape as MT5DataClient.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

FUTURES_URL = "https://fapi.binance.com/fapi/v1/klines"
SPOT_URL = "https://api.binance.com/api/v3/klines"
_INTERVALS = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
              "H1": "1h", "M60": "1h", "H4": "4h", "D1": "1d"}
_INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
                "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000,
                "1d": 86_400_000}
_COLUMNS = ["open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"]


class BinanceDataError(RuntimeError):
    """Raised when Binance returns invalid or insufficient market data."""


def normalize_binance_symbol(symbol: str) -> str:
    value = str(symbol or "").strip().upper().replace("/", "").replace("_", "").replace("-", "")
    aliases = {"BTC": "BTCUSDT", "BTCUSD": "BTCUSDT", "XBTUSD": "BTCUSDT",
               "ETH": "ETHUSDT", "ETHUSD": "ETHUSDT", "SOL": "SOLUSDT",
               "SOLUSD": "SOLUSDT"}
    return aliases.get(value, value)


def _parse_rows(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows, columns=_COLUMNS)
    for col in ("open", "high", "low", "close", "volume", "quote_asset_volume",
                "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["time"] = pd.to_datetime(pd.to_numeric(frame["open_time"]), unit="ms", utc=True)
    frame["close_time"] = pd.to_datetime(pd.to_numeric(frame["close_time"]), unit="ms", utc=True)
    frame["buy_volume"] = frame["taker_buy_base_asset_volume"]
    frame["sell_volume"] = frame["volume"] - frame["buy_volume"]
    frame["volume_delta"] = frame["buy_volume"] - frame["sell_volume"]
    # Preserve quote volume separately; tick_volume uses base-asset volume for
    # consistent volume-climax calculations across symbols.
    frame["tick_volume"] = frame["volume"]
    frame = frame.set_index("time").sort_index()
    frame.index.name = "time"
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame


def filter_closed_bars(bars: pd.DataFrame, timeframe: str,
                       now: datetime | pd.Timestamp | None = None) -> pd.DataFrame:
    """Exclude any candle whose exchange close_time has not elapsed."""
    if bars.empty:
        return bars.copy()
    clock = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    clock = clock.tz_localize("UTC") if clock.tzinfo is None else clock.tz_convert("UTC")
    if "close_time" in bars.columns:
        close_times = pd.to_datetime(bars["close_time"], utc=True)
        return bars.loc[close_times <= clock].copy()
    key = str(timeframe).upper()
    if key not in _INTERVALS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    starts = pd.DatetimeIndex(bars.index)
    starts = starts.tz_localize("UTC") if starts.tz is None else starts.tz_convert("UTC")
    elapsed = pd.to_timedelta(_INTERVAL_MS[_INTERVALS[key]], unit="ms")
    # Binance close_time is inclusive (open + duration - 1ms).
    return bars.loc[starts + elapsed <= clock].copy()


class BinanceDataClient:
    """Paginated, public Binance Futures/Spot klines client with incremental CSV cache."""

    def __init__(self, cache_dir: str | Path = "data_cache", *, no_cache: bool = False,
                 timeout: float = 15.0, sleep_seconds: float = 0.15,
                 opener: Callable | None = None):
        self.cache_dir = Path(cache_dir)
        self.no_cache = bool(no_cache)
        self.timeout = float(timeout)
        self.sleep_seconds = max(0.0, float(sleep_seconds))
        self._opener = opener or urlopen

    @staticmethod
    def _cache_key(symbol: str, timeframe: str) -> str:
        return f"binance_{normalize_binance_symbol(symbol)}_{str(timeframe).upper()}.csv"

    def _read_cache(self, path: Path) -> pd.DataFrame:
        if self.no_cache or not path.exists():
            return pd.DataFrame()
        try:
            frame = pd.read_csv(path, parse_dates=["time", "close_time"])
            frame["time"] = pd.to_datetime(frame["time"], utc=True)
            frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True)
            frame = frame.set_index("time").sort_index()
            frame.index.name = "time"
            return frame[~frame.index.duplicated(keep="last")]
        except (OSError, ValueError, KeyError, pd.errors.ParserError):
            return pd.DataFrame()

    def _write_cache(self, path: Path, frame: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        saved = frame.reset_index()
        saved.to_csv(tmp, index=False)
        tmp.replace(path)

    def _request_page(self, base_url: str, symbol: str, interval: str,
                      end_time: int, limit: int) -> list:
        params = urlencode({"symbol": symbol, "interval": interval,
                            "endTime": end_time, "limit": limit})
        request = Request(f"{base_url}?{params}", headers={"User-Agent": "Pragma/1.0"})
        with self._opener(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict):
            raise BinanceDataError(f"Binance API error: {payload.get('msg', payload)}")
        if not isinstance(payload, list):
            raise BinanceDataError("Unexpected Binance response format")
        return payload

    def _fetch_before(self, symbol: str, interval: str, end_time: int,
                      limit: int, *, force_spot: bool = False) -> tuple[pd.DataFrame, str]:
        urls = [SPOT_URL] if force_spot else [FUTURES_URL, SPOT_URL]
        errors = []
        for url in urls:
            try:
                rows = self._request_page(url, symbol, interval, end_time, min(limit, 1500 if url == FUTURES_URL else 1000))
                return _parse_rows(rows), url
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, BinanceDataError) as exc:
                errors.append(f"{url}: {exc}")
        raise BinanceDataError("All Binance endpoints failed: " + " | ".join(errors))

    def rates(self, symbol: str, timeframe: str = "M1", count: int = 1500) -> pd.DataFrame:
        if count <= 0:
            raise ValueError("count must be positive")
        tf = str(timeframe).upper()
        if tf not in _INTERVALS:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        symbol, interval = normalize_binance_symbol(symbol), _INTERVALS[tf]
        if not symbol.endswith("USDT"):
            raise ValueError(f"Binance USD-M Futures symbol must be USDT-quoted: {symbol}")
        cache_path = self.cache_dir / self._cache_key(symbol, tf)
        cached = self._read_cache(cache_path)
        now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
        interval_ms = _INTERVAL_MS[interval]
        # Incremental requests include overlap to recover the last bar safely.
        end_time = now_ms
        collected: list[pd.DataFrame] = []
        remaining = count
        if not cached.empty and not self.no_cache:
            latest_open_ms = int(cached.index[-1].timestamp() * 1000)
            if latest_open_ms + interval_ms >= now_ms - interval_ms:
                end_time = latest_open_ms + interval_ms * 2
                remaining = max(0, count - len(cached.tail(count)))
                if remaining == 0:
                    return filter_closed_bars(cached.tail(count), tf)
        # Page backward; API caps are 1500 futures / 1000 spot candles.
        while remaining > 0:
            page_limit = min(remaining, 1500)
            page, _ = self._fetch_before(symbol, interval, end_time, page_limit)
            if page.empty:
                break
            collected.append(page)
            oldest_ms = int(page.index[0].timestamp() * 1000)
            remaining -= len(page)
            if oldest_ms <= 0 or len(page) < min(page_limit, 1000):
                break
            end_time = oldest_ms - 1
            if self.sleep_seconds and remaining > 0:
                time.sleep(self.sleep_seconds)
        fetched = pd.concat(collected).sort_index() if collected else pd.DataFrame()
        if not cached.empty and not self.no_cache:
            fetched = pd.concat([cached, fetched]).sort_index()
        if fetched.empty:
            raise BinanceDataError(f"No Binance klines returned for {symbol} {tf}")
        fetched = fetched[~fetched.index.duplicated(keep="last")]
        # Closed-bar filter is based on exchange close_time, not local candle assumptions.
        fetched = filter_closed_bars(fetched, tf)
        if not self.no_cache:
            self._write_cache(cache_path, fetched)
        return fetched.tail(count).copy()
