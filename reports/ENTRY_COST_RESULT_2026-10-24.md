# Pragma giriş kalitesi ve broker maliyet kanıtı — 24 Ekim 2026

## Karar

İlk giriş/maliyet çalışması tamamlandı. Gerçek tarihsel bid/ask ve hesap masraf kayıtları kullanıldı. Mevcut girişe güçlü gövde şartı eklemek tutarlı fayda vermedi. Bir M5 bekleyip kırılım teyidi almak, karşılaştırılabilen 12 sembolün tamamında 15 dakikalık ölçümde kötüleşti. Bu iki değişiklik üretime alınmadı. Tam maliyet sonrası edge henüz kanıtlanmadı.

Önemli düzeltme: önceki FX testindeki 1 bps/yön komisyon ve 0,5 bps/yön kayma broker kalibrasyonu değildi. Ölçülen ücret örnekleri, komisyon varsayımının üç sembolde yüksek olduğunu gösterdi. Kayma ise giriş ve çıkışta aynı davranmıyor. Eski senaryo sonuçları korunuyor; gerçek broker-net sonuçları gibi yorumlanmayacak.

## Komisyon ve swap: gerçek hesap kaydı

Hesap geçmişi yalnız okunarak masraf alanları alındı; emir gönderilmedi. Bunun için resmi [MT5 işlem geçmişi API’si](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py) kullanıldı. Hesap kimliği, emir numarası ve işlem kârı rapora aktarılmadı. Kaynak hesap para birimi USD. İlgili 13 sembolde 39 anonim masraf kaydı var; bunlar Pragma stratejisinin gerçek broker işlemleri değildir.

En az üç tam açılış/kapanış pozisyonu bulunan semboller:

| Sembol | Tam pozisyon örneği | Gözlenen komisyon/ücret debiti | Kullanım |
|---|---:|---:|---|
| XAUUSD | 4 | 4.00 USD/lot/yön | Döneme ait ücret proksisi |
| GBPUSD | 3 | 2.00 USD/lot/yön | Döneme ait ücret proksisi |
| USDCHF | 4 | 2.00 USD/lot/yön | Döneme ait ücret proksisi |

Üç örnek, ücret tarifesinin gelecekte sabit kalacağını kanıtlamaz. Beş sembolde işlem kaydı yok; beş sembolde örnek yetersiz. Bu on sembolün komisyonu sıfır sayılmadı ve diğer sembollerden kopyalanmadı. Eşik altındaki EURUSD/USDJPY vb. kayıtları kanıt dosyasında ayrıca görülebilir.

GBPUSD hesap kayıtlarında toplam 3,20 USD swap debiti gözlendi. Bu, hipotetik Pragma işlemlerine günlük swap oranı olarak taşınmadı; tutma süresi/rollover tarifesi kalibrasyonu eksik. Komisyon, gerekli yerlerde aynı tarih/dakikanın GBPUSD/USDCAD/USDCHF/USDJPY fiyatıyla fiyat birimine çevrildi; güncel kur geçmişe uygulanmadı. Kaynak fiyatlar bid olduğundan bu dönüşüm de ücret proksisidir.

## Tarihsel spread ve kayma kapsamı

Tick pencereleri [MT5 copy_ticks_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py) ile alındı. Mevcut broker saat düzeltmesi taze heartbeat ile kontrol edildi; seçilen tick bid fiyatı aynı dakika broker OHLC aralığıyla sınandı. Bu çalışma geçmişteki bütün broker saat değişimlerini dış kaynakla bağımsız doğrulama iddiası taşımaz.

- 930 tekil kotasyon zamanı sorgulandı: 781 geçerli kotasyon proksisi, 35 iki saniye içinde uygun kotasyon bulunamayan zaman, 114 dondurulmuş geçmiş dışındaki referans zamanı.
- Girişte ilk uygun ask/bid, çıkışta karşı taraf bid/ask kullanıldı. Eksik tickler doldurulmadı; bunlar gerçek gerçekleşmiş emir fill’i sayılmadı.
- Özgün komisyon/kayma senaryosu aday seçme filtresinde sabit kaldı. Yeni ücret bilgisi, giriş hipoteziyle aynı deneyde filtreyi değiştirmek için kullanılmadı. Dolayısıyla bu çalışma mevcut dondurulmuş aday kümesiyle sınırlıdır.

Gerçek emir ve gerçekleşme geçmişi ayrıca [history_orders_get](https://www.mql5.com/en/docs/python_metatrader5/mt5historyordersget_py) ile eşlendi. Emir sunucuda oluşturulmadan hemen önceki kotasyon en fazla bir saniye eski olabiliyordu; gelecekteki kotasyon benchmark seçilmedi. Bu ayrı, deney sonrası tanıdan 39 işlem bacağının 21’inde sunucu-kotasyon kayma proksisi çıktı: 6 giriş, 15 çıkış. Sekizinde uygun piyasa emri, onunda yeterince taze emir-öncesi tick yok.

Bu istemci kararından gerçek fill’e toplam kayma değildir. İstemcinin emir göndermeden önce gördüğü talep kotasyonu kaydedilmemiştir; örnek başka strateji/emir türlerinden gelebilir. Bu sebeple frozen giriş deneyinin maliyetlerine sonradan eklenmedi ve tam kayma kalibre edildi denmedi. Örnekte XAUUSD’nin iki girişinde olumsuz-yön proksi ortalaması yaklaşık 0,085 bps, beş çıkışında 2,785 bps. Aynı kaymayı her giriş ve çıkışa sabit varsaymak desteklenmiyor.

## Önceden sabitlenen giriş hipotezleri

Üç kural, 13 sembolün tamamında aynı 118 benzersiz, pozisyon doluluğundan önce yürütülebilir aday üzerinde incelendi. Önceki ara mesajdaki 128 sayısı yanlıştı; protokol girdilerinden hesaplanan doğru sayı 118. Aylık geçmiş daha önce görüldüğü için çalışma keşif amaçlıdır, OOS değildir.

1. Temel: mevcut aday ve sonraki uygun kotasyon.
2. Güçlü gövde: aynı sinyal M5 mumunun yönlü gerçek gövdesi mum aralığının en az %50’si. Giriş zamanı/stop/hedef değişmiyor.
3. Bir M5 bekle: sonraki tam M5 kapanışı ilk sinyalin tepe/dibini yönünde kırmalı. Bekleme sırasında ilk stop veya TP1 görülürse aday iptal. Teyit sonrasındaki uygun kotasyon giriş proksisi.

Ana ölçüm girişten sonraki 15 dakika; 5 ve 30 dakika ikincil ölçümler. Bunlar TP/SL ile tamamlanmış strateji R getirileri değildir. Gerçek fill, tam komisyon, swap ve istemci kayması olmadığı için hiçbir satıra fully_net_bps üretilmedi. Önceki haftanın aynı saat/yön kotasyonu yalnız mevcutsa referans olarak tutuldu.

| Kural | Seçilen aday | 15 dk kotasyonu tam | Eksik |
|---|---:|---:|---:|
| Temel | 118 | 107 | 11 |
| Güçlü gövde | 55 | 48 | 7 |
| Bir M5 bekle | 44 | 42 | 2 |

Eksikler değerlendirme dışında görünür tutuldu; bütün seçilmiş adaylarda tam maliyetli olumlu sonuç varmış gibi yorumlanmadı. CADJPY bekleme kolunda seçilmiş bir aday var ama uygun 15 dakika kotasyonu yok: sonuç eksik, 0 kâr değildir.

15 dakikalık ortalama, spread dahil kotasyon proksisi (bps; komisyon/kayma/swap hariç):

| Sembol | Temel | Güçlü gövde | Bir M5 bekle |
|---|---:|---:|---:|
| XAUUSD | +14.27 | +20.69 | +13.11 |
| EURUSD | +0.14 | -0.90 | +2.75 |
| GBPUSD | +0.22 | -0.83 | -2.37 |
| USDJPY | -4.12 | -3.52 | -8.09 |
| USDCHF | +2.36 | +1.91 | -0.10 |
| AUDUSD | -4.09 | -5.52 | -9.19 |
| NZDUSD | +2.30 | +0.69 | -0.63 |
| USDCAD | -1.39 | +0.04 | -2.27 |
| CADCHF | +4.34 | +0.00 | +6.21 |
| CADJPY | +1.20 | -1.46 | eksik |
| EURGBP | -0.52 | +0.58 | -1.76 |
| GBPCHF | +0.55 | +2.00 | -1.70 |
| GBPJPY | -1.31 | -5.60 | -7.79 |

Güçlü gövde seçimi temel adayların genel ortalamasına göre 5 sembolde artış, 8 sembolde düşüş verdi. Bu karşılaştırma seçilmiş alt kümeler arasındadır; aynı sinyalin aynı girişini değiştirmediği için eşlenmiş tek-sinyal getirisi farkı sıfırdır. Koşullu ortalamanın yükselmesi tek başına filtre edge’i değildir.

Bekleme hipotezi aynı sinyallerde karşılaştırıldığında, gözlenebilen 12 sembolün tamamında eşit 15 dakikalık tutma ufkunda kötüleşti. Bu karşılaştırma mutlak çıkış saatini de beş dakika ileri taşır. Bu nedenle deneyden sonra ayrıca aynı özgün çıkış saatini sabit tutan maliyet/entry-zamanı ayrıştırması yapıldı: 40 eşlenmiş durumun sembol ortalamalarında, karşılaştırılabilen 12 sembolün tamamında giriş fiyatı etkisi yine negatif. Dört seçilmiş gecikmeli aday bu ayrıştırmada eksik. Bu ek tanı yeni model/parametre seçimi değildir.

Swap/kayma hariç gözlenmiş ücret proksisi de çıkarıldığında temel 15 dakika ortalamaları: XAUUSD +14,08 bps (8 tam kotasyon), GBPUSD -0,08 bps (12), USDCHF +1,96 bps (11). Bunlar tam net getiri veya edge değildir. Aylık, bağımlı küçük örnekte bootstrap güven aralığı üretilmedi; çoklu hipotez seçimi de çözülmüş değildir.

## İleri gözlem

FX için ayrı, yalnız okuma yapan üç-kural gözlemcisi başlatıldı. Doğru broker terminali açıkça seçiliyor; gerçek zamanlı M5 kararları, kabul/ret gerekçeleri, giriş kotasyonu ve 5/15/30 dakika sonraki kotasyonlar ayrı arşivleniyor. Emir, Telegram ve eski shadow hesabına işlem yok.

- Kaynak: reports/fx_entry_forward_2026-10-24; başlatılan PID 43712, güncel PID observer.pid dosyasında.
- Şu an piyasa kapalı: 13 sembolde taze FX kotasyonu yok; WAITING_FOR_FRESH_MARKET, kaynak hatası yok. Henüz yeni ileri işlem örneği yok.
- Giriş kararı en çok 30 saniye gecikebilir; kotasyon en çok 5 saniye eski olabilir ve karar zamanından önce olamaz. Geç/eksik gözleme geriye dönük kârlı fill yazılmaz.
- Teyit bekleyen ve ufuk sonucu bekleyen kayıtlar diskte tutulur. Yeniden başlatma/hafta sonu sonrası geçmiş fill uydurulmaz; kaçan son tarihler eksik işaretlenir.
- Kod/protokol değişirse bekleyen state başka sözleşmeyle yeniden yorumlanmaz. Otomatik Windows başlangıç görevi eklenmedi; bilgisayar/süreç kapanırsa kayıt durur.
- Taze broker saat kontrolü başarısız olursa veri reddedilir; saat farkı kâr lehine tahmin edilmez.

## Alınan karar ve kalan eksikler

Güçlü gövde ve ilave M5 teyidi genel üretim filtresi olmayacak. Aynı veri üzerinde yeni eşik taraması yapılmayacak. Mevcut temel kural ve iki karşı-olgusal kolun yeni zamanda gözlemi, gerçek maliyet kapsamı ve eksik/veri gecikmesi sayıları birlikte değerlendirilecek. Komisyon için 10 sembolde yeterli kanıt, istemci talebinden fill’e kayma ve varsayımsal strateji işlemlerinin swap kalibrasyonu eksik. Mevcut araştırmadan canlı terfi yok.

## Doğrulama

- Protokol SHA256: 2abdaf858b9d5abecdbabf142fd50b5c5d5a17edec127feeb2ce3c272134f3f1; sonuçlar hesaplanmadan önce kod, veri ve hipotezler donduruldu.
- 67 girdi dosyası ve 807 ana tick dosyasının hashleri doğrulandı; uyuşmazlık yok. Sunucu-kayma tanısının 28 tick dosyası da doğrulandı.
- 175 test geçti; derleme ve git diff --check başarılı. Maliyet eksikliği, tam pozisyon eşleme, yönlü bid/ask, geçmiş kur dönüşümü, gecikmeli teyit iptali, gelecek kotasyon kullanmama, zaman etkisi ayrıştırması ve kapalı piyasa restart testleri dahil.
- Karar/strateji davranışı değiştirilmedi. Yeni kod yalnız araştırma ve ayrı ileri gözlem yolunda kullanılıyor.

Çıktılar: [summary.json](entry_cost_calibration_2026-10-24/summary.json), [masraf kanıtı](entry_cost_calibration_2026-10-24/account_cost_evidence.json), [sunucu kayma tanısı](entry_cost_calibration_2026-10-24/broker_slippage_proxy_posthoc.json), [zaman ayrıştırması](entry_cost_calibration_2026-10-24/timing_attribution_posthoc.json), [gözlemci durumu](fx_entry_forward_2026-10-24/status.json).
