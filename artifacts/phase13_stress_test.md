# FAZ 13 — AUDIT FIXES, CRYPTO FILTERS & 300K M1 STRESS TEST RAPORU

## 1. Yönetici Özeti ve Metrikler

- **Veri Havuzu:** 300.000 kapalı M1 bar (208.33 takvim günü: 22 Mart 2026 - 16 Ekim 2026)
- **Maliyet Modeli:** Dinamik 4 bps giriş + 4 bps çıkış (8 bps round-trip) + 8 saatlik periyotlarda %0.01 fonlama kesintisi
- **Filtreler:** Aktif İşlem Saatleri (08:00 - 22:00 UTC), Hafta Sonu & Düşük Hacimli Gün Vetosu, BTC Lider Bear Şartı, 0.35x ATR VWAP Ayrışması, Kesin Negatif Delta (Short)

## 2. 300.000 M1 Stres Testi Matrisi (15 Koşu)

| Dönem | Sembol | TF | Trade | Net PnL (R) | PF | WinRate | MaxDD (R) | Exp (R) | Std R | t-stat | %95 CI (R) | Fonlama (R) |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Period 1: First 200k (Historical Earlier) | `SOLUSDT` | `M5` | 22 | **-14.41** | 0.321 | 13.6% | 17.44 | -0.655 | 1.21 | -2.54 | [-1.16, -0.15] | 0.143R |
| Period 1: First 200k (Historical Earlier) | `SOLUSDT` | `M15` | 24 | **-11.48** | 0.500 | 16.7% | 17.74 | -0.478 | 1.57 | -1.50 | [-1.10, +0.15] | 0.118R |
| Period 1: First 200k (Historical Earlier) | `LINKUSDT` | `M5` | 15 | **-12.53** | 0.134 | 13.3% | 12.53 | -0.835 | 0.75 | -4.33 | [-1.21, -0.46] | 0.099R |
| Period 1: First 200k (Historical Earlier) | `LINKUSDT` | `M15` | 15 | **-11.31** | 0.243 | 13.3% | 14.94 | -0.754 | 1.05 | -2.78 | [-1.29, -0.22] | 0.088R |
| Period 1: First 200k (Historical Earlier) | `BTCUSDT` | `M15` | 24 | **-2.72** | 0.854 | 33.3% | 11.23 | -0.113 | 1.65 | -0.34 | [-0.77, +0.55] | 0.182R |
| Period 2: Last 100k (Recent IS) | `SOLUSDT` | `M5` | 11 | **-0.86** | 0.887 | 36.4% | 4.30 | -0.078 | 1.44 | -0.18 | [-0.93, +0.77] | 0.039R |
| Period 2: Last 100k (Recent IS) | `SOLUSDT` | `M15` | 9 | **-6.55** | 0.252 | 11.1% | 7.63 | -0.727 | 1.10 | -1.98 | [-1.45, -0.01] | 0.044R |
| Period 2: Last 100k (Recent IS) | `LINKUSDT` | `M5` | 5 | **+5.05** | 3.376 | 60.0% | 1.07 | +1.010 | 2.05 | 1.10 | [-0.78, +2.80] | 0.009R |
| Period 2: Last 100k (Recent IS) | `LINKUSDT` | `M15` | 5 | **-0.32** | 0.901 | 40.0% | 3.26 | -0.064 | 1.51 | -0.10 | [-1.39, +1.26] | 0.004R |
| Period 2: Last 100k (Recent IS) | `BTCUSDT` | `M15` | 4 | **+4.62** | 5.391 | 75.0% | 1.05 | +1.156 | 1.51 | 1.53 | [-0.32, +2.63] | 0.000R |
| Period 3: Combined 300k (Full Sample) | `SOLUSDT` | `M5` | 33 | **-15.27** | 0.470 | 21.2% | 17.44 | -0.463 | 1.30 | -2.05 | [-0.91, -0.02] | 0.183R |
| Period 3: Combined 300k (Full Sample) | `SOLUSDT` | `M15` | 33 | **-18.03** | 0.432 | 15.2% | 19.96 | -0.546 | 1.44 | -2.18 | [-1.04, -0.05] | 0.162R |
| Period 3: Combined 300k (Full Sample) | `LINKUSDT` | `M5` | 20 | **-7.48** | 0.550 | 25.0% | 12.53 | -0.374 | 1.40 | -1.19 | [-0.99, +0.24] | 0.108R |
| Period 3: Combined 300k (Full Sample) | `LINKUSDT` | `M15` | 20 | **-11.63** | 0.361 | 20.0% | 14.94 | -0.582 | 1.18 | -2.21 | [-1.10, -0.07] | 0.093R |
| Period 3: Combined 300k (Full Sample) | `BTCUSDT` | `M15` | 28 | **+1.90** | 1.097 | 39.3% | 11.23 | +0.068 | 1.67 | 0.22 | [-0.55, +0.69] | 0.182R |

## 3. Long vs Short Ayrımı (Combined 300k)

| Sembol | TF | Long Trades | Long Net R | Long PF | Long WR | Short Trades | Short Net R | Short PF | Short WR |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `SOLUSDT` | `M5` | 21 | -16.95R | 0.191 | 9.5% | 12 | +1.68R | 1.214 | 41.7% |
| `SOLUSDT` | `M15` | 16 | -10.35R | 0.371 | 12.5% | 17 | -7.67R | 0.497 | 17.6% |
| `LINKUSDT` | `M5` | 16 | -3.01R | 0.752 | 31.2% | 4 | -4.47R | 0.000 | 0.0% |
| `LINKUSDT` | `M15` | 12 | -5.51R | 0.458 | 25.0% | 8 | -6.13R | 0.239 | 12.5% |
| `BTCUSDT` | `M15` | 16 | -0.02R | 0.998 | 43.8% | 12 | +1.92R | 1.208 | 33.3% |

## 4. FAZ 12 (Baseline) vs FAZ 13 Karşılaştırması (Combined 300k)

| Sembol | TF | FAZ 12 Net R | FAZ 13 Net R | FAZ 12 Trades | FAZ 13 Trades | FAZ 12 PF | FAZ 13 PF | FAZ 12 MaxDD | FAZ 13 MaxDD | Net R Değişimi | Karar |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `SOLUSDT` | `M5` | -11.39R | **-15.27R** | 71 | 33 | 0.794 | 0.470 | 15.30R | 17.44R | **-3.88R** | STABILIZED |
| `SOLUSDT` | `M15` | -10.56R | **-18.03R** | 62 | 33 | 0.793 | 0.432 | 16.18R | 19.96R | **-7.47R** | STABILIZED |
| `LINKUSDT` | `M5` | -26.14R | **-7.48R** | 51 | 20 | 0.415 | 0.550 | 29.28R | 12.53R | **+18.66R** | IMPROVED |
| `LINKUSDT` | `M15` | -11.11R | **-11.63R** | 39 | 20 | 0.651 | 0.361 | 13.24R | 14.94R | **-0.52R** | STABILIZED |
| `BTCUSDT` | `M15` | -7.92R | **+1.90R** | 54 | 28 | 0.809 | 1.097 | 9.92R | 11.23R | **+9.82R** | IMPROVED |

## 5. Huni Tanıları (Funnel Diagnostics — Combined 300k)

### `SOLUSDT` `M5`
```json
{
  "sessions_evaluated": 207,
  "bars_with_active_poi": 3116,
  "bars_touched_poi": 1628,
  "passed_zscore": 172,
  "passed_volume": 89,
  "passed_rejection": 59,
  "rejected_low_rr": 4,
  "rejected_session_hours": 1803,
  "rejected_low_volume_day": 20047,
  "rejected_high_spread_to_sl": 0,
  "trades_opened": 33
}
```

### `SOLUSDT` `M15`
```json
{
  "sessions_evaluated": 207,
  "bars_with_active_poi": 3116,
  "bars_touched_poi": 1855,
  "passed_zscore": 166,
  "passed_volume": 71,
  "passed_rejection": 55,
  "rejected_low_rr": 5,
  "rejected_session_hours": 1803,
  "rejected_low_volume_day": 6683,
  "rejected_high_spread_to_sl": 0,
  "trades_opened": 33
}
```

### `LINKUSDT` `M5`
```json
{
  "sessions_evaluated": 207,
  "bars_with_active_poi": 2840,
  "bars_touched_poi": 1305,
  "passed_zscore": 147,
  "passed_volume": 62,
  "passed_rejection": 41,
  "rejected_low_rr": 2,
  "rejected_session_hours": 1592,
  "rejected_low_volume_day": 20623,
  "rejected_high_spread_to_sl": 0,
  "trades_opened": 20
}
```

### `LINKUSDT` `M15`
```json
{
  "sessions_evaluated": 207,
  "bars_with_active_poi": 2840,
  "bars_touched_poi": 1544,
  "passed_zscore": 126,
  "passed_volume": 63,
  "passed_rejection": 41,
  "rejected_low_rr": 7,
  "rejected_session_hours": 1592,
  "rejected_low_volume_day": 6875,
  "rejected_high_spread_to_sl": 0,
  "trades_opened": 20
}
```

### `BTCUSDT` `M15`
```json
{
  "sessions_evaluated": 207,
  "bars_with_active_poi": 4183,
  "bars_touched_poi": 2306,
  "passed_zscore": 177,
  "passed_volume": 85,
  "passed_rejection": 71,
  "rejected_low_rr": 21,
  "rejected_session_hours": 2595,
  "rejected_low_volume_day": 7835,
  "rejected_high_spread_to_sl": 0,
  "trades_opened": 28
}
```

