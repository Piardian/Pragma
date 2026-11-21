"""Pure decision contract shared by research and the forward observer.

No network, notifications, broker orders or process management belong here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd

from pragma.instrument_profiles import canonical_symbol, get_instrument_profile
from pragma.regime_poi_engine import generate_regime_pois
from pragma.trigger_engine import evaluate_trigger

CONTRACT_VERSION = "measurement-v2"


@dataclass(frozen=True)
class ExecutionCosts:
    """Adverse price-equivalent costs PER SIDE; funding is a separate debit.

    Fixed cost must be half-spread plus fixed slippage, not a full round trip.
    Commission/slippage bps are applied to each actual entry/exit reference.
    Assumptions never become observed costs merely by producing a positive R.
    """
    fixed_per_side: float = 0.0
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    funding_rate_8h: float = 0.0
    provenance: str = "UNMEASURED"

    def __post_init__(self):
        values = (self.fixed_per_side, self.commission_bps,
                  self.slippage_bps, self.funding_rate_8h)
        if not all(isfinite(v) and v >= 0 for v in values):
            raise ValueError("Costs must be finite and non-negative")

    @property
    def pct_per_side(self):
        return (self.commission_bps + self.slippage_bps) / 10000.0

    def price_cost(self, price):
        return self.fixed_per_side + abs(float(price)) * self.pct_per_side

    def adverse(self, price, direction, entry):
        buy = (direction == "LONG") if entry else (direction == "SHORT")
        return float(price) + (1 if buy else -1) * self.price_cost(price)

    def stressed(self, multiplier):
        if not isfinite(multiplier) or multiplier < 1:
            raise ValueError("Stress multiplier must be >= 1")
        return replace(self, fixed_per_side=self.fixed_per_side * multiplier,
                       commission_bps=self.commission_bps * multiplier,
                       slippage_bps=self.slippage_bps * multiplier,
                       funding_rate_8h=self.funding_rate_8h * multiplier)


def decide_regime(symbol, bias, profile, vwap, price, atr, *,
                  allow_range=False, allow_mean_reversion=None,
                  disable_trend_pullback=False, btc_leader_filter=False,
                  btc_leader_regime=None, generator=generate_regime_pois):
    p = get_instrument_profile(symbol)
    crypto = p.name == "CRYPTO_MOMENTUM"
    return generator(
        bias, profile, vwap, price, atr, allow_range=allow_range,
        allow_mean_reversion=p.allow_mean_reversion if allow_mean_reversion is None else allow_mean_reversion,
        allow_trend_pullback=p.allow_trend_pullback and not disable_trend_pullback,
        poi_atr_multiplier=p.poi_atr_multiplier,
        imbalance_vwap_poc_atr=p.imbalance_vwap_poc_atr,
        mean_reversion_confluence_atr=p.mean_reversion_confluence_atr,
        is_crypto=crypto, is_btc=canonical_symbol(symbol) == "BTCUSD",
        btc_leader_filter=btc_leader_filter, btc_leader_regime=btc_leader_regime,
    )


def decide_trigger(symbol, bars, poi, atr, cost_price, *, session_hours=None,
                   touch_bars=3, evaluator=evaluate_trigger):
    if touch_bars not in (1, 3):
        raise ValueError("touch_bars must be 1 or 3")
    p = get_instrument_profile(symbol)
    decision = evaluator(
        bars, poi.direction, poi.poi_low, poi.poi_high, atr, poi.take_profits,
        poi_type=poi.poi_type, center_price=poi.center, cost_price=cost_price,
        sl_atr_buffer=p.sl_atr_buffer,
        min_spread_to_sl_ratio=p.min_spread_to_sl_ratio,
        min_rr_tp1=p.min_rr_tp1, min_rr_tp2=p.min_rr_tp2,
        session_hours_utc=session_hours or p.active_hours_utc,
    )
    if touch_bars == 1:
        last = bars.iloc[-1]
        if not (last.low <= poi.poi_high and last.high >= poi.poi_low):
            return replace(decision, execute=False, reason="LAST_BAR_OUTSIDE_POI")
    return decision


def low_volume_veto(session_names, session_volumes, ratio=0.70):
    """Only completed PRIOR sessions; discard initial download fragment."""
    result = {}
    for pos, name in enumerate(session_names):
        past = [session_volumes[session_names[i]] for i in range(max(1, pos - 5), pos)]
        result[name] = bool(pd.Timestamp(name).dayofweek >= 5 or
                            (past and past[-1] < ratio * float(np.mean(past))))
    return result


def decision_snapshot(symbol, bar_time, regime, decisions, *, veto=None):
    return {
        "contract": CONTRACT_VERSION, "symbol": symbol,
        "signal_bar_time": pd.Timestamp(bar_time).isoformat(),
        "decision_time": (pd.Timestamp(bar_time) + pd.Timedelta(minutes=1)).isoformat(),
        "regime": regime.regime.value, "veto": veto,
        "pois": [asdict(poi) for poi, _ in decisions],
        "triggers": [dict(asdict(d), poi_type=poi.poi_type, direction=poi.direction)
                     for poi, d in decisions],
    }


def evaluate_prefix(bars, *, symbol, macro_bias, costs=None, profile_bins=100,
                    trigger_tf=None, allow_range=False, allow_mean_reversion=None,
                    disable_trend_pullback=False, btc_leader_filter=False,
                    btc_leader_regime=None, touch_bars=3,
                    filter_low_volume_days=None, min_daily_volume_ratio=0.70,
                    session_hours_utc=None):
    """Evaluate an already CLOSED M1 prefix, including rejected candidates.

    First observed session is always excluded as a prior profile. No current
    macro gate is read: caller must supply an explicit historical/forward bias.
    """
    from pragma.backtest_engine import _utc_index, _resample_tf, _atr14, _profile_levels
    from pragma.data.mt5_data import filter_closed_bars
    from pragma.instrument_profiles import default_trigger_tf_for_symbol, trigger_tf_minutes
    from pragma.vwap_engine import VWAPEngine

    costs = costs or ExecutionCosts()
    m1 = _utc_index(bars, "closed prefix")
    now = m1.index[-1] + pd.Timedelta(minutes=1)
    names = list(dict.fromkeys(m1.index.strftime("%Y-%m-%d")))
    empty = {"contract": CONTRACT_VERSION, "symbol": symbol,
             "signal_bar_time": m1.index[-1].isoformat(), "decision_time": now.isoformat(),
             "regime": None, "pois": [], "triggers": [], "veto": "WARMUP"}
    tf = trigger_tf or default_trigger_tf_for_symbol(symbol)
    minutes = trigger_tf_minutes(tf)
    if len(names) < 3 or now.minute % minutes:
        return dict(empty, veto="WARMUP" if len(names) < 3 else "TRIGGER_NOT_CLOSED")
    triggers = filter_closed_bars(_resample_tf(m1, tf), tf, now=now).tail(30)
    if len(triggers) < 30:
        return empty
    m15 = filter_closed_bars(_resample_tf(m1, "M15"), "M15", now=now)
    atr = _atr14(m15)
    if atr is None:
        return empty
    labels = m1.index.strftime("%Y-%m-%d")
    prior = _profile_levels(m1.loc[labels == names[-2]], profile_bins)
    active = m1.loc[labels == names[-1]].copy()
    active["session"] = names[-1]
    vwap = VWAPEngine().calculate(active, session_key="session").iloc[-1]
    regime = decide_regime(symbol, macro_bias, prior, vwap, float(m1.close.iloc[-1]), atr,
                           allow_range=allow_range, allow_mean_reversion=allow_mean_reversion,
                           disable_trend_pullback=disable_trend_pullback,
                           btc_leader_filter=btc_leader_filter, btc_leader_regime=btc_leader_regime)
    p = get_instrument_profile(symbol)
    filtered = p.name == "CRYPTO_MOMENTUM" if filter_low_volume_days is None else filter_low_volume_days
    veto = None
    if filtered:
        volumes = m1.groupby(labels).tick_volume.sum().to_dict()
        if low_volume_veto(names, volumes, min_daily_volume_ratio)[names[-1]]:
            veto = "LOW_VOLUME_OR_WEEKEND"
    decisions = [(poi, decide_trigger(symbol, triggers, poi, atr,
                                      costs.price_cost(float(m1.close.iloc[-1])),
                                      touch_bars=touch_bars, session_hours=session_hours_utc))
                 for poi in regime.pois]
    return decision_snapshot(symbol, m1.index[-1], regime, decisions, veto=veto)
