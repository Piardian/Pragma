"""Quantitative Trade and Rejection Journal for Pragma.

Persists full-feature trade snapshots (entry conditions, MAE, MFE, Z-Score,
volume multiplier, holding period, outcome) and rejected signal audit trails
to durable CSV and JSON formats for post-trade root-cause analysis.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

import pandas as pd


TRADE_JOURNAL_COLUMNS = [
    "trade_id",
    "symbol",
    "direction",
    "poi_type",
    "regime",
    "macro_bias",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "initial_stop",
    "final_stop",
    "take_profit_1",
    "take_profit_2",
    "rr_planned",
    "realized_r",
    "realized_pnl",
    "outcome",
    "bars_held",
    "mae_r",
    "mfe_r",
    "z_score",
    "volume_multiplier",
    "order_flow_delta",
    "atr",
    "vwap",
    "pdpoc",
    "balance_after",
]

REJECTED_SIGNALS_COLUMNS = [
    "timestamp",
    "symbol",
    "direction",
    "poi_type",
    "regime",
    "macro_bias",
    "reason",
    "entry_price",
    "stop_loss",
    "take_profit_1",
    "rr_ratio",
    "z_score",
    "volume_multiplier",
    "order_flow_delta",
    "atr",
]


def record_trade_to_journal(journal_path: Path | str, trade: dict[str, Any]) -> None:
    """Append a closed trade record to trade_journal.csv atomically."""
    path = Path(journal_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0

    row = {col: trade.get(col, "") for col in TRADE_JOURNAL_COLUMNS}
    # Ensure numeric floats are formatted cleanly
    for key, val in row.items():
        if isinstance(val, float):
            row[key] = f"{val:.5f}" if abs(val) < 1e5 else f"{val:.2f}"

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_JOURNAL_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def record_rejected_signal(rejected_path: Path | str, signal_info: dict[str, Any]) -> None:
    """Append a rejected signal candidate to rejected_signals.csv."""
    path = Path(rejected_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0

    row = {col: signal_info.get(col, "") for col in REJECTED_SIGNALS_COLUMNS}
    for key, val in row.items():
        if isinstance(val, float):
            row[key] = f"{val:.5f}" if abs(val) < 1e5 else f"{val:.2f}"

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REJECTED_SIGNALS_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def load_trade_journal(journal_path: Path | str) -> pd.DataFrame:
    """Load trade journal CSV into a DataFrame with typed columns."""
    path = Path(journal_path).expanduser()
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=TRADE_JOURNAL_COLUMNS)
    df = pd.read_csv(path)
    for num_col in ["entry_price", "exit_price", "initial_stop", "final_stop",
                    "take_profit_1", "take_profit_2", "rr_planned", "realized_r",
                    "realized_pnl", "bars_held", "mae_r", "mfe_r", "z_score",
                    "volume_multiplier", "order_flow_delta", "atr", "vwap", "pdpoc", "balance_after"]:
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(df[num_col], errors="coerce")
    if "entry_time" in df.columns:
        df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce", utc=True)
    if "exit_time" in df.columns:
        df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce", utc=True)
    return df


def load_rejected_signals(rejected_path: Path | str) -> pd.DataFrame:
    """Load rejected signals CSV into a DataFrame."""
    path = Path(rejected_path).expanduser()
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=REJECTED_SIGNALS_COLUMNS)
    df = pd.read_csv(path)
    for num_col in ["entry_price", "stop_loss", "take_profit_1", "rr_ratio",
                    "z_score", "volume_multiplier", "order_flow_delta", "atr"]:
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(df[num_col], errors="coerce")
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df
