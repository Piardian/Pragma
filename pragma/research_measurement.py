"""Deterministic diagnostics; none of these functions can promote a strategy."""
from __future__ import annotations

from dataclasses import asdict
import numpy as np
import pandas as pd

from pragma.backtest_engine import _OpenTrade, _manage_open_trade, _apply_funding, _trade_record


def finite_json(value):
    if isinstance(value, dict):
        return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [finite_json(v) for v in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return value


def weekly_bootstrap(rows, *, field="r_multiple", time_field="entry_time", draws=5000, seed=231026):
    """Resample calendar weeks INCLUDING empty weeks, preserving trade clusters.

    This is exploratory uncertainty, not a corrected multiple-testing p-value.
    """
    if not rows:
        return {"n": 0, "mean": None, "ci95": None, "weeks": 0}
    values = np.array([float(r[field]) for r in rows])
    dates = pd.DatetimeIndex([pd.Timestamp(r[time_field]) for r in rows]).tz_convert("UTC").tz_localize(None)
    weeks = dates.to_period("W-SUN")
    calendar = pd.period_range(weeks.min(), weeks.max(), freq="W-SUN")
    grouped = pd.DataFrame({"week": weeks, "value": values}).groupby("week").value.agg(["sum", "count"]).reindex(calendar, fill_value=0)
    result = {"n": len(rows), "mean": float(values.mean()), "sum": float(values.sum()),
              "weeks": len(calendar), "ci95": None, "method": "calendar_week_cluster_bootstrap",
              "multiple_testing_corrected": False}
    if len(calendar) >= 8:
        rng = np.random.default_rng(seed)
        ix = rng.integers(0, len(calendar), size=(draws, len(calendar)))
        totals = grouped["sum"].to_numpy()[ix].sum(axis=1)
        counts = grouped["count"].to_numpy()[ix].sum(axis=1)
        means = totals[counts > 0] / counts[counts > 0]
        result["ci95"] = np.quantile(means, [0.025, 0.975]).tolist()
    return result


def replay_fixed_entries(bars, trades, costs, *, be_offset_r):
    """Paired exits on IDENTICAL entries; overlaps are independent counterfactuals.

    No separate capital curve is inferred from overlapping counterfactuals.
    """
    records = []
    for t in trades:
        fill = pd.Timestamp(t["fill_time"])
        p = _OpenTrade(t["symbol"], t["direction"], t["poi_type"], t["regime"], fill,
                       t["entry_price"], t["initial_stop_loss"], t["initial_stop_loss"],
                       t["tp1"], t["tp2"], abs(t["entry_price"] - t["initial_stop_loss"]),
                       be_offset_r=be_offset_r, funding_rate_8h=costs.funding_rate_8h,
                       entry_at_open=True, signal_bar_time=t["signal_bar_time"],
                       decision_time=t["decision_time"])
        record = None
        post_tp1_mae = post_tp1_mfe = 0.0
        for stamp, bar in bars.loc[fill:].iterrows():
            if p.tp1_taken:
                if p.direction == "LONG":
                    post_tp1_mae = max(post_tp1_mae, (p.entry_price - bar.low)/p.initial_risk)
                    post_tp1_mfe = max(post_tp1_mfe, (bar.high - p.entry_price)/p.initial_risk)
                else:
                    post_tp1_mae = max(post_tp1_mae, (bar.high - p.entry_price)/p.initial_risk)
                    post_tp1_mfe = max(post_tp1_mfe, (p.entry_price - bar.low)/p.initial_risk)
            record = _manage_open_trade(p, bar, stamp, costs.fixed_per_side,
                                        costs.pct_per_side, costs.funding_rate_8h > 0)
            if record is not None:
                break
        if record is None:
            stamp = bars.index[-1] + pd.Timedelta(minutes=1)
            exit_price = costs.adverse(float(bars.close.iloc[-1]), p.direction, False)
            fraction = (1-p.tp1_close_pct) if p.tp1_taken else 1.0
            p.r_multiple += fraction * (exit_price-p.entry_price) * (1 if p.direction == "LONG" else -1)/p.initial_risk
            if costs.funding_rate_8h:
                _apply_funding(p, stamp)
            record = _trade_record(p, stamp, "END_OF_DATA")
        records.append(dict(asdict(record), post_tp1_mae_r=post_tp1_mae,
                            post_tp1_mfe_r=post_tp1_mfe,
                            excursion_precision="WHOLE_BARS_UP_TO_EXIT_MAY_INCLUDE_POST_EXIT_EXTREMES"))
    return records


def horizon_diagnostics(bars, candidates, costs):
    """All executable pre-occupancy candidates vs previous-week same-clock baseline.

    Overlapping signal horizons are not independent. Fixed horizons never use
    fabricated gap prices. Reference directions match the candidate direction.
    """
    index = bars.index
    rows = []
    rejected = []
    for candidate in candidates:
        stamp = pd.Timestamp(candidate["signal_bar_time"])
        fill = stamp + pd.Timedelta(minutes=1)
        side = candidate["direction"]
        sign = 1 if side == "LONG" else -1
        for horizon in (5, 15, 30):
            metrics = []
            for start in (fill, fill - pd.Timedelta(days=7)):
                end = start + pd.Timedelta(minutes=horizon-1)
                if start not in index or end not in index:
                    metrics.append(None)
                    continue
                j = index.get_loc(start)
                window = bars.iloc[j:j+horizon]
                if len(window) != horizon or window.index[-1] != end:
                    metrics.append(None)
                    continue
                reference = float(window.open.iloc[0])
                entry = costs.adverse(reference, side, True)
                exit_price = costs.adverse(float(window.close.iloc[-1]), side, False)
                metrics.append({
                    "gross_bps": sign*(float(window.close.iloc[-1])-reference)/reference*10000,
                    "net_bps": sign*(exit_price-entry)/reference*10000,
                    "mae_bps": max(0, (reference-float(window.low.min())) if side == "LONG" else (float(window.high.max())-reference))/reference*10000,
                    "mfe_bps": max(0, (float(window.high.max())-reference) if side == "LONG" else (reference-float(window.low.min())))/reference*10000,
                })
            if metrics[0] is None:
                continue
            row = dict(candidate, horizon_minutes=horizon, entry_time=fill.isoformat(), **metrics[0])
            if metrics[1] is not None:
                row.update(reference_net_bps=metrics[1]["net_bps"], paired_excess_bps=metrics[0]["net_bps"]-metrics[1]["net_bps"])
            (rows if candidate["eligible"] else rejected).append(row)
    summary = {}
    for horizon in (5, 15, 30):
        subset = [r for r in rows if r["horizon_minutes"] == horizon]
        paired = [r for r in subset if "paired_excess_bps" in r]
        summary[str(horizon)] = {
            "net_bps": weekly_bootstrap(subset, field="net_bps"),
            "paired_excess_bps": weekly_bootstrap(paired, field="paired_excess_bps"),
            "gross_mean_bps": float(np.mean([r["gross_bps"] for r in subset])) if subset else None,
            "mean_mae_bps": float(np.mean([r["mae_bps"] for r in subset])) if subset else None,
            "mean_mfe_bps": float(np.mean([r["mfe_bps"] for r in subset])) if subset else None,
            "rejected_counterfactual_n": sum(r["horizon_minutes"] == horizon for r in rejected),
        }
    return summary, rows, rejected
