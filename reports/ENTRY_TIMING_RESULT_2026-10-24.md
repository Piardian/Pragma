# Pragma giriş zamanlaması — 24 Ekim 2026

## Sonuç

“Pragma her zaman hareket bittikten sonra giriyor” açıklaması doğrulanmadı. Sembole ve giriş türüne göre farklı davranış var. İncelemede iki ayrı konu öne çıktı: fiyat/hacim/Z-score koşullarının farklı mumlardan birleştirilmesi ve bazı doğru yönlü başlangıçların işlem sonunda eski maliyet senaryosuyla zarara dönmesi. Bunlar araştırılabilir nedenlerdir; bu tanıdan kârlı bir yeni kural çıkmış değildir.

13 sembolde 118 benzersiz sinyal adayı yeniden oluşturuldu. Bunların 107'sinde 15 dakika sonrası kotasyon tam, 11'inde eksik. Ayrıca önceki testte açılan 64 işlem, aynı giriş adaylarına ve stop/hedef seviyelerine birebir eşlendi. Bu 118 aday pozisyon doluluğundan önceki kümedir; 118 gerçek broker işlemi değildir.

## 1. Her sembolde aynı şekilde geç kalmıyoruz

Girişten önceki 15 dakika hareketi, yalnız karar anından önce kapanmış M1 mumlarından hesaplandı. Artı değer, hareketin önerilen işlem yönünde olduğunu belirtir. Girişten sonraki 15 dakika hareketi, arşivdeki gerçek bid/ask kotasyonlarının orta fiyatından ölçüldü. Aşağıdaki iki sütun her sembolde aynı kotasyonu tam adayları kullanır; önceki hareket medyan, sonraki hareket ortalamadır. Bunlar brüt fiyat hareketleridir, net işlem getirisi değildir.

| Sembol | Tam aday | Önceki 15 dk, medyan bps | Sonraki 15 dk, ortalama bps |
|---|---:|---:|---:|
| XAUUSD | 8 | +15,66 | +15,57 |
| EURUSD | 14 | -0,18 | +0,14 |
| GBPUSD | 12 | +0,95 | +0,22 |
| USDJPY | 10 | +2,44 | -4,12 |
| USDCHF | 11 | +0,12 | +2,98 |
| AUDUSD | 4 | -3,87 | -4,04 |
| NZDUSD | 15 | +2,46 | +3,05 |
| USDCAD | 6 | +2,42 | -1,11 |
| CADCHF | 8 | +2,13 | +5,17 |
| CADJPY | 7 | +3,24 | +1,54 |
| EURGBP | 3 | +0,24 | +0,13 |
| GBPCHF | 5 | +0,63 | +1,91 |
| GBPJPY | 4 | +4,99 | -0,32 |

XAUUSD'de önceden başlamış hareket, bu küçük örnekte girişten sonra da sürüyor. USDJPY'de önce işlem yönünde hareket varken sonrasında ters hareket var. AUDUSD'de hem öncesi hem sonrası işlem yönüne ters: burada “hareket bittikten sonra onu takip etmek” açıklamasından farklı, henüz gerçekleşmeyen bir dönüşü beklemek söz konusu olabilir. Bu gözlemler, tek bir evrensel “erken gir” düzeltmesini desteklemiyor.

118 adayın 23'ü trend geri çekilmesi, 95'i ortalamaya dönüş girişidir. Birincisiyle ikincisinde önceki trendin yorumu aynı olamaz. Sıfır işareti dışında eşik taranmadı; önceki hareket yönünde 76, ters yönde 42 aday var. Bu gruplardan en iyi getirili olanı seçip filtre yapılmadı. Çok küçük alt örnekler, semboller arası bağımlılık ve daha önce görülmüş yaklaşık bir aylık geçmiş nedeniyle nedensellik veya bağımsız edge kanıtı yok.

## 2. Bölge teması taze olsa da hacim kanıtı daha eski olabiliyor

Mevcut tetikleyici, bölge/hacim temasını son üç M5 mumunda; Z-score aşırılığını son beş M5 mumunda arıyor. Bunların aynı mumda oluşması zorunlu değil. Bu, kodun mevcut tasarımıdır; bu incelemede bir yazılım hatası olarak ilan edilmedi.

| Son uygun kanıtın yaşı | Bölgeye son temas | Bölge temasıyla birlikte yeterli hacim |
|---|---:|---:|
| Giriş sinyalinin M5 mumu | 100 | 55 |
| Bir önceki M5 mumu | 16 | 38 |
| İki önceki M5 mumu | 2 | 25 |

Yaş, ilgili M5 mumunun kapanışından itibaren ölçülür; temasın mum içindeki kesin saniyesi bilinmiyor. Dolayısıyla 63/118 adayda en son uygun bölge+hacim kanıtı, sinyal mumundan bir veya iki mum önce. Z-score aşırılığı ise son uygun aşırı mumun kapanışından itibaren 5–20 dakika eski.

Önemli ölçüm ayrıntısı: motorun `volume_climax_position` alanı, en yeni uygun hacim mumunu değil, döngünün bulduğu ilk uygun mumu tutuyor. Bu alan tek başına okunsaydı 104 aday eski hacim kanıtı kullanıyormuş gibi görünecekti. Oysa bunların 41'inde sinyal mumunda da uygun bölge+hacim var. Bu nedenle bütün uygun mumlar tekrar hesaplandı ve yukarıdaki sayılar en yeni uygun kanıtla üretildi. Buradan yanlış bir “104 gecikmiş giriş” sonucu çıkarılmadı.

Bu zaman ayrılığı tek başına zararın nedeni değildir: dönüş teyidinin hacim olayından sonra gelmesi bilinçli ve faydalı da olabilir. “Hacim ve dönüş aynı M5'te olmalı” şartının faydası bu çalışmada test edilmedi ve böyle bir şart etkinleştirilmedi. Önceki yalnız-son-mum-bölge-teması denemesiyle de aynı kural değildir; burada hacmin de o temas sırasında bulunması söz konusudur.

## 3. İlk yön bazen doğru; bu tek başına kârlı işlem olmuyor

Önceki 64 işlemin 45'i eski maliyet senaryosunda zararla kapandı. Bu 45'in 41'inde 15 dakika kotasyonu var; dört eksik gözlem olumlu/olumsuz diye doldurulmadı.

Zararlı işlemlerin 19'unda işlem 15. dakikada hâlâ açıkken orta fiyat girişe göre doğru yöndeydi. Bunların 17'sinde spread sonrası kotasyon proksisi de pozitifti. Bu, girişin her kaybeden işlemde baştan yanlış olduğu iddiasını desteklemiyor. Ancak orta fiyatın olumlu olması, komisyon/kayma/swap sonrası elde kâr bulunduğunu göstermez. “19 işlemde net kâr kesin geri verildi” denmiyor.

Stop/hedef geometrisi de kaydedildi. Gözlenen giriş kotasyonu mevcut olan adaylarda trend girişlerinin medyan stop mesafesi yaklaşık 1,11 kapalı M15 ATR, ilk hedef mesafesi 3,15 ATR; ortalamaya dönüşte sırasıyla 1,76 ve 3,47 ATR. Bu, hedefi kısa fiyat tepkisiyle karıştırmamamız gerektiğini gösteriyor. Hedeflerin mutlaka fazla uzak olduğunun kanıtı değildir; amaçlanan tutma süresi de önemlidir. Bu rakamlardan yeni stop/TP katsayısı seçilmedi.

Önceki [15 dakika çıkış denemesi](EXIT_CAP_RESULT_2026-10-24.md) aynı 64 girişte yapıldı ve 13 sembolün 11'i varsayımsal maliyetler altında hâlâ negatif kaldı. Bu nedenle yukarıdaki 19 örnek, o reddedilmiş çıkış kuralını yeniden başarı diye sunmak için kullanılmadı.

## Karar

Girişleri topluca erkene çekmek için yeterli gerekçe yok. Yeni araştırmada yanıtlanacak somut soru, farklı mumlardan gelen bölge/hacim/dönüş kanıtlarının zaman uyumunun işe yarayıp yaramadığıdır. Bu soru henüz test edilmiş bir iyileştirme değildir. İncelemeden en iyi sembol, saat veya süre seçilmedi; yeni bir üretim filtresi ve gerçek emir eklenmedi.

Ücret/kayma/swap kapsamındaki eski eksikler sürüyor. Çalışma yeni, görülmemiş veriyi kullanmadı; OOS ve tam net edge iddiası yok. Üretim modüllerine ve çalışan gözlemcilerin koduna dokunulmadı.

## Kanıt ve tekrar üretim

```powershell
python scripts/audit_entry_timing.py --baseline reports/broker_measurement_v2_2026-10-24 --entry-study reports/entry_cost_calibration_2026-10-24 --output reports/entry_timing_YENI_DIZIN
python -m pytest -q
```

- Son çalışma: `reports/entry_timing_audit_v3_2026-10-24`.
- Protokol SHA256: `1ea7c0fcd49a1045d3be3eb75e64060ff88760831d56694a9754f8eac1b72b45`.
- 55 girdi ve dondurulmuş kopyası hash ile doğrulandı.
- 118 aday kapalı geçmişten yeniden üretildi; açılan 64 işlemin ilk sıradaki geçerli adayla stop/TP1/TP2 eşitliği doğrulandı. 22 adayda aynı yönde/türde birden fazla bölge alternatifi var; önceki çalışmayla aynı sıralama kullanıldı.
- 107 brüt kotasyon getirisi, özgün giriş/çıkış bid/ask değerlerinden bağımsız formülle tekrar hesaplandı.
- 193 test ve 50 alt test geçti. Derleme ve `git diff --check` başarılı; eski shadow test dosyası için yalnız satır sonu uyarısı mevcut.
- Yeni testler karar ve sonrasındaki bütün mumları değiştirmenin geçmiş özelliklerini etkilememesini, eksik dakikaların doldurulmamasını, yön simetrisini ve ilk eski hacim eşleşmesinin yeni eşleşmeyi gizlememesini kapsıyor.
- İlk tanı çalışması aynı yön/türde tek bölge varsayımı nedeniyle doğrulamada durdu; `INCOMPLETE` kaydı korundu. `v2` ilk hacim eşleşmesiyle tamamlandı; `v3` en yeni hacim eşleşmesini ayrıca hesaplıyor. Önceki çıktılar silinmedi veya başarı seçimi için değiştirilmedi.

Çıktılar: [bulgular](entry_timing_audit_v3_2026-10-24/findings.json), [sembol/grup özeti](entry_timing_audit_v3_2026-10-24/summary.json), [118 aday](entry_timing_audit_v3_2026-10-24/candidates.json), [64 işlem eşlemesi](entry_timing_audit_v3_2026-10-24/matched_actual_trades.json), [doğrulama](entry_timing_audit_v3_2026-10-24/verification.json).
