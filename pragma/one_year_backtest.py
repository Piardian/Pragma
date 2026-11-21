"""Full 1-Year Backtest Runner using HistData M1 archives for Pragma."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
import zipfile

import numpy as np
import pandas as pd

from pragma.backtest_engine import _default_point_size, run_backtest
from pragma.macro_gate import MacroGate

DEFAULT_PAIRS = [
    # Gold & Major FX & Crosses
    "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "NZDUSD", "USDCAD", "CADCHF", "CADJPY",
    "EURGBP", "GBPCHF", "GBPJPY",
]


def parse_histdata_m1(stream) -> pd.DataFrame:
    """HistData ASCII is fixed EST (UTC-5); its M1 volume is usually zero.

    Keep missing volume missing. A range-derived proxy would test a different
    strategy. Refuse to pass it to a volume-dependent strategy as real volume.
    """
    frame = pd.read_csv(stream, sep=";", header=None,
                        names=["time", "open", "high", "low", "close", "tick_volume"])
    times = pd.to_datetime(frame.pop("time"), format="%Y%m%d %H%M%S")
    frame.index = pd.DatetimeIndex(times).tz_localize(timezone(timedelta(hours=-5))).tz_convert("UTC")
    frame = frame.sort_index()
    frame.attrs.update(source="histdata", source_timezone="EST_FIXED_UTC_MINUS_5",
                       volume_semantics="UNAVAILABLE", measurement_schema=2)
    return frame


def require_observed_volume(frame):
    if frame.attrs.get("volume_semantics") not in ("BROKER_TICK_COUNT", "EXCHANGE_BASE_VOLUME"):
        raise ValueError("VOLUME_UNAVAILABLE: HistData M1 cannot validate Pragma's volume-dependent strategy; use observed broker tick volume or exchange volume. Legacy proxy parquet is not admissible.")


def fetch_or_load_year_m1(pair: str, year: str = "2025", cache_dir: Path | None = None) -> pd.DataFrame:
    cache = cache_dir or (Path(__file__).resolve().parent.parent / "historical_data")
    cache.mkdir(parents=True, exist_ok=True)
    parquet_path = cache / f"{pair.upper()}_{year}_M1.parquet"
    if parquet_path.exists():
        frame = pd.read_parquet(parquet_path)
        require_observed_volume(frame)
        return frame

    from histdata import download_hist_data
    zip_path = download_hist_data(
        year=year, month=None, pair=pair.lower(),
        time_frame="M1", platform="ASCII", output_directory=str(cache),
    )
    with zipfile.ZipFile(zip_path, "r") as z:
        csv_file = [n for n in z.namelist() if n.endswith(".csv")][0]
        with z.open(csv_file) as f:
            df = parse_histdata_m1(f)
            require_observed_volume(df)
    # Cleanup downloaded zip to save disk space
    if Path(zip_path).exists():
        try:
            Path(zip_path).unlink()
        except OSError:
            pass
    return df


def run_one_year(pair: str, year: str = "2025", with_macro: bool = False, cache_dir: Path | None = None) -> dict[str, Any]:
    try:
        if with_macro:
            raise ValueError("MACRO_VINTAGE_UNAVAILABLE: a current gate must not be applied to historical bars")
        df = fetch_or_load_year_m1(pair, year=year, cache_dir=cache_dir)
        point_size = _default_point_size(pair)
        if with_macro:
            gate = MacroGate().get_bias(pair)
            bias = int(gate.bias)
            allow_range = getattr(gate, "gate", None) == "NEUTRAL_RANGE"
        else:
            bias = "auto"
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
    parser.add_argument("--output", default="reports/backtest_1year_measurement_v2.json")
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
