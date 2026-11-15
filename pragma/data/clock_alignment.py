"""Explicit correction for the empirically audited non-UTC broker feed.

The normal API contract is UTC. FivePercentOnline-Real reported epochs were
10800 seconds ahead on Oct22/23, confirmed independently over the month by BTC
returns. A fresh heartbeat must confirm this mapping on EVERY retrieval.
Unexpected clock/DST changes fail closed instead of silently changing offsets.
"""
from __future__ import annotations
import pandas as pd

# FivePercentOnline-Real operates in Eastern European Time (EET / EEST):
# UTC+3 (10800s) during Summer Daylight Saving Time
# UTC+2 (7200s) during Winter Standard Time
AUDITED_OFFSETS = {
    'FivePercentOnline-Real': (7200, 10800),
}

_last_confirmed_offset: dict[str, tuple[int, float]] = {}


def observed_offset_seconds(mt5, *, now=None):
    account = mt5.account_info() if hasattr(mt5, 'account_info') else None
    server = getattr(account, 'server', '')
    allowed = AUDITED_OFFSETS.get(server)
    if not allowed:
        return 0
    if isinstance(allowed, int):
        allowed = (allowed,)
    # A continuously traded heartbeat avoids inferring an offset from stale FX
    # quotes at a weekend. No symbol selection or account mutation is performed.
    tick = mt5.symbol_info_tick('BTCUSD')
    clock = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='UTC')
    if clock.tzinfo is None:
        raise ValueError('UTC-aware clock required')
    clock_ts = clock.timestamp()
    if tick is not None:
        tick_time = float(tick.time)
        for candidate in allowed:
            # Candidates 7200 vs 10800 are separated by 3600s. 1200s tolerance (20m)
            # avoids failure during quiet weekend/night trading while unambiguously matching DST.
            if abs(tick_time - clock_ts - candidate) <= 1200:
                _last_confirmed_offset[server] = (candidate, clock_ts)
                return candidate
    # Fallback to cached confirmed offset if tick is temporarily quiet (valid up to 4 hours)
    if server in _last_confirmed_offset:
        cached_offset, cached_ts = _last_confirmed_offset[server]
        if abs(clock_ts - cached_ts) <= 14400:
            return cached_offset
    raise ValueError('Audited broker clock not confirmed by a fresh heartbeat; data blocked')


def normalize_reported_frame(frame, offset_seconds, *, server=''):
    if frame.attrs.get('broker_clock_normalized'):
        raise ValueError('Broker timestamps already normalized')
    out = frame.copy()
    ix = pd.DatetimeIndex(out.index)
    if ix.tz is None:
        raise ValueError('Raw reported epochs must be explicitly UTC-labelled')
    out.index = ix - pd.Timedelta(seconds=offset_seconds)
    out.attrs.update(broker_clock_normalized=True, reported_epoch_offset_seconds=offset_seconds, broker_server=server)
    return out
