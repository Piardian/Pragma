# Pragma measurement v2

This is an observer-first research migration. Existing scanner alerts and the legacy shadow account keep their established behavior. Their gross/incomplete-cost balances are not validated net evidence. No broker orders, Telegram messages, daemon restarts or live promotion are part of this work.

## What changed

- `pragma/measurement.py` owns the shared regime/trigger contract. It includes crypto flags, volume-day veto, instrument RR settings, touch-window policy and the same entry cost used by replay.
- `evaluate_prefix` accepts only a closed M1 prefix and an explicit bias. It never reads today's gate for historical replay. It excludes the first downloaded session as a possibly incomplete prior profile.
- The corrected replay fills at the next contiguous M1 open. Signal bar, decision and fill times are separate. Fill-bar exits are allowed; stop wins OHLC ambiguity; adverse gaps use the worse opening price. Exit times are upper bounds from OHLC, not claimed tick fills.
- Fixed per-side cost plus percentage commission/slippage apply adversely at entry and every exit. Assumed funding is separately debited. A cost object always records provenance. Drawdown percentages use the relevant peak/start denominator.
- HistData timestamps are parsed as fixed UTC-5, then converted to UTC. Missing volume is not reconstructed from candle range. Old proxy parquet and missing historical macro vintages fail with explicit reasons. Old result files are preserved, with a separate admissibility registry.

## Safe forward path

`run_pipeline(..., measurement_mode=True)` returns the shared measurement result without notifications. Default pipeline calls keep the legacy result plus `measurement_observer`, so changes can be compared before switching strategy behavior. Updated shadow code archives this counterfactual into a separate JSONL when that daemon next runs with the new code. No existing process was restarted here.

An independently runnable collector records bid/ask, quote time, clock correction, available contract specifications, macro-as-of snapshot and rejected/executable candidates. Commission, actual fills and actual slippage remain null when unavailable. Binance current funding snapshots are not labelled historical executed funding.

```powershell
python scripts/observe_measurement.py --source mt5 --output reports/forward_observer_mt5 --cycles 1
python scripts/observe_measurement.py --source binance --output reports/forward_observer_binance --cycles 1
```

Use `--cycles 0` only when intentionally running a continuous local observer; stop with Ctrl+C. This collector writes no broker orders or alerts and produces no PnL. Its isolated Binance cache does not mutate frozen research input caches.

## Frozen experiments

```powershell
python scripts/run_measurement_research.py --output reports/new_crypto_run --bars 300000 --timeframes M15
python scripts/run_broker_measurement_research.py --output reports/new_broker_run --bars 30000
```

Output folders must not already exist. Protocol, code/config/input copies and hashes are written before trials. Every declared combination is reported; there is no best-symbol promotion. Hashes are verified again before completion. A failed or interrupted run cannot be treated as complete.

Crypto defaults cover BTCUSDT, SOLUSDT and LINKUSDT, each at the current M15 default. Optional M5 is an additional research trial. The matrix compares baseline, last-bar-only touch, and all costs at 1.5x. A separate paired exit replay changes only the TP1-to-BE transition on identical baseline entries. Overlapping paired exits are independent counterfactuals, not a portfolio equity curve.

Entry diagnostics record 5/15/30-minute signed gross/net scenario bps, MAE/MFE, and previous-week same-clock, same-direction reference returns. Touched but rejected candidates are retained. Empty weeks remain in week-cluster bootstrap; fewer than eight calendar weeks receive no interval. Reported intervals are exploratory and not a correction for choosing among multiple models.

Broker capture uses real tick-count volume. Historical bid OHLC is converted to an assumed midpoint using a captured current spread; that spread is not labelled historical calibration. Commission/slippage are explicit assumptions and swap remains unavailable, so broker scenario R is not measured net edge evidence.

## Outstanding evidence

The March–October 2026 crypto history and previously inspected 2025 data are exploratory. There is no new OOS profitability claim. Forward quote observations do not supply executed slippage or commission. A meaningful time-separated sample, actual cost evidence, stable decision parity and multiplicity-aware evaluation are still required before any profitability or live-readiness claim.

The legacy broker clock adapter verifies a fresh current heartbeat. Applying its current offset to older history is not independent historical clock validation. Broker research records that limitation explicitly.

## Verification

Run `python -m unittest discover -s tests -q`. Financial measurement checks include fixed-EST parsing, rejecting legacy volume/current-macro reuse, two-sided costs, future-mutation invariance, pointwise/replay decision parity, next-open timestamps, gap stops, fill-bar stop priority, unchanged paired entries, fixed-horizon cost accounting and deterministic bootstrap.

## Current forward observer

A read-only Binance collector was started at 00:05 Istanbul on 24 October 2026, using the isolated reports/forward_observer_binance_2026-10-23 folder and a 30-second poll. Startup PID was 118600; observer.pid records it. Check the command line before stopping any PID, since operating systems can reuse PIDs. No startup task or scheduled automation was installed. The MT5 collector stopped on an authorization error.

## Multiple MT5 installations and closed-market research

Use --terminal-path with the broker terminal executable in run_broker_measurement_research.py. The explicit connection never falls back to another installation. For historical research outside FX hours, --quote-archive may specify an observed MT5 quote JSONL as a declared fixed-spread scenario. It does not relax forward quote freshness checks or establish historical spread calibration. The completed 13-symbol FX/gold result is in FX_MEASUREMENT_RESULT_2026-10-24.md.
