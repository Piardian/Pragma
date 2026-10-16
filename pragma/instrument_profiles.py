"""Deterministic per-instrument microstructure profiles."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstrumentProfile:
    name: str
    allow_trend_pullback: bool
    allow_mean_reversion: bool
    poi_atr_multiplier: float
    sl_atr_buffer: float
    imbalance_vwap_poc_atr: float
    mean_reversion_confluence_atr: float
    min_spread_to_sl_ratio: float
    min_rr_tp1: float = 1.5
    min_rr_tp2: float = 2.0
    default_trigger_tf: str = "M5"
    active_hours_utc: tuple[int, int] = (6, 20)


MOMENTUM_TREND = InstrumentProfile(
    name="MOMENTUM_TREND",
    allow_trend_pullback=True,
    allow_mean_reversion=False,
    poi_atr_multiplier=0.35,
    sl_atr_buffer=0.50,
    imbalance_vwap_poc_atr=0.15,
    mean_reversion_confluence_atr=0.75,
    min_spread_to_sl_ratio=4.0,
    default_trigger_tf="M5",
)

FX_MEAN_REVERSION = InstrumentProfile(
    name="FX_MEAN_REVERSION",
    allow_trend_pullback=False,
    allow_mean_reversion=True,
    poi_atr_multiplier=0.45,
    sl_atr_buffer=0.65,
    imbalance_vwap_poc_atr=0.15,
    mean_reversion_confluence_atr=1.0,
    min_spread_to_sl_ratio=3.0,
    min_rr_tp1=1.0,
    min_rr_tp2=1.35,
    default_trigger_tf="M5",
)

CRYPTO_MOMENTUM = InstrumentProfile(
    name="CRYPTO_MOMENTUM",
    allow_trend_pullback=True,
    allow_mean_reversion=False,
    poi_atr_multiplier=0.35,
    sl_atr_buffer=0.50,
    imbalance_vwap_poc_atr=0.15,
    mean_reversion_confluence_atr=0.75,
    min_spread_to_sl_ratio=4.0,
    default_trigger_tf="M15",
    active_hours_utc=(8, 22),
)

_CRYPTO_SYMBOLS = frozenset({
    "BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD", "DOGEUSD",
    "ADAUSD", "AVAXUSD", "LINKUSD", "SUIUSD",
})

TRIGGER_TIMEFRAME_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "M60": 60,
}


def normalize_trigger_tf(timeframe: str) -> str:
    """Validate a trigger timeframe and normalize M60 to its H1 alias."""
    value = str(timeframe or "").strip().upper()
    if value not in TRIGGER_TIMEFRAME_MINUTES:
        raise ValueError("trigger_tf must be one of M1, M5, M15, M30, H1, M60")
    return "H1" if value == "M60" else value


def trigger_tf_minutes(timeframe: str) -> int:
    """Return trigger timeframe duration in minutes."""
    return TRIGGER_TIMEFRAME_MINUTES[normalize_trigger_tf(timeframe)]


_MOMENTUM_SYMBOLS = frozenset({
    "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "SOLUSD",
    "SPX", "US100", "US30", "GBPJPY", "USDJPY",
})
_CURRENCY_CODES = frozenset({
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
    "SEK", "NOK", "DKK", "SGD", "HKD", "CNH", "CNY", "MXN",
    "ZAR", "TRY", "PLN", "HUF", "CZK", "INR", "RUB", "KRW", "THB",
    "ILS", "TWD", "BRL", "ARS", "PHP", "IDR", "MYR", "SAR", "AED",
    "QAR", "KWD", "BHD", "OMR", "EGP", "RON", "BGN", "ISK", "CLP",
    "COP", "PEN", "UYU", "PKR", "BDT", "VND", "NGN", "KES", "GHS",
    "UAH",
})


def canonical_symbol(symbol: str) -> str:
    """Normalize common broker suffixes and crypto contract aliases."""
    value = str(symbol or "").strip().upper()
    # MT5 broker suffixes such as XAUUSD.a, EURUSDm, EURUSD.pro.
    value = value.replace("/", "").replace("_", "").replace("-", "").replace(" ", "")
    for suffix in (".PRO", ".A", ".M", ".RAW", ".ECN", ".R", ".I", ".CASH", ".STD", ".ZERO"):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
    if value.endswith("M") and (
        value[:-1] in _MOMENTUM_SYMBOLS or _is_fx_cross(value[:-1])
    ):
        value = value[:-1]
    if value.endswith(("USDT", "USDC")) and value[:-4] in {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI"}:
        value = value[:-4] + "USD"
    aliases = {"GOLD": "XAUUSD", "SILVER": "XAGUSD", "GC=F": "XAUUSD", "BTC": "BTCUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "BNB": "BNBUSD", "XRP": "XRPUSD", "DOGE": "DOGEUSD", "ADA": "ADAUSD", "AVAX": "AVAXUSD", "LINK": "LINKUSD", "SUI": "SUIUSD"}
    return aliases.get(value, value)


def _is_fx_cross(symbol: str) -> bool:
    return (
        len(symbol) == 6
        and symbol[:3] in _CURRENCY_CODES
        and symbol[3:] in _CURRENCY_CODES
    )


def get_instrument_profile(symbol: str) -> InstrumentProfile:
    """Return a deterministic profile; explicit momentum symbols take precedence.

    Recognized FX crosses not explicitly assigned to MOMENTUM_TREND use the
    mean-reversion profile. Unknown/non-FX instruments retain the momentum
    defaults for backward compatibility with Pragma's prior XAUUSD behavior.
    """
    canonical = canonical_symbol(symbol)
    if canonical in _CRYPTO_SYMBOLS:
        return CRYPTO_MOMENTUM
    if canonical in _MOMENTUM_SYMBOLS:
        return MOMENTUM_TREND
    if _is_fx_cross(canonical):
        return FX_MEAN_REVERSION
    return MOMENTUM_TREND



def default_trigger_tf_for_symbol(symbol: str) -> str:
    """Choose a symbol-aware default for the validated crypto whitelist."""
    canonical = canonical_symbol(symbol)
    crypto_trigger_tfs = {
        "BTCUSD": "M15",
        "SOLUSD": "M5",
        "LINKUSD": "M5",
    }
    if canonical in crypto_trigger_tfs:
        return crypto_trigger_tfs[canonical]
    if canonical in _CRYPTO_SYMBOLS:
        return "M15"
    return get_instrument_profile(symbol).default_trigger_tf
