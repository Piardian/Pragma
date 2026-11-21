"""Read-only quote/candidate evidence. Never orders, Telegram or legacy state.

Costs that cannot be observed (commission, actual execution slippage) stay null.
This is an observer, not a forward PnL simulator or a profitability claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from pragma.data.mt5_data import MT5DataClient, filter_closed_bars
from pragma.data.clock_alignment import observed_offset_seconds
from pragma.data.binance_data import BinanceDataClient
from pragma.measurement import ExecutionCosts, evaluate_prefix


def append(path, row):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, allow_nan=False)+"\n")


def public_json(url):
    with urlopen(url, timeout=15) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("mt5", "binance"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cycles", type=int, default=1, help="0 means continuously until stopped")
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument("--bars", type=int, default=12000)
    parser.add_argument("--symbols", nargs="+")
    args = parser.parse_args()
    if args.cycles < 0 or args.poll_seconds < 1 or args.bars < 10080:
        parser.error("cycles >= 0, poll-seconds >= 1, bars >= 10080 required for complete prior-volume lookback")
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if out == ROOT or out == ROOT/"data_cache":
        parser.error("Use an isolated observer output folder")
    symbols = args.symbols or (["BTCUSDT", "SOLUSDT", "LINKUSDT"] if args.source == "binance" else
                               ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD", "CADCHF", "CADJPY", "EURGBP", "GBPCHF", "GBPJPY"])
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((ROOT/"pragma").rglob("*.py"))}
    manifest = {"started_at": datetime.now(timezone.utc).isoformat(), "source": args.source,
                "symbols": symbols, "code_sha256": hashes, "live_execution": False,
                "observer_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "requested_m1_bars": args.bars, "poll_seconds": args.poll_seconds,
                "notifications": False, "commission": None, "actual_slippage": None,
                "cost_calibrated": False, "edge_proven": False}
    manifest_path = out/f"observer_manifest_{time.time_ns()}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    last_decision = {}
    cycle = 0
    errors = 0
    while args.cycles == 0 or cycle < args.cycles:
        cycle += 1
        for symbol in symbols:
            try:
                now = pd.Timestamp.now(tz="UTC")
                if args.source == "mt5":
                    with MT5DataClient() as client:
                        offset = observed_offset_seconds(client.mt5)
                        tick = client.mt5.symbol_info_tick(symbol)
                        if tick is None:
                            raise ValueError("No quote")
                        quote_time = pd.to_datetime(tick.time_msc, unit="ms", utc=True) - pd.Timedelta(seconds=offset)
                        bid, ask = float(tick.bid), float(tick.ask)
                        # No account credentials or identifying account fields recorded.
                        info = client.mt5.symbol_info(symbol)
                        specs = {k: getattr(info, k, None) for k in ("point", "trade_tick_size", "trade_contract_size", "swap_long", "swap_short", "swap_mode")}
                        current = now.floor("15min")
                        bars = client.rates(symbol, "M1", args.bars) if last_decision.get(symbol) != current else None
                    funding = None
                else:
                    book = public_json(f"https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol={symbol}")
                    premium = public_json(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}")
                    bid, ask = float(book["bidPrice"]), float(book["askPrice"])
                    quote_time = pd.to_datetime(book["time"], unit="ms", utc=True)
                    funding = {"last_funding_rate_snapshot": premium.get("lastFundingRate"),
                               "next_funding_time": premium.get("nextFundingTime"),
                               "executed_trade_funding": None}
                    specs = {}
                    offset = 0
                    current = now.floor("15min")
                    if last_decision.get(symbol) != current:
                        with BinanceDataClient(cache_dir=out/"market_cache", futures_only=True) as client:
                            bars = client.rates(symbol, "M1", args.bars)
                    else:
                        bars = None
                if not (bid > 0 and ask >= bid) or abs((now-quote_time).total_seconds()) > 60:
                    raise ValueError("Invalid/stale bid/ask quote")
                quote = {"observed_at": now.isoformat(), "source": args.source, "symbol": symbol,
                         "quote_time": quote_time.isoformat(), "bid": bid, "ask": ask,
                         "spread_bps": (ask-bid)/((ask+bid)/2)*10000,
                         "reported_clock_offset_seconds": offset, "contract_specs": specs,
                         "funding": funding, "commission_bps": None, "actual_fill_slippage": None,
                         "actual_fill_time": None, "cost_calibrated": False, "edge_proven": False}
                append(out/"quotes.jsonl", quote)
                if bars is not None:
                    closed = filter_closed_bars(bars, "M1", now=now)
                    # MT5 observes Begonya as-of NOW only; no historical reuse.
                    if args.source == "mt5":
                        from pragma.macro_gate import MacroGate
                        gate = MacroGate().get_bias(symbol)
                        bias = int(gate.bias)
                        allow_range = getattr(gate, "gate", None) == "NEUTRAL_RANGE"
                        macro = {"bias": bias, "gate": getattr(gate,"gate",None), "timestamp": getattr(gate,"timestamp",None), "observed_at": now.isoformat()}
                    else:
                        bias, allow_range = "auto", False
                        macro = {"bias": "auto", "source": "CAUSAL_PRICE_REGIME"}
                    snapshot = evaluate_prefix(closed, symbol=symbol, macro_bias=bias,
                                               allow_range=allow_range,
                                               costs=ExecutionCosts(fixed_per_side=(ask-bid)/2,
                                                   provenance="PARTIAL_OBSERVED_SPREAD_ONLY"))
                    computed_at = pd.Timestamp.now(tz="UTC")
                    delay = (computed_at-pd.Timestamp(snapshot["decision_time"])).total_seconds()
                    append(out/"decisions.jsonl", dict(snapshot, observed_at=computed_at.isoformat(),
                          quote=quote, macro_asof=macro, current_half_spread_only=True,
                          commission_bps=None, actual_slippage=None, cost_calibrated=False,
                          sample_kind="FORWARD_OBSERVER_NO_PNL", manifest=manifest_path.name,
                          decision_delay_seconds=delay,
                          entry_eligible_asof=bool(not snapshot["veto"] and 0 <= delay <= 30 and (computed_at-quote_time).total_seconds() <= 30),
                          actual_fill_evidence=False))
                    last_decision[symbol] = current
                print(f"OK {symbol} quote={quote_time.isoformat()}", flush=True)
            except Exception as exc:
                errors += 1
                row = {"observed_at": datetime.now(timezone.utc).isoformat(), "symbol": symbol,
                       "source": args.source, "error": f"{type(exc).__name__}: {exc}", "edge_proven": False}
                append(out/"errors.jsonl", row)
                print(f"ERROR {symbol}: {row['error']}", flush=True)
                # A terminal authorization failure applies to the whole source.
                if "Authorization failed" in str(exc):
                    return 2
        if args.cycles == 0 or cycle < args.cycles:
            time.sleep(args.poll_seconds)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
