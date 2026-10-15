"""Continuous multi-symbol scanner driven by Begonya's published gate universe."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone

from pragma.data.mt5_data import MT5DataClient
from pragma.execution_notifier import ExecutionNotifier
from pragma.macro_gate import MacroGate
from pragma.run_pipeline import run_pipeline


def _clean_symbol(value: str) -> str:
    return "".join(char for char in value.upper() if char.isalnum())


def resolve_symbols(gate_symbols: list[str], available_symbols: list[str]) -> list[str]:
    """Map Begonya base symbols to one best matching broker symbol each."""
    available = sorted(set(available_symbols), key=lambda value: (len(value), value.upper()))
    chosen: set[str] = set()
    for base in gate_symbols:
        exact = [symbol for symbol in available if symbol.upper() == base.upper()]
        if exact:
            chosen.add(exact[0])
            continue
        normalized_base = _clean_symbol(base)
        matches = [
            symbol for symbol in available
            if _clean_symbol(symbol).startswith(normalized_base)
        ]
        if matches:
            chosen.add(matches[0])
    return sorted(chosen, key=str.upper)


def seconds_until_next_boundary(interval_minutes: int,
                                now: datetime | None = None) -> float:
    if interval_minutes < 1 or interval_minutes > 60 or 60 % interval_minutes:
        raise ValueError("interval_minutes must divide 60 (for example 5, 10, 15, or 30)")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    minute = ((current.minute // interval_minutes) + 1) * interval_minutes
    boundary = current.replace(second=0, microsecond=0)
    if minute >= 60:
        boundary = boundary.replace(minute=0) + timedelta(hours=1)
    else:
        boundary = boundary.replace(minute=minute)
    return max(1.0, (boundary - current).total_seconds())


def run_scan_cycle(bars_count: int = 3000,
                   notifier: ExecutionNotifier | None = None) -> dict:
    macro_gate = MacroGate()
    gate_symbols = macro_gate.gate_symbols()
    if not gate_symbols:
        raise RuntimeError(
            f"No fresh Begonya macro gates found at {macro_gate.path}. "
            "Refresh Begonya's gate output before scanning."
        )
    with MT5DataClient() as client:
        available = client.symbols()
    symbols = resolve_symbols(gate_symbols, available)
    if not symbols:
        raise RuntimeError(
            "None of Begonya's gated symbols are available in MT5. "
            "Check the broker's Market Watch symbols."
        )

    notifier = notifier or ExecutionNotifier()
    results = []
    for symbol in symbols:
        try:
            report = run_pipeline(
                symbol=symbol,
                bars_count=bars_count,
                notifier=notifier,
            )
            results.append({
                "symbol": symbol,
                "status": "OK",
                "regime": report.get("regime"),
                "macro": report.get("macro"),
                "poi_count": len(report.get("pois", [])),
                "trigger_count": len(report.get("triggers", [])),
                "notification_count": sum(
                    1 for item in report.get("notifications", [])
                    if item.get("sent")
                ),
            })
        except Exception as exc:
            results.append({
                "symbol": symbol,
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"[ERROR] {symbol}: {type(exc).__name__}: {exc}")

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "gate_file": str(macro_gate.path),
        "gate_symbol_count": len(gate_symbols),
        "available_symbol_count": len(symbols),
        "success_count": sum(item["status"] == "OK" for item in results),
        "error_count": sum(item["status"] == "ERROR" for item in results),
        "symbols": results,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pragma continuous multi-market scanner")
    parser.add_argument("--bars", type=int, default=3000)
    parser.add_argument("--interval-minutes", type=int, default=15)
    parser.add_argument("--once", action="store_true", help="Run one scan cycle and exit")
    args = parser.parse_args(argv)
    if args.interval_minutes < 1 or args.interval_minutes > 60 or 60 % args.interval_minutes:
        parser.error("--interval-minutes must divide 60 (e.g. 5, 10, 15, 30)")

    notifier = ExecutionNotifier()
    while True:
        cycle_failed = False
        try:
            run_scan_cycle(bars_count=args.bars, notifier=notifier)
        except Exception as exc:
            cycle_failed = True
            print(f"[SCAN ERROR] {type(exc).__name__}: {exc}")
        if args.once:
            return 1 if cycle_failed else 0
        if cycle_failed:
            wait = 60.0
            next_run = datetime.now(timezone.utc) + timedelta(seconds=wait)
            print(f"Retrying after startup/data error at {next_run.strftime('%Y-%m-%d %H:%M:%S UTC')}.")
            time.sleep(wait)
            continue
        wait = seconds_until_next_boundary(args.interval_minutes)
        next_run = datetime.now(timezone.utc) + timedelta(seconds=wait)
        print(
            f"Next scan at {next_run.strftime('%Y-%m-%d %H:%M:%S UTC')} "
            f"(waiting {wait:.0f}s)."
        )
        time.sleep(wait)


if __name__ == "__main__":
    raise SystemExit(main())
