"""Deterministic market-regime classification and ATR-scaled POI generation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any, Iterable, Mapping


class MarketRegime(str, Enum):
    BALANCE = "BALANCE"
    IMBALANCE_BULL = "IMBALANCE_BULL"
    IMBALANCE_BEAR = "IMBALANCE_BEAR"
    TRANSITION = "TRANSITION"


@dataclass(frozen=True)
class POI:
    direction: str
    poi_type: str
    regime: MarketRegime
    center: float
    poi_low: float
    poi_high: float
    take_profits: tuple[float, ...]
    source_levels: tuple[str, ...]

    @property
    def take_profit(self) -> float:
        """First target, for consumers that require a single initial target."""
        return self.take_profits[0]


# Explicit interface name used by the orchestration layer; POI remains an alias
# for compatibility with earlier callers.
POIZone = POI


@dataclass(frozen=True)
class RegimePOIDecision:
    regime: MarketRegime
    macro_bias: int
    current_price: float
    atr_14: float
    pois: tuple[POIZone, ...]
    reason: str


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _nearest_lvn(levels: Iterable[float], anchor: float, side: str) -> float | None:
    candidates = [_finite(level, "pdLVN level") for level in (levels or ())]
    if side == "below":
        candidates = [level for level in candidates if level <= anchor]
        return max(candidates) if candidates else None
    candidates = [level for level in candidates if level >= anchor]
    return min(candidates) if candidates else None


def _pair_if_confluent(a_name: str, a: float, b_name: str, b: float,
                       tolerance: float) -> tuple[float, tuple[str, str]] | None:
    if abs(a - b) <= tolerance:
        return (a + b) / 2.0, (a_name, b_name)
    return None


def _level_vs_band_range(
    level_name: str, level: float, band_low_name: str, band_low: float,
    band_high_name: str, band_high: float, tolerance: float,
) -> tuple[float, tuple[str, str]] | None:
    """Match a level to a band interval, including ATR tolerance outside it."""
    low, high = sorted((band_low, band_high))
    nearest = min(max(level, low), high)
    if abs(level - nearest) > tolerance:
        return None
    if low <= level <= high:
        band_name = f"{band_low_name}..{band_high_name}"
    elif nearest == low:
        band_name = band_low_name
    else:
        band_name = band_high_name
    return (level + nearest) / 2.0, (level_name, band_name)


def classify_regime(current_price: float, previous_profile: Any,
                    vwap: Any, atr_14: float = 0.0) -> MarketRegime:
    """Classify with an ATR buffer so pullback regimes survive VA-edge tests."""
    price = _finite(current_price, "current_price")
    val = _finite(_get(previous_profile, "pdVAL", "pd_val"), "pdVAL")
    vah = _finite(_get(previous_profile, "pdVAH", "pd_vah"), "pdVAH")
    poc = _finite(_get(previous_profile, "pdPOC", "pd_poc"), "pdPOC")
    vwap_value = _finite(_get(vwap, "vwap"), "vwap")
    atr = _finite(atr_14, "atr_14")
    if atr < 0:
        raise ValueError("atr_14 cannot be negative")
    if val > vah:
        raise ValueError("pdVAL must be less than or equal to pdVAH")
    buffer = 0.5 * atr
    if vwap_value > poc and price >= vah - buffer:
        return MarketRegime.IMBALANCE_BULL
    if vwap_value < poc and price <= val + buffer:
        return MarketRegime.IMBALANCE_BEAR
    if val - buffer <= price <= vah + buffer:
        return MarketRegime.BALANCE
    if price > vah and vwap_value > poc:
        return MarketRegime.IMBALANCE_BULL
    if price < val and vwap_value < poc:
        return MarketRegime.IMBALANCE_BEAR
    return MarketRegime.TRANSITION


def generate_regime_pois(
    macro_bias: int, previous_profile: Any, vwap: Any,
    current_price: float, atr_14: float, *, allow_range: bool = False,
) -> RegimePOIDecision:
    """Classify regime and generate only spec-defined directional POIs.

    `vwap` may be a mapping, a pandas Series (for example the latest row of
    `calculate_session_vwap`), or an object exposing the named attributes.
    Previous-session LVNs may be supplied as `pdLVN` or `pd_lvn`. In balance
    setups, confluence is checked against the full VWAP +/-1.5σ to +/-2.5σ
    interval, not just its endpoints.
    """
    if macro_bias not in (-1, 0, 1):
        raise ValueError("macro_bias must be -1, 0, or +1")
    price, atr = _finite(current_price, "current_price"), _finite(atr_14, "atr_14")
    if atr <= 0:
        raise ValueError("atr_14 must be greater than zero")
    poc = _finite(_get(previous_profile, "pdPOC", "pd_poc"), "pdPOC")
    vah = _finite(_get(previous_profile, "pdVAH", "pd_vah"), "pdVAH")
    val = _finite(_get(previous_profile, "pdVAL", "pd_val"), "pdVAL")
    if val > vah:
        raise ValueError("pdVAL must be less than or equal to pdVAH")
    vwap_value = _finite(_get(vwap, "vwap"), "vwap")
    sigma_value = _get(vwap, "vwap_sigma", "std_dev", "sigma")
    if sigma_value is None:
        raise ValueError("VWAP output must include vwap_sigma/std_dev/sigma")
    sigma = _finite(sigma_value, "vwap_sigma")
    if sigma < 0:
        raise ValueError("vwap_sigma cannot be negative")

    def band(name: str, fallback: float) -> float:
        value = _get(vwap, name)
        return fallback if value is None else _finite(value, name)

    lower_1 = band("vwap_lower_1p0sigma", vwap_value - sigma)
    upper_1 = band("vwap_upper_1p0sigma", vwap_value + sigma)
    lower_2 = band("vwap_lower_2p0sigma", vwap_value - 2.0 * sigma)
    upper_2 = band("vwap_upper_2p0sigma", vwap_value + 2.0 * sigma)
    lower_1_5 = band("vwap_lower_1p5sigma", vwap_value - 1.5 * sigma)
    upper_1_5 = band("vwap_upper_1p5sigma", vwap_value + 1.5 * sigma)
    lower_2_5 = band("vwap_lower_2p5sigma", vwap_value - 2.5 * sigma)
    upper_2_5 = band("vwap_upper_2p5sigma", vwap_value + 2.5 * sigma)
    regime = classify_regime(price, previous_profile, {"vwap": vwap_value}, atr)
    if macro_bias == 0 and not allow_range:
        return RegimePOIDecision(regime, macro_bias, price, atr, (), "NEUTRAL_MACRO")

    tolerance, half_width = 0.75 * atr, 0.35 * atr
    balance_window = val - 0.5 * atr <= price <= vah + 0.5 * atr
    pois: list[POIZone] = []

    def add(direction: str, poi_type: str, center: float,
            targets: tuple[float, ...], sources: tuple[str, ...]) -> None:
        pois.append(POIZone(direction, poi_type, regime, center,
                            center - half_width, center + half_width,
                            targets, sources))

    lvns = _get(previous_profile, "pdLVN", "pd_lvn", default=()) or ()
    if (macro_bias == 1 or (macro_bias == 0 and allow_range)) and balance_window
        candidates = [("pdVAL", val)]
        nearest_lvn = _nearest_lvn(lvns, val, "below")
        if nearest_lvn is not None:
            candidates.append(("pdLVN", nearest_lvn))
        for level_name, level in candidates:
            match = _level_vs_band_range(level_name, level, "lower_1p0sigma",
                                         lower_1, "lower_2p5sigma", lower_2_5,
                                         tolerance)
            if match is None and abs(level - lower_1_5) <= tolerance:
                match = ((level + lower_1_5) / 2.0, (level_name, "lower_1p5sigma"))
            if match:
                add("LONG", "LONG_MEAN_REVERSION", match[0], (poc, vwap_value), match[1])
    if macro_bias == 1 and regime == MarketRegime.IMBALANCE_BULL:
        for name, level in (("lower_1p0sigma", lower_1), ("vwap", vwap_value)):
            match = _pair_if_confluent("pdVAH", vah, name, level, tolerance)
            if match:
                add("LONG", "LONG_TREND_PULLBACK", match[0], (upper_2,), match[1])
    if (macro_bias == -1 or (macro_bias == 0 and allow_range)) and balance_window
        candidates = [("pdVAH", vah)]
        nearest_lvn = _nearest_lvn(lvns, vah, "above")
        if nearest_lvn is not None:
            candidates.append(("pdLVN", nearest_lvn))
        for level_name, level in candidates:
            match = _level_vs_band_range(level_name, level, "upper_1p0sigma",
                                         upper_1, "upper_2p5sigma", upper_2_5,
                                         tolerance)
            if match is None and abs(level - upper_1_5) <= tolerance:
                match = ((level + upper_1_5) / 2.0, (level_name, "upper_1p5sigma"))
            if match:
                add("SHORT", "SHORT_MEAN_REVERSION", match[0], (poc, vwap_value), match[1])
    if macro_bias == -1 and regime == MarketRegime.IMBALANCE_BEAR:
        for name, level in (("upper_1p0sigma", upper_1), ("vwap", vwap_value)):
            match = _pair_if_confluent("pdVAL", val, name, level, tolerance)
            if match:
                add("SHORT", "SHORT_TREND_PULLBACK", match[0], (lower_2,), match[1])

    # NEUTRAL_RANGE means range-only permission: allow both edges in balance,
    # but never allow trend-pullback POIs without a directional macro gate.
    if macro_bias == 0 and allow_range and balance_window
        candidates = [("pdVAH", vah)]
        nearest_lvn = _nearest_lvn(lvns, vah, "above")
        if nearest_lvn is not None:
            candidates.append(("pdLVN", nearest_lvn))
        for level_name, level in candidates:
            match = _level_vs_band_range(
                level_name, level, "upper_1p0sigma", upper_1,
                "upper_2p5sigma", upper_2_5, tolerance
            )
            if match:
                add("SHORT", "SHORT_MEAN_REVERSION", match[0],
                    (poc, vwap_value), match[1])

    unique: list[POIZone] = []
    seen: set[tuple[str, str, float]] = set()
    for poi in pois:
        key = (poi.direction, poi.poi_type, round(poi.center, 12))
        if key not in seen:
            seen.add(key)
            unique.append(poi)
    reason = "POI_GENERATED" if unique else "NO_CONFLUENCE_OR_REGIME_MISMATCH"
    return RegimePOIDecision(regime, macro_bias, price, atr, tuple(unique), reason)


class RegimePOIEngine:
    def evaluate(self, macro_bias: int, previous_profile: Any, vwap: Any,
                 current_price: float, atr_14: float) -> RegimePOIDecision:
        return generate_regime_pois(macro_bias, previous_profile, vwap,
                                    current_price, atr_14)
