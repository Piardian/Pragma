# Pragma: kayıp tanısı ve tek çıkış denemesi — 24 Ekim 2026

Pragma'yı kazanan bir sisteme dönüştürdüğümüzü söyleyemiyoruz. Bu turda yalnız beklemek yerine, kaybı azaltmak için somut bir çıkış kuralını test ettik: 15 dakika sonunda açık kalan işlemi kapatmak. 13 sembolün 10'unda sonuç iyileşti, üçünde kötüleşti. Yeni kuralda 11 sembol hâlâ negatif. Genel kullanıma alınmadı.

## Önce kaybı ayırdık

Önceki gerçek tarihsel bid/ask çalışmasının temel adayları, önceden belirlenmiş 15 dakika ufkunda tekrar ayrıştırıldı. 118 adayın 107'sinde giriş/çıkış kotasyonu tam, 11'inde eksik. Aynı tam örneklerde:

- USDJPY, AUDUSD, USDCAD ve GBPJPY ortalamaları spread/komisyon/kayma çıkarılmadan önce de negatif. Bu gözlem, bütün sorunun işlem masrafları olduğu açıklamasını desteklemiyor.
- EURGBP'nin küçük pozitif brüt ortalaması spread sonrası negatife dönüyor. Diğer dört negatif sembolle birlikte spread sonrası beş negatif sembol var.
- Bazı sembollerde kısa ufuk olumlu iken eski tamamlanmış işlem senaryosu negatif. Ancak bütün adaylarla pozisyon doluluğundan sonra açılan işlemler farklı örneklerdir; bu fark tek başına çıkışların kayba neden olduğunu kanıtlamaz. Bu yüzden çıkış denemesini aynı işlem girişlerinde eşledik.
- Önceki 64 kapanmış işlemin 45'i ilk kâr alımı gerçekleşmeden stop oldu. Bu oran tek başına sistemin kârlı/kârsız olduğunu kanıtlamaz; sadece sorunun yalnız kâr aldıktan sonraki başabaş stopunda aranamayacağını gösterir.

Komisyon örneği yetersiz olan sembollere sıfır ücret yazılmadı. Kayma ve varsayımsal swap eksikliği devam ediyor. Bütün maliyetlerden sonraki gerçek net getiri hesaplanmış değildir.

## Tek değişiklik: azami 15 dakika

15 dakika, önceki giriş çalışmasının zaten ana ölçüm ufkuydu. Yeni bir süre taraması yapılmadı. Sonuçlar hesaplanmadan önce kod, girdiler, kurallar ve maliyet kapsamı donduruldu.

- Aynı 64 özgün giriş, aynı giriş fiyatı, stop, hedefler, yarım kâr alımı ve başabaş davranışı.
- İlk 15 dakikada mevcut stop/hedef ile kapanırsa özgün çıkış korunuyor.
- Hâlâ açıksa 15. dakikanın açılışında kalan pozisyon kapanıyor. O mumun daha sonra oluşacak tepe/dibi/kapanışı kullanılmıyor.
- Eksik dakika ya da eksik çıkış açılışı tahminle doldurulmuyor. Bu çalışmada 64 eşlemenin tamamı mevcut.
- Karşılaştırma, önceki sabit spread + yön başına 1 bps komisyon + 0,5 bps kayma varsayımını aynen koruyor. Özellikle komisyon varsayımının bazı sembollerde yüksek olduğunu önceki gerçek hesap örnekleri gösterdi. Aşağıdaki R değerleri bu nedenle **aynı varsayım altında çıkış karşılaştırmasıdır; gerçek broker net kazancı değildir.**

| Sembol | İşlem | Özgün senaryo R | 15 dk sınırı R | Fark R |
|---|---:|---:|---:|---:|
| XAUUSD | 5 | +5,340 | +3,377 | -1,963 |
| EURUSD | 8 | -7,085 | -2,611 | +4,475 |
| GBPUSD | 7 | -5,789 | -3,107 | +2,683 |
| USDJPY | 7 | -4,487 | -4,379 | +0,108 |
| USDCHF | 7 | -1,209 | -0,154 | +1,055 |
| AUDUSD | 3 | -3,376 | -1,379 | +1,996 |
| NZDUSD | 6 | -2,941 | -0,663 | +2,278 |
| USDCAD | 3 | -1,923 | -0,878 | +1,045 |
| CADCHF | 4 | -0,226 | +0,094 | +0,320 |
| CADJPY | 4 | -4,617 | -0,992 | +3,624 |
| EURGBP | 3 | +3,785 | -1,819 | -5,604 |
| GBPCHF | 4 | -3,338 | -0,860 | +2,478 |
| GBPJPY | 3 | -0,221 | -0,823 | -0,602 |

59 işlem süre sınırında kapandı; beş erken çıkış özgün haliyle kaldı. 15 dakika sınırı, özgün testte pozitif olan XAUUSD ve EURGBP'nin ikisinde de getiriyi azalttı. Her pariteye uygulanan başarılı bir çözüm bulunmadı. CADCHF'nin dört işlemlik +0,094R sonucu sembol seçme gerekçesi yapılmadı.

Bu, daha erken boşalan pozisyonla açılabilecek yeni işlemleri içeren tam strateji testi değildir; sabit girişlerin karşı-olgusal çıkış karşılaştırmasıdır. Korelasyonlu sembollerin R toplamı portföy performansı diye sunulmadı. Kullanılan yaklaşık bir aylık geçmiş önceden görülmüştür; sonuç OOS/ileri kanıt değildir.

## Karar

15 dakika çıkışı genel stratejiye eklenmeyecek. Bu veride 10/13 iyileşmeyi başarı sayıp yeni süreler taramak için gerekçe yapmayacağız. Girişin maliyet öncesi yön avantajı ile hedef/stop yapısının uyumu birlikte çözülmeden, sadece bu çıkış değişikliğiyle kazanan bir sistem elde edilemiyor. Yeni bir giriş/çıkış hipotezi seçilecekse ayrı gerekçesi ve önceden belirlenmiş testi olmalı; henüz bu denemeden seçilmiş, bağımsız doğrulamaya hazır bir kazanan aday yok.

Üretim kararları, çalışan gözlemcilerin kodu ve emir davranışı değiştirilmedi. Gerçek işlem açılmadı. Yeni bağımsız veri bu başarısız adayı kurtarmak için tüketilmedi.

## Tekrar üretim ve doğrulama

```powershell
python scripts/run_exit_cap_study.py --baseline reports/broker_measurement_v2_2026-10-24 --entry-study reports/entry_cost_calibration_2026-10-24 --output reports/exit_cap_15m_YENI_DIZIN
python -m pytest -q
```

- Protokol SHA256: `959daebc6f203b3c7c666ec360971541027037ba384980f92e6b9a6ccfbe5ea4`.
- 57 kaynak ve dondurulmuş kopyasının hashleri doğrulandı.
- Özgün motor, 64 işlemin getirisini, çıkış gerekçesini ve çıkış zamanını birebir yeniden üretti.
- 59 süre çıkışının fiyat/maliyet/R hesabı bağımsız skaler formülle tekrar doğrulandı; beş erken çıkışın özgün kayıtla eşitliği kontrol edildi.
- 184 test ve 50 alt test geçti. Derleme ve `git diff --check` başarılı; eski `test_shadow_trader.py` için yalnız satır sonu uyarısı mevcut.
- Yeni testler süre mumunun gelecekteki tepe/dibini kullanmama, ters yön, stop önceliği, kötü açılış, kısmi pozisyon maliyeti ve eksik veri durumlarını kapsıyor.

Çıktılar: [protokol](exit_cap_15m_2026-10-24/protocol_frozen.json), [özet](exit_cap_15m_2026-10-24/summary.json), [işlem eşlemeleri](exit_cap_15m_2026-10-24/trades.json), [karar](exit_cap_15m_2026-10-24/decision.json), [doğrulama](exit_cap_15m_2026-10-24/verification.json).
