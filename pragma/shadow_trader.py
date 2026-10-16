"""Broker-free shadow/paper trading for Pragma signals.

Reads prices from the local MT5 terminal but never submits, modifies, or closes broker orders.
All positions, realized PnL, and processing cursors are persisted locally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from pragma.data.mt5_data import MT5DataClient, filter_closed_bars
from pragma.execution_notifier import ExecutionNotifier
from pragma.run_pipeline import _active_begonya_mt5_symbols, run_pipeline


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
                 risk_pct: float = 1.0, notifier: Any | None = None):
        if initial_balance <= 0:
            raise ValueError("initial_balance must be positive")
        if not 0 < risk_pct <= 5:
            raise ValueError("risk_pct must be > 0 and <= 5")
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.risk_pct = float(risk_pct)
        self.notifier = notifier or ExecutionNotifier()
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

    def _save(self) -> None:
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.path)

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

    def _update_drawdown(self) -> None:
        balance = float(self.state["balance"])
        self.state["peak_balance"] = max(float(self.state["peak_balance"]), balance)
        drawdown = float(self.state["peak_balance"]) - balance
        self.state["max_drawdown"] = max(float(self.state.get("max_drawdown", 0.0)), drawdown)

    def process_bar(self, symbol: str, bar_time: str, bar: dict[str, float],
                    signals: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
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
            risk_cash = float(self.state["balance"]) * self.risk_pct / 100.0
            trade_id = hashlib.sha256(signal_key.encode("utf-8")).hexdigest()[:16]
            position = {
                "trade_id": trade_id, "symbol": symbol, "direction": direction,
                "poi_type": str(signal.get("poi_type", "UNKNOWN")),
                "entry_time": stamp, "entry_price": entry, "initial_stop": stop,
                "stop_loss": stop, "take_profit_1": tp1, "take_profit_2": tp2,
                "risk_distance": risk_distance, "risk_cash": risk_cash,
                "remaining_fraction": 1.0, "tp1_done": False,
                "realized_pnl": 0.0, "last_price": normalized["close"],
                "last_bar_time": stamp,
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
        self._save()
        return events

    def _manage_position(self, symbol: str, stamp: str, bar: dict[str, float],
                         position: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        direction = position["direction"]
        stop = float(position["stop_loss"])
        # Conservative OHLC convention: if SL and target are both touched, SL wins.
        if self._bar_hits(bar, direction, stop, "sl"):
            outcome = "BE" if position.get("tp1_done") and abs(stop - float(position["entry_price"])) <= 1e-12 else "SL"
            self._realize(symbol, stamp, position, stop, float(position["remaining_fraction"]), outcome)
            return [{"type": "CLOSE", "symbol": symbol, "outcome": outcome, "time": stamp}]
        tp1, tp2 = float(position["take_profit_1"]), float(position["take_profit_2"])
        distinct = abs(tp2 - tp1) > 1e-12
        if not position["tp1_done"] and self._bar_hits(bar, direction, tp1, "tp"):
            fraction = 0.5 if distinct else 1.0
            self._realize(symbol, stamp, position, tp1, fraction, "TP1" if distinct else "TP")
            if not distinct:
                return [{"type": "CLOSE", "symbol": symbol, "outcome": "TP", "time": stamp}]
            position["tp1_done"] = True
            position["remaining_fraction"] = 0.5
            position["stop_loss"] = float(position["entry_price"])
            position["last_price"] = bar["close"]
            position["last_bar_time"] = stamp
            self._notify(
                f"PRAGMA SHADOW — TP1\n{symbol} {direction}\nTP1: {tp1:.5f}\n"
                f"Kısmi gerçekleşen PnL: {position['realized_pnl']:+.2f}\n"
                f"Kalan pozisyon: %50 | Yeni SL: {position['stop_loss']:.5f}\n"
                f"Bakiye: {self.state['balance']:.2f}"
            )
            # Do not assume TP2 was reached later in the same OHLC bar.
            return [{"type": "TP1", "symbol": symbol, "time": stamp}]
        if position["tp1_done"] and self._bar_hits(bar, direction, tp2, "tp"):
            self._realize(symbol, stamp, position, tp2, float(position["remaining_fraction"]), "TP2")
            return [{"type": "CLOSE", "symbol": symbol, "outcome": "TP2", "time": stamp}]
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
                "exit_time": stamp, "exit_price": float(exit_price), "outcome": outcome,
                "net_pnl": float(position["realized_pnl"]),
                "realized_r": float(position["realized_pnl"]) / float(position["risk_cash"]),
                "balance_after": float(self.state["balance"]),
            })
            self.state["closed_trades"].append(trade)
            self.state["closed_trades"] = self.state["closed_trades"][-5000:]
            self.state["open_positions"].pop(symbol, None)
            self._notify(
                f"PRAGMA SHADOW — {outcome}\n{symbol} {position['direction']}\n"
                f"Çıkış: {float(exit_price):.5f}\nİşlem neti: {trade['net_pnl']:+.2f} "
                f"({trade['realized_r']:+.2f}R)\nBakiye: {self.state['balance']:.2f}\n"
                f"Max DD: {self.state['max_drawdown']:.2f}\nID: {position['trade_id']}"
            )
        else:
            position["remaining_fraction"] = remaining


def _decision_signals(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in report.get("triggers", []) if item.get("execute") is True]


def run_daemon(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser()
    book = PaperTradingBook(
        state_dir / "state.json", initial_balance=args.initial_balance,
        risk_pct=args.risk_pct, notifier=ExecutionNotifier(),
    )
    notifier = book.notifier
    notifier_message = getattr(book, "_notify")
    notifier_message(
        "PRAGMA SHADOW TRADER STARTED\n"
        f"Mod: yalnızca sanal işlem | MT5: yalnızca fiyat verisi\n"
        f"Bakiye: {book.state['balance']:.2f} | İşlem riski: {book.risk_pct:.2f}%\n"
        f"State: {state_dir}"
    )
    last_heartbeat = time.monotonic()
    last_errors: dict[str, str] = {}
    try:
        while True:
            try:
                active_symbols = _active_begonya_mt5_symbols()
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
                        with MT5DataClient() as client:
                            raw = client.rates(symbol, "M1", args.bars)
                        closed = filter_closed_bars(raw, "M1", now=pd.Timestamp.now(tz="UTC"))
                        if closed.empty:
                            continue
                        last_seen = book.state["last_processed"].get(symbol.upper())
                        pending = closed if not last_seen else closed.loc[closed.index > pd.Timestamp(last_seen)]
                        if pending.empty:
                            continue
                        signals: list[dict[str, Any]] = []
                        latest_signal_time = pd.Timestamp(closed.index[-1])
                        if _bias != 0:
                            report = run_pipeline(
                                symbol=symbol, bars_count=args.bars, dry_run=False,
                                notifier=ConsoleOnlyNotifier(), notify_pois=False,
                                trigger_tf=args.trigger_tf,
                                cost_price=args.spread_points * args.point_size if args.point_size else 0.0,
                            )
                            latest_signal_time = pd.Timestamp(report["bars"]["last_closed_m1_time"])
                            signals = _decision_signals(report)
                        for bar_time, row in pending.iterrows():
                            stamp = pd.Timestamp(bar_time).isoformat()
                            bar = {key: float(row[key]) for key in ("open", "high", "low", "close")}
                            current_signals = signals if pd.Timestamp(bar_time) == latest_signal_time else []
                            events = book.process_bar(symbol, stamp, bar, current_signals)
                            if events:
                                print(f"[SHADOW] {symbol} {stamp}: {events}", flush=True)
                        last_errors.pop(symbol, None)
                    except Exception as exc:
                        message = f"{type(exc).__name__}: {exc}"
                        if last_errors.get(symbol) != message:
                            notifier_message(f"PRAGMA SHADOW — DATA/PIPELINE ERROR\n{symbol}\n{message}")
                            last_errors[symbol] = message
                        print(f"[SHADOW ERROR] {symbol}: {message}", flush=True)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                if last_errors.get("__cycle__") != message:
                    notifier_message(f"PRAGMA SHADOW — SCAN ERROR\n{message}")
                    last_errors["__cycle__"] = message
                print(f"[SHADOW SCAN ERROR] {message}", flush=True)

            if time.monotonic() - last_heartbeat >= args.heartbeat_minutes * 60:
                open_count = len(book.state["open_positions"])
                closed_count = len(book.state["closed_trades"])
                net = float(book.state["balance"]) - float(book.state["initial_balance"])
                notifier_message(
                    "PRAGMA SHADOW — HEARTBEAT\n"
                    f"Bakiye: {book.state['balance']:.2f}\nNet: {net:+.2f}\n"
                    f"Kapanan işlem: {closed_count} | Açık pozisyon: {open_count}\n"
                    f"Max DD: {book.state['max_drawdown']:.2f}"
                )
                last_heartbeat = time.monotonic()
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
    parser.add_argument("--heartbeat-minutes", type=int, default=60)
    parser.add_argument("--trigger-tf", choices=("M1", "M5", "M15", "M30", "H1", "M60"), default=None)
    parser.add_argument("--spread-points", type=float, default=0.0)
    parser.add_argument("--point-size", type=float, default=None)
    parser.add_argument("--state-dir", default=str(default_state_dir()))
    args = parser.parse_args(argv)
    if args.poll_seconds < 1:
        parser.error("--poll-seconds must be >= 1")
    if args.heartbeat_minutes < 1:
        parser.error("--heartbeat-minutes must be >= 1")
    if args.bars < 100:
        parser.error("--bars must be >= 100")
    if args.spread_points < 0 or (args.point_size is not None and args.point_size <= 0):
        parser.error("spread-points must be >= 0 and point-size must be > 0")
    return run_daemon(args)


if __name__ == "__main__":
    raise SystemExit(main())
