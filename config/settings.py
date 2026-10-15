"""Centralized defaults for Pragma. Override broker-specific symbols at runtime."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    symbol: str = "XAUUSD"
    timeframe: str = "M1"
    history_bars: int = 1500
    profile_bins: int = 100
    value_area_fraction: float = 0.70
    lvn_percentile: float = 20.0
    session_timezone: str = "UTC"


TIMEFRAME_NAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}
