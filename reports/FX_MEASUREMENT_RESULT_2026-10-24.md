> Güncelleme: gerçek tick spreadi ve hesap ücret örnekleriyle giriş hipotezleri ayrıca incelendi. Önceki maliyet varsayımını broker-net saymayın. Yeni çalışma: [ENTRY_COST_RESULT_2026-10-24.md](ENTRY_COST_RESULT_2026-10-24.md).

# FX/altın ölçüm testi — 24 Ekim 2026

## Sonuç

Önceki yetkilendirme engeli aşıldı. 13 sembolün tamamında M5 araştırması tamamlandı; veri/kod hashleri doğrulandı. Toplam 64 kapanmış temel işlem var. XAUUSD ve EURGBP pozitif, kalan 11 sembol negatif. Örnek yaklaşık bir ay; pozitif sembollerde 5 ve 3 işlem bulunduğundan edge kanıtı yok.

## FX testi önce neden tamamlanmamıştı?

Otomatik MT5 initialize çağrısı Authorization failed döndürüyordu. Bilgisayarda hem genel MetaTrader 5 hem Five Percent Online MetaTrader 5 terminali çalışıyor. Five Percent terminalinin executable yolunu açıkça verince bağlantı ve bütün geçmiş veri çağrıları başarılı oldu. Önceki aşamada bu ayrımın kontrolü eksik kalmıştı. Hesap değiştirilmedi, şifre istenmedi, emir gönderilmedi.

Araştırma komutuna --terminal-path eklendi; belirtilen terminal başarısızsa başka kuruluma sessiz geçiş yapılmıyor. Hafta sonu tarihi testini güncel FX kotasyonuna bağımlı bırakmamak için --quote-archive ile açıkça belirtilmiş eski kotasyon yalnız maliyet senaryosunda kullanılabiliyor. Canlı fiyat tazeliği kontrolü gevşetilmedi.

## Veri ve maliyet kapsamı

- Her sembolde 30.000 gerçek broker tick-volume M1 mumu. XAUUSD başlangıcı 23 Eylül 2026; FX başlangıçları 24 Eylül; bitiş 23 Ekim 2026 UTC.
- Mevcut bar-clock düzeltmesi taze BTC heartbeat ile her alımda doğrulandı: raporlanan epoch farkı +10.800 saniye. Geçmişin saat eşlemesi bağımsız olarak bütün dönem için tekrar doğrulanmış değildir.
- Kaynak bid OHLC, 23 Ekim’de kaydedilmiş sembol spreadinin yarısı ile varsayımsal mid serisine çevrildi. Bu geçmiş spread serisinin ölçümü değildir.
- Her yönde varsayımsal 1 bps komisyon + 0,5 bps kayma, ayrıca ilan edilmiş half-spread maliyeti. Swap verisi yok. Sonuçlar gerçek broker net kârı yerine maliyet senaryosu R değerleridir.
- Makro: nedensel fiyat rejimi auto; bugünkü Begonya makrosu geçmişe uygulanmadı. Bu koşu tarihsel makro katkısını ölçmez.
- Tarihsel örnek keşif amaçlıdır; gerçek zamanlı OOS veya broker fill eşitliği değildir.

## Önceden belirlenmiş karşılaştırmalar

| Sembol | İşlem | Temel R | Son mum teması R | 1,5x maliyet R | BE kaldırma farkı R |
|---|---:|---:|---:|---:|---:|
| XAUUSD | 5 | +5.34 | +5.34 | +5.78 | -0.50 |
| EURUSD | 8 | -7.09 | -7.09 | -8.67 | +0.00 |
| GBPUSD | 7 | -5.79 | -4.70 | -6.29 | +0.00 |
| USDJPY | 7 | -4.49 | -4.49 | -2.52 | +0.00 |
| USDCHF | 7 | -1.21 | -1.21 | -2.14 | -0.50 |
| AUDUSD | 3 | -3.38 | -3.38 | -3.53 | +0.00 |
| NZDUSD | 6 | -2.94 | -2.94 | -3.82 | -0.50 |
| USDCAD | 3 | -1.92 | -1.92 | -2.21 | +1.71 |
| CADCHF | 4 | -0.23 | -0.23 | -0.41 | +0.00 |
| CADJPY | 4 | -4.62 | -4.62 | -4.84 | +0.00 |
| EURGBP | 3 | +3.78 | +3.78 | +0.00 | -0.50 |
| GBPCHF | 4 | -3.34 | -3.70 | -3.87 | -0.50 |
| GBPJPY | 3 | -0.22 | -0.22 | -1.23 | +0.00 |

1,5x senaryosu adayları ve işlem sayısını değiştirebilir; daha az zarar tek başına maliyet dayanıklılığı/edge değildir. EURGBP stresinde sıfır işlem var: 0R başarı sayılmadı. XAUUSD stresinde 4 işlem kaldı; sonucun artması aynı işlemlerin maliyete dayanıklılığını kanıtlamaz.

BE farkları aynı temel giriş ve hedeflerde yalnız TP1 sonrası stopu başabaşa taşıma kaldırılarak hesaplandı. USDCAD +1,71R iyileşiyor fakat yalnız 3 işlem var; genel politika değişikliği için yeterli değil. Diğer sembollerde sonuç değişmiyor veya kötüleşiyor. Son mum teması değişikliği de tutarlı bir iyileştirme sunmuyor.

Az takvim kapsamı nedeniyle hafta bootstrap güven aralığı üretilmedi; yokluğu pozitif güven veya başarı değildir. Semboller ortak USD/korelasyon riski taşır; R toplamı birleşik portföy getirisi değildir. Drawdown kapanmış işlem bakiyesine dayanır ve floating intraday drawdown değildir.

## Maliyet mi, giriş mi?

Deney bittikten sonra yalnız maliyet ayrıştırması yapıldı. Aynı giriş/çıkış yolu, risk paydası ve BE seviyeleri korunarak model maliyetleri geri eklendi. Bu, maliyetsiz stratejinin yeniden backtesti değildir ve yeni parametre seçimi için kullanılmadı.

| Sembol | Sabit işlem yolunda maliyet geri eklenmiş R | Model maliyet yükü R | Senaryo R |
|---|---:|---:|---:|
| XAUUSD | +6.73 | 1.39 | +5.34 |
| EURUSD | -4.38 | 2.71 | -7.09 |
| GBPUSD | -3.55 | 2.24 | -5.79 |
| USDJPY | -2.20 | 2.28 | -4.49 |
| USDCHF | +0.92 | 2.12 | -1.21 |
| AUDUSD | -2.62 | 0.75 | -3.38 |
| NZDUSD | -1.28 | 1.66 | -2.94 |
| USDCAD | -0.85 | 1.08 | -1.92 |
| CADCHF | +1.87 | 2.09 | -0.23 |
| CADJPY | -3.47 | 1.14 | -4.62 |
| EURGBP | +5.72 | 1.93 | +3.78 |
| GBPCHF | -1.51 | 1.82 | -3.34 |
| GBPJPY | +1.11 | 1.33 | -0.22 |

Sekiz sembol maliyet geri eklendiğinde de negatif kalıyor. USDCHF, CADCHF ve GBPJPY bu sabit işlem yolu ayrıştırmasında maliyet eşiğine takılıyor. Bu ayrım, giriş kalitesi ile maliyet kalibrasyonunu ayrı ele almamız gerektiğini gösteriyor; ücretleri kâr lehine azaltma gerekçesi değildir.

Ayrıca 5/15/30 dakika gross/net bps, aynı saatte önceki hafta referansı ve reddedilen aday karşı-olguları saklandı. XAUUSD dışında 5 ve 15 dakikalık net senaryo ortalamaları negatif; CADCHF/EURGBP 30 dakika ortalaması pozitif olsa da küçük, bağımlı, seçilmiş tarihsel örnekten yeni ufuk optimizasyonu yapılmadı.

Ham MT5 bar-spread alanlarının kapsamı ayrıca reported_bar_spread_diagnostics.json dosyasına kaydedildi. Bu alanlar tick fill spreadi olarak etiketlenmedi ve dondurulmuş sabit-spread senaryosu sonradan değiştirilmedi.

## Şimdi alınacak karar

1. Genel bir TP/SL veya son-mum filtresi değişikliği benimsenmedi. Mevcut canlı/shadow karar davranışı korunuyor; araştırma çıktıları ayrı.
2. Pozitif görünen XAUUSD ve EURGBP araştırma adayları; 5/3 işlemden piyasa seçip üretime geçilmiyor. Yeni zamanda bütün ilan edilmiş evrenin kabul/ret adayları birlikte izlenmeli.
3. FX giriş kalitesi, aynı 5/15/30 dakika tanımı ve maliyet öncesi avantajla değerlendirilmelidir. Özellikle maliyet geri eklendiğinde de negatif kalan girişlerde TP/SL ayarı öncelik olmayacak.
4. Eksik komisyon, gerçek kayma, swap ve tarihsel spread kalibrasyonu tamamlanmadan net edge iddiası kurulmayacak. Yeni giriş hipotezi, bu tanıdan sonra ayrı protokolde önceden sabitlenecek; bu örnek yeniden OOS diye kullanılmayacak.

## Doğrulama ve dosyalar

- Çalışma durumu: COMPLETE; başarısız sembol yok. Protokol SHA256: f975938e6d9e2269c0f575dae20292f1e4a084882f9245a38a62e6781e7eb03f.
- Tamamlanmış temel girişlerin 64/64 tanesinde pointwise karar/yön/POI/stop/TP/giriş maliyeti/zaman eşitliği doğrulandı.
- Bütün temel işlemlerde eşlenmiş çıkış replay’i ilk koşuyla aynı sonucu verdi.
- 159 test geçti; compileall ve git diff --check başarılı. Bağlantı seçimi, kapalı piyasa arşiv etiketi, kısmi çıkış maliyeti ve gap maliyeti regresyonları dahil.
- Eski yetkilendirme hatası kaydı ve önceki sonuçlar korundu. Broker emri, hesap değişimi, terminal kapatma veya strateji terfisi yapılmadı. Yalnız bu araştırma sürecinin MT5 IPC bağlantısı açılıp kapatıldı.

Çıktı klasörü: [broker_measurement_v2_2026-10-24](broker_measurement_v2_2026-10-24). Ana sayısal sonuç: [summary.json](broker_measurement_v2_2026-10-24/summary.json).

Yeniden çalıştırma (yeni/boş bir çıktı klasörü gerekir):

```powershell
python scripts/run_broker_measurement_research.py --output reports/new_fx_run --bars 30000 --terminal-path "C:\Program Files\Five Percent Online MetaTrader 5\terminal64.exe" --quote-archive reports/forward_observer_mt5_2026-10-23/quotes.jsonl
```
