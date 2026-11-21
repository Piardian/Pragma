"""Predeclared entry-only hypotheses; no changes to stop/target policies."""
import pandas as pd


def entry_variant(bars, signal, direction, stop, target1, variant):
    from pragma.backtest_engine import _resample_tf
    signal = pd.Timestamp(signal)
    decision = signal+pd.Timedelta(minutes=1)
    m5 = _resample_tf(bars.loc[:signal], "M5")
    if m5.empty or m5.index[-1]+pd.Timedelta(minutes=5) != decision:
        return {"accepted": False, "reason": "SIGNAL_NOT_M5_CLOSE"}
    candle = m5.iloc[-1]
    if variant == "baseline":
        return {"accepted": True, "entry_time": decision.isoformat(), "reason": "BASELINE"}
    if variant == "directional_body_half":
        span = float(candle.high-candle.low)
        body = float(candle.close-candle.open)*(1 if direction == "LONG" else -1)
        accepted = span > 0 and body/span >= 0.5
        return {"accepted": bool(accepted), "entry_time": decision.isoformat() if accepted else None,
                "reason": "BODY_CONFIRMED" if accepted else "DIRECTIONAL_BODY_BELOW_HALF"}
    if variant != "delay_one_m5_break":
        raise ValueError("Unknown entry variant")
    confirm = bars.loc[(bars.index >= decision) & (bars.index < decision+pd.Timedelta(minutes=5))]
    expected = pd.date_range(decision, periods=5, freq="min")
    if not confirm.index.equals(expected):
        return {"accepted": False, "reason": "MISSING_CONFIRMATION_MINUTES"}
    touched_stop = confirm.low.min() <= stop if direction == "LONG" else confirm.high.max() >= stop
    touched_target = confirm.high.max() >= target1 if direction == "LONG" else confirm.low.min() <= target1
    if touched_stop or touched_target:
        return {"accepted": False, "reason": "STOP_OR_TARGET_BEFORE_DELAYED_ENTRY"}
    confirmed = float(confirm.close.iloc[-1]) > float(candle.high) if direction == "LONG" else float(confirm.close.iloc[-1]) < float(candle.low)
    return {"accepted": bool(confirmed),
            "entry_time": (decision+pd.Timedelta(minutes=5)).isoformat() if confirmed else None,
            "reason": "NEXT_M5_BREAK_CONFIRMED" if confirmed else "NEXT_M5_BREAK_NOT_CONFIRMED"}
