"""Fetch MT5 M1 bars and calculate AMT profile plus session VWAP.

Example:
    python -m pragma.run_pipeline --symbol XAUUSD --bars 1500

The symbol name must match the connected broker's Market Watch symbol.
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from pragma.amt_engine import AMTEngine
from pragma.data.mt5_data import MT5DataClient
from pragma.vwap_engine import VWAPEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Pragma data + AMT + VWAP research pipeline")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--bars", type=int, default=1500)
    parser.add_argument("--profile-bins", type=int, default=100)
    args = parser.parse_args()

    with MT5DataClient() as client:
        bars = client.rates(args.symbol, "M1", args.bars)

    # UTC calendar date is a deterministic initial session definition. Replace
    # with a broker/session calendar before using exchange-specific sessions.
    session = pd.Series(bars.index.strftime("%Y-%m-%d"), index=bars.index, name="session")
    bars = bars.copy()
    bars["session"] = session

    profile = AMTEngine(bins=args.profile_bins).calculate(bars)
    vwap = VWAPEngine().calculate(bars, session_key="session")
    last = vwap.iloc[-1]
    print(json.dumps({
        "symbol": args.symbol,
        "bars": len(bars),
        "from_utc": bars.index.min().isoformat(),
        "to_utc": bars.index.max().isoformat(),
        "profile": {
            "poc": profile.poc,
            "vah": profile.vah,
            "val": profile.val,
            "total_tick_volume": profile.total_volume,
            "actual_value_area_fraction": profile.value_area_fraction,
            "lvn_levels": list(profile.lvn_levels),
        },
        "latest_session_vwap": float(last["vwap"]),
        "latest_session_sigma": float(last["vwap_sigma"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
