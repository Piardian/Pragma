# FAZ 13 — AUDIT FIXES, CRYPTO FILTERS & 300K M1 STRESS TEST RAPORU

## 1. Yönetici Özeti ve Metrikler

- **Veri Havuzu:** 300.000 kapalı M1 bar (208.33 takvim günü: 22 Mart 2026 - 16 Ekim 2026)
- **Maliyet Modeli:** Dinamik 4 bps giriş + 4 bps çıkış (8 bps round-trip) + 8 saatlik periyotlarda %0.01 fonlama kesintisi
- **Filtreler:** Aktif İşlem Saatleri (08:00 - 22:00 UTC), Hafta Sonu & Düşük Hacimli Gün Vetosu, BTC Lider Bear Şartı, 0.35x ATR VWAP Ayrışması, Kesin Negatif Delta (Short)

## 2. 300.000 M1 Stres Testi Matrisi (15 Koşu)

| Dönem | Sembol | TF | Trade | Net PnL (R) | PF | WinRate | MaxDD (R) | Exp (R) | Std R | t-stat | %95 CI (R) | Fonlama (R) |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Period 1: First 200k (Historical Earlier) | `SOLUSDT` | `M5` | 28 | **-10.58** | 0.588 | 17.9% | 16.09 | -0.378 | 1.71 | -1.17 | [-1.01, +0.26] | 0.143R |
| Period 1: First 200k (Historical Earlier) | `SOLUSDT` | `M15` | 29 | **+1.01** | 1.044 | 31.0% | 10.16 | +0.035 | 1.86 | 0.10 | [-0.64, +0.71] | 0.118R |
| Period 1: First 200k (Historical Earlier) | `LINKUSDT` | `M5` | 20 | **-15.44** | 0.178 | 15.0% | 15.44 | -0.772 | 0.83 | -4.18 | [-1.13, -0.41] | 0.113R |
| Period 1: First 200k (Historical Earlier) | `LINKUSDT` | `M15` | 21 | **-11.96** | 0.380 | 19.1% | 15.59 | -0.569 | 1.21 | -2.17 | [-1.08, -0.05] | 0.113R |
| Period 1: First 200k (Historical Earlier) | `BTCUSDT` | `M15` | 24 | **-2.79** | 0.851 | 33.3% | 11.30 | -0.116 | 1.66 | -0.34 | [-0.78, +0.55] | 0.182R |
| Period 2: Last 100k (Recent IS) | `SOLUSDT` | `M5` | 11 | **-0.86** | 0.887 | 36.4% | 4.30 | -0.078 | 1.44 | -0.18 | [-0.93, +0.77] | 0.039R |
| Period 2: Last 100k (Recent IS) | `SOLUSDT` | `M15` | 9 | **-6.55** | 0.252 | 11.1% | 7.63 | -0.727 | 1.10 | -1.98 | [-1.45, -0.01] | 0.044R |
| Period 2: Last 100k (Recent IS) | `LINKUSDT` | `M5` | 6 | **+7.50** | 4.526 | 66.7% | 1.07 | +1.249 | 1.92 | 1.59 | [-0.29, +2.79] | 0.020R |
| Period 2: Last 100k (Recent IS) | `LINKUSDT` | `M15` | 6 | **+4.56** | 2.398 | 50.0% | 3.26 | +0.761 | 2.30 | 0.81 | [-1.08, +2.60] | 0.031R |
| Period 2: Last 100k (Recent IS) | `BTCUSDT` | `M15` | 4 | **+4.62** | 5.391 | 75.0% | 1.05 | +1.156 | 1.51 | 1.53 | [-0.32, +2.63] | 0.000R |
| Period 3: Combined 300k (Full Sample) | `SOLUSDT` | `M5` | 39 | **-11.44** | 0.656 | 23.1% | 16.09 | -0.293 | 1.63 | -1.12 | [-0.80, +0.22] | 0.183R |
| Period 3: Combined 300k (Full Sample) | `SOLUSDT` | `M15` | 38 | **-5.54** | 0.826 | 26.3% | 10.16 | -0.146 | 1.73 | -0.52 | [-0.70, +0.40] | 0.162R |
| Period 3: Combined 300k (Full Sample) | `LINKUSDT` | `M5` | 26 | **-7.95** | 0.620 | 26.9% | 15.44 | -0.306 | 1.42 | -1.10 | [-0.85, +0.24] | 0.133R |
| Period 3: Combined 300k (Full Sample) | `LINKUSDT` | `M15` | 27 | **-7.39** | 0.672 | 25.9% | 15.59 | -0.274 | 1.57 | -0.91 | [-0.86, +0.32] | 0.143R |
| Period 3: Combined 300k (Full Sample) | `BTCUSDT` | `M15` | 28 | **+1.83** | 1.093 | 39.3% | 11.30 | +0.065 | 1.67 | 0.21 | [-0.55, +0.68] | 0.182R |

## 3. Long vs Short Ayrımı (Combined 300k)

| Sembol | TF | Long Trades | Long Net R | Long PF | Long WR | Short Trades | Short Net R | Short PF | Short WR |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `SOLUSDT` | `M5` | 27 | -13.12R | 0.483 | 14.8% | 12 | +1.68R | 1.214 | 41.7% |
| `SOLUSDT` | `M15` | 21 | +2.14R | 1.130 | 33.3% | 17 | -7.67R | 0.497 | 17.6% |
| `LINKUSDT` | `M5` | 22 | -3.48R | 0.788 | 31.8% | 4 | -4.47R | 0.000 | 0.0% |
| `LINKUSDT` | `M15` | 19 | -1.27R | 0.913 | 31.6% | 8 | -6.13R | 0.239 | 12.5% |
| `BTCUSDT` | `M15` | 16 | -0.09R | 0.991 | 43.8% | 12 | +1.92R | 1.208 | 33.3% |

## 4. FAZ 12 (Baseline) vs FAZ 13 Karşılaştırması (Combined 300k)

| Sembol | TF | FAZ 12 Net R | FAZ 13 Net R | FAZ 12 Trades | FAZ 13 Trades | FAZ 12 PF | FAZ 13 PF | FAZ 12 MaxDD | FAZ 13 MaxDD | Net R Değişimi | Karar |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `SOLUSDT` | `M5` | -9.18R | **-11.44R** | 85 | 39 | 0.862 | 0.656 | 15.16R | 16.09R | **-2.26R** | STABILIZED |
| `SOLUSDT` | `M15` | +2.81R | **-5.54R** | 72 | 38 | 1.051 | 0.826 | 9.71R | 10.16R | **-8.35R** | STABILIZED |
| `LINKUSDT` | `M5` | -32.24R | **-7.95R** | 68 | 26 | 0.458 | 0.620 | 40.21R | 15.44R | **+24.29R** | IMPROVED |
| `LINKUSDT` | `M15` | -14.50R | **-7.39R** | 50 | 27 | 0.655 | 0.672 | 17.64R | 15.59R | **+7.11R** | IMPROVED |
| `BTCUSDT` | `M15` | -8.00R | **+1.83R** | 54 | 28 | 0.808 | 1.093 | 10.00R | 11.30R | **+9.83R** | IMPROVED |

## 5. Huni Tanıları (Funnel Diagnostics — Combined 300k)

### `SOLUSDT` `M5`
```json
{
  "sessions_evaluated": 207,
  "bars_with_active_poi": 8464,
  "bars_touched_poi": 4631,
  "passed_zscore": 519,
  "passed_volume": 266,
  "passed_rejection": 197,
  "rejected_low_rr": 15,
  "rejected_session_hours": 5509,
  "rejected_low_volume_day": 20047,
  "rejected_high_spread_to_sl": 0,
  "trades_opened": 39
}
```

### `SOLUSDT` `M15`
```json
{
  "sessions_evaluated": 207,
  "bars_with_active_poi": 3814,
  "bars_touched_poi": 2302,
  "passed_zscore": 206,
  "passed_volume": 94,
  "passed_rejection": 78,
  "rejected_low_rr": 12,
  "rejected_session_hours": 2338,
  "rejected_low_volume_day": 6683,
  "rejected_high_spread_to_sl": 0,
  "trades_opened": 38
}
```

### `LINKUSDT` `M5`
```json
{
  "sessions_evaluated": 207,
  "bars_with_active_poi": 9075,
  "bars_touched_poi": 4757,
  "passed_zscore": 560,
  "passed_volume": 234,
  "passed_rejection": 168,
  "rejected_low_rr": 11,
  "rejected_session_hours": 5560,
  "rejected_low_volume_day": 20623,
  "rejected_high_spread_to_sl": 0,
  "trades_opened": 26
}
```

### `LINKUSDT` `M15`
```json
{
  "sessions_evaluated": 207,
  "bars_with_active_poi": 3908,
  "bars_touched_poi": 2301,
  "passed_zscore": 193,
  "passed_volume": 94,
  "passed_rejection": 66,
  "rejected_low_rr": 18,
  "rejected_session_hours": 2296,
  "rejected_low_volume_day": 6875,
  "rejected_high_spread_to_sl": 0,
  "trades_opened": 27
}
```

### `BTCUSDT` `M15`
```json
{
  "sessions_evaluated": 207,
  "bars_with_active_poi": 4214,
  "bars_touched_poi": 2328,
  "passed_zscore": 177,
  "passed_volume": 85,
  "passed_rejection": 74,
  "rejected_low_rr": 22,
  "rejected_session_hours": 2602,
  "rejected_low_volume_day": 7835,
  "rejected_high_spread_to_sl": 0,
  "trades_opened": 28
}
```

