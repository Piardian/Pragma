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


MOMENTUM_TREND = InstrumentProfile(
    name="MOMENTUM_TREND",
    allow_trend_pullback=True,
    allow_mean_reversion=False,
    poi_atr_multiplier=0.35,
    sl_atr_buffer=0.50,
    imbalance_vwap_poc_atr=0.15,
    mean_reversion_confluence_atr=0.75,
    min_spread_to_sl_ratio=4.0,
)

FX_MEAN_REVERSION = InstrumentProfile(
    name="FX_MEAN_REVERSION",
    allow_trend_pullback=False,
    allow_mean_reversion=True,
    poi_atr_multiplier=0.55,
    sl_atr_buffer=0.95,
    imbalance_vwap_poc_atr=0.15,
    mean_reversion_confluence_atr=1.0,
    min_spread_to_sl_ratio=3.0,
)

_MOMENTUM_SYMBOLS = frozenset({
    "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "SOLUSD",
    "SPX", "US100", "US30", "GBPJPY", "USDJPY",
})
_CURRENCY_CODES = frozenset({
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
    "SEK", "NOK", "DKK", "SGD", "HKD", "CNH", "CNY", "MXN",
    "ZAR", "TRY", "PLN", "HUF", "CZK",
})


def canonical_symbol(symbol: str) -> str:
    """Normalize common broker suffixes and crypto contract aliases."""
    value = str(symbol or "").strip().upper()
    # MT5 broker suffixes such as XAUUSD.a, EURUSDm, EURUSD.pro.
    value = value.replace("/", "").replace("_", "").replace("-", "").replace(" ", "")
    for suffix in (".PRO", ".A", ".M", ".RAW", ".ECN"):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
    if value.endswith(("USDT", "USDC")) and value[:-4] in {"BTC", "ETH", "SOL"}:
        value = value[:-4] + "USD"
    aliases = {"GOLD": "XAUUSD", "SILVER": "XAGUSD", "GC=F": "XAUUSD"}
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
    if canonical in _MOMENTUM_SYMBOLS:
        return MOMENTUM_TREND
    if _is_fx_cross(canonical):
        return FX_MEAN_REVERSION
    return MOMENTUM_TREND
