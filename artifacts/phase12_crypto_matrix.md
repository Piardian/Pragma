# Phase 12 Crypto Walk-Forward Matrix (100,000 Closed M1 Bars)

**Data target**: Binance USD-M Futures, 100,000 closed M1 bars per symbol (~68 observed UTC sessions).
**Slippage & Spread**: 4 bps adverse cost per side (0.04% taker entry + 0.04% exit = 8 bps round-trip).
**Execution Engine**: Strict causal prior-session AMT profile + developing session VWAP + M15 rolling ATR.
**Regime Detection**: Autonomous causal regime (Bull Imbalance / Bear Imbalance / Balance) on every closed candle.

| Symbol | Trigger TF | Bars | Trades | Win Rate | Profit Factor | Net R | Expectancy R | Max DD R | Max Total DD % | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| BTCUSDT | M5 | 100,000 | 40 | 30.00% | 0.680 | -10.21R | -0.255R | 17.48R | 16.43% | OK |
| BTCUSDT | M15 | 100,000 | 16 | 43.75% | 1.118 | +1.21R | +0.076R | 3.94R | 4.05% | OK |
| ETHUSDT | M5 | 100,000 | 55 | 20.00% | 0.576 | -20.81R | -0.378R | 25.77R | 24.29% | OK |
| ETHUSDT | M15 | 100,000 | 19 | 15.79% | 0.490 | -9.15R | -0.482R | 11.19R | 10.81% | OK |
| SOLUSDT | M5 | 100,000 | 63 | 36.51% | 1.281 | +12.36R | +0.196R | 9.73R | 11.38% | OK |
| SOLUSDT | M15 | 100,000 | 31 | 29.03% | 0.899 | -2.44R | -0.079R | 7.68R | 7.71% | OK |
| BNBUSDT | M5 | 100,000 | 55 | 18.18% | 0.486 | -26.42R | -0.480R | 32.76R | 30.10% | OK |
| BNBUSDT | M15 | 100,000 | 23 | 21.74% | 0.872 | -2.66R | -0.116R | 10.27R | 9.86% | OK |
| XRPUSDT | M5 | 100,000 | 71 | 22.54% | 0.479 | -31.81R | -0.448R | 34.82R | 30.34% | OK |
| XRPUSDT | M15 | 100,000 | 25 | 32.00% | 0.912 | -1.65R | -0.066R | 7.45R | 7.51% | OK |
| DOGEUSDT | M5 | 100,000 | 62 | 30.65% | 0.989 | -0.52R | -0.008R | 14.55R | 13.68% | OK |
| DOGEUSDT | M15 | 100,000 | 19 | 26.32% | 0.485 | -7.91R | -0.416R | 8.33R | 8.06% | OK |
| AVAXUSDT | M5 | 100,000 | 68 | 22.06% | 0.660 | -19.89R | -0.292R | 22.44R | 21.20% | OK |
| AVAXUSDT | M15 | 100,000 | 30 | 26.67% | 0.870 | -3.15R | -0.105R | 12.41R | 11.84% | OK |
| LINKUSDT | M5 | 100,000 | 72 | 30.56% | 1.200 | +10.96R | +0.152R | 15.88R | 16.05% | OK |
| LINKUSDT | M15 | 100,000 | 19 | 26.32% | 0.735 | -4.03R | -0.212R | 8.51R | 8.57% | OK |
