# Pragma: ilk kâr hedefini 1R'ye yaklaştırma — 24 Ekim 2026

## Karar

Tek bir yeni çıkış kuralı test edildi. İki ayrı hedefli işlemlerde ilk hedefin girişe uzaklığı en fazla 1 başlangıç riski (1R) olarak sınırlandı; pozisyonun yarısı orada kapandı ve mevcut başabaş kuralı o anda devreye girdi. Sonuç genel bir çözüm sunmadı: aynı girişlerde 6 sembol iyileşti, 5'i kötüleşti, 2'si değişmedi. Bütün dönemin yeniden oynatılmasında 13 sembolün 10'u eski maliyet senaryosunda negatif kaldı. Üretime eklenmedi.

## Neyi değiştirdik?

Gerekçe, bazı işlemlerde fiyatın önce doğru yönde ilerleyip ilk kâr hedefine ulaşamadan geri dönmesiydi. Testin sonucundan önce 1R sabitlendi; farklı R katsayıları taranmadı.

- Yalnız özgün TP1 ve TP2'si farklı olan işlemlerde TP1 mesafesi `min(eski mesafe, başlangıç riski)` oldu. LONG için giriş + mesafe, SHORT için giriş - mesafe.
- Risk, sonraki dakika maliyetli açılışında oluşan gerçek simülasyon giriş fiyatıyla özgün ilk stop arasından hesaplandı. O mumun ileride oluşacak tepe/dibi kullanılmadı.
- İlk hedef zaten daha yakınsa uzağa taşınmadı. Tek hedefli işlemler korunarak onlara yeni bir yarım çıkış eklenmedi.
- İlk stop, TP2, yarım çıkış oranı, başabaş ofseti, giriş koşulları, seans ve maliyetler aynı kaldı. Önceki reddedilen giriş filtreleriyle birleştirilmedi.
- Başabaş **kuralı** değişmedi ama erken TP1 nedeniyle daha erken tetiklenebildi. Sonuç, bu mekanik sonucu da içeren politikaya aittir; kısmi çıkış ve başabaş etkileri bağımsız ölçülmüş değildir.
- Özgün sinyalin RR uygunluğu özgün hedeflerden değerlendirildi; yakın TP1 yalnız dolumdan sonraki yönetim aşamasında uygulandı. Yeni hedefe göre giriş kapısı yeniden ayarlanmadı. Bu, çıkış etkisini ayıran araştırma kuralıdır; üretim için yeni bir RR uygunluk onayı değildir.

## Aynı girişler ve bütün dönem ayrı ölçüldü

Önce özgün 64 girişin çıkışları yeniden üretilerek önceki sonuçla eşitliği doğrulandı. Bu 64 işlemin 45'i iki hedefli, 19'u tek hedefliydi. Yeni kuralda 45 ilk hedef değişti; 19 tek hedefli işlemin seviyeleri, çıkış zamanı, nedeni ve getirisi değişmedi. Bütün 64 eşlemede kapanmış sonuç var; eksik veya dönem sonunda açık eşleme yok.

Sonra aynı özgün aday akışı, yeni çıkış yönetimi ve pozisyon doluluğuyla baştan oynatıldı. EURUSD'de erken kapanmanın açılabilir hale getirdiği bir ek işlem oluştu; toplam 65 kapanmış işlem var. Dolayısıyla yalnız eski işlemlerden iyi görünenler seçilmedi.

**Aşağıdaki R getirileri, önceki sabit spread + yön başına 1 bps komisyon + 0,5 bps kayma varsayımına aittir. Bunlar gerçek broker net getirisi değildir. Bazı komisyon varsayımlarının yüksek olduğu önceki hesap örneklerinde görüldü; swap ve tam kayma kalibrasyonu eksik. Maliyetler bu tek çıkış değişikliğini ayırmak için iki kolda sabit tutuldu.**

| Sembol | Özgün işlem | Özgün senaryo R | Aynı girişlerde yeni R | Tam test işlem | Tam test yeni R |
|---|---:|---:|---:|---:|---:|
| XAUUSD | 5 | +5,340 | +0,306 | 5 | +0,306 |
| EURUSD | 8 | -7,085 | -5,633 | 9 | -6,769 |
| GBPUSD | 7 | -5,789 | -4,291 | 7 | -4,291 |
| USDJPY | 7 | -4,487 | -3,417 | 7 | -3,417 |
| USDCHF | 7 | -1,209 | +0,045 | 7 | +0,045 |
| AUDUSD | 3 | -3,376 | -3,376 | 3 | -3,376 |
| NZDUSD | 6 | -2,941 | -0,092 | 6 | -0,092 |
| USDCAD | 3 | -1,923 | -2,038 | 3 | -2,038 |
| CADCHF | 4 | -0,226 | -0,226 | 4 | -0,226 |
| CADJPY | 4 | -4,617 | -3,594 | 4 | -3,594 |
| EURGBP | 3 | +3,785 | +3,680 | 3 | +3,680 |
| GBPCHF | 4 | -3,338 | -3,413 | 4 | -3,413 |
| GBPJPY | 3 | -0,221 | -2,166 | 3 | -2,166 |

Aynı girişlerde önceki 45 zararlı işlemin 7'si pozitife döndü. Buna karşılık önceki 19 kazançlı işlemin 14'ünün getirisi küçüldü. Sadece kazanma sayısına bakmak bu kaybı gizler. Örneğin XAUUSD'nin aynı beş işlemindeki toplam senaryo getirisi +5,340R'den +0,306R'ye indi. Bu örnekte yakın hedef, büyük kazançları önemli ölçüde kesti.

USDCHF, aynı yedi işlemde -1,209R'den yaklaşık +0,045R'ye geçti; bu küçük pozitif sonuç edge kanıtı değildir. Tam testte pozitif üç sembol XAUUSD, USDCHF ve EURGBP; diğer on sembol negatif. Korelasyonlu sembollerin R toplamı portföy getirisi diye sunulmadı. Ayrıntılı işlem başına ölçümler JSON özetinde bulunuyor.

## Sınırlar ve karar

Bu yaklaşık bir aylık geçmiş daha önce incelenmiştir; OOS veya yeni ileri kanıt değildir. Örnek küçük ve maliyetler tamamen gözlenmiş değildir. Güven aralıkları için yeterli takvim haftası yok; tek bir olumlu sembol seçilip başarı ilan edilmedi.

Bu 1R hedef kuralı genel üretim davranışına eklenmeyecek. Daha küçük kazançları daha sık almak bazı kayıpları kurtardı, fakat kazançlı işlemlerdeki kesintiyle birlikte istenen genel sonucu vermedi. Yeni bağımsız veri bu karışık sonucu kurtarmak için kullanılmadı. Aynı geçmişte 0,5R/0,75R/1,5R vb. taranıp en iyisi seçilmedi.

Üretim dosyaları ve çalışan gözlemcilerin kodu değiştirilmedi; gerçek emir veya bildirim gönderilmedi. Araştırma adaptörü yalnız kendi sürecinde, dolumdan sonra ve mum yönetiminden önce TP1'i bir kez atıyor; diğer yönetim kuralları özgün motor tarafından uygulanıyor. Stop-hedef aynı mumda görünürse mevcut stop önceliği, kısmi çıkış sonrası belirsizlikte mevcut başabaş önceliği korunuyor.

## Doğrulama ve tekrar üretim

```powershell
python scripts/run_near_tp1_study.py --baseline reports/broker_measurement_v2_2026-10-24 --output reports/near_tp1_YENI_DIZIN
python -m pytest -q
```

- Protokol SHA256: `6cbd162736c896a24ac6a274da77e0d99426ae907ac43496efc9cb7016b99c7b`.
- 54 girdi ve dondurulmuş kopyası hash ile doğrulandı. Giriş/karar/çıkış çekirdeğindeki sekiz dosya ayrıca özgün baseline sürümüyle byte düzeyinde aynı.
- Özgün 64 işlemin çıkış getirisi, zamanı ve nedeni yeniden üretildi; 64 eşlemenin yeni hedef geometrisi bağımsız formülle kontrol edildi.
- Yeni tam testteki 65 giriş, kapanmış geçmiş değerlendiricisiyle ayrıca doğrulandı: özgün giriş uygunluğu, stop, TP2, sonraki dakika maliyetli dolumu ve dolumdan hesaplanan yeni TP1.
- 19 tek hedefli işlemde sonuçların bütünüyle değişmediği kontrol edildi.
- 210 test ve 50 alt test geçti. Derleme ve `git diff --check` başarılı; eski shadow testinde yalnız satır sonu uyarısı mevcut.
- Yeni testler LONG/SHORT simetrisini, tek hedeflerin korunmasını, stop önceliğini, kısmi pozisyon maliyetini, mevcut başabaş önceliğini ve hedefin dolum başına tek kez atanmasını kapsıyor.

Çıktılar: [karar](near_tp1_1r_2026-10-24/decision.json), [protokol](near_tp1_1r_2026-10-24/protocol_frozen.json), [özet](near_tp1_1r_2026-10-24/summary.json), [64 işlem eşlemesi](near_tp1_1r_2026-10-24/paired_trades.json), [doğrulama](near_tp1_1r_2026-10-24/verification.json).
