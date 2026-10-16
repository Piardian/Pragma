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
with `BEGONYA_MACRO_MAX_AGE_HOURS`. Begonya's current timestamps omit a
timezone, so Pragma interprets naive timestamps as `Europe/Istanbul`; override
this with `BEGONYA_MACRO_TIMEZONE` if Begonya is configured to emit local time
in a different timezone. Explicit timezone offsets in the JSON are respected.

- `LONG_ONLY` maps to long bias.
- `SHORT_ONLY` maps to short bias.
- `NEUTRAL_RANGE` permits only balance-regime mean-reversion POIs; it does
  not permit trend-pullback POIs.
- A missing, stale, malformed, or unmapped gate never defaults to long or short.

Pragma reads Begonya's output artifact; it does not start Begonya's macro engine
or refresh its gate file. Begonya must be running on its own schedule for this
file to stay current.


## Continuous multi-market scanner (Windows)

The scanner reads Begonya's fresh gate file, matches its symbol universe to
symbols available in the MT5 terminal, and runs the Pragma pipeline once per
matched symbol. It then waits for the next 15-minute clock boundary.

Run one cycle:
```powershell
python -m pragma.market_scanner --once --bars 3000
```

Run continuously:
```powershell
python -m pragma.market_scanner --interval-minutes 15 --bars 3000
```

POI alerts are sent when a qualifying zone is found; execution-candidate alerts
are separate and are sent only when the M1 trigger and risk filters pass. Both
go to Telegram when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured;
otherwise they print to the console. Set those as Windows user environment
variables (do not commit credentials), then open a new terminal. In PowerShell,
set them with your own values:
```powershell
setx TELEGRAM_BOT_TOKEN "YOUR_BOT_TOKEN"
setx TELEGRAM_CHAT_ID "YOUR_CHAT_ID"
```

For automatic startup after Windows sign-in, run PowerShell from the project
folder:
```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_startup_task.ps1
```

The task starts at user logon, not before login. MetaTrader 5 must be installed,
running, logged in, and connected to the broker; its available symbols must
include the instruments to be scanned. Pragma does not place broker orders.


## Broker-free shadow trading (Windows)

The optional shadow trader simulates virtual positions from Pragma execution signals. MT5 is used **only as a read-only price feed**; this module never sends broker orders. Default virtual balance is 10,000 account units with 1% initial balance risk per trade. These are simulation assumptions, not broker contract sizing.

Run it manually:
```powershell
.\run_shadow_trader.bat
```

Or install a separate Windows Scheduled Task that starts after the current Windows user signs in and restarts the process after failures:
```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_shadow_startup_task.ps1
```

Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as Windows user environment variables to receive entry, partial TP, final TP/SL, balance, error, and periodic heartbeat notifications. The task starts after sign-in, not before a user session; MT5 must also be installed, logged in, and providing fresh prices. For a restart/reboot to recover open virtual positions, state is stored outside the repository under `%LOCALAPPDATA%\Pragma\shadow_trading` (or `PRAGMA_SHADOW_DIR` if configured).

Simulation policy: TP1 takes 50% off when TP1 and TP2 differ, then moves the remaining stop to entry; TP2 closes the remainder. If SL and a target are both touched in the same OHLC bar, SL wins. TP1 and TP2 are not both assumed to occur in the same bar. Results omit broker commissions and live execution slippage unless reflected by the configured spread cost. Do not interpret paper results as proof of future profitability.
