"""Resolve and validate Begonya's published macro execution gates.

The adapter consumes Begonya's JSON artifact; it does not duplicate the
macro engine. PRAGMA_MACRO_GATE_PATH can prioritize a configured location,
while an explicit MacroGate(path=...) pins a specific file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Bias(IntEnum):
    SHORT = -1
    NEUTRAL = 0
    LONG = 1


_BLOCKING_GATES = {"EVENT_FREEZE", "SYSTEMIC_STRESS", "FREEZE", "BLOCKED"}
_GATE_TO_BIAS = {
    "LONG_ONLY": Bias.LONG, "LONG": Bias.LONG, "BULLISH": Bias.LONG,
    "+1": Bias.LONG, "1": Bias.LONG,
    "SHORT_ONLY": Bias.SHORT, "SHORT": Bias.SHORT, "BEARISH": Bias.SHORT,
    "-1": Bias.SHORT,
    "NEUTRAL_RANGE": Bias.NEUTRAL, "NEUTRAL": Bias.NEUTRAL, "FREEZE": Bias.NEUTRAL,
    "BLOCKED": Bias.NEUTRAL, "EVENT_FREEZE": Bias.NEUTRAL,
    "SYSTEMIC_STRESS": Bias.NEUTRAL, "0": Bias.NEUTRAL,
}
_MAPPING_KEYS = (
    "execution_bias_gates", "deterministic_execution_bias_gates",
    "deterministic_base_gates", "symbols", "gates", "assets",
    "decisions", "instruments", "symbol_gates",
)
_TIMESTAMP_KEYS = ("timestamp", "generated_at", "updated_at", "as_of")


@dataclass(frozen=True)
class MacroDecision:
    bias: Bias
    source: str = "begonya"
    reason: str = ""
    gate: str = "UNMAPPED"
    timestamp: str | None = None


@dataclass(frozen=True)
class GateFileInfo:
    path: Path
    timestamp: datetime | None
    age_hours: float | None
    mtime: float
    valid_timestamp: bool


def _local_timezone():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse ISO timestamps; naive values are producer-local, never implicitly UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        zone_name = os.environ.get("BEGONYA_MACRO_TIMEZONE", "").strip()
        try:
            producer_timezone = ZoneInfo(zone_name) if zone_name else _local_timezone()
        except (ZoneInfoNotFoundError, ValueError):
            producer_timezone = _local_timezone()
        parsed = parsed.replace(tzinfo=producer_timezone)
    return parsed.astimezone(timezone.utc)


def _payload_timestamp(payload: dict[str, Any]) -> datetime | None:
    for key in _TIMESTAMP_KEYS:
        value = payload.get(key)
        parsed = _parse_timestamp(value)
        if parsed is not None:
            return parsed
    return None


def _age_hours(timestamp: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    age = (now.astimezone(timezone.utc) - timestamp).total_seconds() / 3600.0
    # A producer-local naive stamp can look up to UTC+3 hours ahead on a UTC
    # host. Accept small clock skew (up to four hours) as fresh, never negative age.
    if age < 0 and abs(age) <= 4.0:
        return 0.0
    return age


def _future_invalid(timestamp: datetime, now: datetime | None = None) -> bool:
    return _age_hours(timestamp, now) < -4.0


def _normalize_symbol(symbol: str) -> str:
    value = str(symbol).strip().upper()
    value = re.sub(r"\.(A|M|PRO)$", "", value)
    value = value.replace("/", "").replace("_", "").replace("-", "").replace("=", "")
    if value == "GCF":
        return "XAUUSD"
    if value == "GOLD":
        return "XAUUSD"
    if value.endswith("USDT") and len(value) > 4:
        value = value[:-4] + "USD"
    aliases = {
        "XAU": "XAUUSD", "GOLD": "XAUUSD", "GCF": "XAUUSD",
        "BTC": "BTCUSD", "BTCUSD": "BTCUSD", "BTCUSDT": "BTCUSD",
        "EUR": "EURUSD", "EURUSD": "EURUSD",
        "XAUUSD": "XAUUSD",
    }
    return aliases.get(value, value)


def _gate_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("gate", "decision", "bias", "execution_gate", "regime_state",
                    "execution_bias", "direction", "state"):
            if key in value:
                found = _gate_value(value[key])
                if found is not None:
                    return found
        return None
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().upper().replace(" ", "_")
    if text in _GATE_TO_BIAS or text in _BLOCKING_GATES:
        return text
    return None


def _mapping_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    # Preferred execution maps first, followed by schema variants.
    for key in _MAPPING_KEYS:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    # Some versions publish symbol keys directly at the JSON root.
    metadata = set(_TIMESTAMP_KEYS) | {
        "execution_gate", "regime_state", "gate_reason", "reason",
        "event_freeze", "systemic_stress", "metadata", "version",
    }
    direct = {key: value for key, value in payload.items() if key not in metadata}
    return direct or None


def _is_active(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, dict):
        if "active" in value:
            return _is_active(value["active"])
        if "enabled" in value:
            return _is_active(value["enabled"])
        return any(_is_active(v) for v in value.values())
    if isinstance(value, str):
        return value.strip().upper() in {
            "TRUE", "YES", "ON", "ACTIVE", "EVENT_FREEZE", "SYSTEMIC_STRESS",
            "FREEZE", "BLOCKED",
        }
    return False


def _block_reason(payload: dict[str, Any], symbol_entry: Any = None) -> str | None:
    """Apply deterministic blocker precedence: EVENT_FREEZE, then SYSTEMIC_STRESS."""
    sources = [("payload", payload)]
    if isinstance(symbol_entry, str) and symbol_entry.strip().upper() in _BLOCKING_GATES:
        return f"{symbol_entry.strip().upper()} active (symbol)"
    if isinstance(symbol_entry, dict):
        sources.append(("symbol", symbol_entry))
    for wanted in ("EVENT_FREEZE", "SYSTEMIC_STRESS"):
        for source_name, source in sources:
            for key, value in source.items():
                normalized_key = str(key).upper()
                normalized_value = _gate_value(value)
                matches = normalized_key == wanted and _is_active(value)
                matches = matches or normalized_key in {"EXECUTION_GATE", "REGIME_STATE"} and normalized_value == wanted
                matches = matches or normalized_key == "GATE" and normalized_value == wanted
                if matches:
                    reason = source.get("gate_reason", source.get("reason", ""))
                    detail = f": {reason}" if reason else ""
                    return f"{wanted} active ({source_name}){detail}"
    # A direct global gate can be nested in execution_gate/regime_state objects.
    for source_name, source in sources:
        for key in ("execution_gate", "regime_state", "gate", "decision"):
            value = source.get(key)
            candidate = _gate_value(value)
            if candidate in _BLOCKING_GATES:
                reason = source.get("gate_reason", source.get("reason", ""))
                detail = f": {reason}" if reason else ""
                return f"{candidate} active ({source_name}){detail}"
    return None


def _read_payload(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _begonya_roots() -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get("BEGONYA_ROOT", "").strip()
    if configured:
        roots.append(Path(configured).expanduser())
    repo_root = Path(__file__).resolve().parent.parent
    roots.extend([
        repo_root.parent / "Begonya00",
        repo_root.parent / "Begonya",
        repo_root.parent / "begonya",
    ])
    legacy = Path.home() / ".gemini" / "antigravity" / "scratch" / "Begonya"
    roots.append(legacy)
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        marker = str(root.expanduser().resolve()).casefold()
        if marker not in seen:
            seen.add(marker)
            unique.append(root.expanduser())
    return unique


def candidate_gate_paths() -> list[Path]:
    """Return all known candidate paths in resolver priority order."""
    candidates: list[Path] = []
    configured = os.environ.get("PRAGMA_MACRO_GATE_PATH", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    legacy_env = os.environ.get("BEGONYA_MACRO_GATE_PATH", "").strip()
    if legacy_env:
        candidates.append(Path(legacy_env).expanduser())
    repo_root = Path(__file__).resolve().parent.parent
    candidates.extend([
        repo_root.parent / "Begonya00" / "shared" / "macro_bias_gate.json",
        repo_root.parent / "Begonya00" / "macro_engine" / "gateways" / "macro_bias_gate.json",
        repo_root.parent / "Begonya" / "shared" / "macro_bias_gate.json",
        repo_root.parent / "begonya" / "shared" / "macro_bias_gate.json",
        repo_root.parent / "Begonya" / "macro_engine" / "gateways" / "macro_bias_gate.json",
        repo_root.parent / "begonya" / "macro_engine" / "gateways" / "macro_bias_gate.json",
        repo_root / "shared" / "macro_bias_gate.json",
    ])
    for root in _begonya_roots():
        candidates.append(root / "shared" / "macro_bias_gate.json")
        candidates.append(root / "macro_engine" / "gateways" / "macro_bias_gate.json")
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        marker = str(candidate.expanduser().resolve()).casefold()
        if marker not in seen:
            seen.add(marker)
            unique.append(candidate.expanduser())
    return unique


def _file_info(path: Path, now: datetime | None = None) -> GateFileInfo | None:
    if not path.is_file():
        return None
    payload = _read_payload(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    timestamp = _payload_timestamp(payload) if payload is not None else None
    if timestamp is not None:
        age = _age_hours(timestamp, now)
        valid = not _future_invalid(timestamp, now)
        return GateFileInfo(path, timestamp, age, mtime, valid)
    return GateFileInfo(path, None, None, mtime, False)


def resolve_gate_path(path: str | Path | None = None,
                      max_age_hours: float = 36.0) -> tuple[Path, list[GateFileInfo]]:
    """Select the newest candidate by valid payload timestamp, then file mtime.

    An explicit constructor path pins the location. Otherwise all known paths
    are inspected; stale but parseable files remain selectable so refresh logic
    can identify and replace them.
    """
    if path is not None:
        forced = Path(path).expanduser()
        info = _file_info(forced)
        return forced, [info] if info else []
    infos = [info for item in candidate_gate_paths() if (info := _file_info(item))]
    valid_timestamp_infos = [info for info in infos if info.valid_timestamp and info.timestamp]
    if valid_timestamp_infos:
        selected = max(valid_timestamp_infos, key=lambda item: (item.timestamp.timestamp(), item.mtime))
    elif infos:
        selected = max(infos, key=lambda item: item.mtime)
    else:
        # Keep the default candidate meaningful for diagnostics when no file exists.
        selected = candidate_gate_paths()[0] if candidate_gate_paths() else (
            Path(__file__).resolve().parent.parent / "shared" / "macro_bias_gate.json"
        )
    return selected.path, infos


class MacroGate:
    """Resolve Begonya's execution gate; invalid/missing data fails closed."""

    def __init__(self, path: str | Path | None = None,
                 max_age_hours: float | None = None):
        if max_age_hours is None:
            try:
                max_age_hours = float(os.environ.get("BEGONYA_MACRO_MAX_AGE_HOURS", "36"))
            except ValueError:
                max_age_hours = 36.0
        if max_age_hours <= 0:
            raise ValueError("max_age_hours must be positive")
        self.max_age_hours = float(max_age_hours)
        self._pinned_path = Path(path).expanduser() if path is not None else None
        self.path, self.candidate_files = resolve_gate_path(self._pinned_path, self.max_age_hours)
        self.resolved_gate_path = str(self.path)

    def _load(self) -> tuple[dict[str, Any] | None, datetime | None, float | None, str | None]:
        payload = _read_payload(self.path)
        if payload is None:
            return None, None, None, "Could not read Begonya gate JSON"
        timestamp = _payload_timestamp(payload)
        if timestamp is None:
            return payload, None, None, "Begonya gate has no valid timestamp"
        age = _age_hours(timestamp)
        if _future_invalid(timestamp):
            return payload, timestamp, age, "Begonya gate timestamp is more than four hours in the future"
        if age > self.max_age_hours:
            return payload, timestamp, age, (
                f"Begonya gate is stale ({age:.1f}h; limit {self.max_age_hours:.1f}h)"
            )
        return payload, timestamp, age, None

    def gate_symbols(self) -> list[str]:
        payload, _, _, error = self._load()
        if payload is None or error:
            return []
        mapping = _mapping_from_payload(payload)
        if not isinstance(mapping, dict):
            return []
        symbols = set()
        for symbol, value in mapping.items():
            if _normalize_symbol(str(symbol)) == str(symbol).upper() and _gate_value(value) is None:
                continue
            if _gate_value(value) is not None:
                symbols.add(str(symbol).upper())
        return sorted(symbols)

    def get_bias(self, symbol: str = "XAUUSD") -> MacroDecision:
        if not self.path.is_file():
            return MacroDecision(Bias.NEUTRAL, "begonya_missing",
                                 f"Begonya gate file not found: {self.path}")
        payload, timestamp, age, error = self._load()
        if payload is None:
            return MacroDecision(Bias.NEUTRAL, "begonya_error", error or "Could not read gate")
        stamp = timestamp.isoformat() if timestamp else None
        if error:
            source = "begonya_stale" if error.startswith("Begonya gate is stale") else "begonya_invalid"
            return MacroDecision(Bias.NEUTRAL, source, error, timestamp=stamp)

        mapping = _mapping_from_payload(payload)
        if not isinstance(mapping, dict):
            return MacroDecision(Bias.NEUTRAL, "begonya_invalid",
                                 "No supported symbol gate mapping found", timestamp=stamp)

        requested = _normalize_symbol(symbol)
        matched_key = None
        entry = None
        for key, value in mapping.items():
            if _normalize_symbol(str(key)) == requested:
                matched_key, entry = str(key), value
                break

        block = _block_reason(payload, entry)
        if block:
            return MacroDecision(Bias.NEUTRAL, "begonya_blocked", block,
                                 gate=next((g for g in ("EVENT_FREEZE", "SYSTEMIC_STRESS")
                                            if g in block), "BLOCKED"), timestamp=stamp)
        gate = _gate_value(entry)
        if gate not in _GATE_TO_BIAS:
            return MacroDecision(Bias.NEUTRAL, "begonya_unmapped",
                                 f"No supported Begonya gate for symbol {symbol}",
                                 gate="UNMAPPED", timestamp=stamp)
        return MacroDecision(_GATE_TO_BIAS[gate], "begonya",
                             f"{matched_key} gate={gate}", gate=gate, timestamp=stamp)

    def diagnostics(self) -> dict[str, Any]:
        payload, timestamp, age, error = self._load()
        return {
            "resolved_gate_path": self.resolved_gate_path,
            "candidate_files": self.candidate_files,
            "timestamp": timestamp.isoformat() if timestamp else None,
            "age_hours": age,
            "error": error,
            "gate_symbols": self.gate_symbols(),
            "decisions": {symbol: self.get_bias(symbol) for symbol in ("XAUUSD", "EURUSD", "BTCUSD")},
        }


def refresh_begonya_gate(path: str | Path | None = None, *,
                         max_age_hours: float = 36.0, timeout: int = 120) -> dict[str, Any]:
    """Run Begonya's macro engine if its selected gate is missing or stale."""
    gate = MacroGate(path, max_age_hours=max_age_hours)
    _, _, _, error = gate._load()
    if gate.path.is_file() and error is None:
        return {"refreshed": False, "reason": "gate is fresh", "path": str(gate.path)}
    for root in _begonya_roots():
        main_file = root / "macro_engine" / "main.py"
        if not main_file.is_file():
            continue
        try:
            completed = subprocess.run(
                [sys.executable, "macro_engine/main.py"],
                cwd=str(root), timeout=timeout, check=False,
                capture_output=True, text=True,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"refreshed": False, "reason": f"Begonya launch failed: {exc}", "root": str(root)}
        refreshed = MacroGate(path, max_age_hours=max_age_hours)
        _, _, _, refresh_error = refreshed._load()
        return {
            "refreshed": completed.returncode == 0 and refresh_error is None,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "path": refreshed.resolved_gate_path,
            "reason": refresh_error or ("refresh completed" if completed.returncode == 0 else "Begonya exited non-zero"),
        }
    return {"refreshed": False, "reason": "Begonya macro_engine/main.py not found"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose Begonya macro gate resolution")
    parser.add_argument("--symbol", default="XAUUSD", help="Symbol to inspect (default: XAUUSD)")
    parser.add_argument("--max-age-hours", type=float, default=36.0)
    parser.add_argument("--refresh-macro", action="store_true",
                        help="Refresh Begonya first if its gate is missing or stale")
    args = parser.parse_args(argv)
    if args.refresh_macro:
        print("REFRESH:", json.dumps(refresh_begonya_gate(max_age_hours=args.max_age_hours), default=str))
    gate = MacroGate(max_age_hours=args.max_age_hours)
    print("CANDIDATE FILES:")
    for candidate in candidate_gate_paths():
        info = _file_info(candidate)
        if info:
            age_text = f"{info.age_hours:.2f}h" if info.age_hours is not None else "timestamp unavailable"
            print(f"  {candidate} | age={age_text} | timestamp_valid={info.valid_timestamp} | mtime={info.mtime:.0f}")
        else:
            print(f"  {candidate} | MISSING")
    print(f"RESOLVED_GATE_PATH: {gate.resolved_gate_path}")
    info = _file_info(gate.path)
    print(f"TIMESTAMP_AGE_HOURS: {info.age_hours if info and info.age_hours is not None else 'unknown'}")
    print(f"GATE_SYMBOLS: {gate.gate_symbols()}")
    print("SYMBOL | BIAS | GATE | SOURCE | REASON")
    for symbol in (args.symbol, "XAUUSD", "EURUSD", "BTCUSD"):
        decision = gate.get_bias(symbol)
        print(f"{symbol} | {int(decision.bias)} | {decision.gate} | {decision.source} | {decision.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
