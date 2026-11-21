> Güncelleme: MT5 terminali açıkça seçilerek FX/altın testi de tamamlandı. Önceki engel ve sonuçlar aşağıda tarihsel kayıt olarak korunuyor. Güncel FX sonucu: [FX_MEASUREMENT_RESULT_2026-10-24.md](FX_MEASUREMENT_RESULT_2026-10-24.md).

# Pragma ölçüm düzeltmesi ve deney sonucu — 23–24 Ekim 2026

## Karar

Ölçüm hataları düzeltildi ve üç kripto sembolünün mevcut M15 varsayılanında dondurulmuş deneyler tamamlandı. Maliyet sonrası tekrarlanabilir edge kanıtlanmadı. Hiçbir aday canlıya veya mevcut shadow hesabına terfi ettirilmedi. FX/altın tarihsel deneyinin veri çekimi MT5 yetkilendirme hatasında kaldı; tamamlanmış gibi gösterilmiyor.

## Tarihsel deney sonuçları

Veri: sembol başına 300.000 kapalı M1 mum, 22 Mart–16 Ekim 2026. Bu dönem daha önce incelenmiştir; yeni OOS değildir. Yerel Binance arşivinin ham hacim ve taker-delta alanları kontrol edildi; piyasa/venue kökeni bağımsız olarak yeniden indirilip doğrulanmadı.

Maliyet senaryosu: yön başına 4 bps komisyon + 1 bps kayma; nominal gidiş-dönüş 10 bps. Ayrıca sekiz saatte sabit %0,01 funding debiti. Bunlar gerçek fill kalibrasyonu değildir. 1,5x senaryosu tüm maliyet bileşenlerini artırır.

| Sembol / M15 | Temel işlem | Temel R | Son mum teması R | 1,5x maliyet R | BE kaldırma farkı R |
|---|---:|---:|---:|---:|---:|
| BTCUSDT | 22 | -2.39 | -2.33 | -5.63 | -0.50 |
| SOLUSDT | 46 | +6.54 | +8.71 | +4.29 | -0.50 |
| LINKUSDT | 40 | -5.31 | -10.68 | -5.79 | -0.50 |

BE farkı, aynı temel girişler ve hedefler üzerinde yalnız TP1 sonrası stop taşımasını kaldıran eşlenmiş çıkış deneyidir. Bu karşı-olgusal işlemler çakışabilir; ayrı bir portföy getiri eğrisi değildir. Temel/son-mum/maliyet deneylerinde sembol başına aynı anda bir pozisyon vardır; ayrı sembol sonuçları birleşik portföy getirisi sayılmaz.

Bu protokolde BTC lider filtresi kapalıdır; üç sembol kendi nedensel fiyat rejimini kullanır. Eski FAZ13 testi lider filtresi de içerdiğinden eski/yeni sayıları doğrudan karşılaştırıp farkı yalnız ölçüm düzeltmesine bağlamak doğru değildir.

## Belirsizlik ve giriş kalitesi

Sembol bazında temel işlem beklentisi ve hafta kümeleriyle bootstrap %95 aralığı:

- BTCUSDT: -0.108 R/işlem; [-0.721, +0.562] R.
- SOLUSDT: +0.142 R/işlem; [-0.355, +0.764] R.
- LINKUSDT: -0.133 R/işlem; [-0.577, +0.511] R.

Drawdown değerleri kapanmış işlem bakiyesine dayanır; gerçekleşmemiş pozisyon zararını içeren gerçek intraday equity drawdown değildir. Üç aralık da sıfırı içeriyor. Bunlar keşif amaçlı, çoklu deneme düzeltmesi yapılmamış aralıklardır; anlamlı pozitif edge iddiası üretmez. SOL'un pozitif tarihi sonucu yalnız bir araştırma adayıdır.

Giriş kalitesi tüm yürütülebilir adaylarda, pozisyon doluluğu öncesinde ölçüldü. Zaman karşılaştırması önceki haftanın aynı saat/dakika ve aynı yönündeki referanstır. Touched fakat reddedilmiş adayların karşı-olgusal sonuçları ayrıca saklandı.

| Sembol | Aday | 5 dk net bps | 15 dk net bps | 30 dk net bps |
|---|---:|---:|---:|---:|
| BTCUSDT | 32 | -10.68 | -8.86 | -10.29 |
| SOLUSDT | 78 | -10.99 | -11.65 | -10.97 |
| LINKUSDT | 61 | -16.31 | -14.66 | -6.65 |

Bu sabit ufuklar TP/SL stratejisinin getirisi değildir. Kısa ufuklu sinyal kalitesini ve maliyet eşiğini ölçer. Sonuçlar, daha çok filtre eklemek veya BE'yi kaldırmak için olumlu kanıt vermiyor. Son mum teması şartı SOL'da artış, LINK'te belirgin kötüleşme üretti; evrensel bir düzeltme olarak benimsenmedi.

## Uygulanan düzeltmeler

- Ortak saf rejim/tetik sözleşmesi: kripto bayrakları, temas penceresi, RR, maliyet ve geçmiş gün hacmi vetosu aynı hesap üzerinden geçiyor.
- Sonraki kesintisiz M1 açılışında giriş; sinyal, karar ve fill zamanları ayrı. Aynı giriş mumunda stop/TP yönetimi mümkün. Gap stoplarında daha kötü açılış fiyatı kullanılıyor.
- Giriş ve her kısmi/tam çıkışta ters yönlü maliyet. Funding ayrı debit; OHLC sınırındaki belirsizlik iyimser maliyet indirimi üretmiyor.
- Drawdown yüzdeleri tepe/gün başı bakiyeye göre hesaplanıyor. Tekrarlı/sırasız zamanlar sessiz düzeltilmeden reddediliyor.
- HistData sabit EST → UTC dönüşümü; gerçek hacim yoksa test açıkça duruyor. Eski mum genişliği hacim vekili ve bugünkü makroyu bütün geçmişe uygulama kaldırıldı/engellendi.
- Eski sonuçlar korundu; edge kanıtına uygun olmadıkları ayrı hashli kayıtla belirtildi.
- Çalışan legacy sinyal/shadow davranışına karşı ayrı ölçüm gözlemi. Gözlem hesap veya disk hatası eski hattı kesmiyor; açık ölçüm çağrısı hata halinde reddediliyor.
- Yeni ölçüm ve kotasyon toplayıcıları Telegram ve broker emri göndermiyor. Hiçbir daemon yeniden başlatılmadı.

## Gerçek veri gözlemi ve eksikler

MT5 üzerinden 13 sembolden toplam 26 bid/ask gözlemi ve 26 karar/gözlem kaydı alındı. Binance üzerinden ilk örneklemede 3 sembolden toplam 21 kotasyon ve 6 karar/gözlem kaydı alındı; ayrı gözlemci daha sonra sürekli kayıt için başlatıldı. Bu sayılar bağımsız işlem sayısı değildir; tekrarlı ve gecikmiş gözlemler bulunabilir. Karar zamanı ve gözlem zamanı saklanır. Gerçek fill kanıtı yoktur.

Komisyon ve gerçekleşmiş kayma eksik olduğunda null bırakıldı; sıfır maliyet sayılmadı. MT5 sonraki döngü ve geçmiş veri çekiminde `(-6, Terminal: Authorization failed)` döndürdü. Broker FX/altın deneyi bu yüzden eksik. Oturum bağlantısı düzelmeden broker geçmişi testinin tamamlandığı söylenemez. Binance için yalnız okuma yapan gözlemci 24 Ekim 2026 00:05 İstanbul saatinde, 30 saniye aralıkla başlatıldı (ilk başlatma PID: 118600; geçerli PID observer.pid dosyasında). Çalıştığı log ve yeni kotasyonlarla doğrulandı. Emir, Telegram veya PnL üretmiyor; eski shadow hesabını kullanmıyor. Çıktı: forward_observer_binance_2026-10-23. Tam beş günlük hacim geçmişini korumak için gözlemci 12.000 mumla yeniden başlatıldı; ilk 5.000 mumluk kısa gözlemler yalnız tanı kaydıdır. Otomatik başlangıç görevi eklenmedi; süreç durur veya bilgisayar kapanırsa kayıt durur. MT5 tarafında yetkilendirme hatası nedeniyle sürekli süreç başlatılmadı.

Bağımsız doğrulanmış tarihsel broker saat eşlemesi ve swap verisi de eksik. Hazırlanan broker araştırma komutu gerçek tick hacmi kullanır; güncel spreadi geçmişe sabit varsayarsa bunu yalnız senaryo olarak etiketler.

## Doğrulama ve tekrar üretim

- 153 unit test geçti; compileall ve git diff --check başarılı.
- Dondurulmuş veri/kod/config kopyalarının hashleri yeniden doğrulandı; bozuk dosya yok.
- Üç sembolde 12'şer dolu POI örneğinin pointwise/backtest kararı eşit: 36/36.
- Temel deneydeki bütün 108 giriş: karar, yön, POI, stop/TP, sonraki açılış fill fiyatı ve zamanları pointwise gözlemle eşit. Sonlu 8-seans karar penceresinin tam geçmişle eşitliği her sembolün ilk/son girişinde ayrıca doğrulandı.
- BE deneyinin temel çıkış replay'i, bütün temel işlemlerde ilk backtest sonuçlarıyla eşit.
- Deney tamamlandıktan sonra yalnız run_pipeline.py ve shadow_trader.py için gözlem hatası izolasyonu güçlendirildi. Finansal karar/yürütme çekirdeği dondurulmuş sürümle aynı. Bu sonraki farklar ayrı doğrulama kaydında açıkça listelenir.
- İlk büyük deney sonuç üretilmeden performans iyileştirmesi için durduruldu; ABORTED olarak korundu. Son protokol üç sembolün mevcut M15 varsayılanını önceden belirledi; sonuç seçimi yapılmadı.

Çıktılar: `measurement_v2_final_2026-10-23/protocol_frozen.json`, `summary.json`, ham aday/reddedilen kayıtları, işlem listeleri ve eşlenmiş çıkışlar. Protokol SHA256: `729d7b266d1d1f8879badbe81bbfc07a18e00748a3b0fac5619f34a7e79baf6c`.

Komutlar ve sınırlamalar: [MEASUREMENT_V2_USAGE.md](MEASUREMENT_V2_USAGE.md). Eski sonuç uygunluk kaydı: [legacy_evidence_status_2026-10-23.json](legacy_evidence_status_2026-10-23.json).

## Sonraki karar

Mevcut kanıt, genel bir BE/temas filtresi değişikliğini desteklemiyor. Canlıya geçiş yapılmayacak. Önce eksik broker maliyetleri ve zaman eşlemesi tamamlanmalı; ardından yeni zamanda, giriş anında kaydedilmiş adaylar ve gerçek maliyetlerle ileri değerlendirme yapılmalı. Tarihsel SOL sonucunu yeni örneğe bakıp yeniden optimize etmek ileri doğrulama sayılmayacak.
