"""Auction Market Theory profile calculations using bar-level tick volume.

Important: MT5 M1 bars do not reveal true volume-at-price. This engine assigns
each bar's tick volume to its typical-price bin (H+L+C)/3. This approximation
is explicit, deterministic, and suitable for research, not equivalent to
exchange-traded footprint data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class VolumeProfile:
    histogram: pd.DataFrame
    poc: float
    vah: float
    val: float
    total_volume: float
    value_area_fraction: float
    lvn_levels: tuple[float, ...]


def _validate_bars(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"high", "low", "close", "tick_volume"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if bars.empty:
        raise ValueError("bars cannot be empty")
    frame = bars.loc[:, ["high", "low", "close", "tick_volume"]].astype(float).copy()
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError("bars contain NaN or infinite values")
    if (frame["high"] < frame["low"]).any():
        raise ValueError("high must be greater than or equal to low")
    if (frame["tick_volume"] < 0).any():
        raise ValueError("tick_volume cannot be negative")
    if frame["tick_volume"].sum() <= 0:
        raise ValueError("total tick volume must be positive")
    return frame


def calculate_volume_profile(
    bars: pd.DataFrame,
    bins: int = 100,
    value_area_fraction: float = 0.70,
    lvn_percentile: float = 20.0,
) -> VolumeProfile:
    """Calculate POC, contiguous value area, and low-volume nodes.

    Value area expands one adjacent price bin at a time from POC, selecting
    the larger-volume adjacent bin at each step, until target volume is met.
    Ties are resolved downward for deterministic results. VAH/VAL are the
    upper/lower edges of the included bins.

    LVNs are interior local minima whose volume is at or below the requested
    percentile. They are levels, not claims about actual resting liquidity.
    """
    if not isinstance(bins, int) or bins < 2:
        raise ValueError("bins must be an integer >= 2")
    if not 0 < value_area_fraction <= 1:
        raise ValueError("value_area_fraction must be in (0, 1]")
    if not 0 <= lvn_percentile <= 100:
        raise ValueError("lvn_percentile must be in [0, 100]")

    frame = _validate_bars(bars)
    typical = (frame["high"].to_numpy() + frame["low"].to_numpy()
               + frame["close"].to_numpy()) / 3.0
    volume = frame["tick_volume"].to_numpy(dtype=float)

    low_edge = float(frame["low"].min())
    high_edge = float(frame["high"].max())
    if np.isclose(low_edge, high_edge):
        # A non-zero bin width is needed for histogram edges.
        pad = max(abs(low_edge) * 1e-9, np.finfo(float).eps * 16)
        low_edge -= pad
        high_edge += pad

    volumes, edges = np.histogram(typical, bins=bins, range=(low_edge, high_edge),
                                  weights=volume)
    centers = (edges[:-1] + edges[1:]) / 2.0
    total = float(volumes.sum())
    if total <= 0:
        raise ValueError("No positive volume fell inside the profile range")

    poc_idx = int(np.argmax(volumes))
    target = total * value_area_fraction
    left = right = poc_idx
    accumulated = float(volumes[poc_idx])
    while accumulated < target and (left > 0 or right < bins - 1):
        left_vol = float(volumes[left - 1]) if left > 0 else -np.inf
        right_vol = float(volumes[right + 1]) if right < bins - 1 else -np.inf
        if left_vol >= right_vol:
            left -= 1
            accumulated += float(volumes[left])
        else:
            right += 1
            accumulated += float(volumes[right])

    threshold = float(np.percentile(volumes, lvn_percentile))
    local_min = ((volumes[1:-1] <= volumes[:-2])
                 & (volumes[1:-1] <= volumes[2:])
                 & (volumes[1:-1] <= threshold))
    lvn_indices = np.flatnonzero(local_min) + 1

    hist = pd.DataFrame({
        "price_low": edges[:-1],
        "price_high": edges[1:],
        "price": centers,
        "tick_volume": volumes.astype(float),
        "is_value_area": (np.arange(bins) >= left) & (np.arange(bins) <= right),
        "is_lvn": np.isin(np.arange(bins), lvn_indices),
    })
    return VolumeProfile(
        histogram=hist,
        poc=float(centers[poc_idx]),
        vah=float(edges[right + 1]),
        val=float(edges[left]),
        total_volume=total,
        value_area_fraction=float(accumulated / total),
        lvn_levels=tuple(float(centers[i]) for i in lvn_indices),
    )


class AMTEngine:
    """Convenience class wrapper for profile configuration."""

    def __init__(self, bins: int = 100, value_area_fraction: float = 0.70,
                 lvn_percentile: float = 20.0):
        self.bins = bins
        self.value_area_fraction = value_area_fraction
        self.lvn_percentile = lvn_percentile

    def calculate(self, bars: pd.DataFrame) -> VolumeProfile:
        return calculate_volume_profile(
            bars, bins=self.bins,
            value_area_fraction=self.value_area_fraction,
            lvn_percentile=self.lvn_percentile,
        )
