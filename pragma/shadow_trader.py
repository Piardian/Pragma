"""Broker-free shadow/paper trading for Pragma signals.

Reads prices from the local MT5 terminal but never submits, modifies, or closes broker orders.
All positions, realized PnL, and processing cursors are persisted locally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd

from pragma.data.mt5_data import MT5DataClient, filter_closed_bars
from pragma.execution_notifier import ExecutionNotifier
from pragma.run_pipeline import _active_begonya_mt5_symbols, run_pipeline
from pragma.trade_journal import record_rejected_signal, record_trade_to_journal


def default_state_dir() -> Path:
    override = os.environ.get("PRAGMA_SHADOW_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "Pragma" / "shadow_trading" if base else Path.home() / ".pragma" / "shadow_trading"


class ConsoleOnlyNotifier:
    """Prevent the normal signal notifier from duplicating shadow trade alerts."""
    def notify(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"sent": False, "reason": "SHADOW_BOOK_OWNS_NOTIFICATIONS"}

    def notify_poi(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"sent": False, "reason": "SHADOW_BOOK_OWNS_NOTIFICATIONS"}


class PaperTradingBook:
    """Deterministic virtual account with durable state and conservative OHLC exits."""

    def __init__(self, state_path: str | Path, initial_balance: float = 10_000.0,
                 risk_pct: float = 1.0, notifier: Any | None = None,
                 journal_path: str | Path | None = None,
                 rejected_path: str | Path | None = None,
                 enable_runner: bool = True):
        if initial_balance <= 0:
            raise ValueError("initial_balance must be positive")
        if not 0 < risk_pct <= 5:
            raise ValueError("risk_pct must be > 0 and <= 5")
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_path = Path(journal_path) if journal_path else self.path.parent / "trade_journal.csv"
        self.rejected_path = Path(rejected_path) if rejected_path else self.path.parent / "rejected_signals.csv"
        self.risk_pct = float(risk_pct)
        self.enable_runner = bool(enable_runner)
        self.notifier = notifier or ExecutionNotifier()
        self._symbol_cooldowns: dict[str, Any] = {}
        self.state: dict[str, Any] = {
            "version": 1,
            "initial_balance": float(initial_balance),
            "balance": float(initial_balance),
            "peak_balance": float(initial_balance),
            "max_drawdown": 0.0,
            "risk_pct": self.risk_pct,
            "open_positions": {},
            "closed_trades": [],
            "last_processed": {},
            "seen_signals": [],
            "seen_rejections": [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or loaded.get("version") != 1:
                raise ValueError(f"Unsupported or malformed shadow state file: {self.path}")
            required = {"initial_balance", "balance", "open_positions", "closed_trades", "last_processed"}
            if not required.issubset(loaded):
                raise ValueError(f"Shadow state is missing fields: {sorted(required - set(loaded))}")
            self.state = loaded
            # The risk percentage is part of the account's persisted configuration.
            self.risk_pct = float(loaded.get("risk_pct", risk_pct))
            # Auto-backfill trade_journal.csv if state.json has closed trades and CSV is missing
            if self.state.get("closed_trades") and (not self.journal_path.exists() or self.journal_path.stat().st_size == 0):
                for t in self.state["closed_trades"]:
                    try:
                        record_trade_to_journal(self.journal_path, t)
                    except Exception:
                        pass

    def _save(self) -> None:
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        content = json.dumps(self.state, indent=2, ensure_ascii=False)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temp.write_text(content, encoding="utf-8")
        except Exception:
            try:
                self.path.write_text(content, encoding="utf-8")
            except Exception as exc:
                print(f"[WARN] Failed to write state directly: {exc}", flush=True)
            return

        for attempt in range(5):
            try:
                os.replace(temp, self.path)
                return
            except (PermissionError, OSError):
                if attempt == 4:
                    try:
                        self.path.write_text(content, encoding="utf-8")
                    except Exception as exc:
                        print(f"[WARN] Failed to overwrite state.json: {exc}", flush=True)
                    try:
                        temp.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return
                time.sleep(0.05 * (attempt + 1))

    def _notify(self, text: str) -> None:
        send = getattr(self.notifier, "send_text", None)
        if callable(send):
            send(text)
        else:
            # ExecutionNotifier deliberately has no arbitrary-message method.
            token = getattr(self.notifier, "bot_token", "")
            chat_id = getattr(self.notifier, "chat_id", "")
            if token and chat_id:
                from urllib.parse import urlencode
                from urllib.request import Request, urlopen
                import urllib.error
                import json as _json
                request = Request(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data=urlencode({"chat_id": chat_id, "text": text}).encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Pragma/1.0"},
                    method="POST",
                )
                try:
                    with urlopen(request, timeout=8) as response:
                        body = _json.loads(response.read().decode("utf-8"))
                        if response.status < 200 or response.status >= 300 or not body.get("ok"):
                            raise RuntimeError(f"Telegram rejected message: {body}")
                except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                    print(f"[TELEGRAM ERROR] {exc}", flush=True)
            print(text, flush=True)

    @staticmethod
    def _bar_hits(bar: dict[str, float], direction: str, level: float, kind: str) -> bool:
        if kind == "sl":
            return bar["low"] <= level if direction == "LONG" else bar["high"] >= level
        return bar["high"] >= level if direction == "LONG" else bar["low"] <= level

    def touch(self) -> None:
        """Update updated_at and flush state to indicate daemon active liveness."""
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            self._save()
        except Exception:
            pass

    def _update_drawdown(self) -> None:
        balance = float(self.state["balance"])
        self.state["peak_balance"] = max(float(self.state["peak_balance"]), balance)
        drawdown = float(self.state["peak_balance"]) - balance
        self.state["max_drawdown"] = max(float(self.state.get("max_drawdown", 0.0)), drawdown)

    def get_scoreboard_stats(self, target_month: str | None = None) -> dict[str, Any]:
        """Calculate monthly and all-time closed trade statistics."""
        if target_month is None:
            target_month = datetime.now(timezone.utc).strftime("%Y-%m")

        all_closed = self.state.get("closed_trades", [])
        month_closed = [
            t for t in all_closed
            if str(t.get("exit_time", "")).startswith(target_month)
            or (not t.get("exit_time") and str(t.get("entry_time", "")).startswith(target_month))
        ]

        target_list = month_closed if month_closed else all_closed
        total = len(target_list)
        net_r = sum(float(t.get("realized_r", 0.0)) for t in target_list)
        tp_count = sum(1 for t in target_list if float(t.get("realized_r", 0.0)) > 0)
        sl_count = sum(1 for t in target_list if float(t.get("realized_r", 0.0)) < 0)
        be_count = sum(1 for t in target_list if float(t.get("realized_r", 0.0)) == 0)
        win_rate = (tp_count / total * 100.0) if total > 0 else 0.0
        open_count = len(self.state.get("open_positions", {}))

        all_total = len(all_closed)
        all_tp = sum(1 for t in all_closed if float(t.get("realized_r", 0.0)) > 0)
        all_sl = sum(1 for t in all_closed if float(t.get("realized_r", 0.0)) < 0)
        all_be = sum(1 for t in all_closed if float(t.get("realized_r", 0.0)) == 0)
        all_net_r = sum(float(t.get("realized_r", 0.0)) for t in all_closed)

        return {
            "month": target_month,
            "total_closed": total,
            "net_r": net_r,
            "tp_count": tp_count,
            "sl_count": sl_count,
            "be_count": be_count,
            "win_rate": win_rate,
            "open_count": open_count,
            "is_month_specific": bool(month_closed),
            "all_time_total": all_total,
            "all_time_net_r": all_net_r,
            "all_time_tp": all_tp,
            "all_time_sl": all_sl,
            "all_time_be": all_be,
        }

    def format_scoreboard(self, target_month: str | None = None) -> str:
        """Format monthly and all-time performance scoreboard for Telegram alerts and reports."""
        stats = self.get_scoreboard_stats(target_month)
        if stats["total_closed"] == 0 and stats["all_time_total"] == 0:
            return ""

        sign = "+" if stats["net_r"] >= 0 else ""
        sign_all = "+" if stats["all_time_net_r"] >= 0 else ""
        period_label = stats["month"] if stats.get("is_month_specific") else "Tüm Zamanlar"

        lines = [
            f"📊 [PRAGMA RESMİ PERFORMANS SAYACI — {period_label}]",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "ℹ️ Not: Bu sayaç bildirimi PRAGMA motoruna aittir.",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"💰 Net R         : {sign}{stats['net_r']:.2f}R",
            f"📈 Kazanma Oranı : %{stats['win_rate']:.1f} ({stats['tp_count']}/{stats['total_closed']} işlem)",
            f"🎯 TP (Kâr Al)   : {stats['tp_count']}",
            f"🛑 SL (Zarar Kes): {stats['sl_count']}",
            f"🛡️ BE (Başabaş)  : {stats['be_count']}",
        ]
        if stats["all_time_total"] > stats["total_closed"]:
            lines.append(f"🌐 Genel Toplam  : {sign_all}{stats['all_time_net_r']:.2f}R ({stats['all_time_tp']} TP / {stats['all_time_sl']} SL | Toplam: {stats['all_time_total']})")
        lines.extend([
            f"📂 Açık Pozisyon : {stats['open_count']}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ])
        return "\n".join(lines)

    def process_bar(self, symbol: str, bar_time: str, bar: dict[str, float],
                    signals: list[dict[str, Any]] | None = None,
                    rejected_signals: list[dict[str, Any]] | None = None,
                    save: bool = True) -> list[dict[str, Any]]:
        """Process one closed M1 bar exactly once; stops win ambiguous same-bar ties."""
        symbol = symbol.upper()
        timestamp = pd.Timestamp(bar_time)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        stamp = timestamp.isoformat()
        last = self.state["last_processed"].get(symbol)
        if last and pd.Timestamp(last) >= timestamp:
            return []
        normalized = {key: float(bar[key]) for key in ("open", "high", "low", "close")}
        if not all(pd.notna(value) for value in normalized.values()) or normalized["high"] < normalized["low"]:
            raise ValueError("Invalid OHLC bar supplied to shadow trader")
        events: list[dict[str, Any]] = []
        position = self.state["open_positions"].get(symbol)
        if position and pd.Timestamp(position["entry_time"]) < timestamp:
            events.extend(self._manage_position(symbol, stamp, normalized, position))

        # Log rejected signals for audit and root-cause analysis
        for rej in rejected_signals or []:
            rej_key = "|".join((symbol, str(rej.get("direction")), str(rej.get("poi_type")), str(rej.get("reason")), stamp))
            seen_rej = set(self.state.get("seen_rejections", []))
            if rej_key in seen_rej:
                continue
            seen_rej.add(rej_key)
            self.state["seen_rejections"] = list(seen_rej)[-5000:]
            record_info = {
                "timestamp": stamp,
                "symbol": symbol,
                "direction": str(rej.get("direction", "")),
                "poi_type": str(rej.get("poi_type", "")),
                "regime": str(rej.get("regime", "")),
                "macro_bias": rej.get("macro_bias", ""),
                "reason": str(rej.get("reason", "")),
                "entry_price": float(rej["entry_price"]) if rej.get("entry_price") is not None else "",
                "stop_loss": float(rej["stop_loss"]) if rej.get("stop_loss") is not None else "",
                "take_profit_1": float(rej["take_profit_1"]) if rej.get("take_profit_1") is not None else "",
                "rr_ratio": float(rej["rr_ratio"]) if rej.get("rr_ratio") is not None else "",
                "z_score": float(rej["z_score"]) if rej.get("z_score") is not None else "",
                "volume_multiplier": float(rej["volume_multiplier"]) if rej.get("volume_multiplier") is not None else "",
                "order_flow_delta": float(rej["order_flow_delta"]) if rej.get("order_flow_delta") is not None else "",
                "atr": float(rej["atr"]) if rej.get("atr") is not None else "",
            }
            try:
                record_rejected_signal(self.rejected_path, record_info)
            except Exception as exc:
                print(f"[REJECT JOURNAL ERROR] {exc}", flush=True)

        # Only current, newly closed-bar signals are passed here by the daemon.
        for signal in signals or []:
            if not signal.get("execute"):
                continue
            signal_key = "|".join((symbol, str(signal.get("direction")), str(signal.get("poi_type")), stamp))
            seen = set(self.state.get("seen_signals", []))
            if signal_key in seen or symbol in self.state["open_positions"]:
                continue
            seen.add(signal_key)
            self.state["seen_signals"] = list(seen)[-5000:]
            metrics = signal.get("metrics", {}) if isinstance(signal.get("metrics", {}), dict) else {}
            entry = float(signal.get("effective_entry") or metrics.get("effective_entry") or signal.get("entry_price") or normalized["close"])
            stop = float(signal["stop_loss"])
            tp1 = float(signal["take_profit_1"])
            tp2 = float(signal.get("take_profit_2") or tp1)
            risk_distance = abs(entry - stop)
            if not (risk_distance > 0 and all(pd.notna(x) for x in (entry, stop, tp1, tp2))):
                continue
            direction = str(signal["direction"]).upper()
            if direction not in ("LONG", "SHORT"):
                continue
            if direction == "LONG" and not (stop < entry < tp1 <= tp2):
                continue
            if direction == "SHORT" and not (stop > entry > tp1 >= tp2):
                continue

            planned_rr = float(signal.get("rr_ratio") or 0.0)

            # Asya Seansı Kalkanı: 00:00 - 09:00 TSİ (UTC 21:00 - 06:00) yeni işlem yasağı
            try:
                stamp_dt = pd.to_datetime(stamp)
                tsi_hour = (stamp_dt.hour + 3) % 24
                if 0 <= tsi_hour < 9:
                    record_info = {
                        "timestamp": stamp, "symbol": symbol, "direction": direction,
                        "poi_type": str(signal.get("poi_type", "")), "regime": str(signal.get("regime", "")),
                        "macro_bias": signal.get("macro_bias", ""), "reason": "ASIAN_SESSION_SHIELD_ACTIVE",
                        "entry_price": entry, "stop_loss": stop, "take_profit_1": tp1,
                        "rr_ratio": planned_rr, "z_score": "", "volume_multiplier": "",
                        "order_flow_delta": "", "atr": "",
                    }
                    try:
                        record_rejected_signal(self.rejected_path, record_info)
                    except Exception:
                        pass
                    continue
            except Exception:
                pass

            # Sembol Soğuma Kalkanı: Aynı sembole 3 saat (180 dk) peş peşe giriş yasağı
            sym_key = symbol.upper()
            if sym_key in self._symbol_cooldowns:
                last_cd = self._symbol_cooldowns[sym_key]
                try:
                    cur_dt = pd.to_datetime(stamp)
                    if (cur_dt - last_cd).total_seconds() < 3 * 3600:
                        record_info = {
                            "timestamp": stamp, "symbol": symbol, "direction": direction,
                            "poi_type": str(signal.get("poi_type", "")), "regime": str(signal.get("regime", "")),
                            "macro_bias": signal.get("macro_bias", ""), "reason": "SYMBOL_COOLDOWN_ACTIVE",
                            "entry_price": entry, "stop_loss": stop, "take_profit_1": tp1,
                            "rr_ratio": planned_rr, "z_score": "", "volume_multiplier": "",
                            "order_flow_delta": "", "atr": "",
                        }
                        try:
                            record_rejected_signal(self.rejected_path, record_info)
                        except Exception:
                            pass
                        continue
                except Exception:
                    pass

            # Minimum 1:2 R:R Gate: Trade must offer at least 2.0R to main target
            rr_tp2 = abs(tp2 - entry) / risk_distance if risk_distance > 0 else 0.0
            if max(rr_tp2, planned_rr) < 2.0:
                record_info = {
                    "timestamp": stamp, "symbol": symbol, "direction": direction,
                    "poi_type": str(signal.get("poi_type", "")), "regime": str(signal.get("regime", "")),
                    "macro_bias": signal.get("macro_bias", ""), "reason": "LOW_RR_BELOW_1_TO_2",
                    "entry_price": entry, "stop_loss": stop, "take_profit_1": tp1,
                    "rr_ratio": max(rr_tp2, planned_rr), "z_score": "", "volume_multiplier": "",
                    "order_flow_delta": "", "atr": "",
                }
                try:
                    record_rejected_signal(self.rejected_path, record_info)
                except Exception:
                    pass
                continue

            # Begonya Macro Gate Strict Directional Check
            macro_bias = signal.get("macro_bias")
            if macro_bias is not None:
                try:
                    mb = int(macro_bias)
                    if (mb == 1 and direction != "LONG") or (mb == -1 and direction != "SHORT") or (mb == 0):
                        record_info = {
                            "timestamp": stamp, "symbol": symbol, "direction": direction,
                            "poi_type": str(signal.get("poi_type", "")), "regime": str(signal.get("regime", "")),
                            "macro_bias": mb, "reason": "MACRO_GATE_VETO",
                            "entry_price": entry, "stop_loss": stop, "take_profit_1": tp1,
                            "rr_ratio": max(rr_tp2, planned_rr), "z_score": "", "volume_multiplier": "",
                            "order_flow_delta": "", "atr": "",
                        }
                        try:
                            record_rejected_signal(self.rejected_path, record_info)
                        except Exception:
                            pass
                        continue
                except (ValueError, TypeError):
                    pass

            # 1R'de %50 Kâr Al + Breakeven: TP1 kesinlikle 1.0R seviyesine kilitlenir
            sign = 1.0 if direction == "LONG" else -1.0
            tp1 = entry + sign * 1.0 * risk_distance
            if abs(tp2 - entry) / risk_distance < 2.0:
                tp2 = entry + sign * 2.0 * risk_distance

            self._symbol_cooldowns[sym_key] = pd.to_datetime(stamp)

            risk_cash = float(self.state["balance"]) * self.risk_pct / 100.0
            trade_id = hashlib.sha256(signal_key.encode("utf-8")).hexdigest()[:16]
            position = {
                "trade_id": trade_id, "symbol": symbol, "direction": direction,
                "poi_type": str(signal.get("poi_type", "UNKNOWN")),
                "regime": str(signal.get("regime", "UNKNOWN")),
                "macro_bias": signal.get("macro_bias"),
                "entry_time": stamp, "entry_price": entry, "initial_stop": stop,
                "final_stop": stop, "stop_loss": stop, "take_profit_1": tp1, "take_profit_2": tp2,
                "rr_planned": float(signal.get("rr_ratio") or max(rr_tp2, planned_rr)),
                "risk_distance": risk_distance, "risk_cash": risk_cash,
                "remaining_fraction": 1.0, "tp1_done": False, "tp2_done": False,
                "trailing_active": False,
                "peak_price": entry, "peak_r": 0.0,
                "realized_pnl": 0.0, "last_price": normalized["close"],
                "last_bar_time": stamp,
                "bars_held": 0,
                "mae_price": entry,
                "mfe_price": entry,
                "mae_r": 0.0,
                "mfe_r": 0.0,
                "z_score": float(metrics.get("z_score")) if metrics.get("z_score") is not None else None,
                "volume_multiplier": float(metrics.get("volume_multiplier")) if metrics.get("volume_multiplier") is not None else None,
                "order_flow_delta": float(metrics.get("order_flow_delta") or metrics.get("volume_delta") or 0.0),
                "atr": float(signal.get("atr") or 0.0),
                "vwap": float(signal.get("vwap") or 0.0),
                "pdpoc": float(signal.get("pdpoc") or 0.0),
            }
            self.state["open_positions"][symbol] = position
            event = {
                "type": "OPEN", "trade_id": trade_id, "symbol": symbol,
                "direction": direction, "entry": entry, "sl": stop,
                "tp1": tp1, "tp2": tp2, "risk_cash": risk_cash,
                "balance": float(self.state["balance"]), "time": stamp,
            }
            events.append(event)
            self._notify(
                f"PRAGMA SHADOW — VIRTUAL ENTRY\n{symbol} {direction}\n"
                f"Giriş: {entry:.5f}\nSL: {stop:.5f}\nTP1: {tp1:.5f} | TP2: {tp2:.5f}\n"
                f"Sanal risk: {risk_cash:.2f} ({self.risk_pct:.2f}%)\n"
                f"Bakiye: {self.state['balance']:.2f}\nID: {trade_id}"
            )
        self.state["last_processed"][symbol] = stamp
        if save or events:
            self._save()
        return events

    def _manage_position(self, symbol: str, stamp: str, bar: dict[str, float],
                         position: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        direction = position["direction"]
        stop = float(position["stop_loss"])
        position["bars_held"] = int(position.get("bars_held", 0)) + 1

        # Track Maximum Adverse Excursion (MAE) and Maximum Favorable Excursion (MFE)
        entry = float(position["entry_price"])
        risk_dist = max(1e-9, float(position["risk_distance"]))
        if direction == "LONG":
            position["mae_price"] = min(float(position.get("mae_price", entry)), bar["low"])
            position["mfe_price"] = max(float(position.get("mfe_price", entry)), bar["high"])
            position["mae_r"] = max(0.0, (entry - float(position["mae_price"])) / risk_dist)
            position["mfe_r"] = max(0.0, (float(position["mfe_price"]) - entry) / risk_dist)
        else:
            position["mae_price"] = max(float(position.get("mae_price", entry)), bar["high"])
            position["mfe_price"] = min(float(position.get("mfe_price", entry)), bar["low"])
            position["mae_r"] = max(0.0, (float(position["mae_price"]) - entry) / risk_dist)
            position["mfe_r"] = max(0.0, (entry - float(position["mfe_price"])) / risk_dist)

        # Conservative OHLC convention: if SL and target are both touched, SL wins.
        if self._bar_hits(bar, direction, stop, "sl"):
            if position.get("trailing_active"):
                outcome = "TRAILING_STOP"
            elif position.get("tp1_done") and abs(stop - float(position["entry_price"])) <= 1e-6:
                outcome = "BE"
            else:
                outcome = "SL"
            self._realize(symbol, stamp, position, stop, float(position["remaining_fraction"]), outcome)
            return [{"type": "CLOSE", "symbol": symbol, "outcome": outcome, "time": stamp}]
        tp1, tp2 = float(position["take_profit_1"]), float(position["take_profit_2"])
        distinct = abs(tp2 - tp1) > 1e-12

        # 1. Aşama: TP1 Vurulduğunda (%50 Kâr Al + Breakeven'a Çek)
        if not position.get("tp1_done") and self._bar_hits(bar, direction, tp1, "tp"):
            fraction = 0.50 if distinct else 1.0
            self._realize(symbol, stamp, position, tp1, fraction, "TP1" if distinct else "TP")
            if not distinct:
                return [{"type": "CLOSE", "symbol": symbol, "outcome": "TP", "time": stamp}]
            position["tp1_done"] = True
            position["remaining_fraction"] = 0.50
            position["stop_loss"] = float(position["entry_price"])
            position["final_stop"] = float(position["entry_price"])
            position["last_price"] = bar["close"]
            position["last_bar_time"] = stamp
            self._notify(
                f"PRAGMA SHADOW — TP1 VURULDU\n{symbol} {direction}\nTP1: {tp1:.5f}\n"
                f"Kısmi kâr: %50 alındı ({position['realized_pnl']:+.2f}$)\n"
                f"Kalan: %50 | Stop: Breakeven ({position['stop_loss']:.5f})\n"
                f"Bakiye: {self.state['balance']:.2f}$"
            )
            # Do not assume TP2 was reached later in the same OHLC bar.
            return [{"type": "TP1", "symbol": symbol, "time": stamp}]

        # 2. Aşama: TP2 Vurulduğunda
        if position.get("tp1_done") and not position.get("tp2_done") and self._bar_hits(bar, direction, tp2, "tp"):
            if self.enable_runner:
                fraction = 0.25
                self._realize(symbol, stamp, position, tp2, fraction, "TP2")
                position["tp2_done"] = True
                position["remaining_fraction"] = 0.25
                position["trailing_active"] = True

                # Trailing stop asgari kilidi: TP1 seviyesi (en az +1.0R kilitli kâr)
                sign = 1.0 if direction == "LONG" else -1.0
                tp1_r = abs(tp1 - entry) / risk_dist
                lock_in_r = max(1.0, tp1_r)
                initial_trail_sl = entry + sign * lock_in_r * risk_dist
                position["stop_loss"] = initial_trail_sl
                position["final_stop"] = initial_trail_sl
                position["peak_price"] = tp2
                position["peak_r"] = abs(tp2 - entry) / risk_dist
                position["last_price"] = bar["close"]
                position["last_bar_time"] = stamp
                self._notify(
                    f"PRAGMA SHADOW — TP2 VURULDU\n{symbol} {direction}\nTP2: {tp2:.5f}\n"
                    f"Kısmi kâr: %25 alındı (Toplam %75 kâr: {position['realized_pnl']:+.2f}$)\n"
                    f"Kalan: %25 (RUNNER) | Trailing SL: {position['stop_loss']:.5f} (+{lock_in_r:.2f}R Kilitli)\n"
                    f"Bakiye: {self.state['balance']:.2f}$"
                )
                return [{"type": "TP2", "outcome": "TP2", "symbol": symbol, "time": stamp}]
            else:
                self._realize(symbol, stamp, position, tp2, float(position["remaining_fraction"]), "TP2")
                return [{"type": "CLOSE", "outcome": "TP2", "symbol": symbol, "time": stamp}]

        # 3. Aşama: Runner Aktifken Trailing Stop Güncellemesi
        if position.get("trailing_active"):
            sign = 1.0 if direction == "LONG" else -1.0
            tp1_r = abs(tp1 - entry) / risk_dist
            min_lock_r = max(1.0, tp1_r)
            if direction == "LONG":
                cur_high = bar["high"]
                if cur_high > float(position.get("peak_price", entry)):
                    position["peak_price"] = cur_high
                    peak_r = (cur_high - entry) / risk_dist
                    position["peak_r"] = peak_r
                    lock_r = max(min_lock_r, peak_r - 0.75)
                    new_sl = entry + lock_r * risk_dist
                    if new_sl > float(position["stop_loss"]):
                        position["stop_loss"] = new_sl
                        position["final_stop"] = new_sl
            else:
                cur_low = bar["low"]
                if cur_low < float(position.get("peak_price", entry)):
                    position["peak_price"] = cur_low
                    peak_r = (entry - cur_low) / risk_dist
                    position["peak_r"] = peak_r
                    lock_r = max(min_lock_r, peak_r - 0.75)
                    new_sl = entry - lock_r * risk_dist
                    if new_sl < float(position["stop_loss"]):
                        position["stop_loss"] = new_sl
                        position["final_stop"] = new_sl

        position["last_price"] = bar["close"]
        position["last_bar_time"] = stamp
        return events

    def _realize(self, symbol: str, stamp: str, position: dict[str, Any],
                 exit_price: float, fraction: float, outcome: str) -> None:
        sign = 1.0 if position["direction"] == "LONG" else -1.0
        r_multiple = (float(exit_price) - float(position["entry_price"])) * sign / float(position["risk_distance"])
        pnl = r_multiple * float(position["risk_cash"]) * float(fraction)
        position["realized_pnl"] = float(position.get("realized_pnl", 0.0)) + pnl
        self.state["balance"] = float(self.state["balance"]) + pnl
        self._update_drawdown()
        remaining = float(position["remaining_fraction"]) - fraction
        if remaining <= 1e-9:
            trade = dict(position)
            trade.update({
                "final_stop": float(position.get("final_stop", position["stop_loss"])),
                "exit_time": stamp, "exit_price": float(exit_price), "outcome": outcome,
                "net_pnl": float(position["realized_pnl"]),
                "realized_r": float(position["realized_pnl"]) / float(position["risk_cash"]),
                "balance_after": float(self.state["balance"]),
                "bars_held": int(position.get("bars_held", 0)),
                "mae_r": float(position.get("mae_r", 0.0)),
                "mfe_r": float(position.get("mfe_r", 0.0)),
            })
            self.state["closed_trades"].append(trade)
            self.state["closed_trades"] = self.state["closed_trades"][-5000:]
            self.state["open_positions"].pop(symbol, None)
            try:
                record_trade_to_journal(self.journal_path, trade)
            except Exception as exc:
                print(f"[JOURNAL ERROR] {exc}", flush=True)
            scoreboard = self.format_scoreboard()
            close_msg = (
                f"PRAGMA SHADOW — {outcome}\n{symbol} {position['direction']}\n"
                f"Çıkış: {float(exit_price):.5f}\nİşlem neti: {trade['net_pnl']:+.2f} "
                f"({trade['realized_r']:+.2f}R)\nBakiye: {self.state['balance']:.2f}\n"
                f"Max DD: {self.state['max_drawdown']:.2f}\nID: {position['trade_id']}"
            )
            if scoreboard:
                close_msg += f"\n\n{scoreboard}"
            self._notify(close_msg)
        else:
            position["remaining_fraction"] = remaining


def _append_measurement_observer(path: Path, payload: dict[str, Any]) -> bool:
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:
        print(f"[MEASUREMENT OBSERVER ERROR] {exc}", flush=True)
        return False


def _extract_signals(report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract executed and rejected signals enriched with regime and AMT context."""
    executed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    regime = report.get("regime", "UNKNOWN")
    atr = report.get("atr_14_m15")
    macro_bias = report.get("macro", {}).get("bias")
    vwap = report.get("vwap", {}).get("vwap")
    pdpoc = report.get("previous_session", {}).get("pdPOC")

    for item in report.get("triggers", []):
        entry = dict(item)
        entry["regime"] = regime
        entry["atr"] = atr
        entry["macro_bias"] = macro_bias
        entry["vwap"] = vwap
        entry["pdpoc"] = pdpoc
        metrics = item.get("metrics") or {}
        if isinstance(metrics, dict):
            entry["z_score"] = metrics.get("z_score")
            entry["volume_multiplier"] = metrics.get("volume_multiplier")
            entry["order_flow_delta"] = metrics.get("volume_delta") or metrics.get("order_flow_delta")
        if item.get("execute") is True:
            executed.append(entry)
        else:
            rejected.append(entry)
    return executed, rejected


def _decision_signals(report: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_signals(report)[0]


def run_daemon(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser()
    journal_path = Path(args.journal_path).expanduser() if getattr(args, "journal_path", None) else state_dir / "trade_journal.csv"
    rejected_path = Path(args.rejected_path).expanduser() if getattr(args, "rejected_path", None) else state_dir / "rejected_signals.csv"

    book = PaperTradingBook(
        state_dir / "state.json", initial_balance=args.initial_balance,
        risk_pct=args.risk_pct, notifier=ExecutionNotifier(),
        journal_path=journal_path, rejected_path=rejected_path,
    )
    notifier = book.notifier
    notifier_message = getattr(book, "_notify")
    scoreboard = book.format_scoreboard()
    start_msg = (
        "PRAGMA SHADOW TRADER STARTED\n"
        "ℹ️ Not: Bu sayaç bildirimi PRAGMA motoruna aittir.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Mod: yalnızca sanal işlem | MT5: yalnızca fiyat verisi\n"
        f"Bakiye: {book.state['balance']:.2f} | İşlem riski: {book.risk_pct:.2f}%\n"
        f"State: {state_dir}\n"
        f"Journal: {journal_path.name}"
    )
    if scoreboard:
        start_msg += f"\n\n{scoreboard}"
    notifier_message(start_msg)
    last_heartbeat = time.monotonic()
    last_state_touch = 0.0
    last_errors: dict[str, str] = {}
    consecutive_errors: dict[str, int] = {}
    mt5_client = MT5DataClient()
    try:
        while True:
            try:
                active_symbols = _active_begonya_mt5_symbols(client=mt5_client)
                active_names = {symbol.upper() for symbol, _bias in active_symbols}
                # Existing virtual positions must keep being managed if a macro gate turns neutral.
                for open_symbol in list(book.state["open_positions"]):
                    if open_symbol.upper() not in active_names:
                        active_symbols.append((open_symbol, 0))
                active_symbols = sorted(
                    {symbol.upper(): (symbol, bias) for symbol, bias in active_symbols}.values()
                )
                if not active_symbols:
                    print("[SHADOW] Aktif Begonya sembolü bulunamadı; yeniden denenecek.", flush=True)
                for symbol, _bias in active_symbols:
                    try:
                        raw = mt5_client.rates(symbol, "M1", args.bars)
                        closed = filter_closed_bars(raw, "M1", now=pd.Timestamp.now(tz="UTC"))
                        if closed.empty:
                            continue
                        last_seen = book.state["last_processed"].get(symbol.upper())
                        pending = closed if not last_seen else closed.loc[closed.index > pd.Timestamp(last_seen)]
                        if pending.empty:
                            continue
                        executed_signals: list[dict[str, Any]] = []
                        rejected_signals: list[dict[str, Any]] = []
                        latest_signal_time = pd.Timestamp(closed.index[-1])
                        if _bias != 0:
                            report = run_pipeline(
                                symbol=symbol, bars_count=args.bars, dry_run=False,
                                notifier=ConsoleOnlyNotifier(), notify_pois=False,
                                trigger_tf=args.trigger_tf,
                                cost_price=args.spread_points * args.point_size if args.point_size else 0.0,
                            )
                            latest_signal_time = pd.Timestamp(report["bars"]["last_closed_m1_time"])
                            executed_signals, rejected_signals = _extract_signals(report)
                        pending_items = list(pending.iterrows())
                        for idx, (bar_time, row) in enumerate(pending_items):
                            stamp = pd.Timestamp(bar_time).isoformat()
                            bar = {key: float(row[key]) for key in ("open", "high", "low", "close")}
                            cur_exec = executed_signals if pd.Timestamp(bar_time) == latest_signal_time else []
                            cur_rej = rejected_signals if pd.Timestamp(bar_time) == latest_signal_time else []
                            is_last = (idx == len(pending_items) - 1)
                            events = book.process_bar(symbol, stamp, bar, cur_exec, cur_rej, save=is_last)
                            if events:
                                print(f"[SHADOW] {symbol} {stamp}: {events}", flush=True)
                        last_errors.pop(symbol, None)
                        consecutive_errors.pop(symbol, None)
                    except Exception as exc:
                        message = f"{type(exc).__name__}: {exc}"
                        now_mono = time.monotonic()
                        err_key = f"{type(exc).__name__}:{message}"
                        last_sent = last_errors.get(err_key, 0.0)
                        consecutive_errors[symbol] = consecutive_errors.get(symbol, 0) + 1
                        # Only alert if an error persists for >= 5 consecutive cycles (>= 50s) AND at least 30m since last alert
                        should_alert = (consecutive_errors[symbol] >= 5) and (
                            not (isinstance(last_sent, (int, float)) and (now_mono - float(last_sent) < 1800.0))
                        )
                        if should_alert and last_errors.get(symbol) != message:
                            notifier_message(f"PRAGMA SHADOW — DATA/PIPELINE ERROR\n{symbol}\n{message}")
                            last_errors[err_key] = now_mono
                        last_errors[symbol] = message
                        print(f"[SHADOW ERROR] {symbol}: {message}", flush=True)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                if last_errors.get("__cycle__") != message:
                    notifier_message(f"PRAGMA SHADOW — SCAN ERROR\n{message}")
                    last_errors["__cycle__"] = message
                print(f"[SHADOW SCAN ERROR] {message}", flush=True)

            if args.heartbeat_minutes > 0 and (time.monotonic() - last_heartbeat >= args.heartbeat_minutes * 60):
                open_count = len(book.state["open_positions"])
                closed_count = len(book.state["closed_trades"])
                net = float(book.state["balance"]) - float(book.state["initial_balance"])
                sb = book.format_scoreboard()
                hb_lines = [
                    "PRAGMA SHADOW — PERİYODİK SAYAÇ VE DURUM BİLDİRİMİ",
                    "ℹ️ Not: Bu sayaç bildirimi PRAGMA motoruna aittir.",
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    f"Bakiye: {book.state['balance']:.2f} | Net PnL: {net:+.2f}$",
                    f"Kapanan işlem: {closed_count} | Açık pozisyon: {open_count}",
                    f"Max DD: {book.state['max_drawdown']:.2f}$",
                ]
                if sb:
                    hb_lines.extend(["", sb])
                notifier_message("\n".join(hb_lines))
                last_heartbeat = time.monotonic()
            if time.monotonic() - last_state_touch >= 60.0:
                book.touch()
                last_state_touch = time.monotonic()
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        notifier_message("PRAGMA SHADOW TRADER STOPPED BY USER")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pragma broker-free shadow/paper trading daemon")
    parser.add_argument("--bars", type=int, default=3000)
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--initial-balance", type=float, default=10_000.0)
    parser.add_argument("--risk-pct", type=float, default=1.0)
    parser.add_argument("--heartbeat-minutes", type=int, default=0,
                        help="Minutes between heartbeat telegram alerts; 0 disables (default: 0)")
    parser.add_argument("--trigger-tf", choices=("M1", "M5", "M15", "M30", "H1", "M60"), default=None)
    parser.add_argument("--spread-points", type=float, default=0.0)
    parser.add_argument("--point-size", type=float, default=None)
    parser.add_argument("--state-dir", default=str(default_state_dir()))
    parser.add_argument("--journal-path", default=None, help="Explicit path to trade_journal.csv")
    parser.add_argument("--rejected-path", default=None, help="Explicit path to rejected_signals.csv")
    args = parser.parse_args(argv)
    if args.poll_seconds < 1:
        parser.error("--poll-seconds must be >= 1")
    if args.heartbeat_minutes < 0:
        parser.error("--heartbeat-minutes must be >= 0")
    if args.bars < 100:
        parser.error("--bars must be >= 100")
    if args.spread_points < 0 or (args.point_size is not None and args.point_size <= 0):
        parser.error("spread-points must be >= 0 and point-size must be > 0")
    return run_daemon(args)


if __name__ == "__main__":
    raise SystemExit(main())
