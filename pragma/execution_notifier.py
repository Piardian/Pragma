"""Free Telegram and console notifications with per-bar signal deduplication."""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("pragma.execution_notifier")


class SignalDeduplicator:
    """In-memory one-shot key: symbol + POI type + closed M1 bar timestamp."""

    def __init__(self):
        self._seen: set[tuple[str, str, str]] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _key(symbol: str, poi_type: str, bar_time: Any) -> tuple[str, str, str]:
        timestamp = bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time)
        return symbol.upper(), poi_type, timestamp

    def already_seen(self, symbol: str, poi_type: str, bar_time: Any) -> bool:
        with self._lock:
            return self._key(symbol, poi_type, bar_time) in self._seen

    def mark(self, symbol: str, poi_type: str, bar_time: Any) -> None:
        with self._lock:
            self._seen.add(self._key(symbol, poi_type, bar_time))

    def claim(self, symbol: str, poi_type: str, bar_time: Any) -> bool:
        """Atomically reserve a signal key; True only for the first claimant."""
        key = self._key(symbol, poi_type, bar_time)
        with self._lock:
            if key in self._seen:
                return False
            self._seen.add(key)
            return True


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def format_signal_message(symbol: str, poi: Any, decision: Any,
                          regime: Any, bar_time: Any) -> str:
    """Format a deterministic, compact execution candidate report."""
    regime_text = getattr(regime, "value", regime)
    metrics = _value(decision, "metrics", {}) or {}
    low = _value(poi, "poi_low", float("nan"))
    high = _value(poi, "poi_high", float("nan"))
    direction = _value(decision, "direction", _value(poi, "direction", "UNKNOWN"))
    poi_type = _value(poi, "poi_type", "UNKNOWN")
    tp1 = _value(decision, "take_profit_1", _value(decision, "take_profit"))
    tp2 = _value(decision, "take_profit_2", tp1)
    rr = _value(decision, "rr_ratio")
    z = metrics.get("z_score")
    volume_mult = metrics.get("volume_multiplier")
    time_text = bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time)
    def fmt(value):
        return "N/A" if value is None else f"{float(value):.5f}"
    return "\n".join([
        f"PRAGMA EXECUTE — {symbol}",
        f"Yön: {direction} | Rejim: {regime_text}",
        f"POI: {poi_type} [{fmt(low)}, {fmt(high)}]",
        f"Giriş: {fmt(_value(decision, 'entry_price'))}",
        f"SL: {fmt(_value(decision, 'stop_loss'))}",
        f"TP1: {fmt(tp1)} | TP2: {fmt(tp2)}",
        f"R:R (TP1): {fmt(rr)}",
        f"Z-Score: {fmt(z)} | Hacim çarpanı: {fmt(volume_mult)}x",
        f"M1 kapanış: {time_text}",
    ])


class ExecutionNotifier:
    def __init__(self, bot_token: str | None = None, chat_id: str | None = None,
                 deduplicator: SignalDeduplicator | None = None,
                 timeout: float = 8.0):
        self.bot_token = TELEGRAM_BOT_TOKEN if bot_token is None else bot_token
        self.chat_id = TELEGRAM_CHAT_ID if chat_id is None else chat_id
        self.deduplicator = deduplicator or SignalDeduplicator()
        self.timeout = timeout

    def notify(self, symbol: str, poi: Any, decision: Any,
               regime: Any, bar_time: Any) -> dict[str, Any]:
        if not _value(decision, "execute", False):
            return {"sent": False, "reason": "NOT_EXECUTE"}
        poi_type = _value(poi, "poi_type", "UNKNOWN")
        if not self.deduplicator.claim(symbol, poi_type, bar_time):
            return {"sent": False, "reason": "DUPLICATE"}

        message = format_signal_message(symbol, poi, decision, regime, bar_time)
        if not self.bot_token or not self.chat_id:
            logger.info("%s", message)
            print(message)
            return {"sent": True, "channel": "console", "reason": "TELEGRAM_NOT_CONFIGURED"}

        endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = urlencode({"chat_id": self.chat_id, "text": message}).encode("utf-8")
        request = Request(endpoint, data=payload, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Pragma/1.0",
        }, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
                if response.status < 200 or response.status >= 300 or not body.get("ok", False):
                    logger.error("Telegram API rejected signal: %s", body)
                    return {"sent": False, "reason": "TELEGRAM_REJECTED", "response": body}
            logger.info("Telegram signal delivered: %s %s %s", symbol, poi_type, bar_time)
            return {"sent": True, "channel": "telegram", "reason": "SENT"}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            logger.exception("Telegram notification failed")
            return {"sent": False, "reason": "TELEGRAM_ERROR", "error": str(exc)}
