# Pragma edge incelemesi — 23 Ekim 2026

## Karar

Mevcut kanıtlarla maliyet sonrası, tekrarlanabilir edge kanıtlanmadı. Maliyetli kripto sonuçları çoğunlukla negatif; yıllık FX/altın sonuçlarının veri ve ölçüm kusurları var. Pozitif alt gruplar yalnız araştırma adayıdır.

Bu inceleme mevcut JSON sonuçlarının yeniden hesaplanması, güncel kaynak kodunun okunması, yerel shadow state/journal kontrolü ve test çalıştırmasıdır. Tarihsel strateji replay'i yeniden çalıştırılmadı. Eski sonuçların güncel kod sürümüyle üretildiği doğrulanmadı. Input manifesti bugünkü dosyaları sabitler; eski sonuçlara geriye dönük sürüm güvencesi sağlamaz. Çalışan süreç veya strateji kodu değiştirilmedi.

## Sonuç kanıtı

2025 filtresiz yıllık sonuç: 13 sembol, 1.331 işlem, toplam +36,0755R; işlem başına +0,02710R. Bu, sembol sonuçlarının aritmetik toplamıdır; eşzamanlı risk ve korelasyon içeren portföy getirisi değildir. Spread sıfırdır. Bu kayıtlardaki ortalama brüt avantaj, sabit işlemler varsayımında işlem başına 0,0271R ek maliyetle silinir; bu bir maliyetli yeniden test değildir.

Yıllık EURUSD: 83 işlem, +22,4471R, PF 1,5102; XAUUSD: 186 işlem, -8,2923R. Her ikisinde spread sıfırdır. Farklı dönem/sürümdeki batch 3_ay grubunda 15 sembolün aritmetik toplamı 290 işlem ve -60,8330R'dir. Aynı stratejinin kontrollü OOS karşılaştırması olarak yorumlanamaz.

FAZ13, 22 Mart–16 Ekim 2026, tam 300k M1 örnek:

| Sembol | TF | İşlem | R | PF |
|---|---|---:|---:|---:|
| SOLUSDT | M5 | 33 | -15,2670 | 0,4700 |
| SOLUSDT | M15 | 33 | -18,0270 | 0,4319 |
| LINKUSDT | M5 | 20 | -7,4760 | 0,5496 |
| LINKUSDT | M15 | 20 | -11,6349 | 0,3610 |
| BTCUSDT | M15 | 28 | +1,9033 | 1,0967 |

Rapordaki varsayım: yön başına 4 bps ve sekiz saatte sabit %0,01 funding. Bunlar ölçülmüş gerçek fill/funding değildir. BTC ortalaması +0,068R; raporun basit normal yaklaşım aralığı [-0,5503; +0,6862]R. Pozitif beklenti kanıtı yoktur; küçük örnek, bağımlılık ve çoklu seçim bu aralığı daha da sınırlı kılar. Aynı sembolün M5/M15 işlemleri bağımsız portföy örnekleri sayılamaz. Raporun STABILIZED etiketi SOL M5/M15 kayıp ve drawdown artışını başarıya dönüştürmez.

Yerel shadow state ve journal: 4 kapanmış işlem, 0 açık pozisyon; state toplamı -1,025834R. Girişler 19 Ekim, son çıkış 20 Ekim 2026 UTC. Journal toplamı yuvarlama ile -1,02583R. Bu sanal sonuçlar, bağımsız ileri veri veya broker fill doğrulaması değildir. Az işlemden strateji reddi veya kabulü çıkarılamaz.

## Ölçümü geçersizleştiren veya sınırlayan bulgular

1. `pragma/one_year_backtest.py:47`: tick_volume = max(1, round((high-low)/point_size)). Bu gerçek hacim değildir. VWAP, profil ve volume-climax böylece mum genişliği ağırlığıyla test edilmiş olur; gerçek broker tick-volume stratejisinin doğrulaması sayılamaz.
2. Aynı dosya:44, HistData saatini doğrudan utc=True ile okuyor. Kaynak EST, yaz saati uygulanmayan UTC-5 kullanır. Önce sabit UTC-5 lokalizasyonu, sonra UTC dönüşümü gerekir. Seans profili ve saat filtresi etkilenir; eski parquet önbelleklerinin kökeni ayrıca denetlenmelidir. Kaynak: https://www.histdata.com/f-a-q/
3. Aynı dosya:64, MacroGate.get_bias bir kez çağrılıp bütün geçmişe uygulanıyor. Olay zamanında yayımlanmış ve o anda erişilebilir makro yön dizisi yok; makro katkısı ölçülmüş değildir.
4. `backtest_engine.py:635` tetik için yalnız sabit cost kullanırken gerçek girişe yüzde maliyet de ekliyor (:670). `run_pipeline.py:216` Binance yüzde maliyetini tetik filtresine veriyor. Aynı maliyetli aday sözleşmesi yok.
5. `run_pipeline.py:271` yalnız son trigger mumunun bölgeye değmesini şart koşuyor; backtest evaluate_trigger üzerinden son üç mumdaki teması kullanıyor. `run_pipeline.py:225` generate_regime_pois çağrısına is_crypto/is_btc geçirmiyor; backtest :620 geçiriyor. Kripto rejim eşikleri farklı çalışabilir. Sinyal parity'si kanıtlanmadan backtest çalışan hattın sonucu sayılamaz.
6. Shadow varsayılan spread=0. _realize çıkışı hedef/stop fiyatından hesaplıyor; komisyon, funding ve ayrı çıkış kayması düşümü yok. Spread parametresi tek başına tam maliyet muhasebesi sağlamaz.
7. Backtest girişte kapanış fiyatını varsayıyor ve entry_time için mum açılış zamanını kaydediyor (:681); karar anı bir dakika sonradır. Fill gecikmesi/funding sınırı ve yeniden oynatma için open_time, decision_time ve fill_time ayrı tutulmalı.

Olumlu altyapı: kapanmış mum kullanımı, önceki seans profili, nedensel VWAP ve aynı mum belirsizliğinde stop önceliği mevcut. Bunlar edge değil, ölçümün ön koşullarıdır.

## Öncelikli çalışma ve deney protokolü

A. Ölçümü düzelt: ortak backtest/forward karar fonksiyonu; aynı geçmiş öneki için POI, rejim, aday, ret nedeni ve zaman eşitliği. Üretim davranışı değişmeden önce observer modunda fark kaydı. Gerçek hacim gerektiren testte gerçek hacim kullan; yoksa sonucu volume stratejisi olarak etiketleme. EST/UTC ve broker saatini doğrula. Makro için vintage arşivi yoksa katkıyı ölçülemez olarak ayır.

B. Sembol ve seans bazında bid/ask, komisyon, swap/funding, kayma ve karar-fill gecikmesini kaydet. Ölçülmüş normal maliyet ile 1,5x stres maliyetini ayrı çalıştır. Eksik maliyeti sıfır kârlı kanıt sayma. Entry/exit muhasebesini ortaklaştır.

C. Önceden yazılmış üç araştırma hipotezi, her biri aynı dondurulmuş baseline'a karşı tek değişken:
- Giriş: son üç mum temas kuralını, son mum teması ve teyit sonrası ilk erişilebilir fill ile karşılaştır. Aynı teyit sonrası 5/15/30 dakika yönlü getiri, MAE/MFE ve zaman/seans eşlenmiş basit baseline ölç. Fiyat avantajı maliyetten önce bile yoksa çıkış ayarıyla kurtarmaya çalışma.
- TP1/BE: mevcut %50 TP1 + BE politikasına karşı yalnız BE geçişini kaldır; giriş ve hedefleri sabit tut. TP1 sonrası MFE/MAE ile erken BE maliyetini incele. Ayrı bir aşamada partial oranı hipotezi düşünülebilir; aynı deneyde birleştirme.
- Maliyet/seans: önceden sabitlenmiş spread/stop eşiği veya seans kuralını tek tek test et. Reddedilen adayların karşı-olgusal sonuçlarını da ölç; yalnız işlem azalması başarı değildir.

D. Bütün denenmiş konfigürasyonları kaydet; daha önce incelenmiş 2025 ve Mart–Ekim 2026 örneklerini keşif verisi say. Başarılı sembolü sonradan seçip OOS diye sunma. Veri/kod/config SHA256, piyasa evreni, maliyetler ve karar kriterlerini denemeden önce dondur. Eski sonuçları koru. Yeni ve ayrılmış dönemlerde kronolojik test; ardından gerçek zamanda shadow kayıt.

E. Araştırma kabul ölçütü önerisi: yeterli takvim ve rejim kapsamı, net expectancy > 0, önceden belirlenmiş drawdown sınırı, 1,5x maliyette dayanıklılık; hafta bazında blok bootstrap ve çoklu deneme hesabıyla belirsizlik. 100 işlem tek başına ispat eşiği değildir. Portföyde eşzamanlı USD/risk kümeleri ve toplam tahsis riski ayrıca ölçülmeli. Bunlar bu incelemede sağlanmış koşullar değildir.

## Doğrulama

`python -m unittest discover -s tests -q`: 136 test, OK. Bu sonuç yazılım kontrolleridir; strateji kârlılık testi değildir. Mevcut çalışma ağacındaki kullanıcı değişiklikleri korundu.

Çok sinyalli strateji seçiminin overfit riski için birincil araştırma: Robert Novy-Marx, Backtesting Strategies Based on Multiple Signals, https://www.nber.org/papers/w21329 .
