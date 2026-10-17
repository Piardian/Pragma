"""Centralized defaults for Pragma. Override broker-specific symbols at runtime."""
import os
from dataclasses import dataclass


from pathlib import Path

# Load .env file from project root if present
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except Exception:
        # Fallback line-by-line parser if dotenv is not imported
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Default Binance USD-M Futures scan/backtest whitelist. Explicit CLI symbols may override it.
DEFAULT_CRYPTO_SCAN_SYMBOLS = ("BTCUSDT", "SOLUSDT", "LINKUSDT")

# Unprofitable Forex pairs identified in 1-year Walk-Forward backtests
BLACKLIST_FOREX_SYMBOLS = ("GBPUSD", "NZDUSD")

# UTC hour interval [start, end): active London/New York trading window.
ACTIVE_TRADING_HOURS_UTC = (6, 20)


@dataclass(frozen=True)
class Settings:
    symbol: str = "XAUUSD"
    timeframe: str = "M1"
    history_bars: int = 3000
    profile_bins: int = 100
    value_area_fraction: float = 0.70
    lvn_percentile: float = 20.0
    session_timezone: str = "UTC"
    telegram_bot_token: str = TELEGRAM_BOT_TOKEN
    telegram_chat_id: str = TELEGRAM_CHAT_ID


TIMEFRAME_NAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}
