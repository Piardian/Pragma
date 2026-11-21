# PRAGMA — Gölge İşlem (Shadow) & Makro Kapı Benchmark Raporu

- **Son Güncelleme (UTC):** `2026-11-09T17:47:16.798269+00:00`
- **Veri Kaynağı:** `C:\Users\piard\AppData\Local\Pragma\shadow_trading`
- **Kaydedilen Makro Kapı (`macro_bias_gate.json`) Snapshot Sayısı:** `1`

## 1. Genel Performans ve 5'li Benchmark Özeti

| Kategori / Metrik | Değer | Açıklama |
| :--- | :---: | :--- |
| **Kapanan Gölge İşlem** | `12` | Tamamlanan sanal işlemler |
| **1. Başarılı Girişler (`successful_entries`)** | `4` | Pozitif R ile kapanan işlemler |
| **2. Hatalı Girişler (`false_entries`)** | `8` | SL / negatif R ile kapanan işlemler + hata teşhisi |
| **3. Doğru Redler (`correct_rejections`)** | `489` | Filtrelerin doğru şekilde engellediği zayıf sinyaller |
| **4. Kaçan Fırsatlar (`missed_opportunities`)** | `30` | Yüksek RR ve güçlü Z-Score'a rağmen elenen sinyaller |
| **5. Açık Gölge İşlemler (`pending_Shadow`)** | `0` | Şu an açık takip edilen sanal işlemler |
| **Kazanma Oranı (Win Rate)** | `%33.3` | Pozitif kapanış oranı |
| **Toplam Net R** | `-2.78R` | Kümülatif R getirisi |
| **Toplam Net PnL** | `-282.13 USD` | 10,000 USD başlangıç bakiyesi üzerinden net fark |

## 2. Reddedilen Sinyallerin (`rejected_signals`) Neden Dağılımı

| Red Nedeni | Adet |
| :--- | :---: |
| `Z_SCORE_NOT_CONFIRMED` | `364` |
| `SESSION_HOURS` | `101` |
| `VOLUME_CLIMAX_NOT_CONFIRMED` | `49` |
| `REJECTION_NOT_CONFIRMED` | `2` |
| `LEVEL_RECLAIM_NOT_CONFIRMED` | `2` |
| `LOW_RR` | `1` |

## 3. Hatalı Girişler (`false_entries`) ve Geriye Dönük Hata Teşhisi

| Tarih | Sembol | Yön | Sonuç | Net R | MAE / MFE (R) | Makro Uyum | Hata Teşhisi |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `2026-10-19T17:59` | **BTCUSD** | `LONG` | `SL` | `-1.00R` | `0.00R / 0.00R` | `ALIGNED` | IMMEDIATE_ADVERSE_SELECTION (Fiyat girişten sonra +0.25R bile lehimize gitmeden SL oldu) |
| `2026-10-19T15:49` | **USDCHF** | `SHORT` | `SL` | `-1.00R` | `0.00R / 0.00R` | `ALIGNED` | IMMEDIATE_ADVERSE_SELECTION (Fiyat girişten sonra +0.25R bile lehimize gitmeden SL oldu); LOW_PLANNED_RR (Planlanan RR=1.12 düşük) |
| `2026-10-19T16:04` | **EURJPY** | `SHORT` | `SL` | `-1.00R` | `0.00R / 0.00R` | `ALIGNED` | IMMEDIATE_ADVERSE_SELECTION (Fiyat girişten sonra +0.25R bile lehimize gitmeden SL oldu) |
| `2026-11-03T06:04` | **CADJPY** | `SHORT` | `SL` | `-1.00R` | `1.08R / 0.53R` | `ALIGNED` | LOW_PLANNED_RR (Planlanan RR=1.07 düşük) |
| `2026-11-05T12:14` | **USDCHF** | `SHORT` | `SL` | `-1.00R` | `1.07R / 0.66R` | `ALIGNED` | LOW_PLANNED_RR (Planlanan RR=1.14 düşük) |
| `2026-11-05T06:09` | **XAUUSD** | `LONG` | `SL` | `-1.00R` | `1.12R / 1.07R` | `ALIGNED` | REVERSAL_BEFORE_TP1 (Fiyat +1.07R kâra kadar gidip TP1 alamadan geri döndü) |
| `2026-11-05T14:54` | **XAUUSD** | `LONG` | `SL` | `-1.00R` | `1.18R / 1.74R` | `ALIGNED` | REVERSAL_BEFORE_TP1 (Fiyat +1.74R kâra kadar gidip TP1 alamadan geri döndü) |
| `2026-11-09T14:54` | **USDJPY** | `SHORT` | `SL` | `-1.00R` | `1.08R / 0.19R` | `ALIGNED` | IMMEDIATE_ADVERSE_SELECTION (Fiyat girişten sonra +0.25R bile lehimize gitmeden SL oldu) |

## 4. Başarılı Girişler (`successful_entries`)

| Tarih | Sembol | Yön | Sonuç | Net R | Net PnL | MAE / MFE (R) | Makro Uyum |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `2026-10-19T08:39` | **GBPCHF** | `SHORT` | `TP2` | `+1.97R` | `+197.42 USD` | `0.00R / 0.00R` | `ALIGNED` |
| `2026-11-03T12:49` | **USDCHF** | `SHORT` | `BE` | `+0.63R` | `+61.76 USD` | `0.16R / 1.43R` | `ALIGNED` |
| `2026-11-04T10:39` | **GBPCHF** | `SHORT` | `BE` | `+0.54R` | `+53.03 USD` | `0.37R / 1.83R` | `ALIGNED` |
| `2026-11-05T12:14` | **GBPCHF** | `SHORT` | `TP2` | `+2.08R` | `+205.78 USD` | `0.57R / 2.80R` | `ALIGNED` |

## 5. Potansiyel Kaçan Fırsatlar (`missed_opportunities` — Örneklem)

| Tarih | Sembol | Yön | Red Nedeni | Planlanan RR | Z-Score | Makro Uyum |
| :--- | :---: | :---: | :--- | :---: | :---: | :---: |
| `2026-11-05T12:24` | **GBPCHF** | `SHORT` | `Z_SCORE_NOT_CONFIRMED` | `2.76` | `+2.11` | `ALIGNED` |
| `2026-11-05T12:29` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `3.19` | `-2.00` | `ALIGNED` |
| `2026-11-05T12:34` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `6.29` | `-2.27` | `ALIGNED` |
| `2026-11-05T12:39` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `7.12` | `-2.01` | `ALIGNED` |
| `2026-11-05T14:49` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `14.68` | `-2.11` | `ALIGNED` |
| `2026-11-05T14:59` | **AUDUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `2.12` | `-2.14` | `ALIGNED` |
| `2026-11-05T18:04` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `4.73` | `-2.04` | `ALIGNED` |
| `2026-11-05T19:44` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `4.45` | `+3.44` | `ALIGNED` |
| `2026-11-05T19:49` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `3.52` | `+2.79` | `ALIGNED` |
| `2026-11-05T19:54` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `3.11` | `+2.36` | `ALIGNED` |
| `2026-11-09T11:34` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `3.91` | `+2.31` | `ALIGNED` |
| `2026-11-09T14:44` | **USDJPY** | `SHORT` | `Z_SCORE_NOT_CONFIRMED` | `2.37` | `+2.67` | `ALIGNED` |
| `2026-11-09T14:49` | **USDJPY** | `SHORT` | `Z_SCORE_NOT_CONFIRMED` | `4.04` | `+2.49` | `ALIGNED` |
| `2026-11-09T16:49` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `3.80` | `-2.24` | `ALIGNED` |
| `2026-11-09T16:54` | **XAUUSD** | `LONG` | `Z_SCORE_NOT_CONFIRMED` | `10.05` | `-2.45` | `ALIGNED` |
