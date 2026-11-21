"""Post-hoc cost attribution on fixed baseline paths, not a new strategy trial."""
import argparse
import json
from pathlib import Path

import pandas as pd


def attribute(trade, bars, costs):
    fill = pd.Timestamp(trade["fill_time"])
    end = pd.Timestamp(trade["exit_time"])
    risk = abs(trade["entry_price"]-trade["initial_stop_loss"])
    reference_entry = float(bars.loc[fill, "open"])
    reason = trade["exit_reason"]
    if reason == "END_OF_DATA":
        reference_exit = float(bars.iloc[-1].close)
    elif reason in ("STOP_LOSS", "BREAKEVEN_STOP"):
        stop = trade["entry_price"] if trade["tp1_taken"] else trade["initial_stop_loss"]
        opening = float(bars.loc[end-pd.Timedelta(minutes=1), "open"])
        reference_exit = min(stop, opening) if trade["direction"] == "LONG" else max(stop, opening)
    elif reason == "TP1_THEN_BREAKEVEN_SAME_BAR":
        reference_exit = trade["entry_price"]
    elif reason in ("TAKE_PROFIT_2", "TAKE_PROFIT_2_SINGLE_TARGET", "TP1_TP2_SAME_BAR"):
        reference_exit = trade["tp2"]
    else:
        raise ValueError(f"Unrecognized baseline exit: {reason}")
    weighted_exit = .5*(trade["tp1"]+reference_exit) if trade["tp1_taken"] else reference_exit
    notional_sum = reference_entry + weighted_exit
    spread_r = 2*costs["fixed_per_side"]/risk
    commission_r = notional_sum*costs["commission_bps"]/10000/risk
    slippage_r = notional_sum*costs["slippage_bps"]/10000/risk
    funding_r = trade["funding_cost_r"]
    cost_r = spread_r + commission_r + slippage_r + funding_r
    return {"entry_time":trade["entry_time"], "scenario_r":trade["r_multiple"],
            "attributed_spread_r":spread_r, "assumed_commission_r":commission_r,
            "assumed_slippage_r":slippage_r, "funding_r":funding_r,
            "total_cost_r":cost_r, "fixed_path_before_attributed_cost_r":trade["r_multiple"]+cost_r}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    args = parser.parse_args()
    run = Path(args.run)
    completion = json.loads((run/"completion.json").read_text(encoding="utf-8"))
    if completion["status"] != "COMPLETE":
        raise ValueError("Attribution requires a completed experiment")
    protocol = json.loads((run/"protocol_frozen.json").read_text(encoding="utf-8"))
    summaries = []
    for symbol, meta in protocol["captured"].items():
        report = json.loads((run/f"{symbol}_baseline.json").read_text(encoding="utf-8"))
        bars = pd.read_csv(run/"frozen"/meta["path"], index_col="time", parse_dates=True)
        bars.index = pd.DatetimeIndex(pd.to_datetime(bars.index, utc=True))
        bars[["open","high","low","close"]] += meta["half_spread_assumed"]
        details = [attribute(t,bars,report["measurement"]["costs"]) for t in report["trades"]]
        fields = ("scenario_r", "attributed_spread_r", "assumed_commission_r", "assumed_slippage_r", "funding_r", "total_cost_r", "fixed_path_before_attributed_cost_r")
        summaries.append({"symbol":symbol,"n":len(details),
                          **{field:sum(r[field] for r in details) for field in fields},"trades":details})
    result = {"classification":"POSTHOC_FIXED_PATH_COST_ATTRIBUTION_NOT_ZERO_COST_STRATEGY_REPLAY",
              "limitations":["Retains baseline entry/exit path and risk denominator", "BE levels retain cost-inclusive baseline levels", "Commission/slippage assumptions, swap missing", "Not calibrated broker net performance", "Do not select new parameters from this diagnostic"],
              "edge_proven":False, "symbols":summaries}
    (run/"cost_attribution_posthoc.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")


if __name__ == "__main__":
    main()
