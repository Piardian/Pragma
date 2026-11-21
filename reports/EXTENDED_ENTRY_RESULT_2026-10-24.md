# Pragma: daha uzun, ayrı broker döneminde temel giriş ölçümü — 24 Ekim 2026

## Sonuç

Özgün giriş/çıkış kuralları değiştirilmeden 27 Temmuz–22 Eylül 2026 dönemi incelendi. Bu 58 günlük dönem önceki Eylül sonu–Ekim örneğiyle çakışmıyor. 13 sembolde 777.903 değerlendirilen M1 satırı, 219 benzersiz giriş adayı ve 134 kapanmış simülasyon işlemi var.

15 dakika sonraki **maliyet öncesi yönlü fiyat hareketi** 8 sembolde pozitif, 5'inde negatif. Önceki haftanın aynı saat/yön fiyat penceresine göre fark yalnız 5 sembolde pozitif. İki önceden belirlenmiş alt dönemde de brüt ortalaması pozitif kalan üç sembol EURUSD, NZDUSD ve CADJPY; ortalamalar sırasıyla yaklaşık +0,343, +0,302 ve +0,368 bps. Bu küçük fiyat hareketlerinin gerçek maliyetleri karşılayabildiği kanıtlanmadı.

Brüt hareketin güven aralığı 8 sembolde hesaplanabildi ve sekizinin de aralığı sıfırı kapsıyor. Diğer 5 sembolde yeterli gözlem haftası yok. Önceki hafta farkı için hesaplanabilen aralıklar da sıfırı kapsıyor. Genel ve maliyet sonrası Pragma edge'i henüz kanıtlanmadı.

Olumlu bir bulgu: altın, yeni ayrı dönemde özgün hedef/stop yönetimiyle +5,475R, önceki dönemde +5,340R senaryo sonucu verdi. Bunlar 11 ve 5 işlem; toplam 16. Bu, izlenebilir bir ipucudur; sembol seçip canlıya geçme kanıtı değildir. Tam net maliyet ve ileri örnek eksikliği devam eder.

## Veri kapsamını sonuçlara bakmadan sabitledik

- Hazırlık verisi: 20–26 Temmuz 2026. Bu bölümde işlem açılması araştırma adaptörüyle engellendi; profil/VWAP/ATR ve önceki hafta referansı için kullanıldı.
- Değerlendirme: 27 Temmuz 00:00 UTC–23 Eylül 00:00 UTC hariç.
- Sabit blok A: 27 Temmuz–23 Ağustos; blok B: 24 Ağustos–22 Eylül.
- Evren: önceki 13 sembol. Yeni giriş filtresi, hedef/stop değişikliği veya parametre araması yok. Güncel makro puanı geçmişe uygulanmadı; özgün fiyat-temelli `auto` rejimi kullanıldı.
- Ana ufuk: 15 dakika. 5 ve 30 dakika ikincil ölçümler olarak arşivlendi; en iyi görünen ufuk sonradan seçilmedi.
- M1/tick-sayısı verisi doğrudan mevcut broker terminalinden alındı. Mum aralığından hacim üretilmedi ve eksik dakikalar doldurulmadı.

Mevcut terminalin `maxbars` değeri 100.000. Ön yoklamada Haziran/Mart istekleri kullanılabilir eski M1 örneği yerine istenen tarihten sonraki tek kayıt döndü; bu kayıtlar tarihsel test girdisi sayılmadı. Ortak ve erişilebilir daha eski dönem olarak yukarıdaki pencere sabitlendi. Bu çalışma altı aylık/yıllık test diye sunulmadı. Terminal ayarı veya çalışan terminal süreçleri değiştirilmedi.

MT5'in tarihçe erişimi grafiklerde mevcut geçmiş ve terminalin bar sınırına bağlıdır; tarih aralığı isteklerinin sınırları ayrıca doğrulandı. [Resmi MT5 API açıklaması](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py).

## Tarihsel saat eşleşmesini ayrıca doğruladık

Bugünkü üç saat farkını geçmişe otomatik taşımadık. Broker BTCUSD M5 getiri zamanları, dondurulmuş bağımsız Binance BTCUSDT M1 kaynağının tam M5 kapanışlarından üretilen getirileriyle kıyaslandı. Binance `time` etiketi 300.000 kaydın tamamında kaynak `open_time` Unix milisaniyesiyle uyumlu.

Önceden sabitlenen kontrol, her gerekli haftada 0–4 saat adayları arasında en az 500 eşleşmiş getiri, en az 0,8 korelasyon ve ikinci en iyi adaydan en az 0,25 fark istedi. On haftanın tamamı aynı 10.800 saniyelik farkı seçti; en iyi korelasyonlar 0,9544–0,9993 arasındaydı. Fark ham zamanlardan çıkarıldıktan sonra veriler önceden belirlenmiş UTC penceresine kesildi.

Bu, saat etiketlerinin çevrimdışı veri doğrulamasıdır; işlem yönü veya kârlılık parametresi optimizasyonu değildir. Brokerin ortak sunucu saati BTC üzerinden doğrulanır; her FX sembolünün dolum maliyetinin bağımsız doğrulaması sayılmaz. Ham ve normalize 26 sembol dosyası zaman/değer eşlemesiyle kontrol edildi. Yeni dönemin önceki test girdileriyle çakışmadığı doğrulandı.

## Ana ölçüm: girişin ardından fiyat hareketi

Özgün maliyet kapılarını geçen adaylar pozisyon doluluğundan önce toplandı. Aynı zaman/yön/türde birden fazla bölge olduğunda ilk geçerli bölge korundu. Sonraki dakika açılışının özgün stop/hedef geometrisini karşılaması ve ufuktaki bütün dakikaların mevcut olması gerekti. 219 adayın tamamında 5/15/30 dakika pencereleri ve önceki hafta referansları eksiksizdi.

Fiyat ölçümü, brokerin **bid açılışından bid açılışına** yönlü brüt farkıdır. LONG ask giriş/SHORT ask çıkış maliyeti, komisyon, kayma ve swap dahil değildir; gerçek fill veya net getiri değildir. 1 bps fiyatın %0,01'idir.

Referans, aynı yönde bir hafta önceki aynı saat fiyat penceresidir. Önceki hafta gerçekten sinyal üretmiş ve işlem açmış bir strateji değildir. Yönü sonraki sinyalden atanan bir kontrol penceresidir; bu eski pencerelere canlı/gerçekleşmiş strateji getirisi muamelesi yapılmadı.

| Sembol | Aday | 15 dk brüt bps | Önceki hafta farkı bps | Blok A brüt bps | Blok B brüt bps |
|---|---:|---:|---:|---:|---:|
| XAUUSD | 13 | -0,913 | -5,181 | +3,538 | -6,107 |
| EURUSD | 20 | +0,343 | +0,934 | +0,052 | +0,781 |
| GBPUSD | 20 | -0,272 | +2,357 | -1,508 | +0,140 |
| USDJPY | 9 | -0,493 | -0,938 | +1,359 | -1,975 |
| USDCHF | 37 | +0,712 | -1,091 | +2,360 | -0,411 |
| AUDUSD | 19 | +0,687 | +0,961 | -2,458 | +2,521 |
| NZDUSD | 21 | +0,302 | -3,434 | +0,062 | +0,421 |
| USDCAD | 16 | -0,422 | -0,350 | +0,541 | -1,171 |
| CADCHF | 24 | +0,279 | -0,843 | +0,589 | -0,237 |
| CADJPY | 15 | +0,368 | +0,796 | +0,022 | +0,599 |
| EURGBP | 3 | +2,217 | +3,231 | +2,217 | yok |
| GBPCHF | 12 | +0,011 | -0,351 | +0,168 | -0,771 |
| GBPJPY | 10 | -1,306 | -2,756 | -0,901 | -1,351 |

Üç sembolde iki blok pozitif, sekizinde bloklar arasında işaret değişiyor, GBPJPY iki blokta negatif. EURGBP'nin ikinci blokta adayı yok; bu başarı veya sıfır kazanç olarak puanlanmadı.

Güven aralıkları takvim haftası kümeleriyle deterministik bootstrap kullanıyor. Gözlemlerin ilk/son haftası arasında en az sekiz takvim haftası yoksa aralık üretilmiyor. Örtüşen pencereler, önceki hafta referanslarının komşu haftalarla bağımlılığı ve çoklu sembol/ufuk incelemesi tam düzeltilmiş değildir. Bu nedenle aralıklar keşif amaçlıdır; tek bir pozitif nokta tahmini edge kanıtı değildir.

## Özgün hedef/stop stratejisinin ikincil sonucu

Aşağıdaki tabloda özgün hedefler, kısmi çıkış ve başabaş davranışı kullanıldı. Önceki testteki sabit yarım-spread + yön başına 1 bps komisyon +0,5 bps kayma varsayımı yeni döneme de aynı şekilde taşındı. **Bu maliyetler yeni dönemin gerçek dolum maliyetleri değildir; komisyon/kayma/swap tam kalibre edilmedi.** Senaryo ne gerçek net sonuç ne de tüm masrafların kesin kötü durum sınırıdır.

| Sembol | Yeni ayrı dönem işlem | Yeni dönem senaryo R | Önceki dönem işlem | Önceki dönem senaryo R |
|---|---:|---:|---:|---:|
| XAUUSD | 11 | +5,475 | 5 | +5,340 |
| EURUSD | 12 | -2,606 | 8 | -7,085 |
| GBPUSD | 15 | -9,083 | 7 | -5,789 |
| USDJPY | 5 | -2,661 | 7 | -4,487 |
| USDCHF | 18 | +2,155 | 7 | -1,209 |
| AUDUSD | 12 | -9,624 | 3 | -3,376 |
| NZDUSD | 11 | +0,971 | 6 | -2,941 |
| USDCAD | 10 | -8,973 | 3 | -1,923 |
| CADCHF | 13 | -12,032 | 4 | -0,226 |
| CADJPY | 11 | -6,713 | 4 | -4,617 |
| EURGBP | 2 | -2,481 | 3 | +3,785 |
| GBPCHF | 8 | -7,528 | 4 | -3,338 |
| GBPJPY | 6 | -4,241 | 3 | -0,221 |

Yeni dönemde üç sembolün senaryo sonucu pozitif (XAUUSD, USDCHF, NZDUSD), onunun negatif. Dönem sonunda açık kalıp zorunlu kapatılmış işlem yok. İki dönemde de pozitif olan tek sembol altın; iki dönemde de negatif dokuz sembol var. Farklı dönem uzunluklarının R büyüklükleri eşit örnek gibi kıyaslanmadı, semboller arası R toplamı portföy getirisi diye sunulmadı ve en iyi sembole üretim filtresi konmadı.

15 dakika ölçümü erken fiyat hareketini, tam tekrar ise özgün hedef/stop yönetimini gösteriyor. Altının kısa ufku bu yeni dönemde negatifken tam strateji sonucu pozitif kaldı. Bu iki ölçüm farklı soruları yanıtlar; kısa ufuktaki negatifliği tek başına bütün girişlerin başarısızlığı diye yorumlamıyoruz. Tam tekrarın pozitifliği de tek başına gerçek net edge kanıtı değil.

Giriş kabul kapıları eski maliyet varsayımlarını koruduğu için bu çalışma maliyetsiz bütün potansiyel girişlerin taraması değildir. Düşük gerçek maliyetle kabul edilebilecek ek adayları araştırmak ayrı bir maliyet-kalibrasyon hipotezi olur; bu koşu sırasında kapılar değiştirilmedi.

## Karar ve uygulanabilir devam yolu

Bu çalışma, yalnız çıkış ayarları denemekten daha temel bir soruyu ölçtü: girişlerdeki avantajın dönemler arasında tutarlılığı zayıf ve gözlenen küçük brüt ortalamalar belirsiz. Genel Pragma avantajı doğrulanmadı; bu, hiçbir koşulda geliştirilemeyeceği anlamına gelmiyor.

Üretim kuralları ve evren korunuyor. Altının tekrarlanan pozitif senaryo sonucu ileri gözlemde doğrulanabilecek bir araştırma bulgusu olarak kaydedildi. Aynı geçmişten en iyi sembol/saat seçip avantaj varmış gibi yeni bir sistem oluşturulmadı.

Daha güçlü sonraki kanıt için, terminalin geçmiş erişimini genişletme olanağını ayrı test etmek ve daha eski gerçek M1 verisi elde edilirse farklı rejimleri kapsamak gerekir; brokerin bu veriyi sağlayacağı varsayılmamalı. Ayrıca gerçek maliyet kapsamı tamamlanmalı ve dondurulmuş kuralların yeni zamanda gözlemi sürdürülmelidir. Bu adımlar yeni bir stop/TP katsayısı seçmekten farklıdır.

## Doğrulama

- Sonuç dizini: `reports/extended_entry_2026-10-24`.
- Plan, veri alımından ve forex sonuçlarının hesaplanmasından önce donduruldu; protokol, saat/veri kontrollerinden sonra ve strateji analizi başlamadan önce donduruldu.
- Protokol SHA256: `9fbed79ea239a6f8aa4ae09d84a3fdb4aa77df3cf9c66b5cc7a3b82458f08426`.
- 42 kaynak ve dondurulmuş kopyasının hashleri doğrulandı. Özgün karar çekirdeğinin sekiz dosyası önceki sürümle aynı.
- Ham ve normalize 26 sembol dosyası; saat ham verisi, saat denetimi ve kaynak plan hashleri doğrulandı.
- 219 aday kapanmış geçmişten bağımsız olarak yeniden üretildi; stop/TP1/TP2 ve karar zamanı eşitliği kontrol edildi.
- 657 ufuk getirisi ve 657 önceki hafta kontrol penceresi bağımsız formülle yeniden hesaplandı. Eksik veri veya gelecekteki mum kapanışı kullanılmadı.
- 134 simülasyon girişinde özgün aday seviyeleri ve sonraki dakika maliyetli açılışı ayrıca doğrulandı. Hazırlık döneminde işlem olmadığı kontrol edildi.
- 230 test ve 50 alt test geçti; derleme ve `git diff --check` başarılı. Eski shadow testinde yalnız satır sonu uyarısı var.
- Gerçek emir, hesap değişikliği, bildirim veya üretim/gözlemci kodu değişikliği yapılmadı.

```powershell
python scripts/run_extended_entry_study.py --baseline reports/broker_measurement_v2_2026-10-24 --terminal-path "C:\Program Files\Five Percent Online MetaTrader 5\terminal64.exe" --output reports/extended_entry_YENI_DIZIN --workers 3
python -m pytest -q
```

Bu tekrar komutu brokerden aynı tarihleri yeniden ister; birebir veri tekrar üretimi için hashlenmiş arşiv dosyaları esas alınmalıdır. Çalışma zaman bakımından ayrı ek tarihsel tanıdır; gerçek ileri/OOS kanıtı diye etiketlenmedi.

Çıktılar: [karar](extended_entry_2026-10-24/decision.json), [önceden dondurulan plan](extended_entry_2026-10-24/plan_frozen.json), [protokol](extended_entry_2026-10-24/protocol_frozen.json), [tarihsel saat denetimi](extended_entry_2026-10-24/historical_clock_audit.json), [özet](extended_entry_2026-10-24/summary.json), [önceki dönem kıyası](extended_entry_2026-10-24/comparison_with_existing_period.json), [doğrulama](extended_entry_2026-10-24/verification.json).
