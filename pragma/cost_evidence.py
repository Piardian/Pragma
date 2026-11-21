"""Observed broker cost evidence; absent costs never become zero-cost proof."""
from math import isfinite
import pandas as pd


def deal_cost_profiles(deals, symbols):
    """Per-lot/per-side fee proxy from complete entry/exit positions only.

    No PnL, account IDs or order tickets are exported. Trade costs belong to
    the observed account history, not necessarily to Pragma execution.
    """
    profiles = {}
    for symbol in symbols:
        rows = [r for r in deals if r.get("symbol") == symbol and r.get("type") in (0, 1) and r.get("volume", 0) > 0]
        groups = {}
        for row in rows:
            groups.setdefault(row["position_key"], []).append(row)
        complete = []
        for position in groups.values():
            incoming = sum(r["volume"] for r in position if r["entry"] == 0)
            outgoing = sum(r["volume"] for r in position if r["entry"] == 1)
            if incoming > 0 and abs(incoming-outgoing) < 1e-8 and all(r["entry"] in (0, 1) for r in position):
                complete.append(position)
        legs = [r for position in complete for r in position]
        observed = bool(legs) and all(r.get("commission") is not None and r.get("fee") is not None for r in legs)
        volume = sum(r["volume"] for r in legs)
        debit = sum(max(-r["commission"], 0) + max(-r["fee"], 0) for r in legs) if observed else None
        profiles[symbol] = {
            "trade_deal_count": len(rows), "complete_positions": len(complete),
            "calibration_min_complete_positions": 3,
            "observed_fee_debit_per_lot_side": debit/volume if observed else None,
            "fee_proxy_usable": observed and len(complete) >= 3,
            "commission_status": "OBSERVED_ACCOUNT_SAMPLE" if observed else "MISSING",
            "swap_debits_in_sample": sum(max(-r["swap"], 0) for r in rows if r.get("swap") is not None),
            "swap_credits_in_sample": sum(max(r["swap"], 0) for r in rows if r.get("swap") is not None),
            "swap_for_hypothetical_trade": None,
            "slippage": None, "full_cost_calibrated": False,
        }
    return profiles


def select_quote(ticks, event_time, *, max_delay_seconds=2.0):
    event = pd.Timestamp(event_time)
    if ticks.empty:
        return None
    eligible = ticks.loc[(ticks.index >= event) &
                         (ticks.index <= event+pd.Timedelta(seconds=max_delay_seconds))]
    for stamp, row in eligible.iterrows():
        bid, ask = float(row.bid), float(row.ask)
        if isfinite(bid) and isfinite(ask) and bid > 0 and ask >= bid:
            return {"time": stamp.isoformat(), "bid": bid, "ask": ask,
                    "delay_seconds": (stamp-event).total_seconds()}
    return None


def quote_to_usd(symbol, timestamp, bid_bars):
    """Historical quote-currency conversion; missing exact minute is missing."""
    currency = symbol[-3:]
    if currency == "USD":
        return 1.0
    conversion = {"GBP": ("GBPUSD", False), "CAD": ("USDCAD", True),
                  "CHF": ("USDCHF", True), "JPY": ("USDJPY", True)}
    if currency not in conversion:
        return None
    pair, inverse = conversion[currency]
    bars = bid_bars.get(pair)
    stamp = pd.Timestamp(timestamp).floor("min")
    if bars is None or stamp not in bars.index:
        return None
    value = float(bars.loc[stamp, "open"])
    return (1/value if inverse else value) if value > 0 else None


def fee_price_proxy(symbol, timestamp, specs, profiles, bid_bars, account_currency):
    p = profiles[symbol]
    if account_currency != "USD" or not p["fee_proxy_usable"]:
        return None
    contract = specs[symbol].get("trade_contract_size")
    rate = quote_to_usd(symbol, timestamp, bid_bars)
    if not contract or not rate:
        return None
    return p["observed_fee_debit_per_lot_side"]/(contract*rate)


def quoted_outcome(direction, entry_quote, exit_quote, entry_fee_price=None, exit_fee_price=None):
    """First eligible bid/ask proxy; NEVER called an actual broker fill."""
    if entry_quote is None or exit_quote is None:
        return None
    reference = (entry_quote["bid"]+entry_quote["ask"])/2
    exit_mid = (exit_quote["bid"]+exit_quote["ask"])/2
    sign = 1 if direction == "LONG" else -1
    entry = entry_quote["ask"] if direction == "LONG" else entry_quote["bid"]
    exit_price = exit_quote["bid"] if direction == "LONG" else exit_quote["ask"]
    spread_only = sign*(exit_price-entry)/reference*10000
    fee_bps = (entry_fee_price+exit_fee_price)/reference*10000 if entry_fee_price is not None and exit_fee_price is not None else None
    return {"mid_gross_bps": sign*(exit_mid-reference)/reference*10000,
            "quoted_spread_only_bps": spread_only,
            "fee_proxy_bps": fee_bps,
            "known_cost_subtotal_bps": spread_only-fee_bps if fee_bps is not None else None,
            "actual_slippage_bps": None, "hypothetical_swap": None,
            "fully_net_bps": None, "actual_fill": False}
