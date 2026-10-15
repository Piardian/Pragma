# Pragma

Deterministic quantitative trading research system. Initial phase implements the free MT5 data pipeline, AMT volume profile, and session VWAP.

## Defaults
- Runtime: Python 3.11+
- Primary data source: locally running MetaTrader 5 terminal
- Initial symbol: `XAUUSD` (override in configuration; broker symbol names may differ)
- Dependencies: MetaTrader5, numpy, pandas. Tests use unittest.
- No paid APIs or services.

## Install
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Verify
```bash
python -m unittest discover -s tests -v
```

## Important data semantics
MT5 OHLC bars provide tick volume, not centralized traded volume for OTC FX/CFD symbols. The profile assigns each bar's tick volume to its typical price bin; this is a reproducible bar-level approximation, not true bid/ask volume-at-price. VWAP bands are volume-weighted population standard-deviation bands. Value Area is computed by expanding outward from POC until the configured fraction of total profile volume is covered; it is not mathematically equivalent to one standard deviation.

This is a research foundation, not a validated profitable strategy. No live order execution is implemented in these phases.


## Begonya macro gate integration

By default, Pragma reads the latest published gate from:

`%USERPROFILE%\.gemini\antigravity\scratch\Begonya\shared\macro_bias_gate.json`

Override the file location with `BEGONYA_MACRO_GATE_PATH`. The reader prefers
`execution_bias_gates` and falls back to the deterministic gate mappings.
Gate files older than 36 hours fail closed to neutral; configure the threshold
with `BEGONYA_MACRO_MAX_AGE_HOURS`.

- `LONG_ONLY` maps to long bias.
- `SHORT_ONLY` maps to short bias.
- `NEUTRAL_RANGE` permits only balance-regime mean-reversion POIs; it does
  not permit trend-pullback POIs.
- A missing, stale, malformed, or unmapped gate never defaults to long or short.

Pragma reads Begonya's output artifact; it does not start Begonya's macro engine
or refresh its gate file. Begonya must be running on its own schedule for this
file to stay current.
