"""Retrospective Benchmark & Macro Gate Recorder for Pragma.

Provides Begonya/CLT-compatible retrospective recording of:
1. Macro Gate History (`benchmark/macro_gate_history.jsonl`) — full archival of
   every Begonya `macro_bias_gate.json` change (`currency_scores`, `global_regime`,
   symbol gates, sha256 fingerprint).
2. 5-Category Benchmark Records (`benchmark/benchmark_records.json`):
   - `successful_entries`: Closed shadow trades with realized_r > 0
   - `false_entries`: Closed shadow trades with realized_r <= 0 + root-cause diagnosis
   - `correct_rejections`: Rejected triggers where filter prevented low-quality entry
   - `missed_opportunities`: Rejected triggers with strong Z-score/RR that were blocked
   - `pending_Shadow`: Currently open shadow positions
3. Macro Attribution (`benchmark/macro_records.json`):
   - Links every trade and rejection to its historical/live Macro Gate snapshot
     (`base_score`, `quote_score`, `score_diff`, `global_regime`, `gate_alignment`).
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BENCHMARK_DIR = PROJECT_ROOT / "benchmark"

MACRO_GATE_CANDIDATE_PATHS = (
    Path(r"C:\Users\piard\.gemini\antigravity\scratch\Begonya\shared\macro_bias_gate.json"),
    Path(r"C:\Users\piard\Desktop\Begonya00\shared\macro_bias_gate.json"),
    PROJECT_ROOT.parent / "Begonya" / "shared" / "macro_bias_gate.json",
    PROJECT_ROOT / "data" / "macro_bias_gate.json",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> float | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(val)
    except Exception:
        return default


def _split_symbol_currencies(symbol: str) -> tuple[str | None, str | None]:
    clean = str(symbol or "").upper().strip()
    if len(clean) == 6 and clean.isalpha():
        return clean[:3], clean[3:]
    if clean.startswith("XAU"):
        return "XAU", clean[3:] or "USD"
    if clean.endswith("USDT"):
        return clean[:-4], "USD"
    if clean.endswith("USD"):
        return clean[:-3], "USD"
    return None, None


class BenchmarkRecorder:
    """Archives Begonya macro_bias_gate.json changes and syncs Pragma shadow trades & rejections."""

    def __init__(
        self,
        benchmark_dir: Path | str | None = None,
        state_dir: Path | str | None = None,
        macro_gate_path: Path | str | None = None,
    ) -> None:
        self.benchmark_dir = Path(benchmark_dir) if benchmark_dir else DEFAULT_BENCHMARK_DIR
        self.benchmark_dir.mkdir(parents=True, exist_ok=True)

        app_data = os.environ.get("LOCALAPPDATA")
        default_state = (Path(app_data) / "Pragma" / "shadow_trading") if app_data else (Path.home() / ".pragma" / "shadow_trader")
        self.state_dir = Path(state_dir) if state_dir else default_state

        self.macro_gate_path = Path(macro_gate_path) if macro_gate_path else self._discover_macro_gate()
        self.macro_history_path = self.benchmark_dir / "macro_gate_history.jsonl"
        self.benchmark_records_path = self.benchmark_dir / "benchmark_records.json"
        self.macro_records_path = self.benchmark_dir / "macro_records.json"

        self._last_macro_sha256: str | None = self._load_last_macro_sha256()

    @staticmethod
    def _discover_macro_gate() -> Path:
        env_override = os.environ.get("BEGONYA_MACRO_GATE_PATH")
        if env_override and Path(env_override).exists():
            return Path(env_override)
        for candidate in MACRO_GATE_CANDIDATE_PATHS:
            if candidate.exists():
                return candidate
        return MACRO_GATE_CANDIDATE_PATHS[0]

    def _load_last_macro_sha256(self) -> str | None:
        if not self.macro_history_path.exists():
            return None
        try:
            lines = [ln.strip() for ln in self.macro_history_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if not lines:
                return None
            return json.loads(lines[-1]).get("sha256")
        except Exception:
            return None

    def snapshot_macro_gate(self) -> dict[str, Any] | None:
        """Check Begonya macro_bias_gate.json and append to macro_gate_history.jsonl if changed."""
        path = self.macro_gate_path if self.macro_gate_path.exists() else self._discover_macro_gate()
        if not path.exists():
            return None
        try:
            raw_bytes = path.read_bytes()
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None

        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if digest != self._last_macro_sha256:
            entry = {
                "recorded_at": _now_iso(),
                "source_path": str(path),
                "sha256": digest,
                "generated_at": payload.get("generated_at") or payload.get("timestamp"),
                "primary_regime": payload.get("primary_regime") or payload.get("global_regime", "UNKNOWN"),
                "volatility_risk_score": payload.get("volatility_risk_score"),
                "capital_preservation_mode": payload.get("capital_preservation_mode", False),
                "execution_bias_gates": payload.get("execution_bias_gates", {}),
                "gate_conviction_multipliers": payload.get("gate_conviction_multipliers", {}),
                "payload": payload,
            }
            with self.macro_history_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._last_macro_sha256 = digest
        return payload

    def _load_macro_timeline(self) -> list[tuple[float, dict[str, Any]]]:
        timeline: list[tuple[float, dict[str, Any]]] = []
        if self.macro_history_path.exists():
            try:
                for line in self.macro_history_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    payload = item.get("payload") or {}
                    ts = _parse_ts(item.get("generated_at")) or _parse_ts(item.get("recorded_at")) or 0.0
                    timeline.append((ts, payload))
            except Exception:
                pass
        timeline.sort(key=lambda x: x[0])
        return timeline

    @staticmethod
    def _resolve_macro_for_event(
        symbol: str,
        direction: str,
        event_time: Any,
        logged_bias: Any,
        timeline: list[tuple[float, dict[str, Any]]],
        fallback_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = fallback_payload or {}
        ev_ts = _parse_ts(event_time)
        if timeline and ev_ts is not None:
            chosen = timeline[0][1]
            for ts, snap in timeline:
                if ts <= ev_ts:
                    chosen = snap
                else:
                    break
            payload = chosen
        elif timeline:
            payload = timeline[-1][1]

        sym_upper = str(symbol or "").upper()
        exec_gates = payload.get("execution_bias_gates") or payload.get("deterministic_execution_bias_gates") or {}
        conv_mults = payload.get("gate_conviction_multipliers") or {}
        gate_reasons = payload.get("deterministic_gate_reasons") or {}
        alias_key = "BTC" if sym_upper in ("BTCUSDT", "BTCUSD") else ("SOL" if sym_upper in ("SOLUSDT", "SOLUSD") else sym_upper)

        raw_exec_gate = exec_gates.get(sym_upper) or exec_gates.get(alias_key)
        if isinstance(raw_exec_gate, str):
            gate_dir = raw_exec_gate.upper()
            gate_status = "ACTIVE" if gate_dir in ("LONG_ONLY", "SHORT_ONLY") else "DEFENSIVE_HOLD"
            gate_conf = conv_mults.get(sym_upper) or conv_mults.get(alias_key)
            gate_reason = gate_reasons.get(sym_upper) or gate_reasons.get(alias_key)
        else:
            gates = payload.get("gates") if isinstance(payload.get("gates"), dict) else payload
            sym_gate = gates.get(sym_upper, {}) if isinstance(gates, dict) else {}
            if not isinstance(sym_gate, dict):
                sym_gate = {}
            gate_dir = str(sym_gate.get("direction", "NEUTRAL")).upper()
            gate_status = str(sym_gate.get("status", "UNKNOWN")).upper()
            gate_conf = sym_gate.get("confidence")
            gate_reason = sym_gate.get("reason")

        scores = payload.get("currency_scores", {}) if isinstance(payload.get("currency_scores"), dict) else {}
        base_ccy, quote_ccy = _split_symbol_currencies(sym_upper)
        base_score = _safe_float(scores.get(base_ccy), 0.0) if base_ccy in scores else None
        quote_score = _safe_float(scores.get(quote_ccy), 0.0) if quote_ccy in scores else None
        score_diff = round(base_score - quote_score, 4) if (base_score is not None and quote_score is not None) else None

        dir_upper = str(direction or "").upper()

        bias_int = int(_safe_float(logged_bias, 0.0)) if str(logged_bias or "").strip() in ("1", "-1", "0", "+1") else None
        if bias_int == 1 and dir_upper == "LONG":
            alignment = "ALIGNED"
        elif bias_int == -1 and dir_upper == "SHORT":
            alignment = "ALIGNED"
        elif gate_dir in ("LONG_ONLY", "LONG") and dir_upper == "LONG":
            alignment = "ALIGNED"
        elif gate_dir in ("SHORT_ONLY", "SHORT") and dir_upper == "SHORT":
            alignment = "ALIGNED"
        elif gate_dir == "BLOCKED" or gate_status in ("DEFENSIVE_HOLD", "BLOCKED"):
            alignment = "MACRO_HOLD_AT_SNAPSHOT"
        else:
            alignment = "NEUTRAL_OR_UNALIGNED"

        return {
            "primary_regime": payload.get("primary_regime") or payload.get("global_regime", "UNKNOWN"),
            "volatility_risk_score": payload.get("volatility_risk_score"),
            "snapshot_generated_at": payload.get("generated_at") or payload.get("timestamp"),
            "logged_macro_bias": logged_bias,
            "gate_status": gate_status,
            "gate_direction": gate_dir,
            "gate_conviction": gate_conf,
            "gate_reason": gate_reason,
            "base_currency": base_ccy,
            "base_score": base_score,
            "quote_currency": quote_ccy,
            "quote_score": quote_score,
            "score_diff": score_diff,
            "gate_alignment": alignment,
        }

    @staticmethod
    def _diagnose_false_entry(trade: dict[str, Any], macro_ctx: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        mfe_r = _safe_float(trade.get("mfe_r"), 0.0)
        mae_r = _safe_float(trade.get("mae_r"), 0.0)
        bars_held = int(_safe_float(trade.get("bars_held"), 0))
        rr_planned = _safe_float(trade.get("rr_planned"), 0.0)

        if mfe_r < 0.25:
            reasons.append("IMMEDIATE_ADVERSE_SELECTION (Fiyat girişten sonra +0.25R bile lehimize gitmeden SL oldu)")
        elif mfe_r >= 0.80:
            reasons.append(f"REVERSAL_BEFORE_TP1 (Fiyat +{mfe_r:.2f}R kâra kadar gidip TP1 alamadan geri döndü)")
        if bars_held <= 5:
            reasons.append(f"FAST_STOPOUT ({bars_held} bar içinde hızlı stop — likidite süpürmesi devam etti)")
        if rr_planned < 1.3:
            reasons.append(f"LOW_PLANNED_RR (Planlanan RR={rr_planned:.2f} düşük)")
        score_diff = macro_ctx.get("score_diff")
        direction = str(trade.get("direction", "")).upper()
        if score_diff is not None:
            if direction == "LONG" and score_diff < 0:
                reasons.append(f"WEAK_MACRO_DIFF (LONG işlemde Base-Quote skoru negatif: {score_diff:+.2f})")
            elif direction == "SHORT" and score_diff > 0:
                reasons.append(f"WEAK_MACRO_DIFF (SHORT işlemde Base-Quote skoru pozitif: {score_diff:+.2f})")
        if not reasons:
            reasons.append(f"STANDARD_SL_HIT (MAE={mae_r:.2f}R, MFE={mfe_r:.2f}R, {bars_held} bar)")
        return reasons

    def sync(self) -> dict[str, Any]:
        """Synchronize Pragma shadow state, trade journal, rejected signals, and macro history."""
        latest_macro = self.snapshot_macro_gate()
        timeline = self._load_macro_timeline()

        state_file = self.state_dir / "state.json"
        journal_file = self.state_dir / "trade_journal.csv"
        rejected_file = self.state_dir / "rejected_signals.csv"

        open_positions: dict[str, Any] = {}
        closed_trades: list[dict[str, Any]] = []
        state_meta: dict[str, Any] = {}

        if state_file.exists():
            try:
                raw_state = json.loads(state_file.read_text(encoding="utf-8"))
                open_positions = raw_state.get("open_positions", {}) or {}
                closed_trades = list(raw_state.get("closed_trades", []) or [])
                state_meta = {
                    "balance": raw_state.get("balance"),
                    "initial_balance": raw_state.get("initial_balance"),
                    "max_drawdown": raw_state.get("max_drawdown"),
                    "macro_status": raw_state.get("macro_status"),
                    "active_symbols_count": raw_state.get("active_symbols_count"),
                    "updated_at": raw_state.get("updated_at"),
                }
            except Exception:
                pass

        # Backfill from trade_journal.csv if any trade is missing in state.json
        seen_ids = {str(t.get("trade_id")) for t in closed_trades if t.get("trade_id")}
        if journal_file.exists():
            try:
                with journal_file.open("r", encoding="utf-8") as fh:
                    for row in csv.DictReader(fh):
                        tid = str(row.get("trade_id", "")).strip()
                        if tid and tid not in seen_ids:
                            closed_trades.append(dict(row))
                            seen_ids.add(tid)
            except Exception:
                pass

        rejected_rows: list[dict[str, Any]] = []
        if rejected_file.exists():
            try:
                with rejected_file.open("r", encoding="utf-8") as fh:
                    rejected_rows = list(csv.DictReader(fh))
            except Exception:
                pass

        successful_entries: list[dict[str, Any]] = []
        false_entries: list[dict[str, Any]] = []
        pending_shadow: list[dict[str, Any]] = []
        correct_rejections: list[dict[str, Any]] = []
        missed_opportunities: list[dict[str, Any]] = []

        trades_with_macro: list[dict[str, Any]] = []
        rejections_with_macro: list[dict[str, Any]] = []

        for trade in closed_trades:
            sym = str(trade.get("symbol", "")).upper()
            direction = str(trade.get("direction", "")).upper()
            entry_time = trade.get("entry_time")
            realized_r = _safe_float(trade.get("realized_r"), 0.0)
            net_pnl = _safe_float(trade.get("net_pnl", trade.get("realized_pnl")), 0.0)
            macro_ctx = self._resolve_macro_for_event(
                sym, direction, entry_time, trade.get("macro_bias"), timeline, latest_macro
            )
            enriched = {
                "trade_id": trade.get("trade_id"),
                "symbol": sym,
                "direction": direction,
                "poi_type": trade.get("poi_type"),
                "regime": trade.get("regime"),
                "entry_time": entry_time,
                "exit_time": trade.get("exit_time"),
                "entry_price": _safe_float(trade.get("entry_price")),
                "exit_price": _safe_float(trade.get("exit_price")),
                "initial_stop": _safe_float(trade.get("initial_stop", trade.get("stop_loss"))),
                "take_profit_1": _safe_float(trade.get("take_profit_1")),
                "take_profit_2": _safe_float(trade.get("take_profit_2")),
                "rr_planned": _safe_float(trade.get("rr_planned")),
                "realized_r": round(realized_r, 4),
                "net_pnl": round(net_pnl, 2),
                "outcome": trade.get("outcome"),
                "bars_held": int(_safe_float(trade.get("bars_held"), 0)),
                "mae_r": round(_safe_float(trade.get("mae_r")), 4),
                "mfe_r": round(_safe_float(trade.get("mfe_r")), 4),
                "z_score": _safe_float(trade.get("z_score"), 0.0),
                "macro_context": macro_ctx,
            }
            if realized_r > 0:
                enriched["classification"] = "SUCCESSFUL_ENTRY"
                successful_entries.append(enriched)
            else:
                enriched["classification"] = "FALSE_ENTRY"
                enriched["error_diagnosis"] = self._diagnose_false_entry(enriched, macro_ctx)
                false_entries.append(enriched)
            trades_with_macro.append(enriched)

        for sym, pos in open_positions.items():
            direction = str(pos.get("direction", "")).upper()
            entry_time = pos.get("entry_time")
            macro_ctx = self._resolve_macro_for_event(
                sym, direction, entry_time, pos.get("macro_bias"), timeline, latest_macro
            )
            pending_shadow.append({
                "trade_id": pos.get("trade_id"),
                "symbol": sym,
                "direction": direction,
                "poi_type": pos.get("poi_type"),
                "regime": pos.get("regime"),
                "entry_time": entry_time,
                "entry_price": _safe_float(pos.get("entry_price")),
                "stop_loss": _safe_float(pos.get("stop_loss")),
                "take_profit_1": _safe_float(pos.get("take_profit_1")),
                "take_profit_2": _safe_float(pos.get("take_profit_2")),
                "bars_held": int(_safe_float(pos.get("bars_held"), 0)),
                "mae_r": round(_safe_float(pos.get("mae_r")), 4),
                "mfe_r": round(_safe_float(pos.get("mfe_r")), 4),
                "macro_context": macro_ctx,
            })

        # Keep most recent 1000 rejected signals in JSON to stay fast and compact
        for row in rejected_rows[-1000:]:
            sym = str(row.get("symbol", "")).upper()
            direction = str(row.get("direction", "")).upper()
            ts = row.get("timestamp")
            reason = str(row.get("reason", "REJECTED")).strip()
            rr_ratio = _safe_float(row.get("rr_ratio"), 0.0)
            z_score = _safe_float(row.get("z_score"), 0.0)
            macro_ctx = self._resolve_macro_for_event(
                sym, direction, ts, row.get("macro_bias"), timeline, latest_macro
            )
            rec = {
                "timestamp": ts,
                "symbol": sym,
                "direction": direction,
                "poi_type": row.get("poi_type"),
                "regime": row.get("regime"),
                "reason": reason,
                "entry_price": _safe_float(row.get("entry_price")),
                "stop_loss": _safe_float(row.get("stop_loss")),
                "take_profit_1": _safe_float(row.get("take_profit_1")),
                "rr_ratio": round(rr_ratio, 4),
                "z_score": round(z_score, 4),
                "macro_context": macro_ctx,
            }
            # Classify rejection: if RR >= 2.0 and |z_score| >= 2.0 and macro aligned, flag as potential missed opportunity to inspect
            if rr_ratio >= 2.0 and abs(z_score) >= 2.0 and macro_ctx.get("gate_alignment") == "ALIGNED":
                rec["classification"] = "POTENTIAL_MISSED_OPPORTUNITY"
                missed_opportunities.append(rec)
            else:
                rec["classification"] = "CORRECT_REJECTION"
                correct_rejections.append(rec)
            rejections_with_macro.append(rec)

        total_closed = len(successful_entries) + len(false_entries)
        net_r = round(sum(t["realized_r"] for t in trades_with_macro), 4)
        net_pnl = round(sum(t["net_pnl"] for t in trades_with_macro), 2)
        win_rate = round((len(successful_entries) / total_closed * 100.0), 2) if total_closed > 0 else 0.0

        rejection_reasons_summary: dict[str, int] = {}
        for r in rejected_rows:
            rsn = str(r.get("reason", "UNKNOWN")).strip() or "UNKNOWN"
            rejection_reasons_summary[rsn] = rejection_reasons_summary.get(rsn, 0) + 1

        benchmark_payload = {
            "project": "PRAGMA",
            "updated_at": _now_iso(),
            "state_dir": str(self.state_dir),
            "summary": {
                "total_closed_trades": total_closed,
                "successful_entries_count": len(successful_entries),
                "false_entries_count": len(false_entries),
                "pending_shadow_count": len(pending_shadow),
                "total_rejected_signals": len(rejected_rows),
                "correct_rejections_count": len(correct_rejections),
                "missed_opportunities_count": len(missed_opportunities),
                "win_rate_pct": win_rate,
                "net_r": net_r,
                "net_pnl": net_pnl,
                "rejection_reasons_breakdown": rejection_reasons_summary,
                "account_state": state_meta,
            },
            "categories": {
                "successful_entries": successful_entries,
                "false_entries": false_entries,
                "correct_rejections": correct_rejections[-250:],
                "missed_opportunities": missed_opportunities[-250:],
                "pending_Shadow": pending_shadow,
            },
        }

        macro_payload = {
            "project": "PRAGMA",
            "updated_at": _now_iso(),
            "macro_gate_source": str(self.macro_gate_path),
            "macro_history_snapshots_count": len(timeline),
            "latest_macro_snapshot": {
                "timestamp": (latest_macro or {}).get("timestamp") or (latest_macro or {}).get("generated_at"),
                "primary_regime": (latest_macro or {}).get("primary_regime") or (latest_macro or {}).get("global_regime", "UNKNOWN"),
                "volatility_risk_score": (latest_macro or {}).get("volatility_risk_score"),
                "capital_preservation_mode": (latest_macro or {}).get("capital_preservation_mode", False),
                "execution_bias_gates": (latest_macro or {}).get("execution_bias_gates", {}),
                "gate_conviction_multipliers": (latest_macro or {}).get("gate_conviction_multipliers", {}),
            },
            "trades_with_macro": trades_with_macro,
            "rejections_with_macro_sample": rejections_with_macro[-200:],
        }

        self.benchmark_records_path.write_text(
            json.dumps(benchmark_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.macro_records_path.write_text(
            json.dumps(macro_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return benchmark_payload
