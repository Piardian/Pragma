"""Phase 13 Stress Test Matrix and Baseline Comparison Runner."""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from pragma.backtest_engine import run_backtest, BacktestReport
from pragma.data.binance_data import BinanceDataClient


def load_cached_300k(symbol: str) -> pd.DataFrame:
    path = Path("data_cache") / f"binance_{symbol}_M1.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing cached data file: {path}")
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df.attrs["source"] = "binance"
    return df


def calculate_trade_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "total_trades": 0,
            "net_r": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "mean_r": 0.0,
            "std_r": 0.0,
            "t_stat": 0.0,
            "ci_95_low": 0.0,
            "ci_95_high": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "avg_duration_minutes": 0.0,
            "long_trades": 0,
            "long_net_r": 0.0,
            "long_profit_factor": 0.0,
            "long_win_rate": 0.0,
            "short_trades": 0,
            "short_net_r": 0.0,
            "short_profit_factor": 0.0,
            "short_win_rate": 0.0,
            "funding_events": 0,
            "funding_cost_r": 0.0,
        }

    r_vals = [float(t["r_multiple"]) for t in trades]
    n = len(r_vals)
    wins = [r for r in r_vals if r > 0]
    losses = [r for r in r_vals if r < 0]
    sum_wins = sum(wins)
    sum_losses = -sum(losses)
    net_r = sum(r_vals)
    mean_r = net_r / n
    std_r = float(np.std(r_vals, ddof=1)) if n > 1 else 0.0
    se = std_r / math.sqrt(n) if n > 0 else 0.0
    t_stat = (mean_r / se) if se > 0 else 0.0
    ci_low = mean_r - 1.96 * se
    ci_high = mean_r + 1.96 * se

    durations = []
    for t in trades:
        try:
            t_entry = pd.Timestamp(t["entry_time"])
            t_exit = pd.Timestamp(t["exit_time"])
            durations.append((t_exit - t_entry).total_seconds() / 60.0)
        except Exception:
            pass
    avg_duration = float(np.mean(durations)) if durations else 0.0

    long_trades = [t for t in trades if t["direction"] == "LONG"]
    short_trades = [t for t in trades if t["direction"] == "SHORT"]

    def sub_metrics(sub_list: list[dict[str, Any]]) -> tuple[int, float, float, float]:
        sub_n = len(sub_list)
        if not sub_n:
            return 0, 0.0, 0.0, 0.0
        sub_r = [float(t["r_multiple"]) for t in sub_list]
        w = [r for r in sub_r if r > 0]
        l = [-r for r in sub_r if r < 0]
        sw = sum(w)
        sl = sum(l)
        pf = float(sw / sl) if sl > 0 else (math.inf if sw > 0 else 0.0)
        wr = len(w) / sub_n
        return sub_n, float(sum(sub_r)), pf, wr

    l_cnt, l_net, l_pf, l_wr = sub_metrics(long_trades)
    s_cnt, s_net, s_pf, s_wr = sub_metrics(short_trades)

    funding_events = sum(int(t.get("funding_events", 0)) for t in trades)
    funding_cost_r = sum(float(t.get("funding_cost_r", 0.0)) for t in trades)

    return {
        "total_trades": n,
        "net_r": round(net_r, 4),
        "profit_factor": round(float(sum_wins / sum_losses) if sum_losses > 0 else (math.inf if sum_wins > 0 else 0.0), 4),
        "win_rate": round(len(wins) / n, 4),
        "mean_r": round(mean_r, 4),
        "std_r": round(std_r, 4),
        "t_stat": round(t_stat, 4),
        "ci_95_low": round(ci_low, 4),
        "ci_95_high": round(ci_high, 4),
        "avg_win_r": round(float(np.mean(wins)), 4) if wins else 0.0,
        "avg_loss_r": round(float(np.mean(losses)), 4) if losses else 0.0,
        "avg_duration_minutes": round(avg_duration, 2),
        "long_trades": l_cnt,
        "long_net_r": round(l_net, 4),
        "long_profit_factor": round(l_pf, 4) if math.isfinite(l_pf) else 999.0,
        "long_win_rate": round(l_wr, 4),
        "short_trades": s_cnt,
        "short_net_r": round(s_net, 4),
        "short_profit_factor": round(s_pf, 4) if math.isfinite(s_pf) else 999.0,
        "short_win_rate": round(s_wr, 4),
        "funding_events": funding_events,
        "funding_cost_r": round(funding_cost_r, 4),
    }


def run_phase13_suite() -> dict[str, Any]:
    print("[PHASE13] Loading cached 300,000 M1 bars for BTCUSDT, SOLUSDT, LINKUSDT...")
    bars_data = {
        "BTCUSDT": load_cached_300k("BTCUSDT"),
        "SOLUSDT": load_cached_300k("SOLUSDT"),
        "LINKUSDT": load_cached_300k("LINKUSDT"),
    }
    for s, df in bars_data.items():
        print(f"  {s}: {len(df)} bars ({df.index[0]} to {df.index[-1]})")

    periods = {
        "Period 1: First 200k (Historical Earlier)": (0, 200000),
        "Period 2: Last 100k (Recent IS)": (200000, 300000),
        "Period 3: Combined 300k (Full Sample)": (0, 300000),
    }

    test_combos = [
        ("SOLUSDT", "M5"),
        ("SOLUSDT", "M15"),
        ("LINKUSDT", "M5"),
        ("LINKUSDT", "M15"),
        ("BTCUSDT", "M15"),
    ]

    matrix_results: list[dict[str, Any]] = []

    # 1. Run 15 stress test combinations
    for period_name, (start_idx, end_idx) in periods.items():
        print(f"\n==========================================")
        print(f"RUNNING: {period_name} (bars {start_idx} to {end_idx})")
        print(f"==========================================")

        p_bars = {s: df.iloc[start_idx:end_idx].copy() for s, df in bars_data.items()}
        for s, df in p_bars.items():
            df.attrs["source"] = "binance"

        # Generate BTC regimes first
        btc_m1 = p_bars["BTCUSDT"]
        btc_regimes: dict[pd.Timestamp, str] = {}
        print(f"  Computing BTC regimes for {period_name}...")
        btc_report = run_backtest(
            btc_m1, symbol="BTCUSDT", macro_bias="auto",
            trigger_tf="M15", cost_pct=0.0004, apply_funding=True,
            out_regimes=btc_regimes,
        )

        for symbol, tf in test_combos:
            print(f"  Running {symbol} {tf} on {period_name}...")
            m1 = p_bars[symbol]
            report = run_backtest(
                m1,
                symbol=symbol,
                macro_bias="auto",
                trigger_tf=tf,
                cost_pct=0.0004,
                apply_funding=True,
                btc_regimes=btc_regimes,
            )
            rep_dict = report.to_dict()
            metrics = calculate_trade_metrics(rep_dict.get("trades", []))
            row = {
                "period": period_name,
                "start_idx": start_idx,
                "end_idx": end_idx,
                "symbol": symbol,
                "trigger_tf": tf,
                "bars_processed": report.bars_processed,
                "max_drawdown_r": round(report.max_drawdown_r, 4),
                "max_drawdown_pct": round(report.max_total_drawdown_pct, 4),
                "funnel_counts": report.funnel_counts,
                **metrics,
            }
            matrix_results.append(row)
            print(
                f"    -> Trades: {row['total_trades']} | Net R: {row['net_r']:+.2f}R | "
                f"PF: {row['profit_factor']:.3f} | WinRate: {row['win_rate']:.1%} | MaxDD: {row['max_drawdown_r']:.2f}R | "
                f"t-stat: {row['t_stat']:.2f} | Funding: {row['funding_cost_r']:.3f}R ({row['funding_events']} events)"
            )

    # 2. Run Baseline (FAZ 12) vs FAZ 13 Comparison on 300k Combined
    print("\n==========================================")
    print("RUNNING BASELINE COMPARISON (FAZ 12 vs FAZ 13 on Combined 300k)")
    print("==========================================")
    full_bars = {s: df.iloc[:300000].copy() for s, df in bars_data.items()}
    for s, df in full_bars.items():
        df.attrs["source"] = "binance"

    # FAZ 12 Baseline: 24/7 (0,24), filter_low_volume_days=False, cost_pct=0.0, apply_funding=False, spread_points=close*0.0004/0.01
    btc_regimes_faz12: dict[pd.Timestamp, str] = {}
    btc_m1_full = full_bars["BTCUSDT"]
    ref_close_btc = float(btc_m1_full["close"].iloc[-1])
    spread_pts_btc = ref_close_btc * 0.0004 / 0.01

    run_backtest(
        btc_m1_full, symbol="BTCUSDT", macro_bias="auto", trigger_tf="M15",
        spread_points=spread_pts_btc, point_size=0.01, cost_pct=0.0, apply_funding=False,
        session_hours_utc=(0, 24), filter_low_volume_days=False,
        out_regimes=btc_regimes_faz12,
    )

    baseline_comparisons: list[dict[str, Any]] = []
    for symbol, tf in test_combos:
        m1 = full_bars[symbol]
        ref_close = float(m1["close"].iloc[-1])
        spread_pts = ref_close * 0.0004 / 0.01

        # FAZ 12 run
        rep_faz12 = run_backtest(
            m1, symbol=symbol, macro_bias="auto", trigger_tf=tf,
            spread_points=spread_pts, point_size=0.01, cost_pct=0.0, apply_funding=False,
            btc_regimes=btc_regimes_faz12,
            session_hours_utc=(0, 24), filter_low_volume_days=False,
        )

        # FAZ 13 corresponding row from Combined 300k
        faz13_match = next(
            r for r in matrix_results
            if r["symbol"] == symbol and r["trigger_tf"] == tf and "Combined 300k" in r["period"]
        )

        delta_r = faz13_match["net_r"] - rep_faz12.net_r
        decision = "IMPROVED" if delta_r >= 0 else ("REDUCED_DRAWDOWN" if faz13_match["max_drawdown_r"] < rep_faz12.max_drawdown_r else "STABILIZED")

        cmp_row = {
            "symbol": symbol,
            "trigger_tf": tf,
            "faz12_net_r": round(rep_faz12.net_r, 2),
            "faz13_net_r": round(faz13_match["net_r"], 2),
            "faz12_trades": rep_faz12.total_trades,
            "faz13_trades": faz13_match["total_trades"],
            "faz12_pf": round(rep_faz12.profit_factor, 3),
            "faz13_pf": round(faz13_match["profit_factor"], 3),
            "faz12_max_dd_r": round(rep_faz12.max_drawdown_r, 2),
            "faz13_max_dd_r": round(faz13_match["max_drawdown_r"], 2),
            "delta_net_r": round(delta_r, 2),
            "decision": decision,
        }
        baseline_comparisons.append(cmp_row)
        print(
            f"  {symbol} {tf}: FAZ 12 Net R = {cmp_row['faz12_net_r']:+.2f}R ({cmp_row['faz12_trades']} trades, PF {cmp_row['faz12_pf']}) -> "
            f"FAZ 13 Net R = {cmp_row['faz13_net_r']:+.2f}R ({cmp_row['faz13_trades']} trades, PF {cmp_row['faz13_pf']}) | "
            f"Delta: {cmp_row['delta_net_r']:+.2f}R | Decision: {decision}"
        )

    # 3. Export to JSON, CSV, and MD
    out_dir = Path("artifacts")
    out_dir.mkdir(parents=True, exist_ok=True)

    json_payload = {
        "metadata": {
            "phase": "FAZ 13 — Audit Fixes, Crypto Filters & 300k M1 Stress Test",
            "bar_count_per_symbol": 300000,
            "date_range": "2026-03-22 09:24 UTC to 2026-10-16 17:24 UTC",
            "symbols": ["BTCUSDT", "SOLUSDT", "LINKUSDT"],
            "fee_model": "4 bps dynamic per side (8 bps round-trip) + 0.01% funding rate per passed 8h timestamp",
            "filters": {
                "active_hours_utc": [8, 22],
                "filter_low_volume_days": True,
                "short_requires_btc_bear": True,
                "short_requires_vwap_poc_separation_atr": 0.35,
                "short_requires_strict_negative_volume_delta": True,
            },
        },
        "stress_test_matrix_15_runs": matrix_results,
        "baseline_comparison_faz12_vs_faz13": baseline_comparisons,
    }

    json_path = out_dir / "phase13_stress_test.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, indent=2)
    print(f"\n[PHASE13] Saved JSON report to {json_path}")

    # CSV
    csv_path = out_dir / "phase13_stress_test.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "period", "symbol", "trigger_tf", "bars_processed", "total_trades",
            "net_r", "profit_factor", "win_rate", "max_drawdown_r", "max_drawdown_pct",
            "mean_r", "std_r", "t_stat", "ci_95_low", "ci_95_high",
            "avg_win_r", "avg_loss_r", "avg_duration_minutes",
            "long_trades", "long_net_r", "long_profit_factor", "long_win_rate",
            "short_trades", "short_net_r", "short_profit_factor", "short_win_rate",
            "funding_events", "funding_cost_r",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in matrix_results:
            writer.writerow(r)
    print(f"[PHASE13] Saved CSV report to {csv_path}")

    # Markdown
    md_path = out_dir / "phase13_stress_test.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# FAZ 13 — AUDIT FIXES, CRYPTO FILTERS & 300K M1 STRESS TEST RAPORU\n\n")
        f.write("## 1. Yönetici Özeti ve Metrikler\n\n")
        f.write("- **Veri Havuzu:** 300.000 kapalı M1 bar (208.33 takvim günü: 22 Mart 2026 - 16 Ekim 2026)\n")
        f.write("- **Maliyet Modeli:** Dinamik 4 bps giriş + 4 bps çıkış (8 bps round-trip) + 8 saatlik periyotlarda %0.01 fonlama kesintisi\n")
        f.write("- **Filtreler:** Aktif İşlem Saatleri (08:00 - 22:00 UTC), Hafta Sonu & Düşük Hacimli Gün Vetosu, BTC Lider Bear Şartı, 0.35x ATR VWAP Ayrışması, Kesin Negatif Delta (Short)\n\n")

        f.write("## 2. 300.000 M1 Stres Testi Matrisi (15 Koşu)\n\n")
        f.write("| Dönem | Sembol | TF | Trade | Net PnL (R) | PF | WinRate | MaxDD (R) | Exp (R) | Std R | t-stat | %95 CI (R) | Fonlama (R) |\n")
        f.write("| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for r in matrix_results:
            ci_str = f"[{r['ci_95_low']:+.2f}, {r['ci_95_high']:+.2f}]"
            f.write(
                f"| {r['period']} | `{r['symbol']}` | `{r['trigger_tf']}` | {r['total_trades']} | "
                f"**{r['net_r']:+.2f}** | {r['profit_factor']:.3f} | {r['win_rate']:.1%} | {r['max_drawdown_r']:.2f} | "
                f"{r['mean_r']:+.3f} | {r['std_r']:.2f} | {r['t_stat']:.2f} | {ci_str} | {r['funding_cost_r']:.3f}R |\n"
            )

        f.write("\n## 3. Long vs Short Ayrımı (Combined 300k)\n\n")
        f.write("| Sembol | TF | Long Trades | Long Net R | Long PF | Long WR | Short Trades | Short Net R | Short PF | Short WR |\n")
        f.write("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for r in matrix_results:
            if "Combined 300k" in r["period"]:
                f.write(
                    f"| `{r['symbol']}` | `{r['trigger_tf']}` | {r['long_trades']} | {r['long_net_r']:+.2f}R | "
                    f"{r['long_profit_factor']:.3f} | {r['long_win_rate']:.1%} | {r['short_trades']} | {r['short_net_r']:+.2f}R | "
                    f"{r['short_profit_factor']:.3f} | {r['short_win_rate']:.1%} |\n"
                )

        f.write("\n## 4. FAZ 12 (Baseline) vs FAZ 13 Karşılaştırması (Combined 300k)\n\n")
        f.write("| Sembol | TF | FAZ 12 Net R | FAZ 13 Net R | FAZ 12 Trades | FAZ 13 Trades | FAZ 12 PF | FAZ 13 PF | FAZ 12 MaxDD | FAZ 13 MaxDD | Net R Değişimi | Karar |\n")
        f.write("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for c in baseline_comparisons:
            f.write(
                f"| `{c['symbol']}` | `{c['trigger_tf']}` | {c['faz12_net_r']:+.2f}R | **{c['faz13_net_r']:+.2f}R** | "
                f"{c['faz12_trades']} | {c['faz13_trades']} | {c['faz12_pf']:.3f} | {c['faz13_pf']:.3f} | "
                f"{c['faz12_max_dd_r']:.2f}R | {c['faz13_max_dd_r']:.2f}R | **{c['delta_net_r']:+.2f}R** | {c['decision']} |\n"
            )

        f.write("\n## 5. Huni Tanıları (Funnel Diagnostics — Combined 300k)\n\n")
        for r in matrix_results:
            if "Combined 300k" in r["period"]:
                f.write(f"### `{r['symbol']}` `{r['trigger_tf']}`\n")
                f.write("```json\n")
                f.write(json.dumps(r["funnel_counts"], indent=2))
                f.write("\n```\n\n")

    print(f"[PHASE13] Saved Markdown report to {md_path}")
    return json_payload


if __name__ == "__main__":
    run_phase13_suite()
