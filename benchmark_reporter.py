"""CLI Reporter for Pragma Retrospective Benchmark & Macro Gate Records."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pragma.benchmark_recorder import BenchmarkRecorder, PROJECT_ROOT


def generate_markdown_report(payload: dict[str, Any], macro_history_count: int) -> str:
    summary = payload.get("summary", {})
    cats = payload.get("categories", {})
    succ = cats.get("successful_entries", [])
    false_e = cats.get("false_entries", [])
    pending = cats.get("pending_Shadow", [])
    missed = cats.get("missed_opportunities", [])
    rej_breakdown = summary.get("rejection_reasons_breakdown", {})

    lines = [
        "# PRAGMA — Gölge İşlem (Shadow) & Makro Kapı Benchmark Raporu",
        "",
        f"- **Son Güncelleme (UTC):** `{payload.get('updated_at')}`",
        f"- **Veri Kaynağı:** `{payload.get('state_dir')}`",
        f"- **Kaydedilen Makro Kapı (`macro_bias_gate.json`) Snapshot Sayısı:** `{macro_history_count}`",
        "",
        "## 1. Genel Performans ve 5'li Benchmark Özeti",
        "",
        "| Kategori / Metrik | Değer | Açıklama |",
        "| :--- | :---: | :--- |",
        f"| **Kapanan Gölge İşlem** | `{summary.get('total_closed_trades', 0)}` | Tamamlanan sanal işlemler |",
        f"| **1. Başarılı Girişler (`successful_entries`)** | `{summary.get('successful_entries_count', 0)}` | Pozitif R ile kapanan işlemler |",
        f"| **2. Hatalı Girişler (`false_entries`)** | `{summary.get('false_entries_count', 0)}` | SL / negatif R ile kapanan işlemler + hata teşhisi |",
        f"| **3. Doğru Redler (`correct_rejections`)** | `{summary.get('correct_rejections_count', 0)}` | Filtrelerin doğru şekilde engellediği zayıf sinyaller |",
        f"| **4. Kaçan Fırsatlar (`missed_opportunities`)** | `{summary.get('missed_opportunities_count', 0)}` | Yüksek RR ve güçlü Z-Score'a rağmen elenen sinyaller |",
        f"| **5. Açık Gölge İşlemler (`pending_Shadow`)** | `{summary.get('pending_shadow_count', 0)}` | Şu an açık takip edilen sanal işlemler |",
        f"| **Kazanma Oranı (Win Rate)** | `%{summary.get('win_rate_pct', 0.0):.1f}` | Pozitif kapanış oranı |",
        f"| **Toplam Net R** | `{summary.get('net_r', 0.0):+.2f}R` | Kümülatif R getirisi |",
        f"| **Toplam Net PnL** | `{summary.get('net_pnl', 0.0):+.2f} USD` | 10,000 USD başlangıç bakiyesi üzerinden net fark |",
        "",
        "## 2. Reddedilen Sinyallerin (`rejected_signals`) Neden Dağılımı",
        "",
        "| Red Nedeni | Adet |",
        "| :--- | :---: |",
    ]
    if rej_breakdown:
        for reason, cnt in sorted(rej_breakdown.items(), key=lambda x: -x[1]):
            lines.append(f"| `{reason}` | `{cnt}` |")
    else:
        lines.append("| Kayıt yok | `0` |")

    lines.extend([
        "",
        "## 3. Hatalı Girişler (`false_entries`) ve Geriye Dönük Hata Teşhisi",
        "",
        "| Tarih | Sembol | Yön | Sonuç | Net R | MAE / MFE (R) | Makro Uyum | Hata Teşhisi |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ])
    if false_e:
        for item in false_e[-20:]:
            m_ctx = item.get("macro_context", {})
            diag = "; ".join(item.get("error_diagnosis", []))
            lines.append(
                f"| `{str(item.get('entry_time'))[:16]}` | **{item.get('symbol')}** | `{item.get('direction')}` "
                f"| `{item.get('outcome')}` | `{item.get('realized_r', 0.0):+.2f}R` "
                f"| `{item.get('mae_r', 0.0):.2f}R / {item.get('mfe_r', 0.0):.2f}R` "
                f"| `{m_ctx.get('gate_alignment')}` | {diag} |"
            )
    else:
        lines.append("| - | - | - | - | - | - | - | Hatalı giriş kaydı bulunmuyor |")

    lines.extend([
        "",
        "## 4. Başarılı Girişler (`successful_entries`)",
        "",
        "| Tarih | Sembol | Yön | Sonuç | Net R | Net PnL | MAE / MFE (R) | Makro Uyum |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])
    if succ:
        for item in succ[-20:]:
            m_ctx = item.get("macro_context", {})
            lines.append(
                f"| `{str(item.get('entry_time'))[:16]}` | **{item.get('symbol')}** | `{item.get('direction')}` "
                f"| `{item.get('outcome')}` | `{item.get('realized_r', 0.0):+.2f}R` "
                f"| `{item.get('net_pnl', 0.0):+.2f} USD` "
                f"| `{item.get('mae_r', 0.0):.2f}R / {item.get('mfe_r', 0.0):.2f}R` "
                f"| `{m_ctx.get('gate_alignment')}` |"
            )
    else:
        lines.append("| - | - | - | - | - | - | - | - |")

    lines.extend([
        "",
        "## 5. Potansiyel Kaçan Fırsatlar (`missed_opportunities` — Örneklem)",
        "",
        "| Tarih | Sembol | Yön | Red Nedeni | Planlanan RR | Z-Score | Makro Uyum |",
        "| :--- | :---: | :---: | :--- | :---: | :---: | :---: |",
    ])
    if missed:
        for item in missed[-15:]:
            m_ctx = item.get("macro_context", {})
            lines.append(
                f"| `{str(item.get('timestamp'))[:16]}` | **{item.get('symbol')}** | `{item.get('direction')}` "
                f"| `{item.get('reason')}` | `{item.get('rr_ratio', 0.0):.2f}` "
                f"| `{item.get('z_score', 0.0):+.2f}` | `{m_ctx.get('gate_alignment')}` |"
            )
    else:
        lines.append("| - | - | - | Güçlü RR + Z-Score olup reddedilen sinyal yok | - | - | - |")

    if pending:
        lines.extend([
            "",
            "## 6. Açık Gölge İşlemler (`pending_Shadow`)",
            "",
            "| Sembol | Yön | Giriş Zamanı | Giriş Fiyatı | SL | TP1 / TP2 | Bar Sayısı |",
            "| :---: | :---: | :--- | :---: | :---: | :---: | :---: |",
        ])
        for p in pending:
            lines.append(
                f"| **{p.get('symbol')}** | `{p.get('direction')}` | `{str(p.get('entry_time'))[:16]}` "
                f"| `{p.get('entry_price')}` | `{p.get('stop_loss')}` "
                f"| `{p.get('take_profit_1')} / {p.get('take_profit_2')}` | `{p.get('bars_held')}` |"
            )

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    recorder = BenchmarkRecorder()
    payload = recorder.sync()
    macro_hist_count = 0
    if recorder.macro_history_path.exists():
        macro_hist_count = sum(1 for ln in recorder.macro_history_path.read_text(encoding="utf-8").splitlines() if ln.strip())
    report_md = generate_markdown_report(payload, macro_hist_count)
    report_path = PROJECT_ROOT / "PRAGMA_BENCHMARK_RAPOR.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"[PRAGMA BENCHMARK] Synced -> {recorder.benchmark_records_path}")
    print(f"[PRAGMA BENCHMARK] Macro  -> {recorder.macro_records_path} (snapshots={macro_hist_count})")
    print(f"[PRAGMA BENCHMARK] Report -> {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
