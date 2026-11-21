# Pragma: fiyat dönüşü ve hacim aynı M5 mumunda — 24 Ekim 2026

## Karar

Deneme tamamlandı. Aynı M5 mumunda bölge+hacim teyidi istemek genel bir iyileşme sağlamadı. Ana 15 dakika ölçümünde 6 sembol iyileşti, 6 sembol kötüleşti, EURGBP'de hiç aday kalmadı. Tam strateji tekrarında işlem sayısı 64'ten 39'a düştü; işlem başına varsayımsal sonuç 5 sembolde iyileşti, 6'sında kötüleşti, 1'inde değişmedi, 1'inde işlem kalmadı. Bu şart üretime eklenmedi. Tam maliyet sonrası edge kanıtlanmadı.

## Tek değişiklik neydi?

Mevcut kararın tüm koşulları geçerli kalıyor: Z-score dönüşü/iyileşmesi, fitil veya gövde reddi, seans, rejim, mevcut maliyet kapıları. Buna ek olarak **sinyalin kapanmış M5 mumunun kendisi, aynı işlem bölgesine dokunmalı ve mevcut 20 mumluk ortalamanın en az 1,35 katı tick hacmi taşımalı**. Hacim ortalaması, özgün motorla aynı şekilde mevcut kapanmış mumu da içeriyor.

Giriş zamanı, stop, hedefler, kısmi kâr alımı ve başabaş kuralı değişmedi. Ek güçlü-gövde eşiği veya bekleme mumu eklenmedi. Z-score aşırılığının da dönüş mumunda olmasını istemedik; mevcut geçmiş aşırılık koşulu aynen korundu. Aynı yönde/türde birden fazla bölge varsa önceki araştırmanın ilk geçerli bölgesi korunuyor; başarısız bir adayı başka stoplu bölgeye taşıyarak kurtarmıyoruz.

Kurallar, kod ve girdiler sonuçlar hesaplanmadan önce donduruldu. Yalnız bu yeni şart test edildi; farklı hacim çarpanı veya 5/10 dakika tazelik taraması yapılmadı.

## 1. Gerçek arşiv bid/ask ile sabit aday karşılaştırması

118 özgün adayın 55'i tutuldu, 63'ü elendi. Tutulanların 15 dakika giriş/çıkış kotasyonu 49'unda tam, 6'sında eksik. Temel kümede 107 tam, 11 eksik kotasyon vardı. Eksikler doldurulmadı.

Aşağıdaki değerler girişten 15 dakika sonraki ortalama, spread dahil kotasyon proksisidir (bps). Komisyon/kayma/swap bütünüyle dahil değildir. Tamamlanmış stop/hedef işleminin R getirisi değildir.

| Sembol | Tutulan aday | Tam kotasyon | Temel ortalama bps | Tutulan ortalama bps |
|---|---:|---:|---:|---:|
| XAUUSD | 4 | 4 | +14,271 | +21,914 |
| EURUSD | 9 | 7 | +0,142 | +0,503 |
| GBPUSD | 6 | 5 | +0,221 | -0,728 |
| USDJPY | 4 | 3 | -4,124 | -5,463 |
| USDCHF | 8 | 7 | +2,363 | +1,964 |
| AUDUSD | 1 | 1 | -4,089 | -1,146 |
| NZDUSD | 9 | 9 | +2,304 | +2,781 |
| USDCAD | 2 | 2 | -1,393 | -0,350 |
| CADCHF | 4 | 4 | +4,341 | +3,026 |
| CADJPY | 3 | 3 | +1,204 | +0,314 |
| EURGBP | 0 | 0 | -0,516 | işlem yok |
| GBPCHF | 3 | 2 | +0,548 | +0,679 |
| GBPJPY | 2 | 2 | -1,306 | -5,604 |

Bu, farklı alt kümelerin koşullu ortalama karşılaştırmasıdır. Tutulan aynı sinyalin giriş fiyatı ve getirisi değişmiyor; eşlenmiş tek-sinyal getiri değişimi sıfır. “Filtre aynı işlemde daha iyi fiyat buldu” sonucu çıkarılmadı. EURGBP'de sıfır aday başarı sayılmadı; ortalama tanımsız bırakıldı.

Gözlenmiş ücret proksisi de mevcut üç sembolde çıkarılınca tutulanların 15 dakika ortalamaları: XAUUSD +21,720 bps (4), GBPUSD -1,031 bps (5), USDCHF +1,564 bps (7). Bunlar hâlâ kayma/swap ve gerçek fill içermeyen kısmi maliyet sonuçlarıdır.

İkincil 5 dakika ölçümünde koşullu ortalama 9 sembolde yükseldi, 3'ünde düştü. 30 dakikada 6 yükseliş, 6 düşüş var. Ana ufuk önceden 15 dakika olarak sabitlendiği için sonradan 5 dakikayı ana başarı ölçüsü seçmedik. Ayrıca ufukların eksik kotasyon kümeleri farklıdır; bu sayılar tek başına etkinin kesin sönüm süresini kanıtlamaz.

## 2. Pozisyon doluluğu dahil tüm dönem tekrar oynatıldı

Yalnız geçmişte açılmış işlemleri süzmek yeterli değildir: ilk işlemi elemek sonraki bir sinyali açılabilir hale getirebilir. Bu nedenle her sembolde önce özgün strateji baştan çalıştırıldı ve önceki 64 işlemi giriş/çıkış zamanı, seviyeler, getiri ve funnel sayılarıyla birebir üretti. Ardından yeni şart ile dönem yeniden oynatıldı.

39 yeni işlemden 4'ünün giriş adayı özgün 64 işlemde açılmamıştı: EURUSD'de 2, USDCHF ve CADCHF'de birer. Bu yüzden sonuç yalnız 64 kaydın filtrelenmiş toplamı değildir.

**Aşağıdaki sonuçlar eski sabit spread + yön başına 1 bps komisyon + 0,5 bps kayma varsayımı altındadır. Bunlar kalibre edilmiş gerçek broker net sonuçları değildir; swap eksikliği sürer. Önceki maliyet çalışmasında bazı komisyon varsayımlarının yüksek olduğu görülmüştü.** Varsayımlar bu tek giriş değişikliğini ayırabilmek için iki kolda aynı tutuldu.

| Sembol | İşlem, önce → sonra | Temel toplam senaryo R | Yeni toplam senaryo R | Temel R/işlem | Yeni R/işlem |
|---|---:|---:|---:|---:|---:|
| XAUUSD | 5 → 2 | +5,340 | +3,631 | +1,068 | +1,816 |
| EURUSD | 8 → 6 | -7,085 | -4,760 | -0,886 | -0,793 |
| GBPUSD | 7 → 4 | -5,789 | -2,357 | -0,827 | -0,589 |
| USDJPY | 7 → 4 | -4,487 | -0,951 | -0,641 | -0,238 |
| USDCHF | 7 → 6 | -1,209 | -1,552 | -0,173 | -0,259 |
| AUDUSD | 3 → 1 | -3,376 | -1,181 | -1,125 | -1,181 |
| NZDUSD | 6 → 6 | -2,941 | -2,941 | -0,490 | -0,490 |
| USDCAD | 3 → 1 | -1,923 | +0,442 | -0,641 | +0,442 |
| CADCHF | 4 → 3 | -0,226 | -1,390 | -0,057 | -0,463 |
| CADJPY | 4 → 2 | -4,617 | -2,363 | -1,154 | -1,182 |
| EURGBP | 3 → 0 | +3,785 | işlem yok | +1,262 | işlem yok |
| GBPCHF | 4 → 3 | -3,338 | -3,697 | -0,835 | -1,232 |
| GBPJPY | 3 → 1 | -0,221 | -1,221 | -0,074 | -1,221 |

Yeni şart altında iki sembolün senaryo sonucu pozitif, onunun negatif, birinin işlemi yok. USDCAD'nin pozitif sonucu yalnız bir işlemden, XAUUSD'ninki iki işlemden geliyor; bu semboller seçilip kazanan sistem diye sunulmadı. EURGBP'nin önceki pozitif üç işleminin tamamı elendi; işlem açmamak kâr etmek sayılmadı.

AUDUSD ve CADJPY, toplam zarar daha küçük görünse de işlem başına sonuçta kötüleşiyor. Bu, yalnız daha az işlem yapmanın “daha iyi giriş kalitesi” ile karıştırılmaması gerektiğini gösteriyor. Korelasyonlu sembollerin R toplamı portföy performansı diye sunulmadı.

## Sınırlar ve sonraki karar

Bütün dönem daha önce görülmüş yaklaşık bir aylık geçmişten oluşuyor; bu OOS veya yeni ileri kanıt değildir. Az işlem ve az hafta nedeniyle güven aralıkları tanımsız bırakıldı; çoklu araştırma seçiminin etkisi giderilmiş değildir. Tam net performans alanları boş kalır.

Bu şartı genel üretim kuralı yapmak için destek yok. Daha kısa süreyi ya da en iyi sembolü sonradan seçerek denemeyi başarılı ilan etmiyoruz. Yeni, bağımsız veri bu karışık sonucu kurtarmak için kullanılmadı. Başka bir giriş fikri araştırılacaksa ayrı gerekçesi ve dondurulmuş testi olmalı.

Üretim kararları ve çalışan gözlemcilerin dosyaları değiştirilmedi; gerçek emir ve bildirim gönderilmedi. Yeni kod yalnız ayrı araştırma sürecinde karar fonksiyonuna geçici bir adaptör uygular; süreç içindeki değişiklik her replay sonunda geri alınır.

## Doğrulama ve tekrar üretim

```powershell
python scripts/run_synchronized_entry_study.py --baseline reports/broker_measurement_v2_2026-10-24 --entry-study reports/entry_cost_calibration_2026-10-24 --timing-audit reports/entry_timing_audit_v3_2026-10-24 --output reports/synchronized_entry_YENI_DIZIN
python -m pytest -q
```

- Sonuç dizini: `reports/synchronized_entry_v2_2026-10-24`.
- Protokol SHA256: `017f85460916678f4d69ccf8b78545679c842ae66c65a91aece8f132a27970c3`.
- 58 kaynak ve dondurulmuş kopyasının hashleri doğrulandı.
- Özgün 64 işlem ve 118 adayın seçim kararı doğrulandı; yeni şarttaki 39 giriş ayrıca bağımsız kapalı-geçmiş değerlendiricisiyle, aynı bölge/stop/TP1/TP2 ve sonraki dakika maliyetli açılışıyla sınandı.
- Tutulan 49 tam ana-ufuk kotasyonunun getirisi ham giriş/çıkış bid/ask değerlerinden tekrar hesaplandı.
- 202 test ve 50 alt test geçti; derleme ve `git diff --check` başarılı. Eski shadow testinde yalnız satır sonu uyarısı mevcut.
- Yeni testler eski hacim olayının tek başına geçememesini, aynı sinyalin başka bölgeye kaydırılmamasını, stop/hedeflerin korunmasını, eksik kotasyonları ve sıfır işlemin tanımsız performansını kapsıyor.
- İlk çalışmada sonsuz profit-factor değerinin JSON'a yazımı durdu; `INCOMPLETE` çıktısı korundu. Yalnız raporlama normalizasyonu düzeltildi (sonsuz oran → null); yeni dizinde deney aynı kuralla tekrarlandı. İlk ve ikinci çalışmanın sabit-aday seçimleri ve kotasyon sonuçları dosya düzeyinde birebir aynı.

Çıktılar: [karar](synchronized_entry_v2_2026-10-24/decision.json), [protokol](synchronized_entry_v2_2026-10-24/protocol_frozen.json), [kotasyon özeti](synchronized_entry_v2_2026-10-24/quote_summary.json), [tam replay özeti](synchronized_entry_v2_2026-10-24/replay_summary.json), [doğrulama](synchronized_entry_v2_2026-10-24/verification.json).
