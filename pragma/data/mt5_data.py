"""MetaTrader 5 data adapter.

Requires a locally installed and logged-in MT5 terminal and the official
MetaTrader5 Python package. MT5 timestamps are UTC; returned indexes are UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd


class MT5DataError(RuntimeError):
    """Raised when MT5 cannot provide valid market data."""


_TIMEFRAME_NAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


class MT5DataClient:
    """Small, explicit adapter around MT5 rates and ticks APIs."""

    def __init__(self, mt5_module=None):
        # Injection keeps tests independent from an installed MT5 terminal.
        if mt5_module is None:
            try:
                import MetaTrader5 as mt5_module  # type: ignore[no-redef]
            except ImportError as exc:
                raise MT5DataError(
                    "MetaTrader5 package is not installed. Install requirements.txt "
                    "and run this on the computer with the MT5 terminal."
                ) from exc
        self.mt5 = mt5_module
        self._initialized_here = False

    def connect(self) -> None:
        if self.mt5.terminal_info() is not None:
            return
        if not self.mt5.initialize():
            raise MT5DataError(f"MT5 initialize failed: {self.mt5.last_error()}")
        self._initialized_here = True

    def close(self) -> None:
        if self._initialized_here:
            self.mt5.shutdown()
            self._initialized_here = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _timeframe(self, timeframe: str):
        name = _TIMEFRAME_NAMES.get(timeframe.upper())
        if not name or not hasattr(self.mt5, name):
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        return getattr(self.mt5, name)

    def rates(self, symbol: str, timeframe: str = "M1", count: int = 1500) -> pd.DataFrame:
        if count <= 0:
            raise ValueError("count must be positive")
        self.connect()
        if not self.mt5.symbol_select(symbol, True):
            raise MT5DataError(f"Cannot select symbol {symbol!r}: {self.mt5.last_error()}")
        raw = self.mt5.copy_rates_from_pos(symbol, self._timeframe(timeframe), 0, count)
        if raw is None or len(raw) == 0:
            raise MT5DataError(f"No rates returned for {symbol}: {self.mt5.last_error()}")
        frame = pd.DataFrame(raw)
        if "time" not in frame:
            raise MT5DataError("MT5 rates response has no time field")
        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        frame = frame.set_index("time").sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        required = {"open", "high", "low", "close", "tick_volume"}
        missing = required.difference(frame.columns)
        if missing:
            raise MT5DataError(f"Rates response missing columns: {sorted(missing)}")
        for col in ("open", "high", "low", "close", "tick_volume"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=list(required))
        if (frame["high"] < frame["low"]).any():
            raise MT5DataError("Invalid OHLC data: high is below low")
        return frame

    def rates_from(self, symbol: str, timeframe: str, start: datetime,
                   count: int) -> pd.DataFrame:
        """Fetch rates ending at/around a UTC-aware datetime."""
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        self.connect()
        if not self.mt5.symbol_select(symbol, True):
            raise MT5DataError(f"Cannot select symbol {symbol!r}")
        raw = self.mt5.copy_rates_from(
            symbol, self._timeframe(timeframe), start.astimezone(timezone.utc), count
        )
        if raw is None or len(raw) == 0:
            raise MT5DataError(f"No rates returned for {symbol}: {self.mt5.last_error()}")
        frame = pd.DataFrame(raw)
        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        frame = frame.set_index("time").sort_index()
        return frame[~frame.index.duplicated(keep="last")]

    def ticks_from(self, symbol: str, start: datetime, count: int = 10000) -> pd.DataFrame:
        """Fetch raw ticks from a UTC-aware start time."""
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        if count <= 0:
            raise ValueError("count must be positive")
        self.connect()
        if not self.mt5.symbol_select(symbol, True):
            raise MT5DataError(f"Cannot select symbol {symbol!r}")
        raw = self.mt5.copy_ticks_from(
            symbol, start.astimezone(timezone.utc), count, self.mt5.COPY_TICKS_ALL
        )
        if raw is None or len(raw) == 0:
            raise MT5DataError(f"No ticks returned for {symbol}: {self.mt5.last_error()}")
        frame = pd.DataFrame(raw)
        time_col = "time_msc" if "time_msc" in frame.columns else "time"
        unit = "ms" if time_col == "time_msc" else "s"
        frame["time"] = pd.to_datetime(frame[time_col], unit=unit, utc=True)
        return frame.set_index("time").sort_index()
