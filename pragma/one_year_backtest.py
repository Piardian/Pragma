"""Full 1-Year Backtest Runner using HistData M1 archives for Pragma."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
import zipfile

import numpy as np
import pandas as pd
from histdata import download_hist_data

from pragma.backtest_engine import _default_point_size, run_backtest
from pragma.macro_gate import MacroGate

DEFAULT_PAIRS = [
    # Gold & Major FX & Crosses
    "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "NZDUSD", "USDCAD", "CADCHF", "CADJPY",
    "EURGBP", "GBPCHF", "GBPJPY",
]


def fetch_or_load_year_m1(pair: str, year: str = "2025", cache_dir: Path | None = None) -> pd.DataFrame:
    cache = cache_dir or (Path(__file__).resolve().parent.parent / "historical_data")
    cache.mkdir(parents=True, exist_ok=True)
    parquet_path = cache / f"{pair.upper()}_{year}_M1.parquet"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)

    zip_path = download_hist_data(
        year=year, month=None, pair=pair.lower(),
        time_frame="M1", platform="ASCII", output_directory=str(cache),
    )
    with zipfile.ZipFile(zip_path, "r") as z:
        csv_file = [n for n in z.namelist() if n.endswith(".csv")][0]
        with z.open(csv_file) as f:
            df = pd.read_csv(f, sep=";", header=None, names=["time", "open", "high", "low", "close", "vol"])
            df["time"] = pd.to_datetime(df["time"], format="%Y%m%d %H%M%S", utc=True)
            df = df.set_index("time").sort_index()
            point_size = _default_point_size(pair)
            df["tick_volume"] = np.maximum(1.0, ((df["high"] - df["low"]) / point_size).round())
            df = df[["open", "high", "low", "close", "tick_volume"]]
            df.to_parquet(parquet_path)
    # Cleanup downloaded zip to save disk space
    if Path(zip_path).exists():
        try:
            Path(zip_path).unlink()
        except OSError:
            pass
    return df


def run_one_year(pair: str, year: str = "2025", with_macro: bool = False, cache_dir: Path | None = None) -> dict[str, Any]:
    try:
        df = fetch_or_load_year_m1(pair, year=year, cache_dir=cache_dir)
        point_size = _default_point_size(pair)
        if with_macro:
            gate = MacroGate().get_bias(pair)
            bias = int(gate.bias)
            allow_range = getattr(gate, "gate", None) == "NEUTRAL_RANGE"
        else:
            bias = None
            allow_range = True

        report = run_backtest(
            df, symbol=pair, macro_bias=bias,
            point_size=point_size, allow_range=allow_range,
        )
        res = report.to_dict()
        res["status"] = "OK"
        res["bars_processed"] = len(df)
        res["start_time"] = df.index[0].isoformat()
        res["end_time"] = df.index[-1].isoformat()
        return res
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="1-Year Walk-Forward Backtest across HistData archives")
    parser.add_argument("--pairs", nargs="+", default=DEFAULT_PAIRS)
    parser.add_argument("--year", default="2025")
    parser.add_argument("--output", default="backtest_1year_results.json")
    args = parser.parse_args()

    cache_dir = Path(__file__).resolve().parent.parent / "historical_data"
    cache_dir.mkdir(parents=True, exist_ok=True)

    print("==================================================")
    print(f"PRAGMA 1-YILLIK WALK-FORWARD BACKTEST BAŞLATILDI")
    print(f"Veri Kaynağı: HistData M1 ({args.year})")
    print(f"Semboller ({len(args.pairs)}): {', '.join(args.pairs)}")
    print(f"Modlar: Hem Makro Filtresiz (Çift Yönlü) hem Begonya Makro Filtreli")
    print("==================================================\n")

    results: dict[str, dict[str, Any]] = {"filtresiz": {}, "makrolu": {}}
    start_total = time.monotonic()

    for idx, pair in enumerate(args.pairs, 1):
        print(f"\n[{idx:02d}/{len(args.pairs):02d}] === {pair} ({args.year}) ===")
        
        # 1. Filtresiz Test
        t0 = time.monotonic()
        sys.stdout.write(f"  -> Filtresiz (Çift Yönlü) ... ")
        sys.stdout.flush()
        res_free = run_one_year(pair, year=args.year, with_macro=False, cache_dir=cache_dir)
        e_free = time.monotonic() - t0
        results["filtresiz"][pair] = res_free
        if res_free.get("status") == "OK":
            tr = res_free["total_trades"]
            nr = res_free["net_r"]
            wr = res_free["win_rate"] * 100.0
            pf = res_free["profit_factor"]
            pf_str = f"{pf:.2f}" if pf < 100 else "INF"
            dd = res_free["max_drawdown_r"]
            print(f"OK | İşlem: {tr:>3} | Net R: {nr:>+6.2f}R | Win: {wr:>5.1f}% | PF: {pf_str:>4} | MaxDD: {dd:>5.2f}R ({e_free:.1f}s)")
        else:
            print(f"HATA: {res_free.get('error')} ({e_free:.1f}s)")

        # 2. Begonya Makro Filtreli Test
        t1 = time.monotonic()
        sys.stdout.write(f"  -> Begonya Makro Filtreli ... ")
        sys.stdout.flush()
        res_macro = run_one_year(pair, year=args.year, with_macro=True, cache_dir=cache_dir)
        e_macro = time.monotonic() - t1
        results["makrolu"][pair] = res_macro
        if res_macro.get("status") == "OK":
            tr = res_macro["total_trades"]
            nr = res_macro["net_r"]
            wr = res_macro["win_rate"] * 100.0
            pf = res_macro["profit_factor"]
            pf_str = f"{pf:.2f}" if pf < 100 else "INF"
            dd = res_macro["max_drawdown_r"]
            print(f"OK | İşlem: {tr:>3} | Net R: {nr:>+6.2f}R | Win: {wr:>5.1f}% | PF: {pf_str:>4} | MaxDD: {dd:>5.2f}R ({e_macro:.1f}s)")
        else:
            print(f"HATA: {res_macro.get('error')} ({e_macro:.1f}s)")

    # Save to JSON
    out_file = Path(args.output)
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n1 Yıllık sonuçlar '{out_file.name}' dosyasına kaydedildi.")
    print(f"Toplam süre: {(time.monotonic() - start_total) / 60.0:.1f} dakika.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
