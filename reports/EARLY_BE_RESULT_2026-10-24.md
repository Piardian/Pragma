# Pragma: +1R'de erken başabaş stopu — 24 Ekim 2026

## Karar

Deneme tamamlandı. Bu kez erken kâr almadan, fiyat +1R ilerleyince stop girişe taşındı; özgün kâr hedefleri ve kısmi çıkış boyutu korundu. Aynı 64 girişte 5 sembol iyileşti, 2'si kötüleşti, 6'sı değişmedi. Tüm dönem tekrarında 65 işlem oluştu ve eski maliyet senaryosunda 12 sembol negatif, yalnız EURGBP pozitif kaldı. EURGBP'nin sonucu özgün stratejiye göre değişmedi; yeni koruma kuralının kazandırdığı bir edge gibi sunulmadı. Bu kural üretime eklenmedi.

## Soru ve tek yeni kural

Önceki [yakın TP1 denemesi](NEAR_TP1_RESULT_2026-10-24.md), hem erken yarım kâr alımını hem mevcut başabaş kuralının daha erken başlamasını içeriyordu. Bu denemede ilk etkiyi kaldırıp erken korumayı ayrı inceledik.

- Aynı uygun popülasyon: iki ayrı hedefi olan ve ilk hedefi 1R'den uzaktaki işlemler. Tek hedefli veya ilk hedefi zaten daha yakın işlemler değişmedi.
- R, gerçekleşen simülasyon giriş fiyatı ile özgün ilk stop mesafesidir. Fiyat +1R'ye erişince stop giriş fiyatına taşınır.
- TP1 ve TP2 özgün seviyelerinde kalır; +1R'de kısmi çıkış yoktur. Özgün TP1'e ulaşılırsa eski %50 kısmi çıkış ve mevcut başabaş yönetimi devam eder.
- Özgün giriş koşulları, RR uygunluk kapısı, rejim, seans, ilk stop, maliyetler ve semboller değişmedi.
- Eşik sonuçlar öncesinde 1R olarak donduruldu. Başka R eşikleri veya önceki giriş filtreleriyle birleşimler taranmadı.

## Aynı girişler ve tam tekrar

Özgün 64 işlemin çıkış getirisi, zamanı ve nedeni yeniden üretilerek eski sonuçla eşitliği kontrol edildi. Yeni yönetim aynı girişlerde karşılaştırıldı. 19 tek hedefli işlemde seviyeler ve sonuçların bütünüyle değişmediği ayrıca doğrulandı. 64 eşlemenin tamamında kapanmış sonuç var; dönem sonu açık eşleme yok.

Ardından bütün özgün aday akışı yeni stop yönetimiyle tekrar oynatıldı. Daha erken kapanış EURUSD'de bir ek girişe izin verdi; tam tekrar 65 kapanmış işlem içeriyor. Bu yüzden yalnız önceki kayıtlardan uygun görünenler seçilmiş değildir.

**Aşağıdaki R değerleri sabit tarihsel spread varsayımı + yön başına 1 bps komisyon + 0,5 bps kayma senaryosuna aittir. Bunlar gerçek broker net getirileri değildir; swap ve tam kayma eksiktir. Önceki hesap örneklerinde bazı komisyon varsayımlarının yüksek olduğu görülmüştü. Bu tek stop değişikliğini ayırmak için maliyet senaryosu iki kolda aynı tutuldu.**

| Sembol | Özgün işlem | Özgün R | Önceki 1R yarım çıkış R | Yalnız erken BE R, aynı giriş | Tam tekrar işlem | Tam tekrar R |
|---|---:|---:|---:|---:|---:|---:|
| XAUUSD | 5 | +5,340 | +0,306 | -0,342 | 5 | -0,342 |
| EURUSD | 8 | -7,085 | -5,633 | -6,085 | 9 | -7,221 |
| GBPUSD | 7 | -5,789 | -4,291 | -4,789 | 7 | -4,789 |
| USDJPY | 7 | -4,487 | -3,417 | -3,487 | 7 | -3,487 |
| USDCHF | 7 | -1,209 | +0,045 | -0,209 | 7 | -0,209 |
| AUDUSD | 3 | -3,376 | -3,376 | -3,376 | 3 | -3,376 |
| NZDUSD | 6 | -2,941 | -0,092 | -0,941 | 6 | -0,941 |
| USDCAD | 3 | -1,923 | -2,038 | -1,923 | 3 | -1,923 |
| CADCHF | 4 | -0,226 | -0,226 | -0,226 | 4 | -0,226 |
| CADJPY | 4 | -4,617 | -3,594 | -4,617 | 4 | -4,617 |
| EURGBP | 3 | +3,785 | +3,680 | +3,785 | 3 | +3,785 |
| GBPCHF | 4 | -3,338 | -3,413 | -3,338 | 4 | -3,338 |
| GBPJPY | 3 | -0,221 | -2,166 | -2,666 | 3 | -2,666 |

Erken koruma, özgün testte zararlı olan 7 işlemin zararını küçülttü. Ancak önceden kazançlı 3 işlemi negatife çevirdi. XAUUSD'nin aynı beş işleminde özgün +5,340R, önceki erken yarım çıkışla +0,306R, yalnız erken başabaş stopuyla -0,342R oldu. Bu örnekte büyük kazanç kaybını yalnız “yarısını erken sattık” açıklamasına bağlayamayız; erken stop da bazı devam hareketlerini kaçırıyor.

Bu bulgu, her erken koruma kuralının her piyasada kötü olduğu anlamına gelmez. Test edilen 1R kuralının bu veri ve maliyet senaryosunda genel çözüm sağlamadığını gösterir. R toplamları semboller arasında portföy getirisi gibi birleştirilmedi. İşlem başına sonuçlar JSON özetinde bulunur.

## Başabaş, sıfır kayıp garantisi değildir

Sabit giriş karşılaştırmasında 22 pozisyonda erken stop devreye girdi. Stop giriş fiyatında olsa bile modellenen çıkış maliyeti negatif getiri doğurur. Sonraki mum kötü açılırsa giriş seviyesinden daha kötü fiyat kullanılır.

Örneğin CADJPY'de 9 Ekim 2026 12:55 UTC girişli işlem, arşivdeki sonraki açılış boşluğu nedeniyle girişteki stop seviyesinden korunamadı ve yaklaşık -1,189R ile kapandı. Özgün stop ile erken stop aynı kötü açılışa yakalandı. Bu işlemde önceki erken yarım çıkış varsayımı bir miktar getiri kilitlediği için farklı sonuç veriyordu. Erken başabaş stopunu risksiz koruma diye sunmak doğru olmaz.

## Mum içi sıralama nasıl ele alındı?

Kural sonuçlardan önce şu şekilde tanımlandı:

1. Aynı M1 mumunda hem özgün stop hem +1R görülürse özgün stop öncelikli.
2. Yeni stopun devreye girdiği mumda fiyat giriş seviyesine de dönerse hedef geliri yazmadan, stop seviyesi ve olumsuz maliyetlerle çıkış varsayılır. Açılış zaten 1R'yi geçtiyse aktivasyon sırası bilinir; aksi durumda mum içi sıra belirsiz diye işaretlenir.
3. Stop devreye girmeden önce oluşmuş bir açılış fiyatı, sonradan gerçekleşen stop dolumu diye kullanılmaz. Sonraki mumların kötü açılışları ise gerçek modeldeki gibi uygulanır.

**Bu veri kümesinde 22 aktivasyonun hiçbirinde aktivasyon mumu girişe dönmedi; özgün stop ile 1R aynı mumda da görülmedi.** Dolayısıyla bu iki sıra belirsizliği dalı gerçek sonucun belirleyicisi olmadı; dallar testlerle kontrol edildi. Yine de M1 modelinin stop seviyesi/kayma varsayımı gerçek tick dolum kanıtı değildir ve dakika içi boşlukları tam kalibre etmez.

## Araştırma açısından ne öğrendik?

Basit çıkış ayarlarının fayda ve bedelini ayırdık: ilk hedefi yaklaştırmak bazı zararlardan gelir çıkarıyor, erken stop bazı kayıpları azaltıyor; ikisi de sonraki büyük hareketleri kaçırabiliyor. Bu kural ailesinden henüz kârlı ve bağımsız doğrulamaya hazır bir aday çıkmadı. Bunu bütün projenin imkânsızlığına genellemiyoruz.

Bundan sonraki daha anlamlı araştırma, aynı aylık geçmişte yeni stop katsayıları seçmek yerine temel giriş fikrinin daha uzun, ayrı broker verisinde maliyet öncesi avantajını ölçmek olur. Bu, kazanacağı varsayımıyla yapılan bir terfi değil, sistemin hangi koşullarda işe yarayabildiğine dair kapsamı genişleten bir tanı olmalıdır. Veri kapsamı ve maliyet eksikleri ayrıca görünür kalmalıdır.

## Sınırlar ve doğrulama

Bu yaklaşık bir aylık dönem önceden görülmüştür; çalışma OOS veya ileri kanıt değildir. Örnek az sayıda takvim haftası içerir; güven aralıkları tanımsız bırakıldı ve çoklu araştırma seçimi düzeltilmiş değildir. Tam net alanları boş kalır. Yeni, görülmemiş veri bu sonucu kurtarmak için tüketilmedi.

Üretim dosyaları, çalışan gözlemciler, gerçek emirler ve bildirimler değiştirilmedi. Araştırma adaptörü yalnız kendi sürecinde kullanıldı.

```powershell
python scripts/run_early_be_study.py --baseline reports/broker_measurement_v2_2026-10-24 --previous-study reports/near_tp1_1r_2026-10-24 --output reports/early_be_YENI_DIZIN
python -m pytest -q
```

- Protokol SHA256: `17b2f3ec14b6de3a63f89046ac9fcfbe37261e3cc5a85810d8e33113b447ef0d`.
- 56 girdi ve dondurulmuş kopyasının hashleri doğrulandı; karar çekirdeğinin sekiz dosyası özgün sürümle byte düzeyinde aynı.
- Özgün 64 çıkış yeniden üretildi; aynı girişlerde TP1/TP2/ilk stop/giriş fiyatının değişmediği doğrulandı.
- Tam tekrardaki 65 giriş ayrıca kapalı-geçmiş karar değerlendiricisiyle, özgün seviyeler ve sonraki dakika maliyetli dolumuyla doğrulandı.
- Aynı giriş ve tam tekrar popülasyonlarındaki 44 aktivasyon olayının fiyat/zaman koşulları kontrol edildi; 22 erken stop çıkışının maliyet ve kötü açılış hesabı bağımsız formülle doğrulandı. Bunlar iki popülasyon arasında tekrar içeren kontrol sayılarıdır, 44 bağımsız canlı işlem değildir.
- 220 test ve 50 alt test geçti. Derleme ve `git diff --check` başarılı; eski shadow testinde yalnız satır sonu uyarısı var.
- Yeni testler erken kısmi çıkış olmamasını, hedeflerin korunmasını, eski stop önceliğini, aktivasyon mumu belirsizliğini, masraflı başabaş çıkışını, sonraki kötü açılışı ve LONG/SHORT simetrisini kapsıyor.

Çıktılar: [karar](early_be_1r_2026-10-24/decision.json), [protokol](early_be_1r_2026-10-24/protocol_frozen.json), [özet](early_be_1r_2026-10-24/summary.json), [64 işlem eşlemesi](early_be_1r_2026-10-24/paired_trades.json), [doğrulama](early_be_1r_2026-10-24/verification.json).
