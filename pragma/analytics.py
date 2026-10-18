"""Automated Quantitative Diagnostics and Post-Trade Root-Cause Analytics for Pragma.

Analyzes trade journals and rejected signals to provide deep statistical insights:
- Executive Performance (Win Rate, Profit Factor, Expectancy, Drawdown)
- Root Cause Attribution (TP vs SL differences in Z-Score, Volume, MAE, MFE, Holding Time)
- Segmentation by POI Type, Market Regime, Symbol, and Trading Session
- Filter Funnel Analysis (Why potential opportunities were rejected)
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pragma.trade_journal import load_rejected_signals, load_trade_journal


def default_journal_path() -> Path:
    override = os.environ.get("PRAGMA_SHADOW_DIR", "").strip()
    if override:
        return Path(override).expanduser() / "trade_journal.csv"
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "Pragma" / "shadow_trading" if base else Path.home() / ".pragma" / "shadow_trading"
    return root / "trade_journal.csv"


def default_rejected_path() -> Path:
    override = os.environ.get("PRAGMA_SHADOW_DIR", "").strip()
    if override:
        return Path(override).expanduser() / "rejected_signals.csv"
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "Pragma" / "shadow_trading" if base else Path.home() / ".pragma" / "shadow_trading"
    return root / "rejected_signals.csv"


def default_state_path() -> Path:
    override = os.environ.get("PRAGMA_SHADOW_DIR", "").strip()
    if override:
        return Path(override).expanduser() / "state.json"
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "Pragma" / "shadow_trading" if base else Path.home() / ".pragma" / "shadow_trading"
    return root / "state.json"


def analyze_trade_journal(
    df_trades: pd.DataFrame | str | Path,
    df_rejected: pd.DataFrame | str | Path | None = None,
) -> dict[str, Any]:
    """Calculate quantitative diagnostics from completed trades and rejected signals."""
    if isinstance(df_trades, (str, Path)):
        df_trades = load_trade_journal(df_trades)
    if isinstance(df_rejected, (str, Path)):
        df_rejected = load_rejected_signals(df_rejected)

    if df_trades.empty:
        return {
            "total_trades": 0,
            "message": "Henüz tamamlanmış işlem kaydı bulunmamaktadır.",
            "rejections_count": len(df_rejected) if df_rejected is not None else 0,
        }

    total = len(df_trades)
    winners = df_trades[df_trades["realized_r"] > 0]
    losers = df_trades[df_trades["realized_r"] < 0]
    breakevens = df_trades[df_trades["realized_r"] == 0]

    win_count = len(winners)
    loss_count = len(losers)
    be_count = len(breakevens)

    win_rate = (win_count / total) * 100.0 if total > 0 else 0.0
    loss_rate = (loss_count / total) * 100.0 if total > 0 else 0.0
    be_rate = (be_count / total) * 100.0 if total > 0 else 0.0

    total_r = float(df_trades["realized_r"].sum())
    total_pnl = float(df_trades["realized_pnl"].sum())
    gross_profit_r = float(winners["realized_r"].sum())
    gross_loss_r = abs(float(losers["realized_r"].sum()))
    profit_factor = (gross_profit_r / gross_loss_r) if gross_loss_r > 0 else (999.0 if gross_profit_r > 0 else 0.0)
    expectancy_r = total_r / total if total > 0 else 0.0

    avg_win_r = float(winners["realized_r"].mean()) if win_count > 0 else 0.0
    avg_loss_r = abs(float(losers["realized_r"].mean())) if loss_count > 0 else 0.0
    win_loss_ratio = (avg_win_r / avg_loss_r) if avg_loss_r > 0 else 0.0

    # Drawdown calculation
    cum_r = df_trades["realized_r"].cumsum()
    peak_r = cum_r.cummax()
    dd_r = peak_r - cum_r
    max_dd_r = float(dd_r.max()) if not dd_r.empty else 0.0

    # Feature comparison between winners (TP) and losers (SL)
    def _mean_metric(df: pd.DataFrame, col: str) -> float | None:
        if col in df.columns and not df[col].dropna().empty:
            return float(df[col].dropna().mean())
        return None

    feature_comparison = {
        "z_score": {
            "win_avg": _mean_metric(winners, "z_score"),
            "loss_avg": _mean_metric(losers, "z_score"),
        },
        "volume_multiplier": {
            "win_avg": _mean_metric(winners, "volume_multiplier"),
            "loss_avg": _mean_metric(losers, "volume_multiplier"),
        },
        "holding_bars": {
            "win_avg": _mean_metric(winners, "bars_held"),
            "loss_avg": _mean_metric(losers, "bars_held"),
        },
        "mae_r": {
            "win_avg": _mean_metric(winners, "mae_r"),
            "loss_avg": _mean_metric(losers, "mae_r"),
        },
        "mfe_r": {
            "win_avg": _mean_metric(winners, "mfe_r"),
            "loss_avg": _mean_metric(losers, "mfe_r"),
        },
    }

    # Breakdown by POI Type
    poi_summary = []
    if "poi_type" in df_trades.columns:
        for ptype, group in df_trades.groupby("poi_type"):
            p_total = len(group)
            p_wins = len(group[group["realized_r"] > 0])
            p_net_r = float(group["realized_r"].sum())
            p_gross_win = float(group[group["realized_r"] > 0]["realized_r"].sum())
            p_gross_loss = abs(float(group[group["realized_r"] < 0]["realized_r"].sum()))
            p_pf = p_gross_win / p_gross_loss if p_gross_loss > 0 else (999.0 if p_gross_win > 0 else 0.0)
            poi_summary.append({
                "poi_type": str(ptype),
                "trades": p_total,
                "win_rate": (p_wins / p_total) * 100.0,
                "net_r": p_net_r,
                "profit_factor": p_pf,
            })
    poi_summary.sort(key=lambda x: x["net_r"], reverse=True)

    # Breakdown by Market Regime
    regime_summary = []
    if "regime" in df_trades.columns:
        for reg, group in df_trades.groupby("regime"):
            r_total = len(group)
            r_wins = len(group[group["realized_r"] > 0])
            r_net_r = float(group["realized_r"].sum())
            r_gross_win = float(group[group["realized_r"] > 0]["realized_r"].sum())
            r_gross_loss = abs(float(group[group["realized_r"] < 0]["realized_r"].sum()))
            r_pf = r_gross_win / r_gross_loss if r_gross_loss > 0 else (999.0 if r_gross_win > 0 else 0.0)
            regime_summary.append({
                "regime": str(reg),
                "trades": r_total,
                "win_rate": (r_wins / r_total) * 100.0,
                "net_r": r_net_r,
                "profit_factor": r_pf,
            })
    regime_summary.sort(key=lambda x: x["net_r"], reverse=True)

    # Breakdown by Symbol
    symbol_summary = []
    if "symbol" in df_trades.columns:
        for sym, group in df_trades.groupby("symbol"):
            s_total = len(group)
            s_wins = len(group[group["realized_r"] > 0])
            s_net_r = float(group["realized_r"].sum())
            s_gross_win = float(group[group["realized_r"] > 0]["realized_r"].sum())
            s_gross_loss = abs(float(group[group["realized_r"] < 0]["realized_r"].sum()))
            s_pf = s_gross_win / s_gross_loss if s_gross_loss > 0 else (999.0 if s_gross_win > 0 else 0.0)
            symbol_summary.append({
                "symbol": str(sym),
                "trades": s_total,
                "win_rate": (s_wins / s_total) * 100.0,
                "net_r": s_net_r,
                "profit_factor": s_pf,
            })
    symbol_summary.sort(key=lambda x: x["net_r"], reverse=True)

    # Breakdown by Entry Hour (UTC)
    session_summary = []
    if "entry_time" in df_trades.columns and pd.api.types.is_datetime64_any_dtype(df_trades["entry_time"]):
        df_copy = df_trades.copy()
        df_copy["hour"] = df_copy["entry_time"].dt.hour
        for hour, group in df_copy.groupby("hour"):
            h_total = len(group)
            h_wins = len(group[group["realized_r"] > 0])
            h_net_r = float(group["realized_r"].sum())
            session_summary.append({
                "hour_utc": int(hour),
                "trades": h_total,
                "win_rate": (h_wins / h_total) * 100.0,
                "net_r": h_net_r,
            })
        session_summary.sort(key=lambda x: x["hour_utc"])

    # Rejection Reasons Breakdown
    rejection_summary = []
    if df_rejected is not None and not df_rejected.empty and "reason" in df_rejected.columns:
        rej_total = len(df_rejected)
        for reason, count in df_rejected["reason"].value_counts().items():
            rejection_summary.append({
                "reason": str(reason),
                "count": int(count),
                "pct": (count / rej_total) * 100.0,
            })

    return {
        "total_trades": total,
        "win_count": win_count,
        "loss_count": loss_count,
        "be_count": be_count,
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "be_rate": be_rate,
        "total_r": total_r,
        "total_pnl": total_pnl,
        "profit_factor": profit_factor,
        "expectancy_r": expectancy_r,
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "win_loss_ratio": win_loss_ratio,
        "max_drawdown_r": max_dd_r,
        "feature_comparison": feature_comparison,
        "poi_summary": poi_summary,
        "regime_summary": regime_summary,
        "symbol_summary": symbol_summary,
        "session_summary": session_summary,
        "rejection_summary": rejection_summary,
    }


def format_analytics_report(metrics: dict[str, Any]) -> str:
    """Format the analytics metrics into a clear, institutional-grade text report."""
    if metrics.get("total_trades", 0) == 0:
        return (
            "======================================================================\n"
            "            PRAGMA KANTİTATİF İŞLEM VE TEŞHİS RAPORU\n"
            "======================================================================\n"
            "Henüz tamamlanmış işlem kaydı bulunmamaktadır.\n"
            f"Kayıtlı reddedilen sinyal sayısı: {metrics.get('rejections_count', 0)}\n"
        )

    lines = [
        "======================================================================",
        "               PRAGMA KANTİTATİF İŞLEM VE TEŞHİS RAPORU",
        "======================================================================",
        f"Toplam İşlem     : {metrics['total_trades']:<6} | Net R          : {metrics['total_r']:+.2f} R",
        f"Kazanan (TP)     : {metrics['win_count']} (%{metrics['win_rate']:.1f}) | Net PnL        : ${metrics['total_pnl']:+,.2f}",
        f"Kaybeden (SL)    : {metrics['loss_count']} (%{metrics['loss_rate']:.1f}) | Profit Factor  : {metrics['profit_factor']:.2f}",
        f"Başabaş (BE)     : {metrics['be_count']} (%{metrics['be_rate']:.1f}) | Beklenen Değer : {metrics['expectancy_r']:+.2f} R/işlem",
        f"Ortalama Kazanç  : +{metrics['avg_win_r']:.2f} R | Ortalama Kayıp : -{metrics['avg_loss_r']:.2f} R",
        f"Kazanç/Kayıp Oran: {metrics['win_loss_ratio']:.2f}x   | Maks. Drawdown : {metrics['max_drawdown_r']:.2f} R",
        "----------------------------------------------------------------------",
        "1. KÖK NEDEN VE KARAKTERİSTİK ANALİZİ (TP vs SL FARK ANATOMİSİ)",
        "----------------------------------------------------------------------",
        f"{'ÖZELLİK':<26} {'KAZANANLAR (TP)':<18} {'KAYBEDENLER (SL)':<18} {'FARK':<10}",
    ]

    fc = metrics["feature_comparison"]
    def _val(x):
        return f"{x:.2f}" if x is not None else "N/A"

    def _diff(w, l):
        return f"{(w - l):+.2f}" if (w is not None and l is not None) else "N/A"

    lines.append(f"{'Giriş Z-Score Ortalaması':<26} {_val(fc['z_score']['win_avg']):<18} {_val(fc['z_score']['loss_avg']):<18} {_diff(fc['z_score']['win_avg'], fc['z_score']['loss_avg']):<10}")
    lines.append(f"{'Hacim Çarpanı (Volume x)':<26} {_val(fc['volume_multiplier']['win_avg']):<18} {_val(fc['volume_multiplier']['loss_avg']):<18} {_diff(fc['volume_multiplier']['win_avg'], fc['volume_multiplier']['loss_avg']):<10}")
    lines.append(f"{'Ortalama Tutma Süresi (Bar)':<26} {_val(fc['holding_bars']['win_avg']):<18} {_val(fc['holding_bars']['loss_avg']):<18} {_diff(fc['holding_bars']['win_avg'], fc['holding_bars']['loss_avg']):<10}")
    lines.append(f"{'Ortalama MAE (Aleyhe Sapma R)':<26} {_val(fc['mae_r']['win_avg']):<18} {_val(fc['mae_r']['loss_avg']):<18} {_diff(fc['mae_r']['win_avg'], fc['mae_r']['loss_avg']):<10}")
    lines.append(f"{'Ortalama MFE (Lehe Uzanma R)':<26} {_val(fc['mfe_r']['win_avg']):<18} {_val(fc['mfe_r']['loss_avg']):<18} {_diff(fc['mfe_r']['win_avg'], fc['mfe_r']['loss_avg']):<10}")

    lines.append("----------------------------------------------------------------------")
    lines.append("2. POI TİPİNE GÖRE PERFORMANS DAĞILIMI")
    lines.append("----------------------------------------------------------------------")
    lines.append(f"{'POI TİPİ':<28} {'İŞLEM':<7} {'WIN %':<8} {'NET R':<10} {'PF':<6}")
    for item in metrics["poi_summary"]:
        lines.append(f"{item['poi_type']:<28} {item['trades']:<7} %{item['win_rate']:<7.1f} {item['net_r']:<+10.2f} {item['profit_factor']:<6.2f}")

    lines.append("----------------------------------------------------------------------")
    lines.append("3. PİYASA REJİMİNE GÖRE DAĞILIM")
    lines.append("----------------------------------------------------------------------")
    lines.append(f"{'REJİM':<28} {'İŞLEM':<7} {'WIN %':<8} {'NET R':<10} {'PF':<6}")
    for item in metrics["regime_summary"]:
        lines.append(f"{item['regime']:<28} {item['trades']:<7} %{item['win_rate']:<7.1f} {item['net_r']:<+10.2f} {item['profit_factor']:<6.2f}")

    lines.append("----------------------------------------------------------------------")
    lines.append("4. SEMBOL BAZLI NET KÂR / ZARAR TABLOSU")
    lines.append("----------------------------------------------------------------------")
    lines.append(f"{'SEMBOL':<14} {'İŞLEM':<7} {'WIN %':<8} {'NET R':<10} {'PF':<6}")
    for item in metrics["symbol_summary"]:
        lines.append(f"{item['symbol']:<14} {item['trades']:<7} %{item['win_rate']:<7.1f} {item['net_r']:<+10.2f} {item['profit_factor']:<6.2f}")

    if metrics.get("rejection_summary"):
        lines.append("----------------------------------------------------------------------")
        lines.append("5. İŞLEME GİRMEYEN SİNYALLER (FİLTREYE TAKILMA NEDENLERİ)")
        lines.append("----------------------------------------------------------------------")
        lines.append(f"{'RED GEREKÇESİ':<40} {'ADET':<8} {'ORAN'}")
        for item in metrics["rejection_summary"]:
            lines.append(f"{item['reason']:<40} {item['count']:<8} %{item['pct']:.1f}")

    lines.append("======================================================================")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pragma Quantitative Trade & Diagnostic Analytics")
    parser.add_argument("--journal-path", default=str(default_journal_path()),
                        help="Path to trade_journal.csv")
    parser.add_argument("--rejected-path", default=str(default_rejected_path()),
                        help="Path to rejected_signals.csv")
    parser.add_argument("--state-path", default=str(default_state_path()),
                        help="Path to state.json fallback")
    parser.add_argument("--export-json", default=None, help="Export metrics to JSON file")
    parser.add_argument("--export-md", default=None, help="Export report to Markdown file")
    args = parser.parse_args(argv)

    journal_file = Path(args.journal_path).expanduser()
    df_trades = load_trade_journal(journal_file)

    # Fallback to state.json if journal CSV is empty but state.json has closed trades
    if df_trades.empty:
        state_file = Path(args.state_path).expanduser()
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                closed = state.get("closed_trades", [])
                if closed:
                    df_trades = pd.DataFrame(closed)
                    for num_col in ["entry_price", "exit_price", "initial_stop", "final_stop",
                                    "take_profit_1", "take_profit_2", "rr_planned", "realized_r",
                                    "realized_pnl", "bars_held", "mae_r", "mfe_r", "z_score",
                                    "volume_multiplier", "order_flow_delta", "atr", "vwap", "pdpoc", "balance_after"]:
                        if num_col in df_trades.columns:
                            df_trades[num_col] = pd.to_numeric(df_trades[num_col], errors="coerce")
                    if "entry_time" in df_trades.columns:
                        df_trades["entry_time"] = pd.to_datetime(df_trades["entry_time"], errors="coerce", utc=True)
            except Exception:
                pass

    rejected_file = Path(args.rejected_path).expanduser()
    df_rejected = load_rejected_signals(rejected_file) if rejected_file.exists() else None

    metrics = analyze_trade_journal(df_trades, df_rejected)
    report = format_analytics_report(metrics)
    print(report)

    if args.export_json:
        out_json = Path(args.export_json).expanduser()
        out_json.parent.mkdir(parents=True, exist_ok=True)
        # Convert non-serializable items
        clean_metrics = json.loads(json.dumps(metrics, default=str))
        out_json.write_text(json.dumps(clean_metrics, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[INFO] Rapor JSON olarak kaydedildi: {out_json}")

    if args.export_md:
        out_md = Path(args.export_md).expanduser()
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(f"```text\n{report}\n```\n", encoding="utf-8")
        print(f"\n[INFO] Rapor Markdown olarak kaydedildi: {out_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
