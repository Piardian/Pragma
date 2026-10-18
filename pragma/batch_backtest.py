"""Batch backtest runner across multiple symbols and horizons for Pragma."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import pandas as pd

from pragma.backtest_engine import _default_point_size, run_backtest
from pragma.data.mt5_data import MT5DataClient, filter_closed_bars
from pragma.macro_gate import MacroGate

DEFAULT_SYMBOLS = [
    # Crypto, Commodity, Index
    "BTCUSD", "XAUUSD", "NAS100",
    # Majors & FX Crosses from Begonya
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD",
    "USDCAD", "USDCHF", "CADCHF", "CADJPY", "EURGBP",
    "GBPCHF", "GBPJPY",
]

HORIZONS = {
    "1_hafta": 10_000,
    "1_ay": 30_000,
    "3_ay": 80_000,
}


def run_single(symbol: str, bars_count: int, ignore_macro: bool = True) -> dict[str, Any]:
    point_size = _default_point_size(symbol)
    try:
        with MT5DataClient() as client:
            # Check if symbol exists in MT5
            available = set(client.symbols())
            if symbol not in available:
                # Try finding alternative suffix or match
                candidates = [s for s in available if symbol in s]
                if candidates:
                    symbol = candidates[0]
                else:
                    return {"status": "ERROR", "error": f"Symbol {symbol} not in MT5"}
            m1 = client.rates(symbol, "M1", bars_count)
            m15 = client.rates(symbol, "M15", max(300, bars_count // 15 + 100))
        now = pd.Timestamp.now(tz="UTC")
        m1 = filter_closed_bars(m1, "M1", now=now)
        m15 = filter_closed_bars(m15, "M15", now=now)
        if len(m1) < 300:
            return {"status": "ERROR", "error": f"Insufficient bars ({len(m1)})"}

        if ignore_macro:
            bias = None
            allow_range = True
        else:
            gate = MacroGate().get_bias(symbol)
            bias = int(gate.bias)
            allow_range = getattr(gate, "gate", None) == "NEUTRAL_RANGE"

        report = run_backtest(
            m1, symbol=symbol, macro_bias=bias,
            m15_bars=m15, point_size=point_size, allow_range=allow_range,
        )
        data = report.to_dict()
        data["status"] = "OK"
        data["start_time"] = m1.index[0].isoformat()
        data["end_time"] = m1.index[-1].isoformat()
        data["days"] = round((m1.index[-1] - m1.index[0]).total_seconds() / 86400.0, 1)
        return data
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch walk-forward backtest runner")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--horizons", nargs="+", default=["1_hafta", "1_ay", "3_ay"])
    parser.add_argument("--output", default="backtest_batch_results.json")
    parser.add_argument("--with-macro", action="store_true", help="Use macro gate instead of regime-driven mode")
    args = parser.parse_args()

    ignore_macro = not args.with_macro
    results: dict[str, dict[str, Any]] = {}
    print(f"==================================================")
    print(f"PRAGMA BATCH BACKTEST STARTED")
    print(f"Mod: {'Regime-Driven (Makro Filtresiz - Çift Yönlü)' if ignore_macro else 'Macro-Gated'}")
    print(f"Semboller ({len(args.symbols)}): {', '.join(args.symbols)}")
    print(f"Ufuklar: {', '.join(args.horizons)}")
    print(f"==================================================\n")

    start_total = time.monotonic()
    for horizon in args.horizons:
        bars_count = HORIZONS.get(horizon, 10_000)
        results[horizon] = {}
        print(f"\n--- PERİYOT: {horizon.upper()} (~{bars_count:,} M1 Barı) ---")
        for idx, sym in enumerate(args.symbols, 1):
            t0 = time.monotonic()
            sys.stdout.write(f"[{idx:02d}/{len(args.symbols):02d}] {sym:<7} ({horizon:<7}) ... ")
            sys.stdout.flush()
            res = run_single(sym, bars_count, ignore_macro=ignore_macro)
            elapsed = time.monotonic() - t0
            results[horizon][sym] = res
            if res.get("status") == "OK":
                trades = res["total_trades"]
                net_r = res["net_r"]
                wr = res["win_rate"] * 100.0
                pf = res["profit_factor"]
                pf_str = f"{pf:.2f}" if pf < 100 else "INF"
                dd_r = res["max_drawdown_r"]
                print(f"OK | İşlem: {trades:>2} | Net R: {net_r:>+6.2f}R | Win: {wr:>5.1f}% | PF: {pf_str:>4} | MaxDD: {dd_r:>4.2f}R ({elapsed:.1f}s)")
            else:
                print(f"HATA: {res.get('error')} ({elapsed:.1f}s)")

    # Save to JSON
    out_path = Path(args.output)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDetaylı sonuçlar '{out_path}' dosyasına kaydedildi.")
    print(f"Toplam süre: {time.monotonic() - start_total:.1f} saniye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
