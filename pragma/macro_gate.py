"""Read Begonya's published, per-symbol macro execution gates.

The adapter reads the shared JSON artifact; it does not duplicate Begonya's
macro calculations. Configure BEGONYA_MACRO_GATE_PATH to override the default.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any


class Bias(IntEnum):
    SHORT = -1
    NEUTRAL = 0
    LONG = 1


_GATE_TO_BIAS = {
    "LONG_ONLY": Bias.LONG,
    "SHORT_ONLY": Bias.SHORT,
    "NEUTRAL_RANGE": Bias.NEUTRAL,
}


@dataclass(frozen=True)
class MacroDecision:
    bias: Bias
    source: str = "begonya"
    reason: str = ""
    gate: str = "NEUTRAL_RANGE"
    timestamp: str | None = None


def default_gate_path() -> Path:
    configured = os.environ.get("BEGONYA_MACRO_GATE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return (
        Path.home()
        / ".gemini"
        / "antigravity"
        / "scratch"
        / "Begonya"
        / "shared"
        / "macro_bias_gate.json"
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class MacroGate:
    """Resolve Begonya's execution gate for the requested MT5 symbol.

    Missing, malformed, stale, or unsupported gates fail closed to NEUTRAL.
    The JSON's execution_bias_gates is preferred; deterministic gates are the
    fallback for older/newer Begonya output schemas.
    """

    def __init__(self, path: str | Path | None = None,
                 max_age_hours: float | None = None):
        self.path = Path(path).expanduser() if path else default_gate_path()
        if max_age_hours is None:
            try:
                max_age_hours = float(os.environ.get("BEGONYA_MACRO_MAX_AGE_HOURS", "36"))
            except ValueError:
                max_age_hours = 36.0
        if max_age_hours <= 0:
            raise ValueError("max_age_hours must be positive")
        self.max_age_hours = max_age_hours

    @staticmethod
    def _symbol_gate(gates: dict[str, Any], symbol: str) -> tuple[str | None, str | None]:
        requested = "".join(ch for ch in symbol.upper() if ch.isalnum())
        # Exact match first, then support common broker suffixes such as EURUSD.a
        if symbol.upper() in gates:
            return str(gates[symbol.upper()]).upper(), symbol.upper()
        if requested in gates:
            return str(gates[requested]).upper(), requested
        candidates = [
            (key, value) for key, value in gates.items()
            if requested.startswith("".join(ch for ch in str(key).upper() if ch.isalnum()))
        ]
        if len(candidates) == 1:
            key, value = candidates[0]
            return str(value).upper(), str(key)
        return None, None

    def get_bias(self, symbol: str = "XAUUSD") -> MacroDecision:
        now = datetime.now(timezone.utc)
        if not self.path.is_file():
            return MacroDecision(
                Bias.NEUTRAL, "begonya_missing",
                f"Begonya gate file not found: {self.path}",
            )
        try:
            with self.path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            return MacroDecision(
                Bias.NEUTRAL, "begonya_error",
                f"Could not read Begonya gate file: {exc}",
            )
        if not isinstance(payload, dict):
            return MacroDecision(Bias.NEUTRAL, "begonya_invalid", "Gate root must be a JSON object")

        timestamp = _parse_timestamp(payload.get("timestamp"))
        if timestamp is None:
            return MacroDecision(
                Bias.NEUTRAL, "begonya_invalid",
                "Begonya gate has no valid timestamp",
            )
        age_hours = (now - timestamp).total_seconds() / 3600.0
        if age_hours < -1.0:
            return MacroDecision(
                Bias.NEUTRAL, "begonya_invalid",
                "Begonya gate timestamp is in the future",
                timestamp=timestamp.isoformat(),
            )
        if age_hours > self.max_age_hours:
            return MacroDecision(
                Bias.NEUTRAL, "begonya_stale",
                f"Begonya gate is stale ({age_hours:.1f}h; limit {self.max_age_hours:.1f}h)",
                timestamp=timestamp.isoformat(),
            )

        gates = payload.get("execution_bias_gates")
        if not isinstance(gates, dict):
            gates = payload.get("deterministic_execution_bias_gates")
        if not isinstance(gates, dict):
            gates = payload.get("deterministic_base_gates")
        if not isinstance(gates, dict):
            return MacroDecision(
                Bias.NEUTRAL, "begonya_invalid",
                "No supported execution gate mapping found",
                timestamp=timestamp.isoformat(),
            )

        gate, matched_symbol = self._symbol_gate(gates, symbol)
        if gate not in _GATE_TO_BIAS:
            return MacroDecision(
                Bias.NEUTRAL, "begonya_unmapped",
                f"No supported Begonya gate for symbol {symbol}",
                gate="UNMAPPED",
                timestamp=timestamp.isoformat(),
            )
        return MacroDecision(
            bias=_GATE_TO_BIAS[gate],
            source="begonya",
            reason=f"{matched_symbol} gate={gate}",
            gate=gate,
            timestamp=timestamp.isoformat(),
        )
