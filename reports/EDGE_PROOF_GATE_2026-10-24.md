# Pragma edge doğrulama kapıları — 24 Ekim 2026

Amaç geçmişte güzel görünen bir sonucu tekrarlamak değil, gelecekte uygulanabilir net bir avantaj olup olmadığını ölçmek.

## Sabit kapılar

1. **Kural dondurma:** Giriş, stop, hedef, pozisyon boyutu ve sembol evreni ileri gözlem sırasında değişmeyecek.
2. **Gerçek zaman sırası:** İleri dönem verisi karar anından sonra toplanacak; geçmiş veriyle geriye dönük seçim yapılmayacak.
3. **Gerçek maliyet:** Spread, komisyon, kayma ve swap ayrı ayrı kaydedilecek. Maliyet bilinmiyorsa işlem net sonuç hesabından çıkarılacak.
4. **Yeterli örnek:** En az 8 takvim haftası ve en az 50 kapanmış işlem görülmeden sembol veya sistem hakkında olumlu karar verilmeyecek.
5. **Net sonuç:** Sonuç maliyetlerden sonra işlem başına beklenti olarak pozitif olmalı; toplam kâr tek başına yeterli değil.
6. **Belirsizlik:** Haftalık kümelenmiş güven aralığının alt sınırı sıfırın üstünde olmalı. Aralık sıfırı kapsıyorsa sonuç “umut verici ama kanıtlanmadı” kalır.
7. **Karşılaştırma:** Aynı dönem ve sembol evreninde sabit basit karşılaştırıcıya karşı avantaj gösterilmeli.
8. **Canlıya geçiş:** Tüm kapılar geçilmeden üretim kuralı ve gerçek emir davranışı değiştirilmeyecek; önce gözlem/paper aşaması tamamlanacak.

## Mevcut durum

FX ileri gözlemcisi ve Binance gözlemcisi çalışıyor, fakat 24 Ekim 2026 itibarıyla piyasa kapalı olduğu için yeni taze gözlem yok. Bu bekleme durumu başarı veya başarısızlık değildir.

Altının iki geçmiş dönemdeki toplam 16 işlemlik olumlu sonucu bu kapıları karşılamıyor. Bu nedenle altın için canlıya geçiş kararı yok; yalnızca izlenecek hipotez olarak tutuluyor.

## Karar dili

- Tüm kapılar geçerse: “Bu örneklem ve maliyet tanımı altında ileri dönemde pozitif edge kanıtı var.”
- Bazı kapılar geçip güven aralığı sıfırı kapsarsa: “İpucu var, edge kanıtlanmadı.”
- Maliyet sonrası sonuç negatifse veya örnek yetersizse: “Mevcut kanıtlarla uygun değil.”

Bu süreç kazanç garantisi vermez; amacı yanlış bir kesinlik iddiasını engellemektir.
